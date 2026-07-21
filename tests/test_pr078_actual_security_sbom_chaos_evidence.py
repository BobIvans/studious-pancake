from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from pathlib import Path

from src.release_gate import (
    ActualEvidenceArtifact,
    ActualEvidenceGate,
    ActualEvidenceKind,
    ActualEvidencePackage,
    FailureInjectionScenario,
    OperationalDrillSuite,
    OperationalFailureArea,
    SecurityOperationalEvidence,
)

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
SHA_A = "a" * 64
IMAGE_DIGEST = "sha256:" + "b" * 64


def _hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_artifact(
    repo_root: Path,
    kind: ActualEvidenceKind,
    *,
    source: str = "ci",
    policy_enforced: bool = True,
    reviewed: bool | None = None,
    reviewer: str | None = None,
    critical_findings: int = 0,
    placeholder: bool = False,
    sha_override: str | None = None,
) -> ActualEvidenceArtifact:
    path = Path("evidence") / f"{kind.value}.json"
    absolute = repo_root / path
    absolute.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        '{"schema_version":"pr078.test-artifact.v1",'
        f'"kind":"{kind.value}","source":"{source}"}}\n'
    ).encode("utf-8")
    absolute.write_bytes(payload)
    review_required = kind in {
        ActualEvidenceKind.JOURNAL_LOCK_CORRUPTION,
        ActualEvidenceKind.RECOVERY_TIME_SLO,
        ActualEvidenceKind.RESTORE_CORRUPTION_DRILL,
    }
    return ActualEvidenceArtifact(
        kind=kind,
        path=str(path),
        sha256=sha_override or _hash_bytes(payload),
        generated_at=NOW,
        source=source,
        policy_enforced=policy_enforced,
        reviewed=review_required if reviewed is None else reviewed,
        reviewer=(
            "security@example.com" if review_required and reviewer is None else reviewer
        ),
        critical_findings=critical_findings,
        placeholder=placeholder,
    )


def _artifacts(repo_root: Path) -> tuple[ActualEvidenceArtifact, ...]:
    return tuple(_write_artifact(repo_root, kind) for kind in ActualEvidenceKind)


def _security(**changes: object) -> SecurityOperationalEvidence:
    payload: dict[str, object] = {
        "generated_at": NOW,
        "records": (),
        "sbom_sha256": SHA_A,
        "image_digest": IMAGE_DIGEST,
        "isolated_signer_reference": "keychain:flashloan-canary",
        "secret_scan_passed": True,
        "plaintext_key_findings": (),
        "signer_policy_enforced": True,
        "release_manifest_sha256": SHA_A,
    }
    payload.update(changes)
    return SecurityOperationalEvidence.from_vulnerability_records(**payload)


def _scenario(
    area: OperationalFailureArea,
    **changes: object,
) -> FailureInjectionScenario:
    payload: dict[str, object] = {
        "area": area,
        "scenario_id": f"scenario-{area.value}",
        "injected_failure": f"inject {area.value}",
        "expected_safe_state": "safe_idle",
        "passed": True,
        "safe_state_proven": True,
        "evidence_sha256": SHA_A,
        "max_retry_attempts": 3,
        "observed_retry_attempts": 1,
        "max_queue_depth": 10,
        "observed_queue_depth": 2,
        "max_rto_seconds": 60,
        "observed_rto_seconds": 30,
        "automatic_resubmission_attempted": False,
        "residual_task_count": 0,
    }
    payload.update(changes)
    return FailureInjectionScenario(**payload)


def _suite(**changes: object) -> OperationalDrillSuite:
    payload: dict[str, object] = {
        "suite_id": "pr078-actual-evidence-drill-suite",
        "run_started_at": NOW,
        "run_finished_at": NOW,
        "operator": "operator@example.com",
        "environment": "paper-shadow-ci",
        "security": _security(),
        "scenarios": tuple(_scenario(area) for area in OperationalFailureArea),
        "manual_rollback_rehearsed": True,
        "kill_switch_rehearsed": True,
        "no_live_submission": True,
    }
    payload.update(changes)
    return OperationalDrillSuite(**payload)


def _package(
    repo_root: Path,
    *,
    artifacts: tuple[ActualEvidenceArtifact, ...] | None = None,
    suite: OperationalDrillSuite | None = None,
) -> ActualEvidencePackage:
    return ActualEvidencePackage(
        package_id="pr078-actual-security-sbom-chaos-evidence",
        generated_at=NOW,
        artifacts=_artifacts(repo_root) if artifacts is None else artifacts,
        drill_suite=_suite() if suite is None else suite,
    )


def test_pr078_accepts_real_hashed_artifacts_consumed_by_pr062_gate(
    tmp_path: Path,
) -> None:
    result = ActualEvidenceGate(repo_root=tmp_path, evaluated_at=NOW).evaluate(
        _package(tmp_path)
    )

    assert result.accepted is True
    assert result.state == "accepted"
    assert result.pr062_result.ready_for_limited_live is True
    assert result.package_hash == _package(tmp_path).package_hash
    assert not result.blockers


def test_missing_or_placeholder_artifact_blocks_before_release_gate(
    tmp_path: Path,
) -> None:
    artifacts = tuple(
        artifact
        for artifact in _artifacts(tmp_path)
        if artifact.kind is not ActualEvidenceKind.SPDX_SBOM
    )
    signer_index = next(
        index
        for index, artifact in enumerate(artifacts)
        if artifact.kind is ActualEvidenceKind.ISOLATED_SIGNER_BOUNDARY
    )
    artifacts = (
        *artifacts[:signer_index],
        replace(
            artifacts[signer_index],
            source="synthetic",
            placeholder=True,
        ),
        *artifacts[signer_index + 1 :],
    )

    result = ActualEvidenceGate(repo_root=tmp_path, evaluated_at=NOW).evaluate(
        _package(tmp_path, artifacts=artifacts)
    )

    assert result.accepted is False
    assert "REQUIRED_ACTUAL_ARTIFACTS_MISSING" in result.blockers
    assert "ACTUAL_ARTIFACT_MISSING:spdx-sbom" in result.blockers
    assert "PLACEHOLDER_ARTIFACT_REJECTED:isolated-signer-boundary" in result.blockers
    assert (
        "SYNTHETIC_ARTIFACT_SOURCE_REJECTED:isolated-signer-boundary" in result.blockers
    )


def test_hash_mismatch_and_critical_cve_policy_fail_closed(tmp_path: Path) -> None:
    artifacts = list(_artifacts(tmp_path))
    index = next(
        idx
        for idx, artifact in enumerate(artifacts)
        if artifact.kind is ActualEvidenceKind.DEPENDENCY_VULNERABILITY_SCAN
    )
    artifacts[index] = replace(
        artifacts[index],
        sha256="c" * 64,
        policy_enforced=False,
        critical_findings=1,
    )

    result = ActualEvidenceGate(repo_root=tmp_path, evaluated_at=NOW).evaluate(
        _package(tmp_path, artifacts=tuple(artifacts))
    )

    assert result.accepted is False
    assert (
        "SECURITY_POLICY_NOT_ENFORCED:dependency-vulnerability-scan" in result.blockers
    )
    assert "CRITICAL_CVE_POLICY_NOT_ENFORCED" in result.blockers
    assert (
        "ARTIFACT_FILE_MISSING_OR_HASH_MISMATCH:dependency-vulnerability-scan"
        in result.blockers
    )


def test_chaos_suite_must_end_safe_idle_without_duplicate_submission(
    tmp_path: Path,
) -> None:
    scenarios = list(_suite().scenarios)
    index = next(
        idx
        for idx, scenario in enumerate(scenarios)
        if scenario.area is OperationalFailureArea.JITO_AMBIGUOUS_SUBMISSION
    )
    scenarios[index] = replace(
        scenarios[index],
        expected_safe_state="accepted",
        automatic_resubmission_attempted=True,
        residual_task_count=1,
    )

    result = ActualEvidenceGate(repo_root=tmp_path, evaluated_at=NOW).evaluate(
        _package(tmp_path, suite=_suite(scenarios=tuple(scenarios)))
    )

    prefix = OperationalFailureArea.JITO_AMBIGUOUS_SUBMISSION.value
    assert result.accepted is False
    assert f"SCENARIO_DID_NOT_END_SAFE_IDLE:{prefix}" in result.blockers
    assert f"DUPLICATE_SUBMISSION_RISK:{prefix}" in result.blockers
    assert f"RESIDUAL_TASKS_AFTER_PR078_DRILL:{prefix}" in result.blockers
    assert "PR062_OPERATIONAL_GATE_NOT_READY" in result.blockers


def test_restore_corruption_drill_report_must_be_reviewed(tmp_path: Path) -> None:
    artifacts = list(_artifacts(tmp_path))
    index = next(
        idx
        for idx, artifact in enumerate(artifacts)
        if artifact.kind is ActualEvidenceKind.RESTORE_CORRUPTION_DRILL
    )
    artifacts[index] = replace(artifacts[index], reviewed=False, reviewer=None)

    result = ActualEvidenceGate(repo_root=tmp_path, evaluated_at=NOW).evaluate(
        _package(tmp_path, artifacts=tuple(artifacts))
    )

    assert result.accepted is False
    assert "ARTIFACT_NOT_REVIEWED:restore-corruption-drill" in result.blockers
    assert "ARTIFACT_REVIEWER_MISSING:restore-corruption-drill" in result.blockers
