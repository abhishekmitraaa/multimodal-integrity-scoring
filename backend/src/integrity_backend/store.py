"""PostgreSQL persistence for participants, sessions and the hash-chained event log (SPEC 5)."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from .chain import ChainRecord, StoredLink, extend, genesis
from .crypto import FieldCipher, event_aad
from .ingest import SessionState, plan_batch
from .wire import WireError

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def now_us() -> int:
    return time.time_ns() // 1000


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def sha256(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def _dumps(data: dict[str, Any]) -> bytes:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8", "surrogatepass")


def _loads(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw.decode("utf-8", "surrogatepass"))
    assert isinstance(value, dict)
    return value


@dataclass(frozen=True)
class AppendResult:
    next_client_seq: int
    stored: int
    resend_from: int | None = None


@dataclass(frozen=True)
class SessionRow:
    session_id: str
    pseudonym: str
    kind: str
    problem_id: str
    closed: bool
    epoch: int


# Actor names the system writes itself; a staff account cannot take them (D-044).
RESERVED_HANDLES = frozenset({"admin", "reviewer-1", "participant", "retention-job", "admin-cli"})


class SessionLimitError(Exception):
    """The participant already has the one session allowed for this problem."""


class Store:
    def __init__(self, engine: AsyncEngine, cipher: FieldCipher, pseudonym_prefixes: dict[str, str]) -> None:
        self.engine = engine
        self.cipher = cipher
        self.prefixes = pseudonym_prefixes

    # ---- participants and sessions -------------------------------------------------------

    async def create_participant(self, kind: str, consent: dict[str, Any],
                                 study_plan: Callable[[int], Sequence[tuple[int, str, str]]] | None = None) -> tuple[str, str]:
        """With study_plan, the participant joins the study protocol (D-046): their sitting-2 plan is
        study_plan(row), row = how many study participants exist (Latin-square rows in turn)."""
        pseudonym = self.prefixes[kind] + "".join(secrets.choice(CROCKFORD) for _ in range(8))
        token = secrets.token_urlsafe(32)
        async with self.engine.begin() as conn:
            row = None
            if study_plan is not None:
                await conn.execute(text("LOCK TABLE study_assignments IN SHARE ROW EXCLUSIVE MODE"))   # rows in turn
                row = (await conn.execute(text("SELECT count(*) AS n FROM participants WHERE study_protocol"))).one().n
            await conn.execute(
                text("INSERT INTO participants (pseudonym, kind, token_sha256, study_protocol) VALUES (:p, :k, :t, :s)"),
                {"p": pseudonym, "k": kind, "t": sha256(token), "s": study_plan is not None},
            )
            if study_plan is not None:
                for slot, problem_id, condition in study_plan(int(row)):
                    await conn.execute(text("INSERT INTO study_assignments (pseudonym, slot, problem_id, condition) "
                                            "VALUES (:p, :s, :pr, :c)"),
                                       {"p": pseudonym, "s": slot, "pr": problem_id, "c": condition})
            await conn.execute(
                text(
                    "INSERT INTO consent_records (pseudonym, notice_version, notice_sha256, choices) "
                    "VALUES (:p, :v, :h, CAST(:c AS jsonb))"
                ),
                {"p": pseudonym, "v": consent["notice_version"], "h": consent["notice_sha256"], "c": json.dumps(consent["choices"])},
            )
        return pseudonym, token

    async def participant_by_token(self, token: str) -> str | None:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT pseudonym FROM participants WHERE token_sha256 = :t AND withdrawn_at IS NULL"),
                    {"t": sha256(token)},
                )
            ).first()
        return None if row is None else str(row.pseudonym)

    # ---- study protocol (D-046) -------------------------------------------------------------

    async def participant_info(self, pseudonym: str) -> dict[str, Any] | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(text("SELECT kind, study_protocol FROM participants WHERE pseudonym = :p"),
                                      {"p": pseudonym})).first()
        return None if row is None else {"kind": row.kind, "study_protocol": bool(row.study_protocol)}

    async def study_plan(self, pseudonym: str) -> list[dict[str, Any]]:
        """Slots with their session (if any) and whether it is submitted. Scripted sessions are not slots."""
        async with self.engine.connect() as conn:
            rows = (await conn.execute(text(
                "SELECT a.slot, a.problem_id, a.condition, s.session_id, s.closed_at "
                "FROM study_assignments a LEFT JOIN sessions s ON s.pseudonym = a.pseudonym AND s.problem_id = a.problem_id "
                "AND NOT EXISTS (SELECT 1 FROM study_labels l WHERE l.session_id = s.session_id AND l.scripted) "
                "WHERE a.pseudonym = :p ORDER BY a.slot"), {"p": pseudonym})).all()
        return [{"slot": r.slot, "problem_id": r.problem_id, "condition": r.condition,
                 "session_id": str(r.session_id) if r.session_id else None, "done": r.closed_at is not None} for r in rows]

    async def first_practice(self, pseudonym: str) -> tuple[str | None, datetime] | None:
        """(browser brand, start time) of the participant's first practice session: sitting 1."""
        async with self.engine.connect() as conn:
            row = (await conn.execute(text("SELECT browser_brand, created_at FROM sessions WHERE pseudonym = :p AND kind = 'practice' "
                                           "ORDER BY created_at LIMIT 1"), {"p": pseudonym})).first()
        return None if row is None else (row.browser_brand, row.created_at)

    async def study_label(self, session_id: str) -> dict[str, Any] | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(text("SELECT condition, scripted, onset_client_us, onset_at FROM study_labels "
                                           "WHERE session_id = CAST(:s AS uuid)"), {"s": session_id})).first()
        return None if row is None else {"condition": row.condition, "scripted": row.scripted,
                                         "onset_client_us": row.onset_client_us, "onset_at": row.onset_at}

    async def set_onset(self, session_id: str, onset_client_us: int) -> bool:
        """Records the attack onset once; False if it was already set."""
        async with self.engine.begin() as conn:
            n = (await conn.execute(text("UPDATE study_labels SET onset_client_us = :t, onset_at = now() "
                                         "WHERE session_id = CAST(:s AS uuid) AND onset_at IS NULL"),
                                    {"s": session_id, "t": onset_client_us})).rowcount
        return n == 1

    async def assign_condition(self, pseudonym: str, slot: int, condition: str) -> bool:
        """Researcher override of a slot (A8: a genuine task on another keyboard), only before it is started."""
        async with self.engine.begin() as conn:
            n = (await conn.execute(text(
                "UPDATE study_assignments a SET condition = :c WHERE a.pseudonym = :p AND a.slot = :s AND NOT EXISTS "
                "(SELECT 1 FROM sessions s WHERE s.pseudonym = a.pseudonym AND s.problem_id = a.problem_id)"),
                {"p": pseudonym, "s": slot, "c": condition})).rowcount
        return n == 1

    # ---- named staff accounts (D-044) -------------------------------------------------------

    async def staff_by_token(self, token: str) -> tuple[str, str] | None:
        """(handle, role) of an enabled staff account, or None."""
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                text("SELECT handle, role FROM staff_accounts WHERE token_sha256 = :t AND disabled_at IS NULL"),
                {"t": sha256(token)})).first()
        return None if row is None else (str(row.handle), str(row.role))

    async def create_staff_account(self, handle: str, role: str) -> str:
        """Returns the new token; only its hash is stored, so it cannot be shown again."""
        if handle in RESERVED_HANDLES:
            raise ValueError(f"{handle!r} is reserved")
        token = secrets.token_urlsafe(32)
        async with self.engine.begin() as conn:
            await conn.execute(text("INSERT INTO staff_accounts (handle, role, token_sha256) VALUES (:h, :r, :t)"),
                               {"h": handle, "r": role, "t": sha256(token)})
        return token

    async def disable_staff_account(self, handle: str) -> bool:
        async with self.engine.begin() as conn:
            n = (await conn.execute(text("UPDATE staff_accounts SET disabled_at = now() WHERE handle = :h AND disabled_at IS NULL"),
                                    {"h": handle})).rowcount
        return n == 1

    async def list_staff_accounts(self) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            rows = (await conn.execute(text("SELECT handle, role, created_at, disabled_at FROM staff_accounts ORDER BY handle"))).all()
        return [{"handle": r.handle, "role": r.role, "created_at": r.created_at.isoformat(),
                 "disabled_at": r.disabled_at.isoformat() if r.disabled_at else None} for r in rows]

    async def create_session(self, pseudonym: str, kind: str, problem_id: str,
                             at_most_once_among: Sequence[str] = (), env: Mapping[str, Any] | None = None,
                             label: tuple[str, bool] | None = None) -> tuple[str, str]:
        """With at_most_once_among, refuse (SessionLimitError) if the participant already has a session
        for any of those problems. The participant row is locked, so two concurrent requests cannot
        both pass the check (security review of D-038)."""
        session_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(32)
        nonce = secrets.token_bytes(32)
        async with self.engine.begin() as conn:
            if at_most_once_among:
                await conn.execute(text("SELECT 1 FROM participants WHERE pseudonym = :p FOR UPDATE"), {"p": pseudonym})
                existing = (await conn.execute(
                    text("SELECT count(*) AS n FROM sessions WHERE pseudonym = :p AND problem_id = ANY(:ids)"),
                    {"p": pseudonym, "ids": list(at_most_once_among)})).one()
                if existing.n > 0:
                    raise SessionLimitError(problem_id)
            env = env or {}
            await conn.execute(
                text(
                    "INSERT INTO sessions (session_id, pseudonym, kind, problem_id, nonce, token_sha256, head_hash, "
                    "browser_brand, browser_version, cross_origin_isolated) "
                    "VALUES (:s, :p, :k, :pr, :n, :t, :h, :bb, :bv, :coi)"
                ),
                {
                    "s": session_id, "p": pseudonym, "k": kind, "pr": problem_id,
                    "n": nonce, "t": sha256(token), "h": genesis(session_id, nonce),
                    "bb": env.get("browser_brand"), "bv": env.get("browser_version"), "coi": env.get("cross_origin_isolated"),
                },
            )
            if label is not None:                     # study condition (D-046); never read by scoring or reviewers
                condition, scripted = label
                await conn.execute(text("INSERT INTO study_labels (session_id, condition, scripted, onset_at) "
                                        "VALUES (:s, :c, :sc, CASE WHEN :sc THEN now() END)"),
                                   {"s": session_id, "c": condition, "sc": scripted})
        return session_id, token

    async def session_by_token(self, session_id: str, token: str) -> SessionRow | None:
        row = await self._session_row(session_id)
        if row is None or not hmac.compare_digest(bytes(row.token_sha256), sha256(token)):
            return None
        return SessionRow(str(row.session_id), row.pseudonym, row.kind, row.problem_id, row.closed_at is not None, row.epoch)

    async def get_session(self, session_id: str) -> SessionRow | None:
        row = await self._session_row(session_id)
        if row is None:
            return None
        return SessionRow(str(row.session_id), row.pseudonym, row.kind, row.problem_id, row.closed_at is not None, row.epoch)

    async def _session_row(self, session_id: str) -> Any:
        try:
            session_id = str(uuid.UUID(session_id))      # one spelling; asyncpg rejects braces
        except ValueError:
            return None
        async with self.engine.connect() as conn:
            return (await conn.execute(text("SELECT * FROM sessions WHERE session_id = :s"), {"s": session_id})).first()

    async def list_sessions(self) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT session_id, pseudonym, kind, problem_id, created_at, closed_at, "
                        "next_server_seq, unclean_segments FROM sessions ORDER BY created_at DESC LIMIT 200"
                    )
                )
            ).all()
        return [
            {
                "session_id": str(r.session_id), "pseudonym": r.pseudonym, "kind": r.kind,
                "problem_id": r.problem_id, "created_at": r.created_at.isoformat(),
                "closed": r.closed_at is not None, "n_events": r.next_server_seq,
                "unclean_segments": r.unclean_segments,
            }
            for r in rows
        ]

    async def list_participants(self) -> list[dict[str, Any]]:
        """Participants (not withdrawn) with a summary of their sessions, newest first."""
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT p.pseudonym, p.kind AS pkind, p.created_at, s.session_id, s.kind, s.problem_id, "
                        "s.created_at AS s_created, s.closed_at FROM participants p "
                        "LEFT JOIN sessions s ON s.pseudonym = p.pseudonym WHERE p.withdrawn_at IS NULL "
                        "ORDER BY p.created_at DESC, s.created_at"
                    )
                )
            ).all()
        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            entry = out.setdefault(r.pseudonym, {"pseudonym": r.pseudonym, "kind": r.pkind,
                                                 "created_at": r.created_at.isoformat(), "sessions": []})
            if r.session_id is not None:
                entry["sessions"].append({"session_id": str(r.session_id), "kind": r.kind, "problem_id": r.problem_id,
                                          "created_at": r.s_created.isoformat(), "closed": r.closed_at is not None})
        return list(out.values())

    async def participant_sessions_with_events(self, pseudonym: str) -> list[dict[str, Any]] | None:
        """Every session of a participant with its decrypted client and server events, oldest first."""
        async with self.engine.connect() as conn:
            exists = (await conn.execute(text("SELECT 1 FROM participants WHERE pseudonym = :p AND withdrawn_at IS NULL"),
                                         {"p": pseudonym})).first()
            if exists is None:
                return None
            rows = (await conn.execute(text("SELECT session_id, kind, problem_id, created_at, closed_at FROM sessions "
                                            "WHERE pseudonym = :p ORDER BY created_at"), {"p": pseudonym})).all()
        sessions = []
        for r in rows:
            _, links = await self.load_links(str(r.session_id))
            sessions.append({
                "session_id": str(r.session_id), "kind": r.kind, "problem_id": r.problem_id, "closed": r.closed_at is not None,
                "created_at": r.created_at.timestamp(), "closed_at": r.closed_at.timestamp() if r.closed_at else None,
                "events": [{"type": lk.record.type, "t_client_us": lk.record.t_client_us, "data": lk.record.data} for lk in links],
            })
        return sessions

    # ---- event log -----------------------------------------------------------------------

    async def _lock(self, conn: AsyncConnection, session_id: str) -> Any:
        row = (
            await conn.execute(text("SELECT * FROM sessions WHERE session_id = :s FOR UPDATE"), {"s": session_id})
        ).first()
        if row is None:
            raise WireError("unknown_session")
        return row

    async def _append(
        self,
        conn: AsyncConnection,
        row: Any,
        records: Sequence[ChainRecord],
        next_client_seq: int,
        segment_open: bool,
    ) -> None:
        links = extend(bytes(row.head_hash), records)
        await conn.execute(
            text(
                "INSERT INTO events (session_id, server_seq, epoch, client_seq, origin, type, t_client_us, "
                "t_server_us, batch_id, data_ct, prev_hash, hash) VALUES (:session_id, :server_seq, :epoch, "
                ":client_seq, :origin, :type, :t_client_us, :t_server_us, :batch_id, :data_ct, :prev_hash, :hash)"
            ),
            [
                {
                    "session_id": link.record.session_id, "server_seq": link.record.server_seq,
                    "epoch": link.record.epoch, "client_seq": link.record.client_seq,
                    "origin": link.record.origin, "type": link.record.type,
                    "t_client_us": link.record.t_client_us, "t_server_us": link.record.t_server_us,
                    "batch_id": row.next_batch_id,
                    "data_ct": self.cipher.encrypt(_dumps(link.record.data), event_aad(link.record.session_id, link.record.server_seq)),
                    "prev_hash": link.prev_hash, "hash": link.hash,
                }
                for link in links
            ],
        )
        await conn.execute(
            text(
                "UPDATE sessions SET next_client_seq = :c, next_server_seq = :s, head_hash = :h, "
                "next_batch_id = next_batch_id + 1, segment_open = :o WHERE session_id = :id"
            ),
            {
                "c": next_client_seq, "s": row.next_server_seq + len(links), "h": links[-1].hash,
                "o": segment_open, "id": str(row.session_id),
            },
        )

    async def open_segment(self, session_id: str, resume: bool, epoch: int | None) -> tuple[int, int]:
        """Handle a client hello. Returns (epoch, next_client_seq)."""
        async with self.engine.begin() as conn:
            row = await self._lock(conn, session_id)
            if row.closed_at is not None:
                raise WireError("session_closed")
            if resume:
                if epoch != row.epoch or row.epoch < 0:
                    raise WireError("wrong_epoch", f"resume with epoch {epoch}, session is at {row.epoch}")
                return row.epoch, row.next_client_seq
            new_epoch = row.epoch + 1
            await conn.execute(
                text(
                    "UPDATE sessions SET epoch = :e, segment_open = true, "
                    "unclean_segments = unclean_segments + CASE WHEN segment_open THEN 1 ELSE 0 END "
                    "WHERE session_id = :s"
                ),
                {"e": new_epoch, "s": session_id},
            )
            return new_epoch, row.next_client_seq

    async def append_client_batch(self, session_id: str, batch: dict[str, Any], t_server_us: int) -> AppendResult:
        async with self.engine.begin() as conn:
            row = await self._lock(conn, session_id)
            if row.closed_at is not None:
                raise WireError("session_closed")
            state = SessionState(row.next_client_seq, row.next_server_seq, bytes(row.head_hash), row.epoch)
            plan = plan_batch(state, batch)
            if plan.is_nack:
                return AppendResult(row.next_client_seq, 0, plan.resend_from)
            if not plan.accept:
                return AppendResult(row.next_client_seq, 0)
            records = [
                ChainRecord(
                    session_id, row.next_server_seq + i, row.epoch, e["client_seq"], "client",
                    e["type"], e["t_client_us"], t_server_us, e["data"],
                )
                for i, e in enumerate(plan.accept)
            ]
            ended = any(e["type"] == "segment_end" for e in plan.accept)
            next_client_seq = plan.accept[-1]["client_seq"] + 1
            await self._append(conn, row, records, next_client_seq, segment_open=row.segment_open and not ended)
            return AppendResult(next_client_seq, len(records))

    async def append_server_event(self, session_id: str, etype: str, data: dict[str, Any]) -> bool:
        """Chain a server-origin event. Skipped (False) once the session is closed."""
        async with self.engine.begin() as conn:
            row = await self._lock(conn, session_id)
            if row.closed_at is not None:
                return False
            record = ChainRecord(session_id, row.next_server_seq, max(row.epoch, 0), None, "server", etype, None, now_us(), data)
            await self._append(conn, row, [record], row.next_client_seq, row.segment_open)
            return True

    async def close_session(self, session_id: str) -> tuple[int, str]:
        async with self.engine.begin() as conn:
            row = await self._lock(conn, session_id)
            if row.closed_at is None:
                await conn.execute(
                    text("UPDATE sessions SET closed_at = now(), segment_open = false WHERE session_id = :s"),
                    {"s": session_id},
                )
            return int(row.next_server_seq), bytes(row.head_hash).hex()

    async def load_links(self, session_id: str) -> tuple[bytes, list[StoredLink]]:
        """Decrypted chain for a session: (genesis hash, links in server_seq order)."""
        async with self.engine.connect() as conn:
            srow = (await conn.execute(text("SELECT nonce FROM sessions WHERE session_id = :s"), {"s": session_id})).first()
            if srow is None:
                raise KeyError(session_id)
            rows = (
                await conn.execute(text("SELECT * FROM events WHERE session_id = :s ORDER BY server_seq"), {"s": session_id})
            ).all()
        links = [
            StoredLink(
                ChainRecord(
                    str(r.session_id), r.server_seq, r.epoch, r.client_seq, r.origin, r.type,
                    r.t_client_us, r.t_server_us,
                    _loads(self.cipher.decrypt(bytes(r.data_ct), event_aad(str(r.session_id), r.server_seq))),
                ),
                bytes(r.prev_hash),
                bytes(r.hash),
            )
            for r in rows
        ]
        return genesis(session_id, bytes(srow.nonce)), links

    # ---- reviewer decisions and appeals (D-039) ------------------------------------------

    @staticmethod
    def _note_aad(kind: str, session_id: str) -> bytes:
        """Binds an encrypted note to its kind and session (a ciphertext cannot be moved elsewhere)."""
        return f"{kind}:{session_id}".encode("ascii")

    async def add_decision(self, session_id: str, reviewer: str, decision: str, report_state: str, notes: str) -> dict[str, Any]:
        ct = self.cipher.encrypt(notes.encode("utf-8"), self._note_aad("decision", session_id))
        async with self.engine.begin() as conn:
            row = (await conn.execute(
                text("INSERT INTO review_decisions (session_id, reviewer, decision, report_state, notes_ct) "
                     "VALUES (:s, :r, :d, :st, :n) RETURNING id, at"),
                {"s": session_id, "r": reviewer, "d": decision, "st": report_state, "n": ct})).one()
        return {"id": int(row.id), "at": row.at.isoformat()}

    async def add_appeal(self, session_id: str, pseudonym: str, note: str) -> dict[str, Any]:
        ct = self.cipher.encrypt(note.encode("utf-8"), self._note_aad("appeal", session_id))
        async with self.engine.begin() as conn:
            row = (await conn.execute(
                text("INSERT INTO appeals (session_id, pseudonym, note_ct) VALUES (:s, :p, :n) RETURNING id, at"),
                {"s": session_id, "p": pseudonym, "n": ct})).one()
        return {"id": int(row.id), "at": row.at.isoformat()}

    async def reviews_for(self, session_ids: Sequence[str]) -> dict[str, dict[str, list[dict[str, Any]]]]:
        """Decisions (oldest first; the last one is current) and appeals per session, notes decrypted."""
        out: dict[str, dict[str, list[dict[str, Any]]]] = {sid: {"decisions": [], "appeals": []} for sid in session_ids}
        if not session_ids:
            return out
        async with self.engine.connect() as conn:
            decisions = (await conn.execute(
                text("SELECT session_id, reviewer, decision, report_state, notes_ct, at FROM review_decisions "
                     "WHERE session_id = ANY(CAST(:ids AS uuid[])) ORDER BY id"), {"ids": list(session_ids)})).all()
            appeals = (await conn.execute(
                text("SELECT session_id, note_ct, at FROM appeals WHERE session_id = ANY(CAST(:ids AS uuid[])) ORDER BY id"),
                {"ids": list(session_ids)})).all()
        for d in decisions:
            sid = str(d.session_id)
            out[sid]["decisions"].append({
                "decision": d.decision, "reviewer": d.reviewer, "report_state": d.report_state, "at": d.at.isoformat(),
                "notes": self.cipher.decrypt(bytes(d.notes_ct), self._note_aad("decision", sid)).decode("utf-8"),
            })
        for a in appeals:
            sid = str(a.session_id)
            out[sid]["appeals"].append({
                "at": a.at.isoformat(),
                "note": self.cipher.decrypt(bytes(a.note_ct), self._note_aad("appeal", sid)).decode("utf-8"),
            })
        return out

    async def latest_decisions(self) -> dict[str, str]:
        """session_id -> its current decision, for the participant list."""
        async with self.engine.connect() as conn:
            rows = (await conn.execute(text(
                "SELECT DISTINCT ON (session_id) session_id, decision FROM review_decisions ORDER BY session_id, id DESC"))).all()
        return {str(r.session_id): r.decision for r in rows}

    # ---- audit and erasure ---------------------------------------------------------------

    @staticmethod
    def canonical(target: str) -> str:
        """UUID-shaped targets in one spelling (PostgreSQL also accepts upper case, braces and no
        hyphens), so erasure's exact-match redaction finds them."""
        try:
            return str(uuid.UUID(target))
        except ValueError:
            return target

    async def log_access(self, actor: str, role: str, action: str, target: str) -> None:
        """For targets that name no participant. Use log_access_about when one does."""
        async with self.engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO access_log (actor, role, action, target) VALUES (:a, :r, :ac, :t)"),
                {"a": actor, "r": role, "ac": action, "t": self.canonical(target)},
            )

    async def log_access_about(self, actor: str, role: str, action: str, *,
                               pseudonym: str | None = None, session_id: str | None = None) -> bool:
        """Log an access to a participant or one of their sessions, atomically with erasure.

        The participant row is locked FOR KEY SHARE while the log row is written, and erasure's
        DELETE needs a conflicting lock. So either the log row commits first and the erasure then
        redacts it, or the erasure commits first and nothing identifying is written (the target is
        "[unknown ...]"). Returns whether the participant or session exists. A participant actor
        (role "participant") is written only while they exist."""
        async with self.engine.begin() as conn:
            row = None
            if session_id is not None:
                target, unknown = self.canonical(session_id), "[unknown session]"
                if _is_uuid(session_id):
                    row = (await conn.execute(text(
                        "SELECT p.pseudonym FROM sessions s JOIN participants p ON p.pseudonym = s.pseudonym "
                        "WHERE s.session_id = CAST(:s AS uuid) FOR KEY SHARE OF p"), {"s": target})).first()
            else:
                assert pseudonym is not None
                target, unknown = pseudonym, "[unknown participant]"
                row = (await conn.execute(text("SELECT pseudonym FROM participants WHERE pseudonym = :p FOR KEY SHARE"),
                                          {"p": pseudonym})).first()
            exists = row is not None
            await conn.execute(
                text("INSERT INTO access_log (actor, role, action, target) VALUES (:a, :r, :ac, :t)"),
                {"a": actor if exists or role != "participant" else "participant", "r": role, "ac": action,
                 "t": target if exists else unknown},
            )
        return exists

    async def access_log(self, limit: int = 500) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            rows = (await conn.execute(text("SELECT * FROM access_log ORDER BY id DESC LIMIT :n"), {"n": limit})).all()
        return [{"at": r.at.isoformat(), "actor": r.actor, "role": r.role, "action": r.action, "target": r.target} for r in rows]

    async def session_ids_of(self, pseudonym: str) -> list[str]:
        async with self.engine.connect() as conn:
            rows = (await conn.execute(text("SELECT session_id FROM sessions WHERE pseudonym = :p"), {"p": pseudonym})).all()
        return [str(r.session_id) for r in rows]

    async def all_pseudonyms(self) -> list[str]:
        """Every participant, withdrawn or not (for the retention job)."""
        async with self.engine.connect() as conn:
            rows = (await conn.execute(text("SELECT pseudonym FROM participants ORDER BY pseudonym"))).all()
        return [str(r.pseudonym) for r in rows]

    async def erase_participant(self, pseudonym: str, actor: str) -> tuple[int, int]:
        requested = datetime.now(timezone.utc)
        async with self.engine.begin() as conn:
            await conn.execute(text("SELECT set_config('integrity.erasure', 'on', true)"))
            counts = (
                await conn.execute(
                    text(
                        "SELECT count(*) AS n_sessions, coalesce(sum(next_server_seq), 0) AS n_events "
                        "FROM sessions WHERE pseudonym = :p"
                    ),
                    {"p": pseudonym},
                )
            ).one()
            session_ids = [str(r.session_id) for r in (await conn.execute(
                text("SELECT session_id FROM sessions WHERE pseudonym = :p"), {"p": pseudonym})).all()]
            deleted = (await conn.execute(text("DELETE FROM participants WHERE pseudonym = :p"), {"p": pseudonym})).rowcount
            if deleted == 0:
                raise KeyError(pseudonym)
            # The audit trail keeps when / role / action, but not this participant's identifiers (migration 0003).
            await conn.execute(text("UPDATE access_log SET actor = '[erased]' WHERE actor = :p"), {"p": pseudonym})
            await conn.execute(text("UPDATE access_log SET target = '[erased]' WHERE target = :p OR target = ANY(:sids)"),
                               {"p": pseudonym, "sids": session_ids})
            await conn.execute(
                text(
                    "INSERT INTO erasure_log (pseudonym_ref, requested_at, actor, n_sessions, n_events) "
                    "VALUES (:h, :r, :a, :s, :e)"
                ),
                {"h": self.cipher.keyed_ref(b"erasure-tombstone", pseudonym), "r": requested, "a": actor,
                 "s": counts.n_sessions, "e": counts.n_events},
            )
        return int(counts.n_sessions), int(counts.n_events)
