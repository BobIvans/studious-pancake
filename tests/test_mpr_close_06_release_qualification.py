from __future__ import annotations

import json
from pathlib import Path

from scripts.qualify_release import build_release_bundle


ROOT = Path(__file__).resolve().parents[1]


def _copy(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def test_qualify_release_materializes_bundle_and_stays_blocked_without_full_evidence(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _copy(ROOT / "src" / "resources" / "capabilities.json", repo / "src" / "resources" / "capabilities.json")
    _copy(ROOT / "src" / "resources" / "production_debt.json", repo / "src" / "resources" / "production_debt.json")
    _copy(ROOT / "config" / "runtime_authority_map.json", repo / "config" / "runtime_authority_map.json")
    _copy(ROOT / "config" / "production_cutover_manifest.json", repo / "config" / "production_cutover_manifest.json")

    output = repo / ".runtime" / "release-qualification.json"
    qualification = build_release_bundle(
        repo,
        release_id="pytest-release",
        output_path=output,
        profile="production",
    )

    assert qualification["schema_version"] == "mpr-close-06.release-qualification.v1"
    assert qualification["qualified"] is False
    assert qualification["promotion_state"] == "blocked_pending_evidence"
    assert "runtime_image_digest" in qualification["missing_artifacts"]

    bundle_manifest = repo / "release_artifacts" / "final" / "pytest-release" / "bundle_manifest.json"
    human_review = repo / "release_artifacts" / "final" / "pytest-release" / "human_review_manifest.json"
    assert bundle_manifest.is_file()
    assert human_review.is_file()

    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["bundle_manifest_path"] == bundle_manifest.relative_to(repo).as_posix()
    assert written["debt_resolution"]["runtime.product-state"]["resolved"] is False
