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
EXPECTED_CHILD_MAP = {
    "PR-129": {
        "w2_id": "W2-17",
        "scope": "DATA-05",
        "primary_nf": ("NF-077", "NF-078", "NF-079", "NF-080", "NF-082"),
        "canonical_owner_paths": ("src/data_plane/external_datasets.py",),
        "test_paths": ("tests/test_agg13_external_datasets.py",),
    },
    "PR-130": {
        "w2_id": "W2-17",
        "scope": "CHAIN-01",
        "primary_nf": ("NF-257", "NF-258", "NF-259"),
        "canonical_owner_paths": ("src/multichain/core.py",),
        "test_paths": ("tests/test_agg11_multichain_execution_models.py",),
    },
    "PR-131": {
        "w2_id": "W2-17",
        "scope": "CHAIN-02",
        "primary_nf": ("NF-260", "NF-261", "NF-262", "NF-263"),
        "canonical_owner_paths": ("src/multichain/evm_financing.py",),
        "test_paths": ("tests/test_agg11_multichain_execution_models.py",),
    },
    "PR-132": {
        "w2_id": "W2-17",
        "scope": "CHAIN-03",
        "primary_nf": ("NF-264",),
        "canonical_owner_paths": ("src/multichain/evm_settlement.py",),
        "test_paths": ("tests/test_agg11_multichain_execution_models.py",),
    },
    "PR-133": {
        "w2_id": "W2-17",
        "scope": "CHAIN-04",
        "primary_nf": ("NF-265", "NF-266", "NF-267", "NF-268"),
        "canonical_owner_paths": ("src/multichain/sui.py",),
        "test_paths": ("tests/test_agg11_multichain_execution_models.py",),
    },
    "PR-134": {
        "w2_id": "W2-17",
        "scope": "CHAIN-05",
        "primary_nf": ("NF-269", "NF-270"),
        "canonical_owner_paths": ("src/cross_chain/agg12.py",),
        "test_paths": ("tests/test_agg12_multichain_qualification.py",),
    },
    "PR-135": {
        "w2_id": "W2-17",
        "scope": "CHAIN-06",
        "primary_nf": ("NF-271",),
        "canonical_owner_paths": ("src/multichain/qualification.py",),
        "test_paths": ("tests/test_agg11_multichain_execution_models.py",),
    },
    "PR-136": {
        "w2_id": "W2-18",
        "scope": "EVM-01",
        "primary_nf": ("NF-272", "NF-273", "NF-274", "NF-275"),
        "canonical_owner_paths": ("src/cross_chain/agg12.py",),
        "test_paths": ("tests/test_agg12_multichain_qualification.py",),
    },
    "PR-137": {
        "w2_id": "W2-18",
        "scope": "EVM-02",
        "primary_nf": (
            "NF-276",
            "NF-277",
            "NF-278",
            "NF-279",
            "NF-280",
            "NF-282",
            "NF-283",
        ),
        "canonical_owner_paths": ("src/cross_chain/agg12.py",),
        "test_paths": ("tests/test_agg12_multichain_qualification.py",),
    },
    "PR-138": {
        "w2_id": "W2-18",
        "scope": "EVM-03",
        "primary_nf": ("NF-281", "NF-284", "NF-285"),
        "canonical_owner_paths": ("src/cross_chain/agg12.py",),
        "test_paths": ("tests/test_agg12_multichain_qualification.py",),
    },
    "PR-139": {
        "w2_id": "W2-18",
        "scope": "SUI-01",
        "primary_nf": ("NF-286", "NF-287"),
        "canonical_owner_paths": (
            "src/cross_chain/agg12.py",
            "src/multichain/sui.py",
        ),
        "test_paths": (
            "tests/test_agg12_multichain_qualification.py",
            "tests/test_agg11_multichain_execution_models.py",
        ),
    },
    "PR-140": {
        "w2_id": "W2-19",
        "scope": "INV-01",
        "primary_nf": ("NF-288", "NF-289", "NF-306", "NF-307"),
        "canonical_owner_paths": (
            "src/inventory/non_atomic.py",
            "src/inventory/research.py",
        ),
        "test_paths": ("tests/test_agg13_inventory_platform.py",),
    },
    "PR-141": {
        "w2_id": "W2-19",
        "scope": "INV-02",
        "primary_nf": tuple(f"NF-{number:03d}" for number in range(290, 296)),
        "canonical_owner_paths": ("src/inventory/research.py",),
        "test_paths": ("tests/test_agg13_inventory_platform.py",),
    },
    "PR-142": {
        "w2_id": "W2-19",
        "scope": "INV-03",
        "primary_nf": tuple(f"NF-{number:03d}" for number in range(296, 300)),
        "canonical_owner_paths": ("src/inventory/research.py",),
        "test_paths": ("tests/test_agg13_inventory_platform.py",),
    },
    "PR-143": {
        "w2_id": "W2-20",
        "scope": "INV-04",
        "primary_nf": ("NF-300", "NF-301", "NF-302"),
        "canonical_owner_paths": ("src/inventory/research.py",),
        "test_paths": ("tests/test_agg13_inventory_platform.py",),
    },
    "PR-144": {
        "w2_id": "W2-20",
        "scope": "INV-05",
        "primary_nf": ("NF-303", "NF-304", "NF-305"),
        "canonical_owner_paths": ("src/inventory/research.py",),
        "test_paths": ("tests/test_agg13_inventory_platform.py",),
    },
}
EXPECTED_DISPOSITIONS = {
    child_id: {
        "implementation_status": (
            "VERIFIED"
            if child_id in {"PR-136", "PR-137", "PR-139"}
            else "SATISFIED_BY_EXISTING"
        ),
        "qualification_status": (
            "RESEARCH_ONLY"
            if child_id in {"PR-134", "PR-144"}
            else "UNQUALIFIED"
        ),
    }
    for child_id in EXPECTED_CHILDREN
}

EXPECTED_BLOCKERS = frozenset(
    {
        "SUPER07_EXTERNAL_DATA_ENTITLEMENTS_UNQUALIFIED",
        "SUPER07_CHAIN_DEPLOYMENT_CONFORMANCE_UNQUALIFIED",
        "SUPER07_EVM_SUI_LOADED_STATE_CAMPAIGN_NOT_RUN",
        "SUPER07_EXCHANGE_CONNECTORS_AND_ACTUAL_FILL_RECONCILIATION_MISSING",
        "SUPER07_INVENTORY_MARGIN_STRESS_CAMPAIGN_NOT_RUN",
        "SUPER07_RWA_RIGHTS_CUSTODY_SESSION_ACCESS_UNQUALIFIED",
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
    if payload.get("source_pr_range") != "PR-129..PR-144":
        errors.append("SOURCE_PR_RANGE_MISMATCH")
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
        child_id = child.get("source_pr_id")
        expected = EXPECTED_CHILD_MAP.get(str(child_id))
        if expected is None:
            errors.append(f"{child_id}:CHILD_MAPPING_UNKNOWN")
        else:
            for key in (
                "w2_id",
                "scope",
                "primary_nf",
                "canonical_owner_paths",
                "test_paths",
            ):
                actual = child.get(key)
                if isinstance(actual, list):
                    actual = tuple(actual)
                if actual != expected[key]:
                    errors.append(f"{child_id}:CHILD_MAPPING_MISMATCH:{key}")
        implementation_status = child.get("implementation_status")
        qualification_status = child.get("qualification_status")
        if implementation_status not in ALLOWED_IMPLEMENTATION:
            errors.append(f"{child_id}:IMPLEMENTATION_STATUS_INVALID")
        if qualification_status not in ALLOWED_QUALIFICATION:
            errors.append(f"{child_id}:QUALIFICATION_STATUS_INVALID")
        expected_disposition = EXPECTED_DISPOSITIONS.get(str(child_id))
        if expected_disposition is not None:
            if (
                implementation_status
                != expected_disposition["implementation_status"]
            ):
                errors.append(
                    f"{child_id}:CHILD_MAPPING_MISMATCH:implementation_status"
                )
            if (
                qualification_status
                != expected_disposition["qualification_status"]
            ):
                errors.append(
                    f"{child_id}:CHILD_MAPPING_MISMATCH:qualification_status"
                )
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
    else:
        normalized_blockers = tuple(str(item).strip() for item in blockers)
        if any(not item for item in normalized_blockers):
            errors.append("OPERATIONAL_BLOCKER_EMPTY")
        if len(normalized_blockers) != len(set(normalized_blockers)):
            errors.append("OPERATIONAL_BLOCKER_DUPLICATE")
        if frozenset(normalized_blockers) != EXPECTED_BLOCKERS:
            errors.append("OPERATIONAL_BLOCKER_SET_MISMATCH")

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
