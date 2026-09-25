"""Document replay from content deltas, with snapshot consistency checks (SPEC 4.10).

Offsets and lengths are UTF-16 code units, as Monaco reports them, so the document is held as
UTF-16-LE bytes. Changes in one multi-change Monaco event all refer to the document before
that event and do not overlap, so they are applied in descending offset order.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


class ReplayError(ValueError):
    pass


def text_sha256(text: str) -> str:
    """SHA-256 of the UTF-8 bytes the browser's TextEncoder would produce.

    TextEncoder replaces lone surrogates with U+FFFD, so we do the same.
    """
    return hashlib.sha256(_LONE_SURROGATE.sub("�", text).encode("utf-8")).hexdigest()


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


class Utf16Doc:
    def __init__(self, text: str = "") -> None:
        self._buf = bytearray(text.encode("utf-16-le", "surrogatepass"))

    def __len__(self) -> int:
        return len(self._buf) // 2

    @property
    def text(self) -> str:
        return self._buf.decode("utf-16-le", "surrogatepass")

    def apply(self, offset: int, del_len: int, text: str) -> None:
        if offset < 0 or del_len < 0 or offset + del_len > len(self):
            raise ReplayError(f"change [{offset}, {offset + del_len}) outside document of length {len(self)}")
        self._buf[2 * offset : 2 * (offset + del_len)] = text.encode("utf-16-le", "surrogatepass")


@dataclass
class SnapshotCheck:
    server_seq: int
    reason: str
    ok: bool
    expected_sha256: str
    replayed_sha256: str


@dataclass
class Replayer:
    doc: Utf16Doc = field(default_factory=Utf16Doc)
    checks: list[SnapshotCheck] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    _group: list[dict[str, Any]] = field(default_factory=list)

    def feed(self, server_seq: int, etype: str, data: dict[str, Any]) -> None:
        if etype == "content_change":
            self._group.append(data)
            if data["idx"] == data["n"] - 1:
                self._apply_group(server_seq)
        elif etype == "snapshot":
            self._apply_group(server_seq)
            self._check_snapshot(server_seq, data)

    def finish(self) -> None:
        self._apply_group(-1)

    @property
    def mismatches(self) -> list[SnapshotCheck]:
        return [c for c in self.checks if not c.ok]

    def _apply_group(self, server_seq: int) -> None:
        if not self._group:
            return
        group, self._group = self._group, []
        if len({c["version_id"] for c in group}) != 1 or len(group) != group[0]["n"]:
            self.errors.append(f"incomplete multi-change group before server_seq {server_seq}")
        for change in sorted(group, key=lambda c: c["offset"], reverse=True):
            try:
                if change["flush"]:
                    self.doc = Utf16Doc(change["text"])
                else:
                    self.doc.apply(change["offset"], change["del_len"], change["text"])
            except ReplayError as exc:
                self.errors.append(f"server_seq {server_seq}: {exc}")

    def _check_snapshot(self, server_seq: int, data: dict[str, Any]) -> None:
        replayed = text_sha256(self.doc.text)
        ok = replayed == data["sha256"]
        self.checks.append(SnapshotCheck(server_seq, data["reason"], ok, data["sha256"], replayed))
        if not ok:
            # Adopt the snapshot so one lost event does not poison the rest of the replay.
            self.doc = Utf16Doc(data["text"])


def replay(events: list[tuple[int, str, dict[str, Any]]], upto_server_seq: int | None = None) -> Replayer:
    replayer = Replayer()
    for server_seq, etype, data in events:
        if upto_server_seq is not None and server_seq > upto_server_seq:
            break
        replayer.feed(server_seq, etype, data)
    replayer.finish()
    return replayer
