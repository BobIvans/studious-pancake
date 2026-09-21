"""PR-167 / SIM-03: sequential shared-state route interpretation."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Sequence
from .core import Mega802Error, require_nonnegative_int, stable_hash


@dataclass(frozen=True, slots=True)
class StateMutation:
    resource: str
    delta: int
    leg_id: str


def apply_route_leg_to_state(
    state: Mapping[str, int], *, leg_id: str, deltas: Mapping[str, int]
) -> dict[str, int]:
    result = {key: require_nonnegative_int(value, key) for key, value in state.items()}
    for resource, delta in sorted(deltas.items()):
        if isinstance(delta, bool) or not isinstance(delta, int):
            raise Mega802Error("STATE_DELTA_NOT_INTEGER")
        updated = result.get(resource, 0) + delta
        if updated < 0:
            raise Mega802Error("NEGATIVE_SHARED_STATE")
        result[resource] = updated
    return result


def trace_shared_resource_mutations(
    legs: Sequence[tuple[str, Mapping[str, int]]],
) -> tuple[StateMutation, ...]:
    return tuple(
        StateMutation(resource, delta, leg_id)
        for leg_id, deltas in legs
        for resource, delta in sorted(deltas.items())
    )


def rollback_failed_route_branch(
    state: Mapping[str, int], mutations: Sequence[StateMutation]
) -> dict[str, int]:
    result = dict(state)
    for mutation in reversed(tuple(mutations)):
        result[mutation.resource] = result.get(mutation.resource, 0) - mutation.delta
        if result[mutation.resource] < 0:
            raise Mega802Error("ROLLBACK_UNDERFLOW")
    return result


def emit_state_transition_proof(
    before: Mapping[str, int],
    after: Mapping[str, int],
    mutations: Sequence[StateMutation],
) -> str:
    return stable_hash(
        {
            "before": dict(sorted(before.items())),
            "after": dict(sorted(after.items())),
            "mutations": [
                {"resource": item.resource, "delta": item.delta, "leg": item.leg_id}
                for item in mutations
            ],
        }
    )
