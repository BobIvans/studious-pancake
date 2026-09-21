"""PR-305 / NF-906..910: financing order and prefix-solvency constraints."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Mapping, Sequence

from .core import ContractResult, UltimateMegaError, record, require_int, require_nonnegative, require_positive, stable_hash


def encode_financing_composition_constraints(
    lender_constraints: Sequence[Mapping[str, Any]],
    instructions: Sequence[Mapping[str, Any]],
) -> ContractResult:
    positions = []
    for idx, instruction in enumerate(instructions):
        position = require_int(instruction.get("position", idx), "instruction_position")
        if position != idx:
            raise UltimateMegaError("AMBIGUOUS_INSTRUCTION_INDEX")
        positions.append(position)
    labels = []
    before = []
    for item in lender_constraints:
        label = str(item.get("label", "")).strip()
        if not label:
            raise UltimateMegaError("UNQUALIFIED_LENDER_RULE")
        labels.append(label)
        for edge in item.get("before", ()):
            if not isinstance(edge, (list, tuple)) or len(edge) != 2:
                raise UltimateMegaError("UNQUALIFIED_LENDER_RULE")
            before.append((int(edge[0]), int(edge[1]), label))
    return record(
        "encode_financing_composition_constraints",
        {
            "instruction_count": len(positions),
            "labels": tuple(labels),
            "before": tuple(before),
            "constraint_hash": stable_hash(
                "financing-constraints", {"rules": lender_constraints, "instructions": instructions}
            ),
        },
    )


def encode_prefix_balance_and_lifetimes(
    initial_balances: Mapping[str, int],
    steps: Sequence[Mapping[str, Any]],
    *,
    upfront_fee: int = 0,
) -> ContractResult:
    balances = {
        str(asset): require_nonnegative(amount, f"balance_{asset}")
        for asset, amount in initial_balances.items()
    }
    fee = require_nonnegative(upfront_fee, "upfront_fee")
    native = balances.get("native", 0)
    if native < fee:
        raise UltimateMegaError("FEE_BOOTSTRAP_MISSING")
    balances["native"] = native - fee
    trace = [dict(balances)]
    active_accounts: set[str] = set()
    for step in steps:
        for account in step.get("open", ()):
            active_accounts.add(str(account))
        for asset, delta in step.get("deltas", {}).items():
            asset = str(asset)
            delta = require_int(delta, f"delta_{asset}")
            balances[asset] = balances.get(asset, 0) + delta
            if balances[asset] < 0:
                raise UltimateMegaError("RESERVED_FUNDS_REUSED")
        for account in step.get("close", ()):
            account = str(account)
            if account not in active_accounts:
                raise UltimateMegaError("ACCOUNT_LIFETIME_INVALID")
            active_accounts.remove(account)
        trace.append(dict(balances))
    return record(
        "encode_prefix_balance_and_lifetimes",
        {
            "prefix_balances": tuple(trace),
            "open_accounts": tuple(sorted(active_accounts)),
            "upfront_fee": fee,
        },
    )


def solve_financing_order_variant(
    node_count: int,
    before_edges: Sequence[Sequence[int]],
    *,
    node_budget: int = 128,
) -> ContractResult:
    node_count = require_positive(node_count, "node_count")
    node_budget = require_positive(node_budget, "node_budget")
    if node_count > node_budget:
        return record(
            "solve_financing_order_variant",
            {"solver_status": "UNKNOWN", "reason": "NODE_BUDGET"},
            status="UNKNOWN",
            blockers=("TIMEOUT",),
        )
    graph: dict[int, set[int]] = defaultdict(set)
    indegree = [0] * node_count
    for edge in before_edges:
        if len(edge) < 2:
            raise UltimateMegaError("UNQUALIFIED_LENDER_RULE")
        a, b = int(edge[0]), int(edge[1])
        if not (0 <= a < node_count and 0 <= b < node_count):
            raise UltimateMegaError("AMBIGUOUS_INSTRUCTION_INDEX")
        if b not in graph[a]:
            graph[a].add(b)
            indegree[b] += 1
    queue = deque(i for i, degree in enumerate(indegree) if degree == 0)
    order = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for nxt in sorted(graph[node]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if len(order) != node_count:
        core = tuple(i for i, degree in enumerate(indegree) if degree > 0)
        return record(
            "solve_financing_order_variant",
            {"solver_status": "UNSAT", "unsat_nodes": core},
            status="BLOCKED",
            blockers=("UNSAT",),
        )
    return record(
        "solve_financing_order_variant",
        {"solver_status": "SAT", "permutation": tuple(order)},
    )


def verify_solved_financing_variant(
    order_variant: Mapping[str, Any],
    *,
    rebuilt_positions: Sequence[int],
    vm_accepted: bool,
) -> ContractResult:
    if order_variant.get("solver_status") != "SAT":
        raise UltimateMegaError("SOLVER_VARIANT_NOT_SAT")
    permutation = tuple(int(x) for x in order_variant.get("permutation", ()))
    if tuple(rebuilt_positions) != permutation:
        raise UltimateMegaError("POST_BUILD_REORDER")
    if not vm_accepted:
        raise UltimateMegaError("SAT_BUT_VM_REJECTED")
    return record(
        "verify_solved_financing_variant",
        {"permutation": permutation, "vm_accepted": True},
    )


def record_financing_unsat_core(
    unsat: Mapping[str, Any],
    *,
    source_rules: Mapping[str, str],
) -> ContractResult:
    nodes = tuple(int(x) for x in unsat.get("unsat_nodes", ()))
    if not nodes:
        raise UltimateMegaError("CORE_NOT_REPRODUCIBLE")
    if not source_rules:
        raise UltimateMegaError("UNSOURCED_CONSTRAINT")
    return record(
        "record_financing_unsat_core",
        {
            "conflict_nodes": nodes,
            "source_rules": dict(source_rules),
            "core_claim": "sufficient-conflict-set",
            "source_hash": stable_hash("financing-source-rules", source_rules),
        },
    )
