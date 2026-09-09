"""Installed provider-governance authority and adapter entitlement factory."""

from __future__ import annotations

import time
import asyncio
import json
import hashlib
from contextvars import ContextVar
from dataclasses import dataclass, replace
import httpx
from typing import Any, Awaitable, Callable, Mapping, TypeVar, TYPE_CHECKING

if TYPE_CHECKING:
    from .profile import ConnectionProfile

from src.durability.unified_authority_pr02 import UnifiedLifecycleAuthority

from .authority import ProviderSpendAuthority
from .dependency import DependencyController
from .models import (
    AdmissionRequest,
    AdmissionCode,
    ProviderAdmissionError,
    DependencyFailureKind,
    ProviderEntitlement,
    ProviderGovernanceError,
    ProviderOperation,
    ProviderLease,
)
from .scheduler import DeadlineAdmissionScheduler

T = TypeVar("T")


@dataclass
class _PhysicalScope:
    request: AdmissionRequest
    denial: ProviderAdmissionError | None = None
    sequence: int = 0
    credential_ref: str | None = None
    credential_generation: str | None = None


_physical_scope: ContextVar[_PhysicalScope | None] = ContextVar(
    "provider_physical_scope", default=None
)


def entitlement_for_adapter(
    adapter: Any,
    env: Mapping[str, str],
    reviewed_entitlements: Mapping[str, ProviderEntitlement] | None = None,
) -> ProviderEntitlement:
    """Select explicit reviewed authority; capabilities and keys confer no quota."""
    provider_id = getattr(adapter, "provider_id", None)
    if not isinstance(provider_id, str) or not provider_id:
        raise ProviderGovernanceError("provider adapter lacks provider_id")
    if any(key.startswith("PROVIDER_") for key in env):
        raise ProviderGovernanceError(
            "provider entitlement environment overrides are forbidden"
        )
    manifest = (reviewed_entitlements or {}).get(provider_id)
    if manifest is None:
        raise ProviderAdmissionError(
            provider_id,
            AdmissionCode.MANIFEST_MISSING,
            "provider has no reviewed entitlement manifest",
            retryable=False,
            failure_reason="disabled",
        )
    if manifest.provider_id != provider_id:
        raise ProviderGovernanceError("reviewed entitlement mapping identity mismatch")
    return manifest


_FAILURE_KIND_BY_VALUE = {
    "rate_limited": DependencyFailureKind.RATE_LIMITED,
    "quota": DependencyFailureKind.QUOTA,
    "circuit_open": DependencyFailureKind.CIRCUIT_OPEN,
    "timeout": DependencyFailureKind.TIMEOUT,
    "transport": DependencyFailureKind.TRANSPORT,
    "http_error": DependencyFailureKind.TRANSPORT,
    "invalid_schema": DependencyFailureKind.INVALID_SCHEMA,
    "disabled": DependencyFailureKind.DISABLED,
    "auth": DependencyFailureKind.AUTH,
    "cancelled": DependencyFailureKind.CANCELLED,
}


class ProviderGovernance:
    """One runtime authority for entitlement, dependency and work scheduling."""

    connection_profile: ConnectionProfile | None = None

    def __init__(
        self,
        entitlements: Mapping[str, ProviderEntitlement],
        *,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        transient_failure_threshold: int = 2,
        cooldown_seconds: float = 30.0,
        max_queue_size: int = 4096,
        store: UnifiedLifecycleAuthority | None = None,
    ) -> None:
        self.authority = ProviderSpendAuthority(
            entitlements,
            clock=clock,
            wall_clock=wall_clock,
            store=store,
        )
        self.clock = self.authority.clock
        self.dependencies = DependencyController(
            clock=self.clock,
            authority=self.authority,
            transient_failure_threshold=transient_failure_threshold,
            cooldown_seconds=cooldown_seconds,
        )
        self.scheduler = DeadlineAdmissionScheduler(
            self.authority,
            self.dependencies,
            clock=self.clock,
            max_queue_size=max_queue_size,
        )

    @classmethod
    def from_adapters(
        cls,
        adapters: tuple[Any, ...],
        env: Mapping[str, str] | None = None,
        *,
        reviewed_entitlements: Mapping[str, ProviderEntitlement] | None = None,
        **kwargs: Any,
    ) -> "ProviderGovernance":
        provider_ids = tuple(
            getattr(adapter, "provider_id", None) for adapter in adapters
        )
        if len(provider_ids) != len(set(provider_ids)):
            raise ProviderGovernanceError("provider adapters must have unique IDs")
        active_env = {} if env is None else env
        if any(key.startswith("PROVIDER_") for key in active_env):
            raise ProviderGovernanceError(
                "provider entitlement environment overrides are forbidden"
            )
        manifests = {
            adapter.provider_id: entitlement_for_adapter(
                adapter, active_env, reviewed_entitlements
            )
            for adapter in adapters
            if adapter.provider_id in (reviewed_entitlements or {})
        }
        return cls(manifests, **kwargs)

    @classmethod
    def from_profile(cls, path, **kwargs: Any) -> "ProviderGovernance":
        """Use the canonical offline connection loader; resolve no credentials."""
        from .profile import load_connection_profile

        profile = load_connection_profile(path)
        runtime = cls(profile.entitlements, **kwargs)
        runtime.connection_profile = profile
        return runtime

    def entitlement(self, provider_id: str) -> ProviderEntitlement:
        return self.authority.entitlement(provider_id)

    def startup_state(self, provider_id: str) -> dict[str, str]:
        try:
            manifest = self.entitlement(provider_id)
        except ProviderAdmissionError:
            return {
                "dependency_mode": "disabled",
                "dependency_reason": "manifest_missing",
                "entitlement_generation": "",
                "entitlement_manifest_sha256": "",
                "state": "disabled_missing_entitlement",
            }
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

    def bind_transport(self, transport: Any) -> None:
        owner = getattr(transport, "_governance_owner", None)
        if owner is not None and owner is not self:
            raise ProviderGovernanceError(
                "transport already belongs to another governance authority"
            )
        if owner is None and (
            transport.attempt_guard is not None or transport.attempt_result is not None
        ):
            raise ProviderGovernanceError("transport already has attempt policy")
        transport._governance_owner = self
        transport.attempt_guard = self._issue_physical_attempt
        transport.attempt_result = self._finish_physical_attempt

    async def execute_physical(
        self,
        request: AdmissionRequest,
        operation: Callable[[], Awaitable[T]],
        *,
        credential_ref: str | None = None,
        credential_generation: str | None = None,
    ) -> T:
        scope = _PhysicalScope(
            request,
            credential_ref=credential_ref,
            credential_generation=credential_generation,
        )
        token = _physical_scope.set(scope)
        try:
            result = await operation()
            if scope.denial is not None:
                raise scope.denial
            return result
        finally:
            _physical_scope.reset(token)

    def _validate_physical_scope(
        self, request: httpx.Request, scope: _PhysicalScope
    ) -> None:
        manifest = self.entitlement(scope.request.provider_id)

        def deny() -> None:
            raise ProviderAdmissionError(
                scope.request.provider_id,
                AdmissionCode.PHYSICAL_SCOPE_DENIED,
                "physical endpoint, method or credential scope is not reviewed",
                retryable=False,
                failure_reason="disabled",
            )

        endpoint = str(request.url.copy_with(query=None, fragment=None))
        if (
            endpoint not in manifest.allowed_endpoints
            or request.method not in manifest.allowed_http_methods
            or manifest.credential_ref is None
            or manifest.credential_generation is None
            or scope.credential_ref != manifest.credential_ref
            or scope.credential_generation != manifest.credential_generation
        ):
            deny()
        forbidden_query = {
            "apikey",
            "key",
            "token",
            "accesstoken",
            "authorization",
            "secret",
            "password",
            "signature",
        }
        for key in request.url.params:
            normalized = "".join(char for char in key.lower() if char.isalnum())
            if (
                key not in manifest.allowed_query_parameters
                or normalized in forbidden_query
            ):
                deny()
        if manifest.allowed_rpc_methods:
            # Only sender-free methods may pass even if an unsafe method was reviewed.
            allowed = {
                "simulateTransaction",
                "getMultipleAccounts",
                "getLatestBlockhash",
                "isBlockhashValid",
                "getBlockHeight",
                "getFeeForMessage",
                "getGenesisHash",
                "getSlot",
                "getTransaction",
            }
            if request.method != "POST" or len(request.content) > 1_048_576:
                deny()
            try:
                body = json.loads(
                    request.content, object_pairs_hook=_unique_request_object
                )
            except (ValueError, UnicodeDecodeError, RecursionError):
                deny()
            if (
                not isinstance(body, dict)
                or body.get("jsonrpc") != "2.0"
                or not isinstance(body.get("method"), str)
                or body.get("method") not in allowed
                or body.get("method") not in manifest.allowed_rpc_methods
            ):
                deny()
        elif request.content:
            # An RPC envelope must never fall through an ordinary REST scope.
            try:
                body = json.loads(request.content)
            except (ValueError, UnicodeDecodeError, RecursionError):
                body = None
            if isinstance(body, list) or (
                isinstance(body, dict) and ("jsonrpc" in body or "method" in body)
            ):
                deny()

    async def _issue_physical_attempt(
        self, request: httpx.Request, attempt: int
    ) -> ProviderLease:
        scope = _physical_scope.get()
        if scope is None:
            raise ProviderAdmissionError(
                "unbound",
                AdmissionCode.MANIFEST_MISSING,
                "physical request lacks governance scope",
                retryable=False,
                failure_reason="disabled",
            )
        scope.sequence += 1
        # Hash the exact physical URL, headers and payload without retaining raw secrets.
        identity = hashlib.sha256(
            request.method.encode()
            + b"\0"
            + str(request.url).encode()
            + b"\0"
            + repr(tuple(request.headers.multi_items())).encode()
            + b"\0"
            + request.content
        ).hexdigest()
        admission = replace(
            scope.request,
            work_id=f"{scope.request.work_id}:http:{scope.sequence}",
            request_fingerprint=identity,
        )
        lease = None
        try:
            self._validate_physical_scope(request, scope)
            lease = await self.scheduler.acquire(admission)
            await self.dependencies.assert_admissible(
                lease.provider_id, lease.entitlement_generation, lease.operation
            )
            self._validate_physical_scope(request, scope)
            await self.authority.mark_issued(lease)
            return lease
        except ProviderAdmissionError as exc:
            scope.denial = exc
            if lease is not None:
                await self.authority.release(lease)
            raise
        except BaseException:
            if lease is not None:
                await self.authority.release(lease)
            raise

    async def _finish_physical_attempt(
        self, lease: ProviderLease, status: int | None, unknown: bool
    ) -> None:
        async def cleanup() -> None:
            if unknown:
                await self.authority.mark_unknown(lease)
            else:
                await self.authority.complete(lease)
            if status in {401, 403, 429}:
                await self.record_failure(
                    lease.provider_id,
                    "http_error" if status != 429 else "rate_limited",
                    generation=lease.entitlement_generation,
                    status_code=status,
                )

        task = asyncio.create_task(cleanup())
        self.scheduler._cleanup_tasks.add(task)
        task.add_done_callback(self.scheduler._cleanup_tasks.discard)
        await asyncio.shield(task)

    async def record_success(
        self,
        provider_id: str,
        operation: ProviderOperation = ProviderOperation.DISCOVERY,
        *,
        generation: str,
    ) -> None:
        await self.dependencies.record_success(
            provider_id,
            generation,
            operation,
        )

    async def record_failure(
        self,
        provider_id: str,
        reason: str,
        *,
        generation: str,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        kind = (
            DependencyFailureKind.AUTH
            if status_code in {401, 403}
            else _FAILURE_KIND_BY_VALUE.get(reason, DependencyFailureKind.UNKNOWN)
        )
        await self.dependencies.record_failure(
            provider_id,
            generation,
            kind,
            retry_after_seconds=retry_after_seconds,
        )

    async def snapshot(self, provider_id: str) -> dict[str, object]:
        manifest = self.entitlement(provider_id)
        dependency = await self.dependencies.snapshot(provider_id, manifest.generation)
        spend = await self.authority.snapshot(provider_id)
        return spend | {
            "dependency_mode": dependency.mode.value,
            "dependency_reason": dependency.reason,
            "dependency_failures": dependency.consecutive_failures,
            "dependency_retry_at": dependency.retry_at,
        }


def _unique_request_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate RPC request key")
        result[key] = value
    return result


__all__ = ["ProviderGovernance", "entitlement_for_adapter"]
