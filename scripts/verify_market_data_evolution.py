#!/usr/bin/env python3
"""Verifier for the MEGA Market Data Layer Evolution contract closure."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

from src.market_data_evolution import (
    InstrumentIdentity,
    NormalizedObservation,
    SourceManifest,
    all_cross_market_packs,
    materialize_state,
    research_effect_boundary,
)
from src.mechanism_discovery.manifest import FUNCTION_COUNT as PR354_FUNCTION_COUNT
from src.mechanism_discovery.manifest import NF_IDS as PR354_NF_IDS

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/market_data_evolution.json"
EVIDENCE = ROOT / "release_artifacts/market_data_evolution/evidence.json"

FORBIDDEN_TOKENS = (
    "import requests",
    "from requests",
    "import aiohttp",
    "from aiohttp",
    "import httpx",
    "from httpx",
    "send_transaction(",
    "submit_transaction(",
    "private_key",
    "secret_key",
    "isolated_signer",
    "src.submission",
    "src.live_boundary",
)


def _import_ref(ref: str) -> bool:
    module_name, symbol = ref.split(":", 1)
    module = importlib.import_module(module_name)
    return callable(getattr(module, symbol, None))


def verify() -> dict[str, object]:
    errors: list[str] = []
    config = json.loads(CONFIG.read_text(encoding="utf-8"))

    if config.get("counts") != {
        "layers": 9,
        "experiments": 8,
        "milestones": 8,
        "sources": 23,
        "cross_market_packs": 3,
    }:
        errors.append("MDE_COUNT_MISMATCH")

    if [row.get("id") for row in config.get("layers", [])] != [
        f"L{i}" for i in range(9)
    ]:
        errors.append("MDE_LAYER_SET_MISMATCH")
    if [row.get("id") for row in config.get("experiments", [])] != [
        f"E{i:02d}" for i in range(1, 9)
    ]:
        errors.append("MDE_EXPERIMENT_SET_MISMATCH")
    if [row.get("id") for row in config.get("milestones", [])] != [
        f"D{i:02d}" for i in range(1, 9)
    ]:
        errors.append("MDE_MILESTONE_SET_MISMATCH")
    if [row.get("id") for row in config.get("sources", [])] != [
        f"S{i:02d}" for i in range(1, 24)
    ]:
        errors.append("MDE_SOURCE_SET_MISMATCH")

    for row in config.get("layers", []):
        refs = [row.get("child_owner"), *row.get("canonical_reuse", [])]
        if row.get("secondary_child"):
            refs.append(row["secondary_child"])
        for ref in refs:
            if not isinstance(ref, str):
                errors.append(f"MDE_OWNER_REF_MISSING:{row.get('id')}")
                continue
            try:
                if not _import_ref(ref):
                    errors.append(f"MDE_OWNER_NOT_CALLABLE:{row.get('id')}:{ref}")
            except Exception as exc:
                errors.append(f"MDE_OWNER_IMPORT_FAIL:{row.get('id')}:{ref}:{exc}")

    if PR354_FUNCTION_COUNT != 96 or PR354_NF_IDS != tuple(range(1089, 1185)):
        errors.append("MDE_PR354_PREDECESSOR_NOT_CLOSED")
    if config.get("anti_duplication", {}).get("pr354_document") != (
        "SATISFIED_BY_MERGED_GITHUB_PR_533"
    ):
        errors.append("MDE_PR354_REUSE_DISPOSITION_MISSING")

    if any(config.get("effect_boundary", {}).values()):
        errors.append("MDE_EFFECT_BOUNDARY_UNSAFE")
    if any(research_effect_boundary().values()):
        errors.append("MDE_CODE_EFFECT_BOUNDARY_UNSAFE")

    packs = all_cross_market_packs()
    if len(packs) != 3:
        errors.append("MDE_PACK_COUNT_MISMATCH")
    source_ids = {row["id"] for row in config.get("sources", [])}
    for pack in packs:
        if pack.state != "DISABLED" or pack.evidence_status != "BLOCKED_EXTERNAL":
            errors.append(f"MDE_PACK_NOT_BLOCKED:{pack.pack_id}")
        if set(pack.source_ids) - source_ids:
            errors.append(f"MDE_PACK_UNKNOWN_SOURCE:{pack.pack_id}")
        if any(
            (
                pack.live_enabled,
                pack.signing_allowed,
                pack.submission_allowed,
                pack.funds_movement_allowed,
            )
        ):
            errors.append(f"MDE_PACK_EFFECT_UNSAFE:{pack.pack_id}")

    for row in config.get("sources", []):
        if (
            row.get("reuse_mode") != "REFERENCE_ONLY"
            or row.get("license_status") != "REVERIFY"
            or row.get("entitlement_status") != "REVERIFY"
            or row.get("external_fetch_performed") is not False
        ):
            errors.append(f"MDE_SOURCE_OVERCLAIM:{row.get('id')}")

    for row in config.get("experiments", []):
        if row.get("execution_right") is not False:
            errors.append(f"MDE_EXPERIMENT_EXECUTION_RIGHT:{row.get('id')}")
        if "QUALIFIED" in str(row.get("status", "")):
            errors.append(f"MDE_EXPERIMENT_FALSE_QUALIFICATION:{row.get('id')}")
        if not row.get("targets") or not row.get("horizons") or not row.get("reject"):
            errors.append(f"MDE_EXPERIMENT_PREREG_INCOMPLETE:{row.get('id')}")

    required_baselines = {
        "price_only",
        "price_plus_onchain",
        "price_plus_onchain_plus_derivatives",
        "target_market_only",
        "pooled_markets",
        "transferred_adapters",
    }
    if set(config.get("evaluation", {}).get("baselines", [])) != required_baselines:
        errors.append("MDE_BASELINE_SET_MISMATCH")
    if len(config.get("evaluation", {}).get("required_metrics", [])) != 10:
        errors.append("MDE_REQUIRED_METRIC_COUNT_MISMATCH")
    if len(config.get("evaluation", {}).get("required_splits", [])) != 5:
        errors.append("MDE_REQUIRED_SPLIT_COUNT_MISMATCH")
    if len(config.get("evaluation", {}).get("forbidden", [])) != 7:
        errors.append("MDE_FORBIDDEN_EVALUATION_COUNT_MISMATCH")
    if len(config.get("document_boundaries", [])) != 8:
        errors.append("MDE_DOCUMENT_BOUNDARY_COUNT_MISMATCH")
    if len(config.get("observation_contract_conditionally_required", [])) != 7:
        errors.append("MDE_OBSERVATION_CONDITIONAL_FIELD_COUNT_MISMATCH")
    if not config.get("availability_rule") or not config.get("forecast_note"):
        errors.append("MDE_DOCUMENT_SEMANTIC_NOTES_MISSING")
    hint = config.get("document_hint", {})
    if "Graph Continual Learning" not in str(hint.get("topic", "")):
        errors.append("MDE_DOCUMENT_HINT_MISSING")

    source_root = ROOT / "src/market_data_evolution"
    for path in source_root.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_TOKENS:
            if token in source:
                errors.append(f"MDE_FORBIDDEN_EFFECT_TOKEN:{path.name}:{token}")

    # Deterministic fixture: contract correctness only, never market qualification.
    SourceManifest(
        source_id="fixture",
        title="fixture",
        source_family="fixture",
        licence_status="REVERIFY",
        entitlement_status="REVERIFY",
        endpoint_quota_units=0,
        data_delay_ms=0,
        retention_class="reference-only",
        source_version="v1",
    )
    InstrumentIdentity(
        instrument_id="fixture-instrument",
        ticker="FIX",
        underlying_id="underlying",
        issuer_id="issuer",
        venue="venue",
        chain="research",
        settlement_asset="usd",
        maturity="none",
        multiplier_num=1,
        multiplier_den=1,
        session_id="always",
        licence_id="fixture-license",
        claim_rights_hash="a" * 64,
    )
    state, replay = materialize_state(
        (
            NormalizedObservation(
                observation_id="obs",
                source_id="fixture",
                instrument_id="fixture-instrument",
                value_atoms=1,
                event_at=1,
                first_seen_at=2,
                available_at=3,
                revision_id=1,
                effective_from=1,
                effective_until=None,
                instrument_version="v1",
                raw_payload_hash="b" * 64,
            ),
        ),
        cutoff=3,
    )
    if state.state_hash != replay.state_hash or replay.latest_state_read:
        errors.append("MDE_REPLAY_FIXTURE_INVALID")

    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    claims = evidence.get("claims", {})
    for field in (
        "empirical_market_campaign_complete",
        "external_sources_qualified",
        "production_ready",
        "live_authorized",
        "profitability",
    ):
        if claims.get(field) is not False:
            errors.append(f"MDE_EVIDENCE_OVERCLAIM:{field}")

    return {
        "accepted": not errors,
        "errors": errors,
        "layer_count": len(config.get("layers", [])),
        "experiment_count": len(config.get("experiments", [])),
        "milestone_count": len(config.get("milestones", [])),
        "source_count": len(config.get("sources", [])),
        "pack_count": len(packs),
        "pr354_function_count": PR354_FUNCTION_COUNT,
        "live_enabled": False,
        "external_campaign_complete": False,
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
