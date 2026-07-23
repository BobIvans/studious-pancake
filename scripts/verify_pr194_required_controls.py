#!/usr/bin/env python3
"""PR-194 required-control manifest verifier.

The verifier is intentionally offline and sender-free. It validates that the
packaged production-surface manifest names the installed console entrypoints,
their backing required controls, the wheel members that must ship those
controls, and the CLI contracts that must fail closed when paper/live readiness
is blocked or misconfigured.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.production_surface import (  # noqa: E402
    ProductionSurfaceError,
    blocked_command_contracts,
    load_manifest,
    required_control_modules,
    required_control_wheel_members,
    required_controls,
    required_entrypoints,
    required_wheel_members,
)

EVIDENCE_SCHEMA = "pr194.required-control-gate.v1"
EXPECTED_BLOCKED_EXIT = "non_zero_when_blocked"
REQUIRED_BLOCKED_COMMANDS = frozenset(
    {
        "flashloan-bot paper-vertical check",
        "flashloan-bot readiness check",
        "flashloan-checks production-debt check",
    }
)


def _entrypoint_module(target: str) -> str:
    return target.split(":", 1)[0]


def _module_source_exists(root: Path, module: str) -> bool:
    relative = Path(*module.split("."))
    return (root / relative.with_suffix(".py")).is_file() or (
        root / relative / "__init__.py"
    ).is_file()


def _resource_exists(root: Path, member: str) -> bool:
    return (root / member).is_file()


def evaluate_manifest(
    manifest: Mapping[str, Any],
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Return deterministic PR-194 evidence for a manifest object."""

    blockers: list[str] = []
    try:
        entrypoints = required_entrypoints(manifest)
        controls = required_controls(manifest)
        control_modules = required_control_modules(manifest)
        control_members = required_control_wheel_members(manifest)
        wheel_members = required_wheel_members(manifest)
        exit_contracts = blocked_command_contracts(manifest)
    except ProductionSurfaceError as exc:
        return {
            "schema_version": EVIDENCE_SCHEMA,
            "ready": False,
            "blockers": [f"PR194_MANIFEST_INVALID:{type(exc).__name__}"],
            "details": {"error": str(exc)},
        }

    runtime = manifest.get("runtime")
    if not isinstance(runtime, Mapping):
        blockers.append("PR194_RUNTIME_SECTION_MISSING")
        runtime = {}

    if manifest.get("schema_version") != "pr194.production-surface.v1":
        blockers.append("PR194_PRODUCTION_SURFACE_SCHEMA_MISMATCH")
    if manifest.get("product_state") != "not-production-ready":
        blockers.append("PR194_PRODUCT_STATE_WEAKENED")
    if runtime.get("live_trading_enabled") is not False:
        blockers.append("PR194_LIVE_CAPABILITY_ENABLED")
    if runtime.get("sender_free") is not True:
        blockers.append("PR194_SENDER_FREE_CONTRACT_WEAKENED")

    controls_by_module = {control["module"]: control for control in controls}
    controls_by_entrypoint = {
        control["entrypoint"]: control
        for control in controls
        if "entrypoint" in control
    }

    for executable, target in sorted(entrypoints.items()):
        module = _entrypoint_module(target)
        if module not in control_modules:
            blockers.append(f"PR194_ENTRYPOINT_CONTROL_MISSING:{executable}:{module}")
        if executable not in controls_by_entrypoint:
            blockers.append(f"PR194_ENTRYPOINT_CONTROL_UNBOUND:{executable}")
        elif controls_by_entrypoint[executable]["module"] != module:
            blockers.append(f"PR194_ENTRYPOINT_CONTROL_TARGET_DRIFT:{executable}")

    for control in controls:
        control_id = control["id"]
        module = control["module"]
        wheel_member = control["wheel_member"]
        if wheel_member not in wheel_members:
            blockers.append(f"PR194_CONTROL_NOT_REQUIRED_IN_WHEEL:{control_id}")
        if not _module_source_exists(root, module):
            blockers.append(f"PR194_CONTROL_MODULE_MISSING:{control_id}:{module}")
        if not _resource_exists(root, wheel_member):
            blockers.append(f"PR194_CONTROL_WHEEL_MEMBER_MISSING:{control_id}")

    if not control_members.issubset(wheel_members):
        blockers.append("PR194_CONTROL_WHEEL_MEMBER_SET_DRIFT")

    contract_commands = {contract["command"] for contract in exit_contracts}
    for command in sorted(REQUIRED_BLOCKED_COMMANDS - contract_commands):
        blockers.append(f"PR194_BLOCKED_EXIT_CONTRACT_MISSING:{command}")

    for contract in exit_contracts:
        if contract["expected_exit"] != EXPECTED_BLOCKED_EXIT:
            blockers.append(
                f"PR194_BLOCKED_EXIT_CONTRACT_WEAKENED:{contract['command']}"
            )

    return {
        "schema_version": EVIDENCE_SCHEMA,
        "ready": not blockers,
        "blockers": sorted(dict.fromkeys(blockers)),
        "details": {
            "entrypoints": dict(sorted(entrypoints.items())),
            "required_control_count": len(controls),
            "required_control_ids": sorted(control["id"] for control in controls),
            "required_control_modules": sorted(controls_by_module),
            "required_control_wheel_members": sorted(control_members),
            "blocked_command_contracts": sorted(contract_commands),
            "product_state": manifest.get("product_state"),
            "runtime": dict(runtime),
        },
    }


def build_evidence(*, root: Path = ROOT) -> dict[str, Any]:
    """Load the packaged manifest and evaluate PR-194 required-control evidence."""

    return evaluate_manifest(load_manifest(), root=root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the deterministic PR-194 required-control evidence payload.",
    )
    args = parser.parse_args(argv)

    evidence = build_evidence()
    if args.json or not evidence["ready"]:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    else:
        print("PR-194 required-control manifest gate passed.")
    return 0 if evidence["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
