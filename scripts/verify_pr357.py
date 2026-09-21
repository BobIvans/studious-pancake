#!/usr/bin/env python3
"""Structural and semantic verifier for roadmap PR-357."""

from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path
from typing import Any

from src.research.pr357_contracts import (
    CONTRACT_SCHEMAS,
    EFFECT_BOUNDARY,
    PR357ContractError,
    contract_type,
)
from src.research.pr357_core import (
    InformationActionSpec,
    LifecycleState,
    ObservationClock,
    PriorCandidate,
    block_decision_without_safety_info,
    compute_evidence_age_vector,
    define_market_belief_state,
    estimate_evpi,
    estimate_evsi,
    generate_joint_predictive_distribution,
    record_lifecycle_transition,
    replay_lifecycle_history,
    reserve_safety_information_budget,
)
from src.research.pr357_integrated import run_pr357_integrated_vertical

ROOT = Path(__file__).resolve().parents[1]
BANNED_IMPORT_PREFIXES = (
    "src.submission",
    "src.release_gate",
    "src.execution.senders",
    "src.execution.live_control",
    "src.providers.marginfi",
)


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
                errors.append(f"PR357_BANNED_IMPORT:{path.name}:{name}")
    return errors


def verify() -> dict[str, object]:
    errors: list[str] = []
    owner = _load("config/pr357_owner_map.json")
    registry = _load("config/pr357_registry.json")
    evidence = _load("release_artifacts/pr357/current-head-evidence.json")
    audit = _load("release_artifacts/pr357/completion_audit.json")

    rows = owner.get("requirements", [])
    if len(rows) != 384:
        errors.append("PR357_REQUIREMENT_COUNT")
    if owner.get("counts", {}).get("packages") != 48:
        errors.append("PR357_PACKAGE_COUNT")
    if owner.get("counts", {}).get("typed_contracts") != 40:
        errors.append("PR357_CONTRACT_COUNT")
    if owner.get("counts", {}).get("not_run") != 0:
        errors.append("PR357_NOT_RUN_REMAINS")
    if owner.get("duplicate_authorities"):
        errors.append("PR357_DUPLICATE_AUTHORITY")
    if owner.get("roadmap_code_research_scope_complete") is not True:
        errors.append("PR357_SCOPE_INCOMPLETE")
    if owner.get("external_qualification_complete") is not False:
        errors.append("PR357_EXTERNAL_OVERCLAIM")
    if any(owner.get("effect_boundary", {}).values()):
        errors.append("PR357_EFFECT_BOUNDARY_UNSAFE")
    if owner.get("marginfi") != "PAUSED":
        errors.append("PR357_MARGINFI_NOT_PAUSED")
    if owner.get("slumlord_low_capital_requirement") != "REQUIRED":
        errors.append("PR357_SLUMLORD_NOT_REQUIRED")

    seen_ids: set[str] = set()
    seen_symbols: set[str] = set()
    residual_calls = 0
    blocked_runtime = 0
    for row in rows:
        requirement_id = str(row.get("id"))
        symbol_name = str(row.get("symbol"))
        if requirement_id in seen_ids:
            errors.append(f"PR357_DUPLICATE_REQUIREMENT:{requirement_id}")
        seen_ids.add(requirement_id)
        if symbol_name in seen_symbols:
            errors.append(f"PR357_DUPLICATE_SYMBOL:{symbol_name}")
        seen_symbols.add(symbol_name)
        if row.get("disposition") not in {
            "SATISFIED_BY_EXISTING",
            "SPECIALIZE_EXISTING",
            "NEW_OUTCOME",
            "BLOCKED_EXTERNAL",
        }:
            errors.append(f"PR357_BAD_DISPOSITION:{requirement_id}")
        if row.get("status") != "CONTRACT_IMPLEMENTED":
            errors.append(f"PR357_NOT_IMPLEMENTED:{requirement_id}")

        module_name = str(row["owner"])[:-3].replace("/", ".")
        module = importlib.import_module(module_name)
        symbol = getattr(module, symbol_name, None)
        if not callable(symbol):
            errors.append(f"PR357_SYMBOL_MISSING:{requirement_id}:{symbol_name}")
            continue
        if module_name == "src.research.pr357_requirements":
            residual_calls += 1
            result = symbol()
            if result.get("execution_right") is not False:
                errors.append(f"PR357_RESIDUAL_EXECUTION_RIGHT:{requirement_id}")
            if result.get("status") == "BLOCKED_EXTERNAL":
                blocked_runtime += 1
            elif result.get("status") != "CONTRACT_IMPLEMENTED":
                errors.append(f"PR357_RESIDUAL_STATUS:{requirement_id}")

    if len(CONTRACT_SCHEMAS) != 40:
        errors.append("PR357_NORMATIVE_CONTRACT_SCHEMA_COUNT")
    for name in CONTRACT_SCHEMAS:
        cls = contract_type(name)
        if cls.__name__ != name:
            errors.append(f"PR357_CONTRACT_TYPE_MISSING:{name}")

    for path in (
        ROOT / "src/research/pr357_contracts.py",
        ROOT / "src/research/pr357_core.py",
        ROOT / "src/research/pr357_requirements.py",
        ROOT / "src/research/pr357_integrated.py",
    ):
        errors.extend(_scan_imports(path))

    clock = ObservationClock(1, 2, 3, 4, "fixture", "v1")
    try:
        define_market_belief_state(
            belief_id="lookahead",
            decision_time=3,
            observed={"x": 1},
            posterior_mean={"x": 1},
            covariance={"x": {"x": 1}},
            missingness_mask={"x": False},
            source_clocks={"x": clock},
            valid_until=4,
        )
        errors.append("PR357_LOOKAHEAD_NOT_REJECTED")
    except PR357ContractError:
        pass

    try:
        define_market_belief_state(
            belief_id="missing-clock",
            decision_time=10,
            observed={"x": 1},
            posterior_mean={"x": 1},
            covariance={"x": {"x": 1}},
            missingness_mask={"x": False},
            source_clocks={},
            valid_until=11,
        )
        errors.append("PR357_OBSERVED_CLOCK_NOT_REQUIRED")
    except PR357ContractError:
        pass

    same_time_first = record_lifecycle_transition(
        strategy_id="same-time",
        previous_state=LifecycleState.RESEARCH_ONLY,
        next_state=LifecycleState.OBSERVING,
        decision_time=9,
        reason="first append",
        evidence_refs=("a",),
    )
    same_time_second = record_lifecycle_transition(
        strategy_id="same-time",
        previous_state=LifecycleState.OBSERVING,
        next_state=LifecycleState.REQUALIFICATION_DUE,
        decision_time=9,
        reason="second append",
        evidence_refs=("b",),
    )
    if (
        replay_lifecycle_history(
            LifecycleState.RESEARCH_ONLY,
            (same_time_first, same_time_second),
            9,
        )
        is not LifecycleState.REQUALIFICATION_DUE
    ):
        errors.append("PR357_EQUAL_TIME_APPEND_ORDER")

    age = compute_evidence_age_vector(
        now=100,
        evidence_available_at=50,
        current_deployment_generation=2,
        evidence_deployment_generation=1,
        current_source_schema_generation=1,
        evidence_source_schema_generation=1,
        current_topology_generation=1,
        evidence_topology_generation=1,
        regime_distance=0,
        current_model_generation=1,
        evidence_model_generation=1,
    )
    if "DEPLOYMENT_GENERATION_CHANGED" not in age.hard_invalidators:
        errors.append("PR357_DEPLOYMENT_INVALIDATOR_MISSING")
    transition = record_lifecycle_transition(
        strategy_id="fixture",
        previous_state=LifecycleState.OBSERVING,
        next_state=LifecycleState.REQUALIFICATION_DUE,
        decision_time=100,
        reason="fixture invalidator",
        evidence_refs=("fixture",),
    )
    if transition.execution_right is not False:
        errors.append("PR357_TRANSITION_EXECUTION_RIGHT")

    decision = {
        "actions": {
            "A": {"down": 10, "up": 0},
            "B": {"down": 0, "up": 10},
        },
        "state_probabilities_ppm": {"down": 500_000, "up": 500_000},
        "deadline": 10,
        "mandatory_safety": ("safety",),
        "execution_right": False,
    }
    if estimate_evpi(decision) != 5:
        errors.append("PR357_EVPI_IDENTITY")
    evsi = estimate_evsi(
        decision,
        posterior_scenarios=(
            {"down": 900_000, "up": 100_000},
            {"down": 100_000, "up": 900_000},
        ),
        observation_probabilities_ppm=(500_000, 500_000),
    )
    if evsi <= 0 or evsi > 5:
        errors.append("PR357_EVSI_BOUND")
    try:
        estimate_evsi(
            decision,
            posterior_scenarios=({"down": 0, "up": 1_000_000},),
            observation_probabilities_ppm=(1_000_000,),
        )
        errors.append("PR357_INCOHERENT_EVSI_ACCEPTED")
    except PR357ContractError:
        pass

    covariance_clock = ObservationClock(1, 2, 3, 4, "cov", "v1")
    positive_belief = define_market_belief_state(
        belief_id="positive-covariance",
        decision_time=10,
        observed={"x": 0, "y": 0},
        posterior_mean={"x": 0, "y": 0},
        covariance={
            "x": {"x": 100, "y": 80},
            "y": {"x": 80, "y": 100},
        },
        missingness_mask={"x": False, "y": False},
        source_clocks={"x": covariance_clock, "y": covariance_clock},
        valid_until=11,
    )
    negative_belief = define_market_belief_state(
        belief_id="negative-covariance",
        decision_time=10,
        observed={"x": 0, "y": 0},
        posterior_mean={"x": 0, "y": 0},
        covariance={
            "x": {"x": 100, "y": -80},
            "y": {"x": -80, "y": 100},
        },
        missingness_mask={"x": False, "y": False},
        source_clocks={"x": covariance_clock, "y": covariance_clock},
        valid_until=11,
    )
    positive_samples = generate_joint_predictive_distribution(
        positive_belief, sample_count=200, seed=357
    )
    negative_samples = generate_joint_predictive_distribution(
        negative_belief, sample_count=200, seed=357
    )
    if positive_samples == negative_samples:
        errors.append("PR357_COVARIANCE_IGNORED")

    safety = InformationActionSpec("safety", 1, 3, 1, 10, True, "p0")
    optional = InformationActionSpec("optional", 10, 3, 1, 10, False, "p1")
    safety_plan = reserve_safety_information_budget(
        (safety, optional),
        budget_units=3,
    )
    if safety_plan.get("selected") != ("safety",):
        errors.append("PR357_SAFETY_RESERVATION")
    if not block_decision_without_safety_info((), ("safety",)):
        errors.append("PR357_SAFETY_ABSTENTION")

    priors = (
        PriorCandidate("ok", 800_000, 800_000, 800_000, 900_000, 0),
        PriorCandidate(
            "bad-rights",
            990_000,
            990_000,
            990_000,
            990_000,
            0,
            rights_compatible=False,
        ),
    )
    from src.research.pr357_core import rank_bootstrap_prior_set

    if rank_bootstrap_prior_set(priors) != ("ok",):
        errors.append("PR357_PRIOR_RIGHTS_FILTER")

    first = run_pr357_integrated_vertical()
    second = run_pr357_integrated_vertical()
    if first["integrated_receipt_hash"] != second["integrated_receipt_hash"]:
        errors.append("PR357_VERTICAL_NONDETERMINISTIC")
    if first.get("status") not in {
        "SUPPORTED_RESEARCH_ONLY",
        "REJECTED_WITH_EVIDENCE",
    }:
        errors.append("PR357_VERTICAL_STATUS")
    if first["decision"]["absent_safety_probe"] != "ABSTAIN":
        errors.append("PR357_VERTICAL_SAFETY_PROBE")
    if (
        first["decision"]["challenger_regret_units"]
        >= first["decision"]["baseline_regret_units"]
    ):
        errors.append("PR357_VERTICAL_REGRET_NOT_REDUCED")
    if any(first["effect_boundary"].values()):
        errors.append("PR357_VERTICAL_EFFECT_BOUNDARY")
    if first.get("execution_right") is not False:
        errors.append("PR357_VERTICAL_EXECUTION_RIGHT")

    if len(registry.get("packages", [])) != 48:
        errors.append("PR357_REGISTRY_PACKAGES")
    if len(registry.get("hypotheses", [])) != 80:
        errors.append("PR357_REGISTRY_HYPOTHESES")
    if len(registry.get("challenges", [])) != 40:
        errors.append("PR357_REGISTRY_CHALLENGES")
    if len(registry.get("sources", [])) != 27:
        errors.append("PR357_REGISTRY_SOURCES")
    if any(item.get("dependency_added") for item in registry.get("sources", [])):
        errors.append("PR357_UNREVIEWED_DEPENDENCY_ADDED")

    if evidence.get("observed_main_at_start") != (
        "a96491af37594d0aacf2416aa74c56dbb1c9c304"
    ):
        errors.append("PR357_BASE_SHA_MISMATCH")
    if evidence.get("agents_md_at_repo_root") != "NOT_FOUND":
        errors.append("PR357_AGENTS_TRUTH")
    if audit.get("implementation_scope_complete") is not True:
        errors.append("PR357_AUDIT_SCOPE_INCOMPLETE")
    if audit.get("external_qualification_complete") is not False:
        errors.append("PR357_AUDIT_EXTERNAL_OVERCLAIM")
    if any(EFFECT_BOUNDARY.values()):
        errors.append("PR357_STATIC_EFFECT_BOUNDARY_UNSAFE")

    return {
        "accepted": not errors,
        "errors": errors,
        "requirements": len(rows),
        "packages": len(registry.get("packages", [])),
        "typed_contracts": len(CONTRACT_SCHEMAS),
        "hypotheses": len(registry.get("hypotheses", [])),
        "challenges": len(registry.get("challenges", [])),
        "residual_adapter_calls": residual_calls,
        "runtime_blocked_external_without_evidence": blocked_runtime,
        "integrated_receipt_hash": first["integrated_receipt_hash"],
        "external_qualification_complete": False,
        "production_ready": False,
        "live_enabled": False,
        "execution_right": False,
    }


def main() -> int:
    result = verify()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
