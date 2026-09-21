"""PR-185 / POL-01: protocol-owned inventory and fee-sweep events."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence
from .core import EvidenceBinding, Mega802Error, require_nonnegative_int, stable_hash


@dataclass(frozen=True, slots=True)
class InventoryEvent:
    protocol_id: str
    asset_id: str
    amount: int
    event_kind: str
    available_liquidity: int
    evidence: EvidenceBinding


def collect_protocol_owned_liquidity(
    events: Sequence[InventoryEvent], *, now: int
) -> tuple[InventoryEvent, ...]:
    rows = []
    for event in events:
        event.evidence.assert_usable(now=now)
        require_nonnegative_int(event.amount, "amount")
        rows.append(event)
    return tuple(
        sorted(
            rows, key=lambda item: (item.protocol_id, item.asset_id, item.event_kind)
        )
    )


def collect_fee_sweep_events(
    events: Sequence[InventoryEvent], *, now: int
) -> tuple[InventoryEvent, ...]:
    return tuple(
        event
        for event in collect_protocol_owned_liquidity(events, now=now)
        if event.event_kind == "fee_sweep"
    )


def estimate_inventory_release_impact(event: InventoryEvent, *, depth: int) -> int:
    if depth <= 0:
        raise Mega802Error("INVALID_MARKET_DEPTH")
    executable = min(event.amount, event.available_liquidity)
    return executable * 1_000_000 // depth


def emit_protocol_inventory_candidate(
    event: InventoryEvent, *, impact_ppm: int, minimum_impact_ppm: int
) -> str:
    if impact_ppm < minimum_impact_ppm:
        raise Mega802Error("INVENTORY_IMPACT_BELOW_THRESHOLD")
    return stable_hash(
        {
            "protocol": event.protocol_id,
            "asset": event.asset_id,
            "amount": event.amount,
            "impact_ppm": impact_ppm,
            "evidence": event.evidence.identity,
        }
    )
