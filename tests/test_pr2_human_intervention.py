from __future__ import annotations

import sqlite3

import pytest

from src.human_intervention import (
    HumanInterventionLedger,
    HumanInterventionRequest,
    InterventionAction,
    InterventionBlocked,
    InterventionTarget,
    PermitConflict,
    evaluate_human_intervention,
)

pytestmark = pytest.mark.unit

H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64
H4 = "4" * 64
H5 = "5" * 64

REQUIRED_STATEMENTS = [
    "accepts-operator-accountability",
    "confirms-live-submission-remains-disabled",
    "reviewed-evidence-bundle",
    "understands-no-auto-acceptance",
]


def _target(**overrides: str) -> InterventionTarget:
    values = {
        "subject_type": "safety-latch",
        "subject_id": "latch-17",
        "subject_hash": H1,
        "evidence_hash": H2,
        "release_hash": H3,
        "config_hash": H4,
    }
    values.update(overrides)
    return InterventionTarget(**values)


def _approval(
    *,
    operator_id: str,
    request_hash: str,
    target: InterventionTarget,
    secondary_reviewer_id: str,
    acknowledged_at_utc: str = "2026-08-08T20:00:00Z",
) -> dict[str, object]:
    return {
        "schema_version": "pr143.operator-acknowledgement-gate.v1",
        "intent": "manual-override",
        "request_id": request_hash,
        "evidence_bundle_hash": target.evidence_hash,
        "policy_hash": target.config_hash,
        "decision_hash": target.subject_hash,
        "drift_timeline_hash": H5,
        "evidence_refs": ["artifact:intervention", "artifact:subject-evidence"],
        "accepts_new_schema_or_code_hash": False,
        "live_submission_hard_disabled": True,
        "pin_rotation_pr_required": False,
        "unresolved_drift_events": [],
        "secondary_reviewer_id": secondary_reviewer_id,
        "acknowledgement": {
            "operator_id": operator_id,
            "operator_role": "security-reviewer",
            "acknowledged_at_utc": acknowledged_at_utc,
            "protected_environment": True,
            "auto_approved": False,
            "statements": REQUIRED_STATEMENTS,
            "operator_signature": "fixture-only",
        },
    }


def _request(
    *,
    target: InterventionTarget | None = None,
    operator_a: str = "human:alice",
    operator_b: str = "human:bob",
    requested_at_utc: str = "2026-08-08T20:00:00Z",
    expires_at_utc: str = "2026-08-08T20:10:00Z",
) -> HumanInterventionRequest:
    target = target or _target()
    draft = HumanInterventionRequest(
        action=InterventionAction.CLEAR_SAFETY_LATCH,
        target=target,
        requested_at_utc=requested_at_utc,
        expires_at_utc=expires_at_utc,
        acknowledgements=({}, {}),
    )
    return HumanInterventionRequest(
        action=draft.action,
        target=target,
        requested_at_utc=requested_at_utc,
        expires_at_utc=expires_at_utc,
        acknowledgements=(
            _approval(
                operator_id=operator_a,
                request_hash=draft.request_hash,
                target=target,
                secondary_reviewer_id=operator_b,
            ),
            _approval(
                operator_id=operator_b,
                request_hash=draft.request_hash,
                target=target,
                secondary_reviewer_id=operator_a,
            ),
        ),
    )


def test_pr2_dual_human_evidence_creates_sender_free_permit() -> None:
    permit = evaluate_human_intervention(
        _request(), current_utc="2026-08-08T20:05:00Z"
    )

    assert permit.action is InterventionAction.CLEAR_SAFETY_LATCH
    assert permit.operator_ids == ("human:alice", "human:bob")
    assert len(permit.approval_fingerprints) == 2
    assert permit.execution_capability_allowed is False
    assert permit.live_submission_allowed is False
    assert permit.automatic_scale_up_allowed is False


def test_pr2_duplicate_human_cannot_satisfy_dual_control() -> None:
    request = _request(operator_a="human:alice", operator_b="human:alice")

    with pytest.raises(InterventionBlocked, match="PR2_APPROVERS_MUST_BE_DISTINCT"):
        evaluate_human_intervention(request, current_utc="2026-08-08T20:05:00Z")


def test_pr2_bot_approval_is_rejected_by_composed_pr143_authority() -> None:
    request = _request(operator_a="bot:release", operator_b="human:bob")

    with pytest.raises(InterventionBlocked, match="PR143_OPERATOR_MUST_BE_HUMAN"):
        evaluate_human_intervention(request, current_utc="2026-08-08T20:05:00Z")


def test_pr2_subject_hash_drift_fails_closed() -> None:
    request = _request()
    changed = dict(request.acknowledgements[1])
    changed["decision_hash"] = "9" * 64
    drifted = HumanInterventionRequest(
        action=request.action,
        target=request.target,
        requested_at_utc=request.requested_at_utc,
        expires_at_utc=request.expires_at_utc,
        acknowledgements=(request.acknowledgements[0], changed),
    )

    with pytest.raises(InterventionBlocked, match="SUBJECT_HASH_MISMATCH"):
        evaluate_human_intervention(drifted, current_utc="2026-08-08T20:05:00Z")


def test_pr2_one_shot_ledger_is_idempotent_only_for_same_consumer() -> None:
    db = sqlite3.connect(":memory:")
    ledger = HumanInterventionLedger(db)
    request = _request()
    permit = ledger.issue(request, current_utc="2026-08-08T20:05:00Z")

    ledger.consume(
        permit,
        action=request.action,
        target=request.target,
        current_utc="2026-08-08T20:06:00Z",
        idempotency_key="clear-latch:latch-17:g1",
    )
    ledger.consume(
        permit,
        action=request.action,
        target=request.target,
        current_utc="2026-08-08T20:06:01Z",
        idempotency_key="clear-latch:latch-17:g1",
    )

    with pytest.raises(PermitConflict, match="PR2_PERMIT_ALREADY_CONSUMED"):
        ledger.consume(
            permit,
            action=request.action,
            target=request.target,
            current_utc="2026-08-08T20:06:02Z",
            idempotency_key="different-consumer",
        )


def test_pr2_permit_cannot_cross_subject_or_config_binding() -> None:
    db = sqlite3.connect(":memory:")
    ledger = HumanInterventionLedger(db)
    request = _request()
    permit = ledger.issue(request, current_utc="2026-08-08T20:05:00Z")

    with pytest.raises(PermitConflict, match="PR2_PERMIT_BINDING_MISMATCH"):
        ledger.consume(
            permit,
            action=request.action,
            target=_target(config_hash="8" * 64),
            current_utc="2026-08-08T20:06:00Z",
            idempotency_key="wrong-config",
        )


def test_pr2_expired_request_is_blocked() -> None:
    request = _request(
        requested_at_utc="2026-08-08T20:00:00Z",
        expires_at_utc="2026-08-08T20:01:00Z",
    )

    with pytest.raises(InterventionBlocked, match="PR2_REQUEST_EXPIRED"):
        evaluate_human_intervention(request, current_utc="2026-08-08T20:05:00Z")
