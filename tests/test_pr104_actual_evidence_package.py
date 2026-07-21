from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

from src.release_gate.actual_evidence import REQUIRED_ACTUAL_EVIDENCE_KINDS
from src.release_gate.operational_drills import DEFAULT_REQUIRED_FAILURE_AREAS
from src.release_gate.pr104_actual_evidence_package import (
    PR104_DEFAULT_MANIFEST_PATH,
    evaluate_pr104_actual_evidence_package,
    main,
)
from src.release_gate.real_evidence_manifest import (
    PR091_RELEASE_ARTIFACT_ROOT,
    SCHEMA_VERSION,
)


_TS = "2026-07-21T00:00:00+00:00"


def test_pr104_rejects_readme_only_evidence_directory(tmp_path: Path) -> None:
    readme = tmp_path / PR091_RELEASE_ARTIFACT_ROOT / "README.md"
    readme.parent.mkdir(parents=True)
    readme.write_text("README is not release evidence.\n", encoding="utf-8")
    _git_init_and_add(tmp_path)

    result = evaluate_pr104_actual_evidence_package(
        repo_root=tmp_path,
        evaluated_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
    )

    expected_blocker = (
        f"PR104_EVIDENCE_MANIFEST_MISSING:{PR104_DEFAULT_MANIFEST_PATH}"
    )
    assert result.accepted is False
    assert result.state == "blocked"
    assert expected_blocker in result.blockers


def test_pr104_accepts_complete_reviewed_release_package(tmp_path: Path) -> None:
    _write_manifest(tmp_path)
    _git_init_and_add(tmp_path)

    result = evaluate_pr104_actual_evidence_package(
        repo_root=tmp_path,
        evaluated_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
    )

    assert result.accepted is True
    assert result.artifact_count == len(REQUIRED_ACTUAL_EVIDENCE_KINDS)
    assert result.scenario_evidence_count == len(DEFAULT_REQUIRED_FAILURE_AREAS)
    assert result.blockers == ()


def test_pr104_rejects_pr091_gate_blockers(tmp_path: Path) -> None:
    manifest_path, payload = _write_manifest(tmp_path)
    payload["artifacts"][0]["placeholder"] = True
    (tmp_path / manifest_path).write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    _git_init_and_add(tmp_path)

    result = evaluate_pr104_actual_evidence_package(
        repo_root=tmp_path,
        evaluated_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
    )

    assert result.accepted is False
    assert "PR091_GATE_NOT_ACCEPTED" in result.blockers
    assert any(
        blocker.startswith("PR091_GATE_BLOCKED:PLACEHOLDER_ARTIFACT_REJECTED")
        for blocker in result.blockers
    )


def test_pr104_cli_returns_nonzero_when_manifest_is_missing(tmp_path: Path) -> None:
    assert main(["--repo-root", str(tmp_path), "--json"]) == 1


def _write_manifest(root: Path) -> tuple[Path, dict[str, object]]:
    release_root = root / PR091_RELEASE_ARTIFACT_ROOT
    artifacts_dir = release_root / "artifacts"
    scenarios_dir = release_root / "chaos"
    artifacts_dir.mkdir(parents=True)
    scenarios_dir.mkdir(parents=True)

    artifact_records: list[dict[str, object]] = []
    artifact_digests: dict[str, str] = {}
    for kind in sorted(REQUIRED_ACTUAL_EVIDENCE_KINDS, key=lambda item: item.value):
        relative_path = f"{PR091_RELEASE_ARTIFACT_ROOT}/artifacts/{kind.value}.json"
        digest = _write_release_file(
            root,
            relative_path,
            json.dumps(
                {
                    "kind": kind.value,
                    "generated_by": "pr104-test-fixture",
                    "review_state": "reviewed",
                },
                sort_keys=True,
            ),
        )
        artifact_digests[kind.value] = digest
        artifact_records.append(
            {
                "kind": kind.value,
                "path": relative_path,
                "sha256": digest,
                "generated_at": _TS,
                "source": "repository-release-artifact",
                "policy_enforced": True,
                "reviewed": True,
                "reviewer": "release-operator",
                "critical_findings": 0,
                "placeholder": False,
                "notes": "reviewed release evidence file",
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
                "scenario_id": f"pr104-{area.value}",
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
        "package_id": "pr104-reviewed-release-evidence-test-package",
        "generated_at": _TS,
        "artifacts": artifact_records,
        "operational_drill_suite": {
            "suite_id": "pr104-operational-drill-test-suite",
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
                "release_manifest_sha256": _sha256_text("immutable manifest"),
            },
            "scenarios": scenario_records,
            "manual_rollback_rehearsed": True,
            "kill_switch_rehearsed": True,
            "no_live_submission": True,
            "notes": "PR-104 reviewed release package fixture",
        },
        "notes": "fixture proves PR-104 gate invariants, not production readiness",
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
