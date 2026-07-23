#!/usr/bin/env python3
"""Validate NEW-MEGA-PR-04 hermetic release and 72-hour paper soak evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.paper_qualification_pr04 import evaluate_paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--soak-report", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--require-paper-ready", action="store_true")
    args = parser.parse_args(argv)

    report = evaluate_paths(args.manifest, args.soak_report)
    payload = report.to_dict()
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"accepted={payload['accepted']}")
        print(f"promotion_state={payload['promotion_state']}")
        print(f"paper_ready={payload['paper_ready']}")
        print(f"live_ready={payload['live_ready']}")
        for blocker in payload["blockers"]:
            print(f"BLOCKER: {blocker}")
    return 2 if args.require_paper_ready and not report.accepted else 0


if __name__ == "__main__":
    raise SystemExit(main())
