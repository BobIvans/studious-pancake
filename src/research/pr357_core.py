"""Deterministic PR-357 research primitives.

This module implements the semantic core used by lifecycle, bootstrap,
point-in-time world-model, and decision-intelligence adapters.  It is offline,
stdlib-only, deterministic, and research-only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from math import sqrt
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
        if any(
            isinstance(value, bool) or not isinstance(value, int) for value in values
        ):
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
        missing_clocks = sorted(set(self.observed) - set(self.source_clocks))
        if missing_clocks:
            raise PR357ContractError(
                "PR357_OBSERVED_CLOCK_MISSING:" + ",".join(missing_clocks)
            )
        for name, clock in self.source_clocks.items():
            if clock.available_at > self.decision_time:
                raise PR357ContractError(f"PR357_LOOKAHEAD_OBSERVATION:{name}")
        names = set(self.posterior_mean)
        if set(self.covariance) != names:
            raise PR357ContractError("PR357_COVARIANCE_ROW_MISMATCH")
        for row_name, row in self.covariance.items():
            if set(row) != names:
                raise PR357ContractError(f"PR357_COVARIANCE_COLUMN_MISMATCH:{row_name}")
            if row[row_name] < 0:
                raise PR357ContractError("PR357_NEGATIVE_VARIANCE")
            for column_name, value in row.items():
                if value != self.covariance[column_name][row_name]:
                    raise PR357ContractError("PR357_COVARIANCE_ASYMMETRIC")


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
    for transition in transitions:
        if transition.decision_time < last_time:
            raise PR357ContractError("PR357_TRANSITION_TIME_REGRESSION")
        if transition.decision_time > as_of:
            break
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
        name for name, current, prior in generation_pairs if current != prior
    )
    return EvidenceAgeVector(
        wall_age=now - evidence_available_at,
        deployment_generation_age=abs(
            current_deployment_generation - evidence_deployment_generation
        ),
        source_schema_age=abs(
            current_source_schema_generation - evidence_source_schema_generation
        ),
        topology_age=abs(current_topology_generation - evidence_topology_generation),
        regime_distance=regime_distance,
        model_generation_age=abs(current_model_generation - evidence_model_generation),
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
        return "REVERSE"
    return "HOLD"


def compute_semantic_delta(
    parent: Mapping[str, Any],
    successor: Mapping[str, Any],
) -> Mapping[str, tuple[Any, Any]]:
    keys = sorted(set(parent) | set(successor))
    return {
        key: (parent.get(key), successor.get(key))
        for key in keys
        if parent.get(key) != successor.get(key)
    }


def classify_evidence_inheritance(
    semantic_delta: Mapping[str, tuple[Any, Any]],
) -> str:
    hard = {
        "mechanism",
        "economic_rights",
        "execution_domain",
        "settlement",
        "source_schema",
    }
    if hard.intersection(semantic_delta):
        return "INVALID"
    if semantic_delta:
        return "PARTIAL"
    return "REUSABLE"


def decompose_strategy_degradation(
    components: Mapping[str, int],
) -> Mapping[str, int]:
    allowed = {
        "source",
        "latency",
        "crowding",
        "capacity",
        "fee",
        "model",
        "semantic",
        "regime",
        "unknown",
    }
    unknown = set(components) - allowed
    if unknown:
        raise PR357ContractError(
            "PR357_UNKNOWN_DEGRADATION_COMPONENT:" + ",".join(sorted(unknown))
        )
    return {key: int(components.get(key, 0)) for key in sorted(allowed)}


def define_market_bootstrap_descriptor(
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    required = {
        "market_id",
        "chain_or_domain",
        "instrument_type",
        "underlying",
        "settlement",
        "economic_rights",
        "execution_domain",
        "information_domain",
        "access_domain",
        "risk_domain",
        "descriptor_version",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise PR357ContractError(
            "PR357_BOOTSTRAP_DESCRIPTOR_MISSING:" + ",".join(missing)
        )
    result = {key: payload[key] for key in sorted(payload)}
    result["execution_right"] = False
    return result


def canonicalize_market_descriptor(
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    result = dict(define_market_bootstrap_descriptor(payload))
    for key, value in tuple(result.items()):
        if isinstance(value, str):
            result[key] = " ".join(value.strip().lower().split())
    return result


def score_prior_applicability(prior: PriorCandidate) -> int:
    base = (
        prior.semantic_similarity_ppm * 4
        + prior.topology_similarity_ppm * 3
        + prior.source_similarity_ppm * 2
        + prior.freshness_ppm
    ) // 10
    penalty = min(PPM, prior.negative_transfer_count * 100_000)
    if not prior.rights_compatible:
        return 0
    return max(0, base - penalty)


def filter_stale_or_invalid_prior(
    prior: PriorCandidate,
    *,
    minimum_freshness_ppm: int = 500_000,
) -> bool:
    return (
        prior.rights_compatible
        and prior.freshness_ppm >= minimum_freshness_ppm
        and score_prior_applicability(prior) > 0
    )


def rank_bootstrap_prior_set(
    priors: Sequence[PriorCandidate],
) -> tuple[str, ...]:
    eligible = [prior for prior in priors if filter_stale_or_invalid_prior(prior)]
    eligible.sort(
        key=lambda prior: (
            -score_prior_applicability(prior),
            prior.prior_id,
        )
    )
    return tuple(prior.prior_id for prior in eligible)


def detect_calibration_negative_transfer(
    *,
    prior_error_units: int,
    target_only_error_units: int,
) -> bool:
    return prior_error_units > target_only_error_units


def fallback_to_target_only_uncertainty(
    *,
    prior_error_units: int,
    target_only_error_units: int,
    prior_uncertainty_units: int,
    target_uncertainty_units: int,
) -> int:
    if detect_calibration_negative_transfer(
        prior_error_units=prior_error_units,
        target_only_error_units=target_only_error_units,
    ):
        return target_uncertainty_units
    return max(prior_uncertainty_units, target_uncertainty_units)


def detect_semantic_schema_collision(
    left: Mapping[str, str],
    right: Mapping[str, str],
) -> tuple[str, ...]:
    return tuple(
        key for key in sorted(set(left) & set(right)) if left[key] != right[key]
    )


def verify_timestamp_semantics(clock: ObservationClock) -> bool:
    return (
        clock.event_time
        <= clock.published_at
        <= clock.received_at
        <= clock.available_at
    )


def quarantine_unmapped_fields(
    source: Mapping[str, Any],
    mapping: Mapping[str, str],
) -> Mapping[str, Any]:
    return {key: source[key] for key in sorted(source) if key not in mapping}


def define_market_belief_state(
    *,
    belief_id: str,
    decision_time: int,
    observed: Mapping[str, int],
    posterior_mean: Mapping[str, int],
    covariance: Mapping[str, Mapping[str, int]],
    missingness_mask: Mapping[str, bool],
    source_clocks: Mapping[str, ObservationClock],
    valid_until: int,
) -> BeliefState:
    return BeliefState(
        belief_id=belief_id,
        decision_time=decision_time,
        observed=dict(observed),
        posterior_mean=dict(posterior_mean),
        covariance={key: dict(value) for key, value in covariance.items()},
        missingness_mask=dict(missingness_mask),
        source_clocks=dict(source_clocks),
        valid_until=valid_until,
    )


def bind_to_pit_snapshot(
    observations: Mapping[str, tuple[int, ObservationClock]],
    *,
    decision_time: int,
) -> Mapping[str, int]:
    selected: dict[str, int] = {}
    for name, (value, clock) in sorted(observations.items()):
        if clock.available_at <= decision_time:
            selected[name] = value
    return selected


def represent_missing_unknown_state(
    variable_names: Iterable[str],
    observed: Mapping[str, int],
) -> Mapping[str, bool]:
    return {name: name not in observed for name in sorted(set(variable_names))}


def represent_state_covariance(
    variables: Sequence[str],
    variances: Mapping[str, int],
    cross_covariance: Mapping[tuple[str, str], int] | None = None,
) -> Mapping[str, Mapping[str, int]]:
    cross_covariance = cross_covariance or {}
    rows: dict[str, dict[str, int]] = {}
    for left in variables:
        row: dict[str, int] = {}
        for right in variables:
            if left == right:
                value = int(variances[left])
            else:
                value = int(
                    cross_covariance.get(
                        (left, right),
                        cross_covariance.get((right, left), 0),
                    )
                )
            row[right] = value
        rows[left] = row
    return rows


def update_belief_with_observation(
    belief: BeliefState,
    *,
    variable: str,
    value: int,
    clock: ObservationClock,
    posterior_variance: int,
) -> BeliefState:
    if clock.available_at > belief.decision_time:
        raise PR357ContractError("PR357_FUTURE_BELIEF_UPDATE")
    means = dict(belief.posterior_mean)
    means[variable] = value
    observed = dict(belief.observed)
    observed[variable] = value
    missing = dict(belief.missingness_mask)
    missing[variable] = False
    clocks = dict(belief.source_clocks)
    clocks[variable] = clock
    covariance = {key: dict(row) for key, row in belief.covariance.items()}
    if variable not in covariance:
        for row in covariance.values():
            row[variable] = 0
        covariance[variable] = {key: 0 for key in means}
    covariance[variable][variable] = posterior_variance
    return define_market_belief_state(
        belief_id=belief.belief_id,
        decision_time=belief.decision_time,
        observed=observed,
        posterior_mean=means,
        covariance=covariance,
        missingness_mask=missing,
        source_clocks=clocks,
        valid_until=belief.valid_until,
    )


def widen_uncertainty_under_missingness(
    covariance: Mapping[str, Mapping[str, int]],
    missingness_mask: Mapping[str, bool],
    *,
    factor_ppm: int,
) -> Mapping[str, Mapping[str, int]]:
    if factor_ppm < PPM:
        raise PR357ContractError("PR357_MISSINGNESS_FACTOR_MUST_WIDEN")
    result = {name: dict(row) for name, row in covariance.items()}
    for name, missing in missingness_mask.items():
        if missing and name in result and name in result[name]:
            result[name][name] = result[name][name] * factor_ppm // PPM
    return result


def avoid_future_backfill_leakage(
    clock: ObservationClock,
    *,
    decision_time: int,
) -> bool:
    return clock.available_at <= decision_time


def _cholesky_factor(
    belief: BeliefState,
    names: Sequence[str],
) -> tuple[tuple[float, ...], ...]:
    matrix = [
        [float(belief.covariance[left][right]) for right in names] for left in names
    ]
    lower = [[0.0 for _ in names] for _ in names]
    for row in range(len(names)):
        for column in range(row + 1):
            residual = matrix[row][column] - sum(
                lower[row][index] * lower[column][index] for index in range(column)
            )
            if row == column:
                if residual < -1e-9:
                    raise PR357ContractError("PR357_COVARIANCE_NOT_PSD")
                lower[row][column] = sqrt(max(0.0, residual))
            elif lower[column][column] == 0.0:
                if abs(residual) > 1e-9:
                    raise PR357ContractError("PR357_COVARIANCE_NOT_PSD")
            else:
                lower[row][column] = residual / lower[column][column]
    return tuple(tuple(row) for row in lower)


def generate_joint_predictive_distribution(
    belief: BeliefState,
    *,
    sample_count: int,
    seed: int,
) -> tuple[Mapping[str, int], ...]:
    if sample_count < 1:
        raise PR357ContractError("PR357_SCENARIO_SAMPLE_COUNT")
    rng = random.Random(seed)
    names = tuple(sorted(belief.posterior_mean))
    lower = _cholesky_factor(belief, names)
    rows: list[Mapping[str, int]] = []
    for _ in range(sample_count):
        independent = [rng.gauss(0.0, 1.0) for _ in names]
        sample: dict[str, int] = {}
        for row, name in enumerate(names):
            delta = sum(
                lower[row][column] * independent[column] for column in range(row + 1)
            )
            sample[name] = int(round(belief.posterior_mean[name] + delta))
        rows.append(sample)
    return tuple(rows)


def preserve_scenario_provenance(
    *,
    belief: BeliefState,
    seed: int,
    samples: Sequence[Mapping[str, int]],
) -> Mapping[str, Any]:
    return {
        "belief_id": belief.belief_id,
        "decision_time": belief.decision_time,
        "seed": seed,
        "sample_count": len(samples),
        "sample_hash": canonical_hash(tuple(samples)),
        "execution_right": False,
    }


def measure_joint_calibration(
    predicted: Sequence[Mapping[str, int]],
    realized: Sequence[Mapping[str, int]],
) -> Mapping[str, int]:
    if len(predicted) != len(realized) or not predicted:
        raise PR357ContractError("PR357_CALIBRATION_INPUT_INVALID")
    errors: dict[str, list[int]] = {}
    for forecast, actual in zip(predicted, realized, strict=True):
        for name in set(forecast) & set(actual):
            errors.setdefault(name, []).append(
                abs(int(forecast[name]) - int(actual[name]))
            )
    return {name: sum(values) // len(values) for name, values in sorted(errors.items())}


def downgrade_unsupported_counterfactual(
    *,
    identifiable: bool,
    support_overlap_ppm: int,
    minimum_overlap_ppm: int,
) -> str:
    if not identifiable:
        return "INCONCLUSIVE"
    if support_overlap_ppm < minimum_overlap_ppm:
        return "INCONCLUSIVE"
    return "SUPPORTED_RESEARCH_ONLY"


def define_decision_problem(
    *,
    actions: Mapping[str, Mapping[str, int]],
    state_probabilities_ppm: Mapping[str, int],
    deadline: int,
    mandatory_safety: Sequence[str],
) -> Mapping[str, Any]:
    if not actions or not state_probabilities_ppm:
        raise PR357ContractError("PR357_DECISION_PROBLEM_EMPTY")
    if any(
        probability < 0 or probability > PPM
        for probability in state_probabilities_ppm.values()
    ):
        raise PR357ContractError("PR357_STATE_PROBABILITY_RANGE")
    if sum(state_probabilities_ppm.values()) != PPM:
        raise PR357ContractError("PR357_STATE_PROBABILITIES_NOT_NORMALIZED")
    states = set(state_probabilities_ppm)
    for action, losses in actions.items():
        if set(losses) != states:
            raise PR357ContractError(f"PR357_ACTION_STATE_MISMATCH:{action}")
    return {
        "actions": {key: dict(value) for key, value in sorted(actions.items())},
        "state_probabilities_ppm": dict(sorted(state_probabilities_ppm.items())),
        "deadline": deadline,
        "mandatory_safety": tuple(sorted(mandatory_safety)),
        "execution_right": False,
    }


def _expected_loss(
    losses: Mapping[str, int],
    probabilities_ppm: Mapping[str, int],
) -> int:
    return (
        sum(losses[state] * probabilities_ppm[state] for state in probabilities_ppm)
        // PPM
    )


def compute_current_bayes_action(
    decision_problem: Mapping[str, Any],
) -> tuple[str, int]:
    probabilities = decision_problem["state_probabilities_ppm"]
    scored = [
        (
            _expected_loss(losses, probabilities),
            action,
        )
        for action, losses in decision_problem["actions"].items()
    ]
    loss, action = min(scored)
    return action, loss


def estimate_decision_regret(
    decision_problem: Mapping[str, Any],
    chosen_action: str,
) -> int:
    probabilities = decision_problem["state_probabilities_ppm"]
    chosen = _expected_loss(
        decision_problem["actions"][chosen_action],
        probabilities,
    )
    _, best = compute_current_bayes_action(decision_problem)
    return chosen - best


def estimate_evpi(decision_problem: Mapping[str, Any]) -> int:
    _, current_loss = compute_current_bayes_action(decision_problem)
    probabilities = decision_problem["state_probabilities_ppm"]
    perfect_loss = 0
    for state, probability in probabilities.items():
        state_minimum = min(
            losses[state] for losses in decision_problem["actions"].values()
        )
        perfect_loss += state_minimum * probability
    perfect_loss //= PPM
    return max(0, current_loss - perfect_loss)


def estimate_evsi(
    decision_problem: Mapping[str, Any],
    *,
    posterior_scenarios: Sequence[Mapping[str, int]],
    observation_probabilities_ppm: Sequence[int],
) -> int:
    if (
        len(posterior_scenarios) != len(observation_probabilities_ppm)
        or not posterior_scenarios
    ):
        raise PR357ContractError("PR357_EVSI_SCENARIOS_INVALID")
    if sum(observation_probabilities_ppm) != PPM:
        raise PR357ContractError("PR357_EVSI_PROBABILITIES_NOT_NORMALIZED")
    _, current_loss = compute_current_bayes_action(decision_problem)
    prior = decision_problem["state_probabilities_ppm"]
    states = set(prior)
    mixture_numerators = {state: 0 for state in states}
    expected_posterior_loss = 0
    for posterior, weight in zip(
        posterior_scenarios,
        observation_probabilities_ppm,
        strict=True,
    ):
        if set(posterior) != states:
            raise PR357ContractError("PR357_POSTERIOR_STATE_MISMATCH")
        if any(
            probability < 0 or probability > PPM for probability in posterior.values()
        ):
            raise PR357ContractError("PR357_POSTERIOR_PROBABILITY_RANGE")
        if sum(posterior.values()) != PPM:
            raise PR357ContractError("PR357_POSTERIOR_NOT_NORMALIZED")
        for state in states:
            mixture_numerators[state] += posterior[state] * weight
        candidate = dict(decision_problem)
        candidate["state_probabilities_ppm"] = dict(posterior)
        _, loss = compute_current_bayes_action(candidate)
        expected_posterior_loss += loss * weight
    for state, prior_probability in prior.items():
        if abs(mixture_numerators[state] - prior_probability * PPM) > PPM:
            raise PR357ContractError(f"PR357_POSTERIOR_MIXTURE_INCOHERENT:{state}")
    expected_posterior_loss //= PPM
    return max(0, current_loss - expected_posterior_loss)


def subtract_information_cost(evsi_units: int, cost_units: int) -> int:
    return evsi_units - cost_units


def bound_voi_by_deadline(
    value_units: int,
    *,
    completion_time: int,
    deadline: int,
) -> int:
    if completion_time > deadline:
        return 0
    return value_units


def estimate_source_redundancy(
    shared_information_ppm: int,
) -> int:
    if not 0 <= shared_information_ppm <= PPM:
        raise PR357ContractError("PR357_REDUNDANCY_PPM_RANGE")
    return shared_information_ppm


def estimate_provider_common_failure(
    actions: Sequence[InformationActionSpec],
) -> Mapping[str, int]:
    groups: dict[str, list[int]] = {}
    for action in actions:
        groups.setdefault(action.provider_group, []).append(action.failure_ppm)
    return {group: max(values) for group, values in sorted(groups.items())}


def detect_double_counted_information(
    action_ids: Sequence[str],
    redundancy_pairs: Mapping[tuple[str, str], int],
    *,
    threshold_ppm: int,
) -> tuple[tuple[str, str], ...]:
    selected = set(action_ids)
    duplicates: list[tuple[str, str]] = []
    for pair, value in redundancy_pairs.items():
        left, right = pair
        if left in selected and right in selected and value >= threshold_ppm:
            duplicates.append((left, right) if left <= right else (right, left))
    return tuple(sorted(set(duplicates)))


def compute_deadline_adjusted_evsi(action: InformationActionSpec) -> int:
    value = bound_voi_by_deadline(
        action.evsi_units,
        completion_time=action.latency,
        deadline=action.deadline,
    )
    failure_adjusted = value * (PPM - action.failure_ppm) // PPM
    return failure_adjusted - action.cost_units


def reject_too_late_information(action: InformationActionSpec) -> bool:
    return action.latency > action.deadline


def estimate_value_of_computation(
    *,
    expected_decision_improvement_units: int,
    compute_cost_units: int,
    latency_penalty_units: int,
) -> int:
    return (
        expected_decision_improvement_units - compute_cost_units - latency_penalty_units
    )


def stop_computation_on_decision_stability(
    rankings: Sequence[Sequence[str]],
    *,
    stable_rounds: int,
) -> bool:
    if stable_rounds < 2 or len(rankings) < stable_rounds:
        return False
    tail = [tuple(row) for row in rankings[-stable_rounds:]]
    return len(set(tail)) == 1


def preserve_mandatory_safety_features(
    requested: Sequence[str],
    mandatory: Sequence[str],
) -> tuple[str, ...]:
    return tuple(sorted(set(requested) | set(mandatory)))


def reserve_safety_information_budget(
    actions: Sequence[InformationActionSpec],
    *,
    budget_units: int,
) -> Mapping[str, Any]:
    if budget_units < 0:
        raise PR357ContractError("PR357_SAFETY_BUDGET_NEGATIVE")
    mandatory = sorted(
        (action for action in actions if action.mandatory_safety),
        key=lambda action: action.action_id,
    )
    required = sum(action.cost_units for action in mandatory)
    if required > budget_units:
        return {
            "status": "ABSTAIN",
            "reason": "MANDATORY_SAFETY_BUDGET_UNAVAILABLE",
            "selected": (),
            "execution_right": False,
        }
    if any(reject_too_late_information(action) for action in mandatory):
        return {
            "status": "ABSTAIN",
            "reason": "MANDATORY_SAFETY_MISSES_DEADLINE",
            "selected": (),
            "execution_right": False,
        }
    selected = list(mandatory)
    remaining = budget_units - required
    optional = sorted(
        (action for action in actions if not action.mandatory_safety),
        key=lambda action: (
            -compute_deadline_adjusted_evsi(action),
            action.action_id,
        ),
    )
    for action in optional:
        if compute_deadline_adjusted_evsi(action) <= 0:
            continue
        if action.cost_units <= remaining:
            selected.append(action)
            remaining -= action.cost_units
    return {
        "status": "PLANNED",
        "selected": tuple(action.action_id for action in selected),
        "remaining_budget": remaining,
        "execution_right": False,
    }


def block_decision_without_safety_info(
    observed: Sequence[str],
    mandatory: Sequence[str],
) -> bool:
    return not set(mandatory).issubset(set(observed))


def force_abstention_on_unknown_safety(
    observed: Sequence[str],
    mandatory: Sequence[str],
) -> str:
    if block_decision_without_safety_info(observed, mandatory):
        return "ABSTAIN"
    return "RESEARCH_DECISION_ALLOWED"


def measure_decision_regret_and_cost(
    *,
    regret_units: int,
    information_cost_units: int,
    compute_cost_units: int,
    deadline_loss_units: int,
) -> Mapping[str, int]:
    values = {
        "decision_regret": regret_units,
        "information_cost": information_cost_units,
        "compute_cost": compute_cost_units,
        "deadline_loss": deadline_loss_units,
    }
    if min(values.values()) < 0:
        raise PR357ContractError("PR357_DECISION_SCORE_NEGATIVE")
    values["total_loss"] = sum(values.values())
    return values


def assert_research_only_effect_boundary(
    payload: Mapping[str, Any],
) -> None:
    for key, expected in EFFECT_BOUNDARY.items():
        if payload.get(key, expected) is not expected:
            raise PR357ContractError(f"PR357_EFFECT_AUTHORITY_FORBIDDEN:{key}")


def effect_boundary() -> Mapping[str, bool]:
    return dict(EFFECT_BOUNDARY)


def deterministic_receipt(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    body = dict(payload)
    body["execution_right"] = False
    body["receipt_hash"] = canonical_hash(body)
    return body
