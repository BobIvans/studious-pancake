#!/usr/bin/env python3
"""Verify MPR-46 isolated signer/canary policy without enabling live execution."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mpr46_isolated_signer_canary import (  # noqa: E402
    default_policy_path,
    evaluate_mpr46_policy,
    load_json_policy,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--policy",
        default=str(default_policy_path(ROOT)),
        help="MPR-46 policy/evidence JSON to verify",
    )
    parser.add_argument(
        "--request",
        default=None,
        help="optional future sign-request JSON to evaluate offline",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--require-canary-eligible",
        action="store_true",
        help="fail unless the policy/request is fully canary eligible",
    )
    args = parser.parse_args(argv)

    evidence = load_json_policy(args.policy)
    request = load_json_policy(args.request) if args.request else None
    report = evaluate_mpr46_policy(evidence, request=request)
    payload = report.to_dict()

    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"state={payload['state']}")
        print(f"accepted={payload['accepted']}")
        print(f"permit_eligible={payload['permit_eligible']}")
        print(f"one_tx_canary_authorized={payload['one_tx_canary_authorized']}")
        print(f"live_enabled={payload['live_enabled']}")
        print(f"blockers={len(payload['blockers'])}")

    if payload["live_enabled"]:
        return 2
    if payload["unrestricted_live_available"]:
        return 3
    if payload["signature_material_returned"]:
        return 4
    if args.require_canary_eligible and not payload["accepted"]:
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
