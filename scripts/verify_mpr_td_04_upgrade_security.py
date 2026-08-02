#!/usr/bin/env python3
"""Materialize combined repository-closure and production-qualification evidence."""

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

from scripts.verify_mpr_td_01_canonical_surface import (  # noqa: E402
    build_evidence as verify_td01,
)
from scripts.verify_mpr_td_02_failure_verification import (  # noqa: E402
    build_evidence as verify_td02,
)
from scripts.verify_mpr_td_03_capacity_storage import (  # noqa: E402
    build_evidence as verify_td03,
)
from src.release import (  # noqa: E402
    GenerationFenceStore,
    HandoffPhase,
    HandoffState,
    StaleGenerationError,
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


def _load_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"invalid JSON policy {path.relative_to(ROOT)}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"policy {path.relative_to(ROOT)} must contain a JSON object")
        return {}
    return value


def _validate_policy_artifacts(errors: list[str]) -> dict[str, object]:
    release_path = ROOT / "src/resources/release_upgrade_policy.json"
    roots_path = ROOT / "src/resources/filesystem_root_registry.json"
    attack_path = ROOT / "config/mpr_td_04_attack_surface_manifest.json"
    subprocess_path = ROOT / "config/subprocess_allowlist.json"
    paths = {
        "release_policy": release_path,
        "filesystem_roots": roots_path,
        "attack_surface": attack_path,
        "subprocess_allowlist": subprocess_path,
    }
    for path in paths.values():
        if not path.is_file():
            errors.append(f"missing MPR-TD-04 policy artifact: {path.relative_to(ROOT)}")
    if any(not path.is_file() for path in paths.values()):
        return {
            "paths": paths,
            "attack_surface_count": 0,
            "subprocess_count": 0,
            "filesystem_root_count": 0,
        }

    release = _load_json(release_path, errors)
    if release.get("schema_id") != "release-upgrade-policy.v1":
        errors.append("release upgrade policy schema_id is invalid")
    if release.get("sender_free") is not True or release.get("live_enabled") is not False:
        errors.append("release upgrade policy weakens sender-free or live-disabled posture")
    required_identity = release.get("required_identity_fields")
    if not isinstance(required_identity, list) or not required_identity:
        errors.append("release upgrade policy has no identity field list")
    required_phases = {
        "preflight",
        "admission_stopped",
        "drained",
        "backed_up",
        "migrated",
        "activated",
        "verified",
        "resumed",
    }
    phases = release.get("handoff_phases")
    if not isinstance(phases, list) or not required_phases.issubset(phases):
        errors.append("release upgrade policy is missing mandatory handoff phases")
    requirements = release.get("requirements")
    mandatory_requirements = {
        "immutable_previous_artifact",
        "verified_backup",
        "generation_fencing",
        "expand_contract_migrations",
        "stale_worker_denial",
        "sender_free",
    }
    if not isinstance(requirements, dict) or any(
        requirements.get(name) is not True for name in mandatory_requirements
    ):
        errors.append("release upgrade policy requirements are incomplete or fail-open")

    roots = _load_json(roots_path, errors)
    if roots.get("schema_id") != "filesystem-root-registry.v1":
        errors.append("filesystem root registry schema_id is invalid")
    root_entries = roots.get("roots")
    if not isinstance(root_entries, list) or not root_entries:
        errors.append("filesystem root registry has no roots")
        root_entries = []
    root_ids: set[str] = set()
    root_required = {
        "root_id",
        "owner",
        "path_source",
        "default_path",
        "read",
        "write",
        "symlinks",
        "special_files",
        "maximum_file_bytes",
        "security_classification",
    }
    for entry in root_entries:
        if not isinstance(entry, dict) or not root_required.issubset(entry):
            errors.append("filesystem root entry is incomplete")
            continue
        root_id = str(entry["root_id"])
        if not root_id or root_id in root_ids:
            errors.append(f"filesystem root ID is empty or duplicated: {root_id!r}")
        root_ids.add(root_id)
        if entry["symlinks"] != "deny" or entry["special_files"] != "deny":
            errors.append(f"filesystem root {root_id} permits unsafe file types")
        maximum = entry["maximum_file_bytes"]
        if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum <= 0:
            errors.append(f"filesystem root {root_id} has invalid byte limit")

    attack = _load_json(attack_path, errors)
    if attack.get("schema_id") != "attack-surface-manifest.v1":
        errors.append("attack-surface manifest schema_id is invalid")
    if attack.get("sender_free") is not True:
        errors.append("attack-surface manifest is not sender-free")
    surfaces = attack.get("surfaces")
    if not isinstance(surfaces, list) or not surfaces:
        errors.append("attack-surface manifest has no surfaces")
        surfaces = []
    surface_required = {
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
    surface_ids: set[str] = set()
    for surface in surfaces:
        if not isinstance(surface, dict) or not surface_required.issubset(surface):
            errors.append("attack-surface record is incomplete")
            continue
        surface_id = str(surface["surface_id"])
        if not surface_id or surface_id in surface_ids:
            errors.append(f"attack-surface ID is empty or duplicated: {surface_id!r}")
        surface_ids.add(surface_id)
        for name in ("max_bytes", "max_depth", "max_nodes"):
            value = surface[name]
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                errors.append(f"attack surface {surface_id} has invalid {name}")
        tests = surface["tests"]
        if not isinstance(tests, list) or not tests:
            errors.append(f"attack surface {surface_id} has no tests")
            continue
        for test in tests:
            if not isinstance(test, str) or not (ROOT / test).is_file():
                errors.append(
                    f"attack surface {surface_id} references missing test: {test!r}"
                )

    subprocess_policy = _load_json(subprocess_path, errors)
    if subprocess_policy.get("schema_id") != "mpr-td-04.subprocess-allowlist.v1":
        errors.append("subprocess allowlist schema_id is invalid")
    entries = subprocess_policy.get("production_entries")
    if not isinstance(entries, list):
        errors.append("subprocess allowlist entries must be a list")
        entries = []
    policy = subprocess_policy.get("policy")
    deny_fields = {
        "shell",
        "inherit_environment",
        "untrusted_executable",
        "unbounded_output",
        "secret_arguments",
    }
    if not isinstance(policy, dict) or any(
        policy.get(name) is not False for name in deny_fields
    ):
        errors.append("subprocess policy is incomplete or fail-open")
    entry_required = {
        "executable",
        "owner",
        "arguments",
        "working_directory",
        "environment",
        "timeout_seconds",
        "maximum_output_bytes",
        "expected_exit_codes",
        "tests",
    }
    for entry in entries:
        if not isinstance(entry, dict) or not entry_required.issubset(entry):
            errors.append("subprocess allowlist entry is incomplete")

    return {
        "paths": paths,
        "attack_surface_count": len(surfaces),
        "subprocess_count": len(entries),
        "filesystem_root_count": len(root_entries),
    }


def build_evidence() -> dict[str, object]:
    errors: list[str] = []
    predecessor_evidence = {
        "mpr_td_01": verify_td01(),
        "mpr_td_02": verify_td02(),
        "mpr_td_03": verify_td03(),
    }
    predecessor_status: dict[str, dict[str, object]] = {}
    for name, evidence in predecessor_evidence.items():
        complete = bool(evidence["accepted"])
        blockers = [] if complete else list(evidence.get("errors", []))
        predecessor_status[name] = {"complete": complete, "blockers": blockers}
        if not complete:
            errors.append(f"{name} repository closure failed: {blockers!r}")

    database = sqlite3.connect(":memory:")
    fence = GenerationFenceStore(database)
    first = fence.activate("generation-a")
    second = fence.activate("generation-b", expected_epoch=first.epoch)
    stale_denied = False
    try:
        fence.assert_authorized(first)
    except StaleGenerationError:
        stale_denied = True
    if not stale_denied:
        errors.append("stale generation retained authority")
    fence.assert_authorized(second)

    state = HandoffState("closure", "generation-a", "generation-b")
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

    duplicate_rejected = False
    try:
        decode_bounded_json_object(
            b'{"x":1,"x":2}', limits=InputLimits(max_bytes=1024)
        )
    except InputSecurityError:
        duplicate_rejected = True
    if not duplicate_rejected:
        errors.append("duplicate JSON keys were accepted")

    private_rejected = False
    try:
        validate_url(
            "https://127.0.0.1/internal",
            policy=UrlPolicy(frozenset({"127.0.0.1"})),
        )
    except NetworkSecurityError:
        private_rejected = True
    if not private_rejected:
        errors.append("private literal URL was accepted")

    policy_evidence = _validate_policy_artifacts(errors)
    paths = policy_evidence["paths"]

    qualification_blockers = [
        "accepted immutable N-1 wheel/image lineage is not materialized in the repository",
        "production-scale capacity and multi-duration soak require an external controlled environment",
        "production sandbox qualification requires an authoritative deployed image",
    ]
    static_passed = not errors
    return {
        "schema_version": "mpr-td-04.upgrade-security-evidence.v1",
        "accepted": static_passed,
        "static_contract_passed": static_passed,
        "repository_closure_complete": static_passed,
        "production_ready": False,
        "sender_free": True,
        "predecessor_status": predecessor_status,
        "predecessor_evidence": predecessor_evidence,
        "release_policy_sha256": (
            _sha(paths["release_policy"])
            if paths["release_policy"].is_file()
            else None
        ),
        "filesystem_root_registry_sha256": (
            _sha(paths["filesystem_roots"])
            if paths["filesystem_roots"].is_file()
            else None
        ),
        "attack_surface_manifest_sha256": (
            _sha(paths["attack_surface"])
            if paths["attack_surface"].is_file()
            else None
        ),
        "subprocess_allowlist_sha256": (
            _sha(paths["subprocess_allowlist"])
            if paths["subprocess_allowlist"].is_file()
            else None
        ),
        "release_checks": {
            "stale_worker_denied": stale_denied,
            "active_epoch": second.epoch,
            "handoff_terminal_phase": state.phase.value,
        },
        "security_checks": {
            "duplicate_json_keys_rejected": duplicate_rejected,
            "private_literal_url_rejected": private_rejected,
            "attack_surface_count": policy_evidence["attack_surface_count"],
            "filesystem_root_count": policy_evidence["filesystem_root_count"],
            "authorized_new_production_subprocesses": policy_evidence["subprocess_count"],
        },
        "errors": errors,
        "blockers": qualification_blockers,
        "qualification_blockers": qualification_blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Fail when external production-qualification blockers remain.",
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
