from __future__ import annotations

from dataclasses import replace

import pytest

from src.mpr42_exact_economic_settlement_authority import (
    AssetAmount,
    CostBreakdown,
    EconomicLayer,
    FinalizedSettlementProof,
    MPR42State,
    PnLLayerEvidence,
    QuarantineReason,
    SettlementStatus,
    TransactionPlanProof,
    evaluate_mpr42_evidence,
    reject_non_finite_number,
    sample_ready_evidence,
)


def _codes(report: object) -> set[str]:
    return {blocker.code for blocker in report.blockers}  # type: ignore[attr-defined]


def test_ready_foundation_is_sender_free_and_reusable_capital_safe() -> None:
    report = evaluate_mpr42_evidence(sample_ready_evidence())

    assert report.schema_version == "mpr42.exact-economic-settlement-authority.v1"
    assert report.state is MPR42State.READY_FOR_FOUNDATION
    assert report.blockers == ()
    assert report.layers_present == ("expected", "paper_realized", "simulated")
    assert report.live_execution_allowed is False
    assert report.capital_reuse_allowed is True


@pytest.mark.parametrize("bad_value", [1.1, float("nan"), float("inf"), True, "100"])
def test_economic_ingress_rejects_non_integer_or_non_finite_values(bad_value: object) -> None:
    with pytest.raises(ValueError):
        reject_non_finite_number(bad_value, "economic_value")


def test_cost_breakdown_must_add_up_exactly() -> None:
    sample = sample_ready_evidence()
    cost = sample.pnl_layers[0].costs

    with pytest.raises(ValueError, match="MPR42_COST_TOTAL_MISMATCH"):
        replace(cost, total_cost_lamports=cost.total_cost_lamports + 1)


def test_transaction_plan_rejects_message_drift_before_evaluation() -> None:
    sample = sample_ready_evidence()
    with pytest.raises(ValueError, match="MPR42_COMPILED_MESSAGE_DRIFT"):
        replace(sample.plan, compiled_message_hash="b" * 64)


def test_blockhash_margin_is_checked_at_plan_boundary() -> None:
    sample = sample_ready_evidence()
    with pytest.raises(ValueError, match="MPR42_BLOCKHASH_MARGIN_EXPIRED"):
        replace(sample.plan, observed_block_height=170, last_valid_block_height=180)


def test_final_simulation_message_mismatch_blocks_report() -> None:
    sample = sample_ready_evidence()
    evidence = replace(
        sample,
        simulation=replace(sample.simulation, simulated_message_hash="c" * 64),
    )

    report = evaluate_mpr42_evidence(evidence)

    assert report.state is MPR42State.BLOCKED
    assert "MPR42_MESSAGE_HASH_DRIFT" in _codes(report)
    assert "MPR42_EXACT_SIMULATION_NOT_BOUND" in _codes(report)


def test_final_simulation_must_succeed_and_decode_from_raw_state() -> None:
    sample = sample_ready_evidence()
    evidence = replace(
        sample,
        simulation=replace(
            sample.simulation,
            simulation_success=False,
            decoded_from_raw_state=False,
        ),
    )

    report = evaluate_mpr42_evidence(evidence)

    assert report.state is MPR42State.BLOCKED
    assert "MPR42_FINAL_SIMULATION_FAILED" in _codes(report)
    assert "MPR42_CALLER_DECODED_ECONOMICS" in _codes(report)


def test_reservation_cannot_under_reserve_capital() -> None:
    sample = sample_ready_evidence()

    with pytest.raises(ValueError, match="MPR42_UNDER_RESERVED_CAPITAL"):
        replace(sample.reservation, reserved_lamports=1)


def test_required_pnl_layers_cannot_be_missing() -> None:
    sample = sample_ready_evidence()
    evidence = replace(sample, pnl_layers=(sample.pnl_layers[0],))

    report = evaluate_mpr42_evidence(evidence)

    assert report.state is MPR42State.BLOCKED
    assert "MPR42_REQUIRED_PNL_LAYER_MISSING" in _codes(report)


def test_live_realized_pnl_requires_finalized_settlement_evidence() -> None:
    sample = sample_ready_evidence()
    base_layer = sample.pnl_layers[0]
    live_layer = PnLLayerEvidence(
        layer=EconomicLayer.LIVE_REALIZED,
        message_hash=base_layer.message_hash,
        gross=AssetAmount("SOL", 3_500_000, 9, base_layer.gross.metadata_digest),
        costs=base_layer.costs,
        net=AssetAmount("SOL", 1_334_720, 9, base_layer.net.metadata_digest, allow_negative=True),
        provenance_digest="d" * 64,
        strict_positive_threshold_atomic=1,
    )
    evidence = replace(
        sample,
        pnl_layers=sample.pnl_layers + (live_layer,),
        settlement=FinalizedSettlementProof(
            status=SettlementStatus.JITO_ACK,
            message_hash=sample.plan.immutable_message_hash,
            signature_hash="e" * 64,
            finalized_slot=None,
            payer_delta_hash=None,
            token_delta_hash=None,
            economic_ledger_hash=None,
        ),
    )

    report = evaluate_mpr42_evidence(evidence)

    assert report.state is MPR42State.BLOCKED
    assert "MPR42_LIVE_REALIZED_WITHOUT_FINALITY" in _codes(report)
    assert "MPR42_FINALIZED_SETTLEMENT_INCOMPLETE" in _codes(report)
    assert "MPR42_TRANSPORT_STATUS_NOT_FINAL" in _codes(report)


def test_ack_or_bundle_id_cannot_be_used_as_profit() -> None:
    sample = sample_ready_evidence()
    evidence = replace(
        sample,
        settlement=replace(sample.settlement, ack_or_bundle_id_used_as_profit=True),
    )

    report = evaluate_mpr42_evidence(evidence)

    assert report.state is MPR42State.BLOCKED
    assert "MPR42_ACK_USED_AS_PROFIT" in _codes(report)


def test_unresolved_settlement_requires_quarantine_and_blocks_capital_reuse() -> None:
    sample = sample_ready_evidence()
    evidence = replace(
        sample,
        settlement=replace(sample.settlement, status=SettlementStatus.UNRESOLVED),
    )

    report = evaluate_mpr42_evidence(evidence)

    assert report.state is MPR42State.BLOCKED
    assert report.capital_reuse_allowed is False
    assert "MPR42_UNRESOLVED_NOT_QUARANTINED" in _codes(report)


def test_unresolved_quarantine_requires_reason_manual_review_and_capital_lock() -> None:
    sample = sample_ready_evidence()
    evidence = replace(
        sample,
        quarantine=replace(
            sample.quarantine,
            unresolved=True,
            reasons=(QuarantineReason.MESSAGE_DRIFT,),
            capital_reuse_blocked=False,
            manual_review_required=False,
        ),
    )

    report = evaluate_mpr42_evidence(evidence)

    assert report.state is MPR42State.BLOCKED
    assert "MPR42_UNRESOLVED_CAPITAL_REUSE" in _codes(report)
    assert "MPR42_UNRESOLVED_WITHOUT_MANUAL_REVIEW" in _codes(report)


def test_unrestricted_live_remains_forbidden() -> None:
    sample = sample_ready_evidence()
    report = evaluate_mpr42_evidence(replace(sample, unrestricted_live_enabled=True))

    assert report.state is MPR42State.BLOCKED
    assert report.live_execution_allowed is False
    assert "MPR42_UNRESTRICTED_LIVE_FORBIDDEN" in _codes(report)


def test_attempt_generation_must_start_at_one() -> None:
    sample = sample_ready_evidence()

    with pytest.raises(ValueError, match="MPR42_ATTEMPT_GENERATION_MIN_ONE"):
        replace(sample.plan, attempt_generation=0)


def test_plan_model_rejects_negative_block_heights() -> None:
    sample = sample_ready_evidence()

    with pytest.raises(ValueError, match="MPR42_NEGATIVE_BLOCK_HEIGHT"):
        TransactionPlanProof(
            **{**sample.plan.__dict__, "observed_block_height": -1}
        )


def test_bool_is_not_an_integer_amount() -> None:
    sample = sample_ready_evidence()

    with pytest.raises(ValueError, match="atomic_value must be a strict integer"):
        replace(sample.pnl_layers[0].gross, atomic_value=True)  # type: ignore[arg-type]


def test_finalized_live_layer_is_accepted_only_with_complete_finalized_evidence() -> None:
    sample = sample_ready_evidence()
    base_layer = sample.pnl_layers[0]
    live_layer = PnLLayerEvidence(
        layer=EconomicLayer.LIVE_REALIZED,
        message_hash=base_layer.message_hash,
        gross=AssetAmount("SOL", 3_500_000, 9, base_layer.gross.metadata_digest),
        costs=base_layer.costs,
        net=AssetAmount("SOL", 1_334_720, 9, base_layer.net.metadata_digest, allow_negative=True),
        provenance_digest="f" * 64,
        strict_positive_threshold_atomic=1,
    )
    evidence = replace(
        sample,
        pnl_layers=sample.pnl_layers + (live_layer,),
        settlement=FinalizedSettlementProof(
            status=SettlementStatus.FINALIZED,
            message_hash=sample.plan.immutable_message_hash,
            signature_hash="1" * 64,
            finalized_slot=42,
            payer_delta_hash="2" * 64,
            token_delta_hash="3" * 64,
            economic_ledger_hash="4" * 64,
        ),
    )

    report = evaluate_mpr42_evidence(evidence)

    assert report.state is MPR42State.READY_FOR_FOUNDATION
    assert report.realized_settlement_allowed is True
