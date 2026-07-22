#!/usr/bin/env python3
"""Print or enforce production debt with PR-189 explicit command modes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.automation_cli_pr189 import main as automation_main
from src.production_debt import evaluate_production_debt


def _legacy_main(*, as_json: bool, require_ready: bool) -> int:
    """Preserve the pre-PR-189 script payload and human-readable output."""

    report = evaluate_production_debt()
    payload = report.to_dict()
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"production_ready={report.production_ready}")
        print(f"paper_ready={report.paper_ready}")
        print(f"live_ready={report.live_ready}")
        print(f"blockers={len(report.blockers)}")
        for batch in report.batches:
            print(f"{batch['id']}: open={batch['open_items']} p0={batch['p0_items']}")
        for error in report.consistency_errors:
            print(f"CONSISTENCY_ERROR: {error}")

    if report.consistency_errors:
        return 2
    if require_ready and not report.production_ready:
        return 3
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", choices=("inspect", "check"))
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--check",
        action="store_true",
        dest="legacy_inventory_check",
        help="legacy consistency check; preserves the debt-report payload",
    )
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="legacy readiness enforcement; preserves the historical output",
    )
    args = parser.parse_args(argv)

    if args.mode is None:
        return _legacy_main(
            as_json=args.as_json,
            require_ready=args.require_ready,
        )
    if args.require_ready and args.mode != "check":
        parser.error("--require-ready conflicts with explicit inspect mode")
    if args.legacy_inventory_check:
        parser.error("--check is a legacy flag; use the explicit check mode")
    return automation_main(["production-debt", args.mode])


if __name__ == "__main__":
    raise SystemExit(main())
