#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.mpr26_finalized_economic_truth import (  # noqa: E402
    MPR26State,
    evaluate_mpr26_evidence,
    sample_ready_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify MPR-26 finalized economic truth evidence"
    )
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = evaluate_mpr26_evidence(sample_ready_evidence())
    payload = {
        "schema_version": report.schema_version,
        "state": report.state.value,
        "accepted": report.state is MPR26State.READY_FOR_FOUNDATION,
        "blockers": [blocker.__dict__ for blocker in report.blockers],
        "evidence_hash": report.evidence_hash,
        "layers_present": list(report.layers_present),
        "realized_pnl_allowed": report.realized_pnl_allowed,
        "paper_pnl_estimated_only": report.paper_pnl_estimated_only,
        "live_execution_allowed": report.live_execution_allowed,
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2))
    else:
        print(f"MPR-26 finalized economic truth: {payload['state']}")
    if args.strict and not payload["accepted"]:
        return 1
    if payload["live_execution_allowed"] or payload["realized_pnl_allowed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
