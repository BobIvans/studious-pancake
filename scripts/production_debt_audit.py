#!/usr/bin/env python3
"""Print or enforce the aggregate production-debt report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.production_debt import evaluate_production_debt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail only when the inventory is malformed or inconsistent",
    )
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="fail unless the repository has no paper/live production blockers",
    )
    args = parser.parse_args()

    report = evaluate_production_debt()
    payload = report.to_dict()
    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"production_ready={report.production_ready}")
        print(f"paper_ready={report.paper_ready}")
        print(f"live_ready={report.live_ready}")
        print(f"blockers={len(report.blockers)}")
        for batch in report.batches:
            print(
                f"{batch['id']}: open={batch['open_items']} p0={batch['p0_items']}"
            )
        for error in report.consistency_errors:
            print(f"CONSISTENCY_ERROR: {error}")

    if report.consistency_errors:
        return 2
    if args.require_ready and not report.production_ready:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
