"""Contract tests for shared/schema/event.v1.schema.json (docs/SPEC.md section 4)."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "shared" / "schema" / "event.v1.schema.json"
EXAMPLES = sorted((ROOT / "shared" / "schema" / "examples").glob("*.json"))


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def first_event(batch: dict[str, Any], etype: str) -> dict[str, Any]:
    return next(e for e in batch["events"] if e["type"] == etype)


def test_examples_exist() -> None:
    assert len(EXAMPLES) >= 2


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_batches_validate(validator: Draft202012Validator, path: Path) -> None:
    errors = list(validator.iter_errors(load(path)))
    assert errors == [], [e.message for e in errors]


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_client_seq_is_consecutive(path: Path) -> None:
    seqs = [e["client_seq"] for e in load(path)["events"]]
    assert seqs == list(range(seqs[0], seqs[0] + len(seqs)))


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_snapshot_hashes_match_text(path: Path) -> None:
    for event in load(path)["events"]:
        if event["type"] == "snapshot":
            data = event["data"]
            assert data["len"] == len(data["text"].encode("utf-16-le")) // 2
            assert data["sha256"] == hashlib.sha256(data["text"].encode("utf-8")).hexdigest()


def mutate(path: Path, fn: Any) -> dict[str, Any]:
    batch = copy.deepcopy(load(path))
    fn(batch)
    return batch


TYPING = next(p for p in EXAMPLES if "typing" in p.name)


def _add_key_text(b: dict[str, Any]) -> None:
    first_event(b, "keydown")["data"]["key"] = "x"


def _float_timestamp(b: dict[str, Any]) -> None:
    first_event(b, "keydown")["t_client_us"] = 1000000.5


def _unknown_type(b: dict[str, Any]) -> None:
    b["events"][1]["type"] = "mouse_move"


def _negative_seq(b: dict[str, Any]) -> None:
    b["events"][0]["client_seq"] = -1


def _bad_category(b: dict[str, Any]) -> None:
    first_event(b, "keydown")["data"]["cat"] = "vowel"


def _missing_data(b: dict[str, Any]) -> None:
    del first_event(b, "keyup")["data"]


def _bad_cause(b: dict[str, Any]) -> None:
    first_event(b, "content_change")["data"]["cause"] = "autocomplete"


def _float_dpr(b: dict[str, Any]) -> None:
    first_event(b, "segment_start")["data"]["device"]["dpr_x100"] = 1.25


def _raw_user_agent(b: dict[str, Any]) -> None:
    first_event(b, "segment_start")["data"]["device"]["user_agent"] = "Mozilla/5.0"


def _wrong_schema_version(b: dict[str, Any]) -> None:
    b["schema_version"] = "0.9"


def _empty_batch(b: dict[str, Any]) -> None:
    b["events"] = []


@pytest.mark.parametrize(
    "mutation",
    [
        _add_key_text,          # KeyboardEvent.key must never be stored (SPEC 4.5, 10.4)
        _float_timestamp,       # integers only
        _unknown_type,
        _negative_seq,
        _bad_category,
        _missing_data,
        _bad_cause,
        _float_dpr,
        _raw_user_agent,        # full UA string is not collected
        _wrong_schema_version,
        _empty_batch,
    ],
    ids=lambda f: f.__name__.lstrip("_"),
)
def test_schema_rejects_invalid_batches(validator: Draft202012Validator, mutation: Any) -> None:
    assert not validator.is_valid(mutate(TYPING, mutation))
