from __future__ import annotations

import hashlib
from dataclasses import dataclass

from src.execution.models import Instruction, TransactionPlan

from .models import (
    ExecutionProfile,
    FlashLoanPlan,
    OrderbookInstructionPlan,
    OrderbookMarketSnapshot,
    OrderbookReject,
    OrderbookRejectCode,
)


@dataclass(frozen=True, slots=True)
class OrderbookAmmCandidate:
    opportunity_id: str
    payer: str
    authority: str
    direction: str
    snapshot: OrderbookMarketSnapshot
    orderbook_plan: OrderbookInstructionPlan
    amm_instructions: tuple[Instruction, ...]
    flash_loan_plan: FlashLoanPlan
    profile: ExecutionProfile
    min_repayment: int
    required_signers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlannedOrderbookAmm:
    transaction_plan: TransactionPlan
    plan_hash: str
    monitored_accounts: tuple[str, ...]


class OrderbookAmmPlanner:
    def plan(self, c: OrderbookAmmCandidate) -> PlannedOrderbookAmm:
        if not c.profile:
            raise OrderbookReject(
                OrderbookRejectCode.ORDERBOOK_PROFILE_MISSING,
                "missing profile",
            )
        if abs(c.snapshot.context_slot - c.snapshot.source_slot) > c.profile.max_slot_skew:
            raise OrderbookReject(
                OrderbookRejectCode.SLOT_INCONSISTENT,
                "slot policy",
            )

        strategy = (
            (
                *c.orderbook_plan.instructions,
                *c.orderbook_plan.settlement_instructions,
                *c.amm_instructions,
            )
            if c.direction == "CLOB_TO_AMM"
            else (
                *c.amm_instructions,
                *c.orderbook_plan.instructions,
                *c.orderbook_plan.settlement_instructions,
            )
        )
        if any(ix.kind in {"sender", "assembled_transaction"} for ix in strategy):
            raise OrderbookReject(
                OrderbookRejectCode.UNKNOWN_VENUE_OR_POOL,
                "non-composable instruction",
            )
        accounts = tuple(dict.fromkeys(a for ix in strategy for a in ix.accounts))
        if len(accounts) > c.profile.max_static_accounts:
            raise OrderbookReject(
                OrderbookRejectCode.ORDERBOOK_PROFILE_EXCEEDED,
                "account profile exceeded",
            )

        _legacy_plan_hash = hashlib.sha256(
            b"".join(ix.stable_bytes() for ix in strategy)
            + c.snapshot.raw_market_hash.encode()
        ).hexdigest()
        raise OrderbookReject(
            OrderbookRejectCode.SETTLEMENT_PATH_UNPROVEN,
            "orderbook AMM planner still uses legacy string instructions; "
            "a Solders v0 planner is required after PR-053 canonical cutover",
            {
                "opportunity_id": c.opportunity_id,
                "legacy_plan_hash": _legacy_plan_hash,
                "venue_kind": c.snapshot.venue_spec.venue_kind.value,
            },
        )
