#!/usr/bin/env python3
"""Verify structural MEGA8-04 closure without claiming operational qualification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import mega8_04

COVERAGE = ROOT / "config" / "mega8_04_coverage.json"
EXPECTED_NF = {f"NF-{number:03d}" for number in range(585, 641)}
EXPECTED_CHILDREN = {f"PR-{number}" for number in range(209, 223)}


def verify() -> dict[str, object]:
    errors: list[str] = []
    data = json.loads(COVERAGE.read_text(encoding="utf-8"))

    if data.get("mega_id") != "MEGA8-04":
        errors.append("MEGA804_ID_MISMATCH")
    if data.get("child_count") != 14:
        errors.append("MEGA804_CHILD_COUNT_MISMATCH")
    if data.get("nf_count") != 56:
        errors.append("MEGA804_NF_COUNT_MISMATCH")
    if set(mega8_04.NF_SYMBOLS) != EXPECTED_NF:
        errors.append("MEGA804_NF_REGISTRY_MISMATCH")

    children = data.get("children")
    if not isinstance(children, list):
        errors.append("MEGA804_CHILDREN_MISSING")
        children = []

    child_ids = {item.get("roadmap_pr") for item in children if isinstance(item, dict)}
    if child_ids != EXPECTED_CHILDREN:
        errors.append("MEGA804_CHILD_SET_MISMATCH")

    owned_nf: list[str] = []
    for item in children:
        if not isinstance(item, dict):
            errors.append("MEGA804_CHILD_ROW_INVALID")
            continue
        nfs = item.get("nf")
        if not isinstance(nfs, list):
            errors.append("MEGA804_CHILD_NF_INVALID")
            continue
        owned_nf.extend(str(nf) for nf in nfs)
        evidence_file = item.get("evidence_file")
        if not isinstance(evidence_file, str):
            errors.append("MEGA804_CHILD_EVIDENCE_PATH_MISSING")
            continue
        path = ROOT / evidence_file
        if not path.is_file():
            errors.append(f"MEGA804_CHILD_EVIDENCE_MISSING:{evidence_file}")
            continue
        evidence = json.loads(path.read_text(encoding="utf-8"))
        if evidence.get("mega_id") != "MEGA8-04":
            errors.append(f"MEGA804_CHILD_MEGA_ID_MISMATCH:{evidence_file}")
        if evidence.get("roadmap_pr") != item.get("roadmap_pr"):
            errors.append(f"MEGA804_CHILD_ROADMAP_PR_MISMATCH:{evidence_file}")
        if evidence.get("nf") != nfs:
            errors.append(f"MEGA804_CHILD_NF_PARTITION_MISMATCH:{evidence_file}")
        if evidence.get("live_enabled") is not False:
            errors.append(f"MEGA804_CHILD_LIVE_NOT_OFF:{evidence_file}")
        if evidence.get("signing_enabled") is not False:
            errors.append(f"MEGA804_CHILD_SIGNING_NOT_OFF:{evidence_file}")
        if evidence.get("submission_enabled") is not False:
            errors.append(f"MEGA804_CHILD_SUBMISSION_NOT_OFF:{evidence_file}")
        if evidence.get("operational_qualified") is not False:
            errors.append(f"MEGA804_CHILD_OPERATIONAL_FALSE_REQUIRED:{evidence_file}")

    if set(owned_nf) != EXPECTED_NF or len(owned_nf) != len(set(owned_nf)):
        errors.append("MEGA804_PRIMARY_NF_PARTITION_INVALID")

    for nf_id, symbol in mega8_04.NF_SYMBOLS.items():
        if not hasattr(mega8_04, symbol):
            errors.append(f"MEGA804_SYMBOL_MISSING:{nf_id}:{symbol}")

    for field in (
        "operational_qualified",
        "release_claim_allowed",
        "production_ready",
        "live_enabled",
        "signing_enabled",
        "submission_enabled",
        "automatic_capital_increase_allowed",
    ):
        if data.get(field) is not False:
            errors.append(f"MEGA804_UNSAFE_FLAG:{field}")

    blockers = data.get("residual_blockers")
    if not isinstance(blockers, list) or not blockers:
        errors.append("MEGA804_RESIDUAL_BLOCKERS_REQUIRED")

    return {
        "schema_version": "mega8-04.verification.v1",
        "accepted": not errors,
        "mega_id": "MEGA8-04",
        "child_count": len(child_ids),
        "nf_count": len(set(owned_nf)),
        "errors": errors,
        "operational_qualified": False,
        "release_claim_allowed": False,
        "production_ready": False,
        "live_enabled": False,
        "residual_blockers": blockers if isinstance(blockers, list) else [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    evidence = verify()
    if args.json:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    else:
        print(
            "MEGA8-04 structural closure:", "PASS" if evidence["accepted"] else "FAIL"
        )
        for error in evidence["errors"]:
            print(f"- {error}")
    return 0 if evidence["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
