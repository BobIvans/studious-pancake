"""PR-264 / NETWORK-02: slot-leader-aware submission planning only."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Mega806Error, require_nonnegative_int, require_text


def ingest_leader_schedule(
    rows: Sequence[Mapping[str, object]],
) -> tuple[tuple[int, str], ...]:
    normalized = []
    seen = set()
    for row in rows:
        slot = require_nonnegative_int(row.get("slot"), "slot")
        leader = require_text(row.get("leader"), "leader")
        if slot in seen:
            raise Mega806Error("DUPLICATE_SLOT")
        seen.add(slot)
        normalized.append((slot, leader))
    return tuple(sorted(normalized))


def estimate_slot_send_window(
    *,
    slot_start_us: int,
    slot_end_us: int,
    transport_latency_us: int,
    clock_uncertainty_us: int,
    blockhash_deadline_us: int,
) -> tuple[int, int]:
    slot_start_us = require_nonnegative_int(slot_start_us, "slot_start_us")
    slot_end_us = require_nonnegative_int(slot_end_us, "slot_end_us")
    transport_latency_us = require_nonnegative_int(
        transport_latency_us, "transport_latency_us"
    )
    clock_uncertainty_us = require_nonnegative_int(
        clock_uncertainty_us, "clock_uncertainty_us"
    )
    blockhash_deadline_us = require_nonnegative_int(
        blockhash_deadline_us, "blockhash_deadline_us"
    )
    start = slot_start_us + clock_uncertainty_us
    end = (
        min(slot_end_us, blockhash_deadline_us)
        - transport_latency_us
        - clock_uncertainty_us
    )
    if end <= start:
        raise Mega806Error("NO_SAFE_SEND_WINDOW")
    return start, end


def select_slot_aware_transport(
    rows: Sequence[Mapping[str, object]], *, max_latency_us: int
) -> str:
    max_latency_us = require_nonnegative_int(max_latency_us, "max_latency_us")
    candidates = []
    for row in rows:
        if row.get("qualified") is not True:
            continue
        name = require_text(row.get("name"), "name")
        latency = require_nonnegative_int(row.get("latency_us"), "latency_us")
        if latency <= max_latency_us:
            candidates.append((latency, name))
    if not candidates:
        raise Mega806Error("NO_QUALIFIED_SLOT_TRANSPORT")
    return min(candidates)[1]


def audit_slot_submission(
    planned_slot: int, observed_slot: int | None, *, settled: bool
) -> dict[str, object]:
    planned_slot = require_nonnegative_int(planned_slot, "planned_slot")
    if observed_slot is None:
        return {"planned_slot": planned_slot, "outcome": "UNKNOWN", "settled": False}
    observed_slot = require_nonnegative_int(observed_slot, "observed_slot")
    return {
        "planned_slot": planned_slot,
        "observed_slot": observed_slot,
        "slot_delta": observed_slot - planned_slot,
        "outcome": "SETTLED" if settled else "OBSERVED_NOT_FINAL",
        "settled": bool(settled),
    }
