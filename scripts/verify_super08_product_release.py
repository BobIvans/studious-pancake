#!/usr/bin/env python3
"""SUPER-08 structural verifier for PRODUCT-01 + RELEASE-01 closure.

This is an audit projection over existing AGG-14 product owners and the canonical
AGG-15 release-handoff owner. It is not a release, signing, submission, treasury,
or remote-resource authority.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.release_gate.agg15_release_handoff import (
    AGG15_SCHEMA_VERSION,
    EXPECTED_NF_COUNT,
    EXPECTED_NF_IDS,
    EXTENSION_NF_OWNERS,
    EXTENSION_SOURCE_PRS,
)
from src.research.product import RevenueAttributionLedger

ROOT = Path(__file__).resolve().parents[1]
AGG14_COVERAGE = ROOT / "config" / "agg14_research_coverage.json"

_EXPECTED_PRODUCT_NF = tuple(f"NF-{index:03d}" for index in range(318, 323))
_EXPECTED_EXTENSION_GROUPS = {
    "PR-073": ("NF-329", "NF-330", "NF-331", "NF-332"),
    "PR-074": ("NF-333", "NF-334", "NF-335", "NF-336"),
    "PR-075": ("NF-337", "NF-338", "NF-339", "NF-340"),
    "PR-076": ("NF-341", "NF-342", "NF-343", "NF-344"),
    "PR-077": ("NF-345", "NF-346", "NF-347", "NF-348"),
    "PR-078": ("NF-349", "NF-350", "NF-351", "NF-352"),
}


def verify_super08() -> dict[str, Any]:
    blockers: list[str] = []

    if AGG15_SCHEMA_VERSION != "agg15.release-handoff.v2":
        blockers.append("SUPER08_RELEASE_SCHEMA_NOT_V2")
    if EXPECTED_NF_COUNT != 352 or len(EXPECTED_NF_IDS) != 352:
        blockers.append("SUPER08_FULL_TARGET_NOT_352")

    expected_extension_ids = {
        nf_id for ids in _EXPECTED_EXTENSION_GROUPS.values() for nf_id in ids
    }
    if set(EXTENSION_NF_OWNERS) != expected_extension_ids:
        blockers.append("SUPER08_EXTENSION_OWNER_SET_MISMATCH")
    if set(EXTENSION_SOURCE_PRS) != expected_extension_ids:
        blockers.append("SUPER08_EXTENSION_SOURCE_SET_MISMATCH")
    for source_pr, ids in _EXPECTED_EXTENSION_GROUPS.items():
        if any(EXTENSION_SOURCE_PRS.get(nf_id) != source_pr for nf_id in ids):
            blockers.append("SUPER08_EXTENSION_SOURCE_PR_MISMATCH")
            break

    raw = json.loads(AGG14_COVERAGE.read_text(encoding="utf-8"))
    product_rows = {
        str(row.get("id")): row
        for row in raw.get("nf", ())
        if isinstance(row, dict) and str(row.get("id")) in _EXPECTED_PRODUCT_NF
    }
    if tuple(sorted(product_rows)) != _EXPECTED_PRODUCT_NF:
        blockers.append("SUPER08_PRODUCT_NF_COVERAGE_MISSING")
    elif any(row.get("owner") != "PRODUCT-01" for row in product_rows.values()):
        blockers.append("SUPER08_PRODUCT_PRIMARY_OWNER_MISMATCH")
    allowed_product_statuses = {"IMPLEMENTED_OFFLINE", "MERGED_CODE"}
    if product_rows and any(
        row.get("implementation_status") not in allowed_product_statuses
        for row in product_rows.values()
    ):
        blockers.append("SUPER08_PRODUCT_IMPLEMENTATION_INCOMPLETE")

    if raw.get("live_enabled") is not False:
        blockers.append("SUPER08_AGG14_LIVE_DEFAULT_NOT_FALSE")
    if raw.get("signing_enabled") is not False:
        blockers.append("SUPER08_AGG14_SIGNING_DEFAULT_NOT_FALSE")
    if raw.get("submission_enabled") is not False:
        blockers.append("SUPER08_AGG14_SUBMISSION_DEFAULT_NOT_FALSE")
    if raw.get("production_ready") is not False:
        blockers.append("SUPER08_AGG14_PRODUCTION_READY_MUST_REMAIN_FALSE")

    ledger_projection = RevenueAttributionLedger().export()
    if ledger_projection.get("trading_capital_authority") is not False:
        blockers.append("SUPER08_PRODUCT_LEDGER_BECAME_CAPITAL_AUTHORITY")

    return {
        "schema": "super08.product-release-closure.v1",
        "ok": not blockers,
        "blockers": sorted(set(blockers)),
        "release_handoff_schema": AGG15_SCHEMA_VERSION,
        "expected_nf_count": EXPECTED_NF_COUNT,
        "product_nf_ids": list(_EXPECTED_PRODUCT_NF),
        "extension_nf_count": len(expected_extension_ids),
        "extension_source_prs": {
            source_pr: list(ids)
            for source_pr, ids in sorted(_EXPECTED_EXTENSION_GROUPS.items())
        },
        "product_accounting_is_trading_capital_authority": bool(
            ledger_projection.get("trading_capital_authority")
        ),
        "unsafe_effects_enabled": False,
        "operational_qualification_claimed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = verify_super08()
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print("SUPER-08:", "PASS" if report["ok"] else "BLOCKED")
        for blocker in report["blockers"]:
            print("-", blocker)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
