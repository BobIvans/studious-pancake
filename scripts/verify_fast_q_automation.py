#!/usr/bin/env python3
"""Contract verifier for the deterministic FAST-Q action loop."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import fast_q_automation as a


def main() -> int:
    errors: list[str] = []
    registry = json.loads(
        (ROOT / "config/fast_q_actions.json").read_text(encoding="utf-8")
    )
    configured = {item["id"] for item in registry["actions"]}
    if configured != set(a.ACTION_IDS):
        errors.append("ACTION_REGISTRY_DRIFT")
    if set(a.ACTION_REGISTRY) != set(a.ACTION_IDS):
        errors.append("CODE_REGISTRY_DRIFT")
    forbidden = {"live", "trade_live", "sign", "send", "shell", "execute_shell"}
    if set(a.ACTION_IDS) & forbidden:
        errors.append("FORBIDDEN_ACTION_REGISTERED")
    if set(a.FIXED_VALIDATIONS) != {"fast_q_automation", "fast_q1_v3"}:
        errors.append("VALIDATION_SET_DRIFT")
    source = (ROOT / "src/fast_q_automation.py").read_text(encoding="utf-8")
    if "shell=True" in source or "os.system(" in source:
        errors.append("ARBITRARY_SHELL_PRESENT")
    current = a._owner_for("paper-shadow:blocked_missing_wallet_public_key")
    if not current or current.get("patch_allowed") is not False:
        errors.append("CURRENT_BLOCKER_FAIL_CLOSED_RULE_MISSING")
    if current and current.get("owner_files") != [
        "src/runtime_discovery_coordinator.py"
    ]:
        errors.append("CURRENT_BLOCKER_OWNER_DRIFT")
    if any(not a.ACTION_REGISTRY[item]["external_only"] for item in a.EXTERNAL_ACTIONS):
        errors.append("EXTERNAL_BOUNDARY_BROKEN")
    payload = {
        "schema": "fast-q-automation.verification.v1",
        "ok": not errors,
        "errors": errors,
        "action_count": len(a.ACTION_IDS),
        "external_action_count": len(a.EXTERNAL_ACTIONS),
        "live_authorized": False,
        "transactions_sent": 0,
        "paid_api_fallback": False,
        "shell_allowed": False,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
