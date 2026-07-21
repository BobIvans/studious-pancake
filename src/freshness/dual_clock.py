"""PR-127 dual-clock freshness and quote-expiry primitives.

Side-effect free: callers inject monotonic, UTC, slot and block-height evidence.
UTC is retained for audit display only; runtime validity uses monotonic time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

PR127_FRESHNESS_SCHEMA_VERSION = "pr127.dual-clock-freshness.v1"
_NS_PER_SECOND = 1_000_000_000


class PR127ClockError(ValueError):
    """Raised when PR-127 clock/freshness evidence is malformed."""


class PR127ExpiryMode(StrEnum):
    PROVIDER_NATIVE = "provider-native"
    LOCAL_MAX_AGE = "local-max-age"


class PR127FreshnessReason(StrEnum):
    FRESH = "fresh"
    QUOTE_EXPIRED = "quote-expired"
    CHAIN_SLOT_MISSING = "chain-slot-missing"
    QUOTE_SLOT_MISSING = "quote-slot-missing"
    CHAIN_SLOT_REGRESSED = "chain-slot-regressed"
    CROSS_SLOT_NOT_ALLOWED = "cross-slot-not-allowed"
    SLOT_DRIFT_EXCEEDED = "slot-drift-exceeded"
    BLOCK_HEIGHT_MISSING = "block-height-missing"
    BLOCK_HEIGHT_REGRESSED = "block-height-regressed"
    BLOCK_HEIGHT_DRIFT_EXCEEDED = "block-height-drift-exceeded"


class PR127ClockSkewIssue(StrEnum):
    MONOTONIC_CLOCK_REGRESSED = "monotonic-clock-regressed"
    WALL_CLOCK_MOVED_BACKWARD = "wall-clock-moved-backward"
    WALL_MONOTONIC_SKEW_EXCEEDED = "wall-monotonic-skew-exceeded"


@dataclass(frozen=True, slots=True)
class PR127ClockReading:
    monotonic_ns: int
    utc_datetime: datetime
    context_slot: int | None = None
    block_height: int | None = None
    source: str = "runtime"

    def __post_init__(self) -> None:
        _non_negative(self.monotonic_ns, "monotonic_ns")
        _aware(self.utc_datetime, "utc_datetime")
        if self.context_slot is not None:
            _non_negative(self.context_slot, "context_slot")
        if self.block_height is not None:
            _non_negative(self.block_height, "block_height")
        if not self.source.strip():
            raise PR127ClockError("clock source is required")

    @property
    def utc_iso(self) -> str:
        return _iso(self.utc_datetime)

    def to_audit_json(self) -> dict[str, object]:
        return {
            "monotonic_ns": str(self.monotonic_ns),
            "utc": self.utc_iso,
            "context_slot": self.context_slot,
            "block_height": self.block_height,
            "source": self.source,
        }


class PR127ReplayClock:
    def __init__(self, readings: tuple[PR127ClockReading, ...]) -> None:
        if not readings:
            raise PR127ClockError("replay clock requires at least one reading")
        self._readings = readings
        self._index = 0

    def now(self) -> PR127ClockReading:
        if self._index >= len(self._readings):
            raise PR127ClockError("replay clock exhausted")
        reading = self._readings[self._index]
        self._index += 1
        return reading


@dataclass(frozen=True, slots=True)
class PR127Deadline:
    started_at_monotonic_ns: int
    expires_at_monotonic_ns: int
    reason: str

    def __post_init__(self) -> None:
        _non_negative(self.started_at_monotonic_ns, "started_at_monotonic_ns")
        _non_negative(self.expires_at_monotonic_ns, "expires_at_monotonic_ns")
        if self.expires_at_monotonic_ns < self.started_at_monotonic_ns:
            raise PR127ClockError("deadline expiry cannot precede start")
        if not self.reason.strip():
            raise PR127ClockError("deadline reason is required")

    @classmethod
    def after(
        cls,
        reading: PR127ClockReading,
        *,
        duration_ns: int,
        reason: str,
    ) -> "PR127Deadline":
        _non_negative(duration_ns, "duration_ns")
        return cls(reading.monotonic_ns, reading.monotonic_ns + duration_ns, reason)

    def expired_at(self, reading: PR127ClockReading) -> bool:
        return reading.monotonic_ns >= self.expires_at_monotonic_ns

    def remaining_ns_at(self, reading: PR127ClockReading) -> int:
        return max(0, self.expires_at_monotonic_ns - reading.monotonic_ns)


@dataclass(frozen=True, slots=True)
class PR127Cooldown:
    key: str
    ready_at_monotonic_ns: int

    @classmethod
    def start(
        cls,
        reading: PR127ClockReading,
        *,
        key: str,
        duration_ns: int,
    ) -> "PR127Cooldown":
        if not key.strip():
            raise PR127ClockError("cooldown key is required")
        _non_negative(duration_ns, "duration_ns")
        return cls(key, reading.monotonic_ns + duration_ns)

    def ready_at(self, reading: PR127ClockReading) -> bool:
        return reading.monotonic_ns >= self.ready_at_monotonic_ns


@dataclass(frozen=True, slots=True)
class PR127Lease:
    resource_key: str
    owner_id: str
    acquired_at_monotonic_ns: int
    expires_at_monotonic_ns: int

    @classmethod
    def acquire(
        cls,
        reading: PR127ClockReading,
        *,
        resource_key: str,
        owner_id: str,
        ttl_ns: int,
    ) -> "PR127Lease":
        if not resource_key.strip() or not owner_id.strip():
            raise PR127ClockError("lease resource and owner are required")
        _positive(ttl_ns, "ttl_ns")
        return cls(
            resource_key, owner_id, reading.monotonic_ns, reading.monotonic_ns + ttl_ns
        )

    def active_at(self, reading: PR127ClockReading) -> bool:
        return reading.monotonic_ns < self.expires_at_monotonic_ns


@dataclass(frozen=True, slots=True)
class PR127CycleBudget:
    first_legs_ns: int
    exact_second_legs_ns: int
    final_build_ns: int
    compile_simulation_ns: int
    retry_overhead_ns: int = 0

    def __post_init__(self) -> None:
        _positive(self.first_legs_ns, "first_legs_ns")
        _positive(self.exact_second_legs_ns, "exact_second_legs_ns")
        _positive(self.final_build_ns, "final_build_ns")
        _positive(self.compile_simulation_ns, "compile_simulation_ns")
        _non_negative(self.retry_overhead_ns, "retry_overhead_ns")

    @property
    def total_budget_ns(self) -> int:
        return (
            self.first_legs_ns
            + self.exact_second_legs_ns
            + self.final_build_ns
            + self.compile_simulation_ns
            + self.retry_overhead_ns
        )

    def deadline_from(self, reading: PR127ClockReading) -> PR127Deadline:
        return PR127Deadline.after(
            reading,
            duration_ns=self.total_budget_ns,
            reason="pr127-cycle-budget",
        )


@dataclass(frozen=True, slots=True)
class PR127SlotPolicy:
    provider: str
    candidate_id: str
    allow_cross_slot: bool = False
    max_slot_drift: int = 0
    max_block_height_drift: int | None = None

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.candidate_id.strip():
            raise PR127ClockError("slot policy provider and candidate are required")
        _non_negative(self.max_slot_drift, "max_slot_drift")
        if self.max_block_height_drift is not None:
            _non_negative(self.max_block_height_drift, "max_block_height_drift")


@dataclass(frozen=True, slots=True)
class PR127QuoteFreshnessEvidence:
    provider: str
    candidate_id: str
    requested_at_monotonic_ns: int
    received_at: PR127ClockReading
    expiry_mode: PR127ExpiryMode
    expires_at_monotonic_ns: int
    source_reason: str
    provider_timestamp_utc: datetime | None = None
    provider_expires_at_utc: datetime | None = None
    context_slot: int | None = None
    block_height: int | None = None
    schema_version: str = PR127_FRESHNESS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PR127_FRESHNESS_SCHEMA_VERSION:
            raise PR127ClockError("unsupported PR-127 freshness schema")
        if not self.provider.strip() or not self.candidate_id.strip():
            raise PR127ClockError("provider and candidate_id are required")
        _non_negative(self.requested_at_monotonic_ns, "requested_at_monotonic_ns")
        if self.requested_at_monotonic_ns > self.received_at.monotonic_ns:
            raise PR127ClockError("request monotonic timestamp cannot follow receive")
        if not isinstance(self.expiry_mode, PR127ExpiryMode):
            object.__setattr__(
                self, "expiry_mode", PR127ExpiryMode(str(self.expiry_mode))
            )
        _positive(self.expires_at_monotonic_ns, "expires_at_monotonic_ns")
        if self.expires_at_monotonic_ns <= self.received_at.monotonic_ns:
            raise PR127ClockError("quote expiry must be bounded after receive")
        if not self.source_reason.strip():
            raise PR127ClockError("freshness source reason is required")
        _aware_optional(self.provider_timestamp_utc, "provider_timestamp_utc")
        _aware_optional(self.provider_expires_at_utc, "provider_expires_at_utc")
        if self.context_slot is not None:
            _non_negative(self.context_slot, "context_slot")
        if self.block_height is not None:
            _non_negative(self.block_height, "block_height")

    @classmethod
    def provider_native_expiry_after(
        cls,
        *,
        provider: str,
        candidate_id: str,
        requested_at_monotonic_ns: int,
        received_at: PR127ClockReading,
        expires_after_ns: int,
        source_reason: str,
        provider_timestamp_utc: datetime | None = None,
        provider_expires_at_utc: datetime | None = None,
    ) -> "PR127QuoteFreshnessEvidence":
        _positive(expires_after_ns, "expires_after_ns")
        return cls(
            provider=provider,
            candidate_id=candidate_id,
            requested_at_monotonic_ns=requested_at_monotonic_ns,
            received_at=received_at,
            expiry_mode=PR127ExpiryMode.PROVIDER_NATIVE,
            expires_at_monotonic_ns=received_at.monotonic_ns + expires_after_ns,
            source_reason=source_reason,
            provider_timestamp_utc=provider_timestamp_utc,
            provider_expires_at_utc=provider_expires_at_utc,
            context_slot=received_at.context_slot,
            block_height=received_at.block_height,
        )

    @classmethod
    def local_max_age(
        cls,
        *,
        provider: str,
        candidate_id: str,
        requested_at_monotonic_ns: int,
        received_at: PR127ClockReading,
        max_age_ns: int,
        source_reason: str,
        provider_timestamp_utc: datetime | None = None,
    ) -> "PR127QuoteFreshnessEvidence":
        _positive(max_age_ns, "max_age_ns")
        return cls(
            provider=provider,
            candidate_id=candidate_id,
            requested_at_monotonic_ns=requested_at_monotonic_ns,
            received_at=received_at,
            expiry_mode=PR127ExpiryMode.LOCAL_MAX_AGE,
            expires_at_monotonic_ns=received_at.monotonic_ns + max_age_ns,
            source_reason=source_reason,
            provider_timestamp_utc=provider_timestamp_utc,
            context_slot=received_at.context_slot,
            block_height=received_at.block_height,
        )

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "provider": self.provider,
            "candidate_id": self.candidate_id,
            "requested_at_monotonic_ns": str(self.requested_at_monotonic_ns),
            "received_at": self.received_at.to_audit_json(),
            "expiry_mode": self.expiry_mode.value,
            "expires_at_monotonic_ns": str(self.expires_at_monotonic_ns),
            "source_reason": self.source_reason,
            "provider_timestamp_utc": _iso_optional(self.provider_timestamp_utc),
            "provider_expires_at_utc": _iso_optional(self.provider_expires_at_utc),
            "context_slot": self.context_slot,
            "block_height": self.block_height,
        }


@dataclass(frozen=True, slots=True)
class PR127FreshnessDecision:
    allowed: bool
    reason: PR127FreshnessReason
    evidence: PR127QuoteFreshnessEvidence
    evaluated_at: PR127ClockReading
    policy: PR127SlotPolicy | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "reason": self.reason.value,
            "evidence": self.evidence.to_json(),
            "evaluated_at": self.evaluated_at.to_audit_json(),
            "policy": None if self.policy is None else _slot_policy_json(self.policy),
        }


def evaluate_pr127_quote_freshness(
    evidence: PR127QuoteFreshnessEvidence,
    *,
    evaluated_at: PR127ClockReading,
    policy: PR127SlotPolicy | None = None,
) -> PR127FreshnessDecision:
    if evaluated_at.monotonic_ns >= evidence.expires_at_monotonic_ns:
        reason = PR127FreshnessReason.QUOTE_EXPIRED
    else:
        reason = _slot_reason(evidence, evaluated_at, policy)
    return PR127FreshnessDecision(
        allowed=reason is PR127FreshnessReason.FRESH,
        reason=reason,
        evidence=evidence,
        evaluated_at=evaluated_at,
        policy=policy,
    )


def diagnose_pr127_clock_skew(
    previous: PR127ClockReading,
    current: PR127ClockReading,
    *,
    max_wall_monotonic_skew_ns: int,
) -> tuple[PR127ClockSkewIssue, ...]:
    _non_negative(max_wall_monotonic_skew_ns, "max_wall_monotonic_skew_ns")
    monotonic_delta = current.monotonic_ns - previous.monotonic_ns
    wall_delta = int(
        (current.utc_datetime - previous.utc_datetime).total_seconds() * _NS_PER_SECOND
    )
    issues: list[PR127ClockSkewIssue] = []
    if monotonic_delta < 0:
        issues.append(PR127ClockSkewIssue.MONOTONIC_CLOCK_REGRESSED)
    if wall_delta < 0:
        issues.append(PR127ClockSkewIssue.WALL_CLOCK_MOVED_BACKWARD)
    if abs(wall_delta - monotonic_delta) > max_wall_monotonic_skew_ns:
        issues.append(PR127ClockSkewIssue.WALL_MONOTONIC_SKEW_EXCEEDED)
    return tuple(dict.fromkeys(issues))


def _slot_reason(
    evidence: PR127QuoteFreshnessEvidence,
    evaluated_at: PR127ClockReading,
    policy: PR127SlotPolicy | None,
) -> PR127FreshnessReason:
    if policy is None:
        return PR127FreshnessReason.FRESH
    if evaluated_at.context_slot is None:
        return PR127FreshnessReason.CHAIN_SLOT_MISSING
    if evidence.context_slot is None:
        return PR127FreshnessReason.QUOTE_SLOT_MISSING
    if evaluated_at.context_slot < evidence.context_slot:
        return PR127FreshnessReason.CHAIN_SLOT_REGRESSED
    slot_drift = evaluated_at.context_slot - evidence.context_slot
    if not policy.allow_cross_slot and slot_drift != 0:
        return PR127FreshnessReason.CROSS_SLOT_NOT_ALLOWED
    if slot_drift > policy.max_slot_drift:
        return PR127FreshnessReason.SLOT_DRIFT_EXCEEDED
    if policy.max_block_height_drift is None:
        return PR127FreshnessReason.FRESH
    if evaluated_at.block_height is None or evidence.block_height is None:
        return PR127FreshnessReason.BLOCK_HEIGHT_MISSING
    if evaluated_at.block_height < evidence.block_height:
        return PR127FreshnessReason.BLOCK_HEIGHT_REGRESSED
    if (
        evaluated_at.block_height - evidence.block_height
        > policy.max_block_height_drift
    ):
        return PR127FreshnessReason.BLOCK_HEIGHT_DRIFT_EXCEEDED
    return PR127FreshnessReason.FRESH


def _slot_policy_json(policy: PR127SlotPolicy) -> dict[str, object]:
    return {
        "provider": policy.provider,
        "candidate_id": policy.candidate_id,
        "allow_cross_slot": policy.allow_cross_slot,
        "max_slot_drift": policy.max_slot_drift,
        "max_block_height_drift": policy.max_block_height_drift,
    }


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _iso_optional(value: datetime | None) -> str | None:
    return None if value is None else _iso(value)


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PR127ClockError(f"{field} must be timezone-aware")


def _aware_optional(value: datetime | None, field: str) -> None:
    if value is not None:
        _aware(value, field)


def _non_negative(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PR127ClockError(f"{field} must be a non-negative integer")


def _positive(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PR127ClockError(f"{field} must be a positive integer")


__all__ = [
    "PR127ClockError",
    "PR127ClockReading",
    "PR127ClockSkewIssue",
    "PR127Cooldown",
    "PR127CycleBudget",
    "PR127Deadline",
    "PR127ExpiryMode",
    "PR127FreshnessDecision",
    "PR127FreshnessReason",
    "PR127Lease",
    "PR127QuoteFreshnessEvidence",
    "PR127ReplayClock",
    "PR127SlotPolicy",
    "diagnose_pr127_clock_skew",
    "evaluate_pr127_quote_freshness",
]
