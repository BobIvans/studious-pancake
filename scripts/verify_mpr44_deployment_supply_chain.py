#!/usr/bin/env python3
"""Verify MPR-44 deployment, secret, egress and supply-chain evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.deployment_supply_chain_mpr44 import evaluate_manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default="src/resources/deployment_supply_chain_mpr44.example.json",
        help="MPR-44 deployment evidence manifest path",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="return non-zero until all MPR-44 blockers are closed",
    )
    args = parser.parse_args(argv)

    report = evaluate_manifest_path(args.manifest)
    payload = report.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        status = "ACCEPTED" if report.accepted else "BLOCKED"
        print(
            "MPR44_DEPLOYMENT_SUPPLY_CHAIN: "
            f"status={status} paper_release_ready={report.paper_release_ready} "
            f"live_ready={report.live_ready} blockers={len(report.blockers)}"
        )
        for blocker in report.blockers:
            print(f"- {blocker}")
    return 2 if args.require_clean and not report.accepted else 0


if __name__ == "__main__":
    raise SystemExit(main())
