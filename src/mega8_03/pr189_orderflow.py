"""PR-189 / ORDERFLOW-01 — public/opt-in scheduled-flow research only.

No function in this module constructs or authorizes a sandwich/front-run.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .common import (
    EvidenceEnvelope,
    OfflineDecision,
    PPM,
    decision,
    integer,
    require_rows,
)


def index_trigger_and_dca_orders(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    require_rows(rows, "orders")
    accepted = [
        dict(row)
        for row in rows
        if row.get("public_or_opt_in") is True
        and str(row.get("order_id", "")).strip()
        and integer(
            row.get("scheduled_amount_atomic", 0), "scheduled_amount_atomic", minimum=0
        )
        > 0
    ]
    return tuple(sorted(accepted, key=lambda row: str(row["order_id"])))


def estimate_scheduled_flow_impact(
    *,
    scheduled_amount_atomic: int,
    visible_liquidity_atomic: int,
    impact_cap_ppm: int = PPM,
) -> dict[str, int]:
    amount = integer(scheduled_amount_atomic, "scheduled_amount_atomic", minimum=0)
    liquidity = integer(visible_liquidity_atomic, "visible_liquidity_atomic", minimum=1)
    cap = integer(impact_cap_ppm, "impact_cap_ppm", minimum=0)
    estimate = min(cap, amount * PPM // liquidity)
    return {"estimated_impact_ppm": estimate, "scheduled_amount_atomic": amount}


def detect_post_execution_residual(
    *,
    execution_finalized: bool,
    pre_reference_atomic: int,
    post_state_atomic: int,
    minimum_residual_atomic: int,
) -> dict[str, int | bool]:
    if not isinstance(execution_finalized, bool):
        raise ValueError("execution_finalized must be bool")
    residual = integer(post_state_atomic, "post_state_atomic") - integer(
        pre_reference_atomic, "pre_reference_atomic"
    )
    minimum = integer(minimum_residual_atomic, "minimum_residual_atomic", minimum=0)
    return {
        "residual_atomic": residual,
        "eligible_post_state_only": execution_finalized and abs(residual) >= minimum,
    }


def enforce_orderflow_permissions(
    *,
    envelope: EvidenceEnvelope,
    public_or_opt_in: bool,
    execution_finalized: bool,
    attempts_pre_execution_ordering: bool,
) -> OfflineDecision:
    reasons: list[str] = []
    if public_or_opt_in is not True:
        reasons.append("ORDERFLOW_PERMISSION_MISSING")
    if execution_finalized is not True:
        reasons.append("ORDERFLOW_POST_STATE_NOT_FINALIZED")
    if attempts_pre_execution_ordering:
        reasons.append("HARMFUL_FRONTRUN_POLICY_FORBIDDEN")
    payload = {
        "public_or_opt_in": bool(public_or_opt_in),
        "execution_finalized": bool(execution_finalized),
        "attempts_pre_execution_ordering": bool(attempts_pre_execution_ordering),
    }
    return decision(
        "PR-189",
        envelope=envelope,
        payload=payload,
        reasons=reasons,
        research_only=True,
    )


__all__ = [
    "detect_post_execution_residual",
    "enforce_orderflow_permissions",
    "estimate_scheduled_flow_impact",
    "index_trigger_and_dca_orders",
]
