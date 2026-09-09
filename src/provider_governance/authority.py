"""Transactional provider entitlement and spend authority."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from contextlib import contextmanager, asynccontextmanager
import hashlib
import json
import time
from typing import Callable, Mapping
from uuid import uuid4
from src.durability.unified_authority_pr02 import UnifiedLifecycleAuthority

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
    spend_started_at: float = 0.0
    last_observed_at: float = 0.0
    overrun: bool = False
    dependency: dict | None = None
    manifests: dict | None = None
    limits: dict | None = None


@dataclass(slots=True)
class _LeaseRecord:
    lease: ProviderLease
    state: LeaseState
    completion: tuple[int, int] | None = None


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
        store: UnifiedLifecycleAuthority | None = None,
    ) -> None:
        for provider_id, manifest in entitlements.items():
            if provider_id != manifest.provider_id:
                raise ProviderGovernanceError(
                    "entitlement mapping key must match manifest provider_id"
                )
        self._entitlements = dict(entitlements)
        self.store = store
        if store is not None:
            store.install_provider_governance_schema()
            clock = lambda: store._snapshot().utc_ns / 1_000_000_000
            wall_clock = clock
        self.clock = clock
        self.wall_clock = wall_clock
        now = self.clock()
        self._windows = {
            provider_id: _WindowState(started_at=now)
            for provider_id in self._entitlements
        }
        self._leases: dict[str, _LeaseRecord] = {}
        self._lock = asyncio.Lock()
        self._pool_for = {
            key: manifest.quota_pool_ref or key
            for key, manifest in self._entitlements.items()
        }
        for key, pool in self._pool_for.items():
            peers = [k for k, p in self._pool_for.items() if p == pool]
            if peers[0] != key:
                peer = self._entitlements[peers[0]]
                current = self._entitlements[key]
                for field in (
                    "request_limit",
                    "cost_unit_limit",
                    "spend_limit_micros",
                    "window_seconds",
                    "spend_window_seconds",
                    "max_concurrency",
                ):
                    if getattr(peer, field) != getattr(current, field):
                        raise ProviderGovernanceError(
                            "aliases disagree on external pool limits"
                        )
                self._windows[key] = self._windows[peers[0]]

    @contextmanager
    def _transaction(self, *, readonly=False):
        if self.store is None:
            yield
            return
        with self.store.lifecycle.write_transaction():
            db = self.store.db
            pools = {}
            for key, pool in self._pool_for.items():
                if pool not in pools:
                    row = db.execute(
                        "SELECT payload,payload_hash FROM pr02_provider_state WHERE pool=?",
                        (pool,),
                    ).fetchone()
                    if row:
                        if hashlib.sha256(row[0].encode()).hexdigest() != row[1]:
                            raise ProviderGovernanceError(
                                "provider state hash mismatch"
                            )
                        pools[pool] = _WindowState(**json.loads(row[0]))
                    else:
                        now = self.clock()
                        pools[pool] = _WindowState(started_at=now, spend_started_at=now)
                self._windows[key] = pools[pool]
            self._leases.clear()
            for row in db.execute(
                "SELECT payload,state,completion_hash,semantic_hash,attempt_id FROM pr02_provider_attempts"
            ):
                payload = json.loads(row[0])
                lease = ProviderLease(**payload["lease"])
                if lease.provider_id not in self._pool_for:
                    continue
                semantic = hashlib.sha256(
                    json.dumps(asdict(lease), sort_keys=True).encode()
                ).hexdigest()
                if semantic != row[3] or lease.lease_id != row[4]:
                    raise ProviderGovernanceError("provider semantic binding corrupted")
                # Preserve enum identity after deserialization.
                object.__setattr__(
                    lease, "operation", ProviderOperation(lease.operation)
                )
                completion = payload.get("completion")
                completion_hash = (
                    None
                    if completion is None
                    else hashlib.sha256(str(tuple(completion)).encode()).hexdigest()
                )
                if completion_hash != row[2]:
                    raise ProviderGovernanceError(
                        "provider completion binding corrupted"
                    )
                self._leases[lease.lease_id] = _LeaseRecord(
                    lease,
                    LeaseState(row[1]),
                    None if completion is None else tuple(completion),
                )
            now = self.clock()
            for state in pools.values():
                if now < state.last_observed_at:
                    raise ProviderGovernanceError("provider trusted clock regressed")
                if not readonly:
                    state.last_observed_at = now
            yield
            if readonly:
                return
            for pool, state in pools.items():
                payload = json.dumps(
                    asdict(state),
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                db.execute(
                    "INSERT INTO pr02_provider_state VALUES(?,0,?,?) "
                    "ON CONFLICT(pool) DO UPDATE SET revision=revision+1,payload=excluded.payload,payload_hash=excluded.payload_hash",
                    (pool, payload, hashlib.sha256(payload.encode()).hexdigest()),
                )
            for record in self._leases.values():
                lease = record.lease
                payload = json.dumps(
                    {"lease": asdict(lease), "completion": record.completion},
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                semantic = hashlib.sha256(
                    json.dumps(asdict(lease), sort_keys=True).encode()
                ).hexdigest()
                completion_hash = (
                    None
                    if record.completion is None
                    else hashlib.sha256(str(record.completion).encode()).hexdigest()
                )
                db.execute(
                    "INSERT INTO pr02_provider_attempts VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(attempt_id) DO UPDATE SET state=excluded.state,payload=excluded.payload,completion_hash=excluded.completion_hash",
                    (
                        lease.lease_id,
                        self._pool_for[lease.provider_id],
                        semantic,
                        record.state.value,
                        payload,
                        completion_hash,
                    ),
                )

    @asynccontextmanager
    async def _locked_transaction(self, *, readonly=False):
        async with self._lock:
            with self._transaction(readonly=readonly):
                yield

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

        previous = self.entitlement(manifest.provider_id)
        if (manifest.quota_pool_ref or manifest.provider_id) != self._pool_for[
            manifest.provider_id
        ]:
            raise ProviderGovernanceError("rotation cannot replace accounting pool")
        if manifest.spend_window_seconds != previous.spend_window_seconds:
            raise ProviderGovernanceError("rotation cannot reset spend period")
        with self._transaction():
            state = self._windows[manifest.provider_id]
            self._assert_manifest(previous, state)
            assert state.manifests is not None
            for key, peer in self._entitlements.items():
                if (
                    key != manifest.provider_id
                    and self._pool_for[key] == self._pool_for[manifest.provider_id]
                ):
                    if self._limits(peer) != self._limits(manifest):
                        raise ProviderGovernanceError(
                            "rotation conflicts with alias pool limits"
                        )
            state.manifests[manifest.provider_id] = manifest.manifest_sha256
            state.limits = self._limits(manifest)
            if state.dependency is not None:
                state.dependency = dict(
                    state.dependency, generation=manifest.generation
                )
        self._entitlements[manifest.provider_id] = manifest
        self._windows.setdefault(
            manifest.provider_id, _WindowState(started_at=self.clock())
        )

    @staticmethod
    def _limits(manifest):
        return {
            name: getattr(manifest, name)
            for name in (
                "request_limit",
                "cost_unit_limit",
                "spend_limit_micros",
                "window_seconds",
                "spend_window_seconds",
                "max_concurrency",
                "finalization_reserve_requests",
                "finalization_reserve_cost_units",
                "finalization_reserve_spend_micros",
            )
        }

    def _assert_manifest(self, manifest, state):
        if state.manifests is None:
            state.manifests = {}
        if state.limits is None:
            state.limits = self._limits(manifest)
        if state.limits != self._limits(manifest):
            raise ProviderGovernanceError("durable pool policy limits mismatch")
        digest = state.manifests.get(manifest.provider_id)
        if digest is not None and digest != manifest.manifest_sha256:
            raise self._deny(
                manifest,
                AdmissionCode.GENERATION_MISMATCH,
                "durable entitlement was replaced",
                retryable=False,
            )
        state.manifests[manifest.provider_id] = manifest.manifest_sha256

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
        if now - state.spend_started_at >= manifest.spend_window_seconds:
            state.spend_started_at = now
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
        async with self._locked_transaction():
            now = self.clock()
            self._expire_unissued_locked(now)
            manifest = self.entitlement(request.provider_id)
            self._assert_manifest(manifest, self._windows[request.provider_id])
            for record in self._leases.values():
                lease = record.lease
                if (
                    lease.provider_id == request.provider_id
                    and lease.work_id == request.work_id
                ):
                    if (
                        lease.request_fingerprint != request.request_fingerprint
                        or lease.operation != request.operation
                        or lease.estimated_cost_units != request.estimated_cost_units
                        or lease.estimated_spend_micros
                        != request.estimated_spend_micros
                        or lease.manifest_sha256 != manifest.manifest_sha256
                    ):
                        raise ProviderGovernanceError(
                            "provider semantic replay conflict"
                        )
                    return lease
            if len(self._leases) >= 10000:
                raise ProviderGovernanceError(
                    "provider replay horizon capacity exhausted"
                )
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
            if state.overrun:
                raise ProviderGovernanceError(
                    "provider overrun requires reconciliation review"
                )
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
                owner_boot_id=(
                    "process-local"
                    if self.store is None
                    else self.store._snapshot().boot_id
                ),
                owner_process_generation=(
                    1
                    if self.store is None
                    else self.store._snapshot().process_generation
                ),
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
        async with self._locked_transaction():
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
            self._assert_manifest(current, self._windows[lease.provider_id])
            if self.store is not None and (
                lease.owner_boot_id != self.store._snapshot().boot_id
                or lease.owner_process_generation
                != self.store._snapshot().process_generation
            ):
                raise ProviderGovernanceError("unissued lease belongs to an old boot")
            if (
                current.expires_at_epoch_seconds is not None
                and self.wall_clock() >= current.expires_at_epoch_seconds
            ):
                self._release_reserved(self._windows[lease.provider_id], lease)
                record.state = LeaseState.RELEASED
                raise self._deny(
                    current,
                    AdmissionCode.MANIFEST_EXPIRED,
                    "entitlement expired before physical issuance",
                    retryable=False,
                )
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
        async with self._locked_transaction():
            record = self._record(lease)
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
            if record.state is LeaseState.COMPLETED:
                if record.completion != (cost, spend):
                    raise ProviderGovernanceError("completion replay conflict")
                return
            if record.state not in (LeaseState.ISSUED, LeaseState.OUTCOME_UNKNOWN):
                raise ProviderGovernanceError("completion without physical issuance")
            state = self._windows[lease.provider_id]
            state.overrun |= (
                cost > lease.estimated_cost_units
                or spend > lease.estimated_spend_micros
            )
            self._release_reserved(state, lease)
            state.committed_requests += 1
            state.committed_cost_units += cost
            state.committed_spend_micros += spend
            record.state = LeaseState.COMPLETED
            record.completion = (cost, spend)

    async def mark_unknown(self, lease: ProviderLease) -> None:
        async with self._locked_transaction():
            record = self._record(lease)
            if record.state not in (LeaseState.ISSUED, LeaseState.OUTCOME_UNKNOWN):
                raise ProviderGovernanceError("unknown outcome requires issuance")
            record.state = LeaseState.OUTCOME_UNKNOWN

    async def release(self, lease: ProviderLease) -> None:
        async with self._locked_transaction():
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
        async with self._locked_transaction(readonly=True):
            now = self.clock()
            manifest = self.entitlement(provider_id)
            state = self._windows[provider_id]
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
