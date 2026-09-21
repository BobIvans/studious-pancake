#!/usr/bin/env python3
"""Structural + focused semantic verifier for roadmap PR-356."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

from src.mechanism_discovery.pr356_campaigns import (
    compare_reachable_capacity_error,
    inject_deployment_upgrade_attack,
    inject_label_censoring_attack,
    inject_provider_disagreement_attack,
    inject_revision_attack,
    inject_schema_unit_attack,
    inject_source_delay_attack,
    inject_topology_rights_attack,
    measure_campaign_reaction_gap,
    publish_reachability_verdict,
)
from src.mechanism_discovery.pr356_discovery import (
    define_hypothesis_program,
    publish_novelty_receipt,
)
from src.mechanism_discovery.pr356_state_machine import (
    compute_friendly_liquidity,
    define_deferred_constraint_window,
    measure_reaction_gap,
    simulate_transient_solvency_state,
)
from src.research.pr356_allocation import (
    build_opportunity_portfolio_problem,
    publish_allocation_proposal,
    solve_opportunity_portfolio,
    verify_portfolio_feasibility,
)
from src.research.pr356_ecology import (
    define_ecology_environment,
    record_ecology_trajectory,
    replay_ecology_trajectory,
)

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_DISPOSITIONS = {
    "SATISFIED_BY_EXISTING",
    "SPECIALIZE_EXISTING",
    "NEW_OUTCOME",
    "BLOCKED_EXTERNAL",
}
ALLOWED_IMPL_STATUS = {
    "CONTRACT_IMPLEMENTED",
    "SATISFIED_BY_EXISTING",
    "NOT_RUN",
    "BLOCKED_EXTERNAL",
}
FORBIDDEN_EFFECT_TOKENS = (
    "from src.submission",
    "import src.submission",
    "isolated_signer_service",
    "send_transaction(",
    "submit_transaction(",
    "requests.",
    "aiohttp.",
    "httpx.",
    "PRIVATE_KEY",
)
PR356_CODE_PATHS = (
    "src/mechanism_discovery/pr356_contracts.py",
    "src/mechanism_discovery/pr356_state_machine.py",
    "src/mechanism_discovery/pr356_campaigns.py",
    "src/mechanism_discovery/pr356_discovery.py",
    "src/research/pr356_ecology.py",
    "src/research/pr356_allocation.py",
    "src/research/pr356_completion_contracts.py",
    "src/mechanism_discovery/pr356_state_completion.py",
    "src/mechanism_discovery/pr356_campaign_completion.py",
    "src/mechanism_discovery/pr356_benchmark_completion.py",
    "src/mechanism_discovery/pr356_discovery_completion.py",
    "src/research/pr356_ecology_completion.py",
    "src/research/pr356_allocation_completion.py",
    "src/research/pr356_integrated_loop.py",
)


def _module_from_path(path: str) -> str:
    if not path.endswith(".py"):
        raise ValueError(path)
    return path[:-3].replace("/", ".")


def verify() -> dict[str, object]:
    errors: list[str] = []
    owner_map = json.loads(
        (ROOT / "config/pr356_owner_map.json").read_text(encoding="utf-8")
    )
    registry = json.loads(
        (ROOT / "config/pr356_registry.json").read_text(encoding="utf-8")
    )
    rollback = json.loads(
        (ROOT / "config/pr356_rollback.json").read_text(encoding="utf-8")
    )
    evidence = json.loads(
        (
            ROOT
            / "release_artifacts/pr356/current-head-evidence.json"
        ).read_text(encoding="utf-8")
    )

    rows = owner_map.get("requirements", [])
    ids = [row.get("requirement_id") for row in rows]
    if len(rows) != 544 or len(set(ids)) != 544:
        errors.append("PR356_REQUIREMENT_COUNT_OR_ID_DUPLICATION")
    if owner_map.get("counts", {}).get("packages") != 68:
        errors.append("PR356_PACKAGE_COUNT_MISMATCH")
    if owner_map.get("duplicate_authorities") != []:
        errors.append("PR356_DUPLICATE_AUTHORITY_DECLARED")
    if owner_map.get("permanent_nf_allocated") is not False:
        errors.append("PR356_UNAUTHORIZED_PERMANENT_NF")
    if any(
        value is not False
        for value in owner_map.get("effect_boundary", {}).values()
    ):
        errors.append("PR356_EFFECT_BOUNDARY_UNSAFE")
    if owner_map.get("marginfi") != "PAUSED":
        errors.append("PR356_MARGINFI_NOT_PAUSED")
    if owner_map.get("slumlord_low_capital_requirement") != "REQUIRED":
        errors.append("PR356_SLUMLORD_REQUIREMENT_DRIFT")

    for row in rows:
        rid = str(row.get("requirement_id"))
        if row.get("disposition") not in ALLOWED_DISPOSITIONS:
            errors.append(f"PR356_DISPOSITION_INVALID:{rid}")
        if row.get("implementation_status") not in ALLOWED_IMPL_STATUS:
            errors.append(f"PR356_IMPLEMENTATION_STATUS_INVALID:{rid}")
        if (
            not row.get("owner_path")
            or not row.get("tests")
            or not row.get("evidence_refs")
        ):
            errors.append(f"PR356_OWNER_EVIDENCE_MISSING:{rid}")
        if row.get("implementation_status") == "CONTRACT_IMPLEMENTED":
            try:
                module = importlib.import_module(
                    _module_from_path(str(row["owner_path"]))
                )
                symbol = row.get("owner_symbol")
                if not callable(getattr(module, str(symbol), None)):
                    errors.append(
                        f"PR356_IMPLEMENTED_SYMBOL_MISSING:{rid}:{symbol}"
                    )
            except Exception as exc:
                errors.append(
                    "PR356_IMPLEMENTED_OWNER_IMPORT_FAILED:"
                    f"{rid}:{type(exc).__name__}"
                )

    collision = owner_map.get("known_symbol_collision", {})
    if collision.get("canonical_requirement") != "W2F-044":
        errors.append("PR356_REACTION_GAP_CANONICAL_OWNER_DRIFT")
    if collision.get("consumer_requirement") != "W3F-043":
        errors.append("PR356_REACTION_GAP_CONSUMER_DRIFT")
    if collision.get("duplicate_public_symbol_created") is not False:
        errors.append("PR356_REACTION_GAP_DUPLICATE_OWNER")
    if measure_campaign_reaction_gap(
        actionable_at_ms=10,
        response_at_ms=17,
    ) != measure_reaction_gap(
        actionable_at_ms=10,
        response_at_ms=17,
    ):
        errors.append("PR356_REACTION_GAP_ALIAS_SEMANTICS_DRIFT")

    expected_registry_counts = {
        "packages": 68,
        "marketpacks": 16,
        "campaigns": 8,
        "benchmarks": 10,
        "red_team_cases": 10,
        "challenges": 30,
        "hypotheses": 124,
        "sources": 58,
    }
    for key, expected in expected_registry_counts.items():
        if len(registry.get(key, [])) != expected:
            errors.append(f"PR356_REGISTRY_COUNT_MISMATCH:{key}")
    scope_complete = registry.get("scope_complete_implementation_claim")
    if scope_complete is True:
        completion_path = (
            ROOT / "release_artifacts/pr356/completion_audit.json"
        )
        if not completion_path.is_file():
            errors.append("PR356_SCOPE_COMPLETE_WITHOUT_AUDIT")
        elif any(
            row.get("implementation_status") == "NOT_RUN"
            for row in owner_map.get("requirements", [])
        ):
            errors.append("PR356_SCOPE_COMPLETE_WITH_NOT_RUN")
    elif scope_complete is not False:
        errors.append("PR356_SCOPE_COMPLETION_FLAG_INVALID")
    if any(
        value is not False
        for value in registry.get("effect_boundary", {}).values()
    ):
        errors.append("PR356_REGISTRY_EFFECT_BOUNDARY_UNSAFE")
    if any(
        row.get("execution_right") is not False
        for row in registry.get("hypotheses", [])
    ):
        errors.append("PR356_HYPOTHESIS_EXECUTION_RIGHT_UNSAFE")
    if any(
        row.get("copy_performed") is not False
        for row in registry.get("sources", [])
    ):
        errors.append("PR356_UNATTESTED_SOURCE_COPY")
    if any(
        row.get("status") != "REFERENCE_ONLY_REVERIFY"
        for row in registry.get("sources", [])
    ):
        errors.append("PR356_SOURCE_REVERIFY_BOUNDARY_MISSING")

    if rollback.get("config_first") is not True or len(
        rollback.get("steps", [])
    ) != 5:
        errors.append("PR356_ROLLBACK_INCOMPLETE")
    for field in (
        "signing_required",
        "fund_recovery_required",
        "remote_transaction_reversal_required",
    ):
        if rollback.get(field) is not False:
            errors.append(f"PR356_ROLLBACK_EFFECT_UNSAFE:{field}")

    if evidence.get("implementation_base_sha") != owner_map.get(
        "implementation_base_sha"
    ):
        errors.append("PR356_EVIDENCE_BASE_SHA_MISMATCH")
    if any(evidence.get("claims", {}).values()):
        errors.append("PR356_EVIDENCE_OVERCLAIM")
    if any(
        value is not False
        for value in evidence.get("safety", {}).values()
    ):
        errors.append("PR356_EVIDENCE_SAFETY_UNSAFE")

    liquidity = compute_friendly_liquidity(
        visible_atoms=100,
        target_current_atoms=100,
        sources=(
            {
                "source_id": "vault-a",
                "available_atoms": 80,
                "flow_cap_atoms": 50,
                "target_cap_atoms": 160,
            },
        ),
    )
    if (
        liquidity["reachable_atoms"] != 150
        or liquidity["exclusivity_assumed"] is not False
    ):
        errors.append("PR356_REACHABLE_LIQUIDITY_FIXTURE_FAILED")

    window = define_deferred_constraint_window(
        {
            "window_id": "evc-style",
            "final_min_equity_atoms": 0,
            "temporary_debt_limit_atoms": 50,
            "check_at_end_only": True,
            "allowed_accounts": ("subaccount-0",),
        }
    )
    transient = simulate_transient_solvency_state(
        initial_equity_atoms=10,
        deltas_atoms=(-30, 25),
        window=window,
    )
    if (
        transient.get("accepted") is not True
        or min(transient.get("trace", (0,))) >= 0
    ):
        errors.append("PR356_DEFERRED_SOLVENCY_FIXTURE_FAILED")

    comparison = compare_reachable_capacity_error(
        naive_capacity_atoms=100,
        reachable_capacity_atoms=150,
        exact_capacity_atoms=150,
    )
    verdict = publish_reachability_verdict(
        campaign_id="CAMP-01",
        hypothesis_id="C3H-01",
        comparison=comparison,
        exact_evidence_available=False,
    )
    if verdict.verdict != "BLOCKED_EXTERNAL" or verdict.execution_right:
        errors.append("PR356_CAMP01_EXTERNAL_BOUNDARY_FAILED")

    redteam = (
        inject_source_delay_attack(detector_abstained=True),
        inject_schema_unit_attack(schema_rejected=True),
        inject_revision_attack(future_revision_excluded=True),
        inject_deployment_upgrade_attack(generation_invalidated=True),
        inject_topology_rights_attack(evidence_invalidated=True),
        inject_provider_disagreement_attack(quarantined=True),
        inject_label_censoring_attack(unknown_preserved=True),
    )
    if sum(1 for row in redteam if row["passed"]) < 6:
        errors.append("PR356_REDTEAM_MINIMUM_NOT_MET")

    hypothesis = define_hypothesis_program(
        {
            "hypothesis_id": "fixture-h",
            "mechanism_motif_id": "reachable-liquidity",
            "observed_variables": ("visible", "friendly"),
            "target": "exact_capacity",
            "horizon": 1,
            "regime": "fixture",
            "null_hypothesis": "friendly adds no value",
            "reject_condition": "no locked improvement",
            "counterexample_class": "shared liquidity race",
            "holdout_id": "locked-fixture",
        }
    )
    novelty = publish_novelty_receipt(hypothesis, (), ())
    if novelty.get("verdict") != "NOVEL":
        errors.append("PR356_NOVELTY_FIXTURE_FAILED")

    environment = define_ecology_environment(
        {
            "environment_id": "eco-fixture",
            "state_owner_refs": ("canonical-state",),
            "mechanism_generations": ("g1",),
            "seed": 7,
        }
    )
    events = (
        {
            "at_ms": 1,
            "kind": "DISCOVERY",
            "edge_delta_atoms": 0,
        },
        {
            "at_ms": 2,
            "kind": "COMPETITOR_REACTION",
            "edge_delta_atoms": -3,
        },
    )
    trajectory = record_ecology_trajectory(
        environment=environment,
        events=events,
        initial_edge_atoms=10,
    )
    replay = replay_ecology_trajectory(
        environment=environment,
        events=events,
        initial_edge_atoms=10,
        expected_receipt_hash=trajectory["receipt_hash"],
    )
    if (
        replay.get("reproduced") is not True
        or trajectory.get("synthetic") is not True
    ):
        errors.append("PR356_ECOLOGY_DETERMINISM_FAILED")

    problem = build_opportunity_portfolio_problem(
        (
            {
                "candidate_id": "a",
                "expected_utility_units": 7,
                "tail_loss_units": 2,
                "resource_usage": {"compute": 2},
                "conflict_keys": ("pool-x",),
            },
            {
                "candidate_id": "b",
                "expected_utility_units": 6,
                "tail_loss_units": 2,
                "resource_usage": {"compute": 2},
                "conflict_keys": ("pool-x",),
            },
            {
                "candidate_id": "c",
                "expected_utility_units": 4,
                "tail_loss_units": 1,
                "resource_usage": {"compute": 1},
                "conflict_keys": ("pool-y",),
            },
        ),
        {"compute": 3},
    )
    proposal = solve_opportunity_portfolio(problem)
    feasibility = verify_portfolio_feasibility(proposal, problem)
    published = publish_allocation_proposal(proposal)
    if (
        feasibility.get("feasible") is not True
        or published.get("execution_right") is not False
    ):
        errors.append("PR356_ALLOCATION_FIXTURE_FAILED")
    if set(proposal.candidate_ids) != {"a", "c"}:
        errors.append("PR356_ALLOCATION_EXPECTED_SET_FAILED")

    for relative in PR356_CODE_PATHS:
        source = (ROOT / relative).read_text(encoding="utf-8")
        for token in FORBIDDEN_EFFECT_TOKENS:
            if token in source:
                errors.append(
                    f"PR356_FORBIDDEN_EFFECT_TOKEN:{relative}:{token}"
                )

    return {
        "accepted": not errors,
        "errors": errors,
        "requirement_count": len(rows),
        "package_count": len(registry.get("packages", [])),
        "implemented_contract_count": owner_map.get("counts", {}).get(
            "implemented_contracts"
        ),
        "red_team_fixture_passes": sum(
            1 for row in redteam if row["passed"]
        ),
        "camp01_verdict": verdict.verdict,
        "ecology_reproduced": replay.get("reproduced"),
        "allocation_candidate_ids": proposal.candidate_ids,
        "live_enabled": False,
        "signer_access": False,
        "submission_access": False,
        "wallet_access": False,
        "execution_right": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = verify()
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(result)
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
