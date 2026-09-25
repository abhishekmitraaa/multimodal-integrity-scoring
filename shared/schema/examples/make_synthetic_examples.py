"""Regenerate the SYNTHETIC example batches in this folder.

These files are hand-designed fixtures for schema and pipeline tests. They are not
recorded from any person and must never be reported as results.

Usage: python shared/schema/examples/make_synthetic_examples.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent

DEVICE: dict[str, Any] = {
    "os_family": "windows",
    "browser_family": "chromium",
    "browser_major": 0,
    "layout": "synthetic",
    "layout_source": "unknown",
    "keyboard_type": "unknown",
    "screen_w": 1920,
    "screen_h": 1080,
    "dpr_x100": 100,
}


def sha256_text(text: str) -> str:
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def segment_start(page: str, problem_id: str) -> dict[str, Any]:
    return {
        "time_origin_unix_us": 1_758_800_000_000_000,
        "page": page,
        "problem_id": problem_id,
        "editor_policy_id": "policy-v1",
        "editor_policy_sha256": "0" * 64,
        "device": DEVICE,
        "timer": {"resolution_us": 100, "cross_origin_isolated": False},
        "synthetic": True,
    }


def key(code: str, cat: str, col: int, mods: int = 0) -> dict[str, Any]:
    return {
        "code": code,
        "cat": cat,
        "rep": False,
        "mods": mods,
        "trusted": True,
        "composing": False,
        "target": "editor",
        "line": 1,
        "col": col,
    }


def typed_change(version: int, offset: int, text: str) -> dict[str, Any]:
    return {
        "version_id": version,
        "idx": 0,
        "n": 1,
        "offset": offset,
        "del_len": 0,
        "ins_len": len(text),
        "text": text,
        "start_line": 1,
        "start_col": offset + 1,
        "end_line": 1,
        "end_col": offset + 1,
        "cause": "typed",
        "undo": False,
        "redo": False,
        "flush": False,
    }


def batch(session_id: str, batch_seq: int, events: list[tuple[str, int, dict[str, Any]]]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "session_id": session_id,
        "epoch": 0,
        "batch_seq": batch_seq,
        "events": [
            {"client_seq": i, "type": etype, "t_client_us": t, "data": data}
            for i, (etype, t, data) in enumerate(events)
        ],
    }


def typing_example() -> dict[str, Any]:
    """Type `x=1` key by key, then take a timer snapshot."""
    events: list[tuple[str, int, dict[str, Any]]] = [("segment_start", 5_000, segment_start("practice", "synthetic_p1"))]
    t = 1_000_000
    for version, (ch, code, cat) in enumerate([("x", "KeyX", "letter"), ("=", "Equal", "symbol"), ("1", "Digit1", "digit")], start=2):
        offset = version - 2
        events.append(("keydown", t, key(code, cat, offset + 1)))
        events.append(("content_change", t + 400, typed_change(version, offset, ch)))
        events.append(("keyup", t + 85_000, key(code, cat, offset + 2)))
        t += 210_000
    text = "x=1"
    events.append(("snapshot", t, {"version_id": 4, "reason": "timer", "len": len(text), "sha256": sha256_text(text), "text": text}))
    return batch("5f0c9a1e-3b7d-4c2a-9e41-0a6b2d8f7c11", 0, events)


def paste_example() -> dict[str, Any]:
    """Leave the window, come back, paste a 2-line function, submit."""
    pasted = "def f(a):\n    return a\n"
    ctrl = key("ControlLeft", "modifier", 1, mods=2)
    v_key = key("KeyV", "letter", 1, mods=2)
    events: list[tuple[str, int, dict[str, Any]]] = [
        ("segment_start", 4_000, segment_start("exam", "synthetic_e1")),
        ("copy", 900_000, {"source": "problem_panel", "len": 9, "sha256": sha256_text("def f(a):")}),
        ("blur", 1_000_000, {"target": "window"}),
        ("visibility", 1_000_500, {"state": "hidden"}),
        ("visibility", 19_000_000, {"state": "visible"}),
        ("focus", 19_000_300, {"target": "window"}),
        ("keydown", 20_000_000, ctrl),
        ("keydown", 20_150_000, v_key),
        ("paste", 20_150_800, {
            "len": len(pasted), "newlines": pasted.count("\n"), "trusted": True, "mimes": ["text/plain"],
            "start_line": 1, "start_col": 1, "end_line": 3, "end_col": 1,
        }),
        ("content_change", 20_151_000, {
            **typed_change(2, 0, pasted), "cause": "paste",
        }),
        ("keyup", 20_230_000, v_key),
        ("keyup", 20_300_000, {**ctrl, "mods": 0}),
        ("snapshot", 20_300_500, {"version_id": 2, "reason": "large_insert", "len": len(pasted), "sha256": sha256_text(pasted), "text": pasted}),
        ("submit", 45_000_000, {"version_id": 2, "sha256": sha256_text(pasted)}),
        ("segment_end", 45_000_100, {"reason": "submit"}),
    ]
    return batch("9d2e4b7a-6c1f-4e8b-a3d5-7f0e1c2b9a44", 0, events)


def main() -> None:
    for name, payload in [
        ("synthetic_batch_typing.json", typing_example()),
        ("synthetic_batch_paste.json", paste_example()),
    ]:
        (HERE / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
