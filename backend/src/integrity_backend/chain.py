"""Per-session hash chain over stored events (SPEC 4.4). P1: plain chain, no signatures."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Sequence

GENESIS_TAG = b"IMS-CHAIN-v1"


@dataclass(frozen=True)
class ChainRecord:
    session_id: str
    server_seq: int
    epoch: int
    client_seq: int | None
    origin: str
    type: str
    t_client_us: int | None
    t_server_us: int
    data: dict[str, Any]


@dataclass(frozen=True)
class StoredLink:
    record: ChainRecord
    prev_hash: bytes
    hash: bytes


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    n_events: int
    head_hash: bytes
    first_bad_index: int | None = None
    reason: str | None = None


def genesis(session_id: str, nonce: bytes) -> bytes:
    """h_{-1} = SHA256("IMS-CHAIN-v1" || UTF-8(session_id) || nonce)."""
    return hashlib.sha256(GENESIS_TAG + session_id.encode("utf-8") + nonce).digest()


def canonical(record: ChainRecord) -> bytes:
    obj = {
        "session_id": record.session_id,
        "server_seq": record.server_seq,
        "epoch": record.epoch,
        "client_seq": record.client_seq,
        "origin": record.origin,
        "type": record.type,
        "t_client_us": record.t_client_us,
        "t_server_us": record.t_server_us,
        "data": record.data,
    }
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    # surrogatepass: a lone UTF-16 surrogate from the client must still hash deterministically.
    return text.encode("utf-8", "surrogatepass")


def link(prev_hash: bytes, record: ChainRecord) -> bytes:
    return hashlib.sha256(prev_hash + canonical(record)).digest()


def extend(head: bytes, records: Sequence[ChainRecord]) -> list[StoredLink]:
    out: list[StoredLink] = []
    for record in records:
        h = link(head, record)
        out.append(StoredLink(record, head, h))
        head = h
    return out


def verify_chain(genesis_hash: bytes, links: Sequence[StoredLink]) -> VerifyResult:
    """Recompute the chain; report the first index where anything disagrees."""
    expected_prev = genesis_hash
    for i, stored in enumerate(links):
        if stored.record.server_seq != i:
            return VerifyResult(False, len(links), expected_prev, i, "server_seq gap or reorder")
        if stored.prev_hash != expected_prev:
            return VerifyResult(False, len(links), expected_prev, i, "prev_hash mismatch")
        if link(expected_prev, stored.record) != stored.hash:
            return VerifyResult(False, len(links), expected_prev, i, "hash mismatch")
        expected_prev = stored.hash
    return VerifyResult(True, len(links), expected_prev)
