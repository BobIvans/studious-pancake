"""PR-127 dual-clock freshness and provenance contract.

Side-effect-free timing boundary: callers pass captured monotonic/UTC/slot
values. This module never reads clocks, sleeps, talks to providers, signs, or
submits transactions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json
import re
from typing import Any

PR127_FRESHNESS_SCHEMA_VERSION = "pr127.dual-clock-freshness.v1"

_PROVIDER_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{1,63}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_NS = 2**63 - 1


class PR127FreshnessReason(StrEnum):
    FRESH = "fresh"
    CURRENT_MONOTONIC_BEFORE_RECEIVED = "current-monotonic-before-received"
    PROVIDER_NATIVE_EXPIRED = "provider-native-expired"
    LOCAL_MAX_AGE_EXPIRED = "local-max-age-expired"
    MISSING_PROVIDER_OR_LOCAL_EXPIRY = "missing-provider-or-local-expiry"
    CONTEXT_SLOT_TOO_OLD = "context-slot-too-old"
    BLOCK_HEIGHT_TOO_OLD = "block-height-too-old"


class PR127DeadlineReason(StrEnum):
    WITHIN_DEADLINE = "within-deadline"
    DEADLINE_EXPIRED = "deadline-expired"
    CURRENT_MONOTONIC_BEFORE_START = "current-monotonic-before-start"


class PR127ClockSkewStatus(StrEnum):
    OK = "ok"
    SKEWED = "skewed"


@dataclass(frozen=True, slots=True)
class PR127ClockSnapshot:
    monotonic_ns: int
    utc_wall: datetime
    context_slot: int | None = None
    block_height: int | None = None

    def __post_init__(self) -> None:
        _strict_ns(self.monotonic_ns, "monotonic_ns")
        _utc(self.utc_wall, "utc_wall")
        if self.context_slot is not None:
            _strict_non_negative_int(self.context_slot, "context_slot")
        if self.block_height is not None:
            _strict_non_negative_int(self.block_height, "block_height")

    def to_json(self) -> dict[str, object]:
        return {
            "monotonic_ns": str(self.monotonic_ns),
            "utc_wall": _iso_utc(self.utc_wall),
            "context_slot": self.context_slot,
            "block_height": self.block_height,
        }


@dataclass(frozen=True, slots=True)
class PR127QuoteFreshnessPolicy:
    provider: str
    conservative_local_max_age_ns: int | None
    max_context_slot_delta: int | None = None
    max_block_height_delta: int | None = None
    require_provider_native_expiry: bool = False
    source: str = "local-policy"
    reason: str = "bounded provider freshness"

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _provider(self.provider))
        if self.conservative_local_max_age_ns is not None:
            _strict_positive_ns(
                self.conservative_local_max_age_ns,
                "conservative_local_max_age_ns",
            )
        if self.max_context_slot_delta is not None:
            _strict_non_negative_int(
                self.max_context_slot_delta,
                "max_context_slot_delta",
            )
        if self.max_block_height_delta is not None:
            _strict_non_negative_int(
                self.max_block_height_delta,
                "max_block_height_delta",
            )
        if not isinstance(self.require_provider_native_expiry, bool):
            raise ValueError("require_provider_native_expiry must be boolean")
        if not self.source.strip() or not self.reason.strip():
            raise ValueError("freshness policy source and reason are required")


@dataclass(frozen=True, slots=True)
class PR127ProviderNativeExpiry:
    expires_at_monotonic_ns: int
    provider_expires_at_utc: datetime | None = None
    source: str = "provider-native-expiry"

    def __post_init__(self) -> None:
        _strict_ns(self.expires_at_monotonic_ns, "expires_at_monotonic_ns")
        if self.provider_expires_at_utc is not None:
            _utc(self.provider_expires_at_utc, "provider_expires_at_utc")
        if not self.source.strip():
            raise ValueError("provider native expiry source is required")

    def to_json(self) -> dict[str, object]:
        return {
            "expires_at_monotonic_ns": str(self.expires_at_monotonic_ns),
            "provider_expires_at_utc": (
                None
                if self.provider_expires_at_utc is None
                else _iso_utc(self.provider_expires_at_utc)
            ),
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class PR127QuoteProvenance:
    provider: str
    quote_id: str
    route_hash: str
    requested_at: PR127ClockSnapshot
    received_at: PR127ClockSnapshot
    provider_timestamp_utc: datetime | None = None
    provider_native_expiry: PR127ProviderNativeExpiry | None = None
    schema_version: str = PR127_FRESHNESS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PR127_FRESHNESS_SCHEMA_VERSION:
            raise ValueError("unsupported PR-127 quote provenance schema")
        object.__setattr__(self, "provider", _provider(self.provider))
        object.__setattr__(self, "route_hash", _hash(self.route_hash, "route_hash"))
        if not self.quote_id.strip():
            raise ValueError("quote_id is required")
        if self.received_at.monotonic_ns < self.requested_at.monotonic_ns:
            raise ValueError("received_at monotonic cannot be before requested_at")
        if self.provider_timestamp_utc is not None:
            _utc(self.provider_timestamp_utc, "provider_timestamp_utc")
        if (
            self.provider_native_expiry is not None
            and self.provider_native_expiry.expires_at_monotonic_ns
            < self.received_at.monotonic_ns
        ):
            raise ValueError("provider native expiry cannot be before receipt")

    def effective_expires_at_monotonic_ns(
        self,
        policy: PR127QuoteFreshnessPolicy,
    ) -> int | None:
        native = (
            None
            if self.provider_native_expiry is None
            else self.provider_native_expiry.expires_at_monotonic_ns
        )
        local = (
            None
            if policy.conservative_local_max_age_ns is None
            else self.received_at.monotonic_ns + policy.conservative_local_max_age_ns
        )
        if policy.require_provider_native_expiry and native is None:
            return None
        expiries = tuple(item for item in (native, local) if item is not None)
        return None if not expiries else min(expiries)

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "provider": self.provider,
            "quote_id": self.quote_id,
            "route_hash": self.route_hash,
            "requested_at": self.requested_at.to_json(),
            "received_at": self.received_at.to_json(),
            "provider_timestamp_utc": (
                None
                if self.provider_timestamp_utc is None
                else _iso_utc(self.provider_timestamp_utc)
            ),
            "provider_native_expiry": (
                None
                if self.provider_native_expiry is None
                else self.provider_native_expiry.to_json()
            ),
        }

    def provenance_hash(self) -> str:
        return _sha256_payload(self.to_json())


@dataclass(frozen=True, slots=True)
class PR127FreshnessDecision:
    fresh: bool
    reason: PR127FreshnessReason
    provider: str
    quote_id: str
    age_ns: int | None
    effective_expires_at_monotonic_ns: int | None
    context_slot_delta: int | None
    block_height_delta: int | None
    provenance_hash: str

    def to_json(self) -> dict[str, object]:
        return {
            "fresh": self.fresh,
            "reason": self.reason.value,
            "provider": self.provider,
            "quote_id": self.quote_id,
            "age_ns": None if self.age_ns is None else str(self.age_ns),
            "effective_expires_at_monotonic_ns": (
                None
                if self.effective_expires_at_monotonic_ns is None
                else str(self.effective_expires_at_monotonic_ns)
            ),
            "context_slot_delta": self.context_slot_delta,
            "block_height_delta": self.block_height_delta,
            "provenance_hash": self.provenance_hash,
        }


def evaluate_pr127_quote_freshness(
    *,
    provenance: PR127QuoteProvenance,
    policy: PR127QuoteFreshnessPolicy,
    now: PR127ClockSnapshot,
) -> PR127FreshnessDecision:
    """Evaluate freshness with monotonic time only; UTC is audit display only."""

    if provenance.provider != policy.provider:
        raise ValueError("freshness policy provider does not match quote provider")
    expiry = provenance.effective_expires_at_monotonic_ns(policy)
    if now.monotonic_ns < provenance.received_at.monotonic_ns:
        return _decision(
            False,
            PR127FreshnessReason.CURRENT_MONOTONIC_BEFORE_RECEIVED,
            provenance,
            now,
            expiry,
        )

    age_ns = now.monotonic_ns - provenance.received_at.monotonic_ns
    if expiry is None:
        return _decision(
            False,
            PR127FreshnessReason.MISSING_PROVIDER_OR_LOCAL_EXPIRY,
            provenance,
            now,
            expiry,
            age_ns=age_ns,
        )

    native_expiry = provenance.provider_native_expiry
    if native_expiry is not None and now.monotonic_ns > (
        native_expiry.expires_at_monotonic_ns
    ):
        return _decision(
            False,
            PR127FreshnessReason.PROVIDER_NATIVE_EXPIRED,
            provenance,
            now,
            expiry,
            age_ns=age_ns,
        )
    if now.monotonic_ns > expiry:
        return _decision(
            False,
            PR127FreshnessReason.LOCAL_MAX_AGE_EXPIRED,
            provenance,
            now,
            expiry,
            age_ns=age_ns,
        )

    slot_delta = _delta(now.context_slot, provenance.received_at.context_slot)
    if (
        policy.max_context_slot_delta is not None
        and slot_delta is not None
        and slot_delta > policy.max_context_slot_delta
    ):
        return _decision(
            False,
            PR127FreshnessReason.CONTEXT_SLOT_TOO_OLD,
            provenance,
            now,
            expiry,
            age_ns=age_ns,
            context_slot_delta=slot_delta,
        )

    height_delta = _delta(now.block_height, provenance.received_at.block_height)
    if (
        policy.max_block_height_delta is not None
        and height_delta is not None
        and height_delta > policy.max_block_height_delta
    ):
        return _decision(
            False,
            PR127FreshnessReason.BLOCK_HEIGHT_TOO_OLD,
            provenance,
            now,
            expiry,
            age_ns=age_ns,
            block_height_delta=height_delta,
        )

    return _decision(
        True,
        PR127FreshnessReason.FRESH,
        provenance,
        now,
        expiry,
        age_ns=age_ns,
        context_slot_delta=slot_delta,
        block_height_delta=height_delta,
    )


@dataclass(frozen=True, slots=True)
class PR127CycleDeadlinePlan:
    cycle_id: str
    started_at: PR127ClockSnapshot
    first_leg_budget_ns: int
    exact_second_leg_budget_ns: int
    final_build_budget_ns: int
    compile_simulation_budget_ns: int
    slack_budget_ns: int = 0

    def __post_init__(self) -> None:
        if not self.cycle_id.strip():
            raise ValueError("cycle_id is required")
        for field in (
            "first_leg_budget_ns",
            "exact_second_leg_budget_ns",
            "final_build_budget_ns",
            "compile_simulation_budget_ns",
            "slack_budget_ns",
        ):
            _strict_ns(getattr(self, field), field)

    @property
    def total_budget_ns(self) -> int:
        return (
            self.first_leg_budget_ns
            + self.exact_second_leg_budget_ns
            + self.final_build_budget_ns
            + self.compile_simulation_budget_ns
            + self.slack_budget_ns
        )

    @property
    def deadline_monotonic_ns(self) -> int:
        return self.started_at.monotonic_ns + self.total_budget_ns

    def evaluate(self, now: PR127ClockSnapshot) -> PR127DeadlineReason:
        if now.monotonic_ns < self.started_at.monotonic_ns:
            return PR127DeadlineReason.CURRENT_MONOTONIC_BEFORE_START
        if now.monotonic_ns > self.deadline_monotonic_ns:
            return PR127DeadlineReason.DEADLINE_EXPIRED
        return PR127DeadlineReason.WITHIN_DEADLINE

    def remaining_ns(self, now: PR127ClockSnapshot) -> int:
        reason = self.evaluate(now)
        if reason is PR127DeadlineReason.CURRENT_MONOTONIC_BEFORE_START:
            raise ValueError("current monotonic cannot be before cycle start")
        if reason is PR127DeadlineReason.DEADLINE_EXPIRED:
            return 0
        return self.deadline_monotonic_ns - now.monotonic_ns


@dataclass(frozen=True, slots=True)
class PR127MonotonicLease:
    key: str
    acquired_at: PR127ClockSnapshot
    ttl_ns: int

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("lease key is required")
        _strict_positive_ns(self.ttl_ns, "ttl_ns")

    @property
    def expires_at_monotonic_ns(self) -> int:
        return self.acquired_at.monotonic_ns + self.ttl_ns

    def active(self, now: PR127ClockSnapshot) -> bool:
        if now.monotonic_ns < self.acquired_at.monotonic_ns:
            raise ValueError("current monotonic cannot be before lease acquisition")
        return now.monotonic_ns <= self.expires_at_monotonic_ns


@dataclass(frozen=True, slots=True)
class PR127ClockSkewDiagnostic:
    observed_utc: datetime
    reference_utc: datetime
    max_allowed_skew_seconds: int

    def __post_init__(self) -> None:
        _utc(self.observed_utc, "observed_utc")
        _utc(self.reference_utc, "reference_utc")
        _strict_non_negative_int(
            self.max_allowed_skew_seconds,
            "max_allowed_skew_seconds",
        )

    @property
    def skew_seconds(self) -> float:
        return abs((self.observed_utc - self.reference_utc).total_seconds())

    @property
    def status(self) -> PR127ClockSkewStatus:
        if self.skew_seconds > self.max_allowed_skew_seconds:
            return PR127ClockSkewStatus.SKEWED
        return PR127ClockSkewStatus.OK


def _decision(
    fresh: bool,
    reason: PR127FreshnessReason,
    provenance: PR127QuoteProvenance,
    now: PR127ClockSnapshot,
    expiry: int | None,
    *,
    age_ns: int | None = None,
    context_slot_delta: int | None = None,
    block_height_delta: int | None = None,
) -> PR127FreshnessDecision:
    if context_slot_delta is None:
        context_slot_delta = _delta(
            now.context_slot, provenance.received_at.context_slot
        )
    if block_height_delta is None:
        block_height_delta = _delta(
            now.block_height,
            provenance.received_at.block_height,
        )
    return PR127FreshnessDecision(
        fresh=fresh,
        reason=reason,
        provider=provenance.provider,
        quote_id=provenance.quote_id,
        age_ns=age_ns,
        effective_expires_at_monotonic_ns=expiry,
        context_slot_delta=context_slot_delta,
        block_height_delta=block_height_delta,
        provenance_hash=provenance.provenance_hash(),
    )


def _delta(current: int | None, previous: int | None) -> int | None:
    if current is None or previous is None:
        return None
    return max(0, current - previous)


def _strict_ns(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be integer nanoseconds")
    if value < 0 or value > _MAX_NS:
        raise ValueError(f"{field} outside allowed nanosecond range")


def _strict_positive_ns(value: int, field: str) -> None:
    _strict_ns(value, field)
    if value <= 0:
        raise ValueError(f"{field} must be positive")


def _strict_non_negative_int(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")


def _utc(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware UTC")
    if value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{field} must be UTC")


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _provider(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("provider must be a normalized identifier")
    provider = value.strip().lower()
    if not _PROVIDER_RE.fullmatch(provider):
        raise ValueError("provider must be a normalized identifier")
    return provider


def _hash(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a non-placeholder sha256")
    lowered = value.lower()
    if not _HASH_RE.fullmatch(lowered) or lowered == "0" * 64:
        raise ValueError(f"{field} must be a non-placeholder sha256")
    return lowered


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _sha256_payload(payload: Any) -> str:
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


__all__ = [
    "PR127ClockSkewDiagnostic",
    "PR127ClockSkewStatus",
    "PR127ClockSnapshot",
    "PR127CycleDeadlinePlan",
    "PR127DeadlineReason",
    "PR127FreshnessDecision",
    "PR127FreshnessReason",
    "PR127MonotonicLease",
    "PR127ProviderNativeExpiry",
    "PR127QuoteFreshnessPolicy",
    "PR127QuoteProvenance",
    "PR127_FRESHNESS_SCHEMA_VERSION",
    "evaluate_pr127_quote_freshness",
]
