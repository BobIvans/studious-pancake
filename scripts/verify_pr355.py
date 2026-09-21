#!/usr/bin/env python3
"""Structural and semantic verifier for PR-355 Evidence-Native Mechanism OS."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

from src.mechanism_discovery.boros import run_boros_fixture_vertical
from src.mechanism_discovery.marketpacks import MARKETPACKS
from src.mechanism_discovery.pr355_manifest import (
    FUNCTION_COUNT,
    GROUPS,
    NXF_IDS,
    NXF_TO_SYMBOL,
)

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_EFFECT_TOKENS = (
    "from src.submission",
    "import src.submission",
    "isolated_signer_service",
    "from src.live_boundary",
    "import src.live_boundary",
    "send_transaction(",
    "submit_transaction(",
    "requests.",
    "aiohttp.",
    "httpx.",
)

PR355_MODULES = (
    "evidence_native_core.py",
    "pr355_delta.py",
    "claims.py",
    "liquidity_shape.py",
    "programmable_cash.py",
    "rwa.py",
    "shared_credit.py",
    "mechanism_transfer.py",
    "frontier.py",
    "research_receipt.py",
    "research_resources.py",
    "incident_admission.py",
    "causal_twin.py",
    "marketpacks.py",
    "boros.py",
    "pr355_manifest.py",
)

REQUIRED_ARTIFACTS = (
    "config/pr355_owner_map.json",
    "config/pr355_marketpacks.json",
    "config/pr355_experiments.json",
    "docs/roadmap/pr355-evidence-native-mechanism-os.md",
    "docs/roadmap/pr355_source_provenance.json",
    "release_artifacts/pr355/current-head-evidence.json",
)


def verify() -> dict[str, object]:
    errors: list[str] = []

    if FUNCTION_COUNT != 72 or NXF_IDS != tuple(
        f"NXF-{index:03d}" for index in range(1, 73)
    ):
        errors.append("PR355_NXF_MANIFEST_MISMATCH")
    if tuple(GROUPS) != tuple(f"NX-{index:02d}" for index in range(12)):
        errors.append("PR355_NX_GROUP_SET_MISMATCH")

    for nxf, (_group, module_name, symbol) in NXF_TO_SYMBOL.items():
        module = importlib.import_module(f"src.mechanism_discovery.{module_name}")
        if not callable(getattr(module, symbol, None)):
            errors.append(f"PR355_SYMBOL_MISSING:{nxf}:{module_name}:{symbol}")

    for relative in REQUIRED_ARTIFACTS:
        if not (ROOT / relative).is_file():
            errors.append(f"PR355_REQUIRED_ARTIFACT_MISSING:{relative}")

    owner_map = json.loads(
        (ROOT / "config/pr355_owner_map.json").read_text(encoding="utf-8")
    )
    counts = owner_map.get("counts", {})
    if counts != {"ig": 57, "nxf": 72, "marketpacks": 9, "total": 138}:
        errors.append("PR355_OWNER_MAP_COUNT_MISMATCH")
    if owner_map.get("duplicate_authorities") != []:
        errors.append("PR355_DUPLICATE_AUTHORITY_DECLARED")
    if owner_map.get("permanent_nf_allocated") is not False:
        errors.append("PR355_UNAUTHORIZED_NF_ALLOCATION")

    ig_rows = owner_map.get("ig_obligations", [])
    nxf_rows = owner_map.get("nxf_requirements", [])
    pack_rows = owner_map.get("marketpacks", [])
    all_ids = [
        *(row.get("requirement_id") for row in ig_rows),
        *(row.get("requirement_id") for row in nxf_rows),
        *(row.get("requirement_id") for row in pack_rows),
    ]
    if len(all_ids) != len(set(all_ids)) or len(all_ids) != 138:
        errors.append("PR355_OWNER_MAP_ID_DUPLICATE_OR_GAP")
    if [row.get("requirement_id") for row in nxf_rows] != list(NXF_IDS):
        errors.append("PR355_NXF_OWNER_MAP_ORDER_MISMATCH")
    for row in nxf_rows:
        expected = NXF_TO_SYMBOL.get(row.get("requirement_id"))
        if expected is None:
            continue
        _group, module_name, symbol = expected
        if row.get("owner") != f"src.mechanism_discovery.{module_name}":
            errors.append(f"PR355_NXF_OWNER_MISMATCH:{row.get('requirement_id')}")
        if row.get("symbol") != symbol:
            errors.append(f"PR355_NXF_SYMBOL_MISMATCH:{row.get('requirement_id')}")
        if row.get("permanent_nf") is not None:
            errors.append(f"PR355_NXF_PERMANENT_NF_FORBIDDEN:{row.get('requirement_id')}")

    packs = json.loads(
        (ROOT / "config/pr355_marketpacks.json").read_text(encoding="utf-8")
    )
    if set(packs.get("packages", {})) != set(MARKETPACKS):
        errors.append("PR355_MARKETPACK_SET_MISMATCH")
    for pack_id, row in packs.get("packages", {}).items():
        if row.get("state") != "DISABLED" or row.get("live") is not False:
            errors.append(f"PR355_MARKETPACK_NOT_DISABLED:{pack_id}")
    boundary = packs.get("effect_boundary", {})
    if not boundary or any(value is not False for value in boundary.values()):
        errors.append("PR355_EFFECT_BOUNDARY_UNSAFE")
    if packs.get("marginfi") != "PAUSED":
        errors.append("PR355_MARGINFI_NOT_PAUSED")
    if packs.get("slumlord_low_capital_requirement") != "REQUIRED":
        errors.append("PR355_SLUMLORD_REQUIREMENT_DRIFT")
    if packs.get("source_copy_performed") is not False:
        errors.append("PR355_SOURCE_COPY_FLAG_UNSAFE")

    experiments = json.loads(
        (ROOT / "config/pr355_experiments.json").read_text(encoding="utf-8")
    )
    rows = experiments.get("rows", [])
    expected_experiments = [f"NXE-{index:02d}" for index in range(1, 27)]
    if [row.get("id") for row in rows] != expected_experiments:
        errors.append("PR355_EXPERIMENT_REGISTRY_MISMATCH")
    if experiments.get("preregistered") is not True:
        errors.append("PR355_EXPERIMENTS_NOT_PREREGISTERED")
    if any(row.get("execution_right") is not False for row in rows):
        errors.append("PR355_EXPERIMENT_EXECUTION_RIGHT_UNSAFE")
    if rows and rows[0].get("status") != "FIXTURE_TESTED_BLOCKED_EXTERNAL":
        errors.append("PR355_NXE01_STATUS_MISMATCH")
    if any(row.get("status") == "QUALIFIED" for row in rows):
        errors.append("PR355_SYNTHETIC_QUALIFICATION_FORBIDDEN")

    provenance = json.loads(
        (ROOT / "docs/roadmap/pr355_source_provenance.json").read_text(
            encoding="utf-8"
        )
    )
    if provenance.get("copy_or_port_performed") is not False:
        errors.append("PR355_UNATTESTED_SOURCE_COPY")
    for row in provenance.get("rows", []):
        if row.get("reuse_mode") != "REFERENCE_ONLY":
            errors.append("PR355_UPSTREAM_NOT_REFERENCE_ONLY")
        if row.get("source_copy_allowed") is not False:
            errors.append("PR355_EXTERNAL_COPY_ALLOWED")
        if row.get("remote_action_performed") is not False:
            errors.append("PR355_REMOTE_ACTION_CLAIMED")

    source_root = ROOT / "src" / "mechanism_discovery"
    for name in PR355_MODULES:
        source = (source_root / name).read_text(encoding="utf-8")
        for token in FORBIDDEN_EFFECT_TOKENS:
            if token in source:
                errors.append(f"PR355_FORBIDDEN_EFFECT_TOKEN:{name}:{token}")

    evo09 = (
        ROOT / "src/strategy_evolution/residual_discovery.py"
    ).read_text(encoding="utf-8")
    for required in (
        '"outcome_missing": realized_net_atoms is None',
        '"mixed_units_combined": False',
        "STABILITY_EVIDENCE_REQUIRED",
        "FDR_EVIDENCE_REQUIRED",
        "PERSISTENCE_EVIDENCE_REQUIRED",
    ):
        if required not in evo09:
            errors.append(f"PR355_EVO09_SEMANTIC_REPAIR_MISSING:{required}")

    boros = run_boros_fixture_vertical()
    if boros.get("verdict") != "BLOCKED_EXTERNAL":
        errors.append("PR355_BOROS_FAKE_QUALIFICATION")
    if boros.get("fixture_tested") is not True or boros.get("synthetic_pass") is not False:
        errors.append("PR355_BOROS_FIXTURE_STATUS_INVALID")
    if int(boros["forecast_written_at"]) >= int(boros["mature_label_available_at"]):
        errors.append("PR355_BOROS_TEMPORAL_LEAKAGE")

    evidence = json.loads(
        (ROOT / "release_artifacts/pr355/current-head-evidence.json").read_text(
            encoding="utf-8"
        )
    )
    claims = evidence.get("claims", {})
    if any(
        claims.get(field) is not False
        for field in ("qualified", "authorized_live", "production_ready", "profitability")
    ):
        errors.append("PR355_EVIDENCE_OVERCLAIM")
    safety = evidence.get("safety", {})
    if any(value is not False for value in safety.values()):
        errors.append("PR355_EVIDENCE_SAFETY_UNSAFE")

    return {
        "accepted": not errors,
        "nxf_count": FUNCTION_COUNT,
        "ig_count": len(ig_rows),
        "marketpack_count": len(pack_rows),
        "experiment_count": len(rows),
        "owner_total": len(all_ids),
        "boros_verdict": boros.get("verdict"),
        "errors": errors,
        "live_enabled": False,
        "signer_access": False,
        "submission_access": False,
        "automatic_promotion": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = verify()
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(payload)
    return 0 if payload["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
