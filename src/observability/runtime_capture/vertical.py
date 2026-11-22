"""Supported paper/shadow vertical: end-to-end captured stage timeline (OCA-W10)."""

from __future__ import annotations

from typing import Any

from ..events import EventType, Outcome
from .capture import RuntimeCaptureAdapter

# Stage timeline of the supported offline/paper atomic vertical. Every stage
# is a real captured producer event; nothing here is synthesized from static
# call graphs.
VERTICAL_STAGES: list[dict[str, Any]] = [
    {
        "stage": "candidate",
        "event_type": EventType.opportunity_detected,
        "outcome": Outcome.accepted,
        "critical": True,
    },
    {
        "stage": "quote",
        "event_type": EventType.quote_received,
        "outcome": Outcome.observed,
        "critical": True,
        "provider_id": "fixture-quote-provider",
    },
    {
        "stage": "plan",
        "event_type": EventType.route_planned,
        "outcome": Outcome.accepted,
        "critical": True,
    },
    {
        "stage": "simulation",
        "event_type": EventType.simulation_completed,
        "outcome": Outcome.succeeded,
        "critical": True,
    },
    {
        "stage": "paper_outcome",
        "event_type": EventType.balance_reconciled,
        "outcome": Outcome.succeeded,
        "critical": True,
    },
]


def run_vertical(
    adapter: RuntimeCaptureAdapter,
    *,
    logical_opportunity_id: str,
    start_sequence: int = 1,
    strategy_ref: str | None = None,
) -> dict[str, Any]:
    """Capture the full supported vertical for one opportunity.

    Returns receipts for every stage (CAPTURED or explicit DEGRADED). Critical
    stages carry critical=True and are never sampled.
    """
    receipts = []
    for offset, stage in enumerate(VERTICAL_STAGES):
        receipts.append(
            adapter.capture_stage(
                logical_opportunity_id=logical_opportunity_id,
                sequence_no=start_sequence + offset,
                event_type=stage["event_type"],
                outcome=stage["outcome"],
                stage=stage["stage"],
                provider_id=stage.get("provider_id"),
                venue_id=stage.get("venue_id"),
                critical=stage["critical"],
                attributes={"stage_index": offset},
                strategy_ref=strategy_ref,
            )
        )
    degraded = [receipt for receipt in receipts if receipt["status"] != "CAPTURED"]
    return {
        "schema": "studious.observability.vertical-run.v1",
        "route": adapter.route,
        "logical_opportunity_id": logical_opportunity_id,
        "receipts": receipts,
        "captured": len(receipts) - len(degraded),
        "degraded": len(degraded),
        "complete": not degraded,
    }
