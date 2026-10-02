#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import automation_cli_pr189
from src import qualification_report as q


def verify() -> dict[str, object]:
    errors: list[str] = []
    if q.ACTION_ID != "qualify_and_report":
        errors.append("FAST_Q1_ACTION_ID_DRIFT")
    if q.PROFILE != "offline_sender_free":
        errors.append("FAST_Q1_PROFILE_DRIFT")
    if [row[0] for row in q.PREFLIGHT_STEPS] != [
        "status",
        "capabilities",
        "doctor",
        "admission",
    ]:
        errors.append("FAST_Q1_PREFLIGHT_ORDER_DRIFT")
    if q.PAPER_STEP[0] != "paper-shadow":
        errors.append("FAST_Q1_PAPER_STEP_MISSING")

    parser = automation_cli_pr189._parser()
    command_action = next(
        action
        for action in parser._actions
        if getattr(action, "dest", None) == "command"
    )
    if "qualify-and-report" not in command_action.choices:
        errors.append("FAST_Q1_CLI_ROUTE_MISSING")

    env = q._environment(
        {
            "PATH": "/bin",
            "OPENAI_API_KEY": "secret",
            "FLASHLOAN_PRIVATE_KEY": "secret",
            "HTTPS_PROXY": "http://example.invalid",
        }
    )
    if "OPENAI_API_KEY" in env or "FLASHLOAN_PRIVATE_KEY" in env:
        errors.append("FAST_Q1_SECRET_ENV_LEAK")
    if "HTTPS_PROXY" in env:
        errors.append("FAST_Q1_PROXY_ENV_LEAK")
    if env.get("LIVE_TRADING_ENABLED") != "false":
        errors.append("FAST_Q1_LIVE_NOT_DENIED")
    if env.get("FLASHLOAN_JUPITER_ENABLED") != "false":
        errors.append("FAST_Q1_PROVIDER_NETWORK_NOT_DEFAULT_OFF")

    source = (ROOT / "src/qualification_report.py").read_text(encoding="utf-8")
    if "shell=True" in source:
        errors.append("FAST_Q1_SHELL_EXECUTION_PRESENT")

    baseline = json.loads(
        (ROOT / "release_artifacts/fast_q1_v3/BASELINE.json").read_text(
            encoding="utf-8"
        )
    )
    matrix = json.loads(
        (
            ROOT / "release_artifacts/fast_q1_v3/REQUIREMENT_EVIDENCE_MATRIX.json"
        ).read_text(encoding="utf-8")
    )
    if baseline.get("selected_goal") != "FAST-Q1":
        errors.append("FAST_Q1_BASELINE_GOAL_MISMATCH")
    if baseline.get("disposition") != "EXTEND_EXISTING":
        errors.append("FAST_Q1_REUSE_DECISION_DRIFT")
    if not any(
        row.get("requirement") == "one paper-shadow pass only after preflight"
        and row.get("status") == "IMPLEMENTED"
        for row in matrix.get("rows", [])
    ):
        errors.append("FAST_Q1_PAPER_PASS_NOT_MAPPED")

    return {
        "schema": "fast-q1-v3.verification.v1",
        "ok": not errors,
        "errors": errors,
        "action_id": q.ACTION_ID,
        "profile": q.PROFILE,
        "preflight_count": len(q.PREFLIGHT_STEPS),
        "paper_pass_maximum": 1,
        "qualified": False,
        "live_authorized": False,
        "shell_allowed": False,
        "auto_merge": False,
    }


def main() -> int:
    result = verify()
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
