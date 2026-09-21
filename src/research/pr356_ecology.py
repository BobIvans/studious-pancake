"""PR-356 deterministic synthetic market-ecology research.

No method in this module can sign, submit, fund, or mutate a remote market.
Trajectories are explicitly synthetic and may only support research claims.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.mechanism_discovery.pr356_contracts import (
    AgentArchetype,
    PR356ContractError,
    canonical_hash,
)


def define_agent_archetype(payload: Mapping[str, Any]) -> AgentArchetype:
    return AgentArchetype(
        archetype_id=str(payload["archetype_id"]),
        role=str(payload["role"]),
        market_scope=tuple(str(x) for x in payload.get("market_scope", ())),
        information_set=tuple(str(x) for x in payload.get("information_set", ())),
        action_space=tuple(str(x) for x in payload.get("action_space", ())),
        inventory_capital_constraints={
            str(k): int(v)
            for k, v in dict(
                payload.get("inventory_capital_constraints", {})
            ).items()
        },
        risk_limits={
            str(k): int(v)
            for k, v in dict(payload.get("risk_limits", {})).items()
        },
        execution_rights=tuple(
            str(x) for x in payload.get("execution_rights", ())
        ),
        uncertainty_ppm=int(payload.get("uncertainty_ppm", 1_000_000)),
    )


def define_ecology_environment(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    environment = {
        "environment_id": str(payload["environment_id"]),
        "state_owner_refs": tuple(str(x) for x in payload["state_owner_refs"]),
        "mechanism_generations": tuple(
            str(x) for x in payload["mechanism_generations"]
        ),
        "event_clock": str(payload.get("event_clock", "DISCRETE")),
        "information_regime": str(
            payload.get("information_regime", "PUBLIC")
        ),
        "seed": int(payload.get("seed", 0)),
        "unsupported_mechanics": tuple(
            str(x) for x in payload.get("unsupported_mechanics", ())
        ),
        "synthetic_boundary": True,
        "execution_right": False,
    }
    environment["environment_hash"] = canonical_hash(environment)
    return environment


def schedule_discrete_events(
    events: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    normalized = []
    for index, row in enumerate(events):
        at = int(row["at_ms"])
        if at < 0:
            raise PR356ContractError("ECOLOGY_EVENT_TIME_NEGATIVE")
        normalized.append({**dict(row), "at_ms": at, "_ordinal": index})
    return tuple(
        sorted(normalized, key=lambda row: (row["at_ms"], row["_ordinal"]))
    )


def record_ecology_trajectory(
    *,
    environment: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    initial_edge_atoms: int,
) -> Mapping[str, Any]:
    edge = int(initial_edge_atoms)
    sequence = []
    for event in schedule_discrete_events(events):
        kind = str(event.get("kind", "")).upper()
        delta = int(event.get("edge_delta_atoms", 0))
        if kind not in {
            "DISCOVERY",
            "COMPETITOR_REACTION",
            "LP_RESPONSE",
            "BLOCKSPACE",
            "OUR_HYPOTHETICAL_ACTION",
        }:
            raise PR356ContractError("ECOLOGY_EVENT_KIND_UNKNOWN")
        edge += delta
        sequence.append(
            {
                "at_ms": event["at_ms"],
                "kind": kind,
                "edge_atoms": edge,
            }
        )
    payload = {
        "environment_hash": environment["environment_hash"],
        "seed": environment["seed"],
        "event_sequence": tuple(sequence),
        "terminal_edge_atoms": edge,
        "synthetic": True,
        "execution_right": False,
    }
    return {**payload, "receipt_hash": canonical_hash(payload)}


def replay_ecology_trajectory(
    *,
    environment: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    initial_edge_atoms: int,
    expected_receipt_hash: str,
) -> Mapping[str, Any]:
    observed = record_ecology_trajectory(
        environment=environment,
        events=events,
        initial_edge_atoms=initial_edge_atoms,
    )
    return {
        "reproduced": observed["receipt_hash"] == expected_receipt_hash,
        "observed_receipt_hash": observed["receipt_hash"],
    }


def instantiate_competing_searcher_population(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    population = []
    for row in rows:
        latency = int(row["discovery_latency_ms"])
        cost = int(row.get("cost_atoms", 0))
        if latency < 0 or cost < 0:
            raise PR356ContractError("SEARCHER_POPULATION_VALUE_INVALID")
        population.append(
            {
                "searcher_id": str(row["searcher_id"]),
                "discovery_latency_ms": latency,
                "cost_atoms": cost,
            }
        )
    return tuple(
        sorted(
            population,
            key=lambda row: (
                row["discovery_latency_ms"],
                row["searcher_id"],
            ),
        )
    )


def measure_competitive_half_life(
    *, static_lifetime_ms: int, adaptive_lifetime_ms: int
) -> Mapping[str, int]:
    if static_lifetime_ms < 0 or adaptive_lifetime_ms < 0:
        raise PR356ContractError("OPPORTUNITY_LIFETIME_NEGATIVE")
    return {
        "static_lifetime_ms": static_lifetime_ms,
        "adaptive_lifetime_ms": adaptive_lifetime_ms,
        "optimism_ms": max(0, static_lifetime_ms - adaptive_lifetime_ms),
    }


def measure_crowding_capacity(
    *, base_capacity_atoms: int, competitor_claims_atoms: Sequence[int]
) -> Mapping[str, int]:
    if base_capacity_atoms < 0 or any(
        value < 0 for value in competitor_claims_atoms
    ):
        raise PR356ContractError("CROWDING_CAPACITY_NEGATIVE")
    remaining = max(0, base_capacity_atoms - sum(competitor_claims_atoms))
    return {
        "base_capacity_atoms": base_capacity_atoms,
        "crowding_capacity_atoms": remaining,
    }


def define_selfplay_policy_space(
    policies: Sequence[str],
) -> Mapping[str, Any]:
    normalized = tuple(sorted({str(policy) for policy in policies}))
    if not normalized:
        raise PR356ContractError("SELFPLAY_POLICY_SPACE_EMPTY")
    return {"policies": normalized, "execution_right": False}


def solve_policy_meta_mixture(
    payoff_floor_by_policy: Mapping[str, int],
) -> Mapping[str, Any]:
    if not payoff_floor_by_policy:
        raise PR356ContractError("SELFPLAY_PAYOFFS_REQUIRED")
    best = max(
        sorted(payoff_floor_by_policy),
        key=lambda name: payoff_floor_by_policy[name],
    )
    return {
        "policy_weights_ppm": {
            name: (1_000_000 if name == best else 0)
            for name in sorted(payoff_floor_by_policy)
        },
        "criterion": "MAXIMIN_RESEARCH_BASELINE",
        "execution_right": False,
    }


def measure_policy_exploitability(
    *, incumbent_floor: int, best_response_value: int
) -> Mapping[str, int]:
    return {
        "exploitability_units": max(
            0, int(best_response_value) - int(incumbent_floor)
        )
    }


def detect_selfplay_pathology(history: Sequence[str]) -> Mapping[str, Any]:
    cycle = len(history) >= 4 and history[-2:] == history[-4:-2]
    collapse = len(set(history[-3:])) == 1 if len(history) >= 3 else False
    return {
        "cycle_detected": cycle,
        "collapse_detected": collapse,
        "pathology": cycle or collapse,
    }


def measure_ecology_reality_gap(
    *,
    simulated_metrics: Mapping[str, int],
    real_metrics: Mapping[str, int],
) -> Mapping[str, Any]:
    shared = sorted(set(simulated_metrics) & set(real_metrics))
    if not shared:
        raise PR356ContractError("ECOLOGY_REALITY_GAP_METRICS_MISSING")
    deltas = {
        key: abs(int(simulated_metrics[key]) - int(real_metrics[key]))
        for key in shared
    }
    return {
        "metric_deltas": deltas,
        "max_delta": max(deltas.values()),
        "research_only": True,
    }


def downgrade_unvalidated_ecology_claim(
    *, reality_gap: int, tolerance: int
) -> Mapping[str, Any]:
    allowed = reality_gap <= tolerance
    return {
        "validated_for_research": allowed,
        "claim_status": (
            "RESEARCH_USE_ALLOWED" if allowed else "INCONCLUSIVE"
        ),
        "execution_right": False,
    }


def sandbox_remote_research_result(
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    return {
        "artifact_hash": canonical_hash(dict(payload)),
        "trusted": False,
        "local_replication_required": True,
        "execution_right": False,
    }
