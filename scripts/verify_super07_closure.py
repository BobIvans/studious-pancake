#!/usr/bin/env python3
"""Fail-closed structural verifier for the SUPER-07 W2-17..W2-20 closure."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
COVERAGE_PATH = ROOT / "config" / "super07_coverage.json"

EXPECTED_W2 = ("W2-17", "W2-18", "W2-19", "W2-20")
EXPECTED_CHILDREN = tuple(f"PR-{number:03d}" for number in range(129, 145))
EXPECTED_NF = frozenset(
    {
        *(f"NF-{number:03d}" for number in (77, 78, 79, 80, 82)),
        *(f"NF-{number:03d}" for number in range(257, 272)),
        *(f"NF-{number:03d}" for number in range(272, 281)),
        "NF-282",
        "NF-283",
        "NF-281",
        "NF-284",
        "NF-285",
        "NF-286",
        "NF-287",
        "NF-288",
        "NF-289",
        *(f"NF-{number:03d}" for number in range(290, 306)),
        "NF-306",
        "NF-307",
    }
)
ALLOWED_IMPLEMENTATION = {"SATISFIED_BY_EXISTING", "VERIFIED"}
ALLOWED_QUALIFICATION = {"UNQUALIFIED", "RESEARCH_ONLY"}


def verify_payload(
    payload: Mapping[str, Any],
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    errors: list[str] = []
    if payload.get("schema_version") != "super07.coverage.v1":
        errors.append("SCHEMA_VERSION_MISMATCH")
    if payload.get("super_id") != "SUPER-07":
        errors.append("SUPER_ID_MISMATCH")
    if tuple(payload.get("w2_packages", ())) != EXPECTED_W2:
        errors.append("W2_PACKAGE_SET_MISMATCH")
    if payload.get("live_enabled") is not False:
        errors.append("LIVE_MUST_REMAIN_DISABLED")
    if payload.get("operational_qualified") is not False:
        errors.append("OPERATIONAL_QUALIFICATION_MUST_REMAIN_FALSE")

    children = payload.get("children")
    if not isinstance(children, list):
        errors.append("CHILDREN_REQUIRED")
        children = []

    child_ids = tuple(
        child.get("source_pr_id")
        for child in children
        if isinstance(child, Mapping)
    )
    if child_ids != EXPECTED_CHILDREN:
        errors.append("CHILD_PR_SET_MISMATCH")

    observed_nf: list[str] = []
    for child in children:
        if not isinstance(child, Mapping):
            errors.append("CHILD_ENTRY_INVALID")
            continue
        if child.get("implementation_status") not in ALLOWED_IMPLEMENTATION:
            errors.append(f"{child.get('source_pr_id')}:IMPLEMENTATION_STATUS_INVALID")
        if child.get("qualification_status") not in ALLOWED_QUALIFICATION:
            errors.append(f"{child.get('source_pr_id')}:QUALIFICATION_STATUS_INVALID")
        nf = child.get("primary_nf")
        if not isinstance(nf, list) or not nf:
            errors.append(f"{child.get('source_pr_id')}:PRIMARY_NF_REQUIRED")
        else:
            observed_nf.extend(str(item) for item in nf)
        for key in ("canonical_owner_paths", "test_paths"):
            paths = child.get(key)
            if not isinstance(paths, list) or not paths:
                errors.append(f"{child.get('source_pr_id')}:{key.upper()}_REQUIRED")
                continue
            for relative in paths:
                path = root / str(relative)
                if not path.is_file():
                    errors.append(
                        f"{child.get('source_pr_id')}:{key.upper()}_MISSING:{relative}"
                    )

    if len(observed_nf) != len(set(observed_nf)):
        errors.append("DUPLICATE_PRIMARY_NF")
    if frozenset(observed_nf) != EXPECTED_NF:
        errors.append("PRIMARY_NF_SET_MISMATCH")

    blockers = payload.get("blockers")
    if not isinstance(blockers, list) or not blockers:
        errors.append("OPERATIONAL_BLOCKERS_REQUIRED")

    return {
        "ok": not errors,
        "super_id": "SUPER-07",
        "child_count": len(children),
        "nf_count": len(set(observed_nf)),
        "implementation_closure": not errors,
        "operational_qualified": False,
        "live_enabled": False,
        "errors": errors,
        "blockers": list(blockers) if isinstance(blockers, list) else [],
    }


def verify_file(path: Path = COVERAGE_PATH) -> dict[str, Any]:
    return verify_payload(json.loads(path.read_text(encoding="utf-8")))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = verify_file()
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(
            f"SUPER-07 ok={result['ok']} children={result['child_count']} "
            f"nf={result['nf_count']} operational_qualified=false live=false"
        )
        for error in result["errors"]:
            print(f"ERROR {error}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
