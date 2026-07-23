#!/usr/bin/env python3
"""Verify MPR-CLOSE-05 Jito settlement semantics."""

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

    report = evaluate_mpr_close_05_evidence(sample_ready_evidence(canary_requested=False))
    unsafe_evidence = sample_ready_evidence(canary_requested=False)
    unsafe_report = evaluate_mpr_close_05_evidence(
        replace(
            unsafe_evidence,
            jito=replace(
                unsafe_evidence.jito,
                ack_not_settlement=False,
                bundle_id_not_settlement=False,
                finalized_onchain_reconciliation=False,
            ),
        )
    )
    unsafe_codes = {blocker.code for blocker in unsafe_report.blockers}
    payload = {
        "schema_version": report.schema_version,
        "state": report.state.value,
        "blockers": [blocker.__dict__ for blocker in report.blockers],
        "ack_is_terminal": False,
        "bundle_id_is_terminal": False,
        "unsafe_fixture_blocked": "JITO_SEMANTICS_INCOMPLETE" in unsafe_codes,
        "unrestricted_live_available": report.unrestricted_live_available,
        "evidence_hash": report.evidence_hash,
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2))
    else:
        print(f"MPR-CLOSE-05 Jito semantics: {payload['state']}")
    if args.strict and (report.blockers or not payload["unsafe_fixture_blocked"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
