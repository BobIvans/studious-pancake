#!/usr/bin/env python3
"""Verify the MPR-42 exact economic settlement authority boundary."""

from __future__ import annotations

import argparse
import json
import sys

from src.mpr42_exact_economic_settlement_authority import (
    MPR42State,
    evaluate_mpr42_evidence,
    reject_non_finite_number,
    sample_ready_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable report")
    parser.add_argument("--strict", action="store_true", help="fail if the boundary is not ready")
    args = parser.parse_args()

    report = evaluate_mpr42_evidence(sample_ready_evidence())
    strict_integer_checks = _run_strict_integer_ingress_checks()
    payload = {
        "schema_version": report.schema_version,
        "state": report.state.value,
        "message_hash": report.message_hash,
        "layers_present": list(report.layers_present),
        "blockers": [blocker.__dict__ for blocker in report.blockers],
        "live_execution_allowed": report.live_execution_allowed,
        "realized_settlement_allowed": report.realized_settlement_allowed,
        "capital_reuse_allowed": report.capital_reuse_allowed,
        "strict_integer_checks": strict_integer_checks,
    }

    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2))
    else:
        print(f"MPR-42 state: {report.state.value}")
        for blocker in report.blockers:
            print(f"- {blocker.code}: {blocker.message}")

    if args.strict:
        if report.state is not MPR42State.READY_FOR_FOUNDATION:
            return 1
        if report.live_execution_allowed:
            return 2
        if not report.capital_reuse_allowed:
            return 3
        if not strict_integer_checks:
            return 4
    return 0


def _run_strict_integer_ingress_checks() -> bool:
    rejected = 0
    for bad_value in (1.1, float("nan"), float("inf"), True, "100"):
        try:
            reject_non_finite_number(bad_value, "economic_value")
        except ValueError:
            rejected += 1
    return rejected == 5


if __name__ == "__main__":
    sys.exit(main())
