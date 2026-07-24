#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.mpr_next_06_shadow_soak_final_promotion import (  # noqa: E402
    evaluate_mpr_next_06,
    sample_review_ready_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify MPR-NEXT-06 shadow soak final promotion evidence"
    )
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = evaluate_mpr_next_06(sample_review_ready_evidence())
    payload = report.to_dict()
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2))
    else:
        print(f"MPR-NEXT-06 shadow soak final promotion: {payload['state']}")
    if payload["unrestricted_live_allowed"] or payload["production_ready_claimed"]:
        return 1
    if args.strict and not payload["accepted"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
