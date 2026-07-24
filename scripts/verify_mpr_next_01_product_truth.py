#!/usr/bin/env python3
"""Run the MPR-NEXT-01 product truth and release hygiene gate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mpr_next_01_product_truth_gate import evaluate_mpr_next_01


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = evaluate_mpr_next_01(args.root)
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif result.accepted:
        print("MPR-NEXT-01 product truth verification passed")
    else:
        print("MPR-NEXT-01 product truth verification failed", file=sys.stderr)
        for blocker in result.blockers:
            print(f"- {blocker}", file=sys.stderr)
    return 0 if result.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
