#!/usr/bin/env python3
"""Materialize static MPR-TD-04 upgrade and application-security evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.release import (  # noqa: E402
    GenerationFenceStore,
    HandoffPhase,
    HandoffState,
    ReleaseGenerationIdentity,
    StaleGenerationError,
    decide_rollback,
)
from src.security import (  # noqa: E402
    InputLimits,
    InputSecurityError,
    NetworkSecurityError,
    UrlPolicy,
    decode_bounded_json_object,
    validate_url,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _release_checks(errors: list[str]) -> dict[str, Any]:
    digest = "a" * 64
    identity = ReleaseGenerationIdentity(
        source_sha="b" * 40,
        wheel_sha256=digest,
        image_digest=None,
        schema_registry_sha256=digest,
        config_identity="verification-config",
        provider_registry_sha256=digest,
        capability_manifest_sha256=digest,
        production_surface_sha256=digest,
        runtime_authority_sha256=digest,
        dependency_lock_sha256=digest,
        migration_set_sha256=digest,
    )
    database = sqlite3.connect(":memory:")
    fence_store = GenerationFenceStore(database)
    old_fence = fence_store.activate("old-generation")
    new_fence = fence_store.activate("new-generation", expected_epoch=old_fence.epoch)
    try:
        fence_store.assert_authorized(old_fence)
        errors.append("stale generation retained authority")
    except StaleGenerationError:
        stale_worker_denied = True
    else:
        stale_worker_denied = False
    fence_store.assert_authorized(new_fence)

    state = HandoffState("verify-upgrade", "old-generation", "new-generation")
    for phase in (
        HandoffPhase.ADMISSION_STOPPED,
        HandoffPhase.DRAINED,
        HandoffPhase.BACKED_UP,
        HandoffPhase.MIGRATED,
        HandoffPhase.ACTIVATED,
        HandoffPhase.VERIFIED,
        HandoffPhase.RESUMED,
    ):
        state = state.transition(phase)

    rollback = decide_rollback(
        storage_backward_readable=True,
        configuration_compatible=True,
        provider_contracts_compatible=True,
        destructive_contraction=False,
        immutable_previous_artifact_available=True,
        verified_backup_available=True,
    )
    return {
        "sample_generation_id": identity.generation_id,
        "stale_worker_denied": stale_worker_denied,
        "active_epoch": new_fence.epoch,
        "handoff_terminal_phase": state.phase.value,
        "rollback_contract_allows_compatible_case": rollback.allowed,
    }


def _security_checks(errors: list[str]) -> dict[str, Any]:
    limits = InputLimits(max_bytes=1024)
    decode_bounded_json_object(b'{"safe":1}', limits=limits)
    duplicate_rejected = False
    try:
        decode_bounded_json_object(b'{"x":1,"x":2}', limits=limits)
    except InputSecurityError:
        duplicate_rejected = True
    if not duplicate_rejected:
        errors.append("duplicate JSON keys were accepted")

    private_url_rejected = False
    try:
        validate_url(
            "https://127.0.0.1/internal",
            policy=UrlPolicy(frozenset({"127.0.0.1"})),
        )
    except NetworkSecurityError:
        private_url_rejected = True
    if not private_url_rejected:
        errors.append("private literal URL was accepted")

    attack_surface = _load_json(ROOT / "config/mpr_td_04_attack_surface_manifest.json")
    surfaces = attack_surface.get("surfaces")
    if not isinstance(surfaces, list) or not surfaces:
        errors.append("attack-surface manifest has no surfaces")
        surfaces = []
    required = {
        "surface_id",
        "owner",
        "module",
        "callable",
        "input_origin",
        "trust_level",
        "max_bytes",
        "max_depth",
        "max_nodes",
        "failure_reason_code",
        "tests",
    }
    missing_fields = 0
    missing_tests = 0
    for surface in surfaces:
        if not isinstance(surface, dict) or not required.issubset(surface):
            missing_fields += 1
            continue
        for test in surface["tests"]:
            if not (ROOT / str(test)).is_file():
                missing_tests += 1
    if missing_fields:
        errors.append(f"{missing_fields} attack surfaces are incomplete")
    if missing_tests:
        errors.append(f"{missing_tests} attack-surface tests are missing")

    subprocess_policy = _load_json(ROOT / "config/subprocess_allowlist.json")
    entries = subprocess_policy.get("production_entries")
    if not isinstance(entries, list):
        errors.append("subprocess allowlist entries must be a list")
        entries = []

    return {
        "duplicate_json_keys_rejected": duplicate_rejected,
        "private_literal_url_rejected": private_url_rejected,
        "attack_surface_count": len(surfaces),
        "attack_surface_missing_fields": missing_fields,
        "attack_surface_missing_tests": missing_tests,
        "authorized_new_production_subprocesses": len(entries),
    }


def _predecessor_status() -> dict[str, Any]:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    mpr1_blockers = []
    if "src.cli_pr189:main" in pyproject:
        mpr1_blockers.append("historical installed entrypoint remains active")
    if not (ROOT / "src/resources/schema_registry.json").is_file():
        mpr1_blockers.append("canonical schema registry is not materialized")

    mpr2_blockers = []
    if not (ROOT / "scripts/verify_mpr_td_02_failure_verification.py").is_file():
        mpr2_blockers.append("authoritative MPR-TD-02 verifier is absent")

    mpr3_blockers = []
    if not (ROOT / "scripts/verify_mpr_td_03_capacity_storage.py").is_file():
        mpr3_blockers.append("capacity/storage verifier is absent")
    if not (ROOT / "config/capacity_profiles.json").is_file():
        mpr3_blockers.append("capacity profile registry is absent")

    return {
        "mpr_td_01": {"complete": not mpr1_blockers, "blockers": mpr1_blockers},
        "mpr_td_02": {"complete": not mpr2_blockers, "blockers": mpr2_blockers},
        "mpr_td_03": {"complete": not mpr3_blockers, "blockers": mpr3_blockers},
    }


def build_evidence() -> dict[str, Any]:
    errors: list[str] = []
    release_policy = ROOT / "src/resources/release_upgrade_policy.json"
    filesystem_roots = ROOT / "src/resources/filesystem_root_registry.json"
    attack_surface = ROOT / "config/mpr_td_04_attack_surface_manifest.json"
    subprocess_allowlist = ROOT / "config/subprocess_allowlist.json"
    required_paths = (
        release_policy,
        filesystem_roots,
        attack_surface,
        subprocess_allowlist,
    )
    for path in required_paths:
        if not path.is_file():
            errors.append(f"missing required artifact: {path.relative_to(ROOT)}")

    release_checks = _release_checks(errors) if not errors else {}
    security_checks = _security_checks(errors) if not errors else {}
    predecessor = _predecessor_status()

    external_blockers = [
        "accepted immutable N-1 wheel/image not materialized by this static verifier",
        "production image sandbox qualification requires an authoritative built image",
        "multi-duration fuzz and deployment drills require real elapsed execution",
    ]
    predecessor_blockers = [
        f"{name}: {blocker}"
        for name, status in predecessor.items()
        for blocker in status["blockers"]
    ]

    return {
        "schema_version": "mpr-td-04.upgrade-security-evidence.v1",
        "static_contract_passed": not errors,
        "production_ready": False,
        "sender_free": True,
        "release_policy_sha256": (
            _sha(release_policy) if release_policy.is_file() else None
        ),
        "filesystem_root_registry_sha256": (
            _sha(filesystem_roots) if filesystem_roots.is_file() else None
        ),
        "attack_surface_manifest_sha256": (
            _sha(attack_surface) if attack_surface.is_file() else None
        ),
        "subprocess_allowlist_sha256": (
            _sha(subprocess_allowlist) if subprocess_allowlist.is_file() else None
        ),
        "release_checks": release_checks,
        "security_checks": security_checks,
        "predecessor_status": predecessor,
        "errors": errors,
        "blockers": predecessor_blockers + external_blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Fail when predecessor or external qualification blockers remain.",
    )
    args = parser.parse_args()
    evidence = build_evidence()
    print(json.dumps(evidence, sort_keys=True, indent=2))
    if not evidence["static_contract_passed"]:
        return 1
    if args.require_complete and evidence["blockers"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
