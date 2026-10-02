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

from src import automation_cli_pr189
from src import fast_q_automation as fastq

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
    command_action = next(
        item
        for item in parser._actions
        if getattr(item, "dest", None) == "command"
    )
    for command in ("qualify-and-report", "automation-request"):
        if command not in command_action.choices:
            errors.append(f"OCC_REQUIRED_ROUTE_MISSING:{command}")

    explicit = fastq.validate_request(
        {
            "schema_version": fastq.REQUEST_SCHEMA,
            "request_id": "verify",
            "idempotency_key": "verify",
            "action": "qualify_and_report",
            "text": None,
            "inputs": {},
            "proposal": {
                "source": "laya",
                "action": "transcribe_local_audio",
            },
        }
    )
    if explicit["action"] != "qualify_and_report":
        errors.append("OCC_LAYA_CHANGED_EXPLICIT_ACTION")

    paper = json.loads(
        (CONFIG / "paper_campaign.plan.json").read_text(encoding="utf-8")
    )
    if paper.get("status") != "BLOCKED_NOT_STARTED":
        errors.append("OCC_PAPER_PLAN_NOT_BLOCKED")
    if paper.get("native_adapter_compatible") is not False:
        errors.append("OCC_PAPER_PLAN_MARKED_EXECUTABLE")
    try:
        fastq.validate_request(paper)
    except ValueError:
        pass
    else:
        errors.append("OCC_PAPER_PLAN_ADMITTED_AS_ACTION")

    voice = json.loads(
        (CONFIG / "voice_tools.responses.json").read_text(encoding="utf-8")
    )
    action_enum = set(
        voice[0]["parameters"]["properties"]["action"]["enum"]
    )
    forbidden = {
        "shell",
        "exec",
        "send_transaction",
        "send_bundle",
        "merge",
        "trade_live",
        "sign",
    }
    if forbidden.intersection(action_enum):
        errors.append("OCC_VOICE_TOOL_UNSAFE_ACTION")
    if not action_enum.issubset(set(fastq.ACTION_IDS)):
        errors.append("OCC_VOICE_ACTION_OUTSIDE_REVIEWED_REGISTRY")

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

    router_source = (ROOT / "src/fast_q_automation.py").read_text(
        encoding="utf-8"
    )
    if "shell=True" in router_source or "os.system(" in router_source:
        errors.append("OCC_ROUTER_ARBITRARY_SHELL_PRESENT")
    if {"sign", "send_transaction", "send_bundle", "trade_live"}.intersection(
        fastq.ACTION_IDS
    ):
        errors.append("OCC_ROUTER_UNSAFE_ACTION_REGISTERED")

    current = fastq._owner_for(
        "paper-shadow:blocked_missing_wallet_public_key"
    )
    if not current or current.get("patch_allowed") is not False:
        errors.append("OCC_CURRENT_BLOCKER_NOT_FAIL_CLOSED")

    return {
        "schema": "occ-automation.verification.v2",
        "ok": not errors,
        "errors": errors,
        "qualification_route": "flashloan-checks automation-request inspect",
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
