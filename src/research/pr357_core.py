"""Deterministic PR-357 research primitives.

This module implements the semantic core used by lifecycle, bootstrap,
point-in-time world-model, and decision-intelligence adapters.  It is offline,
stdlib-only, deterministic, and research-only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from math import isqrt
import random
from typing import Any, Iterable, Mapping, Sequence

from src.research.pr357_contracts import (
    EFFECT_BOUNDARY,
    PR357ContractError,
    canonical_hash,
)


PPM = 1_000_000


class LifecycleState(StrEnum):
    RESEARCH_ONLY = "RESEARCH_ONLY"
    OBSERVING = "OBSERVING"
    SHADOW_CANDIDATE = "SHADOW_CANDIDATE"
    VERIFIED_SHADOW = "VERIFIED_SHADOW"
    DORMANT = "DORMANT"
    REQUALIFICATION_DUE = "REQUALIFICATION_DUE"
    RETIRED = "RETIRED"
    REJECTED = "REJECTED"
    BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"


_ALLOWED_TRANSITIONS: dict[LifecycleState, frozenset[LifecycleState]] = {
    LifecycleState.RESEARCH_ONLY: frozenset(
        {
            LifecycleState.OBSERVING,
            LifecycleState.REJECTED,
            LifecycleState.BLOCKED_EXTERNAL,
        }
    ),
    LifecycleState.OBSERVING: frozenset(
        {
            LifecycleState.SHADOW_CANDIDATE,
            LifecycleState.DORMANT,
            LifecycleState.REQUALIFICATION_DUE,
            LifecycleState.REJECTED,
            LifecycleState.BLOCKED_EXTERNAL,
        }
    ),
    LifecycleState.SHADOW_CANDIDATE: frozenset(
        {
            LifecycleState.VERIFIED_SHADOW,
            LifecycleState.DORMANT,
            LifecycleState.REQUALIFICATION_DUE,
            LifecycleState.REJECTED,
        }
    ),
    LifecycleState.VERIFIED_SHADOW: frozenset(
        {
            LifecycleState.DORMANT,
            LifecycleState.REQUALIFICATION_DUE,
            LifecycleState.RETIRED,
        }
    ),
    LifecycleState.DORMANT: frozenset(
        {
            LifecycleState.OBSERVING,
            LifecycleState.REQUALIFICATION_DUE,
            LifecycleState.RETIRED,
        }
    ),
    LifecycleState.REQUALIFICATION_DUE: frozenset(
        {
            LifecycleState.OBSERVING,
            LifecycleState.DORMANT,
            LifecycleState.RETIRED,
            LifecycleState.REJECTED,
            LifecycleState.BLOCKED_EXTERNAL,
        }
    ),
    LifecycleState.BLOCKED_EXTERNAL: frozenset(
        {
            LifecycleState.RESEARCH_ONLY,
            LifecycleState.REQUALIFICATION_DUE,
            LifecycleState.REJECTED,
        }
    ),
    LifecycleState.RETIRED: frozenset({LifecycleState.REQUALIFICATION_DUE}),
    LifecycleState.REJECTED: frozenset({LifecycleState.REQUALIFICATION_DUE}),
}


@dataclass(frozen=True, slots=True)
class ObservationClock:
    event_time: int
    published_at: int
    received_at: int
    available_at: int
    source_id: str
    revision_id: str

    def __post_init__(self) -> None:
        values = (
            self.event_time,
            self.published_at,
            self.received_at,
            self.available_at,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise PR357ContractError("PR357_TIMESTAMP_INTEGER_REQUIRED")
        if min(values) < 0:
            raise PR357ContractError("PR357_NEGATIVE_TIMESTAMP")
        if not (
            self.event_time
            <= self.published_at
            <= self.received_at
            <= self.available_at
        ):
            raise PR357ContractError("PR357_TIMESTAMP_ORDER_INVALID")
        if not self.source_id or not self.revision_id:
            raise PR357ContractError("PR357_SOURCE_REVISION_REQUIRED")


@dataclass(frozen=True, slots=True)
class LifecycleTransitionReceipt:
    strategy_id: str
    previous_state: LifecycleState
    next_state: LifecycleState
    decision_time: int
    reason: str
    evidence_refs: tuple[str, ...]
    execution_right: bool = False

    def __post_init__(self) -> None:
        if not self.strategy_id or not self.reason:
            raise PR357ContractError("PR357_TRANSITION_ID_REASON_REQUIRED")
        if self.decision_time < 0:
            raise PR357ContractError("PR357_TRANSITION_TIME_INVALID")
        if self.execution_right:
            raise PR357ContractError("PR357_TRANSITION_EXECUTION_RIGHT_FORBIDDEN")
        if self.next_state not in _ALLOWED_TRANSITIONS[self.previous_state]:
            raise PR357ContractError(
                f"PR357_LIFECYCLE_TRANSITION_INVALID:"
                f"{self.previous_state}->{self.next_state}"
            )

    @property
    def receipt_hash(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True, slots=True)
class EvidenceAgeVector:
    wall_age: int
    deployment_generation_age: int
    source_schema_age: int
    topology_age: int
    regime_distance: int
    model_generation_age: int
    hard_invalidators: tuple[str, ...]

    def __post_init__(self) -> None:
        numeric = (
            self.wall_age,
            self.deployment_generation_age,
            self.source_schema_age,
            self.topology_age,
            self.regime_distance,
            self.model_generation_age,
        )
        if any(value < 0 for value in numeric):
            raise PR357ContractError("PR357_NEGATIVE_EVIDENCE_AGE")


@dataclass(frozen=True, slots=True)
class PriorCandidate:
    prior_id: str
    semantic_similarity_ppm: int
    topology_similarity_ppm: int
    source_similarity_ppm: int
    freshness_ppm: int
    negative_transfer_count: int
    rights_compatible: bool = True

    def __post_init__(self) -> None:
        if not self.prior_id:
            raise PR357ContractError("PR357_PRIOR_ID_REQUIRED")
        for value in (
            self.semantic_similarity_ppm,
            self.topology_similarity_ppm,
            self.source_similarity_ppm,
            self.freshness_ppm,
        ):
            if not 0 <= value <= PPM:
                raise PR357ContractError("PR357_PRIOR_SCORE_RANGE")
        if self.negative_transfer_count < 0:
            raise PR357ContractError("PR357_NEGATIVE_TRANSFER_COUNT")


@dataclass(frozen=True, slots=True)
class BeliefState:
    belief_id: str
    decision_time: int
    observed: Mapping[str, int]
    posterior_mean: Mapping[str, int]
    covariance: Mapping[str, Mapping[str, int]]
    missingness_mask: Mapping[str, bool]
    source_clocks: Mapping[str, ObservationClock]
    valid_until: int
    execution_right: bool = False

    def __post_init__(self) -> None:
        if not self.belief_id:
            raise PR357ContractError("PR357_BELIEF_ID_REQUIRED")
        if self.decision_time < 0 or self.valid_until < self.decision_time:
            raise PR357ContractError("PR357_BELIEF_VALIDITY_INVALID")
        if self.execution_right:
            raise PR357ContractError("PR357_BELIEF_EXECUTION_RIGHT_FORBIDDEN")
        for name, clock in self.source_clocks.items():
            if clock.available_at > self.decision_time:
                raise PR357ContractError(
                    f"PR357_LOOKAHEAD_OBSERVATION:{name}"
                )
        names = set(self.posterior_mean)
        if set(self.covariance) != names:
            raise PR357ContractError("PR357_COVARIANCE_ROW_MISMATCH")
        for row_name, row in self.covariance.items():
            if set(row) != names:
                raise PR357ContractError(
                    f"PR357_COVARIANCE_COLUMN_MISMATCH:{row_name}"
                )
            if row[row_name] < 0:
                raise PR357ContractError("PR357_NEGATIVE_VARIANCE")


@dataclass(frozen=True, slots=True)
class InformationActionSpec:
    action_id: str
    evsi_units: int
    cost_units: int
    latency: int
    deadline: int
    mandatory_safety: bool
    provider_group: str
    failure_ppm: int = 0

    def __post_init__(self) -> None:
        if not self.action_id or not self.provider_group:
            raise PR357ContractError("PR357_INFORMATION_ACTION_ID_REQUIRED")
        if min(self.cost_units, self.latency, self.deadline, self.failure_ppm) < 0:
            raise PR357ContractError("PR357_INFORMATION_ACTION_NEGATIVE")
        if self.failure_ppm > PPM:
            raise PR357ContractError("PR357_FAILURE_PPM_RANGE")


def define_strategy_lifecycle_state(value: str) -> LifecycleState:
    try:
        return LifecycleState(value)
    except ValueError as exc:
        raise PR357ContractError("PR357_UNKNOWN_LIFECYCLE_STATE") from exc


def define_lifecycle_transition(
    previous_state: str,
    next_state: str,
) -> tuple[LifecycleState, LifecycleState]:
    previous = define_strategy_lifecycle_state(previous_state)
    nxt = define_strategy_lifecycle_state(next_state)
    if nxt not in _ALLOWED_TRANSITIONS[previous]:
        raise PR357ContractError("PR357_LIFECYCLE_TRANSITION_INVALID")
    return previous, nxt


def record_lifecycle_transition(
    *,
    strategy_id: str,
    previous_state: str,
    next_state: str,
    decision_time: int,
    reason: str,
    evidence_refs: Sequence[str],
) -> LifecycleTransitionReceipt:
    previous, nxt = define_lifecycle_transition(previous_state, next_state)
    return LifecycleTransitionReceipt(
        strategy_id=strategy_id,
        previous_state=previous,
        next_state=nxt,
        decision_time=decision_time,
        reason=reason,
        evidence_refs=tuple(evidence_refs),
    )


def reject_invalid_lifecycle_transition(
    previous_state: str,
    next_state: str,
) -> bool:
    try:
        define_lifecycle_transition(previous_state, next_state)
    except PR357ContractError:
        return True
    return False


def replay_lifecycle_history(
    initial_state: str,
    transitions: Sequence[LifecycleTransitionReceipt],
    as_of: int,
) -> LifecycleState:
    state = define_strategy_lifecycle_state(initial_state)
    last_time = -1
    for transition in sorted(
        transitions,
        key=lambda item: (item.decision_time, item.receipt_hash),
    ):
        if transition.decision_time > as_of:
            break
        if transition.decision_time < last_time:
            raise PR357ContractError("PR357_TRANSITION_TIME_REGRESSION")
        if transition.previous_state != state:
            raise PR357ContractError("PR357_TRANSITION_HISTORY_FORK")
        state = transition.next_state
        last_time = transition.decision_time
    return state


def compute_evidence_age_vector(
    *,
    now: int,
    evidence_available_at: int,
    current_deployment_generation: int,
    evidence_deployment_generation: int,
    current_source_schema_generation: int,
    evidence_source_schema_generation: int,
    current_topology_generation: int,
    evidence_topology_generation: int,
    regime_distance: int,
    current_model_generation: int,
    evidence_model_generation: int,
) -> EvidenceAgeVector:
    fields = (
        now,
        evidence_available_at,
        current_deployment_generation,
        evidence_deployment_generation,
        current_source_schema_generation,
        evidence_source_schema_generation,
        current_topology_generation,
        evidence_topology_generation,
        regime_distance,
        current_model_generation,
        evidence_model_generation,
    )
    if min(fields) < 0:
        raise PR357ContractError("PR357_EVIDENCE_AGE_INPUT_NEGATIVE")
    if evidence_available_at > now:
        raise PR357ContractError("PR357_EVIDENCE_FROM_FUTURE")
    generation_pairs = (
        (
            "DEPLOYMENT_GENERATION_CHANGED",
            current_deployment_generation,
            evidence_deployment_generation,
        ),
        (
            "SOURCE_SCHEMA_CHANGED",
            current_source_schema_generation,
            evidence_source_schema_generation,
        ),
        (
            "TOPOLOGY_GENERATION_CHANGED",
            current_topology_generation,
            evidence_topology_generation,
        ),
        (
            "MODEL_GENERATION_CHANGED",
            current_model_generation,
            evidence_model_generation,
        ),
    )
    invalidators = tuple(
        name
        for name, current, prior in generation_pairs
        if current != prior
    )
    return EvidenceAgeVector(
        wall_age=now - evidence_available_at,
        deployment_generation_age=abs(
            current_deployment_generation - evidence_deployment_generation
        ),
        source_schema_age=abs(
            current_source_schema_generation - evidence_source_schema_generation
        ),
        topology_age=abs(
            current_topology_generation - evidence_topology_generation
        ),
        regime_distance=regime_distance,
        model_generation_age=abs(
            current_model_generation - evidence_model_generation
        ),
        hard_invalidators=invalidators,
    )


def detect_evidence_invalidation_event(
    age: EvidenceAgeVector,
) -> tuple[str, ...]:
    return age.hard_invalidators


def estimate_strategy_survival_curve(
    durations: Sequence[int],
    failed: Sequence[bool],
) -> tuple[tuple[int, int], ...]:
    if len(durations) != len(failed) or not durations:
        raise PR357ContractError("PR357_SURVIVAL_INPUT_INVALID")
    if any(duration < 0 for duration in durations):
        raise PR357ContractError("PR357_SURVIVAL_DURATION_NEGATIVE")
    at_risk = len(durations)
    survival_ppm = PPM
    result: list[tuple[int, int]] = []
    for time in sorted(set(durations)):
        events = sum(
            1
            for duration, event in zip(durations, failed, strict=True)
            if duration == time and event
        )
        censored = sum(
            1
            for duration, event in zip(durations, failed, strict=True)
            if duration == time and not event
        )
        if at_risk <= 0:
            break
        if events:
            survival_ppm = survival_ppm * (at_risk - events) // at_risk
        result.append((time, survival_ppm))
        at_risk -= events + censored
    return tuple(result)


def detect_offline_change_point(
    values: Sequence[int],
    *,
    minimum_window: int,
    threshold_units: int,
) -> int | None:
    if minimum_window < 1 or threshold_units < 0:
        raise PR357ContractError("PR357_CHANGE_POINT_POLICY_INVALID")
    if len(values) < minimum_window * 2:
        return None
    best: tuple[int, int] | None = None
    for split in range(minimum_window, len(values) - minimum_window + 1):
        left = values[:split]
        right = values[split:]
        left_mean = sum(left) // len(left)
        right_mean = sum(right) // len(right)
        distance = abs(right_mean - left_mean)
        candidate = (distance, -split)
        if best is None or candidate > best:
            best = candidate
    assert best is not None
    distance, negative_split = best
    if distance < threshold_units:
        return None
    return -negative_split


def separate_data_break_from_market_regime(
    *,
    change_detected: bool,
    schema_generation_changed: bool,
    source_gap_detected: bool,
    independent_market_signal_count: int,
) -> str:
    if not change_detected:
        return "NO_CONFIRMED_BREAK"
    if schema_generation_changed or source_gap_detected:
        return "DATA_BREAK"
    if independent_market_signal_count >= 2:
        return "MARKET_REGIME_CANDIDATE"
    return "INCONCLUSIVE"


def apply_lifecycle_hysteresis(
    *,
    forward_score: int,
    reverse_score: int,
    forward_threshold: int,
    reverse_threshold: int,
) -> str:
    if min(forward_threshold, reverse_threshold) < 0:
        raise PR357ContractError("PR357_HYSTERESIS_THRESHOLD_NEGATIVE")
    if forward_score >= forward_threshold and reverse_score < reverse_threshold:
        return "FORWARD"
    if reverse_score >= reverse_threshold and forward_score < forward_threshold:
