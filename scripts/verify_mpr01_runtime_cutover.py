#!/usr/bin/env python3
"""MPR-01 canonical runtime and release-truth verifier."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.production_surface import load_manifest, required_entrypoints  # noqa: E402

EVIDENCE_SCHEMA = "mpr01.runtime-cutover-gate.v1"
CONTRACT_SCHEMA = "mpr01.runtime-cutover.v1"
EXPECTED_STATE = "blocked_pending_runtime_cutover"
REQUIRED_ENDPOINTS = {"liveness", "safe_idle", "data_ready", "paper_ready", "live_gate"}
REQUIRED_BLOCKERS = {
    "MPR01_SAFE_IDLE_NOT_WORKLOAD_READY",
    "MPR01_PAPER_CONTAINER_COMPOSITION_NOT_UNIFIED",
    "MPR01_RELEASE_QUALIFICATION_NOT_AUTHORITATIVE",
    "MPR01_PROOF_ISLANDS_NOT_RUNTIME_AUTHORITIES",
}
REQUIRED_RELEASE_FLAGS = {
    "clean_wheel_import_closure_required",
    "network_disabled_release_required",
    "signed_wheelhouse_required",
    "sbom_required",
    "full_sha_actions_required",
    "ambient_packages_forbidden",
}
ALLOWED_DISPOSITIONS = {
    "must_integrate_or_quarantine",
    "diagnostic_only_not_ready",
    "alias_to_canonical_required",
}


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def evaluate_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    runtime = _mapping(manifest.get("runtime"))
    cutover = _mapping(manifest.get("runtime_cutover"))
    canonical = _mapping(cutover.get("canonical_composition"))
    container = _mapping(cutover.get("container_paper_mode"))
    release = _mapping(cutover.get("release_truth"))
    entrypoints = required_entrypoints(manifest)

    if not cutover:
        blockers.append("MPR01_SECTION_MISSING:runtime_cutover")
    if manifest.get("product_state") != "not-production-ready":
        blockers.append("MPR01_PRODUCT_STATE_WEAKENED")
    if runtime.get("live_trading_enabled") is not False:
        blockers.append("MPR01_LIVE_CAPABILITY_ENABLED")
    if runtime.get("sender_free") is not True:
        blockers.append("MPR01_SENDER_FREE_CONTRACT_WEAKENED")
    if cutover.get("schema_version") != CONTRACT_SCHEMA:
        blockers.append("MPR01_CUTOVER_SCHEMA_MISMATCH")
    if cutover.get("roadmap") != "MPR-01":
        blockers.append("MPR01_ROADMAP_ID_MISMATCH")
    if cutover.get("state") != EXPECTED_STATE:
        blockers.append("MPR01_CUTOVER_STATE_WEAKENED")
    if cutover.get("production_ready") is not False:
        blockers.append("MPR01_PRODUCTION_READY_CLAIMED_WITHOUT_RELEASE_TRUTH")
    if cutover.get("paper_ready") is not False:
        blockers.append("MPR01_PAPER_READY_CLAIMED_WITHOUT_VERTICAL_TRUTH")

    if canonical.get("supported_entrypoint") != runtime.get("supported_entrypoint"):
        blockers.append("MPR01_CANONICAL_ENTRYPOINT_DRIFT")
    if canonical.get("console_entrypoint") not in entrypoints:
        blockers.append("MPR01_CANONICAL_CONSOLE_ENTRYPOINT_NOT_INSTALLED")
    if canonical.get("paper_command") != "flashloan-bot paper":
        blockers.append("MPR01_CANONICAL_PAPER_COMMAND_DRIFT")
    if canonical.get("composition_module") != "src.cli_pr189":
        blockers.append("MPR01_CANONICAL_COMPOSITION_MODULE_DRIFT")
    if container.get("workload_ready") is not False:
        blockers.append("MPR01_CONTAINER_PAPER_MODE_CLAIMS_WORKLOAD_READY")

    endpoints = cutover.get("readiness_endpoints", [])
    endpoint_names = {item.get("name") for item in endpoints if isinstance(item, Mapping)}
    for required in sorted(REQUIRED_ENDPOINTS - endpoint_names):
        blockers.append(f"MPR01_REQUIRED_ENDPOINT_MISSING:{required}")
    for item in endpoints if isinstance(endpoints, list) else []:
        if isinstance(item, Mapping) and item.get("name") in {"data_ready", "paper_ready", "live_gate"}:
            if item.get("may_be_green_when_blocked") is not False:
                blockers.append(f"MPR01_WORKLOAD_ENDPOINT_CAN_BE_GREEN_WHEN_BLOCKED:{item.get('name')}")

    declared = set(cutover.get("declared_blockers", [])) if isinstance(cutover.get("declared_blockers"), list) else set()
    for required in sorted(REQUIRED_BLOCKERS - declared):
        blockers.append(f"MPR01_DECLARED_BLOCKER_MISSING:{required}")
    if release.get("authoritative_check") != "release-qualification":
        blockers.append("MPR01_AUTHORITATIVE_RELEASE_CHECK_NOT_DECLARED")
    for flag in sorted(REQUIRED_RELEASE_FLAGS):
        if release.get(flag) is not True:
            blockers.append(f"MPR01_RELEASE_TRUTH_FLAG_MISSING:{flag}")
    commands = set(release.get("local_reproduction_commands", [])) if isinstance(release.get("local_reproduction_commands"), list) else set()
    if "python scripts/verify_repo.py --skip-dependency-audit" not in commands:
        blockers.append("MPR01_LOCAL_VERIFY_REPRODUCTION_MISSING")
    if "python scripts/verify_mpr01_runtime_cutover.py --json" not in commands:
        blockers.append("MPR01_LOCAL_CUTOVER_REPRODUCTION_MISSING")

    islands = cutover.get("proof_island_dispositions", [])
    if not isinstance(islands, list) or not islands:
        blockers.append("MPR01_PROOF_ISLAND_INVENTORY_EMPTY")
    for island in islands if isinstance(islands, list) else []:
        if not isinstance(island, Mapping) or island.get("disposition") not in ALLOWED_DISPOSITIONS:
            blockers.append(f"MPR01_PROOF_ISLAND_DISPOSITION_INVALID:{island.get('module') if isinstance(island, Mapping) else 'unknown'}")

    unique = sorted(dict.fromkeys(blockers))
    return {
        "schema_version": EVIDENCE_SCHEMA,
        "contract_schema": cutover.get("schema_version"),
        "roadmap": cutover.get("roadmap"),
        "state": cutover.get("state"),
        "gate_passed": not unique,
        "production_ready": False,
        "paper_ready": False,
        "blockers": unique,
        "details": {
            "supported_entrypoint": runtime.get("supported_entrypoint"),
            "readiness_endpoints": sorted(name for name in endpoint_names if isinstance(name, str)),
            "proof_island_count": len(islands) if isinstance(islands, list) else 0,
        },
    }


def build_evidence() -> dict[str, Any]:
    return evaluate_manifest(load_manifest())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    evidence = build_evidence()
    if args.json or not evidence["gate_passed"]:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    else:
        print("MPR-01 canonical runtime cutover gate passed.")
    return 0 if evidence["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
