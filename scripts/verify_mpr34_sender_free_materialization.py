#!/usr/bin/env python3
"""Fail-closed scaffold for MPR-34 sender-free message/simulation materialization.

This verifier blocks until exact message bytes, simulation request/response,
returned accounts and decoder-owned economics are materialized and recomputed
internally.
"""
from __future__ import annotations

import argparse
import json
from typing import Final

SCHEMA_VERSION: Final = "mpr34.sender-free-materialization.v0"
BLOCKERS: Final = [
    "PR222_MESSAGE_BYTES_NOT_MATERIALIZED",
    "SIMULATION_ARTIFACTS_NOT_MATERIALIZED",
    "RETURNED_ACCOUNTS_NOT_MATERIALIZED",
    "PROGRAM_IDS_NOT_VALIDATED_AGAINST_CHAIN_REGISTRY",
    "ECONOMICS_NOT_DECODER_OWNED",
]


def build_report() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "accepted": False,
        "promotion_ready": False,
        "materialized": False,
        "blockers": BLOCKERS,
        "notes": [
            "MPR-34 requires exact VersionedMessage and simulation artifacts, not only digest declarations.",
            "Economics must be rebuilt by decoder/accounting authority from materialized bytes and accounts.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print JSON report")
    args = parser.parse_args(argv)

    report = build_report()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("MPR-34 sender-free materialization is not implemented; fail closed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
