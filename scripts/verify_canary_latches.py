#!/usr/bin/env python3
"""Verify MPR-CLOSE-05 bounded canary latches."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mpr_close_05_isolated_signer_jito_canary import (  # noqa: E402
    evaluate_mpr_close_05_evidence,
    sample_ready_evidence,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    evidence = sample_ready_evidence(canary_requested=True)
    report = evaluate_mpr_close_05_evidence(evidence)
    unsafe = replace(
        evidence,
        canary=replace(
            evidence.canary,
            live_canary_available_by_default=True,
            unrestricted_live_available=True,
            independent_approval_hashes=("a" * 64,),
        ),
    )
    unsafe_report = evaluate_mpr_close_05_evidence(unsafe)
    unsafe_codes = {blocker.code for blocker in unsafe_report.blockers}
    payload = {
        "schema_version": report.schema_version,
        "state": report.state.value,
        "blockers": [blocker.__dict__ for blocker in report.blockers],
        "bounded_canary_default_off": report.bounded_canary_default_off,
        "bounded_canary_review_ready": report.bounded_canary_review_ready,
        "unrestricted_live_available": report.unrestricted_live_available,
        "unsafe_default_on_blocked": "CANARY_DEFAULT_ON_FORBIDDEN" in unsafe_codes,
        "unsafe_unrestricted_live_blocked": "CANARY_UNRESTRICTED_LIVE_FORBIDDEN" in unsafe_codes,
        "second_approval_required": "CANARY_SECOND_APPROVAL_MISSING" in unsafe_codes,
        "evidence_hash": report.evidence_hash,
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2))
    else:
        print(f"MPR-CLOSE-05 canary latches: {payload['state']}")
    if args.strict and (
        report.blockers
        or not report.bounded_canary_default_off
        or not payload["unsafe_default_on_blocked"]
        or not payload["unsafe_unrestricted_live_blocked"]
        or not payload["second_approval_required"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
