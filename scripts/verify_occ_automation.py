#!/usr/bin/env python3
"""Verify the isolated OCC/Laya tooling boundary."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "occ_automation"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

import qualification_adapter as qa
from src import automation_cli_pr189

CONFIG = TOOL / "config"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            values.add(node.module.split(".", 1)[0])
    return values


def verify() -> dict[str, object]:
    errors: list[str] = []

    parser = automation_cli_pr189._parser()
    action = next(
        item
        for item in parser._actions
        if getattr(item, "dest", None) == "command"
    )
    if "qualify-and-report" not in action.choices:
        errors.append("OCC_CURRENT_QUALIFICATION_ROUTE_MISSING")

    request = qa.validate_action_request(
        {
            "schema_version": qa.ACTION_SCHEMA,
            "request_id": "verify",
            "action": "qualification_audit",
            "goal": "inspect only",
            "source_refs": [],
            "repeat": "once",
            "duration_hours": None,
        }
    )
    routed = qa.route_request(
        request,
        laya_proposal="pause_jobs",
        laya_confidence=1.0,
    )
    if routed.selected_action != "qualification_audit":
        errors.append("OCC_LAYA_CHANGED_EXPLICIT_ACTION")
    if routed.permissions_granted_by_laya:
        errors.append("OCC_LAYA_GRANTED_PERMISSION")

    paper = json.loads(
        (CONFIG / "paper_campaign.plan.json").read_text(encoding="utf-8")
    )
    try:
        qa.assert_paper_plan_not_executable(paper)
    except qa.AdapterError as exc:
        if str(exc) != "PAPER_PLAN_DESIGN_ONLY_DO_NOT_EXECUTE":
            errors.append("OCC_PAPER_PLAN_WRONG_BLOCKER")
    else:
        errors.append("OCC_PAPER_PLAN_EXECUTABLE")

    voice = json.loads(
        (CONFIG / "voice_tools.responses.json").read_text(encoding="utf-8")
    )
    action_enum = voice[0]["parameters"]["properties"]["action"]["enum"]
    forbidden = {"shell", "exec", "send_transaction", "send_bundle", "merge"}
    if forbidden.intersection(action_enum):
        errors.append("OCC_VOICE_TOOL_UNSAFE_ACTION")

    orchestration = json.loads(
        (CONFIG / "occ_orchestration.plan.json").read_text(encoding="utf-8")
    )
    permissions = orchestration["permissions"]
    for key in (
        "arbitrary_shell",
        "automatic_installation",
        "automatic_push",
        "automatic_merge",
        "signing",
        "transactions",
        "wallet_credentials",
        "automatic_capital_increase",
        "modify_capability_or_release_gates",
    ):
        if permissions.get(key) is not False:
            errors.append(f"OCC_UNSAFE_PERMISSION:{key}")
    budget = orchestration["budget"]
    if budget.get("paid_api_enabled") is not False:
        errors.append("OCC_PAID_API_DEFAULT_ENABLED")

    baseline = json.loads(
        (ROOT / "release_artifacts/fast_q1_v3/BASELINE.json").read_text(
            encoding="utf-8"
        )
    )
    if baseline.get("selected_goal") != "FAST-Q1":
        errors.append("OCC_FAST_Q_BASELINE_DRIFT")
    if baseline.get("integration_goal") != "MEGA FAST-Q deterministic automation":
        errors.append("OCC_INTEGRATION_GOAL_MISSING")

    occ_imports = _imports(TOOL / "occ_local.py")
    if {"socket", "requests", "httpx", "aiohttp", "urllib"}.intersection(occ_imports):
        errors.append("OCC_LOCAL_NETWORK_IMPORT_PRESENT")

    adapter_source = (TOOL / "qualification_adapter.py").read_text(
        encoding="utf-8"
    )
    if "shell=True" in adapter_source:
        errors.append("OCC_ADAPTER_SHELL_EXECUTION_PRESENT")
    if "send_raw_transaction" in adapter_source or "sign_and_send" in adapter_source:
        errors.append("OCC_ADAPTER_TRANSACTION_EXECUTION_PRESENT")

    return {
        "schema": "occ-automation.verification.v1",
        "ok": not errors,
        "errors": errors,
        "qualification_route": "flashloan-checks qualify-and-report inspect",
        "laya_authority": False,
        "paper_campaign_executable": False,
        "asr_optional": True,
        "paid_api_enabled": False,
        "arbitrary_shell": False,
        "signer": False,
        "sender": False,
        "live_authorized": False,
        "transactions_sent": 0,
    }


def main() -> int:
    result = verify()
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
