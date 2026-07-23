from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.verify_pr200_production_cutover import (
    ProductionCutoverError,
    REQUIRED_FAULT_INJECTIONS,
    REQUIRED_RELEASE_ARTIFACTS,
    validate_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "config/production_cutover_manifest.json"


def _load_current_manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_pr200_cutover_gate_accepts_current_manifest() -> None:
    evidence = validate_manifest(_load_current_manifest())

    assert evidence["accepted"] is True
    assert evidence["promotion_state"] == "blocked_pending_evidence"
    assert evidence["live_trading_enabled"] is False
    assert evidence["release_artifact_count"] == len(REQUIRED_RELEASE_ARTIFACTS)
    assert evidence["fault_injection_count"] == len(REQUIRED_FAULT_INJECTIONS)
    assert "MISSING_RUNTIME_IMAGE_DIGEST" in evidence["promotion_blockers"]


def test_pr200_cutover_gate_rejects_live_promotion() -> None:
    manifest = _load_current_manifest()
    manifest["promotion_state"] = "ready_for_live"
    manifest["live_trading_enabled"] = True

    with pytest.raises(ProductionCutoverError, match="blocked until evidence"):
        validate_manifest(manifest)


def test_pr200_cutover_gate_rejects_signer_network_escape() -> None:
    manifest = _load_current_manifest()
    signer = manifest["isolation"]["signer"]  # type: ignore[index]
    signer["shared_internet_egress_allowed"] = True

    with pytest.raises(ProductionCutoverError, match="signer"):
        validate_manifest(manifest)


def test_pr200_cutover_gate_rejects_probe_conflation() -> None:
    manifest = _load_current_manifest()
    readiness = manifest["readiness"]  # type: ignore[index]
    readiness["readiness_endpoint"] = readiness["liveness_endpoint"]

    with pytest.raises(ProductionCutoverError, match="distinct"):
        validate_manifest(manifest)


def test_pr200_cutover_gate_rejects_missing_fault_drill() -> None:
    manifest = _load_current_manifest()
    fault_cases = copy.deepcopy(manifest["fault_injection"])  # type: ignore[index]
    manifest["fault_injection"] = [
        case for case in fault_cases if case["id"] != "jito_ack_without_chain_record"
    ]

    with pytest.raises(ProductionCutoverError, match="missing fault injections"):
        validate_manifest(manifest)


def test_pr200_cutover_gate_rejects_missing_release_artifact() -> None:
    manifest = _load_current_manifest()
    artifacts = copy.deepcopy(
        manifest["required_release_artifacts"]
    )  # type: ignore[index]
    manifest["required_release_artifacts"] = [
        artifact
        for artifact in artifacts
        if artifact["id"] != "backup_restore_report_digest"
    ]

    with pytest.raises(ProductionCutoverError, match="missing release artifacts"):
        validate_manifest(manifest)


def test_pr200_cutover_gate_requires_drain_only_rollback() -> None:
    manifest = _load_current_manifest()
    rollback = manifest["rollback"]  # type: ignore[index]
    rollback["mode"] = "replace-writer"

    with pytest.raises(ProductionCutoverError, match="drain-only"):
        validate_manifest(manifest)
