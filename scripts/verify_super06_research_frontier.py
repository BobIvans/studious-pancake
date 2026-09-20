"""Fail-closed static closure verifier for SUPER-06 = W2-16 + W2-21."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

EXPECTED_CHILDREN: Mapping[str, tuple[str, ...]] = {
    "PR-123": tuple(f"NF-{n:03d}" for n in range(216, 222)) + ("NF-230", "NF-232"),
    "PR-124": tuple(f"NF-{n:03d}" for n in range(222, 230)) + ("NF-231", "NF-238"),
    "PR-125": tuple(f"NF-{n:03d}" for n in range(233, 238)),
    "PR-145": tuple(f"NF-{n:03d}" for n in range(308, 313)),
    "PR-149": ("NF-323",),
    "PR-146": tuple(f"NF-{n:03d}" for n in range(313, 316)),
    "PR-147": tuple(f"NF-{n:03d}" for n in range(316, 318)),
}
EXPECTED_NF = frozenset(nf for values in EXPECTED_CHILDREN.values() for nf in values)
EXCLUDED_PRODUCT_NF = frozenset(f"NF-{n:03d}" for n in range(318, 323))
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_RECEIPTS: Mapping[str, tuple[int, str]] = {
    "AGG-10": (500, "de483bc3084a87d2b3f34830bdecf94ea0e4e63d"),
    "AGG-14": (509, "baedd8c0697c0bf789e582dab8acf5bbc113c123"),
    "AGG-09": (505, "5d1d8177c933221dcb31baf0753924c4f32e3313"),
    "AGG-05": (498, "1eef148ae77459f9974754b6b911ab31b461c851"),
    "AGG-04": (497, "b26c6a05c0646fb839f49f537fc21acbd863455c"),
    "AGG-02": (496, "a52bbd11338e3c9092cd871227d2279450b928a3"),
    "AGG-01": (501, "670ed70a3b3be199ece5d5f6cba29ee1709d4c55"),
}


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"OBJECT_REQUIRED:{path}")
    return payload


def validate_super_payload(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != "super06.research-frontier-closure.v1":
        raise ValueError("SUPER06_SCHEMA_INVALID")
    if payload.get("super_id") != "SUPER-06":
        raise ValueError("SUPER06_ID_INVALID")
    if payload.get("source_packages") != ["W2-16", "W2-21"]:
        raise ValueError("SUPER06_PACKAGE_SCOPE_INVALID")
    for key in ("live_enabled", "signing_enabled", "submission_enabled", "production_ready"):
        if payload.get(key) is not False:
            raise ValueError(f"SUPER06_UNSAFE_FLAG:{key}")
    if payload.get("implementation_status") != "VERIFIED":
        raise ValueError("SUPER06_IMPLEMENTATION_STATUS_INVALID")
    if payload.get("operational_status") != "UNQUALIFIED":
        raise ValueError("SUPER06_OPERATIONAL_STATUS_MUST_REMAIN_UNQUALIFIED")
    if payload.get("activation_status") != "DEFAULT_OFF":
        raise ValueError("SUPER06_ACTIVATION_MUST_REMAIN_DEFAULT_OFF")

    rows = payload.get("children")
    if not isinstance(rows, list):
        raise ValueError("SUPER06_CHILD_ROWS_MISSING")
    by_child: dict[str, Mapping[str, Any]] = {}
    all_nf: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("SUPER06_CHILD_ROW_INVALID")
        child = row.get("source_pr")
        if not isinstance(child, str) or child in by_child:
            raise ValueError("SUPER06_CHILD_ID_DUPLICATE_OR_INVALID")
        by_child[child] = row
        nfs = row.get("nf")
        if not isinstance(nfs, list) or any(not isinstance(nf, str) for nf in nfs):
            raise ValueError(f"SUPER06_CHILD_NF_INVALID:{child}")
        all_nf.extend(nfs)
        if row.get("disposition") != "SATISFIED_BY_EXISTING":
            raise ValueError(f"SUPER06_CHILD_NOT_REUSED:{child}")

    if set(by_child) != set(EXPECTED_CHILDREN):
        raise ValueError("SUPER06_CHILD_SCOPE_MISMATCH")
    for child, expected in EXPECTED_CHILDREN.items():
        if tuple(by_child[child]["nf"]) != expected:
            raise ValueError(f"SUPER06_CHILD_NF_SCOPE_MISMATCH:{child}")
    if len(all_nf) != len(set(all_nf)):
        raise ValueError("SUPER06_DUPLICATE_PRIMARY_NF")
    if frozenset(all_nf) != EXPECTED_NF or payload.get("primary_nf_count") != len(EXPECTED_NF):
        raise ValueError("SUPER06_NF_SCOPE_MISMATCH")
    if set(all_nf) & EXCLUDED_PRODUCT_NF:
        raise ValueError("SUPER06_PRODUCT_SCOPE_INFLATION")
    if set(payload.get("excluded_adjacent_nf", ())) != EXCLUDED_PRODUCT_NF:
        raise ValueError("SUPER06_PRODUCT_EXCLUSION_RECORD_MISMATCH")

    receipts = payload.get("source_receipts")
    if not isinstance(receipts, list) or not receipts:
        raise ValueError("SUPER06_SOURCE_RECEIPTS_MISSING")
    observed_receipts: dict[str, tuple[int, str]] = {}
    for receipt in receipts:
        if not isinstance(receipt, dict) or not _SHA40.fullmatch(str(receipt.get("merge_sha", ""))):
            raise ValueError("SUPER06_SOURCE_RECEIPT_INVALID")
        name = receipt.get("name")
        pr = receipt.get("pr")
        sha = receipt.get("merge_sha")
        if not isinstance(name, str) or type(pr) is not int or not isinstance(sha, str):
            raise ValueError("SUPER06_SOURCE_RECEIPT_INVALID")
        if name in observed_receipts:
            raise ValueError("SUPER06_SOURCE_RECEIPT_DUPLICATE")
        observed_receipts[name] = (pr, sha)
    if observed_receipts != dict(EXPECTED_RECEIPTS):
        raise ValueError("SUPER06_SOURCE_RECEIPT_MISMATCH")

    blockers = payload.get("blockers")
    if not isinstance(blockers, list) or not blockers:
        raise ValueError("SUPER06_BLOCKERS_MUST_REMAIN_EXPLICIT")


def validate_source_artifacts(root: Path, payload: Mapping[str, Any]) -> None:
    agg10 = _load(root / "release_artifacts/agg/AGG-10/coverage.json")
    agg14 = _load(root / "config/agg14_research_coverage.json")

    if agg10.get("implementation_status") != "IMPLEMENTED_OFFLINE":
        raise ValueError("SUPER06_AGG10_IMPLEMENTATION_NOT_OFFLINE")
    if agg10.get("operational_status") != "UNQUALIFIED" or agg10.get("live_enabled") is not False:
        raise ValueError("SUPER06_AGG10_UNSAFE_STATUS")
    agg10_nf = set(agg10.get("primary_nf", ()))
    expected_ml = {f"NF-{n:03d}" for n in range(216, 239)}
    if not expected_ml <= agg10_nf:
        raise ValueError("SUPER06_AGG10_ML_COVERAGE_MISSING")

    rows = agg14.get("nf")
    if not isinstance(rows, list):
        raise ValueError("SUPER06_AGG14_ROWS_MISSING")
    agg14_rows = {row.get("id"): row for row in rows if isinstance(row, dict)}
    expected_research = {f"NF-{n:03d}" for n in range(308, 318)} | {"NF-323"}
    if not expected_research <= set(agg14_rows):
        raise ValueError("SUPER06_AGG14_RESEARCH_COVERAGE_MISSING")
    for key in ("live_enabled", "signing_enabled", "submission_enabled", "production_ready"):
        if agg14.get(key) is not False:
            raise ValueError(f"SUPER06_AGG14_UNSAFE_FLAG:{key}")
    for nf in expected_research:
        row = agg14_rows[nf]
        if row.get("implementation_status") != "IMPLEMENTED_OFFLINE":
            raise ValueError(f"SUPER06_AGG14_IMPLEMENTATION_MISMATCH:{nf}")
        if row.get("operational_status") != "UNQUALIFIED":
            raise ValueError(f"SUPER06_AGG14_OPERATIONAL_MISMATCH:{nf}")

    for child in payload["children"]:
        for key in ("owner", "test", "evidence"):
            value = child.get(key)
            if not isinstance(value, str) or not (root / value).is_file():
                raise ValueError(f"SUPER06_MISSING_EVIDENCE_PATH:{child.get('source_pr')}:{key}")


def verify(root: Path) -> dict[str, Any]:
    payload = _load(root / "release_artifacts/super/SUPER-06/coverage.json")
    validate_super_payload(payload)
    validate_source_artifacts(root, payload)
    return {
        "schema": "super06.verify-result.v1",
        "ok": True,
        "child_count": len(EXPECTED_CHILDREN),
        "nf_count": len(EXPECTED_NF),
        "implementation_status": payload["implementation_status"],
        "operational_status": payload["operational_status"],
        "activation_status": payload["activation_status"],
        "live_enabled": False,
        "product_scope_included": False,
        "blocker_count": len(payload["blockers"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = verify(Path(__file__).resolve().parents[1])
    print(json.dumps(result, sort_keys=True) if args.json else result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
