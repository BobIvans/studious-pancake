#!/usr/bin/env python3
"""Fail-closed scaffold for MPR-34 transport materialization checks.

This verifier intentionally blocks promotion until rooted transport evidence is
implemented with materialized receipts.
"""
from __future__ import annotations

import argparse
import json
from typing import Final

SCHEMA_VERSION: Final = "mpr34.transport-materialization.v0"
BLOCKERS: Final = [
    "ABSOLUTE_DEADLINE_NOT_IMPLEMENTED",
    "BOUNDED_RESPONSE_PARSER_NOT_IMPLEMENTED",
    "DUPLICATE_KEY_REJECTION_NOT_IMPLEMENTED",
    "PEER_IP_TLS_BINDING_NOT_IMPLEMENTED",
    "PRIVATE_IP_REBIND_BLOCKING_NOT_IMPLEMENTED",
]


def build_report() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "accepted": False,
        "promotion_ready": False,
        "materialized": False,
        "blockers": BLOCKERS,
        "notes": [
            "MPR-34 requires rooted transport evidence from authority-owned collection code.",
            "Synthetic booleans, hashes and placeholder observations must not satisfy this verifier.",
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
        print("MPR-34 transport materialization is not implemented; fail closed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
