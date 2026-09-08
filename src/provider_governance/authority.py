"""Transactional provider entitlement and spend authority."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from typing import Callable, Mapping
from uuid import uuid4

from .models import (
    AdmissionCode,
    AdmissionRequest,
    LeaseState,
    ProviderAdmissionError,
    ProviderEntitlement,
    ProviderGovernanceError,
    ProviderLease,
    ProviderOperation,
)


@dataclass(slots=True)
class _WindowState:
    started_at: float
    reserved_requests: int = 0
    committed_requests: int = 0
    reserved_cost_units: int = 0
    committed_cost_units: int = 0
    reserved_spend_micros: int = 0
    committed_spend_micros: int = 0
    active_leases: int = 0


@dataclass(slots=True)
class _LeaseRecord:
    lease: ProviderLease
    state: LeaseState


class ProviderSpendAuthority:
    """Own provider request, cost, spend and concurrency reservations.

    Capacity is reserved before work is issued. Once a lease is marked issued,
    cancellation or provider failure still consumes the reservation because the
    external side effect may already have happened.
    """

    def __init__(
        self,
        entitlements: Mapping[str, ProviderEntitlement],
        *,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        if not entitlements:
            raise ProviderGovernanceError(
                "at least one provider entitlement is required"
            )
        for provider_id, manifest in entitlements.items():
            if provider_id != manifest.provider_id:
                raise ProviderGovernanceError(
                    "entitlement mapping key must match manifest provider_id"
                )
        self._entitlements = dict(entitlements)
        self.clock = clock
        self.wall_clock = wall_clock
        now = self.clock()
        self._windows = {
            provider_id: _WindowState(started_at=now)
            for provider_id in self._entitlements
        }
        self._leases: dict[str, _LeaseRecord] = {}
        self._lock = asyncio.Lock()

    def entitlement(self, provider_id: str) -> ProviderEntitlement:
        try:
            return self._entitlements[provider_id]
        except KeyError as exc:
            raise ProviderAdmissionError(
                provider_id,
                AdmissionCode.MANIFEST_MISSING,
                "provider has no entitlement manifest",
                retryable=False,
                failure_reason="disabled",
            ) from exc

    def entitlements(self) -> tuple[ProviderEntitlement, ...]:
        return tuple(self._entitlements[key] for key in sorted(self._entitlements))

    def replace_entitlement(self, manifest: ProviderEntitlement) -> None:
        """Install a reviewed generation for future reservations.

        Existing issued leases retain their original generation and complete
        against the capacity they reserved. Unissued leases are generation-
        fenced immediately before issue and cannot contact a provider after a
        manifest replacement.
        """

        self._entitlements[manifest.provider_id] = manifest
        self._windows.setdefault(
            manifest.provider_id, _WindowState(started_at=self.clock())
        )

    def _reset_window_if_needed(
        self,
        manifest: ProviderEntitlement,
        state: _WindowState,
        now: float,
    ) -> None:
        if now - state.started_at < manifest.window_seconds:
            return
        if state.active_leases:
            # Active work is generation-bound and cannot be erased by a clock
            # boundary. The next window begins after the final active lease.
            return
        state.started_at = now
        state.reserved_requests = 0
        state.committed_requests = 0
        state.reserved_cost_units = 0
        state.committed_cost_units = 0
        state.reserved_spend_micros = 0
        state.committed_spend_micros = 0

    def _release_reserved(self, state: _WindowState, lease: ProviderLease) -> None:
        state.reserved_requests -= 1
        state.reserved_cost_units -= lease.estimated_cost_units
        state.reserved_spend_micros -= lease.estimated_spend_micros
        state.active_leases -= 1
        if (
            min(
                state.reserved_requests,
                state.reserved_cost_units,
                state.reserved_spend_micros,
                state.active_leases,
            )
            < 0
        ):
            raise ProviderGovernanceError("provider authority counters underflowed")

    def _expire_unissued_locked(self, now: float) -> None:
        for record in tuple(self._leases.values()):
            if record.state is not LeaseState.RESERVED:
                continue
            if record.lease.expires_at > now:
                continue
            state = self._windows[record.lease.provider_id]
            self._release_reserved(state, record.lease)
            record.state = LeaseState.EXPIRED

    def _deny(
        self,
        manifest: ProviderEntitlement,
        code: AdmissionCode,
        detail: str,
        *,
        retryable: bool,
        retry_at: float | None = None,
        failure_reason: str | None = None,
    ) -> ProviderAdmissionError:
        return ProviderAdmissionError(
            manifest.provider_id,
            code,
            detail,
            retryable=retryable,
            retry_at=retry_at,
            failure_reason=failure_reason,
        )

    async def reserve(self, request: AdmissionRequest) -> ProviderLease:
        async with self._lock:
            now = self.clock()
            self._expire_unissued_locked(now)
            manifest = self.entitlement(request.provider_id)
            if (
                manifest.expires_at_epoch_seconds is not None
                and self.wall_clock() >= manifest.expires_at_epoch_seconds
            ):
                raise self._deny(
                    manifest,
                    AdmissionCode.MANIFEST_EXPIRED,
                    "provider entitlement manifest has expired",
                    retryable=False,
                    failure_reason="disabled",
                )
            if (
                request.expected_generation is not None
                and request.expected_generation != manifest.generation
            ):
                raise self._deny(
                    manifest,
                    AdmissionCode.GENERATION_MISMATCH,
                    "work was built for a different entitlement generation",
                    retryable=False,
                    failure_reason="disabled",
                )
            if request.operation not in manifest.allowed_operations:
                raise self._deny(
                    manifest,
                    AdmissionCode.OPERATION_NOT_ENTITLED,
                    f"{request.operation.value} is not allowed by the manifest",
                    retryable=False,
                    failure_reason="disabled",
                )
            if request.deadline_at <= now:
                raise self._deny(
                    manifest,
                    AdmissionCode.DEADLINE_EXPIRED,
                    "work deadline elapsed before reservation",
                    retryable=False,
                    failure_reason="timeout",
                )

            state = self._windows[manifest.provider_id]
            self._reset_window_if_needed(manifest, state, now)
            retry_at = state.started_at + manifest.window_seconds
            if state.active_leases >= manifest.max_concurrency:
                raise self._deny(
                    manifest,
                    AdmissionCode.CONCURRENCY_EXHAUSTED,
                    "provider concurrency entitlement is exhausted",
                    retryable=True,
                    failure_reason="rate_limited",
                )

            is_finalization = request.operation is ProviderOperation.FINALIZATION
            request_cap = manifest.request_limit
            cost_cap = manifest.cost_unit_limit
            spend_cap = manifest.spend_limit_micros
            if not is_finalization:
                request_cap -= manifest.finalization_reserve_requests
                cost_cap -= manifest.finalization_reserve_cost_units
                if spend_cap:
                    spend_cap -= manifest.finalization_reserve_spend_micros

            occupied_requests = state.reserved_requests + state.committed_requests
            occupied_cost = state.reserved_cost_units + state.committed_cost_units
            occupied_spend = state.reserved_spend_micros + state.committed_spend_micros
            if occupied_requests + 1 > request_cap:
                code = (
                    AdmissionCode.FINALIZATION_RESERVE_PROTECTED
                    if not is_finalization and request_cap < manifest.request_limit
                    else AdmissionCode.REQUEST_QUOTA_EXHAUSTED
                )
                raise self._deny(
                    manifest,
                    code,
                    "provider request window has no admissible capacity",
                    retryable=True,
                    retry_at=retry_at,
                    failure_reason="rate_limited",
                )
            if occupied_cost + request.estimated_cost_units > cost_cap:
                code = (
                    AdmissionCode.FINALIZATION_RESERVE_PROTECTED
                    if not is_finalization and cost_cap < manifest.cost_unit_limit
                    else AdmissionCode.COST_QUOTA_EXHAUSTED
                )
                raise self._deny(
                    manifest,
                    code,
                    "provider cost-unit window has no admissible capacity",
                    retryable=True,
                    retry_at=retry_at,
                    failure_reason="rate_limited",
                )
            if request.estimated_spend_micros:
                if (
                    spend_cap == 0
                    or occupied_spend + request.estimated_spend_micros > spend_cap
                ):
                    code = (
                        AdmissionCode.FINALIZATION_RESERVE_PROTECTED
                        if not is_finalization
                        and manifest.finalization_reserve_spend_micros
                        else AdmissionCode.SPEND_LIMIT_EXHAUSTED
                    )
                    raise self._deny(
                        manifest,
                        code,
                        "provider monetary spend limit has no admissible capacity",
                        retryable=True,
                        retry_at=retry_at,
                        failure_reason="rate_limited",
                    )

            lease = ProviderLease(
                lease_id=uuid4().hex,
                work_id=request.work_id,
                provider_id=manifest.provider_id,
                operation=request.operation,
                request_fingerprint=request.request_fingerprint,
                entitlement_generation=manifest.generation,
                manifest_sha256=manifest.manifest_sha256,
                reserved_at=now,
                expires_at=min(request.deadline_at, now + request.lease_ttl_seconds),
                estimated_cost_units=request.estimated_cost_units,
                estimated_spend_micros=request.estimated_spend_micros,
            )
            self._leases[lease.lease_id] = _LeaseRecord(
                lease=lease, state=LeaseState.RESERVED
            )
            state.reserved_requests += 1
            state.reserved_cost_units += lease.estimated_cost_units
            state.reserved_spend_micros += lease.estimated_spend_micros
            state.active_leases += 1
            return lease

    def _record(self, lease: ProviderLease) -> _LeaseRecord:
        try:
            record = self._leases[lease.lease_id]
        except KeyError as exc:
            raise ProviderGovernanceError("unknown provider lease") from exc
        if record.lease != lease:
            raise ProviderGovernanceError("provider lease identity mismatch")
        return record

    async def mark_issued(self, lease: ProviderLease) -> None:
        async with self._lock:
            record = self._record(lease)
            if record.state is not LeaseState.RESERVED:
                raise ProviderAdmissionError(
                    lease.provider_id,
                    AdmissionCode.LEASE_STATE_INVALID,
                    f"cannot issue lease in state {record.state.value}",
                    retryable=False,
                    failure_reason="disabled",
                )
            current = self.entitlement(lease.provider_id)
            if (
                lease.entitlement_generation != current.generation
                or lease.manifest_sha256 != current.manifest_sha256
            ):
                state = self._windows[lease.provider_id]
                self._release_reserved(state, lease)
                record.state = LeaseState.RELEASED
                raise ProviderAdmissionError(
                    lease.provider_id,
                    AdmissionCode.GENERATION_MISMATCH,
                    "reserved work belongs to a replaced entitlement manifest",
                    retryable=False,
                    failure_reason="disabled",
                )
            if lease.expires_at <= self.clock():
                state = self._windows[lease.provider_id]
                self._release_reserved(state, lease)
                record.state = LeaseState.EXPIRED
                raise ProviderAdmissionError(
                    lease.provider_id,
                    AdmissionCode.DEADLINE_EXPIRED,
                    "provider lease expired before issue",
                    retryable=False,
                    failure_reason="timeout",
                )
            record.state = LeaseState.ISSUED

    async def complete(
        self,
        lease: ProviderLease,
        *,
        actual_cost_units: int | None = None,
        actual_spend_micros: int | None = None,
    ) -> None:
        async with self._lock:
            record = self._record(lease)
            if record.state is not LeaseState.ISSUED:
                raise ProviderGovernanceError(
                    f"cannot complete lease in state {record.state.value}"
                )
            cost = (
                lease.estimated_cost_units
                if actual_cost_units is None
                else actual_cost_units
            )
            spend = (
                lease.estimated_spend_micros
                if actual_spend_micros is None
                else actual_spend_micros
            )
            if type(cost) is not int or cost < 0:
                raise ProviderGovernanceError("actual_cost_units must be non-negative")
            if type(spend) is not int or spend < 0:
                raise ProviderGovernanceError(
                    "actual_spend_micros must be non-negative"
                )
            if cost > lease.estimated_cost_units:
                raise ProviderGovernanceError(
                    "actual cost exceeded the reservation upper bound"
                )
            if spend > lease.estimated_spend_micros:
                raise ProviderGovernanceError(
                    "actual spend exceeded the reservation upper bound"
                )
            state = self._windows[lease.provider_id]
            self._release_reserved(state, lease)
            state.committed_requests += 1
            state.committed_cost_units += cost
            state.committed_spend_micros += spend
            record.state = LeaseState.COMPLETED

    async def release(self, lease: ProviderLease) -> None:
        async with self._lock:
            record = self._record(lease)
            if record.state in (LeaseState.RELEASED, LeaseState.EXPIRED):
                return
            if record.state is not LeaseState.RESERVED:
                raise ProviderGovernanceError(
                    "issued provider work cannot be released as unspent"
                )
            state = self._windows[lease.provider_id]
            self._release_reserved(state, lease)
            record.state = LeaseState.RELEASED

    async def snapshot(self, provider_id: str) -> dict[str, object]:
        async with self._lock:
            now = self.clock()
            self._expire_unissued_locked(now)
            manifest = self.entitlement(provider_id)
            state = self._windows[provider_id]
            self._reset_window_if_needed(manifest, state, now)
            return {
                "provider_id": provider_id,
                "generation": manifest.generation,
                "manifest_sha256": manifest.manifest_sha256,
                "window_started_at": state.started_at,
                "window_resets_at": state.started_at + manifest.window_seconds,
                "reserved_requests": state.reserved_requests,
                "committed_requests": state.committed_requests,
                "reserved_cost_units": state.reserved_cost_units,
                "committed_cost_units": state.committed_cost_units,
                "reserved_spend_micros": state.reserved_spend_micros,
                "committed_spend_micros": state.committed_spend_micros,
                "active_leases": state.active_leases,
            }


__all__ = ["ProviderSpendAuthority"]
