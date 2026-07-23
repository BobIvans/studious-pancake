from __future__ import annotations

import copy
from pathlib import Path

from scripts.verify_pr194_required_controls import (
    EXPECTED_BLOCKED_EXIT,
    REQUIRED_BLOCKED_COMMANDS,
    build_evidence,
    evaluate_manifest,
)
from src.production_surface import (
    blocked_command_contracts,
    load_manifest,
    required_control_modules,
    required_control_wheel_members,
    required_controls,
    required_entrypoints,
)

ROOT = Path(__file__).resolve().parents[1]


def _manifest_copy() -> dict[str, object]:
    return copy.deepcopy(load_manifest())


def test_pr194_required_control_manifest_accepts_current_checkout() -> None:
    evidence = build_evidence(root=ROOT)

    assert evidence["schema_version"] == "pr194.required-control-gate.v1"
    assert evidence["ready"] is True
    assert evidence["blockers"] == []
    assert "src.cli_pr189" in evidence["details"]["required_control_modules"]
    assert (
        "flashloan-bot paper-vertical check"
        in evidence["details"]["blocked_command_contracts"]
    )


def test_pr194_required_controls_cover_all_console_entrypoints() -> None:
    entrypoint_modules = {
        target.split(":", 1)[0] for target in required_entrypoints().values()
    }

    assert entrypoint_modules <= required_control_modules()
    assert {
        "src/cli_pr189.py",
        "src/automation_cli_pr189.py",
        "src/external_contracts/cli_pr189.py",
        "src/release_gate/materialized_evidence.py",
    } <= required_control_wheel_members()


def test_pr194_control_objects_are_stable_and_unique() -> None:
    controls = required_controls()

    assert len({control["id"] for control in controls}) == len(controls)
    assert all(control["id"].startswith("PR194_") for control in controls)
    assert all(control["category"] for control in controls)


def test_pr194_rejects_live_capability_weakening() -> None:
    manifest = _manifest_copy()
    manifest["runtime"]["live_trading_enabled"] = True  # type: ignore[index]

    evidence = evaluate_manifest(manifest, root=ROOT)

    assert evidence["ready"] is False
    assert "PR194_LIVE_CAPABILITY_ENABLED" in evidence["blockers"]


def test_pr194_rejects_entrypoint_without_required_control() -> None:
    manifest = _manifest_copy()
    manifest["required_controls"] = [  # type: ignore[index]
        control
        for control in manifest["required_controls"]  # type: ignore[index]
        if control["module"] != "src.cli_pr189"
    ]

    evidence = evaluate_manifest(manifest, root=ROOT)

    assert evidence["ready"] is False
    assert (
        "PR194_ENTRYPOINT_CONTROL_MISSING:flashloan-bot:src.cli_pr189"
        in evidence["blockers"]
    )


def test_pr194_rejects_control_not_required_in_wheel() -> None:
    manifest = _manifest_copy()
    manifest["required_wheel_members"] = [  # type: ignore[index]
        member
        for member in manifest["required_wheel_members"]  # type: ignore[index]
        if member != "src/automation_cli_pr189.py"
    ]

    evidence = evaluate_manifest(manifest, root=ROOT)

    assert evidence["ready"] is False
    assert "PR194_CONTROL_NOT_REQUIRED_IN_WHEEL:PR194_CHECKS_ENTRYPOINT" in evidence[
        "blockers"
    ]


def test_pr194_rejects_missing_nonzero_blocked_exit_contract() -> None:
    manifest = _manifest_copy()
    manifest["blocked_command_contracts"] = [  # type: ignore[index]
        contract
        for contract in manifest["blocked_command_contracts"]  # type: ignore[index]
        if contract["command"] != "flashloan-bot paper-vertical check"
    ]

    evidence = evaluate_manifest(manifest, root=ROOT)

    assert evidence["ready"] is False
    assert (
        "PR194_BLOCKED_EXIT_CONTRACT_MISSING:flashloan-bot paper-vertical check"
        in evidence["blockers"]
    )


def test_pr194_blocked_exit_contracts_are_strict() -> None:
    contracts = blocked_command_contracts()

    assert REQUIRED_BLOCKED_COMMANDS <= {contract["command"] for contract in contracts}
    assert all(
        contract["expected_exit"] == EXPECTED_BLOCKED_EXIT for contract in contracts
    )


def test_pr194_verify_repo_runs_required_control_gate() -> None:
    verify_repo = ROOT.joinpath("scripts", "verify_repo.py").read_text(
        encoding="utf-8"
    )

    assert "VERIFY_PR194_REQUIRED_CONTROLS_COMMAND" in verify_repo
    assert "scripts/verify_pr194_required_controls.py" in verify_repo
