"""Wire parsing and validation (SPEC 4.1, 4.2). Batches are SYNTHETIC fixtures."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from integrity_backend.wire import CLIENT_EVENT_TYPES, WireError, parse_message, validate_batch

EXAMPLES = Path(__file__).resolve().parents[2] / "shared" / "schema" / "examples"


def synthetic_batch() -> dict[str, Any]:
    return json.loads((EXAMPLES / "synthetic_batch_typing.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("token", ["1.0", "1e3", "2E-1", "-0.5"])
def test_float_tokens_rejected_even_when_integral(token: str) -> None:
    with pytest.raises(WireError) as exc:
        parse_message(f'{{"t_client_us": {token}}}')
    assert exc.value.code == "float_not_allowed"


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_rejected(token: str) -> None:
    with pytest.raises(WireError) as exc:
        parse_message(f'{{"x": {token}}}')
    assert exc.value.code == "non_finite_number"


def test_bad_json_and_non_object() -> None:
    with pytest.raises(WireError):
        parse_message("{not json")
    with pytest.raises(WireError):
        parse_message("[1, 2]")


def test_example_batches_pass() -> None:
    for path in EXAMPLES.glob("synthetic_*.json"):
        validate_batch(parse_message(path.read_text(encoding="utf-8")))


def test_all_schema_event_types_are_known() -> None:
    assert "keydown" in CLIENT_EVENT_TYPES and "snapshot" in CLIENT_EVENT_TYPES
    assert "clock_sync" not in CLIENT_EVENT_TYPES  # server-origin only


def test_unknown_type_rejected_with_location() -> None:
    batch = synthetic_batch()
    batch["events"][2]["type"] = "mouse_move"
    with pytest.raises(WireError, match="events/2"):
        validate_batch(batch)


def test_key_text_rejected() -> None:
    batch = synthetic_batch()
    batch["events"][1]["data"]["key"] = "x"
    with pytest.raises(WireError, match="events/1"):
        validate_batch(batch)


def test_non_contiguous_rejected() -> None:
    batch = synthetic_batch()
    batch["events"][3]["client_seq"] = 99
    with pytest.raises(WireError) as exc:
        validate_batch(batch)
    assert exc.value.code == "non_contiguous"


def test_client_cannot_send_server_only_type() -> None:
    batch = copy.deepcopy(synthetic_batch())
    batch["events"][1] = {"client_seq": 1, "type": "clock_sync", "t_client_us": 1, "data": {}}
    with pytest.raises(WireError):
        validate_batch(batch)
