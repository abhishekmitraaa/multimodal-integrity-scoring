"""End-to-end ingest over WebSocket against PostgreSQL (SPEC 4.2–4.4, 5, 10). SYNTHETIC traffic."""

from __future__ import annotations

import hashlib
import asyncio
import json
import time
import uuid
from typing import Any, Callable

import pytest
from synthetic_events import SyntheticTyping, batch, chunks

REVIEWER = {"Authorization": "Bearer reviewer-test-token"}
ADMIN = {"Authorization": "Bearer admin-test-token"}
CONSENT = {"notice_version": "draft-p1", "notice_sha256": "a" * 64, "choices": {"participation": True}}


def new_session(client: Any, kind: str = "synthetic") -> tuple[str, str, str]:
    r = client.post("/api/participants", json={"kind": kind, "age_confirmed": True, "consent": CONSENT})
    assert r.status_code == 200, r.text
    participant = r.json()
    r = client.post(
        "/api/sessions",
        json={"participant_token": participant["participant_token"], "kind": "practice", "problem_id": "practice_sum_evens"},
    )
    assert r.status_code == 200, r.text
    return r.json()["session_id"], r.json()["session_token"], participant["pseudonym"]


def hello(ws: Any, resume: bool = False, epoch: int | None = None) -> dict[str, Any]:
    ws.send_text(json.dumps({"type": "hello", "resume": resume, "epoch": epoch}))
    welcome = ws.receive_json()
    assert welcome["type"] == "welcome", welcome
    return welcome  # type: ignore[no-any-return]


def send(ws: Any, sid: str, events: list[dict[str, Any]], epoch: int = 0) -> dict[str, Any]:
    ws.send_text(json.dumps({"type": "batch", "batch": batch(sid, events, epoch)}))
    return ws.receive_json()  # type: ignore[no-any-return]


def events_of(client: Any, sid: str, settle: bool = True) -> list[dict[str, Any]]:
    """Events for a session. With settle, wait briefly for the detached ws_close write."""
    for _ in range(50):
        r = client.get(f"/api/sessions/{sid}/events", headers=REVIEWER)
        assert r.status_code == 200
        events: list[dict[str, Any]] = r.json()["events"]
        if not settle or (events and events[-1]["type"] == "ws_close"):
            return events
        time.sleep(0.02)
    return events


def client_seqs(events: list[dict[str, Any]]) -> list[int]:
    return [e["client_seq"] for e in events if e["origin"] == "client"]


def ws_url(sid: str, token: str) -> str:
    return f"/ws/sessions/{sid}?token={token}"


# ---- consent gate ------------------------------------------------------------------------


def test_real_participants_refused_until_ethics_approval(client: Any) -> None:
    r = client.post("/api/participants", json={"kind": "real", "age_confirmed": True, "consent": CONSENT})
    assert r.status_code == 403


def test_age_confirmation_required(client: Any) -> None:
    r = client.post("/api/participants", json={"kind": "dev", "age_confirmed": False, "consent": CONSENT})
    assert r.status_code == 400


def test_pseudonym_prefixes(client: Any) -> None:
    assert new_session(client, "synthetic")[2].startswith("SYN-")
    assert new_session(client, "dev")[2].startswith("DEV-")


# ---- ordering ----------------------------------------------------------------------------


def test_in_order_batches_give_gapless_server_seq_and_valid_chain(client: Any) -> None:
    sid, token, _ = new_session(client)
    gen = SyntheticTyping()
    stream = gen.segment_start() + gen.type_text("def f(): pass") + [gen.snapshot()]
    with client.websocket_connect(ws_url(sid, token)) as ws:
        assert hello(ws) == {"type": "welcome", "epoch": 0, "next_client_seq": 0}
        for part in chunks(stream, 15):
            reply = send(ws, sid, part)
            assert reply == {"type": "ack", "next_client_seq": part[-1]["client_seq"] + 1}
    events = events_of(client, sid)
    assert [e["server_seq"] for e in events] == list(range(len(events)))
    assert client_seqs(events) == list(range(len(stream)))
    assert events[0]["type"] == "ws_open" and events[-1]["type"] == "ws_close"
    verify = client.get(f"/api/sessions/{sid}/verify", headers=REVIEWER).json()
    assert verify["ok"] and verify["n_events"] == len(events)


def test_duplicate_batch_is_idempotent(client: Any) -> None:
    sid, token, _ = new_session(client)
    gen = SyntheticTyping()
    first = gen.segment_start() + gen.type_text("ab")
    with client.websocket_connect(ws_url(sid, token)) as ws:
        hello(ws)
        assert send(ws, sid, first)["next_client_seq"] == len(first)
        assert send(ws, sid, first) == {"type": "ack", "next_client_seq": len(first)}
        overlap = first[-2:] + gen.type_text("c")
        assert send(ws, sid, overlap)["next_client_seq"] == len(first) + 3
    assert client_seqs(events_of(client, sid)) == list(range(len(first) + 3))


def test_out_of_order_batch_is_nacked_then_recovered(client: Any) -> None:
    sid, token, _ = new_session(client)
    gen = SyntheticTyping()
    one = gen.segment_start() + gen.type_text("x")
    two = gen.type_text("y")
    with client.websocket_connect(ws_url(sid, token)) as ws:
        hello(ws)
        assert send(ws, sid, two) == {"type": "nack", "resend_from": 0}
        send(ws, sid, one)
        send(ws, sid, two)
    assert client_seqs(events_of(client, sid)) == list(range(len(one) + len(two)))


def test_reconnect_resume_and_new_page(client: Any) -> None:
    sid, token, _ = new_session(client)
    gen = SyntheticTyping()
    part1 = gen.segment_start() + gen.type_text("ab")
    part2 = gen.type_text("cd")
    with client.websocket_connect(ws_url(sid, token)) as ws:
        hello(ws)
        send(ws, sid, part1)
    # network drop: the same page resumes epoch 0 and resends an overlapping window
    with client.websocket_connect(ws_url(sid, token)) as ws:
        welcome = hello(ws, resume=True, epoch=0)
        assert welcome == {"type": "welcome", "epoch": 0, "next_client_seq": len(part1)}
        assert send(ws, sid, part1[-3:] + part2)["next_client_seq"] == len(part1) + len(part2)
    # page reload without segment_end: new epoch, previous segment counted as unclean
    with client.websocket_connect(ws_url(sid, token)) as ws:
        welcome = hello(ws, resume=False)
        assert welcome["epoch"] == 1
        reload_gen = SyntheticTyping(first_seq=welcome["next_client_seq"], initial_text=gen.text)
        assert send(ws, sid, reload_gen.segment_start(), epoch=1)["type"] == "ack"
        # a stale batch from the old page (epoch 0) is refused
        ws.send_text(json.dumps({"type": "batch", "batch": batch(sid, reload_gen.type_text("z"), epoch=0)}))
        assert ws.receive_json()["code"] == "wrong_epoch"
    sessions = {s["session_id"]: s for s in client.get("/api/sessions", headers=REVIEWER).json()}
    assert sessions[sid]["unclean_segments"] == 1
    replay = client.get(f"/api/sessions/{sid}/replay", headers=REVIEWER).json()
    assert replay["text"] == "abcd" and replay["mismatches"] == 0


def test_newer_connection_supersedes_older(client: Any) -> None:
    sid, token, _ = new_session(client)
    with client.websocket_connect(ws_url(sid, token)) as first:
        hello(first)
        with client.websocket_connect(ws_url(sid, token)) as second:
            hello(second, resume=True, epoch=0)
            with pytest.raises(Exception):
                first.receive_json()


# ---- validation --------------------------------------------------------------------------


def test_float_and_schema_errors_are_reported_and_not_stored(client: Any) -> None:
    sid, token, _ = new_session(client)
    gen = SyntheticTyping()
    good = gen.segment_start()
    with client.websocket_connect(ws_url(sid, token)) as ws:
        hello(ws)
        raw = json.dumps({"type": "batch", "batch": batch(sid, good)})
        ws.send_text(raw.replace('"t_client_us": 1000000', '"t_client_us": 1000000.0', 1))
        assert ws.receive_json()["code"] == "float_not_allowed"
        bad = [dict(good[0], data={**good[0]["data"], "user_agent": "Mozilla"})]
        assert send(ws, sid, bad)["code"] == "schema"
        assert send(ws, sid, good)["type"] == "ack"
    assert client_seqs(events_of(client, sid)) == [0, 1]


def test_wrong_token_rejected(client: Any) -> None:
    sid, _, _ = new_session(client)
    with pytest.raises(Exception):
        with client.websocket_connect(ws_url(sid, "nope")) as ws:
            ws.receive_json()
    assert client.get(f"/api/sessions/{sid}/events").status_code == 401
    assert client.get(f"/api/sessions/{sid}/events", headers={"Authorization": "Bearer nope"}).status_code == 403


# ---- replay, close, beacon, clock sync ---------------------------------------------------


def test_replay_with_non_bmp_text_matches_snapshots(client: Any) -> None:
    sid, token, _ = new_session(client)
    gen = SyntheticTyping()
    stream = gen.segment_start() + gen.type_text("s = 'π😀'") + [gen.snapshot()] + gen.type_text("\n") + [gen.snapshot()]
    with client.websocket_connect(ws_url(sid, token)) as ws:
        hello(ws)
        for part in chunks(stream, 15):
            send(ws, sid, part)
    body = client.get(f"/api/sessions/{sid}/replay", headers=REVIEWER).json()
    assert body["text"] == "s = 'π😀'\n"
    assert body["mismatches"] == 0 and len(body["snapshot_checks"]) == 3 and body["errors"] == []


def test_close_returns_head_hash_and_blocks_later_events(client: Any) -> None:
    sid, token, _ = new_session(client)
    gen = SyntheticTyping()
    with client.websocket_connect(ws_url(sid, token)) as ws:
        hello(ws)
        send(ws, sid, gen.segment_start() + gen.type_text("ok") + [gen.segment_end()])
        closed = client.post(f"/api/sessions/{sid}/close", headers={"Authorization": f"Bearer {token}"}).json()
        assert send(ws, sid, gen.type_text("late"))["code"] == "session_closed"
    verify = client.get(f"/api/sessions/{sid}/verify", headers=REVIEWER).json()
    assert closed["head_hash"] == verify["head_hash"] and closed["n_events"] == verify["n_events"]
    assert closed["signed"] is False


def test_beacon_delivers_final_batch(client: Any) -> None:
    sid, token, _ = new_session(client)
    gen = SyntheticTyping()
    with client.websocket_connect(ws_url(sid, token)) as ws:
        hello(ws)
        send(ws, sid, gen.segment_start())
    tail = gen.type_text("zz") + [gen.segment_end()]
    r = client.post(
        f"/api/sessions/{sid}/beacon?token={token}",
        content=json.dumps({"type": "batch", "batch": batch(sid, tail)}),
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 200 and r.json()["stored"] == len(tail)


def test_clock_sync_is_recorded(make_client: Callable[..., Any], settings: Any) -> None:
    client = make_client(capture={**settings.capture, "clock_sync_interval_ms": 50})
    sid, token, _ = new_session(client)
    with client.websocket_connect(ws_url(sid, token)) as ws:
        hello(ws)
        ping = ws.receive_json()
        assert ping["type"] == "ping"
        ws.send_text(json.dumps({"type": "pong", "id": ping["id"], "t_client_unix_us": ping["t_server_us"] + 5_000}))
        ws.send_text(json.dumps({"type": "batch", "batch": batch(sid, SyntheticTyping().segment_start()[:1])}))
        while (reply := ws.receive_json())["type"] == "ping":
            pass
        assert reply["type"] == "ack"
    syncs = [e for e in events_of(client, sid) if e["type"] == "clock_sync"]
    assert syncs and syncs[0]["data"]["rtt_us"] >= 0


# ---- storage guarantees ------------------------------------------------------------------


async def _sql(db_url: str, sql: str, *args: Any) -> Any:
    import asyncpg

    conn = await asyncpg.connect(db_url.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


def _run(db_url: str, sql: str, *args: Any) -> Any:
    return asyncio.run(_sql(db_url, sql, *args))


def _session_with_text(client: Any, text: str) -> tuple[str, str, str]:
    sid, token, pseudonym = new_session(client)
    gen = SyntheticTyping()
    with client.websocket_connect(ws_url(sid, token)) as ws:
        hello(ws)
        for part in chunks(gen.segment_start() + gen.type_text(text) + [gen.snapshot()], 15):
            send(ws, sid, part)
    return sid, token, pseudonym


def test_event_payloads_are_encrypted_at_rest(client: Any, db_url: str) -> None:
    sid, _, _ = _session_with_text(client, "SECRETWORD")
    rows = _run(db_url, "SELECT data_ct FROM events WHERE session_id = $1", uuid.UUID(sid))
    blob = b"".join(bytes(r["data_ct"]) for r in rows)
    assert b"SECRETWORD" not in blob and b"segment_start" not in blob and b"synthetic" not in blob


def test_events_are_append_only(client: Any, db_url: str) -> None:
    import asyncpg

    sid, _, _ = _session_with_text(client, "a")
    uid = uuid.UUID(sid)
    for sql in (
        "UPDATE events SET t_server_us = 0 WHERE session_id = $1",
        "DELETE FROM events WHERE session_id = $1",
    ):
        with pytest.raises(asyncpg.RaiseError, match="append-only"):
            _run(db_url, sql, uid)
    with pytest.raises(asyncpg.RaiseError, match="append-only"):
        _run(db_url, "TRUNCATE events CASCADE")
    with pytest.raises(asyncpg.RaiseError, match="append-only"):
        _run(db_url, "DELETE FROM access_log")


def test_db_level_tampering_is_detected_by_verify(client: Any, db_url: str) -> None:
    sid, _, _ = _session_with_text(client, "abc")
    uid = uuid.UUID(sid)

    async def tamper() -> None:
        import asyncpg

        conn = await asyncpg.connect(db_url.replace("postgresql+asyncpg://", "postgresql://"))
        try:
            async with conn.transaction():
                await conn.execute("ALTER TABLE events DISABLE TRIGGER events_append_only")
                await conn.execute(
                    "UPDATE events SET t_server_us = t_server_us + 1 WHERE session_id = $1 AND server_seq = 3", uid
                )
                await conn.execute("ALTER TABLE events ENABLE TRIGGER events_append_only")
        finally:
            await conn.close()

    asyncio.run(tamper())
    verify = client.get(f"/api/sessions/{sid}/verify", headers=REVIEWER).json()
    assert verify["ok"] is False and verify["first_bad_index"] == 3


def test_staff_reads_are_access_logged(client: Any) -> None:
    sid, _, _ = _session_with_text(client, "a")
    client.get(f"/api/sessions/{sid}/replay", headers=REVIEWER)
    client.get(f"/api/sessions/{sid}/verify", headers=REVIEWER)
    log = client.get("/api/access-log", headers=ADMIN).json()
    actions = {(e["action"], e["target"]) for e in log}
    assert ("replay", sid) in actions and ("verify_chain", sid) in actions
    assert client.get("/api/access-log", headers=REVIEWER).status_code == 403


def test_erasure_deletes_everything_and_leaves_tombstone(client: Any, db_url: str) -> None:
    sid, _, pseudonym = _session_with_text(client, "bye")
    r = client.delete(f"/api/participants/{pseudonym}", headers=ADMIN)
    assert r.status_code == 200 and r.json()["n_sessions"] == 1
    uid = uuid.UUID(sid)
    assert _run(db_url, "SELECT count(*) AS n FROM events WHERE session_id = $1", uid)[0]["n"] == 0
    assert _run(db_url, "SELECT count(*) AS n FROM participants WHERE pseudonym = $1", pseudonym)[0]["n"] == 0
    tomb = _run(db_url, "SELECT pseudonym_ref, n_events FROM erasure_log")
    assert any(row["n_events"] > 0 for row in tomb)
    assert all(pseudonym not in str(dict(row)) for row in tomb)
    assert hashlib.sha256(pseudonym.encode()).hexdigest() not in {row["pseudonym_ref"] for row in tomb}   # keyed, not a bare hash
    log = client.get("/api/access-log", headers=ADMIN).json()
    assert not any(pseudonym in (e["actor"], e["target"]) or sid in (e["actor"], e["target"]) for e in log)
    assert client.delete(f"/api/participants/{pseudonym}", headers=REVIEWER).status_code == 403
