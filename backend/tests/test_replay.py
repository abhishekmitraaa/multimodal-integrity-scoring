"""UTF-16-aware replay and snapshot checks (SPEC 4.10). SYNTHETIC edit streams."""

from __future__ import annotations

from typing import Any

import pytest

from integrity_backend.replay import ReplayError, Utf16Doc, replay, text_sha256, utf16_len


def change(version: int, offset: int, del_len: int, text: str, idx: int = 0, n: int = 1, flush: bool = False) -> dict[str, Any]:
    return {"version_id": version, "idx": idx, "n": n, "offset": offset, "del_len": del_len, "text": text, "flush": flush}


def snapshot(text: str, reason: str = "timer") -> dict[str, Any]:
    return {"reason": reason, "sha256": text_sha256(text), "text": text, "len": utf16_len(text)}


def test_utf16_offsets_with_non_bmp_characters() -> None:
    doc = Utf16Doc("a😀b")  # the emoji is 2 UTF-16 code units
    assert len(doc) == 4
    doc.apply(3, 1, "c")  # replace "b"
    assert doc.text == "a😀c"
    doc.apply(1, 2, "")  # delete the whole emoji
    assert doc.text == "ac"


def test_out_of_range_change_raises() -> None:
    with pytest.raises(ReplayError):
        Utf16Doc("abc").apply(2, 5, "")


def test_typing_then_snapshot_matches() -> None:
    events = [(i, "content_change", change(i + 2, i, 0, ch)) for i, ch in enumerate("x=1")]
    events.append((3, "snapshot", snapshot("x=1")))
    r = replay(events)
    assert r.doc.text == "x=1" and r.mismatches == [] and r.errors == []


def test_multi_change_event_applied_against_pre_event_document() -> None:
    # Multi-cursor typing "#" at the start of two lines of "ab\ncd": offsets 0 and 3.
    events = [
        (0, "content_change", change(2, 0, 0, "#", idx=0, n=2)),
        (1, "content_change", change(2, 3, 0, "#", idx=1, n=2)),
    ]
    # The first segment_start snapshot (starter code) is the base document, not a mismatch.
    rep = replay([(0, "snapshot", snapshot("ab\ncd", "segment_start"))] + [(s + 1, t, d) for s, t, d in events])
    assert rep.doc.text == "#ab\n#cd"
    assert rep.mismatches == [] and rep.checks[0].reason == "base"


def test_reload_snapshot_that_differs_from_replay_is_a_mismatch() -> None:
    events = [
        (0, "snapshot", snapshot("def f():", "segment_start")),
        (1, "content_change", change(2, 8, 0, " pass")),
        (2, "snapshot", snapshot("something else", "segment_start")),  # reload restored other text
    ]
    r = replay(events)
    assert [c.server_seq for c in r.mismatches] == [2]


def test_undo_is_just_another_change() -> None:
    events = [
        (0, "content_change", change(2, 0, 0, "hello")),
        (1, "content_change", change(3, 0, 5, "")),  # undo
        (2, "snapshot", snapshot("")),
    ]
    assert replay(events).mismatches == []


def test_flush_replaces_everything() -> None:
    events = [
        (0, "content_change", change(2, 0, 0, "old")),
        (1, "content_change", change(3, 0, 3, "new text", flush=True)),
    ]
    assert replay(events).doc.text == "new text"


def test_snapshot_mismatch_detected_and_adopted() -> None:
    events = [
        (0, "content_change", change(2, 0, 0, "abc")),
        # event 1 (inserting "d") was lost
        (2, "snapshot", snapshot("abcd")),
        (3, "content_change", change(4, 4, 0, "e")),
        (4, "snapshot", snapshot("abcde")),
    ]
    r = replay(events)
    assert [c.server_seq for c in r.mismatches] == [2]
    assert r.checks[-1].ok and r.doc.text == "abcde"


def test_replay_upto_server_seq() -> None:
    events = [(i, "content_change", change(i + 2, i, 0, ch)) for i, ch in enumerate("abc")]
    assert replay(events, upto_server_seq=1).doc.text == "ab"


def test_sha_matches_textencoder_for_lone_surrogate() -> None:
    # TextEncoder encodes a lone surrogate as U+FFFD (EF BF BD).
    import hashlib

    assert text_sha256("a\ud800") == hashlib.sha256(b"a\xef\xbf\xbd").hexdigest()
