#!/usr/bin/env python3
"""Structural and semantic verifier for roadmap PR-358."""

from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path
from typing import Any

from src.research.pr358_contracts import CONTRACT_SCHEMAS, EFFECT_BOUNDARY, PR358ContractError, contract_type
from src.research.pr358_core import (
    CacheEntry,
    CorrelationObservation,
    ExperimentNode,
    apply_relation_multiple_testing_control,
    bind_distribution_entitlement,
    bind_product_query_budget,
    classify_cache_reuse,
    compute_incremental_invalidation,
    compute_node_content_key,
    define_experiment_dag,
    define_market_science_service,
    materialize_joined_research_view,
)
from src.research.pr358_integrated import run_pr358_integrated_vertical

ROOT = Path(__file__).resolve().parents[1]
BANNED_IMPORT_PREFIXES = (
    "src.submission",
    "src.execution.live_control",
    "src.execution.senders",
    "src.providers.marginfi",
)
BANNED_NETWORK_MODULES = {"requests", "httpx", "urllib", "socket", "aiohttp"}


def _load(path: str) -> Any:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _scan_imports(path: Path) -> list[str]:
    errors: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        for name in names:
            if name.startswith(BANNED_IMPORT_PREFIXES):
                errors.append(f"PR358_BANNED_IMPORT:{path.name}:{name}")
            if name.split(".", 1)[0] in BANNED_NETWORK_MODULES:
                errors.append(f"PR358_NETWORK_IMPORT:{path.name}:{name}")
    return errors


def _fixture_observation(*, bucket: str, frame: str, value: int, available_at: int) -> CorrelationObservation:
    return CorrelationObservation(
        frame_id=frame,
        entity_id="entity",
        instrument_id="FIX/USDC",
        bucket_id=bucket,
        feature_name=f"feature-{bucket}",
        value=value,
        unit="unit",
        event_at=available_at - 3,
        published_at=available_at - 2,
        received_at=available_at - 1,
        available_at=available_at,
        revision="v1",
        source_id="fixture",
        source_generation="1",
        synthetic=True,
        privacy_class="PUBLIC_SYNTHETIC",
        distribution_allowed=True,
        entitlement_scope="research",
        provenance_hash="a" * 64,
    )


def verify() -> dict[str, object]:
    errors: list[str] = []
    owner = _load("config/pr358_owner_map.json")
    registry = _load("config/pr358_registry.json")
    rights = _load("config/pr358_source_rights.json")
    audit = _load("release_artifacts/pr358/completion_audit.json")
    evidence = _load("release_artifacts/pr358/current-head-evidence.json")
    pr357 = _load("config/pr357_owner_map.json")

    rows = owner.get("requirements", [])
    expected_counts = {
        "requirements": 288,
        "packages": 36,
        "typed_contracts": 24,
        "not_run": 0,
    }
    for key, expected in expected_counts.items():
        if owner.get("counts", {}).get(key) != expected:
            errors.append(f"PR358_OWNER_COUNT:{key}")
    if len(rows) != 288:
        errors.append("PR358_REQUIREMENT_COUNT")
    if len({row.get("id") for row in rows}) != 288:
        errors.append("PR358_REQUIREMENT_ID_UNIQUE")
    if len({row.get("symbol") for row in rows}) != 288:
        errors.append("PR358_REQUIREMENT_SYMBOL_UNIQUE")
    if owner.get("duplicate_authorities"):
        errors.append("PR358_DUPLICATE_AUTHORITY")
    if any(owner.get("effect_boundary", {}).values()):
        errors.append("PR358_OWNER_EFFECT_BOUNDARY")
    if owner.get("roadmap_code_research_scope_complete") is not True:
        errors.append("PR358_OWNER_SCOPE_INCOMPLETE")
    if owner.get("external_qualification_complete") is not False:
        errors.append("PR358_EXTERNAL_OVERCLAIM")
    if owner.get("marginfi") != "PAUSED" or owner.get("slumlord_low_capital_requirement") != "REQUIRED":
        errors.append("PR358_PREDECESSOR_POLICY_DRIFT")

    allowed = {"SATISFIED_BY_EXISTING", "SPECIALIZE_EXISTING", "NEW_OUTCOME", "BLOCKED_EXTERNAL"}
    residual_calls = 0
    runtime_blocked = 0
    for row in rows:
        requirement_id = str(row["id"])
        symbol_name = str(row["symbol"])
        if row.get("disposition") not in allowed:
            errors.append(f"PR358_BAD_DISPOSITION:{requirement_id}")
        if row.get("status") != "CONTRACT_IMPLEMENTED":
            errors.append(f"PR358_NOT_IMPLEMENTED:{requirement_id}")
        module_name = str(row["owner"])[:-3].replace("/", ".")
        module = importlib.import_module(module_name)
        symbol = getattr(module, symbol_name, None)
        if not callable(symbol):
            errors.append(f"PR358_SYMBOL_MISSING:{requirement_id}:{symbol_name}")
            continue
        if module_name == "src.research.pr358_requirements":
            residual_calls += 1
            result = symbol()
            if result.get("execution_right") is not False:
                errors.append(f"PR358_ADAPTER_EXECUTION_RIGHT:{requirement_id}")
            if result.get("status") == "BLOCKED_EXTERNAL":
                runtime_blocked += 1
            elif result.get("status") != "CONTRACT_IMPLEMENTED":
                errors.append(f"PR358_ADAPTER_STATUS:{requirement_id}")

    if len(CONTRACT_SCHEMAS) != 24:
        errors.append("PR358_CONTRACT_SCHEMA_COUNT")
    for name in CONTRACT_SCHEMAS:
        if contract_type(name).__name__ != name:
            errors.append(f"PR358_CONTRACT_TYPE:{name}")

    registry_expected = {
        "packages": 36,
        "hypotheses": 72,
        "challenges": 28,
        "data_buckets": 12,
        "technology_buckets": 14,
        "vertical_templates": 16,
        "sources": 53,
    }
    for key, expected in registry_expected.items():
        if len(registry.get(key, [])) != expected:
            errors.append(f"PR358_REGISTRY_COUNT:{key}")
    tech02 = next((row for row in registry.get("technology_buckets", []) if row.get("id") == "TECH-02"), None)
    if not tech02 or tech02.get("name") != "UNSPECIFIED_IN_PROMPT":
        errors.append("PR358_TECH02_SOURCE_GAP_NOT_PRESERVED")
    if any(item.get("dependency_added") for item in registry.get("sources", [])):
        errors.append("PR358_UNREVIEWED_RUNTIME_DEPENDENCY")
    if len(rights.get("sources", [])) != 53:
        errors.append("PR358_RIGHTS_LEDGER_COUNT")
    if any(item.get("selected_for_runtime_dependency") for item in rights.get("sources", [])):
        errors.append("PR358_EXTERNAL_RUNTIME_DEPENDENCY_SELECTED")
    if rights.get("fixture_policy", {}).get("redistribution_allowed") is not True:
        errors.append("PR358_FIXTURE_RIGHTS")

    if pr357.get("roadmap_code_research_scope_complete") is not True:
        errors.append("PR358_PR357_DEPENDENCY_INCOMPLETE")
    if pr357.get("external_qualification_complete") is not False:
        errors.append("PR358_PR357_EXTERNAL_OVERCLAIM")
    if evidence.get("observed_main_at_start") != "dd40b9c8f3e95cedb94a630a0a0c83e02a73a146":
        errors.append("PR358_BASE_SHA_MISMATCH")
    if evidence.get("pr357_merge_sha") != "dd40b9c8f3e95cedb94a630a0a0c83e02a73a146":
        errors.append("PR358_PR357_DEPENDENCY_PROOF")
    if evidence.get("agents_md_at_repo_root") != "NOT_FOUND":
        errors.append("PR358_AGENTS_TRUTH")
    if audit.get("implementation_scope_complete") is not True:
        errors.append("PR358_AUDIT_SCOPE_INCOMPLETE")
    if audit.get("external_qualification_complete") is not False:
        errors.append("PR358_AUDIT_EXTERNAL_OVERCLAIM")
    if any(EFFECT_BOUNDARY.values()):
        errors.append("PR358_STATIC_EFFECT_BOUNDARY")

    for path in (
        ROOT / "src/research/pr358_contracts.py",
        ROOT / "src/research/pr358_core.py",
        ROOT / "src/research/pr358_requirements.py",
        ROOT / "src/research/pr358_integrated.py",
    ):
        errors.extend(_scan_imports(path))

    common = {
        "node_kind": "STAT_TEST",
        "symbol_version": "v1",
        "params_hash": "b" * 64,
        "upstream_artifact_hashes": ("c" * 64,),
        "data_snapshot_ids": ("d" * 64,),
        "tool_versions": ("stdlib",),
        "environment_lock_hash": "e" * 64,
        "seed": 358,
        "time_cutoff": 10,
        "license_generation": "l1",
        "entitlement_generation": "e1",
        "semantic_version": "s1",
    }
    node_a = ExperimentNode(node_id="a", dependencies=(), **common)
    node_b = ExperimentNode(node_id="b", dependencies=("a",), **common)
    key = compute_node_content_key(node_a)
    if key != compute_node_content_key(node_a):
        errors.append("PR358_NODE_KEY_NONDETERMINISTIC")
    define_experiment_dag((node_a, node_b))
    if compute_incremental_invalidation((node_a, node_b), ("a",)) != ("a", "b"):
        errors.append("PR358_INVALIDATION_NOT_PRECISE")
    entry = CacheEntry(key, "f" * 64, 10, "l1", "e1", "r1", "d1", "s1")
    exact = classify_cache_reuse(entry, expected_content_key=key, time_cutoff=10, license_generation="l1", entitlement_generation="e1", source_revision="r1", deployment_generation="d1", semantic_version="s1")
    changed = classify_cache_reuse(entry, expected_content_key=key, time_cutoff=10, license_generation="l1", entitlement_generation="e1", source_revision="r2", deployment_generation="d1", semantic_version="s1")
    if exact != "REUSE_EXACT" or changed != "INVALIDATE":
        errors.append("PR358_CACHE_PROVENANCE")
    try:
        cyc_a = ExperimentNode(node_id="a", dependencies=("b",), **common)
        cyc_b = ExperimentNode(node_id="b", dependencies=("a",), **common)
        define_experiment_dag((cyc_a, cyc_b))
        errors.append("PR358_CYCLE_ACCEPTED")
    except PR358ContractError:
        pass

    obs_a = _fixture_observation(bucket="DB-01", frame="a", value=1, available_at=10)
    obs_b = _fixture_observation(bucket="DB-03", frame="b", value=2, available_at=11)
    joined = materialize_joined_research_view((obs_a, obs_b), decision_time=11)
    if len(joined["rows"]) != 2:
        errors.append("PR358_JOIN_MISSING_ROWS")
    try:
        future = _fixture_observation(bucket="DB-05", frame="future", value=3, available_at=12)
        materialize_joined_research_view((obs_a, future), decision_time=11)
        errors.append("PR358_LOOKAHEAD_ACCEPTED")
    except PR358ContractError:
        pass
    if apply_relation_multiple_testing_control({"good": 10_000, "bad": 900_000}, alpha_ppm=50_000) != ("good",):
        errors.append("PR358_FDR_IDENTITY")

    service = define_market_science_service(
        service_id="verify-service",
        service_family="evidence",
        input_schema="i1",
        output_schema="o1",
        evidence_tier="fixture",
        max_age=5,
        access_scope="research",
        distribution_rights=True,
        privacy_class="PUBLIC_SYNTHETIC",
        query_budget=1,
        redaction_policy="public",
        price_model="simulated",
        prohibited_use=("live",),
    )
    if not bind_distribution_entitlement(service, requested_scope="research"):
        errors.append("PR358_ENTITLEMENT_REJECTED")
    try:
        bind_product_query_budget(service, used_queries=1)
        errors.append("PR358_QUERY_BUDGET_NOT_BLOCKED")
    except PR358ContractError:
        pass

    first = run_pr358_integrated_vertical()
    second = run_pr358_integrated_vertical()
    if first["integrated_receipt_hash"] != second["integrated_receipt_hash"]:
        errors.append("PR358_VERTICAL_NONDETERMINISTIC")
    if first.get("status") not in {"SUPPORTED_RESEARCH_ONLY", "REJECTED_WITH_EVIDENCE"}:
        errors.append("PR358_VERTICAL_STATUS")
    if first.get("joined_bucket_count", 0) < 3:
        errors.append("PR358_VERTICAL_BUCKET_COVERAGE")
    if first["cache"]["exact"] != "REUSE_EXACT" or first["cache"]["revision_change"] != "INVALIDATE":
        errors.append("PR358_VERTICAL_CACHE")
    if any(first["effect_boundary"].values()):
        errors.append("PR358_VERTICAL_EFFECT_BOUNDARY")
    for key in ("execution_right", "production_ready", "live_enabled", "customer_billing", "external_service_activation"):
        if first.get(key) is not False:
            errors.append(f"PR358_VERTICAL_FORBIDDEN_EFFECT:{key}")

    return {
        "accepted": not errors,
        "errors": errors,
        "requirements": len(rows),
        "packages": len(registry.get("packages", [])),
        "typed_contracts": len(CONTRACT_SCHEMAS),
        "hypotheses": len(registry.get("hypotheses", [])),
        "challenges": len(registry.get("challenges", [])),
        "data_buckets": len(registry.get("data_buckets", [])),
        "technology_buckets": len(registry.get("technology_buckets", [])),
        "vertical_templates": len(registry.get("vertical_templates", [])),
        "residual_adapter_calls": residual_calls,
        "runtime_blocked_external_without_evidence": runtime_blocked,
        "integrated_receipt_hash": first["integrated_receipt_hash"],
        "external_qualification_complete": False,
        "production_ready": False,
        "live_enabled": False,
        "execution_right": False,
        "customer_billing": False,
    }


def main() -> int:
    result = verify()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
