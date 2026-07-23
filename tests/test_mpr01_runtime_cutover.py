from __future__ import annotations

from copy import deepcopy

from scripts.verify_mpr01_runtime_cutover import evaluate_manifest
from src.production_surface import load_manifest


def manifest_copy() -> dict[str, object]:
    return deepcopy(load_manifest())


def test_mpr01_runtime_cutover_gate_passes_as_blocked_not_ready() -> None:
    evidence = evaluate_manifest(manifest_copy())
    assert evidence["gate_passed"] is True
    assert evidence["production_ready"] is False
    assert evidence["paper_ready"] is False
    assert evidence["state"] == "blocked_pending_runtime_cutover"
    assert evidence["blockers"] == []


def test_mpr01_rejects_missing_runtime_cutover_contract() -> None:
    manifest = manifest_copy()
    manifest.pop("runtime_cutover")
    evidence = evaluate_manifest(manifest)
    assert evidence["gate_passed"] is False
    assert "MPR01_SECTION_MISSING:runtime_cutover" in evidence["blockers"]


def test_mpr01_rejects_paper_ready_claim_without_vertical_truth() -> None:
    manifest = manifest_copy()
    cutover = manifest["runtime_cutover"]
    assert isinstance(cutover, dict)
    cutover["paper_ready"] = True
    evidence = evaluate_manifest(manifest)
    assert "MPR01_PAPER_READY_CLAIMED_WITHOUT_VERTICAL_TRUTH" in evidence["blockers"]


def test_mpr01_rejects_live_capability_weakening() -> None:
    manifest = manifest_copy()
    runtime = manifest["runtime"]
    assert isinstance(runtime, dict)
    runtime["live_trading_enabled"] = True
    evidence = evaluate_manifest(manifest)
    assert "MPR01_LIVE_CAPABILITY_ENABLED" in evidence["blockers"]


def test_mpr01_rejects_container_paper_mode_claiming_ready() -> None:
    manifest = manifest_copy()
    cutover = manifest["runtime_cutover"]
    assert isinstance(cutover, dict)
    container = cutover["container_paper_mode"]
    assert isinstance(container, dict)
    container["workload_ready"] = True
    evidence = evaluate_manifest(manifest)
    assert "MPR01_CONTAINER_PAPER_MODE_CLAIMS_WORKLOAD_READY" in evidence["blockers"]


def test_mpr01_rejects_missing_required_endpoint() -> None:
    manifest = manifest_copy()
    cutover = manifest["runtime_cutover"]
    assert isinstance(cutover, dict)
    endpoints = cutover["readiness_endpoints"]
    assert isinstance(endpoints, list)
    cutover["readiness_endpoints"] = [
        endpoint for endpoint in endpoints if endpoint.get("name") != "live_gate"
    ]
    evidence = evaluate_manifest(manifest)
    assert "MPR01_REQUIRED_ENDPOINT_MISSING:live_gate" in evidence["blockers"]


def test_mpr01_rejects_weakened_release_truth_flag() -> None:
    manifest = manifest_copy()
    cutover = manifest["runtime_cutover"]
    assert isinstance(cutover, dict)
    release = cutover["release_truth"]
    assert isinstance(release, dict)
    release["full_sha_actions_required"] = False
    evidence = evaluate_manifest(manifest)
    assert "MPR01_RELEASE_TRUTH_FLAG_MISSING:full_sha_actions_required" in evidence["blockers"]


def test_mpr01_rejects_unknown_proof_island_disposition() -> None:
    manifest = manifest_copy()
    cutover = manifest["runtime_cutover"]
    assert isinstance(cutover, dict)
    islands = cutover["proof_island_dispositions"]
    assert isinstance(islands, list)
    islands[0] = {"module": "src.pr198_sender_free_qualification_v3", "disposition": "already_authoritative"}
    evidence = evaluate_manifest(manifest)
    assert "MPR01_PROOF_ISLAND_DISPOSITION_INVALID:src.pr198_sender_free_qualification_v3" in evidence["blockers"]
