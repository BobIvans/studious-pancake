"""Exact offline CPMM branches for the existing joint split-flow owner.

State is an immutable serialized pool vector, shared by all branches. This is
model replay evidence, not deployment qualification or execution permission.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
import math

from src.economics.split_flow import PathExecution, SharedExecutionState
from .exact_cpmm_capacity import (
    CpmmEvaluationError,
    CpmmEvaluationRejection,
    ExactCpmmRoutePlan,
    QualifiedCpmmState,
    QualifiedRaydiumCpmmAdapter,
)


def pool_key(pool: QualifiedCpmmState) -> str:
    return json.dumps(asdict(pool.venue), sort_keys=True, separators=(",", ":"))


def shared_cpmm_state(plans: tuple[ExactCpmmRoutePlan, ...]) -> SharedExecutionState:
    if not plans:
        raise ValueError("plans required")
    pools: dict[str, QualifiedCpmmState] = {}
    generation = plans[0].pools[0].generation.identity
    asset = plans[0].settlement_asset
    for plan in plans:
        if plan.settlement_asset != asset:
            raise ValueError("split settlement assets differ")
        for pool in plan.pools:
            if pool.generation.identity != generation:
                raise ValueError("split generations differ")
            key = pool_key(pool)
            if key in pools and pools[key] != pool:
                raise ValueError("aliased pool has conflicting initial state")
            pools[key] = pool
    return SharedExecutionState(
        generation,
        (),
        tuple(
            (
                key,
                json.dumps(
                    [
                        pool.identity,
                        pool.reserve_a,
                        pool.reserve_b,
                        pool.accrued_fees_a,
                        pool.accrued_fees_b,
                    ],
                    separators=(",", ":"),
                ),
            )
            for key, pool in pools.items()
        ),
    )


@dataclass(frozen=True, slots=True)
class ExactCpmmSplitPath:
    plan: ExactCpmmRoutePlan
    now: float
    compute_units: int
    message_bytes: int
    explicit_cost_units: int = 0
    max_snapshot_age_seconds: float = 5.0
    max_slot_skew: int = 0

    def __post_init__(self) -> None:
        if (
            isinstance(self.now, bool)
            or not math.isfinite(self.now)
            or self.now <= 0
            or isinstance(self.max_snapshot_age_seconds, bool)
            or not math.isfinite(self.max_snapshot_age_seconds)
            or self.max_snapshot_age_seconds <= 0
        ):
            raise ValueError("finite snapshot clock and positive age policy required")
        for field, minimum in (
            ("compute_units", 1),
            ("message_bytes", 1),
            ("explicit_cost_units", 0),
            ("max_slot_skew", 0),
        ):
            value = getattr(self, field)
            if type(value) is not int or value < minimum:
                raise ValueError("integer split resource and slot policy required")

    @property
    def path_id(self) -> str:
        return self.plan.semantic_route_id

    def evaluate(
        self, amount: int, state: SharedExecutionState
    ) -> PathExecution | None:
        if state.generation != self.plan.pools[0].generation.identity:
            raise ValueError("stale split generation")
        if (
            max(p.slot for p in self.plan.pools) - min(p.slot for p in self.plan.pools)
            > self.max_slot_skew
        ):
            raise ValueError("split slot skew")
        states = dict(state.market_states)
        asset = self.plan.settlement_asset
        current = amount
        adapter = QualifiedRaydiumCpmmAdapter()
        # Reject corrupt shared frames in every pool before considering an
        # amount-local zero-output/capacity rejection in the first leg.
        for original in self.plan.pools:
            adapter.qualify_state(original)
            identity, ra, rb, fa, fb = json.loads(states[pool_key(original)])
            if identity != original.identity:
                raise ValueError("split pool revision mismatch")
            replace(
                original,
                reserve_a=ra,
                reserve_b=rb,
                accrued_fees_a=tuple(fa),
                accrued_fees_b=tuple(fb),
            )
            if (
                original.observed_at > self.now
                or self.now >= original.expires_at
                or self.now - original.observed_at > self.max_snapshot_age_seconds
            ):
                raise ValueError("stale split pool")
        for original in self.plan.pools:
            adapter.qualify_state(original)
            if (
                original.observed_at > self.now
                or self.now >= original.expires_at
                or self.now - original.observed_at > self.max_snapshot_age_seconds
            ):
                raise ValueError("stale split pool")
            key = pool_key(original)
            identity, reserve_a, reserve_b, fees_a, fees_b = json.loads(states[key])
            if identity != original.identity:
                raise ValueError("split pool revision mismatch")
            pool = replace(
                original,
                reserve_a=reserve_a,
                reserve_b=reserve_b,
                accrued_fees_a=tuple(fees_a),
                accrued_fees_b=tuple(fees_b),
            )
            try:
                leg = adapter.evaluate(pool, input_asset=asset, requested_input=current)
            except CpmmEvaluationError as exc:
                if exc.reason in (
                    CpmmEvaluationRejection.ZERO_OUTPUT,
                    CpmmEvaluationRejection.INPUT_CAPACITY_EXCEEDED,
                ):
                    return None
                raise
            states[key] = json.dumps(
                [
                    identity,
                    leg.state_after.reserve_a,
                    leg.state_after.reserve_b,
                    leg.state_after.accrued_fees_a,
                    leg.state_after.accrued_fees_b,
                ],
                separators=(",", ":"),
            )
            asset, current = leg.output_asset, leg.conservative_output
        if asset != self.plan.settlement_asset:
            raise ValueError("split path does not close")
        return PathExecution(
            self.path_id,
            amount,
            current,
            SharedExecutionState(
                state.generation, state.capacities, tuple(states.items())
            ),
            self.compute_units,
            self.message_bytes,
            self.explicit_cost_units,
        )
