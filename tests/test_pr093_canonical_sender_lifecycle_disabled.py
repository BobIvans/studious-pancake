from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.submission.lifecycle_integration import CANONICAL_SUBMISSION_OUTBOX_TOPIC
from src.submission.sender_lifecycle_disabled import (
    CANONICAL_SENDER_OWNER,
    REQUIRED_LIFECYCLE_CONTROLS,
    REQUIRED_PR093_EVIDENCE,
    REQUIRED_STATUS_OUTCOMES,
    REQUIRED_TRANSPORTS,
    CanonicalSenderLifecycleDisabledPackage,
    SenderLifecycleDisabledError,
    SenderLifecycleDisabledState,
    SenderLifecycleEvidenceRef,
    evaluate_canonical_sender_lifecycle_disabled,
)

SHA = "a" * 64
OTHER_SHA = "b" * 64
GIT_SHA = "1" * 40


def _evidence(
    *,
    missing: str | None = None,
    not_passed: str | None = None,
    not_reviewed: str | None = None,
) -> tuple[SenderLifecycleEvidenceRef, ...]:
    items: list[SenderLifecycleEvidenceRef] = []
    for name in REQUIRED_PR093_EVIDENCE:
        if name == missing:
            continue
        items.append(
            SenderLifecycleEvidenceRef(
                name=name,
                sha256=OTHER_SHA if name == not_passed else SHA,
                source_commit=GIT_SHA,
                passed=name != not_passed,
                human_reviewed=name != not_reviewed,
                reviewer="operator-reviewer",
            )
        )
    return tuple(items)


def _package(**overrides) -> CanonicalSenderLifecycleDisabledPackage:
    data = {
        "evidence": _evidence(),
        "lifecycle_controls": {name: True for name in REQUIRED_LIFECYCLE_CONTROLS},
        "status_outcomes": {name: True for name in REQUIRED_STATUS_OUTCOMES},
        "transport_contracts": {name: True for name in REQUIRED_TRANSPORTS},
        "sender_owner": CANONICAL_SENDER_OWNER,
        "outbox_topic": CANONICAL_SUBMISSION_OUTBOX_TOPIC,
        "assembled_at": datetime(2026, 7, 21, tzinfo=UTC),
        "assembled_by": "release-operator",
        "compile_time_submission_enabled": False,
        "config_submission_enabled": False,
        "supported_command_submission_enabled": False,
        "automatic_resend_enabled": False,
        "signer_boundary_reviewed": True,
    }
    data.update(overrides)
    return CanonicalSenderLifecycleDisabledPackage(**data)


def test_pr093_ready_package_is_reviewable_but_runtime_disabled() -> None:
    result = evaluate_canonical_sender_lifecycle_disabled(_package())

    assert result.state is SenderLifecycleDisabledState.READY_DISABLED_FOR_REVIEW
    assert result.sender_lifecycle_review_ready is True
    assert result.live_allowed is False
    assert result.runtime_submission_enabled is False
    assert result.supported_command_can_submit is False
    assert result.automatic_resend_enabled is False
    assert result.blockers == ()
    assert result.to_dict()["supported_command_can_submit"] is False


def test_pr093_missing_upstream_evidence_blocks() -> None:
    result = evaluate_canonical_sender_lifecycle_disabled(
        _package(evidence=_evidence(missing="pr092.real-shadow-soak"))
    )

    assert result.state is SenderLifecycleDisabledState.BLOCKED
    assert "EVIDENCE_MISSING:pr092.real-shadow-soak" in result.blockers
    assert result.live_allowed is False


def test_pr093_unreviewed_or_failed_evidence_blocks() -> None:
    result = evaluate_canonical_sender_lifecycle_disabled(
        _package(
            evidence=_evidence(
                not_passed="pr086.protocol-aware-rpc-jito-transport",
                not_reviewed="pr091.security-signer-boundary",
            )
        )
    )

    assert (
        "EVIDENCE_NOT_PASSED:pr086.protocol-aware-rpc-jito-transport" in result.blockers
    )
    assert "EVIDENCE_NOT_REVIEWED:pr091.security-signer-boundary" in result.blockers


def test_pr093_supported_command_submission_stays_hard_denied() -> None:
    result = evaluate_canonical_sender_lifecycle_disabled(
        _package(
            compile_time_submission_enabled=True,
            config_submission_enabled=True,
            supported_command_submission_enabled=True,
        )
    )

    assert "COMPILE_TIME_SUBMISSION_ENABLED" in result.blockers
    assert "CONFIG_SUBMISSION_ENABLED" in result.blockers
    assert "SUPPORTED_COMMAND_CAN_SUBMIT" in result.blockers
    assert result.supported_command_can_submit is False


def test_pr093_no_automatic_resend_under_ambiguity() -> None:
    result = evaluate_canonical_sender_lifecycle_disabled(
        _package(automatic_resend_enabled=True)
    )

    assert "AUTOMATIC_RESEND_ENABLED" in result.blockers
    assert result.automatic_resend_enabled is False


def test_pr093_requires_all_ack_status_outcomes() -> None:
    statuses = {name: True for name in REQUIRED_STATUS_OUTCOMES}
    statuses["failed"] = False

    result = evaluate_canonical_sender_lifecycle_disabled(
        _package(status_outcomes=statuses)
    )

    assert "STATUS_OUTCOME_NOT_COVERED:failed" in result.blockers
    assert "STATUS_OUTCOME_NOT_COVERED:expired" not in result.blockers


def test_pr093_requires_canonical_owner_and_outbox() -> None:
    result = evaluate_canonical_sender_lifecycle_disabled(
        _package(
            sender_owner="src.execution.live_control.PermitBoundSender",
            outbox_topic="legacy.sender.outbox",
        )
    )

    assert "CANONICAL_SENDER_OWNER_MISMATCH" in result.blockers
    assert "CANONICAL_OUTBOX_TOPIC_MISMATCH" in result.blockers


def test_pr093_rejects_malformed_duplicate_evidence_names() -> None:
    duplicate = _evidence() + (
        SenderLifecycleEvidenceRef(
            name=REQUIRED_PR093_EVIDENCE[0],
            sha256=OTHER_SHA,
            source_commit=GIT_SHA,
            passed=True,
            human_reviewed=True,
            reviewer="operator-reviewer",
        ),
    )

    with pytest.raises(SenderLifecycleDisabledError, match="evidence names"):
        _package(evidence=duplicate)
