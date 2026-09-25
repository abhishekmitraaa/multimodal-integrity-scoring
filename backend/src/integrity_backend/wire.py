"""Wire parsing and validation for client messages (SPEC 4.1, 4.2).

JSON Schema treats 1.0 as an integer, so floats are rejected at the parser, before validation.
Each event is validated against its own schema definition, chosen by its `type`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "shared" / "schema" / "event.v1.schema.json"
MAX_MESSAGE_BYTES = 4 * 1024 * 1024


class WireError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _reject_float(token: str) -> Any:
    raise WireError("float_not_allowed", token[:32])


def _reject_constant(token: str) -> Any:
    raise WireError("non_finite_number", token)


def parse_message(raw: str | bytes) -> dict[str, Any]:
    if len(raw) > MAX_MESSAGE_BYTES:
        raise WireError("too_large", f"{len(raw)} bytes")
    try:
        obj = json.loads(raw, parse_float=_reject_float, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise WireError("bad_json", str(exc)) from exc
    if not isinstance(obj, dict):
        raise WireError("bad_message", "top level must be an object")
    return obj


def _load_validators() -> tuple[Draft202012Validator, dict[str, Draft202012Validator]]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    defs = schema["$defs"]
    envelope = {
        **schema,
        "properties": {
            **schema["properties"],
            "events": {"type": "array", "minItems": 1, "maxItems": 500, "items": {"type": "object"}},
        },
    }
    per_type: dict[str, Draft202012Validator] = {}
    for option in defs["event"]["oneOf"]:
        name = option["$ref"].rsplit("/", 1)[1]
        etype = defs[name]["properties"]["type"]["const"]
        per_type[etype] = Draft202012Validator({"$ref": f"#/$defs/{name}", "$defs": defs})
    return Draft202012Validator(envelope), per_type


_ENVELOPE, _PER_TYPE = _load_validators()
CLIENT_EVENT_TYPES = frozenset(_PER_TYPE)


def _first_error(validator: Draft202012Validator, instance: Any, where: str) -> None:
    error = next(iter(validator.iter_errors(instance)), None)
    if error is not None:
        path = "/".join(str(p) for p in error.absolute_path)
        raise WireError("schema", f"{where}{'/' + path if path else ''}: {error.message[:200]}")


def validate_batch(batch: dict[str, Any]) -> None:
    """Raise WireError unless `batch` is a valid, internally contiguous client batch."""
    _first_error(_ENVELOPE, batch, "batch")
    for i, event in enumerate(batch["events"]):
        validator = _PER_TYPE.get(event.get("type")) if isinstance(event.get("type"), str) else None
        if validator is None:
            raise WireError("schema", f"events/{i}: unknown event type {event.get('type')!r}")
        _first_error(validator, event, f"events/{i}")
    seqs = [e["client_seq"] for e in batch["events"]]
    if seqs != list(range(seqs[0], seqs[0] + len(seqs))):
        raise WireError("non_contiguous", "client_seq must be consecutive within a batch")
