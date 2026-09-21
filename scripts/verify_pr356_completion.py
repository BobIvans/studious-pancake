#!/usr/bin/env python3
"""Corrective completion verifier for roadmap PR-356."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from src.mechanism_discovery.pr356_contracts import (
    AllocationProposal,
    MarketEpisodeRecord,
    PR356ContractError,
)
from src.research.pr356_allocation import (
    build_opportunity_portfolio_problem,
    solve_opportunity_portfolio,
    verify_portfolio_feasibility,
)
from src.research.pr356_integrated_loop import run_integrated_science_fixture

ROOT = Path(__file__).resolve().parents[1]


def verify() -> dict[str, object]:
    errors: list[str] = []
    owner = json.loads(
        (ROOT / "config/pr356_owner_map.json").read_text(encoding="utf-8")
    )
    registry = json.loads(
        (ROOT / "config/pr356_registry.json").read_text(encoding="utf-8")
    )
    audit = json.loads(
        (
            ROOT / "release_artifacts/pr356/completion_audit.json"
        ).read_text(encoding="utf-8")
    )

    rows = owner.get("requirements", [])
    if len(rows) != 544:
        errors.append("PR356_COMPLETION_REQUIREMENT_COUNT")
    counts = owner.get("counts", {})
    if counts.get("implemented_contracts") != 499:
        errors.append("PR356_COMPLETION_IMPLEMENTED_COUNT")
    if counts.get("satisfied_by_existing") != 45:
        errors.append("PR356_COMPLETION_SATISFIED_COUNT")
    if counts.get("not_run") != 0:
        errors.append("PR356_COMPLETION_NOT_RUN_REMAINS")
    if owner.get("roadmap_code_research_scope_complete") is not True:
        errors.append("PR356_COMPLETION_OWNER_SCOPE_FALSE")
    if registry.get("scope_complete_implementation_claim") is not True:
        errors.append("PR356_COMPLETION_REGISTRY_SCOPE_FALSE")
    if registry.get("roadmap_code_research_scope_complete") is not True:
        errors.append("PR356_COMPLETION_REGISTRY_CODE_SCOPE_FALSE")
    if registry.get("external_qualification_complete") is not False:
        errors.append("PR356_COMPLETION_EXTERNAL_OVERCLAIM")

    residual_count = 0
    blocked_count = 0
    for row in rows:
        if row.get("implementation_status") == "NOT_RUN":
            errors.append(
                f"PR356_COMPLETION_NOT_RUN:{row.get('requirement_id')}"
            )
        if not row.get("corrective_completion"):
            continue
        residual_count += 1
        module_name = str(row["owner_path"])[:-3].replace("/", ".")
        module = importlib.import_module(module_name)
        symbol = getattr(module, str(row["owner_symbol"]), None)
        if not callable(symbol):
            errors.append(
                f"PR356_COMPLETION_SYMBOL_MISSING:{row.get('requirement_id')}"
            )
            continue
        result = symbol()
        if result.get("execution_right") is not False:
            errors.append(
                f"PR356_COMPLETION_EXECUTION_RIGHT:{row.get('requirement_id')}"
            )
        if result.get("status") not in {
            "CONTRACT_IMPLEMENTED",
            "BLOCKED_EXTERNAL",
        }:
            errors.append(
                f"PR356_COMPLETION_STATUS_INVALID:{row.get('requirement_id')}"
            )
        if result.get("status") == "BLOCKED_EXTERNAL":
            blocked_count += 1
    if residual_count != 391:
        errors.append("PR356_COMPLETION_RESIDUAL_COUNT")

    for package in registry.get("packages", []):
        if package.get("status") == "NOT_RUN":
            errors.append(
                f"PR356_COMPLETION_PACKAGE_NOT_RUN:{package.get('id')}"
            )
    for group in ("campaigns", "benchmarks", "challenges"):
        for row in registry.get(group, []):
            if row.get("status") == "NOT_RUN":
                errors.append(
                    f"PR356_COMPLETION_REGISTRY_NOT_RUN:{group}:{row.get('id')}"
                )

    try:
        MarketEpisodeRecord(
            episode_id="bad-order",
            campaign_id="c",
            mechanism_id="m",
            trigger_available_at=10,
            episode_start=12,
            episode_end_or_censored=11,
            feature_snapshot_hash="h",
            label_status="MISSING",
            label_available_at=None,
            outcome_provenance=None,
            interference_cluster_id="cluster",
        )
        errors.append("PR356_REVIEW_FIX_EPISODE_END_NOT_ENFORCED")
    except PR356ContractError:
        pass

    try:
        MarketEpisodeRecord(
            episode_id="bad-label",
            campaign_id="c",
            mechanism_id="m",
            trigger_available_at=10,
            episode_start=10,
            episode_end_or_censored=20,
            feature_snapshot_hash="h",
            label_status="MATURE",
            label_available_at=19,
            outcome_provenance="fixture",
            interference_cluster_id="cluster",
        )
        errors.append("PR356_REVIEW_FIX_LABEL_ORDER_NOT_ENFORCED")
    except PR356ContractError:
        pass

    negative_problem = build_opportunity_portfolio_problem(
        (
            {
                "candidate_id": "negative",
                "expected_utility_units": 1,
                "tail_loss_units": 0,
                "resource_usage": {"compute": -1},
            },
        ),
        {"compute": 0},
    )
    try:
        solve_opportunity_portfolio(negative_problem)
        errors.append("PR356_REVIEW_FIX_NEGATIVE_USAGE_NOT_ENFORCED")
    except PR356ContractError:
        pass

    tail_problem = build_opportunity_portfolio_problem(
        (
            {
                "candidate_id": "tail",
                "expected_utility_units": 1,
                "tail_loss_units": 5,
                "resource_usage": {"compute": 0},
            },
        ),
        {"compute": 0},
    )
    tail_problem["max_tail_loss_units"] = 2
    loaded = AllocationProposal(
        proposal_id="loaded",
        candidate_ids=("tail",),
        weights_or_sizes={"tail": 1},
        resource_usage={"compute": 0},
        expected_utility_units=1,
        tail_loss_units=5,
        binding_constraints=(),
        rejected_candidates=(),
        sensitivity_ppm=0,
        evidence_refs=("fixture",),
    )
    if verify_portfolio_feasibility(loaded, tail_problem).get("feasible"):
        errors.append("PR356_REVIEW_FIX_TAIL_RECHECK_NOT_ENFORCED")

    first = run_integrated_science_fixture()
    second = run_integrated_science_fixture()
    if first["integrated_receipt_hash"] != second["integrated_receipt_hash"]:
        errors.append("PR356_INTEGRATED_RECEIPT_NONDETERMINISTIC")
    if first.get("execution_right") is not False:
        errors.append("PR356_INTEGRATED_EXECUTION_RIGHT_UNSAFE")
    portfolio = first.get("portfolio", {})
    if len(portfolio.get("strategy_cards", ())) != 3:
        errors.append("PR356_THREE_STRATEGY_CARDS_MISSING")
    if portfolio.get("feasibility", {}).get("feasible") is not True:
        errors.append("PR356_INTEGRATED_FEASIBILITY_FAILED")

    dod = audit.get("definition_of_done", [])
    if len(dod) != 19 or any(
        row.get("status") == "NOT_RUN" for row in dod
    ):
        errors.append("PR356_DEFINITION_OF_DONE_INCOMPLETE")
    if audit.get("implementation_scope_complete") is not True:
        errors.append("PR356_AUDIT_IMPLEMENTATION_SCOPE_FALSE")
    if audit.get("external_qualification_complete") is not False:
        errors.append("PR356_AUDIT_EXTERNAL_OVERCLAIM")
    if any(value is not False for value in audit.get("safety", {}).values()):
        errors.append("PR356_AUDIT_EFFECT_BOUNDARY_UNSAFE")

    return {
        "accepted": not errors,
        "errors": errors,
        "requirements": len(rows),
        "corrective_residual_contracts": residual_count,
        "residual_blocked_external_without_evidence": blocked_count,
        "not_run": counts.get("not_run"),
        "packages": len(registry.get("packages", [])),
        "campaigns": len(registry.get("campaigns", [])),
        "benchmarks": len(registry.get("benchmarks", [])),
        "challenges": len(registry.get("challenges", [])),
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
