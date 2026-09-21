"""MEGA8-07 shared offline performance, data and capital contracts.

This package is deliberately sender-free and effect-free. It consumes already
captured evidence/state and emits deterministic research/control artifacts only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Mapping, Sequence

from src.research.common import (
    OFFLINE_RESEARCH_BOUNDARY,
    hash_json,
    require_id,
    require_nonnegative,
    require_positive,
    require_sha256,
    require_text,
)


class Mega807Error(ValueError):
    """Fail-closed MEGA8-07 contract violation."""


class Disposition(StrEnum):
    IMPLEMENTED_OFFLINE = "implemented-offline"
    RESEARCH_ONLY = "research-only"
    BLOCKED = "blocked"


def stable_hash(domain: str, value: object) -> str:
    return hash_json(domain, value)


@dataclass(frozen=True, slots=True)
class EvidenceBinding:
    evidence_id: str
    artifact_sha256: str
    generation: str
    policy_generation: str
    observed_at: int
    expires_at: int
    verified: bool = True
    live_enabled: bool = False
    capital_authority: bool = False

    def __post_init__(self) -> None:
        require_id(self.evidence_id, "evidence_id")
        require_sha256(self.artifact_sha256, "artifact_sha256")
        require_id(self.generation, "generation")
        require_id(self.policy_generation, "policy_generation")
        require_nonnegative(self.observed_at, "observed_at")
        require_positive(self.expires_at, "expires_at")
        if self.expires_at <= self.observed_at:
            raise Mega807Error("EVIDENCE_EXPIRY_INVALID")
        if self.live_enabled or self.capital_authority:
            raise Mega807Error("MEGA8_07_CANNOT_GRANT_AUTHORITY")
        if OFFLINE_RESEARCH_BOUNDARY.signing or OFFLINE_RESEARCH_BOUNDARY.submission:
            raise Mega807Error("OFFLINE_BOUNDARY_CORRUPTED")

    def assert_usable(self, *, now: int) -> None:
        require_nonnegative(now, "now")
        if not self.verified:
            raise Mega807Error("UNVERIFIED_EVIDENCE")
        if now < self.observed_at:
            raise Mega807Error("FUTURE_EVIDENCE")
        if now >= self.expires_at:
            raise Mega807Error("STALE_EVIDENCE")

    @property
    def identity(self) -> str:
        return stable_hash("mega8-07-evidence", asdict(self))


@dataclass(frozen=True, slots=True)
class OfflineResult:
    operation: str
    evidence_identity: str
    payload_sha256: str
    disposition: Disposition
    reason: str
    live_enabled: bool = False
    capital_authority: bool = False

    def __post_init__(self) -> None:
        require_id(self.operation, "operation")
        require_sha256(self.evidence_identity, "evidence_identity")
        require_sha256(self.payload_sha256, "payload_sha256")
        require_text(self.reason, "reason")
        if self.live_enabled or self.capital_authority:
            raise Mega807Error("RESULT_CANNOT_GRANT_AUTHORITY")


def offline_result(
    operation: str,
    evidence: EvidenceBinding,
    payload: object,
    *,
    now: int,
    reason: str = "OFFLINE_CONTRACT_SATISFIED",
    disposition: Disposition = Disposition.IMPLEMENTED_OFFLINE,
) -> OfflineResult:
    evidence.assert_usable(now=now)
    return OfflineResult(
        operation=operation,
        evidence_identity=evidence.identity,
        payload_sha256=stable_hash(operation, payload),
        disposition=disposition,
        reason=reason,
    )


@dataclass(frozen=True, slots=True)
class StateSlice:
    slice_id: str
    generation: str
    content_sha256: str
    evidence_identity: str
    payload: Mapping[str, int | str]

    def __post_init__(self) -> None:
        require_id(self.slice_id, "slice_id")
        require_id(self.generation, "generation")
        require_sha256(self.content_sha256, "content_sha256")
        require_sha256(self.evidence_identity, "evidence_identity")


@dataclass(frozen=True, slots=True)
class ResearchJob:
    job_id: str
    workload_sha256: str
    shard: int
    shard_count: int

    def __post_init__(self) -> None:
        require_id(self.job_id, "job_id")
        require_sha256(self.workload_sha256, "workload_sha256")
        require_nonnegative(self.shard, "shard")
        require_positive(self.shard_count, "shard_count")
        if self.shard >= self.shard_count:
            raise Mega807Error("INVALID_SHARD")


@dataclass(frozen=True, slots=True)
class CapitalEvidence:
    finalized_profit: int
    protected_reserve: int
    available_balance: int
    capacity_limit: int
    evidence: EvidenceBinding

    def __post_init__(self) -> None:
        for field in (
            "finalized_profit",
            "protected_reserve",
            "available_balance",
            "capacity_limit",
        ):
            require_nonnegative(getattr(self, field), field)


@dataclass(frozen=True, slots=True)
class LenderCapacity:
    lender_id: str
    asset_id: str
    observed_capacity: int
    conservative_capacity: int
    generation: str
    evidence: EvidenceBinding

    def __post_init__(self) -> None:
        require_id(self.lender_id, "lender_id")
        require_id(self.asset_id, "asset_id")
        require_nonnegative(self.observed_capacity, "observed_capacity")
        require_nonnegative(self.conservative_capacity, "conservative_capacity")
        require_id(self.generation, "generation")
        if self.conservative_capacity > self.observed_capacity:
            raise Mega807Error("CONSERVATIVE_CAPACITY_EXCEEDS_OBSERVED")


@dataclass(frozen=True, slots=True)
class MarginRequirement:
    venue_id: str
    asset_id: str
    initial_margin_ppm: int
    maintenance_margin_ppm: int

    def __post_init__(self) -> None:
        require_id(self.venue_id, "venue_id")
        require_id(self.asset_id, "asset_id")
        require_nonnegative(self.initial_margin_ppm, "initial_margin_ppm")
        require_nonnegative(self.maintenance_margin_ppm, "maintenance_margin_ppm")
        if not 0 <= self.maintenance_margin_ppm <= self.initial_margin_ppm <= 1_000_000:
            raise Mega807Error("INVALID_MARGIN_REQUIREMENT")


@dataclass(frozen=True, slots=True)
class RatePoint:
    market_id: str
    asset_id: str
    supply_rate_ppm: int
    borrow_rate_ppm: int
    capacity: int
    available_at: int

    def __post_init__(self) -> None:
        require_id(self.market_id, "market_id")
        require_id(self.asset_id, "asset_id")
        require_nonnegative(self.supply_rate_ppm, "supply_rate_ppm")
        require_nonnegative(self.borrow_rate_ppm, "borrow_rate_ppm")
        require_nonnegative(self.capacity, "capacity")
        require_nonnegative(self.available_at, "available_at")


def bounded_sum(values: Sequence[int], *, field: str) -> int:
    total = 0
    for value in values:
        total += require_nonnegative(value, field)
    return total
