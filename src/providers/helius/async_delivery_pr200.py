"""PR-200 non-blocking adapter for the durable Helius delivery plane."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import hmac
import time

from src.persistence.async_writer_pr200 import (
    AsyncPersistenceWriter,
    AsyncPersistenceWriterConfig,
    PersistenceCommit,
    PersistenceHealth,
    PersistenceOperation,
    PersistenceResult,
    PersistenceState,
    PersistenceWorkClass,
)
from src.providers.helius.delivery import (
    DeliveryDecision,
    DeliveryOutcome,
    HeliusDeliveryConfig,
    HeliusDeliveryPlane,
    RejectReason,
    SCHEMA_VERSION,
)

ASYNC_DELIVERY_SCHEMA_VERSION = "pr200.helius-async-delivery.v1"
_BOOTSTRAP_OPERATION_ID = "pr200.helius-async-delivery.bootstrap"
_BOOTSTRAP_DEADLINE_FLOOR_MS = 1_000


@dataclass(frozen=True, slots=True)
class AsyncDeliveryResult:
    schema_version: str
    operation_id: str
    persistence_state: PersistenceState
    outcome: DeliveryOutcome

    @property
    def acknowledged(self) -> bool:
        return (
            self.persistence_state is PersistenceState.COMMITTED
            and self.outcome.acknowledged
        )

    @property
    def retryable(self) -> bool:
        return not self.acknowledged and self.outcome.http_status == 503


class AsyncHeliusDeliveryPlane:
    """Run all Helius SQLite work on one owned persistence thread."""

    def __init__(
        self,
        config: HeliusDeliveryConfig,
        *,
        writer_config: AsyncPersistenceWriterConfig = AsyncPersistenceWriterConfig(),
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self.config = config
        self._monotonic_ns = monotonic_ns
        self._writer = AsyncPersistenceWriter(
            writer_config,
            monotonic_ns=monotonic_ns,
        )
        self._sync_plane: HeliusDeliveryPlane | None = None

    async def accept_delivery(
        self,
        *,
        headers: Mapping[str, str],
        raw_body: bytes,
        webhook_id: str | None = None,
        started_monotonic_ns: int | None = None,
    ) -> AsyncDeliveryResult:
        started_ns = (
            self._monotonic_ns()
            if started_monotonic_ns is None
            else started_monotonic_ns
        )
        operation_id = self._operation_id(
            headers=headers,
            raw_body=raw_body,
            webhook_id=webhook_id,
        )
        bootstrap = await self._ensure_plane_ready()
        if bootstrap.state is not PersistenceState.COMMITTED:
            return AsyncDeliveryResult(
                schema_version=ASYNC_DELIVERY_SCHEMA_VERSION,
                operation_id=operation_id,
                persistence_state=bootstrap.state,
                outcome=self._retryable_outcome(
                    started_ns=started_ns,
                    reason=RejectReason.STORE_ERROR,
                ),
            )

        delivery_started_ns = self._monotonic_ns()
        deadline_ns = (
            delivery_started_ns + self.config.limits.delivery_deadline_ms * 1_000_000
        )

        def run(absolute_deadline_ns: int) -> PersistenceCommit[DeliveryOutcome]:
            plane = self._plane_on_writer_thread()
            replay_started_ns = absolute_deadline_ns - (
                self.config.limits.delivery_deadline_ms * 1_000_000
            )
            outcome = plane.accept_delivery(
                headers=headers,
                raw_body=raw_body,
                webhook_id=webhook_id,
                started_monotonic_ns=replay_started_ns,
            )
            return PersistenceCommit(
                committed=outcome.acknowledged,
                value=outcome,
            )

        persistence = await self._writer.submit(
            PersistenceOperation(
                operation_id=operation_id,
                work_class=PersistenceWorkClass.WEBHOOK_DURABLE_ENQUEUE,
                deadline_ns=deadline_ns,
                estimated_bytes=len(raw_body),
                run=run,
            )
        )
        outcome = persistence.value
        if outcome is None:
            reason = (
                RejectReason.DELIVERY_DEADLINE_EXCEEDED
                if persistence.state is PersistenceState.NOT_SUBMITTED
                else RejectReason.STORE_ERROR
            )
            outcome = self._retryable_outcome(
                started_ns=delivery_started_ns,
                reason=reason,
            )
        return AsyncDeliveryResult(
            schema_version=ASYNC_DELIVERY_SCHEMA_VERSION,
            operation_id=operation_id,
            persistence_state=persistence.state,
            outcome=outcome,
        )

    def lookup(self, operation_id: str) -> PersistenceResult[object]:
        return self._writer.lookup(operation_id)

    def health(self) -> PersistenceHealth:
        return self._writer.health()

    async def close(self, *, cancel_optional: bool = True) -> PersistenceHealth:
        return await self._writer.close(cancel_optional=cancel_optional)

    async def _ensure_plane_ready(self) -> PersistenceResult[bool]:
        if self._sync_plane is not None:
            return PersistenceResult(
                operation_id=_BOOTSTRAP_OPERATION_ID,
                state=PersistenceState.COMMITTED,
                value=True,
            )

        bootstrap_budget_ms = max(
            _BOOTSTRAP_DEADLINE_FLOOR_MS,
            self.config.limits.delivery_deadline_ms,
            self.config.limits.sqlite_busy_timeout_ms * 4,
        )
        deadline_ns = self._monotonic_ns() + bootstrap_budget_ms * 1_000_000

        def run(_absolute_deadline_ns: int) -> PersistenceCommit[bool]:
            # HeliusDeliveryPlane construction initializes the SQLite schema. Keep
            # that blocking bootstrap on the dedicated writer thread, but do not let
            # a cold schema setup consume an individual webhook delivery deadline.
            self._plane_on_writer_thread()
            return PersistenceCommit(committed=True, value=True)

        return await self._writer.submit(
            PersistenceOperation(
                operation_id=_BOOTSTRAP_OPERATION_ID,
                work_class=PersistenceWorkClass.WEBHOOK_DURABLE_ENQUEUE,
                deadline_ns=deadline_ns,
                estimated_bytes=0,
                run=run,
            )
        )

    def _plane_on_writer_thread(self) -> HeliusDeliveryPlane:
        if self._sync_plane is None:
            # HeliusDeliveryPlane.__init__ initializes SQLite. This function is only
            # invoked by the dedicated writer, so construction is also off-loop.
            self._sync_plane = HeliusDeliveryPlane(
                self.config,
                monotonic_ns=self._monotonic_ns,
            )
        return self._sync_plane

    def _operation_id(
        self,
        *,
        headers: Mapping[str, str],
        raw_body: bytes,
        webhook_id: str | None,
    ) -> str:
        normalized_headers = {
            str(key).lower(): str(value) for key, value in headers.items()
        }
        content_encoding = normalized_headers.get(
            "content-encoding", "identity"
        ).lower().strip()
        received_auth = normalized_headers.get("authorization")
        if received_auth is None:
            auth_state = "missing"
        elif hmac.compare_digest(self.config.auth_header, received_auth):
            auth_state = "match"
        else:
            auth_state = "mismatch"
        material = b"\0".join(
            (
                ASYNC_DELIVERY_SCHEMA_VERSION.encode(),
                (webhook_id or self.config.webhook_id).encode(),
                self.config.cluster_genesis.encode(),
                content_encoding.encode(),
                auth_state.encode(),
                hashlib.sha256(raw_body).digest(),
            )
        )
        return hashlib.sha256(material).hexdigest()

    def _retryable_outcome(
        self,
        *,
        started_ns: int,
        reason: RejectReason,
    ) -> DeliveryOutcome:
        return DeliveryOutcome(
            schema_version=SCHEMA_VERSION,
            decision=DeliveryDecision.REJECTED,
            http_status=503,
            reason=reason.value,
            delivery_id=None,
            accepted_event_count=0,
            duplicate_event_count=0,
            payload_hash=None,
            gap_detected=False,
            backfill_required=False,
            duration_ms=max(
                0,
                (self._monotonic_ns() - started_ns) // 1_000_000,
            ),
        )


__all__ = [
    "ASYNC_DELIVERY_SCHEMA_VERSION",
    "AsyncDeliveryResult",
    "AsyncHeliusDeliveryPlane",
]
