"""Ordering rules for incoming batches (SPEC 4.2). Pure logic; the store applies the plan."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .wire import WireError


@dataclass(frozen=True)
class SessionState:
    next_client_seq: int
    next_server_seq: int
    head: bytes
    epoch: int


@dataclass(frozen=True)
class Plan:
    accept: list[dict[str, Any]]
    resend_from: int | None = None

    @property
    def is_nack(self) -> bool:
        return self.resend_from is not None


def plan_batch(state: SessionState, batch: dict[str, Any]) -> Plan:
    """Decide what to store from an already-validated, internally contiguous batch.

    - first client_seq == expected: accept all
    - first < expected: drop the already-stored prefix (idempotent resend), accept the rest
    - first > expected: nothing stored; ask the client to resend from `expected`
    """
    if batch["epoch"] != state.epoch:
        raise WireError("wrong_epoch", f"batch epoch {batch['epoch']} != session epoch {state.epoch}")
    events = batch["events"]
    expected = state.next_client_seq
    if events[0]["client_seq"] > expected:
        return Plan([], resend_from=expected)
    return Plan([e for e in events if e["client_seq"] >= expected])
