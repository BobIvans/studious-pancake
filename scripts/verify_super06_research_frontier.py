"""Fail-closed static closure verifier for SUPER-06 = W2-16 + W2-21."""

from __future__ import annotations

import argparse
import hashlib
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

EXPECTED_CHILD_METADATA: Mapping[str, Mapping[str, object]] = {
    "PR-123": {
        "package": "W2-16", "scope": "ML-01", "owner": "src/decision/agg10.py",
        "test": "tests/test_agg10_intelligence.py",
        "evidence": "release_artifacts/agg/AGG-10/coverage.json", "merged_by_pr": 500,
    },
    "PR-124": {
        "package": "W2-16", "scope": "ML-02", "owner": "src/decision/agg10.py",
        "test": "tests/test_agg10_intelligence.py",
        "evidence": "release_artifacts/agg/AGG-10/coverage.json", "merged_by_pr": 500,
    },
    "PR-125": {
        "package": "W2-16", "scope": "ML-03", "owner": "src/decision/agg10.py",
        "test": "tests/test_agg10_intelligence.py",
        "evidence": "release_artifacts/agg/AGG-10/coverage.json", "merged_by_pr": 500,
    },
    "PR-145": {
        "package": "W2-16", "scope": "RND-01", "owner": "src/research/evidence.py",
        "test": "tests/test_agg14_research_system.py",
        "evidence": "config/agg14_research_coverage.json", "merged_by_pr": 509,
    },
    "PR-149": {
        "package": "W2-16", "scope": "RND-04", "owner": "src/research/promotion.py",
        "test": "tests/test_agg14_research_system.py",
        "evidence": "config/agg14_research_coverage.json", "merged_by_pr": 509,
    },
    "PR-146": {
        "package": "W2-21", "scope": "RND-02", "owner": "src/research/benchmarks.py",
        "test": "tests/test_agg14_research_system.py",
        "evidence": "config/agg14_research_coverage.json", "merged_by_pr": 509,
    },
    "PR-147": {
        "package": "W2-21", "scope": "RND-03", "owner": "src/research/verifiability.py",
        "test": "tests/test_agg14_research_system.py",
        "evidence": "config/agg14_research_coverage.json", "merged_by_pr": 509,
    },
}

EXPECTED_SOURCE_BLOBS: Mapping[str, str] = {
    "src/decision/agg10.py": "8e2c777a53efe2716229b67609d44bcc66278c7c",
    "tests/test_agg10_intelligence.py": "8569fb519b504ed6ad99e7ebda5f3136771d7d3b",
    "release_artifacts/agg/AGG-10/coverage.json": "90fef936d66d4d2b53b78211cd115b1bd77260e3",
    "src/research/evidence.py": "bfbdc1d883070c3b9db2f3e41c8f81ec002fc960",
    "src/research/promotion.py": "6e2212ba777c16317b5f1e890c87a24830fd4fe2",
    "src/research/benchmarks.py": "f7fe5c4e99fd665564700999db6b2ace49a344cc",
    "src/research/verifiability.py": "e6ffc3131540ba59f6e7c76a919b61fd0287a070",
    "tests/test_agg14_research_system.py": "df28cf5c9f6f5c6ed3c706187b4e8ea3c00d150c",
    "config/agg14_research_coverage.json": "51b968bfadfac0712c93ab14c8273e958392c08a",
}

EXPECTED_BLOCKERS = frozenset({
    "SUPER06_NF223_ACTUAL_LIVE03_SENT_ATTEMPT_LABELS_NOT_ATTESTED",
    "SUPER06_DEFENSIVE_TOOL_CORPUS_NOT_EXTERNALLY_QUALIFIED",
    "SUPER06_QUBO_HARDWARE_EXPERIMENT_NOT_RUN",
    "SUPER06_QUANTUM_MODEL_HOLDOUT_EXPERIMENT_NOT_RUN",
    "SUPER06_ACCELERATOR_HARDWARE_BENCHMARK_NOT_RUN",
    "SUPER06_FEDERATED_USE_CASE_AND_PARTICIPANT_CONSENT_NOT_PROVISIONED",
    "SUPER06_ZK_USE_CASE_AND_PROOF_SYSTEM_NOT_PINNED",
})

EXPECTED_AGG14_BLOCKERS: Mapping[str, tuple[str, ...]] = {
    "NF-312": ("DEFENSIVE_TOOL_CORPUS_NOT_EXTERNALLY_QUALIFIED",),
    "NF-313": ("QUBO_HARDWARE_EXPERIMENT_NOT_RUN",),
    "NF-314": ("QUANTUM_MODEL_HOLDOUT_EXPERIMENT_NOT_RUN",),
    "NF-315": ("ACCELERATOR_HARDWARE_BENCHMARK_NOT_RUN",),
    "NF-316": ("FEDERATED_USE_CASE_AND_PARTICIPANT_CONSENT_NOT_PROVISIONED",),
    "NF-317": ("ZK_USE_CASE_AND_PROOF_SYSTEM_NOT_PINNED",),
}


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"OBJECT_REQUIRED:{path}")
    return payload


def _git_blob_sha(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"SUPER06_PINNED_SOURCE_MISSING:{path}") from exc
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


def validate_pinned_source_blobs(root: Path) -> None:
    for relative, expected_sha in EXPECTED_SOURCE_BLOBS.items():
        observed = _git_blob_sha(root / relative)
        if observed != expected_sha:
            raise ValueError(
                f"SUPER06_SOURCE_BLOB_MISMATCH:{relative}:{observed}:{expected_sha}"
            )


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
    for child, expected_nf in EXPECTED_CHILDREN.items():
        row = by_child[child]
        if tuple(row["nf"]) != expected_nf:
            raise ValueError(f"SUPER06_CHILD_NF_SCOPE_MISMATCH:{child}")
        expected_metadata = EXPECTED_CHILD_METADATA[child]
        for key, expected_value in expected_metadata.items():
            if row.get(key) != expected_value:
                raise ValueError(f"SUPER06_CHILD_METADATA_MISMATCH:{child}:{key}")

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
    if not isinstance(blockers, list) or any(not isinstance(item, str) for item in blockers):
        raise ValueError("SUPER06_BLOCKERS_INVALID")
    if frozenset(blockers) != EXPECTED_BLOCKERS or len(blockers) != len(EXPECTED_BLOCKERS):
        raise ValueError("SUPER06_BLOCKER_SET_MISMATCH")


def validate_source_artifacts(root: Path, payload: Mapping[str, Any]) -> None:
    validate_pinned_source_blobs(root)

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
    agg10_blockers = agg10.get("blockers")
    if not isinstance(agg10_blockers, list) or not any(
        isinstance(item, str)
        and "NF-223" in item
        and "LIVE-03" in item
        and "sent-attempt" in item
        for item in agg10_blockers
    ):
        raise ValueError("SUPER06_AGG10_NF223_SOURCE_BLOCKER_MISSING")

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
    for nf, expected_blockers in EXPECTED_AGG14_BLOCKERS.items():
        if tuple(agg14_rows[nf].get("blockers", ())) != expected_blockers:
            raise ValueError(f"SUPER06_AGG14_SOURCE_BLOCKER_MISMATCH:{nf}")

    for child, expected_metadata in EXPECTED_CHILD_METADATA.items():
        for key in ("owner", "test", "evidence"):
            value = expected_metadata[key]
            if not isinstance(value, str) or not (root / value).is_file():
                raise ValueError(f"SUPER06_MISSING_EVIDENCE_PATH:{child}:{key}")


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
        "pinned_source_blob_count": len(EXPECTED_SOURCE_BLOBS),
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
