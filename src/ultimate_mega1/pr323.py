"""PR-323 / NF-996..1001: typed cashflow lattice and payoff-package search."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

from .core import ContractResult, UltimateMegaError, record, require_int, require_nonnegative, require_positive, stable_hash


def build_typed_cashflow_lattice(
    primitives: Sequence[Mapping[str, Any]],
) -> ContractResult:
    nodes = []
    seen = set()
    for primitive in primitives:
        key = (
            primitive.get("asset"),
            primitive.get("payment_time"),
            primitive.get("contingency_id"),
            primitive.get("rights_hash"),
        )
        if any(value is None for value in key):
            raise UltimateMegaError("RIGHTS_UNVERIFIED")
        if key in seen:
            continue
        seen.add(key)
        nodes.append(
            {
                "key": key,
                "capacity": require_nonnegative(int(primitive.get("capacity", 0)), "capacity"),
                "cashflows": tuple(require_int(int(x), "cashflow") for x in primitive.get("cashflows", ())),
            }
        )
    if not nodes:
        raise UltimateMegaError("TIME_BASIS_MISMATCH")
    return record("build_typed_cashflow_lattice", {"nodes": tuple(nodes)})


def derive_cashflow_equivalence_classes(
    nodes: Sequence[Mapping[str, Any]],
) -> ContractResult:
    classes: dict[tuple[Any, ...], list[Any]] = defaultdict(list)
    for node in nodes:
        key = tuple(node.get("key", ()))
        cashflows = tuple(node.get("cashflows", ()))
        if len(key) != 4 or not cashflows:
            raise UltimateMegaError("UNMODELED_CONTINGENCY")
        equivalence_key = (key[0], key[1], key[2], key[3], cashflows)
        classes[equivalence_key].append(key)
    return record(
        "derive_cashflow_equivalence_classes",
        {"classes": tuple((key, tuple(value)) for key, value in sorted(classes.items(), key=lambda x: repr(x[0])))},
    )


def search_executable_payoff_packages(
    candidates: Sequence[Mapping[str, Any]],
    *,
    search_budget: int,
) -> ContractResult:
    budget = require_positive(search_budget, "search_budget")
    if len(candidates) > budget:
        raise UltimateMegaError("SEARCH_BUDGET_EXCEEDED")
    feasible = []
    resource_used: dict[str, int] = defaultdict(int)
    for candidate in candidates:
        capacity = require_nonnegative(int(candidate.get("capacity", 0)), "capacity")
        requested = require_nonnegative(int(candidate.get("requested", 0)), "requested")
        if requested > capacity:
            continue
        resource = str(candidate.get("resource_id", candidate.get("id", "")))
        resource_cap = require_nonnegative(int(candidate.get("resource_capacity", capacity)), "resource_capacity")
        if resource_used[resource] + requested > resource_cap:
            continue
        resource_used[resource] += requested
        feasible.append(dict(candidate))
    return record(
        "search_executable_payoff_packages",
        {"feasible": tuple(feasible), "searched": len(candidates), "resource_usage": dict(resource_used)},
    )


def certify_package_obligation_balance(
    *,
    inflows: Mapping[tuple[str, int, str], int],
    outflows: Mapping[tuple[str, int, str], int],
    expenses: Mapping[tuple[str, int, str], int] | None = None,
) -> ContractResult:
    expenses = dict(expenses or {})
    keys = set(inflows) | set(outflows) | set(expenses)
    deficits = {}
    balances = {}
    for key in keys:
        incoming = require_int(inflows.get(key, 0), "inflow")
        outgoing = require_int(outflows.get(key, 0), "outflow")
        expense = require_nonnegative(expenses.get(key, 0), "expense")
        balance = incoming - outgoing - expense
        balances[str(key)] = balance
        if balance < 0:
            deficits[str(key)] = -balance
    if deficits:
        return record(
            "certify_package_obligation_balance",
            {"balances": balances, "counterexample_deficits": deficits},
            status="BLOCKED",
            blockers=("PAYOFF_DEFICIT",),
        )
    return record("certify_package_obligation_balance", {"balances": balances, "counterexample_deficits": {}})


def compile_verified_package_to_existing_dialect(
    certificate: Mapping[str, Any],
    *,
    supported_legs: Sequence[str],
    package_legs: Sequence[str],
    temporal: bool,
) -> ContractResult:
    if certificate.get("counterexample_deficits"):
        raise UltimateMegaError("PAYOFF_DEFICIT")
    unsupported = tuple(sorted(set(package_legs) - set(supported_legs)))
    if unsupported:
        return record(
            "compile_verified_package_to_existing_dialect",
            {"unsupported_legs": unsupported, "compiled": False, "domain": "TEMPORAL" if temporal else "ATOMIC"},
            status="BLOCKED",
            blockers=("UNSUPPORTED_EXECUTION_DIALECT",),
        )
    return record(
        "compile_verified_package_to_existing_dialect",
        {"unsupported_legs": (), "compiled": True, "domain": "TEMPORAL" if temporal else "ATOMIC", "unsigned": True},
    )


def benchmark_package_search_against_cycles(
    *,
    verified_packages: int,
    verified_cycles: int,
    common_query_budget: int,
    common_sim_budget: int,
) -> ContractResult:
    packages = require_nonnegative(verified_packages, "verified_packages")
    cycles = require_nonnegative(verified_cycles, "verified_cycles")
    queries = require_positive(common_query_budget, "common_query_budget")
    sims = require_positive(common_sim_budget, "common_sim_budget")
    return record(
        "benchmark_package_search_against_cycles",
        {"verified_packages": packages, "verified_cycles": cycles, "incremental_verified": packages - cycles, "query_budget": queries, "simulation_budget": sims},
    )
