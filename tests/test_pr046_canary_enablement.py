from __future__ import annotations

import pytest

from src.evidence.shadow_soak import (
    RECONCILED_REASON,
    ShadowOutcomeRecord,
    ShadowSoakAnalyzer,
    ShadowSoakThresholds,
)
from src.live_canary import (
    ActorKind,
    AdmissionReason,
    CanaryCandidate,
    CanaryControlError,
    CanaryMode,
    CanaryPolicy,
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


def policy() -> CanaryPolicy:
    return CanaryPolicy(
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


def bundle():
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
    return ShadowSoakAnalyzer(
        [record], thresholds=thresholds, corpus_id="reviewed-pr039"
    ).build_bundle()


def candidate(**overrides) -> CanaryCandidate:
    values = {
        "attempt_id": "live-attempt-1",
        "pair": "SOL/USDC",
        "provider": "jupiter",
        "program_ids": (PROGRAM,),
        "principal_base_units": 1_000_000,
        "wallet_spend_lamports": 100_000,
        "plan_hash": A,
        "message_hash": B,
        "observed_at_ms": 100,
    }
    values.update(overrides)
    return CanaryCandidate(**values)


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


def armed() -> tuple[LimitedLiveCanaryController, OperatorIdentity]:
    controller = LimitedLiveCanaryController(policy())
    operator = OperatorIdentity("operator-alice")
    review = controller.review_shadow_evidence(
        bundle(),
        reviewer=operator,
        review_reference="https://github.com/BobIvans/studious-pancake/pull/39",
        reviewed_at_ms=10,
    )
    ack = controller.acknowledge_policy(
        operator=operator,
        policy_hash=controller.policy.policy_hash,
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


def test_default_policy_is_unable_to_authorize_live() -> None:
    controller = LimitedLiveCanaryController()
    decision = controller.evaluate(candidate(), snapshot())
    assert not decision.allowed
    assert AdmissionReason.POLICY_DISABLED in decision.reasons
    assert AdmissionReason.SHADOW_MODE in decision.reasons
    assert controller.report().ai_authority is False


def test_only_human_can_control_enablement() -> None:
    controller = LimitedLiveCanaryController(policy())
    ai = OperatorIdentity("model-agent", ActorKind.AI)
    with pytest.raises(CanaryControlError, match="human operator"):
        controller.review_shadow_evidence(
            bundle(), reviewer=ai, review_reference="review", reviewed_at_ms=1
        )
    with pytest.raises(CanaryControlError, match="human operator"):
        controller.manual_kill(operator=ai, reason="stop", observed_at_ms=2)


def test_review_acknowledgement_and_arm_are_separate_steps() -> None:
    controller = LimitedLiveCanaryController(policy())
    operator = OperatorIdentity("operator-alice")
    assert (
        AdmissionReason.HUMAN_REVIEW_MISSING
        in controller.evaluate(candidate(), snapshot()).reasons
    )

    review = controller.review_shadow_evidence(
        bundle(), reviewer=operator, review_reference="review-1", reviewed_at_ms=10
    )
    with pytest.raises(CanaryControlError, match="different policy hash"):
        controller.acknowledge_policy(
            operator=operator,
            policy_hash=A,
            evidence_hash=review.evidence_hash,
            acknowledgement=OPERATOR_ACKNOWLEDGEMENT,
            acknowledged_at_ms=20,
        )
    with pytest.raises(CanaryControlError, match="exact limited-live"):
        controller.acknowledge_policy(
            operator=operator,
            policy_hash=controller.policy.policy_hash,
            evidence_hash=review.evidence_hash,
            acknowledgement="yes",
            acknowledged_at_ms=20,
        )

    ack = controller.acknowledge_policy(
        operator=operator,
        policy_hash=controller.policy.policy_hash,
        evidence_hash=review.evidence_hash,
        acknowledgement=OPERATOR_ACKNOWLEDGEMENT,
        acknowledged_at_ms=20,
    )
    assert (
        AdmissionReason.CANARY_NOT_ARMED
        in controller.evaluate(candidate(), snapshot()).reasons
    )
    controller.arm(
        operator=operator,
        acknowledgement_id=ack.acknowledgement_id,
        armed_at_ms=30,
    )
    assert controller.evaluate(candidate(), snapshot()).allowed


def test_exactly_one_submission_requires_reconciliation() -> None:
    controller, _ = armed()
    first = candidate()
    decision = controller.evaluate(first, snapshot())
    controller.reserve_submission(decision, first, reserved_at_ms=101)

    blocked = controller.evaluate(
        candidate(attempt_id="live-attempt-2"), snapshot(now_ms=102)
    )
    assert AdmissionReason.OUTSTANDING_SUBMISSION in blocked.reasons

    report = controller.record_reconciliation(
        ReconciliationResult(
            attempt_id=first.attempt_id,
            message_hash=first.message_hash,
            reconciliation_hash=C,
            status=ReconciliationStatus.SUCCESS,
            realized_pnl_lamports=10_000,
            observed_at_ms=103,
        )
    )
    assert report.outstanding_attempt_id is None


def test_allowlists_and_tiny_caps_are_enforced() -> None:
    cases = (
        (candidate(pair="USDC/SOL"), AdmissionReason.PAIR_NOT_ALLOWLISTED),
        (candidate(provider="okx"), AdmissionReason.PROVIDER_NOT_ALLOWLISTED),
        (
            candidate(program_ids=("11111111111111111111111111111111",)),
            AdmissionReason.PROGRAM_NOT_ALLOWLISTED,
        ),
        (
            candidate(principal_base_units=1_000_001),
            AdmissionReason.PRINCIPAL_CAP_EXCEEDED,
        ),
        (
            candidate(wallet_spend_lamports=100_001),
            AdmissionReason.WALLET_SPEND_CAP_EXCEEDED,
        ),
    )
    for proposed, reason in cases:
        controller, _ = armed()
        decision = controller.evaluate(proposed, snapshot())
        assert not decision.allowed
        assert reason in decision.reasons
