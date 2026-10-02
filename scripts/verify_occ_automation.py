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


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            values.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            values.add(node.module.split(".", 1)[0])
    return values


def verify() -> dict[str, object]:
    errors: list[str] = []

    parser = automation_cli_pr189._parser()
    command_action = next(
        item for item in parser._actions if getattr(item, "dest", None) == "command"
    )
    if "qualify-and-report" not in command_action.choices:
        errors.append("OCC_CURRENT_QUALIFICATION_ROUTE_MISSING")

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
    if paper.get("schema_version") != "occ-paper-campaign-proposal.v1":
        errors.append("OCC_PAPER_PLAN_SCHEMA_DRIFT")
    if paper.get("native_adapter_compatible") is not False:
        errors.append("OCC_PAPER_PLAN_MARKED_EXECUTABLE")
    if paper.get("market_campaign_executed") is not False:
        errors.append("OCC_PAPER_CAMPAIGN_FALSE_CLAIM")
    try:
        fastq.validate_request(paper)
    except ValueError:
        pass
    else:
        errors.append("OCC_PAPER_PLAN_ACCEPTED_AS_ACTION")

    voice = json.loads(
        (CONFIG / "voice_tools.responses.json").read_text(encoding="utf-8")
    )
    action_enum = set(voice[0]["parameters"]["properties"]["action"]["enum"])
    if action_enum != set(fastq.ACTION_IDS):
        errors.append("OCC_VOICE_REGISTRY_DRIFT")
    forbidden = {
        "shell",
        "exec",
        "send_transaction",
        "send_bundle",
        "merge",
        "trade_live",
    }
    if forbidden.intersection(action_enum):
        errors.append("OCC_VOICE_TOOL_UNSAFE_ACTION")

    laya = json.loads(
        (CONFIG / "laya_request.example.json").read_text(encoding="utf-8")
    )
    laya_actions = set(laya["questions"]["proposed_route"]["criteria"])
    if not set(fastq.ACTION_IDS).issubset(laya_actions):
        errors.append("OCC_LAYA_REGISTRY_INCOMPLETE")

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
    if orchestration["budget"].get("paid_api_enabled") is not False:
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
    if {
        "socket",
        "requests",
        "httpx",
        "aiohttp",
        "urllib",
        "subprocess",
    }.intersection(occ_imports):
        errors.append("OCC_LOCAL_EFFECT_IMPORT_PRESENT")

    asr_top = _top_level_imports(TOOL / "asr_cpu_experiment.py")
    if "faster_whisper" in asr_top:
        errors.append("OCC_ASR_HEAVY_IMPORT_AT_MODULE_LOAD")

    fastq_source = (ROOT / "src/fast_q_automation.py").read_text(encoding="utf-8")
    if "shell=True" in fastq_source or "os.system(" in fastq_source:
        errors.append("OCC_FAST_Q_ARBITRARY_SHELL_PRESENT")
    if "send_raw_transaction" in fastq_source or "sign_and_send" in fastq_source:
        errors.append("OCC_FAST_Q_TRANSACTION_EXECUTION_PRESENT")

    current = fastq._owner_for("paper-shadow:blocked_missing_wallet_public_key")
    if not current or current.get("patch_allowed") is not False:
        errors.append("OCC_CURRENT_BLOCKER_NOT_FAIL_CLOSED")

    return {
        "schema": "occ-automation.verification.v2",
        "ok": not errors,
        "errors": errors,
        "router_owner": "src.fast_q_automation",
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
