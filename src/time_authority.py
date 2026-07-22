"""PR-182 trusted time authority and explicit clock-domain primitives.

This module owns clock reads for correctness-sensitive runtime paths.  UTC is
retained for audit and durable expiry bounds, while in-process deadlines and
same-boot leases use monotonic time.  Persisted monotonic values are always
bound to a boot/time-domain identity and process generation.

The module never enables live trading, signs, submits, or reads private keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import os
from pathlib import Path
import platform
import threading
import time
from typing import Callable, Protocol, runtime_checkable
from uuid import uuid4

PR182_TIME_SCHEMA = "pr182.trusted-time.v1"


class TimeAuthorityError(RuntimeError):
    """Base error for trusted-time failures."""


class ClockUnhealthyError(TimeAuthorityError):
    """Raised when a correctness-sensitive operation sees unhealthy time."""


class ClockDomainMismatchError(TimeAuthorityError):
    """Raised when monotonic values from different boot domains are compared."""


class TimeSourceStatus(StrEnum):
    SYNCHRONIZED = "synchronized"
    DEGRADED = "degraded"
    UNSYNCHRONIZED = "unsynchronized"
    ANOMALOUS = "anomalous"


class ClockAnomalyKind(StrEnum):
    UTC_ROLLBACK = "utc-rollback"
    UTC_FORWARD_STEP = "utc-forward-step"
    MONOTONIC_ROLLBACK = "monotonic-rollback"
    BOOT_DOMAIN_CHANGED = "boot-domain-changed"
    UNCERTAINTY_EXCEEDED = "uncertainty-exceeded"


@dataclass(frozen=True, slots=True)
class TimeSnapshot:
    utc_ns: int
    monotonic_ns: int
    boot_id: str
    process_generation: int
    time_source_status: TimeSourceStatus
    max_uncertainty_ns: int
    observed_chain_slot: int | None = None
    observed_chain_root: int | None = None
    schema_version: str = PR182_TIME_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != PR182_TIME_SCHEMA:
            raise ValueError("unsupported trusted-time schema")
        if min(self.utc_ns, self.monotonic_ns, self.max_uncertainty_ns) < 0:
            raise ValueError("time values must be non-negative")
        if not self.boot_id.strip():
            raise ValueError("boot_id is required")
        if self.process_generation < 1:
            raise ValueError("process_generation must be positive")
        for name in ("observed_chain_slot", "observed_chain_root"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative")

    @property
    def healthy_for_sensitive_operations(self) -> bool:
        return self.time_source_status is TimeSourceStatus.SYNCHRONIZED

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "utc_ns": str(self.utc_ns),
            "monotonic_ns": str(self.monotonic_ns),
            "boot_id": self.boot_id,
            "process_generation": self.process_generation,
            "time_source_status": self.time_source_status.value,
            "max_uncertainty_ns": str(self.max_uncertainty_ns),
            "observed_chain_slot": self.observed_chain_slot,
            "observed_chain_root": self.observed_chain_root,
        }


@dataclass(frozen=True, slots=True)
class ClockIncident:
    kind: ClockAnomalyKind
    previous: TimeSnapshot | None
    current: TimeSnapshot
    expected_utc_delta_ns: int | None
    observed_utc_delta_ns: int | None

    def to_json(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "previous": None if self.previous is None else self.previous.to_json(),
            "current": self.current.to_json(),
            "expected_utc_delta_ns": self.expected_utc_delta_ns,
            "observed_utc_delta_ns": self.observed_utc_delta_ns,
        }


@runtime_checkable
class TimeAuthority(Protocol):
    @property
    def boot_id(self) -> str: ...

    @property
    def process_generation(self) -> int: ...

    def snapshot(self) -> TimeSnapshot: ...

    def assert_healthy_for_sensitive_operation(self) -> TimeSnapshot: ...


@dataclass(frozen=True, slots=True)
class MonotonicDeadline:
    boot_id: str
    process_generation: int
    started_at_monotonic_ns: int
    expires_at_monotonic_ns: int

    def __post_init__(self) -> None:
        if not self.boot_id.strip():
            raise ValueError("boot_id is required")
        if self.process_generation < 1:
            raise ValueError("process_generation must be positive")
        if self.started_at_monotonic_ns < 0:
            raise ValueError("started_at_monotonic_ns must be non-negative")
        if self.expires_at_monotonic_ns <= self.started_at_monotonic_ns:
            raise ValueError("deadline expiry must follow start")

    def expired(self, now: TimeSnapshot) -> bool:
        _require_same_time_domain(
            self.boot_id,
            self.process_generation,
            now.boot_id,
            now.process_generation,
        )
        return now.monotonic_ns >= self.expires_at_monotonic_ns


@dataclass(frozen=True, slots=True)
class PersistedExpiry:
    """Boot-bound monotonic expiry plus durable UTC upper bound.

    A restart or failover never interprets another boot domain's monotonic value.
    It must reconcile/reissue instead.  Both bounds are conservative: either one
    expiring invalidates the permit/evidence.
    """

    boot_id: str
    process_generation: int
    issued_at_utc_ns: int
    expires_at_utc_ns: int
    issued_at_monotonic_ns: int
    expires_at_monotonic_ns: int

    def __post_init__(self) -> None:
        if not self.boot_id.strip():
            raise ValueError("boot_id is required")
        if self.process_generation < 1:
            raise ValueError("process_generation must be positive")
        if min(
            self.issued_at_utc_ns,
            self.expires_at_utc_ns,
            self.issued_at_monotonic_ns,
            self.expires_at_monotonic_ns,
        ) < 0:
            raise ValueError("expiry values must be non-negative")
        if self.expires_at_utc_ns <= self.issued_at_utc_ns:
            raise ValueError("UTC expiry must follow issuance")
        if self.expires_at_monotonic_ns <= self.issued_at_monotonic_ns:
            raise ValueError("monotonic expiry must follow issuance")

    @classmethod
    def issue(cls, authority: TimeAuthority, *, ttl_ns: int) -> "PersistedExpiry":
        if ttl_ns <= 0:
            raise ValueError("ttl_ns must be positive")
        now = authority.assert_healthy_for_sensitive_operation()
        return cls(
            boot_id=now.boot_id,
            process_generation=now.process_generation,
            issued_at_utc_ns=now.utc_ns,
            expires_at_utc_ns=now.utc_ns + ttl_ns,
            issued_at_monotonic_ns=now.monotonic_ns,
            expires_at_monotonic_ns=now.monotonic_ns + ttl_ns,
        )

    def valid_at(self, now: TimeSnapshot) -> bool:
        if not now.healthy_for_sensitive_operations:
            return False
        if (
            now.boot_id != self.boot_id
            or now.process_generation != self.process_generation
        ):
            return False
        return (
            now.monotonic_ns < self.expires_at_monotonic_ns
            and now.utc_ns < self.expires_at_utc_ns
        )

    def to_json(self) -> dict[str, object]:
        return {
            "boot_id": self.boot_id,
            "process_generation": self.process_generation,
            "issued_at_utc_ns": str(self.issued_at_utc_ns),
            "expires_at_utc_ns": str(self.expires_at_utc_ns),
            "issued_at_monotonic_ns": str(self.issued_at_monotonic_ns),
            "expires_at_monotonic_ns": str(self.expires_at_monotonic_ns),
        }


class SystemTimeAuthority:
    """Runtime-owned clock reader with rollback/forward-step detection.

    ``source_status`` should be supplied by the host timesync/readiness adapter.
    The default is deliberately ``UNSYNCHRONIZED`` so live-sensitive operations
    fail closed until the deployment proves synchronization.
    """

    def __init__(
        self,
        *,
        boot_id: str | None = None,
        process_generation: int = 1,
        source_status: TimeSourceStatus = TimeSourceStatus.UNSYNCHRONIZED,
        max_uncertainty_ns: int = 1_000_000_000,
        max_step_ns: int = 5_000_000_000,
        utc_clock_ns: Callable[[], int] = time.time_ns,
        monotonic_clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        if process_generation < 1:
            raise ValueError("process_generation must be positive")
        if max_uncertainty_ns < 0 or max_step_ns <= 0:
            raise ValueError("invalid clock uncertainty/step policy")
        self._boot_id = boot_id or resolve_boot_id()
        self._process_generation = process_generation
        self._source_status = source_status
        self._max_uncertainty_ns = max_uncertainty_ns
        self._max_step_ns = max_step_ns
        self._utc_clock_ns = utc_clock_ns
        self._monotonic_clock_ns = monotonic_clock_ns
        self._last: TimeSnapshot | None = None
        self._incidents: list[ClockIncident] = []
        self._lock = threading.Lock()

    @property
    def boot_id(self) -> str:
        return self._boot_id

    @property
    def process_generation(self) -> int:
        return self._process_generation

    @property
    def incidents(self) -> tuple[ClockIncident, ...]:
        with self._lock:
            return tuple(self._incidents)

    def update_source_status(
        self,
        status: TimeSourceStatus,
        *,
        max_uncertainty_ns: int | None = None,
    ) -> None:
        if max_uncertainty_ns is not None and max_uncertainty_ns < 0:
            raise ValueError("max_uncertainty_ns must be non-negative")
        with self._lock:
            self._source_status = status
            if max_uncertainty_ns is not None:
                self._max_uncertainty_ns = max_uncertainty_ns

    def snapshot(self) -> TimeSnapshot:
        with self._lock:
            raw = TimeSnapshot(
                utc_ns=self._utc_clock_ns(),
                monotonic_ns=self._monotonic_clock_ns(),
                boot_id=self._boot_id,
                process_generation=self._process_generation,
                time_source_status=self._source_status,
                max_uncertainty_ns=self._max_uncertainty_ns,
            )
            incident = self._detect_anomaly(self._last, raw)
            if incident is not None:
                self._incidents.append(incident)
                raw = TimeSnapshot(
                    utc_ns=raw.utc_ns,
                    monotonic_ns=raw.monotonic_ns,
                    boot_id=raw.boot_id,
                    process_generation=raw.process_generation,
                    time_source_status=TimeSourceStatus.ANOMALOUS,
                    max_uncertainty_ns=raw.max_uncertainty_ns,
                )
            self._last = raw
            return raw

    def assert_healthy_for_sensitive_operation(self) -> TimeSnapshot:
        snapshot = self.snapshot()
        if not snapshot.healthy_for_sensitive_operations:
            raise ClockUnhealthyError(
                "trusted time is not synchronized and anomaly-free"
            )
        return snapshot

    def _detect_anomaly(
        self,
        previous: TimeSnapshot | None,
        current: TimeSnapshot,
    ) -> ClockIncident | None:
        if previous is None:
            return None
        if previous.boot_id != current.boot_id:
            return ClockIncident(
                ClockAnomalyKind.BOOT_DOMAIN_CHANGED,
                previous,
                current,
                None,
                None,
            )
        monotonic_delta = current.monotonic_ns - previous.monotonic_ns
        utc_delta = current.utc_ns - previous.utc_ns
        if monotonic_delta < 0:
            return ClockIncident(
                ClockAnomalyKind.MONOTONIC_ROLLBACK,
                previous,
                current,
                monotonic_delta,
                utc_delta,
            )
        if utc_delta < -current.max_uncertainty_ns:
            return ClockIncident(
                ClockAnomalyKind.UTC_ROLLBACK,
                previous,
                current,
                monotonic_delta,
                utc_delta,
            )
        drift = utc_delta - monotonic_delta
        if drift > self._max_step_ns + current.max_uncertainty_ns:
            return ClockIncident(
                ClockAnomalyKind.UTC_FORWARD_STEP,
                previous,
                current,
                monotonic_delta,
                utc_delta,
            )
        if current.max_uncertainty_ns > self._max_step_ns:
            return ClockIncident(
                ClockAnomalyKind.UNCERTAINTY_EXCEEDED,
                previous,
                current,
                monotonic_delta,
                utc_delta,
            )
        return None


def resolve_boot_id() -> str:
    """Resolve a conservative boot/time-domain identity.

    Linux exposes a real boot UUID.  On platforms without an equivalent safe
    standard-library primitive, use a process-scoped domain.  That conservative
    fallback invalidates persisted monotonic leases on every process restart
    instead of incorrectly extending ownership across an unknown boot.
    """

    linux_boot_id = Path("/proc/sys/kernel/random/boot_id")
    try:
        value = linux_boot_id.read_text(encoding="ascii").strip().lower()
    except OSError:
        value = ""
    if value:
        return value
    seed = "\0".join(
        (
            platform.node(),
            str(os.getpid()),
            str(time.monotonic_ns()),
            uuid4().hex,
        )
    )
    return "process-domain-" + hashlib.sha256(seed.encode()).hexdigest()


def _require_same_time_domain(
    left_boot_id: str,
    left_generation: int,
    right_boot_id: str,
    right_generation: int,
) -> None:
    if left_boot_id != right_boot_id or left_generation != right_generation:
        raise ClockDomainMismatchError(
            "monotonic values from different boot/process domains are incomparable"
        )


__all__ = [
    "ClockAnomalyKind",
    "ClockDomainMismatchError",
    "ClockIncident",
    "ClockUnhealthyError",
    "MonotonicDeadline",
    "PR182_TIME_SCHEMA",
    "PersistedExpiry",
    "SystemTimeAuthority",
    "TimeAuthority",
    "TimeAuthorityError",
    "TimeSnapshot",
    "TimeSourceStatus",
    "resolve_boot_id",
]
