from __future__ import annotations

from pathlib import Path

import pytest

from src.durability import DurableLifecycleStore
from src.economics.capital import (
    CapitalCandidate,
    CapitalEngineError,
    CapitalPolicy,
    NativeCostBreakdown,
)
from src.economics.durable_reservations import (
    DurableCapitalCoordinator,
    WalletBalanceSnapshot,
)
from src.economics.non_monotonic_sizing import (
    PR118AssetAmount,
    PR118CostComponentKind,
    PR118CostLedgerEntry,
    PR118FlashRepaymentTerms,
    PR118LedgerDirection,
    PR118SizingCandidateEvidence,
    PR118SizingStopReason,
    PR118TypedCostLedger,
    build_pr118_amount_grid,
    evaluate_pr118_non_monotonic_sizing,
)

QUOTE_A = "a" * 64
QUOTE_B = "b" * 64


def _policy() -> CapitalPolicy:
    return CapitalPolicy(
        protected_reserve_lamports=0,
        minimum_net_profit_lamports=1,
        maximum_priority_fee_lamports=10_000,
        maximum_jito_tip_lamports=10_000,
        maximum_peak_rent_lamports=10_000,
        contingency_lamports=0,
        maximum_flash_loan_lamports=1_000_000,
    )


def _snapshot() -> WalletBalanceSnapshot:
    return WalletBalanceSnapshot(
        wallet_pubkey="wallet111111111111111111111111111111111111",
        native_lamports=10_000_000,
        context_slot=123,
    )


def _coordinator(tmp_path: Path) -> DurableCapitalCoordinator:
    return DurableCapitalCoordinator(
        store=DurableLifecycleStore(tmp_path / "capital.db"),
        policy=_policy(),
    )


def _candidate(amount: int, profit: int) -> CapitalCandidate:
    return CapitalCandidate(
        candidate_id=f"amount-{amount}",
        guaranteed_min_out_lamports=amount + profit,
        flash_repayment_lamports=amount,
        requested_flash_loan_lamports=amount,
        native_costs=NativeCostBreakdown(base_network_fee_lamports=0),
        message_hash=f"message-{amount}",
    )


def _evidence(amount: int, profit: int) -> PR118SizingCandidateEvidence:
    return PR118SizingCandidateEvidence(
        amount_lamports=amount,
        candidate=_candidate(amount, profit),
        quote_hashes=(QUOTE_A, QUOTE_B),
        route_id=f"route-{amount}",
    )


def test_pr118_grid_is_bounded_and_not_binary_only() -> None:
    assert build_pr118_amount_grid(
        lower_lamports=10,
        upper_lamports=50,
        max_points=5,
    ) == (10, 20, 30, 40, 50)


def test_pr118_non_monotonic_search_selects_best_allowed_after_rejection(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    profits = {
        10: 5,
        20: -1,
        30: 80,
    }
    seen: list[int] = []

    result = evaluate_pr118_non_monotonic_sizing(
        coordinator=coordinator,
        wallet_snapshot=_snapshot(),
        amounts_lamports=(10, 20, 30),
        candidate_factory=lambda amount: seen.append(amount) or _evidence(
            amount,
            profits[amount],
        ),
        max_evaluations=10,
    )

    assert seen == [10, 20, 30]
    assert result.allowed is True
    assert result.selected_amount_lamports == 30
    assert result.stop_reason is PR118SizingStopReason.EVALUATED_ALL_POINTS
    assert [item.allowed for item in result.evaluations] == [True, False, True]
    assert result.selected is not None
    assert result.selected.decision.conservative_net_profit_lamports == 80


def test_pr118_request_budget_stops_without_assuming_monotonicity(
    tmp_path: Path,
) -> None:
    result = evaluate_pr118_non_monotonic_sizing(
        coordinator=_coordinator(tmp_path),
        wallet_snapshot=_snapshot(),
        amounts_lamports=(10, 20, 30),
        candidate_factory=lambda amount: _evidence(amount, amount),
        max_evaluations=2,
    )

    assert result.stop_reason is PR118SizingStopReason.REQUEST_BUDGET_EXHAUSTED
    assert result.evaluated_amounts == (10, 20)
    assert result.selected_amount_lamports == 20


def test_pr118_exact_amount_mismatch_is_rejected(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)

    with pytest.raises(CapitalEngineError, match="exact request"):
        evaluate_pr118_non_monotonic_sizing(
            coordinator=coordinator,
            wallet_snapshot=_snapshot(),
            amounts_lamports=(100,),
            candidate_factory=lambda amount: PR118SizingCandidateEvidence(
                amount_lamports=amount,
                candidate=_candidate(amount + 1, profit=10),
                quote_hashes=(QUOTE_A,),
            ),
            max_evaluations=1,
        )


def test_pr118_flash_repayment_prevents_protocol_fee_double_count() -> None:
    ledger = PR118TypedCostLedger(
        min_out=PR118AssetAmount("SOL", 1_050),
        flash_repayment=PR118FlashRepaymentTerms(
            asset_id="SOL",
            principal_amount=1_000,
            flash_fee_amount=3,
            protocol_rounding_amount=2,
        ),
        entries=(
            PR118CostLedgerEntry(
                asset_id="SOL",
                kind=PR118CostComponentKind.SLIPPAGE,
                amount=10,
            ),
        ),
    )

    candidate = ledger.to_capital_candidate(
        candidate_id="ledger-candidate",
        native_costs=NativeCostBreakdown(base_network_fee_lamports=0),
    )

    assert ledger.required_repayment_amount == 1_005
    assert ledger.conservative_net_amount() == 35
    assert candidate.flash_repayment_lamports == 1_005
    assert candidate.protocol_fee_lamports == 0
    assert candidate.conservative_net_profit_lamports() == 35


def test_pr118_ledger_rejects_duplicate_flash_fee_entry() -> None:
    with pytest.raises(CapitalEngineError, match="flash fee"):
        PR118TypedCostLedger(
            min_out=PR118AssetAmount("SOL", 1_050),
            flash_repayment=PR118FlashRepaymentTerms(
                asset_id="SOL",
                principal_amount=1_000,
                flash_fee_amount=3,
            ),
            entries=(
                PR118CostLedgerEntry(
                    asset_id="SOL",
                    kind=PR118CostComponentKind.FLASH_FEE,
                    amount=3,
                ),
            ),
        )


def test_pr118_non_settlement_asset_requires_conversion_contract() -> None:
    ledger = PR118TypedCostLedger(
        min_out=PR118AssetAmount("SOL", 1_050),
        flash_repayment=PR118FlashRepaymentTerms(
            asset_id="SOL",
            principal_amount=1_000,
            flash_fee_amount=3,
        ),
        entries=(
            PR118CostLedgerEntry(
                asset_id="USDC",
                kind=PR118CostComponentKind.PROVIDER_FEE,
                amount=1,
            ),
        ),
    )

    with pytest.raises(CapitalEngineError, match="conversion contract"):
        ledger.conservative_net_amount()


def test_pr118_credit_entries_use_integer_amounts_only() -> None:
    ledger = PR118TypedCostLedger(
        min_out=PR118AssetAmount("SOL", 1_050),
        flash_repayment=PR118FlashRepaymentTerms(
            asset_id="SOL",
            principal_amount=1_000,
            flash_fee_amount=3,
        ),
        entries=(
            PR118CostLedgerEntry(
                asset_id="SOL",
                kind=PR118CostComponentKind.RENT_REFUNDED,
                amount=5,
                direction=PR118LedgerDirection.CREDIT,
            ),
        ),
    )

    assert ledger.net_cost_by_asset() == {"SOL": -5}
    assert ledger.conservative_net_amount() == 52
    assert ledger.to_json()["min_out"]["amount"] == "1050"
