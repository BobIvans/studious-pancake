#!/usr/bin/env python3
"""Structural and semantic verifier for complete PR-355 roadmap scope."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

from src.mechanism_discovery.boros import run_boros_fixture_vertical
from src.mechanism_discovery.marketpack_adapters import all_marketpack_bindings
from src.mechanism_discovery.marketpacks import MARKETPACKS
from src.mechanism_discovery.pr355_manifest import (
    FUNCTION_COUNT,
    GROUPS,
    NXF_IDS,
    NXF_TO_SYMBOL,
)
from src.strategy_evolution.residual_discovery import (
    build_bot_operation_feature_frame,
    select_training_labels_as_of,
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
    "marketpack_adapters.py",
    "research_quality.py",
    "boros.py",
    "pr355_manifest.py",
)

REQUIRED_ARTIFACTS = (
    "config/pr355_owner_map.json",
    "config/pr355_marketpacks.json",
    "config/pr355_experiments.json",
    "config/pr355_rollback.json",
    "docs/roadmap/pr355-evidence-native-mechanism-os.md",
    "docs/roadmap/pr355-evidence-native-mechanism-os-ru.md",
    "docs/roadmap/pr355_source_provenance.json",
    "docs/mechanism_discovery/pr355_incident_corpus.json",
    "release_artifacts/pr355/current-head-evidence.json",
    "release_artifacts/pr355/completion_audit.json",
)

ALLOWED_OWNER_DISPOSITIONS = {
    "SATISFIED_BY_EXISTING",
    "SPECIALIZE_EXISTING",
    "NEW_OUTCOME",
    "BLOCKED_EXTERNAL",
}

ALLOWED_EVIDENCE_STATUSES = {
    "REFERENCE_ONLY",
    "CONTRACT_IMPLEMENTED",
    "FIXTURE_TESTED",
    "OFFLINE_REPLAYED",
    "PAPER_OBSERVED",
    "BLOCKED_EXTERNAL",
    "NOT_RUN",
    "QUALIFIED",
    "AUTHORIZED_LIVE",
}


def _module_from_path(path: str) -> str:
    if not path.startswith("src/") or not path.endswith(".py"):
        raise ValueError("owner path must be a src Python path")
    return path[:-3].replace("/", ".")


def _verify_owner_symbol(
    errors: list[str],
    *,
    requirement_id: str,
    path: object,
    symbol: object,
) -> None:
    if not isinstance(path, str) or not isinstance(symbol, str):
        errors.append(f"PR355_EXACT_OWNER_FIELDS_MISSING:{requirement_id}")
        return
    if not (ROOT / path).is_file():
        errors.append(f"PR355_OWNER_PATH_MISSING:{requirement_id}:{path}")
        return
    try:
        module = importlib.import_module(_module_from_path(path))
    except Exception as exc:
        errors.append(f"PR355_OWNER_IMPORT_FAIL:{requirement_id}:{exc}")
        return
    if not callable(getattr(module, symbol, None)):
        errors.append(f"PR355_OWNER_SYMBOL_MISSING:{requirement_id}:{symbol}")


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
    exact_contract = owner_map.get("exact_owner_contract", {})
    if not exact_contract or not all(exact_contract.values()):
        errors.append("PR355_EXACT_OWNER_CONTRACT_INCOMPLETE")

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

    for row in (*ig_rows, *nxf_rows, *pack_rows):
        requirement_id = str(row.get("requirement_id", "UNKNOWN"))
        if row.get("disposition") not in ALLOWED_OWNER_DISPOSITIONS:
            errors.append(f"PR355_OWNER_DISPOSITION_INVALID:{requirement_id}")
        if not row.get("tests") or not row.get("evidence_refs"):
            errors.append(f"PR355_OWNER_EVIDENCE_MISSING:{requirement_id}")
        _verify_owner_symbol(
            errors,
            requirement_id=requirement_id,
            path=row.get("owner_path"),
            symbol=row.get("owner_symbol") or row.get("symbol"),
        )

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
            errors.append(
                f"PR355_NXF_PERMANENT_NF_FORBIDDEN:{row.get('requirement_id')}"
            )

    packs = json.loads(
        (ROOT / "config/pr355_marketpacks.json").read_text(encoding="utf-8")
    )
    if set(packs.get("packages", {})) != set(MARKETPACKS):
        errors.append("PR355_MARKETPACK_SET_MISMATCH")
    if set(packs.get("allowed_evidence_statuses", ())) != ALLOWED_EVIDENCE_STATUSES:
        errors.append("PR355_EVIDENCE_STATUS_VOCABULARY_MISMATCH")
    for pack_id, row in packs.get("packages", {}).items():
        if row.get("state") != "DISABLED" or row.get("live") is not False:
            errors.append(f"PR355_MARKETPACK_NOT_DISABLED:{pack_id}")
        if row.get("authorized_live") is not False:
            errors.append(f"PR355_MARKETPACK_LIVE_AUTHORITY_UNSAFE:{pack_id}")
        if row.get("evidence_status") not in ALLOWED_EVIDENCE_STATUSES:
            errors.append(f"PR355_MARKETPACK_EVIDENCE_STATUS_INVALID:{pack_id}")
        if row.get("external_qualification") != "BLOCKED_EXTERNAL":
            errors.append(f"PR355_MARKETPACK_EXTERNAL_STATUS_INVALID:{pack_id}")
    boundary = packs.get("effect_boundary", {})
    if not boundary or any(value is not False for value in boundary.values()):
        errors.append("PR355_EFFECT_BOUNDARY_UNSAFE")
    if packs.get("marginfi") != "PAUSED":
        errors.append("PR355_MARGINFI_NOT_PAUSED")
    if packs.get("slumlord_low_capital_requirement") != "REQUIRED":
        errors.append("PR355_SLUMLORD_REQUIREMENT_DRIFT")
    if packs.get("source_copy_performed") is not False:
        errors.append("PR355_SOURCE_COPY_FLAG_UNSAFE")

    bindings = all_marketpack_bindings()
    if len(bindings) != 9 or {item.pack_id for item in bindings} != set(MARKETPACKS):
        errors.append("PR355_MARKETPACK_BINDING_SET_MISMATCH")
    for binding in bindings:
        if (
            binding.state != "DISABLED"
            or binding.live_enabled
            or binding.signer_access
            or binding.submission_access
            or binding.remote_mutation
        ):
            errors.append(f"PR355_MARKETPACK_BINDING_UNSAFE:{binding.pack_id}")
        if not binding.blockers:
            errors.append(f"PR355_MARKETPACK_BLOCKER_MISSING:{binding.pack_id}")
        for owner in (
            binding.instrument_owner,
            binding.data_owner,
            binding.rights_owner,
            binding.target_owner,
            binding.evidence_owner,
        ):
            module_name, symbol = owner.split(":", 1)
            module = importlib.import_module(module_name)
            if not callable(getattr(module, symbol, None)):
                errors.append(
                    f"PR355_MARKETPACK_BOUND_OWNER_MISSING:{binding.pack_id}:{owner}"
                )

    experiments = json.loads(
        (ROOT / "config/pr355_experiments.json").read_text(encoding="utf-8")
    )
    rows = experiments.get("rows", [])
    expected_experiments = [f"NXE-{index:02d}" for index in range(1, 27)]
    if [row.get("id") for row in rows] != expected_experiments:
        errors.append("PR355_EXPERIMENT_REGISTRY_MISMATCH")
    if experiments.get("preregistered") is not True:
        errors.append("PR355_EXPERIMENTS_NOT_PREREGISTERED")
    if experiments.get("frozen_before_external_evaluation") is not True:
        errors.append("PR355_EXPERIMENTS_NOT_FROZEN")
    for row in rows:
        experiment_id = str(row.get("id", "UNKNOWN"))
        if row.get("execution_right") is not False:
            errors.append(f"PR355_EXPERIMENT_EXECUTION_RIGHT_UNSAFE:{experiment_id}")
        for field in (
            "target",
            "horizon",
            "control",
            "primary_metric",
            "assumptions",
            "reject_condition",
            "missing_and_censored",
        ):
            value = row.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"PR355_EXPERIMENT_FIELD_MISSING:{experiment_id}:{field}")
        if str(row.get("target", "")).startswith("DECLARED_"):
            errors.append(f"PR355_EXPERIMENT_TARGET_PLACEHOLDER:{experiment_id}")
        if str(row.get("horizon", "")).startswith("DECLARED_"):
            errors.append(f"PR355_EXPERIMENT_HORIZON_PLACEHOLDER:{experiment_id}")
        if not isinstance(row.get("costs"), dict):
            errors.append(f"PR355_EXPERIMENT_COSTS_NOT_EXPLICIT:{experiment_id}")
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

    incident = json.loads(
        (ROOT / "docs/mechanism_discovery/pr355_incident_corpus.json").read_text(
            encoding="utf-8"
        )
    )
    incident_rows = incident.get("rows", [])
    if not incident_rows:
        errors.append("PR355_INCIDENT_CORPUS_EMPTY")
    for row in incident_rows:
        if row.get("source_status") != "REFERENCE_ONLY":
            errors.append("PR355_INCIDENT_NOT_REFERENCE_ONLY")
        if row.get("production_adapter_allowed") is not False:
            errors.append("PR355_INCIDENT_PRODUCTION_ADAPTER_UNSAFE")
        if row.get("quarantine_required") is not True:
            errors.append("PR355_INCIDENT_QUARANTINE_MISSING")

    rollback = json.loads(
        (ROOT / "config/pr355_rollback.json").read_text(encoding="utf-8")
    )
    if rollback.get("config_first") is not True or len(rollback.get("steps", [])) != 5:
        errors.append("PR355_ROLLBACK_PLAN_INCOMPLETE")
    for field in (
        "signing_required",
        "fund_recovery_required",
        "remote_transaction_reversal_required",
    ):
        if rollback.get(field) is not False:
            errors.append(f"PR355_ROLLBACK_EFFECT_UNSAFE:{field}")
    if not all(row.get("preserve_evidence") is True for row in rollback.get("steps", [])):
        errors.append("PR355_ROLLBACK_APPEND_ONLY_EVIDENCE_MISSING")

    completion = json.loads(
        (ROOT / "release_artifacts/pr355/completion_audit.json").read_text(
            encoding="utf-8"
        )
    )
    sections = completion.get("sections", [])
    if [row.get("section") for row in sections] != [str(index) for index in range(19)]:
        errors.append("PR355_COMPLETION_AUDIT_SECTION_GAP")
    if any(completion.get("external_nonclaims", {}).values()):
        errors.append("PR355_COMPLETION_AUDIT_OVERCLAIM")

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
        "select_training_labels_as_of",
        '"label_leakage": False',
    ):
        if required not in evo09:
            errors.append(f"PR355_EVO09_SEMANTIC_REPAIR_MISSING:{required}")

    telemetry = build_bot_operation_feature_frame(
        (
            {
                "operation_id": "matured",
                "decision_at": 1,
                "disposition": "PAPER_OBSERVED",
                "predicted_net_atoms": 1,
                "realized_net_atoms": 2,
                "label_available_at": 5,
            },
            {
                "operation_id": "future",
                "decision_at": 1,
                "disposition": "PAPER_OBSERVED",
                "predicted_net_atoms": 1,
                "realized_net_atoms": 3,
                "label_available_at": 20,
            },
            {
                "operation_id": "censored",
                "decision_at": 1,
                "disposition": "FAILED",
                "predicted_net_atoms": 1,
                "realized_net_atoms": 4,
                "label_available_at": 4,
                "censored": True,
            },
            {
                "operation_id": "missing",
                "decision_at": 1,
                "disposition": "NO_TRADE",
                "predicted_net_atoms": 1,
            },
        )
    )
    training = select_training_labels_as_of(
        telemetry.payload["rows"],
        training_cutoff=10,
    )
    if training.payload["selected_count"] != 1:
        errors.append("PR355_EVO09_TRAINING_CUTOFF_BROKEN")
    if training.payload["future_labels_excluded"] != 1:
        errors.append("PR355_EVO09_FUTURE_LABEL_NOT_EXCLUDED")
    if training.payload["censored_preserved"] != 1:
        errors.append("PR355_EVO09_CENSORED_NOT_PRESERVED")
    if training.payload["missing_preserved"] != 1:
        errors.append("PR355_EVO09_MISSING_NOT_PRESERVED")

    boros = run_boros_fixture_vertical()
    if boros.get("verdict") != "BLOCKED_EXTERNAL":
        errors.append("PR355_BOROS_FAKE_QUALIFICATION")
    if (
        boros.get("fixture_tested") is not True
        or boros.get("synthetic_pass") is not False
    ):
        errors.append("PR355_BOROS_FIXTURE_STATUS_INVALID")
    if int(boros["forecast_written_at"]) >= int(boros["mature_label_available_at"]):
        errors.append("PR355_BOROS_TEMPORAL_LEAKAGE")
    if boros.get("bounded_ingest") is not True or int(boros.get("raw_record_count", 0)) < 5:
        errors.append("PR355_BOROS_BOUNDED_INGEST_MISSING")
    model_comparison = boros.get("model_comparison", {})
    for key in (
        "simple_baseline_mae_atoms",
        "local_only_mae_atoms",
        "pooled_markets_mae_atoms",
        "mechanism_transfer_mae_atoms",
        "negative_transfer",
    ):
        if key not in model_comparison:
            errors.append(f"PR355_BOROS_MODEL_COMPARATOR_MISSING:{key}")
    split = boros.get("purged_walk_forward", {})
    if int(split.get("train_count", 0)) < 1 or int(split.get("holdout_count", 0)) < 1:
        errors.append("PR355_BOROS_PURGED_SPLIT_MISSING")
    if not boros.get("blind_spots"):
        errors.append("PR355_BOROS_BLIND_SPOTS_MISSING")
    if "fdr" not in boros or "calibration" not in boros or "source_value" not in boros:
        errors.append("PR355_BOROS_RESEARCH_PROTOCOL_INCOMPLETE")

    evidence = json.loads(
        (ROOT / "release_artifacts/pr355/current-head-evidence.json").read_text(
            encoding="utf-8"
        )
    )
    claims = evidence.get("claims", {})
    if any(
        claims.get(field) is not False
        for field in (
            "qualified",
            "authorized_live",
            "production_ready",
            "profitability",
        )
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
        "marketpack_binding_count": len(bindings),
        "experiment_count": len(rows),
        "owner_total": len(all_ids),
        "completion_section_count": len(sections),
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
