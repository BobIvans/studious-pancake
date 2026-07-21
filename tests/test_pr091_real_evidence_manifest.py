from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from src.release_gate.actual_evidence import REQUIRED_ACTUAL_EVIDENCE_KINDS
from src.release_gate.operational_drills import DEFAULT_REQUIRED_FAILURE_AREAS
from src.release_gate.real_evidence_manifest import (
    PR091_RELEASE_ARTIFACT_ROOT,
    SCHEMA_VERSION,
    RealEvidenceManifestError,
    evaluate_pr091_actual_evidence_manifest,
    load_pr091_actual_evidence_manifest,
)

_TS = "2026-07-21T00:00:00+00:00"


def test_pr091_manifest_loads_git_tracked_release_artifacts(tmp_path: Path) -> None:
    manifest_path, payload = _write_manifest(tmp_path)
    _git_init_and_add(tmp_path)

    loaded = load_pr091_actual_evidence_manifest(
        repo_root=tmp_path,
        manifest_path=manifest_path,
    )
    result = evaluate_pr091_actual_evidence_manifest(
        repo_root=tmp_path,
        manifest_path=manifest_path,
        evaluated_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
    )

    assert loaded.schema_version == SCHEMA_VERSION
    assert loaded.package.package_id == payload["package_id"]
    assert loaded.manifest_path == manifest_path.as_posix()
    assert all(
        path.startswith(f"{PR091_RELEASE_ARTIFACT_ROOT}/")
        for path in loaded.tracked_paths
    )
    assert result.accepted is True
    assert result.state == "accepted"
    assert result.blockers == ()


def test_pr091_manifest_rejects_untracked_tmp_fixture(tmp_path: Path) -> None:
    manifest_path, _payload = _write_manifest(tmp_path)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    with pytest.raises(RealEvidenceManifestError, match="GIT_TRACKING_REQUIRED"):
        load_pr091_actual_evidence_manifest(
            repo_root=tmp_path,
            manifest_path=manifest_path,
        )


def test_pr091_manifest_rejects_artifacts_outside_release_root(tmp_path: Path) -> None:
    manifest_path, payload = _write_manifest(tmp_path)
    artifact = payload["artifacts"][0]
    artifact["path"] = "tests/tmp-fixture.json"
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _git_init_and_add(tmp_path)

    with pytest.raises(
        RealEvidenceManifestError,
        match="PATH_NOT_UNDER_PR091_RELEASE_ARTIFACTS",
    ):
        load_pr091_actual_evidence_manifest(
            repo_root=tmp_path,
            manifest_path=manifest_path,
        )


def test_pr091_manifest_requires_scenario_evidence_file_hash(tmp_path: Path) -> None:
    manifest_path, payload = _write_manifest(tmp_path)
    payload["operational_drill_suite"]["scenarios"][0]["evidence_sha256"] = "1" * 64
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _git_init_and_add(tmp_path)

    with pytest.raises(
        RealEvidenceManifestError,
        match="SCENARIO_EVIDENCE_HASH_MISMATCH",
    ):
        load_pr091_actual_evidence_manifest(
            repo_root=tmp_path,
            manifest_path=manifest_path,
        )


def test_pr091_manifest_keeps_live_submission_blocked(tmp_path: Path) -> None:
    manifest_path, payload = _write_manifest(tmp_path)
    payload = deepcopy(payload)
    payload["operational_drill_suite"]["no_live_submission"] = False
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _git_init_and_add(tmp_path)

    result = evaluate_pr091_actual_evidence_manifest(
        repo_root=tmp_path,
        manifest_path=manifest_path,
        evaluated_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
    )

    assert result.accepted is False
    assert "LIVE_SUBMISSION_OCCURRED_DURING_PR078_EVIDENCE" in result.blockers


def _write_manifest(root: Path) -> tuple[Path, dict[str, object]]:
    release_root = root / PR091_RELEASE_ARTIFACT_ROOT
    artifacts_dir = release_root / "artifacts"
    scenarios_dir = release_root / "chaos"
    artifacts_dir.mkdir(parents=True)
    scenarios_dir.mkdir(parents=True)

    artifact_records: list[dict[str, object]] = []
    artifact_digests: dict[str, str] = {}
    for kind in sorted(REQUIRED_ACTUAL_EVIDENCE_KINDS, key=lambda item: item.value):
        relative_path = f"{PR091_RELEASE_ARTIFACT_ROOT}/artifacts/{kind.value}.txt"
        digest = _write_release_file(
            root,
            relative_path,
            f"real PR-091 test evidence for {kind.value}\n",
        )
        artifact_digests[kind.value] = digest
        artifact_records.append(
            {
                "kind": kind.value,
                "path": relative_path,
                "sha256": digest,
                "generated_at": _TS,
                "source": "ci-generated",
                "policy_enforced": True,
                "reviewed": True,
                "reviewer": "release-operator",
                "critical_findings": 0,
                "placeholder": False,
                "notes": "tracked release evidence",
            }
        )

    scenario_records: list[dict[str, object]] = []
    for area in sorted(DEFAULT_REQUIRED_FAILURE_AREAS, key=lambda item: item.value):
        relative_path = f"{PR091_RELEASE_ARTIFACT_ROOT}/chaos/{area.value}.json"
        digest = _write_release_file(
            root,
            relative_path,
            json.dumps(
                {
                    "area": area.value,
                    "terminal_state": "safe_idle",
                    "no_live_submission": True,
                },
                sort_keys=True,
            ),
        )
        scenario_records.append(
            {
                "area": area.value,
                "scenario_id": f"pr091-{area.value}",
                "injected_failure": f"offline drill for {area.value}",
                "expected_safe_state": "safe_idle",
                "passed": True,
                "safe_state_proven": True,
                "evidence_path": relative_path,
                "evidence_sha256": digest,
                "max_retry_attempts": 3,
                "observed_retry_attempts": 1,
                "max_queue_depth": 10,
                "observed_queue_depth": 1,
                "max_rto_seconds": 60,
                "observed_rto_seconds": 10,
                "automatic_resubmission_attempted": False,
                "residual_task_count": 0,
                "notes": "offline fail-closed drill",
            }
        )

    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "package_id": "pr091-real-evidence-test-package",
        "generated_at": _TS,
        "artifacts": artifact_records,
        "operational_drill_suite": {
            "suite_id": "pr091-operational-drill-test-suite",
            "run_started_at": _TS,
            "run_finished_at": _TS,
            "operator": "release-operator",
            "environment": "offline-ci",
            "security": {
                "generated_at": _TS,
                "secret_scan_passed": True,
                "plaintext_key_findings": [],
                "dependency_decision": {
                    "allowed": True,
                    "reason": "dependency audit passed critical-CVE policy",
                    "blockers": [],
                },
                "sbom_sha256": artifact_digests["cyclonedx-sbom"],
                "image_digest": "sha256:" + _sha256_text("offline image digest"),
                "signer_policy_enforced": True,
                "isolated_signer_reference": "env:FLASHLOAN_SIGNER_POLICY_REFERENCE",
            },
            "scenarios": scenario_records,
            "manual_rollback_rehearsed": True,
            "kill_switch_rehearsed": True,
            "no_live_submission": True,
            "notes": "PR-091 loader fixture with git-tracked files",
        },
        "notes": "fixture proves loader invariants, not production readiness",
    }
    manifest_path = release_root / "manifest.json"
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return manifest_path.relative_to(root), payload


def _write_release_file(root: Path, relative_path: str, content: str) -> str:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _git_init_and_add(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "add", PR091_RELEASE_ARTIFACT_ROOT],
        cwd=root,
        check=True,
        capture_output=True,
    )
