"""SYNTHETIC client events for backend tests. Nothing here is recorded from a person."""

from __future__ import annotations

import hashlib
import re
from typing import Any

_LONE = re.compile("[\ud800-\udfff]")

DEVICE = {
    "os_family": "windows", "browser_family": "chromium", "browser_major": 0, "layout": "synthetic",
    "layout_source": "unknown", "keyboard_type": "unknown", "screen_w": 1920, "screen_h": 1080, "dpr_x100": 100,
}


def sha(text: str) -> str:
    return hashlib.sha256(_LONE.sub("�", text).encode("utf-8")).hexdigest()


def u16(text: str) -> int:
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


class SyntheticTyping:
    """Builds a consistent stream: segment_start, per-character keydown/content_change/keyup, snapshots."""

    def __init__(self, first_seq: int = 0, initial_text: str = "") -> None:
        self.seq = first_seq
        self.t = 1_000_000
        self.text = initial_text
        self.version = 1

    def _event(self, etype: str, data: dict[str, Any]) -> dict[str, Any]:
        event = {"client_seq": self.seq, "type": etype, "t_client_us": self.t, "data": data}
        self.seq += 1
        self.t += 40_000
        return event

    def segment_start(self, problem_id: str = "practice_sum_evens") -> list[dict[str, Any]]:
        start = self._event("segment_start", {
            "time_origin_unix_us": 1_758_800_000_000_000, "page": "practice", "problem_id": problem_id,
            "editor_policy_id": "policy-v1", "editor_policy_sha256": "0" * 64, "device": DEVICE,
            "timer": {"resolution_us": 100, "cross_origin_isolated": False}, "synthetic": True,
        })
        return [start, self.snapshot("segment_start")]

    def key(self, etype: str, code: str = "KeyA", cat: str = "letter") -> dict[str, Any]:
        return self._event(etype, {
            "code": code, "cat": cat, "rep": False, "mods": 0, "trusted": True, "composing": False,
            "target": "editor", "line": 1, "col": 1,
        })

    def insert(self, ch: str, offset: int | None = None, cause: str = "typed") -> dict[str, Any]:
        offset = u16(self.text) if offset is None else offset
        self.version += 1
        encoded = self.text.encode("utf-16-le", "surrogatepass")
        self.text = (encoded[: 2 * offset] + ch.encode("utf-16-le", "surrogatepass") + encoded[2 * offset :]).decode(
            "utf-16-le", "surrogatepass"
        )
        return self._event("content_change", {
            "version_id": self.version, "idx": 0, "n": 1, "offset": offset, "del_len": 0,
            "ins_len": u16(ch), "text": ch, "start_line": 1, "start_col": 1, "end_line": 1, "end_col": 1,
            "cause": cause, "undo": False, "redo": False, "flush": False,
        })

    def type_text(self, text: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for ch in text:
            out += [self.key("keydown"), self.insert(ch), self.key("keyup")]
        return out

    def snapshot(self, reason: str = "timer") -> dict[str, Any]:
        return self._event("snapshot", {
            "version_id": self.version, "reason": reason, "len": u16(self.text), "sha256": sha(self.text), "text": self.text,
        })

    def segment_end(self) -> dict[str, Any]:
        return self._event("segment_end", {"reason": "submit"})


def batch(session_id: str, events: list[dict[str, Any]], epoch: int = 0, batch_seq: int = 0) -> dict[str, Any]:
    return {"schema_version": "1.0", "session_id": session_id, "epoch": epoch, "batch_seq": batch_seq, "events": events}


def chunks(events: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [events[i : i + size] for i in range(0, len(events), size)]
