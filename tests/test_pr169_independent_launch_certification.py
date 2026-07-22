from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.release_gate.independent_assurance import (
    AssuranceDecision,
    AssuranceSignoffRole,
    IndependentEvidenceArtifact,
    IndependentLaunchCertificationPackage,
    IndependentLaunchSignoff,
    LaunchEvidenceKind,
    LaunchRiskRegisterItem,
    LaunchRiskSeverity,
    LaunchRiskState,
    REQUIRED_EVIDENCE_KINDS,
    REQUIRED_SECURITY_INVARIANTS,
    REQUIRED_SIGNOFF_ROLES,
    evaluate_independent_launch_certification,
)

pytestmark = pytest.mark.unit

_SHA = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64
_GIT_SHA = "d" * 40
_IMAGE = "sha256:" + "e" * 64
_NOW = datetime(2026, 7, 22, tzinfo=timezone.utc)


def _evidence(kind: LaunchEvidenceKind) -> IndependentEvidenceArtifact:
    return IndependentEvidenceArtifact(
        evidence_kind=kind,
        tool_name=f"pr169-{kind.value}",
        tool_version="1.0.0",
        command=f"python -m pr169.{kind.value}",
        source_commit=_GIT_SHA,
        image_digest=_IMAGE,
        produced_at=_NOW,
        producer_identity=f"automation/{kind.value}",
        runner_identity="github-actions/pr-169",
        verifier_identity=f"independent-verifier/{kind.value}",
        raw_report_sha256=_SHA,
        signature_reference=f"sigstore:pr169/{kind.value}",
        passed=True,
    )


def _signoff(role: AssuranceSignoffRole) -> IndependentLaunchSignoff:
    return IndependentLaunchSignoff(
        role=role,
        identity=f"{role.value}@reviewer.example",
        decision=AssuranceDecision.APPROVE,
        signed_at=_NOW,
        exact_release_digest=_SHA_B,
        raw_evidence_sha256=_SHA_C,
        authored_release_changes=False,
    )


def _package(
    *,
    evidence: tuple[IndependentEvidenceArtifact, ...] | None = None,
    risks: tuple[LaunchRiskRegisterItem, ...] = (),
    signoffs: tuple[IndependentLaunchSignoff, ...] | None = None,
) -> IndependentLaunchCertificationPackage:
    return IndependentLaunchCertificationPackage(
        release_digest=_SHA_B,
        threat_model_path="docs/security/PR-169-current-threat-model.md",
        threat_model_reviewed_at=_NOW,
        assets=("treasury", "signing-authority", "release-artifact"),
        trust_boundaries=("provider-boundary", "signer-ipc", "deployment-control"),
        security_invariants=tuple(sorted(REQUIRED_SECURITY_INVARIANTS)),
        evidence=evidence
        if evidence is not None
        else tuple(_evidence(kind) for kind in REQUIRED_EVIDENCE_KINDS),
        risk_register=risks,
        signoffs=signoffs
        if signoffs is not None
        else tuple(_signoff(role) for role in REQUIRED_SIGNOFF_ROLES),
    )


def test_pr169_approves_complete_independent_assurance_package() -> None:
    result = evaluate_independent_launch_certification(_package())

    assert result.approved is True
    assert result.blockers == ()
    assert set(result.observed_evidence) == {
        kind.value for kind in REQUIRED_EVIDENCE_KINDS
    }


def test_pr169_rejects_self_declared_evidence_without_signed_report() -> None:
    with pytest.raises(ValueError, match="signature_reference"):
        IndependentEvidenceArtifact(
            evidence_kind=LaunchEvidenceKind.EXTERNAL_PENTEST,
            tool_name="external-pentest",
            tool_version="1.0.0",
            command="vendor report",
            source_commit=_GIT_SHA,
            image_digest=_IMAGE,
            produced_at=_NOW,
            producer_identity="vendor",
            runner_identity="vendor-runner",
            verifier_identity="independent-reviewer",
            raw_report_sha256=_SHA,
            signature_reference="",
            passed=True,
        )


def test_pr169_blocks_missing_security_evidence_kind() -> None:
    evidence = tuple(
        _evidence(kind)
        for kind in REQUIRED_EVIDENCE_KINDS
        if kind is not LaunchEvidenceKind.MUTATION_TESTING
    )

    result = evaluate_independent_launch_certification(_package(evidence=evidence))

    assert result.approved is False
    assert "missing independent evidence: mutation-testing" in result.blockers


def test_pr169_blocks_unresolved_high_risk_even_with_other_green_evidence() -> None:
    risk = LaunchRiskRegisterItem(
        finding_id="SEC-001",
        severity=LaunchRiskSeverity.HIGH,
        state=LaunchRiskState.ACCEPTED,
        owner="treasury-risk",
        mitigation="keep live disabled",
        blast_radius="meaningful funds",
        acceptance_authority="risk-committee",
        accepted_until=_NOW + timedelta(days=3),
    )

    result = evaluate_independent_launch_certification(_package(risks=(risk,)))

    assert result.approved is False
    assert "unresolved high-severity risk: SEC-001" in result.blockers


def test_pr169_independent_reviewer_cannot_author_release_changes() -> None:
    with pytest.raises(ValueError, match="independent reviewer"):
        IndependentLaunchSignoff(
            role=AssuranceSignoffRole.INDEPENDENT_REVIEWER,
            identity="same-author",
            decision=AssuranceDecision.APPROVE,
            signed_at=_NOW,
            exact_release_digest=_SHA_B,
            raw_evidence_sha256=_SHA_C,
            authored_release_changes=True,
        )


def test_pr169_blocks_signoff_for_wrong_release_digest() -> None:
    wrong_signoff = IndependentLaunchSignoff(
        role=AssuranceSignoffRole.SECURITY,
        identity="security@example",
        decision=AssuranceDecision.APPROVE,
        signed_at=_NOW,
        exact_release_digest="f" * 64,
        raw_evidence_sha256=_SHA_C,
    )
    signoffs = (wrong_signoff,) + tuple(
        _signoff(role)
        for role in REQUIRED_SIGNOFF_ROLES
        if role is not AssuranceSignoffRole.SECURITY
    )

    result = evaluate_independent_launch_certification(_package(signoffs=signoffs))

    assert result.approved is False
    assert "signoff release mismatch: security" in result.blockers
