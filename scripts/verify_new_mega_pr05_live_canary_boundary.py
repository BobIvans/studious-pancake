#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.new_mega_pr05_live_canary_boundary import (  # noqa: E402
    BoundaryState,
    sample_ready_flow,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify NEW-MEGA-PR-05 isolated signer and bounded canary boundary"
    )
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = sample_ready_flow()
    accepted = (
        payload["permit_state"] == BoundaryState.READY_FOR_BOUNDED_CANARY_REVIEW.value
        and payload["reconciliation_state"] == BoundaryState.READY_FOR_BOUNDED_CANARY_REVIEW.value
        and payload["canary_state"] == BoundaryState.READY_FOR_BOUNDED_CANARY_REVIEW.value
        and payload["finalized_settlement"] is True
        and payload["manual_review_required"] is False
        and payload["unrestricted_live_allowed"] is False
        and not payload["permit_blockers"]
        and not payload["submission_blockers"]
        and not payload["reconciliation_blockers"]
        and not payload["canary_blockers"]
    )
    payload["accepted"] = accepted
    payload["live_scope"] = "bounded_canary_only"
    payload["unrestricted_live_decision"] = "forbidden_until_separate_governance"

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"NEW-MEGA-PR-05 live canary boundary accepted={accepted}")

    if args.strict and not accepted:
        return 1
    if payload["unrestricted_live_allowed"] is not False:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
