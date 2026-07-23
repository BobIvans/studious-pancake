#!/usr/bin/env python3
"""Verify SUPER-MPR-B durable-economic evidence artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.economic_authority_super_mpr_b import evaluate_super_mpr_b_evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--evidence",
        default="release_artifacts/super_mpr_b_evidence.json",
        help="relative SUPER-MPR-B evidence bundle path",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = evaluate_super_mpr_b_evidence(args.root, evidence_path=args.evidence)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"super_mpr_b_evidence_accepted={report['accepted']}")
        for blocker in report["blockers"]:
            print(f"BLOCKER: {blocker}")
    return 0 if report["accepted"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
