from __future__ import annotations

import pytest

from src.submission.canonical_lifecycle_pr106 import (
    REQUIRED_PR106_LIFECYCLE_CONTROLS,
    REQUIRED_PR106_UPSTREAM_EVIDENCE,
    PR106CanonicalSenderLifecycleError,
    PR106CanonicalSenderLifecyclePackage,
    PR106CanonicalSenderLifecycleState,
    PR106UpstreamEvidenceRef,
    evaluate_pr106_canonical_sender_lifecycle,
)
from src.submission.lifecycle_integration import CANONICAL_SUBMISSION_OUTBOX_TOPIC
from src.submission.sender_lifecycle_disabled import (
    CANONICAL_SENDER_OWNER,
    CanonicalSenderLifecycleDisabledReadiness,
    SenderLifecycleDisabledState,
)

SHA = "1234567890abcdef" * 4
OTHER_SHA = "abcdef0123456789" * 4
GIT_SHA = "0123456789abcdef0123456789abcdef01234567"


def _upstream(
    *,
    missing: str | None = None,
    not_passed: str | None = None,
    not_reviewed: str | None = None,
) -> tuple[PR106UpstreamEvidenceRef, ...]:
    items: list[PR106UpstreamEvidenceRef] = []
    for name in REQUIRED_PR106_UPSTREAM_EVIDENCE:
        if name == missing:
            continue
        items.append(
            PR106UpstreamEvidenceRef(
                name=name,
                sha256=OTHER_SHA if name == not_passed else SHA,
                source_commit=GIT_SHA,
                passed=name != not_passed,
                human_reviewed=name != not_reviewed,
                reviewer="release-reviewer",
            )
        )
    return tuple(items)


def _pr093_ready(**overrides) -> CanonicalSenderLifecycleDisabledReadiness:
    data = {
        "state": SenderLifecycleDisabledState.READY_DISABLED_FOR_REVIEW,
        "sender_lifecycle_review_ready": True,
        "live_allowed": False,
        "runtime_submission_enabled": False,
        "supported_command_can_submit": False,
        "automatic_resend_enabled": False,
        "blockers": (),
        "warnings": (),
    }
    data.update(overrides)
    return CanonicalSenderLifecycleDisabledReadiness(**data)


def _package(**overrides) -> PR106CanonicalSenderLifecyclePackage:
    data = {
        "upstream_evidence": _upstream(),
        "pr093_readiness": _pr093_ready(),
        "lifecycle_controls": {
            control: True for control in REQUIRED_PR106_LIFECYCLE_CONTROLS
        },
        "sender_owner": CANONICAL_SENDER_OWNER,
        "outbox_topic": CANONICAL_SUBMISSION_OUTBOX_TOPIC,
        "compile_time_live_enabled": False,
        "config_live_enabled": False,
        "supported_command_submission_enabled": False,
        "automatic_resend_enabled": False,
        "signer_import_path": None,
    }
    data.update(overrides)
    return PR106CanonicalSenderLifecyclePackage(**data)


def test_pr106_ready_package_is_reviewable_but_live_disabled() -> None:
    result = evaluate_pr106_canonical_sender_lifecycle(_package())

    assert result.state is PR106CanonicalSenderLifecycleState.READY_DISABLED_FOR_REVIEW
    assert result.lifecycle_review_ready
    assert not result.live_allowed
    assert not result.runtime_submission_enabled
    assert not result.supported_command_can_submit
    assert not result.automatic_resend_enabled
    assert result.blockers == ()
    assert result.to_dict()["live_allowed"] is False


def test_pr106_requires_pr104_pr105_and_pr093_upstream_evidence() -> None:
    result = evaluate_pr106_canonical_sender_lifecycle(
        _package(upstream_evidence=_upstream(missing="pr105.real-shadow-soak-harness-72h"))
    )

    assert result.state is PR106CanonicalSenderLifecycleState.BLOCKED
    assert "UPSTREAM_EVIDENCE_MISSING:pr105.real-shadow-soak-harness-72h" in result.blockers
    assert not result.live_allowed


def test_pr106_failed_or_unreviewed_upstream_blocks() -> None:
    result = evaluate_pr106_canonical_sender_lifecycle(
        _package(
            upstream_evidence=_upstream(
                not_passed="pr104.security-sbom-provenance-chaos-package",
                not_reviewed="pr093.sender-lifecycle-disabled-review",
            )
        )
    )

    assert (
        "UPSTREAM_EVIDENCE_NOT_PASSED:pr104.security-sbom-provenance-chaos-package"
        in result.blockers
    )
    assert (
        "UPSTREAM_EVIDENCE_NOT_REVIEWED:pr093.sender-lifecycle-disabled-review"
        in result.blockers
    )


def test_pr106_pr093_blockers_are_preserved() -> None:
    pr093 = _pr093_ready(
        sender_lifecycle_review_ready=False,
        blockers=("EVIDENCE_MISSING:pr092.real-shadow-soak",),
    )

    result = evaluate_pr106_canonical_sender_lifecycle(_package(pr093_readiness=pr093))

    assert "PR093_LIFECYCLE_NOT_REVIEW_READY" in result.blockers
    assert "PR093:EVIDENCE_MISSING:pr092.real-shadow-soak" in result.blockers


def test_pr106_live_and_resend_paths_remain_hard_denied() -> None:
    result = evaluate_pr106_canonical_sender_lifecycle(
        _package(
            compile_time_live_enabled=True,
            config_live_enabled=True,
            supported_command_submission_enabled=True,
            automatic_resend_enabled=True,
            signer_import_path="src.security.live_signer",
        )
    )

    assert "COMPILE_TIME_LIVE_ENABLED" in result.blockers
    assert "CONFIG_LIVE_ENABLED" in result.blockers
    assert "SUPPORTED_COMMAND_CAN_SUBMIT" in result.blockers
    assert "AUTOMATIC_RESEND_ENABLED" in result.blockers
    assert "SIGNER_IMPORT_PATH_PRESENT" in result.blockers
    assert not result.live_allowed
    assert not result.supported_command_can_submit


def test_pr106_requires_all_lifecycle_controls() -> None:
    controls = {control: True for control in REQUIRED_PR106_LIFECYCLE_CONTROLS}
    controls["durable_unknown_state"] = False

    result = evaluate_pr106_canonical_sender_lifecycle(
        _package(lifecycle_controls=controls)
    )

    assert "PR106_LIFECYCLE_CONTROL_MISSING:durable_unknown_state" in result.blockers


def test_pr106_requires_canonical_owner_and_outbox() -> None:
    result = evaluate_pr106_canonical_sender_lifecycle(
        _package(
            sender_owner="src.execution.live_control.PermitBoundSender",
            outbox_topic="legacy.sender.outbox",
        )
    )

    assert "CANONICAL_SENDER_OWNER_MISMATCH" in result.blockers
    assert "CANONICAL_OUTBOX_TOPIC_MISMATCH" in result.blockers


def test_pr106_rejects_duplicate_upstream_names() -> None:
    duplicate = _upstream() + (
        PR106UpstreamEvidenceRef(
            name=REQUIRED_PR106_UPSTREAM_EVIDENCE[0],
            sha256=OTHER_SHA,
            source_commit=GIT_SHA,
            passed=True,
            human_reviewed=True,
            reviewer="release-reviewer",
        ),
    )

    with pytest.raises(PR106CanonicalSenderLifecycleError, match="unique"):
        _package(upstream_evidence=duplicate)
