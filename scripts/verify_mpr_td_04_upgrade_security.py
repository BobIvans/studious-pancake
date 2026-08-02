#!/usr/bin/env python3
"""Materialize combined repository-closure and production-qualification evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

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
        predecessor_status[name] = {
            "complete": complete,
            "blockers": blockers,
        }
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

    required_paths = {
        "release_policy": ROOT / "src/resources/release_upgrade_policy.json",
        "filesystem_roots": ROOT / "src/resources/filesystem_root_registry.json",
        "attack_surface": ROOT / "config/mpr_td_04_attack_surface_manifest.json",
        "subprocess_allowlist": ROOT / "config/subprocess_allowlist.json",
    }
    missing = [
        str(path.relative_to(ROOT))
        for path in required_paths.values()
        if not path.is_file()
    ]
    if missing:
        errors.append(f"missing MPR-TD-04 policy artifacts: {missing!r}")

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
            _sha(required_paths["release_policy"])
            if required_paths["release_policy"].is_file()
            else None
        ),
        "filesystem_root_registry_sha256": (
            _sha(required_paths["filesystem_roots"])
            if required_paths["filesystem_roots"].is_file()
            else None
        ),
        "attack_surface_manifest_sha256": (
            _sha(required_paths["attack_surface"])
            if required_paths["attack_surface"].is_file()
            else None
        ),
        "subprocess_allowlist_sha256": (
            _sha(required_paths["subprocess_allowlist"])
            if required_paths["subprocess_allowlist"].is_file()
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
