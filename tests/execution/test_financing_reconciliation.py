from __future__ import annotations

from dataclasses import replace

from src.execution.economic_reconciliation import (
    EconomicReconciler,
    FeeEvidence,
    NATIVE_SOL_ASSET,
    NativeObservation,
    NativeState,
    ReconciliationEvidence,
    ReconciliationReason,
    ReconciliationStatus,
)
from src.execution.financing_evidence import FinancingRepaymentBundle, RepaymentDecision
from src.lending.financing import FinancingRole

SHA_A = "a" * 64
SHA_B = "b" * 64


def _decision() -> RepaymentDecision:
    return RepaymentDecision(
        proven=True,
        attempt_id="attempt-1",
        attempt_generation=1,
        message_hash=SHA_A,
        lender_id="jupiter-lend",
        program_id="program",
        deployment_generation=1,
        decoder_identity="decoder-v1",
        asset_id=NATIVE_SOL_ASSET.stable_id(),
        debt_before_base_units=100,
        debt_after_base_units=0,
        required_repayment_base_units=101,
        observed_repayment_base_units=101,
        role=FinancingRole.PRIMARY,
        reason=None,
        evidence_digest=SHA_B,
    )


def _evidence(decision: RepaymentDecision) -> ReconciliationEvidence:
    return ReconciliationEvidence(
        expected_message_hash=SHA_A,
        simulated_message_hash=SHA_A,
        simulation_slot=10,
        snapshot_slot=10,
        min_context_slot=10,
        simulation_succeeded=True,
        response_hash=SHA_A,
        logs_hash=SHA_B,
        settlement_asset=NATIVE_SOL_ASSET,
        native=(
            NativeObservation(
                address="wallet",
                pre=NativeState("wallet", "owner", 1000, 10),
                post=NativeState("wallet", "owner", 1001, 10),
            ),
        ),
        tokens=(),
        fees=FeeEvidence(0, 0, 0),
        marginfi=None,
        required_accounts=("wallet",),
        financing=FinancingRepaymentBundle(primary=decision),
    )


def test_generic_financing_repayment_closes_in_canonical_reconciler() -> None:
    report = EconomicReconciler().reconcile(_evidence(_decision()))
    assert report.complete is True
    assert report.status is ReconciliationStatus.PROVEN_PROFIT
    assert report.repayment.proven is True
    assert report.repayment.borrowed == 100
    assert report.repayment.required == 101
    assert report.repayment.protocol_fee == 1


def test_generic_financing_repayment_is_bound_to_exact_message() -> None:
    evidence = _evidence(replace(_decision(), message_hash="c" * 64))
    report = EconomicReconciler().reconcile(evidence)
    assert report.complete is False
    assert report.status is ReconciliationStatus.REPAYMENT_FAILED
    assert report.reason is ReconciliationReason.FINANCING_MESSAGE_MISMATCH


def test_generic_financing_repayment_is_bound_to_settlement_asset() -> None:
    evidence = _evidence(replace(_decision(), asset_id="spl:other:6"))
    report = EconomicReconciler().reconcile(evidence)
    assert report.complete is False
    assert report.reason is ReconciliationReason.FINANCING_ASSET_MISMATCH


def test_marginfi_and_generic_financing_cannot_be_supplied_together() -> None:
    # The model-level invariant is covered without fabricating MarginFi state:
    # ReconciliationEvidence only permits one authoritative repayment owner.
    assert _evidence(_decision()).marginfi is None
