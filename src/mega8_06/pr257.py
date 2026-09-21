"""PR-257 / TCA-01: transaction-cost analysis and channel comparison."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Mega806Error, require_nonnegative_int, stable_hash


def decompose_transaction_costs(
    *,
    fees: int,
    impact: int,
    delay: int,
    opportunity_decay: int,
    recovery: int = 0,
) -> dict[str, int]:
    values = {
        "fees": require_nonnegative_int(fees, "fees"),
        "impact": require_nonnegative_int(impact, "impact"),
        "delay": require_nonnegative_int(delay, "delay"),
        "opportunity_decay": require_nonnegative_int(
            opportunity_decay, "opportunity_decay"
        ),
        "recovery": require_nonnegative_int(recovery, "recovery"),
    }
    gross = (
        values["fees"]
        + values["impact"]
        + values["delay"]
        + values["opportunity_decay"]
    )
    values["total"] = max(0, gross - values["recovery"])
    return values


def benchmark_execution_shortfall(intended_output: int, finalized_output: int) -> int:
    intended_output = require_nonnegative_int(intended_output, "intended_output")
    finalized_output = require_nonnegative_int(finalized_output, "finalized_output")
    return max(0, intended_output - finalized_output)


def compare_submission_channels(
    rows: Sequence[Mapping[str, object]],
) -> tuple[tuple[str, int], ...]:
    scored = []
    for row in rows:
        name = str(row.get("channel", "")).strip()
        if not name:
            raise Mega806Error("channel is required")
        if row.get("settled") is not True:
            continue
        cost = require_nonnegative_int(row.get("cost"), "cost")
        shortfall = require_nonnegative_int(row.get("shortfall"), "shortfall")
        ambiguity = require_nonnegative_int(
            row.get("ambiguity_cost", 0), "ambiguity_cost"
        )
        scored.append((name, cost + shortfall + ambiguity))
    if not scored:
        raise Mega806Error("NO_FINALIZED_CHANNEL_EVIDENCE")
    return tuple(sorted(scored, key=lambda item: (item[1], item[0])))


def publish_tca_report(
    strategy_id: str, cost_rows: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    if not strategy_id.strip():
        raise Mega806Error("strategy_id is required")
    normalized = tuple(sorted((dict(row) for row in cost_rows), key=lambda r: str(r)))
    return {
        "strategy_id": strategy_id,
        "rows": normalized,
        "report_sha256": stable_hash((strategy_id, normalized)),
        "realized_only": True,
    }
