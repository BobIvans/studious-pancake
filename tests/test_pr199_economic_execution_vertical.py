from types import SimpleNamespace

import pytest

from src.domain.money import WSOL_MINT
from src.economics.execution_vertical_pr199 import (
    EconomicIdentity,
    FinalMessageBinding,
    ImmutablePaperReconciliation,
    PR199EconomicError,
    PaperOutcome,
    assess_shadow_opportunity_pr199,
)
from src.strategy.domain import Opportunity

_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64
_HASH_D = "d" * 64
_HASH_E = "e" * 64
_HASH_F = "f" * 64
_HASH_1 = "1" * 64
_HASH_2 = "2" * 64
_HASH_3 = "3" * 64
_HASH_4 = "4" * 64
_HASH_5 = "5" * 64
_HASH_6 = "6" * 64


def _config(wallet_lamports: int = 20_000_000):
    return SimpleNamespace(
        monetary=SimpleNamespace(
            wallet_lamports=wallet_lamports,
            protected_reserve_lamports=1_000_000,
            minimum_net_profit_lamports=100_000,
            maximum_priority_fee_lamports=500_000,
            contingency_lamports=50_000,
        )
    )


def _opportunity(metadata):
    return Opportunity.create(
        strategy_name="circular_arbitrage",
        opportunity_type="two_leg_circular_snapshot",
        detection_slot=10,
        input_mint=WSOL_MINT,
        output_mint=WSOL_MINT,
        proposed_amount_base_units=1_000_000_000,
        expected_gross_profit=int(metadata.get("gross_profit_base_units", 0)),
        ttl_seconds=1.0,
        metadata=metadata,
        detected_at=1.0,
    )


def _cost_metadata(**overrides):
    payload = {
        "gross_profit_base_units": 2_000_000,
        "projected_final_base_units": 1_002_000_000,
        "flash_repayment_lamports": 1_000_000_000,
        "base_network_fee_lamports": 5_000,
        "priority_fee_lamports": 10_000,
        "jito_tip_lamports": 20_000,
        "peak_rent_lamports": 2_000_000,
        "rent_loss_lamports": 0,
        "protocol_fee_lamports": 0,
        "slippage_buffer_lamports": 100_000,
        "uncertainty_buffer_lamports": 100_000,
        "message_hash": _HASH_A,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_pr199_blocks_strong_gross_edge_without_cost_evidence():
    report = assess_shadow_opportunity_pr199(
        _opportunity({"gross_profit_base_units": 5_000_000}),
        _config(),
    )

    assert report.allowed is False
    assert report.reason_code == "pr199_cost_evidence_missing"
    assert report.details["error_code"] == "PR199_COST_EVIDENCE_MISSING"


@pytest.mark.asyncio
async def test_pr199_keeps_legacy_weak_edge_rejection_code():
    report = assess_shadow_opportunity_pr199(
        _opportunity({"gross_profit_base_units": 1}),
        _config(),
    )

    assert report.allowed is False
    assert report.reason_code == "no_trade_insufficient_prechecked_edge"


@pytest.mark.asyncio
async def test_pr199_accepts_only_positive_net_after_all_costs():
    report = assess_shadow_opportunity_pr199(
        _opportunity(_cost_metadata()),
        _config(wallet_lamports=30_000_000),
    )

    assert report.allowed is True
    assert report.decision is not None
    assert report.decision.conservative_net_profit_lamports == 1_765_000
    assert report.details["economic_gate"] == "pr199_mint_cost_bound_capital_gate"


@pytest.mark.asyncio
async def test_pr199_gross_profit_can_be_rejected_after_tip_fee_and_buffers():
    report = assess_shadow_opportunity_pr199(
        _opportunity(
            _cost_metadata(
                base_network_fee_lamports=200_000,
                priority_fee_lamports=100_000,
                jito_tip_lamports=300_000,
                protocol_fee_lamports=900_000,
                slippage_buffer_lamports=400_000,
                uncertainty_buffer_lamports=200_000,
            )
        ),
        _config(wallet_lamports=30_000_000),
    )

    assert report.allowed is False
    expected = "no_trade_non_positive_conservative_net_profit"
    assert report.reason_code == expected


def _identity() -> EconomicIdentity:
    return EconomicIdentity(
        logical_opportunity_id="opp-1",
        attempt_generation=1,
        evidence_generation_hash=_HASH_A,
        policy_hash=_HASH_B,
        route_hash=_HASH_C,
        plan_hash=_HASH_D,
    )


def _binding(message_hash: str = _HASH_E) -> FinalMessageBinding:
    return FinalMessageBinding(
        plan_hash=_HASH_D,
        compiled_message_hash=message_hash,
        blockhash_context_hash=_HASH_F,
        alt_evidence_hash=_HASH_1,
        account_metas_hash=_HASH_2,
        instruction_order_hash=_HASH_3,
        exact_simulation_hash=_HASH_4,
        exact_simulation_message_hash=message_hash,
        final_fee_hash=_HASH_5,
    )


def test_pr199_message_mutation_after_simulation_invalidates_permit():
    binding = _binding()

    with pytest.raises(PR199EconomicError, match="modified message") as excinfo:
        binding.assert_unchanged_for_permit(permit_message_hash=_HASH_6)

    assert excinfo.value.code == "PR199_PERMIT_MESSAGE_HASH_MISMATCH"


def test_pr199_reconciliation_separates_paper_from_finalized_live_evidence():
    report = assess_shadow_opportunity_pr199(
        _opportunity(_cost_metadata()),
        _config(wallet_lamports=30_000_000),
    )
    assert report.decision is not None

    with pytest.raises(PR199EconomicError) as excinfo:
        ImmutablePaperReconciliation(
            identity=_identity(),
            capital_decision=report.decision,
            final_message=_binding(),
            simulated_net_profit_lamports=1_000_000,
            conservative_net_profit_lamports=1_000_000,
            reconciliation_hash=_HASH_6,
            outcome=PaperOutcome.RECONCILED_PAPER_SUCCESS,
            finalized_live_hash=_HASH_A,
        )

    assert excinfo.value.code == "PR199_FINALIZED_LIVE_DATA_FORBIDDEN_IN_PAPER"
