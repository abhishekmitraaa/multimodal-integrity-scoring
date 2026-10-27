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
from typing import Any, Sequence, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from .chain import ChainRecord, StoredLink, extend, genesis
from .crypto import FieldCipher, event_aad
from .ingest import SessionState, plan_batch
from .wire import WireError

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def now_us() -> int:
    return time.time_ns() // 1000


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


class Store:
    def __init__(self, engine: AsyncEngine, cipher: FieldCipher, pseudonym_prefixes: dict[str, str]) -> None:
        self.engine = engine
        self.cipher = cipher
        self.prefixes = pseudonym_prefixes

    # ---- participants and sessions -------------------------------------------------------

    async def create_participant(self, kind: str, consent: dict[str, Any]) -> tuple[str, str]:
        pseudonym = self.prefixes[kind] + "".join(secrets.choice(CROCKFORD) for _ in range(8))
        token = secrets.token_urlsafe(32)
        async with self.engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO participants (pseudonym, kind, token_sha256) VALUES (:p, :k, :t)"),
                {"p": pseudonym, "k": kind, "t": sha256(token)},
            )
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

    async def create_session(self, pseudonym: str, kind: str, problem_id: str) -> tuple[str, str]:
        session_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(32)
        nonce = secrets.token_bytes(32)
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO sessions (session_id, pseudonym, kind, problem_id, nonce, token_sha256, head_hash) "
                    "VALUES (:s, :p, :k, :pr, :n, :t, :h)"
                ),
                {
                    "s": session_id, "p": pseudonym, "k": kind, "pr": problem_id,
                    "n": nonce, "t": sha256(token), "h": genesis(session_id, nonce),
                },
            )
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
            uuid.UUID(session_id)
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

    async def count_sessions(self, pseudonym: str, problem_ids: Sequence[str]) -> int:
        async with self.engine.connect() as conn:
            row = (await conn.execute(text("SELECT count(*) AS n FROM sessions WHERE pseudonym = :p AND problem_id = ANY(:ids)"),
                                      {"p": pseudonym, "ids": list(problem_ids)})).first()
        return int(row.n) if row else 0

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

    # ---- audit and erasure ---------------------------------------------------------------

    async def log_access(self, actor: str, role: str, action: str, target: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO access_log (actor, role, action, target) VALUES (:a, :r, :ac, :t)"),
                {"a": actor, "r": role, "ac": action, "t": target},
            )

    async def access_log(self, limit: int = 500) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            rows = (await conn.execute(text("SELECT * FROM access_log ORDER BY id DESC LIMIT :n"), {"n": limit})).all()
        return [{"at": r.at.isoformat(), "actor": r.actor, "role": r.role, "action": r.action, "target": r.target} for r in rows]

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
            deleted = (await conn.execute(text("DELETE FROM participants WHERE pseudonym = :p"), {"p": pseudonym})).rowcount
            if deleted == 0:
                raise KeyError(pseudonym)
            await conn.execute(
                text(
                    "INSERT INTO erasure_log (pseudonym_sha256, requested_at, actor, n_sessions, n_events) "
                    "VALUES (:h, :r, :a, :s, :e)"
                ),
                {"h": sha256(pseudonym).hex(), "r": requested, "a": actor, "s": counts.n_sessions, "e": counts.n_events},
            )
        return int(counts.n_sessions), int(counts.n_events)
