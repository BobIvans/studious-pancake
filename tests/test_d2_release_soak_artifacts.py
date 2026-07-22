from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from src.release_soak_artifacts_d2 import (
    D2Artifact,
    D2ArtifactKind,
    D2Readiness,
    D2ReleaseIdentity,
    D2ReleaseSoakBundle,
    D2SoakEvidence,
    bundle_from_manifest,
)

NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
SHA1 = "1" * 64
SHA2 = "2" * 64
SHA3 = "3" * 64
SHA4 = "4" * 64
SHA5 = "5" * 64
COMMIT = "a" * 40


def _artifact(kind: D2ArtifactKind, sha: str | None = None) -> D2Artifact:
    digest = sha or hashlib.sha256(kind.value.encode()).hexdigest()
    return D2Artifact(
        kind=kind,
        uri=f"file:/evidence/{kind.value}.json",
        sha256=digest,
        size_bytes=123,
        produced_by="protected-release-job",
    )


def _release(*, wheel_sha: str = SHA2, image_digest: str = "sha256:" + SHA3):
    return D2ReleaseIdentity(
        source_commit=COMMIT,
        release_digest="sha256:" + SHA1,
        policy_bundle_sha256=SHA4,
        image_digest=image_digest,
        wheel_sha256=wheel_sha,
        build_twice_comparison_sha256=SHA5,
        docker_base_digest="sha256:" + "6" * 64,
        action_full_sha_review_sha256="7" * 64,
    )


def _soak(**overrides):
    payload = dict(
        release_digest="sha256:" + SHA1,
        policy_bundle_sha256=SHA4,
        started_at=NOW,
        finished_at=NOW + timedelta(hours=73),
        reviewed_duration_seconds=72 * 60 * 60,
        non_synthetic=True,
        pinned_wheel=True,
        pinned_image=True,
        pinned_policy=True,
        sender_imports_detected=False,
        signer_imports_detected=False,
        signatures_observed=0,
        submissions_observed=0,
        candidates_seen=17,
        terminal_outcomes={"NO_TRADE": 6, "BLOCKED": 8, "RECONCILED_PAPER_SUCCESS": 3},
        unreconciled_terminal_gaps=0,
        reservation_leaks=0,
        data_gaps=0,
        restart_recovery_passed=True,
        cancellation_recovery_passed=True,
        resource_limits_passed=True,
        fixture_rows_excluded=True,
    )
    payload.update(overrides)
    return D2SoakEvidence(**payload)


def _all_artifacts():
    return (
        _artifact(D2ArtifactKind.WHEEL, SHA2),
        _artifact(D2ArtifactKind.WHEELHOUSE),
        _artifact(D2ArtifactKind.IMAGE_DIGEST, SHA3),
        _artifact(D2ArtifactKind.SBOM),
        _artifact(D2ArtifactKind.DEPENDENCY_GRAPH),
        _artifact(D2ArtifactKind.PROVENANCE),
        _artifact(D2ArtifactKind.SOURCE_WHEEL_PARITY),
        _artifact(D2ArtifactKind.POLICY_BUNDLE),
        _artifact(D2ArtifactKind.PROVIDER_CONTRACTS),
        _artifact(D2ArtifactKind.SOAK_SUMMARY),
        _artifact(D2ArtifactKind.SOAK_EVENTS),
        _artifact(D2ArtifactKind.RESOURCE_METRICS),
        _artifact(D2ArtifactKind.RESTART_RECOVERY),
    )


def test_d2_ready_bundle_requires_real_artifacts_and_clean_soak() -> None:
    bundle = D2ReleaseSoakBundle(
        release=_release(),
        soak=_soak(),
        artifacts=_all_artifacts(),
        generated_at=NOW + timedelta(hours=74),
    )

    assert bundle.readiness is D2Readiness.READY_FOR_REVIEW
    assert bundle.blockers() == ()
    payload = bundle.to_dict()
    assert payload["live_enabled"] is False
    assert payload["sender_reachable"] is False
    assert len(payload["bundle_hash"]) == 64


def test_d2_blocks_short_synthetic_or_submission_contaminated_soak() -> None:
    bundle = D2ReleaseSoakBundle(
        release=_release(),
        soak=_soak(
            finished_at=NOW + timedelta(hours=1),
            reviewed_duration_seconds=60,
            non_synthetic=False,
            signatures_observed=1,
            submissions_observed=1,
        ),
        artifacts=_all_artifacts(),
        generated_at=NOW + timedelta(hours=2),
    )

    assert bundle.readiness is D2Readiness.BLOCKED
    assert "SOAK_REVIEWED_DURATION_TOO_SHORT_FOR_D2" in bundle.blockers()
    assert "SOAK_SYNTHETIC_OR_FIXTURE_CONTAMINATED" in bundle.blockers()
    assert "SOAK_SIGNATURES_OBSERVED" in bundle.blockers()
    assert "SOAK_SUBMISSIONS_OBSERVED" in bundle.blockers()


def test_d2_blocks_missing_release_or_soak_artifacts() -> None:
    bundle = D2ReleaseSoakBundle(
        release=_release(),
        soak=_soak(),
        artifacts=(_artifact(D2ArtifactKind.WHEEL, SHA2),),
        generated_at=NOW + timedelta(hours=74),
    )

    assert "MISSING_ARTIFACT:sbom" in bundle.blockers()
    assert "MISSING_ARTIFACT:soak-summary" in bundle.blockers()


def test_d2_rejects_mismatched_wheel_or_image_identity() -> None:
    with pytest.raises(ValueError, match="wheel artifact"):
        D2ReleaseSoakBundle(
            release=_release(wheel_sha="9" * 64),
            soak=_soak(),
            artifacts=_all_artifacts(),
            generated_at=NOW + timedelta(hours=74),
        )

    with pytest.raises(ValueError, match="image digest"):
        D2ReleaseSoakBundle(
            release=_release(image_digest="sha256:" + "9" * 64),
            soak=_soak(),
            artifacts=_all_artifacts(),
            generated_at=NOW + timedelta(hours=74),
        )


def test_d2_rejects_secret_bearing_artifact_metadata() -> None:
    with pytest.raises(ValueError, match="secret-bearing"):
        D2Artifact(
            kind=D2ArtifactKind.SBOM,
            uri="file:/tmp/Authorization:Bearer leak",
            sha256="8" * 64,
            size_bytes=10,
            produced_by="job",
        )


def test_d2_manifest_hashes_actual_files(tmp_path: Path) -> None:
    wheel = tmp_path / "candidate.whl"
    image = tmp_path / "image-digest.txt"
    wheel.write_text("wheel-bytes", encoding="utf-8")
    image.write_text("image-digest", encoding="utf-8")
    wheel_sha = hashlib.sha256(wheel.read_bytes()).hexdigest()
    image_sha = hashlib.sha256(image.read_bytes()).hexdigest()
    artifacts = [
        {"kind": "wheel", "path": "candidate.whl"},
        {"kind": "image-digest", "path": "image-digest.txt"},
    ]
    for kind in (
        "wheelhouse",
        "sbom",
        "dependency-graph",
        "provenance",
        "source-wheel-parity",
        "policy-bundle",
        "provider-contracts",
        "soak-summary",
        "soak-events",
        "resource-metrics",
        "restart-recovery",
    ):
        path = tmp_path / f"{kind}.json"
        path.write_text(kind, encoding="utf-8")
        artifacts.append({"kind": kind, "path": path.name})

    manifest = {
        "generated_at": (NOW + timedelta(hours=74)).isoformat(),
        "release": _release(wheel_sha=wheel_sha, image_digest="sha256:" + image_sha).to_dict(),
        "soak": _soak().to_dict(),
        "artifacts": artifacts,
    }

    bundle = bundle_from_manifest(manifest, base_dir=tmp_path)

    assert bundle.readiness is D2Readiness.READY_FOR_REVIEW
    assert bundle.artifacts[0].sha256 == wheel_sha
    assert bundle.artifacts[1].sha256 == image_sha


def test_d2_script_outputs_blocked_json_for_incomplete_manifest(tmp_path: Path) -> None:
    wheel = tmp_path / "candidate.whl"
    wheel.write_text("wheel-bytes", encoding="utf-8")
    wheel_sha = hashlib.sha256(wheel.read_bytes()).hexdigest()
    manifest = {
        "release": _release(wheel_sha=wheel_sha).to_dict(),
        "soak": _soak(non_synthetic=False).to_dict(),
        "artifacts": [{"kind": "wheel", "path": "candidate.whl"}],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "scripts/d2_release_soak_bundle.py", "--manifest", str(manifest_path)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["schema_version"] == "mega-pr-d2.real-soak-release-artifacts.v1"
    assert payload["readiness"] == "blocked"
    assert "SOAK_SYNTHETIC_OR_FIXTURE_CONTAMINATED" in payload["blockers"]
