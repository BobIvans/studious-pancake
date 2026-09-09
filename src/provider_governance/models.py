"""Typed contracts for provider entitlement, dependency and work admission."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
from urllib.parse import urlsplit, urlunsplit


class ProviderOperation(StrEnum):
    DISCOVERY = "discovery"
    REFINEMENT = "refinement"
    FINALIZATION = "finalization"
    BACKFILL = "backfill"
    HEALTH_PROBE = "health_probe"


class DependencyMode(StrEnum):
    ACTIVE = "active"
    DEGRADED = "degraded"
    COOLDOWN = "cooldown"
    DISABLED = "disabled"


class DependencyFailureKind(StrEnum):
    RATE_LIMITED = "rate_limited"
    QUOTA = "quota"
    CIRCUIT_OPEN = "circuit_open"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    INVALID_SCHEMA = "invalid_schema"
    DISABLED = "disabled"
    AUTH = "auth"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class LeaseState(StrEnum):
    RESERVED = "reserved"
    ISSUED = "issued"
    COMPLETED = "completed"
    RELEASED = "released"
    EXPIRED = "expired"
    OUTCOME_UNKNOWN = "outcome_unknown"


class AdmissionCode(StrEnum):
    MANIFEST_MISSING = "manifest_missing"
    PHYSICAL_SCOPE_DENIED = "physical_scope_denied"
    MANIFEST_EXPIRED = "manifest_expired"
    GENERATION_MISMATCH = "generation_mismatch"
    OPERATION_NOT_ENTITLED = "operation_not_entitled"
    DEADLINE_EXPIRED = "deadline_expired"
    QUEUE_FULL = "queue_full"
    DEPENDENCY_DISABLED = "dependency_disabled"
    DEPENDENCY_COOLDOWN = "dependency_cooldown"
    DEGRADED_OPERATION_DENIED = "degraded_operation_denied"
    REQUEST_QUOTA_EXHAUSTED = "request_quota_exhausted"
    COST_QUOTA_EXHAUSTED = "cost_quota_exhausted"
    SPEND_LIMIT_EXHAUSTED = "spend_limit_exhausted"
    FINALIZATION_RESERVE_PROTECTED = "finalization_reserve_protected"
    CONCURRENCY_EXHAUSTED = "concurrency_exhausted"
    LEASE_STATE_INVALID = "lease_state_invalid"


class ProviderGovernanceError(ValueError):
    """Raised when a governance contract or transition is malformed."""


class ProviderAdmissionError(RuntimeError):
    """Typed fail-closed admission denial.

    ``governance_error_kind`` and ``failure_reason`` are plain immutable values
    so routing can preserve the denial across module reloads or installed/source
    import aliases without relying solely on Python class identity.
    """

    governance_error_kind = "provider_admission"

    def __init__(
        self,
        provider_id: str,
        code: AdmissionCode,
        detail: str,
        *,
        retryable: bool,
        retry_at: float | None = None,
        failure_reason: str | None = None,
    ) -> None:
        super().__init__(f"{provider_id}: {code.value}: {detail}")
        self.provider_id = provider_id
        self.code = code
        self.detail = detail
        self.retryable = retryable
        self.retry_at = retry_at
        self.failure_reason = failure_reason


def _positive_int(value: int, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ProviderGovernanceError(f"{label} must be a positive integer")
    return value


def _non_negative_int(value: int, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ProviderGovernanceError(f"{label} must be a non-negative integer")
    return value


def _positive_float(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderGovernanceError(f"{label} must be numeric")
    result = float(value)
    if result <= 0 or result != result or result in (float("inf"), float("-inf")):
        raise ProviderGovernanceError(f"{label} must be finite and positive")
    return result


@dataclass(frozen=True, slots=True)
class ProviderEntitlement:
    provider_id: str
    generation: str
    allowed_operations: frozenset[ProviderOperation]
    window_seconds: float
    request_limit: int
    cost_unit_limit: int
    spend_limit_micros: int
    max_concurrency: int
    finalization_reserve_requests: int = 0
    finalization_reserve_cost_units: int = 0
    finalization_reserve_spend_micros: int = 0
    expires_at_epoch_seconds: int | None = None
    source_ref: str = "runtime-derived"
    quota_pool_ref: str | None = None
    spend_window_seconds: int = 86400
    allowed_endpoints: tuple[str, ...] = ()
    allowed_http_methods: frozenset[str] = frozenset()
    allowed_rpc_methods: frozenset[str] = frozenset()
    allowed_query_parameters: frozenset[str] = frozenset()
    credential_ref: str | None = None
    credential_generation: str | None = None
    manifest_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise ProviderGovernanceError("provider_id is required")
        if not isinstance(self.generation, str) or not self.generation:
            raise ProviderGovernanceError("generation is required")
        operations = frozenset(
            ProviderOperation(item) for item in self.allowed_operations
        )
        if not operations:
            raise ProviderGovernanceError("allowed_operations cannot be empty")
        object.__setattr__(self, "allowed_operations", operations)
        object.__setattr__(
            self,
            "window_seconds",
            _positive_float(self.window_seconds, "window_seconds"),
        )
        _positive_int(self.request_limit, "request_limit")
        _positive_int(self.cost_unit_limit, "cost_unit_limit")
        _non_negative_int(self.spend_limit_micros, "spend_limit_micros")
        _positive_int(self.max_concurrency, "max_concurrency")
        _non_negative_int(
            self.finalization_reserve_requests,
            "finalization_reserve_requests",
        )
        _non_negative_int(
            self.finalization_reserve_cost_units,
            "finalization_reserve_cost_units",
        )
        _non_negative_int(
            self.finalization_reserve_spend_micros,
            "finalization_reserve_spend_micros",
        )
        if self.finalization_reserve_requests >= self.request_limit:
            raise ProviderGovernanceError(
                "finalization request reserve must be smaller than request_limit"
            )
        if self.finalization_reserve_cost_units >= self.cost_unit_limit:
            raise ProviderGovernanceError(
                "finalization cost reserve must be smaller than cost_unit_limit"
            )
        if self.spend_limit_micros == 0:
            if self.finalization_reserve_spend_micros != 0:
                raise ProviderGovernanceError(
                    "spend reserve must be zero when spend_limit_micros is zero"
                )
        elif self.finalization_reserve_spend_micros >= self.spend_limit_micros:
            raise ProviderGovernanceError(
                "finalization spend reserve must be smaller than spend limit"
            )
        if (
            any(
                value > 0
                for value in (
                    self.finalization_reserve_requests,
                    self.finalization_reserve_cost_units,
                    self.finalization_reserve_spend_micros,
                )
            )
            and ProviderOperation.FINALIZATION not in operations
        ):
            raise ProviderGovernanceError(
                "finalization reserves require FINALIZATION entitlement"
            )
        if self.expires_at_epoch_seconds is not None:
            _positive_int(self.expires_at_epoch_seconds, "expires_at_epoch_seconds")
        if not isinstance(self.source_ref, str) or not self.source_ref:
            raise ProviderGovernanceError("source_ref is required")
        if self.quota_pool_ref is not None and (
            not isinstance(self.quota_pool_ref, str) or not self.quota_pool_ref
        ):
            raise ProviderGovernanceError("quota_pool_ref must be a nonempty string")
        _positive_int(self.spend_window_seconds, "spend_window_seconds")
        endpoints = tuple(sorted(set(self.allowed_endpoints)))
        for endpoint in endpoints:
            if not isinstance(endpoint, str):
                raise ProviderGovernanceError("reviewed endpoint must be a string")
            parsed = urlsplit(endpoint)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or endpoint
                != urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
            ):
                raise ProviderGovernanceError(
                    "reviewed endpoint must be exact HTTPS without credentials or query"
                )
        object.__setattr__(self, "allowed_endpoints", endpoints)
        for field_name in (
            "allowed_http_methods",
            "allowed_rpc_methods",
            "allowed_query_parameters",
        ):
            values = frozenset(getattr(self, field_name))
            if any(not isinstance(value, str) or not value for value in values):
                raise ProviderGovernanceError(
                    "reviewed scope entries must be nonempty strings"
                )
            object.__setattr__(self, field_name, values)
        if self.allowed_http_methods - {"GET", "POST"}:
            raise ProviderGovernanceError("reviewed HTTP method is unsupported")
        for value in (self.credential_ref, self.credential_generation):
            if value is not None and (
                not isinstance(value, str) or not value or len(value) > 128
            ):
                raise ProviderGovernanceError(
                    "credential identity must be an opaque bounded reference"
                )
        payload = {
            "schema_version": "mpr043.provider-entitlement.v1",
            "provider_id": self.provider_id,
            "generation": self.generation,
            "allowed_operations": sorted(item.value for item in operations),
            "window_seconds": self.window_seconds,
            "request_limit": self.request_limit,
            "cost_unit_limit": self.cost_unit_limit,
            "spend_limit_micros": self.spend_limit_micros,
            "max_concurrency": self.max_concurrency,
            "finalization_reserve_requests": self.finalization_reserve_requests,
            "finalization_reserve_cost_units": self.finalization_reserve_cost_units,
            "finalization_reserve_spend_micros": self.finalization_reserve_spend_micros,
            "expires_at_epoch_seconds": self.expires_at_epoch_seconds,
            "source_ref": self.source_ref,
            "quota_pool_ref": self.quota_pool_ref,
            "spend_window_seconds": self.spend_window_seconds,
            "allowed_endpoints": self.allowed_endpoints,
            "allowed_http_methods": sorted(self.allowed_http_methods),
            "allowed_rpc_methods": sorted(self.allowed_rpc_methods),
            "allowed_query_parameters": sorted(self.allowed_query_parameters),
            "credential_ref": self.credential_ref,
            "credential_generation": self.credential_generation,
        }
        object.__setattr__(
            self,
            "manifest_sha256",
            hashlib.sha256(
                json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "generation": self.generation,
            "allowed_operations": tuple(
                sorted(item.value for item in self.allowed_operations)
            ),
            "window_seconds": self.window_seconds,
            "request_limit": self.request_limit,
            "cost_unit_limit": self.cost_unit_limit,
            "spend_limit_micros": self.spend_limit_micros,
            "max_concurrency": self.max_concurrency,
            "finalization_reserve_requests": self.finalization_reserve_requests,
            "finalization_reserve_cost_units": self.finalization_reserve_cost_units,
            "finalization_reserve_spend_micros": self.finalization_reserve_spend_micros,
            "expires_at_epoch_seconds": self.expires_at_epoch_seconds,
            "source_ref": self.source_ref,
            "manifest_sha256": self.manifest_sha256,
            "quota_pool_ref": self.quota_pool_ref,
            "spend_window_seconds": self.spend_window_seconds,
            "allowed_endpoints": self.allowed_endpoints,
            "allowed_http_methods": tuple(sorted(self.allowed_http_methods)),
            "allowed_rpc_methods": tuple(sorted(self.allowed_rpc_methods)),
            "allowed_query_parameters": tuple(sorted(self.allowed_query_parameters)),
            "credential_ref": self.credential_ref,
            "credential_generation": self.credential_generation,
        }


@dataclass(frozen=True, slots=True)
class AdmissionRequest:
    work_id: str
    provider_id: str
    operation: ProviderOperation
    request_fingerprint: str
    fairness_key: str
    deadline_at: float
    expected_generation: str | None = None
    estimated_cost_units: int = 1
    estimated_spend_micros: int = 0
    lease_ttl_seconds: float = 10.0
    priority: int = 100

    def __post_init__(self) -> None:
        for label, value in (
            ("work_id", self.work_id),
            ("provider_id", self.provider_id),
            ("request_fingerprint", self.request_fingerprint),
            ("fairness_key", self.fairness_key),
        ):
            if not isinstance(value, str) or not value:
                raise ProviderGovernanceError(f"{label} is required")
        object.__setattr__(self, "operation", ProviderOperation(self.operation))
        object.__setattr__(
            self, "deadline_at", _positive_float(self.deadline_at, "deadline_at")
        )
        _positive_int(self.estimated_cost_units, "estimated_cost_units")
        _non_negative_int(self.estimated_spend_micros, "estimated_spend_micros")
        object.__setattr__(
            self,
            "lease_ttl_seconds",
            _positive_float(self.lease_ttl_seconds, "lease_ttl_seconds"),
        )
        _non_negative_int(self.priority, "priority")
        if self.expected_generation is not None and (
            not isinstance(self.expected_generation, str)
            or not self.expected_generation
        ):
            raise ProviderGovernanceError(
                "expected_generation must be a nonempty string"
            )


@dataclass(frozen=True, slots=True)
class ProviderLease:
    lease_id: str
    work_id: str
    provider_id: str
    operation: ProviderOperation
    request_fingerprint: str
    entitlement_generation: str
    manifest_sha256: str
    reserved_at: float
    expires_at: float
    estimated_cost_units: int
    estimated_spend_micros: int
    owner_boot_id: str = "process-local"
    owner_process_generation: int = 1


@dataclass(frozen=True, slots=True)
class DependencySnapshot:
    provider_id: str
    generation: str
    mode: DependencyMode
    consecutive_failures: int
    reason: str
    retry_at: float | None


__all__ = [
    "AdmissionCode",
    "AdmissionRequest",
    "DependencyFailureKind",
    "DependencyMode",
    "DependencySnapshot",
    "LeaseState",
    "ProviderAdmissionError",
    "ProviderEntitlement",
    "ProviderGovernanceError",
    "ProviderLease",
    "ProviderOperation",
]
