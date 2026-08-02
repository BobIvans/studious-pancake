"""Installed provider-governance authority and adapter entitlement factory."""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Mapping, TypeVar

from .authority import ProviderSpendAuthority
from .dependency import DependencyController
from .models import (
    AdmissionRequest,
    DependencyFailureKind,
    ProviderEntitlement,
    ProviderGovernanceError,
    ProviderOperation,
)
from .scheduler import DeadlineAdmissionScheduler


T = TypeVar("T")


def _env_int(
    env: Mapping[str, str], key: str, default: int, *, minimum: int = 0
) -> int:
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ProviderGovernanceError(f"{key} must be an integer") from exc
    if value < minimum:
        raise ProviderGovernanceError(f"{key} must be >= {minimum}")
    return value


def _env_float(
    env: Mapping[str, str], key: str, default: float, *, minimum: float = 0.0
) -> float:
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ProviderGovernanceError(f"{key} must be numeric") from exc
    if value < minimum or value != value or value in (float("inf"), float("-inf")):
        raise ProviderGovernanceError(f"{key} must be finite and >= {minimum}")
    return value


def _provider_prefix(provider_id: str) -> str:
    return "PROVIDER_" + "".join(
        character if character.isalnum() else "_"
        for character in provider_id.upper()
    )


def _role_value(adapter: Any) -> str:
    return str(getattr(getattr(adapter, "capabilities", None), "role", "disabled").value)


def _generation(adapter: Any) -> str:
    capabilities = getattr(adapter, "capabilities", None)
    value = getattr(capabilities, "schema_version_pin", None)
    if not isinstance(value, str) or not value:
        raise ProviderGovernanceError(
            f"{getattr(adapter, 'provider_id', '<unknown>')} lacks a generation pin"
        )
    return value


def entitlement_for_adapter(
    adapter: Any, env: Mapping[str, str]
) -> ProviderEntitlement:
    provider_id = getattr(adapter, "provider_id", None)
    if not isinstance(provider_id, str) or not provider_id:
        raise ProviderGovernanceError("provider adapter lacks provider_id")
    prefix = _provider_prefix(provider_id)
    quota = getattr(adapter, "quota", None)
    limiter = getattr(adapter, "limiter", None)
    default_limit = int(
        getattr(quota, "limit", getattr(limiter, "max_calls", 60))
    )
    default_window = float(
        getattr(quota, "window", getattr(limiter, "window_seconds", 60.0))
    )
    request_limit = _env_int(
        env, f"{prefix}_REQUEST_LIMIT", default_limit, minimum=1
    )
    window_seconds = _env_float(
        env, f"{prefix}_WINDOW_SECONDS", default_window, minimum=0.001
    )
    cost_limit = _env_int(
        env, f"{prefix}_COST_UNIT_LIMIT", request_limit, minimum=1
    )
    max_concurrency = _env_int(
        env,
        f"{prefix}_MAX_CONCURRENCY",
        1 if provider_id == "jupiter_router" else 2,
        minimum=1,
    )
    spend_limit = _env_int(
        env, f"{prefix}_SPEND_LIMIT_MICROS", 0, minimum=0
    )
    role = _role_value(adapter)
    operations = {
        ProviderOperation.DISCOVERY,
        ProviderOperation.BACKFILL,
        ProviderOperation.HEALTH_PROBE,
    }
    if role == "executable":
        operations.update(
            {ProviderOperation.REFINEMENT, ProviderOperation.FINALIZATION}
        )
    if role == "disabled":
        operations = {ProviderOperation.HEALTH_PROBE}

    default_finalization_reserve = 0
    if ProviderOperation.FINALIZATION in operations:
        default_finalization_reserve = min(
            int(getattr(quota, "finalization_reserve", 2)),
            max(0, request_limit - 1),
        )
    reserve_requests = _env_int(
        env,
        f"{prefix}_FINALIZATION_RESERVE_REQUESTS",
        default_finalization_reserve,
        minimum=0,
    )
    reserve_cost = _env_int(
        env,
        f"{prefix}_FINALIZATION_RESERVE_COST_UNITS",
        min(reserve_requests, max(0, cost_limit - 1)),
        minimum=0,
    )
    reserve_spend = _env_int(
        env,
        f"{prefix}_FINALIZATION_RESERVE_SPEND_MICROS",
        0,
        minimum=0,
    )
    expires_raw = env.get(f"{prefix}_ENTITLEMENT_EXPIRES_AT_EPOCH_SECONDS")
    expires_at = (
        None
        if expires_raw is None or expires_raw == ""
        else _env_int(
            env,
            f"{prefix}_ENTITLEMENT_EXPIRES_AT_EPOCH_SECONDS",
            0,
            minimum=1,
        )
    )
    return ProviderEntitlement(
        provider_id=provider_id,
        generation=_generation(adapter),
        allowed_operations=frozenset(operations),
        window_seconds=window_seconds,
        request_limit=request_limit,
        cost_unit_limit=cost_limit,
        spend_limit_micros=spend_limit,
        max_concurrency=max_concurrency,
        finalization_reserve_requests=reserve_requests,
        finalization_reserve_cost_units=reserve_cost,
        finalization_reserve_spend_micros=reserve_spend,
        expires_at_epoch_seconds=expires_at,
        source_ref=f"adapter-capabilities:{_generation(adapter)}",
    )


_FAILURE_KIND_BY_VALUE = {
    "rate_limited": DependencyFailureKind.RATE_LIMITED,
    "quota": DependencyFailureKind.QUOTA,
    "circuit_open": DependencyFailureKind.CIRCUIT_OPEN,
    "timeout": DependencyFailureKind.TIMEOUT,
    "transport": DependencyFailureKind.TRANSPORT,
    "http_error": DependencyFailureKind.TRANSPORT,
    "invalid_schema": DependencyFailureKind.INVALID_SCHEMA,
    "disabled": DependencyFailureKind.DISABLED,
    "cancelled": DependencyFailureKind.CANCELLED,
}


class ProviderGovernance:
    """One runtime authority for entitlement, dependency and work scheduling."""

    def __init__(
        self,
        entitlements: Mapping[str, ProviderEntitlement],
        *,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        transient_failure_threshold: int = 2,
        cooldown_seconds: float = 30.0,
        max_queue_size: int = 4096,
    ) -> None:
        self.clock = clock
        self.authority = ProviderSpendAuthority(
            entitlements,
            clock=clock,
            wall_clock=wall_clock,
        )
        self.dependencies = DependencyController(
            clock=clock,
            transient_failure_threshold=transient_failure_threshold,
            cooldown_seconds=cooldown_seconds,
        )
        self.scheduler = DeadlineAdmissionScheduler(
            self.authority,
            self.dependencies,
            clock=clock,
            max_queue_size=max_queue_size,
        )

    @classmethod
    def from_adapters(
        cls,
        adapters: tuple[Any, ...],
        env: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> "ProviderGovernance":
        active_env = {} if env is None else env
        manifests = {
            adapter.provider_id: entitlement_for_adapter(adapter, active_env)
            for adapter in adapters
        }
        return cls(manifests, **kwargs)

    def entitlement(self, provider_id: str) -> ProviderEntitlement:
        return self.authority.entitlement(provider_id)

    def startup_state(self, provider_id: str) -> dict[str, str]:
        manifest = self.entitlement(provider_id)
        dependency = self.dependencies.peek(provider_id, manifest.generation)
        return {
            "dependency_mode": dependency.mode.value,
            "dependency_reason": dependency.reason,
            "entitlement_generation": manifest.generation,
            "entitlement_manifest_sha256": manifest.manifest_sha256,
            "entitlement_request_limit": str(manifest.request_limit),
            "entitlement_cost_unit_limit": str(manifest.cost_unit_limit),
            "entitlement_spend_limit_micros": str(manifest.spend_limit_micros),
            "entitlement_max_concurrency": str(manifest.max_concurrency),
        }

    async def execute(
        self,
        request: AdmissionRequest,
        operation: Callable[[], Awaitable[T]],
    ) -> T:
        return await self.scheduler.execute(request, operation)

    async def record_success(self, provider_id: str) -> None:
        manifest = self.entitlement(provider_id)
        await self.dependencies.record_success(provider_id, manifest.generation)

    async def record_failure(
        self,
        provider_id: str,
        reason: str,
        *,
        retry_after_seconds: float | None = None,
    ) -> None:
        manifest = self.entitlement(provider_id)
        kind = _FAILURE_KIND_BY_VALUE.get(
            reason, DependencyFailureKind.UNKNOWN
        )
        await self.dependencies.record_failure(
            provider_id,
            manifest.generation,
            kind,
            retry_after_seconds=retry_after_seconds,
        )

    async def snapshot(self, provider_id: str) -> dict[str, object]:
        manifest = self.entitlement(provider_id)
        dependency = await self.dependencies.snapshot(
            provider_id, manifest.generation
        )
        spend = await self.authority.snapshot(provider_id)
        return spend | {
            "dependency_mode": dependency.mode.value,
            "dependency_reason": dependency.reason,
            "dependency_failures": dependency.consecutive_failures,
            "dependency_retry_at": dependency.retry_at,
        }


__all__ = ["ProviderGovernance", "entitlement_for_adapter"]
