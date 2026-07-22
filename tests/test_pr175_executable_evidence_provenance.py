from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.release_gate.executable_evidence import (
    EvidenceOutcome,
    EvidenceSource,
    EvidenceVerificationPolicy,
    IndependentEvidenceVerifier,
    RawEvidenceArtifact,
    VerifiedEvidencePackage,
    evaluate_verified_evidence_package,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
_RELEASE = "sha256:" + "1" * 64
_POLICY = "2" * 64
_CLUSTER = "3" * 64
_COMMIT = "a" * 40


def _raw_artifact(
    *,
    requirement_id: str = "provider.jupiter.build.conformance",
    source: EvidenceSource = EvidenceSource.CREDENTIALED_PROVIDER_PROBE,
    producer_id: str = "producer/github-actions-pr175",
    release_digest: str = _RELEASE,
    policy_bundle_digest: str = _POLICY,
    cluster_genesis_hash: str | None = _CLUSTER,
    exit_code: int = 0,
    finished_at: datetime = _NOW,
) -> RawEvidenceArtifact:
    return RawEvidenceArtifact(
        requirement_id=requirement_id,
        source=source,
        producer_id=producer_id,
        command=("python", "scripts/provider_probe.py", "--provider", "jupiter"),
        source_commit=_COMMIT,
        release_digest=release_digest,
        policy_bundle_digest=policy_bundle_digest,
        component_owner="src.providers.jupiter",
        environment="protected-ci-probe",
        started_at=finished_at - timedelta(seconds=3),
        finished_at=finished_at,
        exit_code=exit_code,
        raw_output_sha256="4" * 64,
        stdout_sha256="5" * 64,
        stderr_sha256="6" * 64,
        input_artifact_sha256="7" * 64,
        raw_artifact_uri="sha256:" + "8" * 64,
        cluster_genesis_hash=cluster_genesis_hash,
        sanitized_summary="credentialed probe passed with redacted output",
    )


def _policy(
    *,
    requirement_id: str = "provider.jupiter.build.conformance",
    release_digest: str = _RELEASE,
    policy_bundle_digest: str = _POLICY,
    cluster_genesis_hash: str | None = _CLUSTER,
    max_age_seconds: int = 600,
) -> EvidenceVerificationPolicy:
    return EvidenceVerificationPolicy(
        requirement_id=requirement_id,
        accepted_sources=(EvidenceSource.CREDENTIALED_PROVIDER_PROBE,),
        release_digest=release_digest,
        policy_bundle_digest=policy_bundle_digest,
        cluster_genesis_hash=cluster_genesis_hash,
        required_component_owner="src.providers.jupiter",
        max_age_seconds=max_age_seconds,
    )


def _verify(
    artifact: RawEvidenceArtifact | None = None,
    policy: EvidenceVerificationPolicy | None = None,
    *,
    verifier_id: str = "independent/security-reviewer",
    verified_at: datetime = _NOW + timedelta(seconds=5),
):
    verifier = IndependentEvidenceVerifier(
        verifier_id=verifier_id,
        verifier_tool="pr175-evidence-verifier/1.0",
    )
    return verifier.verify(
        artifact or _raw_artifact(),
        policy or _policy(),
        verified_at=verified_at,
        provenance_signature_ref="sigstore:bundle/pr175-provider-jupiter",
    )


def test_pr175_verifies_executable_evidence_and_package() -> None:
    report = _verify()

    assert report.accepted is True
    assert report.evidence.outcome is EvidenceOutcome.VERIFIED
    assert report.evidence.blockers == ()

    package = VerifiedEvidencePackage(
        package_id="release-candidate-pr175",
        release_digest=_RELEASE,
        policy_bundle_digest=_POLICY,
        evidences=(report.evidence,),
        generated_at=_NOW + timedelta(seconds=6),
        required_requirement_ids=("provider.jupiter.build.conformance",),
    )

    package_result = evaluate_verified_evidence_package(
        package,
        evaluated_at=_NOW + timedelta(seconds=10),
    )

    assert package_result.ready is True
    assert package_result.blockers == ()


def test_pr175_rejects_self_verified_producer() -> None:
    report = _verify(verifier_id="producer/github-actions-pr175")

    assert report.accepted is False
    assert report.evidence.outcome is EvidenceOutcome.BLOCKED
    assert report.evidence.blockers == ("PRODUCER_VERIFIER_NOT_INDEPENDENT",)


def test_pr175_blocks_nonzero_producer_exit() -> None:
    report = _verify(_raw_artifact(exit_code=2))

    assert report.accepted is False
    assert "PRODUCER_EXIT_NONZERO" in report.evidence.blockers


def test_pr175_blocks_cross_release_reuse() -> None:
    report = _verify(_raw_artifact(release_digest="sha256:" + "9" * 64))

    assert report.accepted is False
    assert "RELEASE_DIGEST_MISMATCH" in report.evidence.blockers


def test_pr175_blocks_cross_cluster_reuse() -> None:
    report = _verify(_raw_artifact(cluster_genesis_hash="9" * 64))

    assert report.accepted is False
    assert "CLUSTER_GENESIS_MISMATCH" in report.evidence.blockers


def test_pr175_blocks_stale_evidence() -> None:
    artifact = _raw_artifact(finished_at=_NOW - timedelta(hours=2))
    report = _verify(artifact, _policy(max_age_seconds=60))

    assert report.accepted is False
    assert "EVIDENCE_STALE" in report.evidence.blockers


def test_pr175_rejects_random_or_placeholder_digests() -> None:
    with pytest.raises(ValueError, match="raw_output_sha256"):
        RawEvidenceArtifact(
            requirement_id="provider.jupiter.build.conformance",
            source=EvidenceSource.CREDENTIALED_PROVIDER_PROBE,
            producer_id="producer/github-actions-pr175",
            command=("python", "probe.py"),
            source_commit=_COMMIT,
            release_digest=_RELEASE,
            policy_bundle_digest=_POLICY,
            component_owner="src.providers.jupiter",
            environment="protected-ci-probe",
            started_at=_NOW,
            finished_at=_NOW,
            exit_code=0,
            raw_output_sha256="0" * 64,
            stdout_sha256="5" * 64,
            stderr_sha256="6" * 64,
            input_artifact_sha256="7" * 64,
            raw_artifact_uri="sha256:" + "8" * 64,
            cluster_genesis_hash=_CLUSTER,
        )


def test_pr175_rejects_secret_bearing_metadata() -> None:
    with pytest.raises(ValueError, match="secret-bearing"):
        _raw_artifact(
            producer_id="producer-with-authorization: bearer leaked",
        )


def test_pr175_package_fails_missing_and_expired_evidence() -> None:
    report = _verify(verified_at=_NOW + timedelta(seconds=5))
    package = VerifiedEvidencePackage(
        package_id="release-candidate-pr175",
        release_digest=_RELEASE,
        policy_bundle_digest=_POLICY,
        evidences=(report.evidence,),
        generated_at=_NOW + timedelta(seconds=6),
        required_requirement_ids=(
            "provider.jupiter.build.conformance",
            "settlement.finalized.rpc.trace",
        ),
    )

    package_result = evaluate_verified_evidence_package(
        package,
        evaluated_at=_NOW + timedelta(hours=1),
    )

    assert package_result.ready is False
    assert "VERIFIED_EVIDENCE_MISSING:settlement.finalized.rpc.trace" in (
        package_result.blockers
    )
    assert "VERIFIED_EVIDENCE_EXPIRED:provider.jupiter.build.conformance" in (
        package_result.blockers
    )
