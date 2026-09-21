"""PR-194 / ECON-01 — finalized recovery attribution without PnL inflation."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .common import EvidenceEnvelope, OfflineDecision, decision, integer


def attribute_positive_slippage(
    *,
    quoted_output_atomic: int,
    finalized_output_atomic: int,
) -> int:
    quoted = integer(quoted_output_atomic, "quoted_output_atomic", minimum=0)
    finalized = integer(finalized_output_atomic, "finalized_output_atomic", minimum=0)
    return max(0, finalized - quoted)


def attribute_transaction_rebate(
    *,
    finalized_rebate_atomic: int,
    receipt_verified: bool,
) -> int:
    rebate = integer(finalized_rebate_atomic, "finalized_rebate_atomic", minimum=0)
    return rebate if receipt_verified else 0


def attribute_affiliate_or_fee_refund(
    *,
    finalized_refund_atomic: int,
    source_verified: bool,
) -> int:
    refund = integer(finalized_refund_atomic, "finalized_refund_atomic", minimum=0)
    return refund if source_verified else 0


def reconcile_recovery_components(
    components: Sequence[Mapping[str, Any]],
    *,
    envelope: EvidenceEnvelope,
    strategy_net_before_recoveries_atomic: int,
    finalized: bool,
) -> OfflineDecision:
    total = 0
    for component in components:
        amount = integer(component.get("amount_atomic", 0), "amount_atomic", minimum=0)
        if component.get("finalized") is True and component.get("source_verified") is True:
            total += amount
    base = integer(strategy_net_before_recoveries_atomic, "strategy_net_before_recoveries_atomic")
    reasons = () if finalized else ("RECOVERY_OUTCOME_NOT_FINALIZED",)
    payload = {
        "strategy_net_before_recoveries_atomic": base,
        "recovery_total_atomic": total,
        "accounting_total_atomic": base + total,
        "recoveries_are_strategy_alpha": False,
        "finalized": bool(finalized),
    }
    return decision("PR-194", envelope=envelope, payload=payload, reasons=reasons)


__all__ = [
    "attribute_affiliate_or_fee_refund",
    "attribute_positive_slippage",
    "attribute_transaction_rebate",
    "reconcile_recovery_components",
]
