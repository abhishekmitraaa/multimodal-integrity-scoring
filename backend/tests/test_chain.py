"""Hash chain detects edits, insertions, deletions and reorders (SPEC 4.4). SYNTHETIC records."""

from __future__ import annotations

import dataclasses

import pytest

from integrity_backend.chain import ChainRecord, StoredLink, extend, genesis, link, verify_chain

SID = "5f0c9a1e-3b7d-4c2a-9e41-0a6b2d8f7c11"
NONCE = b"\x07" * 32


def synthetic_records(n: int = 8) -> list[ChainRecord]:
    return [
        ChainRecord(
            session_id=SID,
            server_seq=i,
            epoch=0,
            client_seq=i if i % 4 else None,
            origin="client" if i % 4 else "server",
            type="keydown" if i % 4 else "clock_sync",
            t_client_us=1000 * i if i % 4 else None,
            t_server_us=10_000 + i,
            data={"code": "KeyA", "cat": "letter", "n": i},
        )
        for i in range(n)
    ]


def build() -> tuple[bytes, list[StoredLink]]:
    g = genesis(SID, NONCE)
    return g, extend(g, synthetic_records())


def relink(g: bytes, records: list[ChainRecord]) -> list[StoredLink]:
    """What an attacker without the head hash could do: recompute everything."""
    return extend(g, records)


def test_intact_chain_verifies() -> None:
    g, links = build()
    result = verify_chain(g, links)
    assert result.ok and result.n_events == 8 and result.head_hash == links[-1].hash


def test_genesis_depends_on_nonce_and_session() -> None:
    assert genesis(SID, NONCE) != genesis(SID, b"\x08" * 32)
    assert genesis(SID, NONCE) != genesis(SID.replace("5", "6"), NONCE)


FIELDS = [f.name for f in dataclasses.fields(ChainRecord)]


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("index", [0, 3, 7])
def test_single_field_edit_detected(field: str, index: int) -> None:
    g, links = build()
    rec = links[index].record
    new_value = {
        "session_id": SID.upper(),
        "server_seq": rec.server_seq + 1,
        "epoch": rec.epoch + 1,
        "client_seq": 999,
        "origin": "tampered",
        "type": "paste",
        "t_client_us": 123,
        "t_server_us": rec.t_server_us + 1,
        "data": {**rec.data, "cat": "digit"},
    }[field]
    tampered = dataclasses.replace(rec, **{field: new_value})
    links[index] = StoredLink(tampered, links[index].prev_hash, links[index].hash)
    result = verify_chain(g, links)
    assert not result.ok and result.first_bad_index == index


def test_nested_data_edit_detected() -> None:
    g, links = build()
    rec = links[5].record
    links[5] = StoredLink(dataclasses.replace(rec, data={**rec.data, "n": 6}), links[5].prev_hash, links[5].hash)
    assert verify_chain(g, links).first_bad_index == 5


def test_deletion_detected() -> None:
    g, links = build()
    del links[4]
    assert verify_chain(g, links).first_bad_index == 4


def test_insertion_detected() -> None:
    g, links = build()
    extra = dataclasses.replace(links[2].record, data={"forged": True})
    links.insert(3, StoredLink(extra, links[2].hash, link(links[2].hash, extra)))
    assert verify_chain(g, links).first_bad_index == 3


def test_reorder_detected() -> None:
    g, links = build()
    links[2], links[3] = links[3], links[2]
    assert verify_chain(g, links).first_bad_index == 2


def test_truncation_changes_head() -> None:
    g, links = build()
    short = verify_chain(g, links[:5])
    assert short.ok  # a prefix is a valid chain...
    assert short.head_hash != verify_chain(g, links).head_hash  # ...but a kept head hash exposes it


def test_full_recompute_only_caught_by_kept_head_hash() -> None:
    g, links = build()
    kept_head = links[-1].hash
    records = [link.record for link in links]
    records[3] = dataclasses.replace(records[3], data={"forged": True})
    rewritten = relink(g, records)
    assert verify_chain(g, rewritten).ok  # documented P1 gap (SPEC 4.4)
    assert rewritten[-1].hash != kept_head


def test_lone_surrogate_hashes_deterministically() -> None:
    rec = dataclasses.replace(synthetic_records(1)[0], data={"text": "a\ud800b"})
    assert link(b"x", rec) == link(b"x", rec)
