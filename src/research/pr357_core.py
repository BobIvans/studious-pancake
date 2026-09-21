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
