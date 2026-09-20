#!/usr/bin/env python3
"""Verify SUPER-01 implementation ownership without claiming external qualification."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CHILD_NF: Final[dict[str, tuple[str, ...]]] = {
    "PR-079": tuple([f"NF-{n:03d}" for n in range(1, 12)] + ["NF-016"]),
    "PR-080": tuple(f"NF-{n:03d}" for n in range(17, 31)),
    "PR-082": tuple(f"NF-{n:03d}" for n in range(31, 45)),
    "PR-083": tuple([f"NF-{n:03d}" for n in range(45, 55)] + ["NF-061"]),
    "PR-084": tuple(f"NF-{n:03d}" for n in range(55, 61)),
    "PR-085": ("NF-062", "NF-063", "NF-064", "NF-065", "NF-066", "NF-083"),
    "PR-086": ("NF-067", "NF-069", "NF-071", "NF-075", "NF-076"),
    "PR-077": ("NF-345", "NF-346", "NF-347", "NF-348"),
    "PR-088": (
        "NF-084",
        "NF-085",
        "NF-086",
        "NF-087",
        "NF-088",
        "NF-089",
        "NF-091",
        "NF-092",
        "NF-093",
        "NF-094",
    ),
    "PR-089": ("NF-090", "NF-095"),
    "PR-075": ("NF-337", "NF-338", "NF-339", "NF-340"),
}

OWNER_SYMBOLS: Final[dict[str, tuple[str, ...]]] = {
    "PR-079": (
        "src.release_gate.agg01_foundation:CampaignBaseline",
        "src.release_gate.agg01_foundation:CoverageMatrix",
    ),
    "PR-080": (
        "src.release_gate.agg01_foundation:UpstreamPin",
        "src.release_gate.agg01_foundation:LicenseDecision",
        "src.release_gate.agg01_foundation:ReuseAdmission",
    ),
    "PR-082": (
        "src.agg02:SourceBudgetAuthority",
        "src.agg02:SourceBudgetReservation",
        "src.agg02:SubscriptionPlan",
    ),
    "PR-083": (
        "src.agg02:RawEventEnvelope",
        "src.agg02:StateFrame",
        "src.agg02:DurableRawJournal",
    ),
    "PR-084": (
        "src.agg02:DatasetManifest",
        "src.agg02:DatasetReplayReader",
    ),
    "PR-085": (
        "src.agg02:SubscriptionPlan",
        "src.data_plane.bounded_provider_plane_pr197:SQLiteQuotaAuthority",
    ),
    "PR-086": (
        "src.agg02:ExecutableGraph",
        "src.agg02:CapacitySurface",
        "src.agg02:FeeSurface",
    ),
    "PR-077": (
        "src.agg02:TransactionReadCapabilityReport",
        "src.agg02:decode_versioned_transaction_envelope",
        "src.agg02:record_format_coverage_gap",
    ),
    "PR-088": (
        "src.agg02:ExecutableGraph",
        "src.agg02:AffectedRouteIndex",
        "src.agg02:EvidenceLineageDAG",
    ),
    "PR-089": (
        "src.decision.agg10:StatisticalRelationGraph",
        "src.decision.agg10:compare_source_ablation",
    ),
    "PR-075": (
        "src.agg02:record_market_lifecycle_evidence",
        "src.agg02:materialize_market_membership",
        "src.agg02:select_universe_as_known",
        "src.agg02:audit_universe_survivorship",
    ),
}

OPERATIONAL_BLOCKERS: Final[tuple[str, ...]] = (
    "SUPER01_EXTERNAL_COLLECTOR_FLEET_NOT_QUALIFIED",
    "SUPER01_V1_PROVIDER_SDK_CODEC_NOT_QUALIFIED",
    "SUPER01_HISTORICAL_MEMBERSHIP_SOURCE_NOT_QUALIFIED",
)


def _symbol_exists(reference: str) -> bool:
    module_name, symbol = reference.split(":", 1)
    try:
        module = importlib.import_module(module_name)
    except Exception:
        return False
    return hasattr(module, symbol)


def verify() -> dict[str, object]:
    errors: list[str] = []
    all_nf = [nf for values in CHILD_NF.values() for nf in values]
    if len(all_nf) != len(set(all_nf)):
        errors.append("SUPER01_DUPLICATE_PRIMARY_NF")
    if len(all_nf) != 88:
        errors.append(f"SUPER01_NF_COUNT_MISMATCH:{len(all_nf)}")

    child_status: dict[str, dict[str, object]] = {}
    for child, references in OWNER_SYMBOLS.items():
        missing = tuple(ref for ref in references if not _symbol_exists(ref))
        if missing:
            errors.extend(f"SUPER01_OWNER_SYMBOL_MISSING:{ref}" for ref in missing)
        child_status[child] = {
            "nf": list(CHILD_NF[child]),
            "owner_symbols": list(references),
            "implementation_status": (
                "SATISFIED_BY_EXISTING"
                if child not in {"PR-077", "PR-075"}
                else "IMPLEMENTED_OFFLINE"
            ),
            "missing_symbols": list(missing),
        }

    expected_children = set(CHILD_NF)
    if set(OWNER_SYMBOLS) != expected_children:
        errors.append("SUPER01_CHILD_OWNER_COVERAGE_MISMATCH")

    return {
        "schema_version": "super01.closure-evidence.v1",
        "accepted": not errors,
        "super_id": "SUPER-01",
        "packages": ["W2-01", "W2-02", "W2-05"],
        "child_count": len(CHILD_NF),
        "nf_count": len(set(all_nf)),
        "children": child_status,
        "errors": errors,
        "operational_qualified": False,
        "live_enabled": False,
        "signing_enabled": False,
        "submission_enabled": False,
        "operational_blockers": list(OPERATIONAL_BLOCKERS),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    evidence = verify()
    if args.json:
        print(json.dumps(evidence, sort_keys=True, indent=2))
    else:
        print(
            "SUPER-01 implementation closure: "
            + ("PASS" if evidence["accepted"] else "FAIL")
        )
        for error in evidence["errors"]:
            print(f"- {error}")
    return 0 if evidence["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
