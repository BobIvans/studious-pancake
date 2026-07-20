from __future__ import annotations

import pytest

from src.evidence.shadow_soak import (
    RECONCILED_REASON,
    ShadowOutcomeRecord,
    ShadowSoakAnalyzer,
    ShadowSoakThresholds,
)
from src.live_canary import (
    AdmissionReason,
    CanaryCandidate,
    CanaryMode,
    CanaryPolicy,
    LatchCode,
    LimitedLiveCanaryController,
    OPERATOR_ACKNOWLEDGEMENT,
    OperatorIdentity,
    ReconciliationResult,
    ReconciliationStatus,
    RuntimeSafetySnapshot,
)

A = "a" * 64
B = "b" * 64
C = "c" * 64
PROGRAM = "ComputeBudget111111111111111111111111111111"


def controller_and_operator():
    policy = CanaryPolicy(
        enabled=True,
        mode=CanaryMode.LIMITED_LIVE,
        allowlisted_pairs=("SOL/USDC",),
        allowlisted_program_ids=(PROGRAM,),
        allowlisted_providers=("jupiter",),
        max_principal_base_units=1_000_000,
        deployment_principal_ceiling_base_units=1_000_000,
        max_wallet_spend_lamports=100_000,
        deployment_wallet_spend_ceiling_lamports=100_000,
        minimum_wallet_reserve_lamports=10_000_000,
        maximum_daily_loss_lamports=1_000_000,
        maximum_consecutive_failures=2,
        maximum_data_age_ms=1_000,
        maximum_rpc_slot_divergence=2,
        operator_confirmation_ttl_ms=10_000,
    )
    record = ShadowOutcomeRecord(
        opportunity_id="shadow-opportunity",
        attempt_id="shadow-attempt",
        plan_hash=A,
        message_hash=B,
        reconciliation_hash=C,
        terminal_reason=RECONCILED_REASON,
        created_at=1,
        completed_at=2,
        conservative_quote_pnl=1,
        simulated_executable_pnl=1,
        simulation_success=True,
        repayment_proven=True,
    )
    thresholds = ShadowSoakThresholds(
        minimum_samples=1,
        minimum_duration_seconds=0,
        maximum_unexplained_mismatches=0,
        maximum_unclassified_failures=0,
        maximum_false_positive_rate_bps=0,
    )
    bundle = ShadowSoakAnalyzer([record], thresholds=thresholds).build_bundle()
    controller = LimitedLiveCanaryController(policy)
    operator = OperatorIdentity("operator-alice")
    review = controller.review_shadow_evidence(
        bundle,
        reviewer=operator,
        review_reference="review-1",
        reviewed_at_ms=10,
    )
    ack = controller.acknowledge_policy(
        operator=operator,
        policy_hash=policy.policy_hash,
        evidence_hash=review.evidence_hash,
        acknowledgement=OPERATOR_ACKNOWLEDGEMENT,
        acknowledged_at_ms=20,
    )
    controller.arm(
        operator=operator,
        acknowledgement_id=ack.acknowledgement_id,
        armed_at_ms=30,
    )
    return controller, operator


def candidate(attempt_id: str = "live-attempt-1") -> CanaryCandidate:
    return CanaryCandidate(
        attempt_id=attempt_id,
        pair="SOL/USDC",
        provider="jupiter",
        program_ids=(PROGRAM,),
        principal_base_units=1_000_000,
        wallet_spend_lamports=100_000,
        plan_hash=A,
        message_hash=B,
        observed_at_ms=100,
    )


def snapshot(**overrides) -> RuntimeSafetySnapshot:
    values = {
        "now_ms": 100,
        "wallet_balance_lamports": 20_000_000,
        "daily_realized_pnl_lamports": 0,
        "consecutive_failures": 0,
        "data_observed_at_ms": 100,
        "reconciliation_ambiguous": False,
        "rpc_primary_slot": 100,
        "rpc_secondary_slot": 100,
    }
    values.update(overrides)
    return RuntimeSafetySnapshot(**values)


@pytest.mark.parametrize(
    ("runtime", "expected"),
    [
        (snapshot(daily_realized_pnl_lamports=-1_000_000), LatchCode.DAILY_LOSS_LIMIT),
        (snapshot(consecutive_failures=2), LatchCode.CONSECUTIVE_FAILURE_LIMIT),
        (snapshot(now_ms=2_000, data_observed_at_ms=100), LatchCode.STALE_DATA),
        (
            snapshot(rpc_primary_slot=100, rpc_secondary_slot=103),
            LatchCode.RPC_DIVERGENCE,
        ),
        (snapshot(reconciliation_ambiguous=True), LatchCode.RECONCILIATION_AMBIGUITY),
    ],
)
def test_runtime_latches_are_sticky_and_fail_closed(
    runtime: RuntimeSafetySnapshot, expected: LatchCode
) -> None:
    controller, _ = controller_and_operator()
    decision = controller.evaluate(candidate(), runtime)
    assert not decision.allowed
    assert AdmissionReason.ACTIVE_LATCH in decision.reasons
    assert expected in controller.report().active_latches


def test_low_balance_uses_post_spend_reserve() -> None:
    controller, _ = controller_and_operator()
    decision = controller.evaluate(
        candidate(), snapshot(wallet_balance_lamports=10_050_000)
    )
    assert AdmissionReason.WALLET_RESERVE_BREACH in decision.reasons
    assert LatchCode.LOW_BALANCE in controller.report().active_latches


def test_indeterminate_reconciliation_keeps_outstanding_and_latches() -> None:
    controller, _ = controller_and_operator()
    proposed = candidate()
    decision = controller.evaluate(proposed, snapshot())
    controller.reserve_submission(decision, proposed, reserved_at_ms=101)

    report = controller.record_reconciliation(
        ReconciliationResult(
            attempt_id=proposed.attempt_id,
            message_hash=proposed.message_hash,
            reconciliation_hash=C,
            status=ReconciliationStatus.INDETERMINATE,
            realized_pnl_lamports=0,
            observed_at_ms=102,
        )
    )
    assert report.outstanding_attempt_id == proposed.attempt_id
    assert LatchCode.RECONCILIATION_AMBIGUITY in report.active_latches


def test_manual_kill_and_rollback_require_new_arm() -> None:
    controller, operator = controller_and_operator()
    controller.manual_kill(
        operator=operator, reason="operator stop", observed_at_ms=200
    )
    assert controller.mode is CanaryMode.SHADOW
    assert LatchCode.MANUAL_KILL_SWITCH in controller.report().active_latches

    controller.clear_latches(
        operator=operator, reason="incident reviewed", observed_at_ms=201
    )
    decision = controller.evaluate(
        candidate(), snapshot(now_ms=202, data_observed_at_ms=202)
    )
    assert AdmissionReason.CANARY_NOT_ARMED in decision.reasons

    controller.rollback_to_shadow(
        operator=operator, reason="return to shadow", observed_at_ms=203
    )
    report = controller.report()
    assert report.mode is CanaryMode.SHADOW
    assert not report.armed
    assert report.ai_authority is False
    assert len(report.report_hash) == 64


def test_two_failures_activate_loss_and_failure_latches() -> None:
    controller, operator = controller_and_operator()
    for index, message_char in enumerate(("b", "d")):
        proposed = CanaryCandidate(
            attempt_id=f"live-attempt-{index}",
            pair="SOL/USDC",
            provider="jupiter",
            program_ids=(PROGRAM,),
            principal_base_units=1_000_000,
            wallet_spend_lamports=100_000,
            plan_hash=A,
            message_hash=message_char * 64,
            observed_at_ms=100 + index * 10,
        )
        runtime = snapshot(
            now_ms=100 + index * 10,
            data_observed_at_ms=100 + index * 10,
        )
        decision = controller.evaluate(proposed, runtime)
        assert decision.allowed
        controller.reserve_submission(decision, proposed, reserved_at_ms=runtime.now_ms)
        controller.record_reconciliation(
            ReconciliationResult(
                attempt_id=proposed.attempt_id,
                message_hash=proposed.message_hash,
                reconciliation_hash=("e" if index == 0 else "f") * 64,
                status=ReconciliationStatus.FAILURE,
                realized_pnl_lamports=-500_000,
                observed_at_ms=runtime.now_ms + 1,
            )
        )
        if index == 0:
            review = controller.review_shadow_evidence(
                ShadowSoakAnalyzer(
                    [
                        ShadowOutcomeRecord(
                            opportunity_id="shadow-2",
                            attempt_id="shadow-2",
                            plan_hash=A,
                            message_hash=B,
                            reconciliation_hash=C,
                            terminal_reason=RECONCILED_REASON,
                            created_at=1,
                            completed_at=2,
                            simulation_success=True,
                            repayment_proven=True,
                        )
                    ],
                    thresholds=ShadowSoakThresholds(minimum_duration_seconds=0),
                ).build_bundle(),
                reviewer=operator,
                review_reference="review-2",
                reviewed_at_ms=runtime.now_ms + 2,
            )
            ack = controller.acknowledge_policy(
                operator=operator,
                policy_hash=controller.policy.policy_hash,
                evidence_hash=review.evidence_hash,
                acknowledgement=OPERATOR_ACKNOWLEDGEMENT,
                acknowledged_at_ms=runtime.now_ms + 3,
            )
            controller.arm(
                operator=operator,
                acknowledgement_id=ack.acknowledgement_id,
                armed_at_ms=runtime.now_ms + 4,
            )

    report = controller.report()
    assert LatchCode.DAILY_LOSS_LIMIT in report.active_latches
    assert LatchCode.CONSECUTIVE_FAILURE_LIMIT in report.active_latches
