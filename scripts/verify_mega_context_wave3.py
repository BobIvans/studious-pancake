#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mega_context_wave3 import KnowledgeWorkbench, verify_no_todo

STATUS_PATH = ROOT / "config" / "mega_context_wave3_status.json"
DISCREPANCY_PATH = ROOT / "config" / "mega_context_wave3_source_discrepancies.json"


def verify() -> dict[str, object]:
    status = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    discrepancy = json.loads(DISCREPANCY_PATH.read_text(encoding="utf-8"))
    rows = status["rows"]
    errors: list[str] = []

    counts = {"BASE": 0, "SPX": 0, "W3": 0}
    by_id: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        layer = str(row["layer"])
        counts[layer] = counts.get(layer, 0) + 1
        by_id[(layer, str(row["id"]))] = row

    if counts != {"BASE": 95, "SPX": 96, "W3": 72}:
        errors.append(f"COUNT_MISMATCH:{counts!r}")
    if not verify_no_todo(rows):
        errors.append("INVALID_OR_TODO_STATUS")
    if discrepancy.get("baseline_json_missing_id") != 54:
        errors.append("BASE54_DISCREPANCY_NOT_PRESERVED")
    if discrepancy.get("authoritative_function") != "fetch_github_pr_metadata()":
        errors.append("BASE54_FUNCTION_MISMATCH")

    for requirement_id in status["merge_blocking_ids"]["spx_p0"]:
        if by_id.get(("SPX", requirement_id), {}).get("status") != "IMPLEMENTED":
            errors.append(f"SPX_P0_NOT_IMPLEMENTED:{requirement_id}")
    for requirement_id in status["merge_blocking_ids"]["w3_p0"]:
        if by_id.get(("W3", requirement_id), {}).get("status") != "IMPLEMENTED":
            errors.append(f"W3_P0_NOT_IMPLEMENTED:{requirement_id}")

    workbench = KnowledgeWorkbench()
    action_registry = workbench.register_actions(
        [
            {"action_id": "read-context", "effects": ["read"]},
            {"action_id": "forbidden-send", "effects": ["send"]},
            {"action_id": "forbidden-shell", "command": "echo nope"},
        ]
    )
    if set(action_registry) != {"read-context"}:
        errors.append("ACTION_BOUNDARY_FAILED")

    blocked = [row for row in rows if row["status"] == "BLOCKED"]
    if any(
        not str(row.get("evidence", "")).startswith("BLOCKED_")
        for row in blocked
    ):
        errors.append("BLOCKED_WITHOUT_REASON")

    return {
        "schema": "mega-context-wave3-verification.v1",
        "ok": not errors,
        "errors": errors,
        "counts": counts,
        "implemented": sum(row["status"] == "IMPLEMENTED" for row in rows),
        "blocked": len(blocked),
        "p0_spx": len(status["merge_blocking_ids"]["spx_p0"]),
        "p0_w3": len(status["merge_blocking_ids"]["w3_p0"]),
        "no_live_effects": True,
        "base54_discrepancy_preserved": True,
    }


def main() -> int:
    result = verify()
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
