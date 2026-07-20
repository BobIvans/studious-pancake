"""Runtime adapter from detected opportunities to the PR-057 capital gate."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from src.economics.capital import (
    AtomicCapitalLedger,
    CapitalCandidate,
    CapitalEngineError,
    CapitalPolicy,
    NativeCostBreakdown,
    PolicyProfile,
)
from src.economics.durable_reservations import DurableCapitalLedger
from src.strategy.consumer import PrecheckDecision
from src.strategy.domain import Opportunity


class CapitalLedgerProtocol(Protocol):
    policy: CapitalPolicy

    def evaluate(self, candidate: CapitalCandidate) -> Any: ...

    def reserve(self, candidate: CapitalCandidate) -> Any: ...


class WalletSnapshotRequiredPrecheck:
    """Fail closed until the runtime supplies an actual wallet balance snapshot."""

    async def assess(self, opportunity: Opportunity) -> PrecheckDecision:
        return PrecheckDecision(
            allowed=False,
            reason_code="capital_wallet_snapshot_missing",
            details={
                "opportunity_id": opportunity.opportunity_id,
                "strategy_name": opportunity.strategy_name,
                "required_input": "wallet_balance_lamports",
            },
        )


class CapitalEngineOpportunityPrecheck:
    """Canonical PR-032/057 capital engine adapter for application opportunities."""

    def __init__(self, ledger: CapitalLedgerProtocol, *, reserve: bool = False) -> None:
        self.ledger = ledger
        self.reserve = reserve

    async def assess(self, opportunity: Opportunity) -> PrecheckDecision:
        try:
            candidate = opportunity_to_capital_candidate(opportunity)
            decision = (
                self.ledger.reserve(candidate)
                if self.reserve
                else self.ledger.evaluate(candidate)
            )
        except CapitalEngineError as exc:
            return PrecheckDecision(
                allowed=False,
                reason_code="capital_candidate_invalid",
                details={
                    "opportunity_id": opportunity.opportunity_id,
                    "error": str(exc),
                },
            )

        return PrecheckDecision(
            allowed=decision.allowed,
            reason_code=decision.reason.value,
            details=decision.to_json(),
        )


def build_capital_precheck(
    config: Any = None,
    *,
    wallet_lamports: int | None = None,
    reservations_db_path: str | Path | None = None,
    reserve: bool = False,
) -> CapitalEngineOpportunityPrecheck | WalletSnapshotRequiredPrecheck:
    """Build the supported runtime precheck from config plus a wallet snapshot.

    PR-057 deliberately refuses to invent wallet balance.  If the composition
    root has not supplied a balance from RPC or a recorded fixture, the returned
    precheck rejects every opportunity with a stable NO_TRADE reason instead of
    falling back to the old gross-profit-only heuristic.
    """

    policy = _policy_from_config(config)
    resolved_wallet = _first_int(
        wallet_lamports,
        _nested(config, "wallet_balance_lamports"),
        _nested(config, "capital_wallet_lamports"),
        _nested(config, "runtime", "wallet_balance_lamports"),
        _nested(config, "monetary", "wallet_balance_lamports"),
    )
    if resolved_wallet is None:
        return WalletSnapshotRequiredPrecheck()

    resolved_db_path = reservations_db_path or _nested(
        config,
        "runtime",
        "capital_reservations_db_path",
    ) or _nested(config, "capital_reservations_db_path")
    if resolved_db_path:
        ledger: CapitalLedgerProtocol = DurableCapitalLedger(
            resolved_db_path,
            wallet_lamports=resolved_wallet,
            policy=policy,
        )
    else:
        ledger = AtomicCapitalLedger(wallet_lamports=resolved_wallet, policy=policy)
    return CapitalEngineOpportunityPrecheck(ledger, reserve=reserve)


def opportunity_to_capital_candidate(opportunity: Opportunity) -> CapitalCandidate:
    metadata = opportunity.metadata
    requested_flash_loan = _lamports(
        metadata,
        "requested_flash_loan_lamports",
        default=opportunity.proposed_amount_base_units,
    )
    flash_repayment = _lamports(
        metadata,
        "flash_repayment_lamports",
        default=requested_flash_loan,
    )
    gross_profit = _lamports(
        metadata,
        "gross_profit_lamports",
        aliases=("gross_profit_base_units",),
        default=None,
    )
    guaranteed_min_out = _lamports(
        metadata,
        "guaranteed_min_out_lamports",
        aliases=("guaranteed_min_out_base_units",),
        default=(None if gross_profit is None else flash_repayment + gross_profit),
    )
    if guaranteed_min_out is None:
        raise CapitalEngineError(
            "opportunity requires guaranteed_min_out_lamports or gross_profit_lamports"
        )

    fee = _lamports(
        metadata,
        "base_network_fee_lamports",
        aliases=("estimated_base_network_fee_lamports", "base_fee_lamports"),
        default=0,
    )
    native_costs = NativeCostBreakdown(
        base_network_fee_lamports=fee,
        priority_fee_lamports=_lamports(
            metadata,
            "priority_fee_lamports",
            aliases=("estimated_priority_fee_lamports",),
            default=0,
        ),
        jito_tip_lamports=_lamports(
            metadata,
            "jito_tip_lamports",
            aliases=("estimated_jito_tip_lamports",),
            default=0,
        ),
        peak_rent_lamports=_lamports(
            metadata,
            "peak_rent_lamports",
            aliases=("estimated_peak_rent_lamports",),
            default=0,
        ),
        rent_loss_lamports=_lamports(
            metadata,
            "rent_loss_lamports",
            aliases=("estimated_rent_loss_lamports",),
            default=0,
        ),
    )
    message_hash = metadata.get("message_hash")
    if message_hash is not None and not isinstance(message_hash, str):
        raise CapitalEngineError("message_hash must be a string when present")

    return CapitalCandidate(
        candidate_id=opportunity.opportunity_id,
        guaranteed_min_out_lamports=guaranteed_min_out,
        flash_repayment_lamports=flash_repayment,
        requested_flash_loan_lamports=requested_flash_loan,
        native_costs=native_costs,
        protocol_fee_lamports=_lamports(metadata, "protocol_fee_lamports", default=0),
        slippage_buffer_lamports=_lamports(
            metadata,
            "slippage_buffer_lamports",
            default=0,
        ),
        uncertainty_buffer_lamports=_lamports(
            metadata,
            "uncertainty_buffer_lamports",
            default=0,
        ),
        message_hash=message_hash,
    )


def _policy_from_config(config: Any) -> CapitalPolicy:
    if config is None or not hasattr(config, "monetary"):
        return CapitalPolicy(profile=PolicyProfile.PAPER)
    return CapitalPolicy.from_runtime_config(config, profile=PolicyProfile.PAPER)


def _lamports(
    metadata: Mapping[str, Any],
    key: str,
    *,
    aliases: tuple[str, ...] = (),
    default: int | None,
) -> int | None:
    for candidate_key in (key, *aliases):
        if candidate_key in metadata:
            value = metadata[candidate_key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CapitalEngineError(
                    f"{candidate_key} must be non-negative int lamports"
                )
            return value
    return default


def _nested(root: Any, *path: str) -> Any:
    current = root
    for part in path:
        if current is None:
            return None
        if isinstance(current, Mapping):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
    return current


def _first_int(*values: Any) -> int | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise CapitalEngineError(
                "wallet balance snapshot must be non-negative int lamports"
            )
        return value
    return None
