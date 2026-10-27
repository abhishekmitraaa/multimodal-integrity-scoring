"""FastAPI app: consent and sessions, WebSocket ingest, replay and audit (SPEC 4, 5, 10)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import itertools
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Literal

import yaml
from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import create_async_engine

from .chain import verify_chain
from .crypto import FieldCipher
from .replay import replay
from .report import build_report
from .settings import Settings, load_config, load_settings
from .store import SessionLimitError, Store, now_us
from .wire import WireError, parse_message, validate_batch

PROBLEMS_DIR = Path(__file__).resolve().parents[2] / "problems"


def load_problems() -> dict[str, dict[str, Any]]:
    """Problem files. Practice tasks must carry `reference_solution` (the code to type, D-035);
    exam tasks must not."""
    problems = {}
    for path in sorted(PROBLEMS_DIR.glob("*.yaml")):
        problem = yaml.safe_load(path.read_text(encoding="utf-8"))
        has_solution = "reference_solution" in problem
        if problem["kind"] == "practice" and not has_solution:
            raise ValueError(f"{path.name}: practice tasks need a reference_solution (D-035)")
        if problem["kind"] == "exam" and has_solution:
            raise ValueError(f"{path.name}: exam tasks must not carry a reference_solution")
        allowed = {"practice": ("baseline", "check"), "exam": ("exam",)}[problem["kind"]]
        if problem.get("stage") not in allowed:
            raise ValueError(f"{path.name}: stage must be one of {allowed} for a {problem['kind']} task (D-038)")
        problems[problem["id"]] = problem
    return problems


def public_problem(problem: dict[str, Any]) -> dict[str, Any]:
    """What the browser may see. An exam task's solution is never sent, whatever the file says."""
    if problem.get("kind") == "practice":
        return problem
    return {k: v for k, v in problem.items() if k != "reference_solution"}


def policy_payload(policy: dict[str, Any]) -> dict[str, Any]:
    canonical = json.dumps(policy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {**policy, "sha256": hashlib.sha256(canonical).hexdigest()}


class ConsentIn(BaseModel):
    notice_version: str = Field(min_length=1, max_length=64)
    notice_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    choices: dict[str, bool]


class ParticipantIn(BaseModel):
    kind: Literal["real", "synthetic", "dev"]
    age_confirmed: bool
    consent: ConsentIn


class SessionIn(BaseModel):
    participant_token: str
    kind: Literal["practice", "exam"]
    problem_id: str


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    return authorization.removeprefix("Bearer ").strip()


def _events_payload(links: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "server_seq": link.record.server_seq, "client_seq": link.record.client_seq,
            "epoch": link.record.epoch, "origin": link.record.origin, "type": link.record.type,
            "t_client_us": link.record.t_client_us, "t_server_us": link.record.t_server_us,
            "data": link.record.data,
        }
        for link in links
    ]


def report_config() -> dict[str, Any]:
    """Settings for build_report, all from config/ (no magic numbers in code)."""
    features, models, scoring, capture = (load_config(n) for n in ("features", "models", "scoring", "capture"))
    return {
        "report": scoring["report"],
        "m": int(features["keystroke"]["window_keystrokes"]),
        "stride": int(features["keystroke"]["exam_stride"]),
        "clip_s": float(features["keystroke"]["latency_clip_ms"]) / 1000,
        "g_min": int(models["enrollment"]["g_min"]),
        "large_insert_chars": int(capture["snapshot"]["large_insert_min_chars"]),
        "coupling_s": float(features["clipboard"]["focus_paste_coupling_s"]),
    }


NUMERIC_DETECTION_FIELDS = ("windows", "population_threshold", "personal_threshold", "share_above", "threshold",
                            "eer_threshold", "g")


PARTICIPANT_TEXT = {
    ("keystroke", "flag"): "Your typing rhythm in the exam differs from your practice typing more than usual. A person will look at it.",
    ("keystroke", "ok"): "Your typing rhythm in the exam is within the usual range of your practice typing.",
    ("keystroke", "unavailable"): "The typing comparison could not run for this exam.",
    ("baseline_check", "flag"): "Your baseline check did not match your practice typing. A person will look at it.",
}
CHECK_TEXT = {
    "confirmed": "Your baseline check matched your practice typing.",
    "not_confirmed": "Your baseline check did not match your practice typing. A person will look at it.",
}


def redact_for_participant(report: dict[str, Any]) -> dict[str, Any]:
    """A participant sees verdicts and plain-language findings without distances, thresholds or
    shares, which would show how close to the line a typing style can go (security reviews of D-038).
    The typing-rhythm and baseline-check texts are replaced, and the reasons rebuilt from them."""
    check = report["baseline"].get("check", {})
    check = {k: v for k, v in check.items() if k not in NUMERIC_DETECTION_FIELDS}
    check["detail"] = CHECK_TEXT.get(check.get("status", ""), check.get("detail", ""))
    report["baseline"]["check"] = check
    for exam in report["exams"]:
        exam["keystroke"] = {"available": False, "redacted": bool(exam["keystroke"].get("available"))}
        for f in exam["findings"]:
            f["detail"] = PARTICIPANT_TEXT.get((f["id"], f["status"]), f["detail"])
        exam["reasons"] = [f"{f['title']}: {f['detail']}" for f in exam["findings"] if f["status"] == "flag"]
    report["overall"]["reasons"] = [r for e in report["exams"] for r in e["reasons"]]
    return report


def load_keystroke_model(data_root: Path, model_file: str) -> tuple[Any, str]:
    """(model or None, note). The model is optional: without it the keystroke check says so."""
    path = data_root / model_file
    if not path.exists():
        return None, f"No keystroke model at {path}. Run integrity_eval.serving_calibration (docs/phase-reports/P2.md)."
    try:
        from integrity_ml.serving import KeystrokeModel

        model = KeystrokeModel(path, load_config("models")["keystroke_encoder"])
    except Exception as exc:  # noqa: BLE001 - report any load problem instead of failing the report
        return None, f"The keystroke model could not be loaded: {exc}"
    return model, "Reference ranges: " + str(model.calibration_meta.get("source", ""))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    problems = load_problems()
    rcfg = report_config()
    keystroke_model: dict[str, Any] = {}

    def get_model() -> tuple[Any, str]:
        if "loaded" not in keystroke_model:      # loaded on first use: torch is slow to import
            keystroke_model["loaded"] = load_keystroke_model(settings.data_root, rcfg["report"]["model_file"])
        return keystroke_model["loaded"]  # type: ignore[no-any-return]

    async def participant_report(pseudonym: str, for_participant: bool = False) -> dict[str, Any]:
        sessions = await store().participant_sessions_with_events(pseudonym)
        if sessions is None:
            raise HTTPException(404, "unknown participant")
        for x in sessions:      # baseline / check / exam (D-038), from the problem files
            x["stage"] = problems.get(x["problem_id"], {}).get("stage", "exam" if x["kind"] == "exam" else "baseline")
        model, note = await asyncio.to_thread(get_model)
        if for_participant:
            # Submitted sessions only: an open exam's report would let a student check, mid-exam,
            # whether they are being flagged. And no server paths or exception text.
            sessions = [x for x in sessions if x["closed"]]
            note = "Keystroke reference ranges from a public dataset." if model is not None else "The typing check is not available on this server."
        report = await asyncio.to_thread(build_report, pseudonym, sessions, model, note, rcfg)
        return redact_for_participant(report) if for_participant else report
    policy = policy_payload(settings.editor_policy)
    prefixes = {
        "real": settings.privacy["pseudonym"]["prefix_real"],
        "synthetic": settings.privacy["pseudonym"]["prefix_synthetic"],
        "dev": settings.privacy["pseudonym"]["prefix_dev"],
    }
    ping_interval_s = settings.capture["clock_sync_interval_ms"] / 1000

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        app.state.store = Store(engine, FieldCipher(settings.data_key), prefixes)
        app.state.active = {}
        yield
        await engine.dispose()

    app = FastAPI(title="integrity-backend", lifespan=lifespan)

    def store() -> Store:
        return app.state.store  # type: ignore[no-any-return]

    def staff(authorization: str | None, admin_only: bool = False) -> tuple[str, str]:
        token = _bearer(authorization)
        if hmac.compare_digest(token, settings.admin_token):
            return "admin", "admin"
        if not admin_only and hmac.compare_digest(token, settings.reviewer_token):
            return "reviewer-1", "reviewer"
        raise HTTPException(403, "not authorised")

    async def session_for(session_id: str, token: str) -> Any:
        session = await store().session_by_token(session_id, token)
        if session is None:
            raise HTTPException(403, "bad session token")
        return session

    # ---- public ----------------------------------------------------------------------------

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/editor-policy")
    async def editor_policy() -> dict[str, Any]:
        return policy

    @app.get("/api/client-config")
    async def client_config() -> dict[str, Any]:
        """Everything the capture client needs from config/, so the browser hard-codes nothing."""
        return {"policy": policy, "capture": settings.capture}

    @app.get("/api/problems/{problem_id}")
    async def problem(problem_id: str) -> dict[str, Any]:
        if problem_id not in problems:
            raise HTTPException(404, "unknown problem")
        return public_problem(problems[problem_id])

    @app.post("/api/participants")
    async def create_participant(body: ParticipantIn) -> dict[str, str]:
        if not body.age_confirmed:
            raise HTTPException(400, "participants must confirm they are 18 or older")
        if body.kind == "real" and not settings.privacy["real_collection_enabled"]:
            raise HTTPException(403, "real data collection is disabled until ethics approval")
        pseudonym, token = await store().create_participant(body.kind, body.consent.model_dump())
        return {"pseudonym": pseudonym, "participant_token": token}

    @app.post("/api/sessions")
    async def create_session(body: SessionIn) -> dict[str, str]:
        pseudonym = await store().participant_by_token(body.participant_token)
        if pseudonym is None:
            raise HTTPException(403, "bad participant token")
        if body.problem_id not in problems:
            raise HTTPException(404, "unknown problem")
        problem = problems[body.problem_id]
        if body.kind != problem["kind"]:        # the server decides; the client's kind must agree
            raise HTTPException(400, f"{body.problem_id} is a {problem['kind']} task")
        once = [pid for pid, p in problems.items() if p.get("stage") == "check"] if problem.get("stage") == "check" else []
        try:          # one baseline check per participant (D-038), checked and inserted atomically
            session_id, token = await store().create_session(pseudonym, problem["kind"], body.problem_id, at_most_once_among=once)
        except SessionLimitError as exc:
            raise HTTPException(409, "the baseline check can only be taken once") from exc
        return {"session_id": session_id, "session_token": token}

    # ---- session-token endpoints -------------------------------------------------------------

    @app.get("/api/sessions/{session_id}/state")
    async def session_state(session_id: str, authorization: str | None = Header(None)) -> dict[str, Any]:
        """Current document for restoring the editor after a reload."""
        await session_for(session_id, _bearer(authorization))
        _, links = await store().load_links(session_id)
        r = replay([(lk.record.server_seq, lk.record.type, lk.record.data) for lk in links])
        return {"text": r.doc.text, "n_events": len(links)}

    @app.post("/api/sessions/{session_id}/close")
    async def close_session(session_id: str, authorization: str | None = Header(None)) -> dict[str, Any]:
        await session_for(session_id, _bearer(authorization))
        n_events, head = await store().close_session(session_id)
        return {"n_events": n_events, "head_hash": head, "signed": False}

    @app.post("/api/sessions/{session_id}/beacon")
    async def beacon(session_id: str, request: Request, token: str = "") -> dict[str, Any]:
        """Last batch sent with navigator.sendBeacon on pagehide (no custom headers possible)."""
        await session_for(session_id, token)
        try:
            msg = parse_message(await request.body())
            batch = msg.get("batch")
            if not isinstance(batch, dict) or batch.get("session_id") != session_id:
                raise WireError("bad_message", "beacon must carry a batch for this session")
            validate_batch(batch)
            result = await store().append_client_batch(session_id, batch, now_us())
        except WireError as exc:
            raise HTTPException(400, exc.code) from exc
        return {"next_client_seq": result.next_client_seq, "stored": result.stored}

    # ---- staff endpoints (access-logged) --------------------------------------------------

    @app.get("/api/sessions")
    async def list_sessions(authorization: str | None = Header(None)) -> list[dict[str, Any]]:
        actor, role = staff(authorization)
        await store().log_access(actor, role, "list_sessions", "*")
        return await store().list_sessions()

    @app.get("/api/participants")
    async def list_participants(authorization: str | None = Header(None)) -> list[dict[str, Any]]:
        actor, role = staff(authorization)
        await store().log_access(actor, role, "list_participants", "*")
        participants = await store().list_participants()
        for p in participants:
            for x in p["sessions"]:
                x["stage"] = problems.get(x["problem_id"], {}).get("stage", "exam" if x["kind"] == "exam" else "baseline")
        return participants

    @app.get("/api/participants/{pseudonym}/report")
    async def staff_report(pseudonym: str, authorization: str | None = Header(None)) -> dict[str, Any]:
        actor, role = staff(authorization)
        await store().log_access(actor, role, "read_report", pseudonym)
        return await participant_report(pseudonym)

    @app.get("/api/me/report")
    async def own_report(authorization: str | None = Header(None)) -> dict[str, Any]:
        """A participant's own report (SPEC 10.10: participants can view their own evidence)."""
        pseudonym = await store().participant_by_token(_bearer(authorization))
        if pseudonym is None:
            raise HTTPException(403, "not authorised")
        await store().log_access(pseudonym, "participant", "read_own_report", pseudonym)
        return await participant_report(pseudonym, for_participant=True)

    @app.get("/api/sessions/{session_id}/events")
    async def session_events(session_id: str, authorization: str | None = Header(None)) -> dict[str, Any]:
        actor, role = staff(authorization)
        if await store().get_session(session_id) is None:
            raise HTTPException(404, "unknown session")
        await store().log_access(actor, role, "read_events", session_id)
        _, links = await store().load_links(session_id)
        return {"session_id": session_id, "events": _events_payload(links)}

    @app.get("/api/sessions/{session_id}/replay")
    async def session_replay(session_id: str, upto: int | None = None, authorization: str | None = Header(None)) -> dict[str, Any]:
        actor, role = staff(authorization)
        if await store().get_session(session_id) is None:
            raise HTTPException(404, "unknown session")
        await store().log_access(actor, role, "replay", session_id)
        _, links = await store().load_links(session_id)
        r = replay([(lk.record.server_seq, lk.record.type, lk.record.data) for lk in links], upto)
        return {
            "text": r.doc.text,
            "upto": upto,
            "n_events": len(links),
            "snapshot_checks": [c.__dict__ for c in r.checks],
            "mismatches": len(r.mismatches),
            "errors": r.errors,
        }

    @app.get("/api/sessions/{session_id}/verify")
    async def session_verify(session_id: str, authorization: str | None = Header(None)) -> dict[str, Any]:
        actor, role = staff(authorization)
        if await store().get_session(session_id) is None:
            raise HTTPException(404, "unknown session")
        await store().log_access(actor, role, "verify_chain", session_id)
        genesis_hash, links = await store().load_links(session_id)
        result = verify_chain(genesis_hash, links)
        return {
            "ok": result.ok, "n_events": result.n_events, "head_hash": result.head_hash.hex(),
            "first_bad_index": result.first_bad_index, "reason": result.reason,
        }

    @app.get("/api/access-log")
    async def access_log(authorization: str | None = Header(None)) -> list[dict[str, Any]]:
        actor, role = staff(authorization, admin_only=True)
        await store().log_access(actor, role, "read_access_log", "*")
        return await store().access_log()

    @app.delete("/api/participants/{pseudonym}")
    async def erase(pseudonym: str, authorization: str | None = Header(None)) -> dict[str, Any]:
        actor, role = staff(authorization, admin_only=True)
        try:
            n_sessions, n_events = await store().erase_participant(pseudonym, actor)
        except KeyError as exc:
            raise HTTPException(404, "unknown participant") from exc
        await store().log_access(actor, role, "erase_participant", "erased")
        return {"erased": True, "n_sessions": n_sessions, "n_events": n_events}

    # ---- WebSocket ingest ----------------------------------------------------------------

    @app.websocket("/ws/sessions/{session_id}")
    async def ingest(ws: WebSocket, session_id: str, token: str = "") -> None:
        session = await store().session_by_token(session_id, token)
        if session is None:
            await ws.close(code=4403)
            return
        await ws.accept()
        previous = app.state.active.get(session_id)
        if previous is not None:  # one live connection per session; the newest wins
            await previous.close(code=4409)
        app.state.active[session_id] = ws
        pending_pings: dict[int, int] = {}
        ping_task: asyncio.Task[None] | None = None
        close_code = 1006  # abnormal closure unless the client says otherwise
        opened = False

        async def ping_loop() -> None:
            for ping_id in itertools.count():
                await asyncio.sleep(ping_interval_s)
                pending_pings[ping_id] = now_us()
                await ws.send_json({"type": "ping", "id": ping_id, "t_server_us": pending_pings[ping_id]})

        try:
            hello = parse_message(await ws.receive_text())
            if hello.get("type") != "hello":
                raise WireError("expected_hello")
            resume = bool(hello.get("resume"))
            epoch, next_seq = await store().open_segment(session_id, resume, hello.get("epoch"))
            await store().append_server_event(session_id, "ws_open", {"resume": resume, "epoch": epoch})
            opened = True
            await ws.send_json({"type": "welcome", "epoch": epoch, "next_client_seq": next_seq})
            ping_task = asyncio.create_task(ping_loop())
            while True:
                raw = await ws.receive_text()
                try:
                    msg = parse_message(raw)
                    if msg.get("type") == "batch":
                        batch = msg.get("batch")
                        if not isinstance(batch, dict) or batch.get("session_id") != session_id:
                            raise WireError("bad_message", "batch for another session")
                        validate_batch(batch)
                        result = await store().append_client_batch(session_id, batch, now_us())
                        if result.resend_from is not None:
                            await ws.send_json({"type": "nack", "resend_from": result.resend_from})
                        else:
                            await ws.send_json({"type": "ack", "next_client_seq": result.next_client_seq})
                    elif msg.get("type") == "pong":
                        sent = pending_pings.pop(int(msg.get("id", -1)), None)
                        if sent is not None and isinstance(msg.get("t_client_unix_us"), int):
                            received = now_us()
                            rtt = received - sent
                            offset = msg["t_client_unix_us"] - (sent + rtt // 2)
                            await store().append_server_event(
                                session_id, "clock_sync", {"ping_id": int(msg["id"]), "rtt_us": rtt, "offset_us": offset}
                            )
                    else:
                        raise WireError("bad_message", f"unknown message type {msg.get('type')!r}")
                except WireError as exc:
                    await ws.send_json({"type": "error", "code": exc.code, "detail": exc.detail})
                    if exc.code in {"session_closed", "wrong_epoch", "unknown_session"}:
                        await ws.close(code=4400)
                        return
        except WebSocketDisconnect as exc:
            close_code = exc.code
        except WireError as exc:
            await ws.send_json({"type": "error", "code": exc.code, "detail": exc.detail})
            await ws.close(code=4400)
            close_code = 4400
        finally:
            if ping_task is not None:
                ping_task.cancel()
            if app.state.active.get(session_id) is ws:
                del app.state.active[session_id]
                if opened:
                    # A detached task, so the write completes even if this handler is being
                    # cancelled (server shutdown, or the test client tearing down the socket).
                    record = asyncio.ensure_future(
                        store().append_server_event(session_id, "ws_close", {"code": close_code})
                    )
                    await asyncio.shield(record)

    return app


def main() -> None:
    import uvicorn

    # access_log=False: WebSocket and beacon URLs carry session tokens in the query string.
    uvicorn.run(create_app(), host="127.0.0.1", port=8000, access_log=False)


if __name__ == "__main__":
    main()
