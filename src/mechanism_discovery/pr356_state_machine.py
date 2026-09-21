"""PR-356 versioned financial-state and reachability research primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .pr356_contracts import PR356ContractError, canonical_hash


def _integer(value: Any, name: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PR356ContractError(f"{name.upper()}_INTEGER_REQUIRED")
    if minimum is not None and value < minimum:
        raise PR356ContractError(f"{name.upper()}_BELOW_MINIMUM")
    return value


def _name(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PR356ContractError(f"{name.upper()}_REQUIRED")
    return value.strip()


@dataclass(frozen=True, slots=True)
class DeferredConstraintWindow:
    window_id: str
    final_min_equity_atoms: int
    temporary_debt_limit_atoms: int
    check_at_end_only: bool
    allowed_accounts: tuple[str, ...]

    def __post_init__(self) -> None:
        _name(self.window_id, "window_id")
        _integer(self.final_min_equity_atoms, "final_min_equity_atoms")
        _integer(self.temporary_debt_limit_atoms, "temporary_debt_limit_atoms", minimum=0)
        if not self.allowed_accounts:
            raise PR356ContractError("DEFERRED_WINDOW_ACCOUNTS_REQUIRED")


def snapshot_financial_graph_topology(
    *,
    topology_id: str,
    observed_at: int,
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    rights: Sequence[Mapping[str, Any]] = (),
) -> Mapping[str, Any]:
    """Create a deterministic content-addressed graph snapshot."""
    _name(topology_id, "topology_id")
    _integer(observed_at, "observed_at", minimum=0)
    normalized_nodes = tuple(sorted((dict(row) for row in nodes), key=lambda row: str(row.get("id", ""))))
    normalized_edges = tuple(
        sorted(
            (dict(row) for row in edges),
            key=lambda row: (str(row.get("source", "")), str(row.get("target", "")), str(row.get("kind", ""))),
        )
    )
    normalized_rights = tuple(
        sorted((dict(row) for row in rights), key=lambda row: (str(row.get("subject", "")), str(row.get("right", ""))))
    )
    payload = {
        "topology_id": topology_id,
        "observed_at": observed_at,
        "nodes": normalized_nodes,
        "edges": normalized_edges,
        "rights": normalized_rights,
    }
    return {**payload, "topology_hash": canonical_hash(payload), "research_only": True}


def record_topology_delta(before: Mapping[str, Any], after: Mapping[str, Any]) -> Mapping[str, Any]:
    """Record structural births/deaths separately from numeric drift."""
    before_nodes = {str(row["id"]) for row in before.get("nodes", ())}
    after_nodes = {str(row["id"]) for row in after.get("nodes", ())}
    before_edges = {(str(row["source"]), str(row["target"]), str(row.get("kind", ""))) for row in before.get("edges", ())}
    after_edges = {(str(row["source"]), str(row["target"]), str(row.get("kind", ""))) for row in after.get("edges", ())}
    return {
        "nodes_added": tuple(sorted(after_nodes - before_nodes)),
        "nodes_removed": tuple(sorted(before_nodes - after_nodes)),
        "edges_added": tuple(sorted(after_edges - before_edges)),
        "edges_removed": tuple(sorted(before_edges - after_edges)),
        "before_hash": before.get("topology_hash"),
        "after_hash": after.get("topology_hash"),
    }


def detect_topology_drift(delta: Mapping[str, Any]) -> bool:
    return any(delta.get(key) for key in ("nodes_added", "nodes_removed", "edges_added", "edges_removed"))


def retire_invalid_graph_knowledge(
    knowledge_rows: Sequence[Mapping[str, Any]], *, active_topology_hash: str
) -> tuple[Mapping[str, Any], ...]:
    _name(active_topology_hash, "active_topology_hash")
    result = []
    for row in knowledge_rows:
        item = dict(row)
        item["active"] = item.get("topology_hash") == active_topology_hash
        if not item["active"]:
            item["retired_reason"] = "TOPOLOGY_GENERATION_CHANGED"
        result.append(item)
    return tuple(result)


def define_deferred_constraint_window(payload: Mapping[str, Any]) -> DeferredConstraintWindow:
    return DeferredConstraintWindow(
        window_id=_name(payload.get("window_id"), "window_id"),
        final_min_equity_atoms=_integer(payload.get("final_min_equity_atoms"), "final_min_equity_atoms"),
        temporary_debt_limit_atoms=_integer(payload.get("temporary_debt_limit_atoms"), "temporary_debt_limit_atoms", minimum=0),
        check_at_end_only=bool(payload.get("check_at_end_only", False)),
        allowed_accounts=tuple(_name(item, "allowed_account") for item in payload.get("allowed_accounts", ())),
    )


def compile_deferred_status_checks(window: DeferredConstraintWindow) -> Mapping[str, Any]:
    return {
        "window_id": window.window_id,
        "prefix_equity_check_required": not window.check_at_end_only,
        "final_equity_check_required": True,
        "temporary_debt_limit_atoms": window.temporary_debt_limit_atoms,
        "final_min_equity_atoms": window.final_min_equity_atoms,
    }


def simulate_transient_solvency_state(
    *,
    initial_equity_atoms: int,
    deltas_atoms: Sequence[int],
    window: DeferredConstraintWindow,
) -> Mapping[str, Any]:
    equity = _integer(initial_equity_atoms, "initial_equity_atoms")
    trace = [equity]
    max_deficit = max(0, -equity)
    for delta in deltas_atoms:
        equity += _integer(delta, "delta_atoms")
        trace.append(equity)
        max_deficit = max(max_deficit, -equity)
        if not window.check_at_end_only and equity < window.final_min_equity_atoms:
            return {
                "accepted": False,
                "reason": "PREFIX_SOLVENCY_FAILED",
                "trace": tuple(trace),
                "final_equity_atoms": equity,
            }
        if max_deficit > window.temporary_debt_limit_atoms:
            return {
                "accepted": False,
                "reason": "TEMPORARY_DEBT_LIMIT_EXCEEDED",
                "trace": tuple(trace),
                "final_equity_atoms": equity,
            }
    return {
        "accepted": equity >= window.final_min_equity_atoms,
        "reason": "FINAL_SOLVENCY_OK" if equity >= window.final_min_equity_atoms else "FINAL_SOLVENCY_FAILED",
        "trace": tuple(trace),
        "max_deficit_atoms": max_deficit,
        "final_equity_atoms": equity,
    }


def prove_final_batch_solvency(simulation: Mapping[str, Any], window: DeferredConstraintWindow) -> Mapping[str, Any]:
    final_equity = _integer(simulation.get("final_equity_atoms"), "final_equity_atoms")
    proved = bool(simulation.get("accepted")) and final_equity >= window.final_min_equity_atoms
    return {
        "proved": proved,
        "window_id": window.window_id,
        "final_equity_atoms": final_equity,
        "required_equity_atoms": window.final_min_equity_atoms,
        "proof_kind": "BOUNDED_DETERMINISTIC_RESEARCH_CHECK",
    }


def register_reallocatable_liquidity_source(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "source_id": _name(payload.get("source_id"), "source_id"),
        "available_atoms": _integer(payload.get("available_atoms"), "available_atoms", minimum=0),
        "flow_cap_atoms": _integer(payload.get("flow_cap_atoms"), "flow_cap_atoms", minimum=0),
        "target_cap_atoms": _integer(payload.get("target_cap_atoms"), "target_cap_atoms", minimum=0),
        "penalty_ppm": _integer(payload.get("penalty_ppm", 0), "penalty_ppm", minimum=0),
        "generation": _name(payload.get("generation"), "generation"),
    }


def read_reallocation_caps_and_penalty(source: Mapping[str, Any]) -> Mapping[str, int]:
    return {
        "flow_cap_atoms": _integer(source.get("flow_cap_atoms"), "flow_cap_atoms", minimum=0),
        "target_cap_atoms": _integer(source.get("target_cap_atoms"), "target_cap_atoms", minimum=0),
        "penalty_ppm": _integer(source.get("penalty_ppm"), "penalty_ppm", minimum=0),
    }


def compute_friendly_liquidity(
    *, visible_atoms: int, target_current_atoms: int, sources: Sequence[Mapping[str, Any]]
) -> Mapping[str, Any]:
    visible = _integer(visible_atoms, "visible_atoms", minimum=0)
    target_current = _integer(target_current_atoms, "target_current_atoms", minimum=0)
    additions = []
    total_extra = 0
    for source in sources:
        available = _integer(source.get("available_atoms"), "available_atoms", minimum=0)
        flow_cap = _integer(source.get("flow_cap_atoms"), "flow_cap_atoms", minimum=0)
        target_cap = _integer(source.get("target_cap_atoms"), "target_cap_atoms", minimum=0)
        room = max(0, target_cap - target_current - total_extra)
        extra = min(available, flow_cap, room)
        additions.append((str(source.get("source_id")), extra))
        total_extra += extra
    return {
        "visible_atoms": visible,
        "reallocatable_atoms": total_extra,
        "reachable_atoms": visible + total_extra,
        "source_allocations": tuple(additions),
        "exclusivity_assumed": False,
    }


def plan_reallocation_before_operation(
    *, requested_atoms: int, liquidity: Mapping[str, Any]
) -> Mapping[str, Any]:
    requested = _integer(requested_atoms, "requested_atoms", minimum=0)
    visible = _integer(liquidity.get("visible_atoms"), "visible_atoms", minimum=0)
    reachable = _integer(liquidity.get("reachable_atoms"), "reachable_atoms", minimum=0)
    needed = max(0, requested - visible)
    if requested > reachable:
        return {"feasible": False, "reason": "REACHABLE_CAPACITY_INSUFFICIENT", "requested_atoms": requested}
    return {
        "feasible": True,
        "reallocate_atoms": needed,
        "operate_atoms": requested,
        "ordered_steps": ("REALLOCATE", "OPERATION") if needed else ("OPERATION",),
    }


def model_reallocation_race(*, planned_atoms: int, remaining_atoms: int) -> Mapping[str, Any]:
    planned = _integer(planned_atoms, "planned_atoms", minimum=0)
    remaining = _integer(remaining_atoms, "remaining_atoms", minimum=0)
    lost = max(0, planned - remaining)
    return {
        "planned_atoms": planned,
        "remaining_atoms": remaining,
        "race_loss_atoms": lost,
        "stale_plan": lost > 0,
    }


def attribute_reallocation_cost(
    *, amount_atoms: int, penalty_ppm: int, gas_atoms: int, opportunity_cost_atoms: int
) -> Mapping[str, int]:
    amount = _integer(amount_atoms, "amount_atoms", minimum=0)
    penalty = _integer(penalty_ppm, "penalty_ppm", minimum=0)
    gas = _integer(gas_atoms, "gas_atoms", minimum=0)
    opportunity = _integer(opportunity_cost_atoms, "opportunity_cost_atoms", minimum=0)
    penalty_atoms = amount * penalty // 1_000_000
    return {
        "penalty_atoms": penalty_atoms,
        "gas_atoms": gas,
        "opportunity_cost_atoms": opportunity,
        "total_cost_atoms": penalty_atoms + gas + opportunity,
    }


def define_information_visibility_state(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    regime = _name(payload.get("regime"), "regime").upper()
    allowed = {"PUBLIC", "PRIVATE_RFQ", "ENCRYPTED", "OEV_UPDATE_RIGHT", "BATCH", "PRECONFIRMED"}
    if regime not in allowed:
        raise PR356ContractError("INFORMATION_REGIME_UNKNOWN")
    return {
        "regime": regime,
        "visible_to": tuple(sorted(str(x) for x in payload.get("visible_to", ()))),
        "actionable_at": _integer(payload.get("actionable_at"), "actionable_at", minimum=0),
    }


def record_reveal_commit_timeline(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    fields = {}
    previous = None
    for name in ("encrypted_at", "committed_at", "revealed_at", "included_at"):
        value = payload.get(name)
        if value is None:
            fields[name] = None
            continue
        timestamp = _integer(value, name, minimum=0)
        if previous is not None and timestamp < previous:
            raise PR356ContractError("INFORMATION_TIMELINE_NON_MONOTONIC")
        previous = timestamp
        fields[name] = timestamp
    return fields


def measure_reaction_gap(*, actionable_at_ms: int, response_at_ms: int) -> Mapping[str, int]:
    actionable = _integer(actionable_at_ms, "actionable_at_ms", minimum=0)
    response = _integer(response_at_ms, "response_at_ms", minimum=0)
    if response < actionable:
        raise PR356ContractError("REACTION_PRECEDES_INFORMATION")
    return {"reaction_gap_ms": response - actionable}


def separate_public_private_encrypted_orderflow(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, tuple[Mapping[str, Any], ...]]:
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        regime = _name(row.get("regime"), "regime").upper()
        groups.setdefault(regime, []).append(dict(row))
    return {key: tuple(value) for key, value in sorted(groups.items())}


def define_crosschain_finality_class(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    finality = _name(payload.get("finality_class"), "finality_class").upper()
    if finality not in {"STANDARD", "FINALIZED", "FAST_ATTESTED"}:
        raise PR356ContractError("CROSSCHAIN_FINALITY_CLASS_UNKNOWN")
    return {
        "finality_class": finality,
        "attestation_required": bool(payload.get("attestation_required", finality == "FAST_ATTESTED")),
        "source_atomic_with_destination": False,
        "research_only": True,
    }


def estimate_transfer_inventory_shadow_cost(
    *, locked_atoms: int, duration_seconds: int, cost_ppm_per_day: int, fast_fee_atoms: int
) -> Mapping[str, int]:
    locked = _integer(locked_atoms, "locked_atoms", minimum=0)
    duration = _integer(duration_seconds, "duration_seconds", minimum=0)
    rate = _integer(cost_ppm_per_day, "cost_ppm_per_day", minimum=0)
    fee = _integer(fast_fee_atoms, "fast_fee_atoms", minimum=0)
    duration_cost = locked * rate * duration // (1_000_000 * 86_400)
    return {"duration_cost_atoms": duration_cost, "fast_fee_atoms": fee, "total_atoms": duration_cost + fee}
