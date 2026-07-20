"""WebSocket reconnect, resubscribe, heartbeat and slot-gap state machine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib

from .common import (
    CommitmentLevel,
    DataConsistencyPolicy,
    DataPlaneError,
    DataPlaneReason,
    ReadinessState,
    canonical_hash,
    non_empty,
    non_negative_int,
    sha256_hex,
)
from .readiness import ReadinessReport


class SubscriptionState(str, Enum):
    DISCONNECTED = "disconnected"
    RESUBSCRIBE_REQUIRED = "resubscribe_required"
    ACTIVE = "active"
    GAP_DETECTED = "gap_detected"


@dataclass(frozen=True, slots=True)
class SubscriptionSpec:
    key: str
    method: str
    params_hash: str
    commitment: CommitmentLevel

    def __post_init__(self) -> None:
        non_empty(self.key, "key")
        non_empty(self.method, "method")
        sha256_hex(self.params_hash, "params_hash")


@dataclass(frozen=True, slots=True)
class WsEndpointSnapshot:
    endpoint_id: str
    generation: int
    connected: bool
    state: str
    pending_keys: tuple[str, ...]
    active_keys: tuple[str, ...]
    last_context_slot: int | None
    gap_from_slot: int | None
    gap_to_slot: int | None


@dataclass(frozen=True, slots=True)
class WsNotificationDecision:
    accepted: bool
    reason: DataPlaneReason
    requires_polling_backfill: bool
    evidence_hash: str


@dataclass(slots=True)
class _State:
    endpoint_id: str
    generation: int = 0
    connected: bool = False
    state: str = SubscriptionState.DISCONNECTED
    server_ids: dict[str, int] = field(default_factory=dict)
    last_slots: dict[str, int] = field(default_factory=dict)
    last_pong_ms: int | None = None
    gap_from: int | None = None
    gap_to: int | None = None


class WebSocketSubscriptionSupervisor:
    def __init__(self, policy: DataConsistencyPolicy) -> None:
        self.policy = policy
        self.desired: dict[str, SubscriptionSpec] = {}
        self.endpoints: dict[str, _State] = {}

    def register(self, spec: SubscriptionSpec) -> None:
        existing = self.desired.get(spec.key)
        if existing and existing != spec:
            raise DataPlaneError(
                DataPlaneReason.INVALID_INPUT,
                "subscription key cannot change parameters",
            )
        self.desired[spec.key] = spec
        for endpoint_state in self.endpoints.values():
            if endpoint_state.connected:
                endpoint_state.state = SubscriptionState.RESUBSCRIBE_REQUIRED

    def on_connected(self, endpoint_id: str, now_monotonic_ms: int) -> int:
        non_empty(endpoint_id, "endpoint_id")
        non_negative_int(now_monotonic_ms, "now_monotonic_ms")
        endpoint_state = self.endpoints.setdefault(endpoint_id, _State(endpoint_id))
        endpoint_state.generation += 1
        endpoint_state.connected = True
        endpoint_state.state = SubscriptionState.RESUBSCRIBE_REQUIRED
        endpoint_state.server_ids.clear()
        endpoint_state.last_slots.clear()
        endpoint_state.last_pong_ms = now_monotonic_ms
        endpoint_state.gap_from = endpoint_state.gap_to = None
        return endpoint_state.generation

    def bind_subscription(
        self,
        endpoint_id: str,
        *,
        generation: int,
        key: str,
        server_subscription_id: int,
    ) -> None:
        endpoint_state = self._state(endpoint_id)
        if not endpoint_state.connected or generation != endpoint_state.generation:
            raise DataPlaneError(
                DataPlaneReason.WS_RESUBSCRIBE_REQUIRED,
                "acknowledgement belongs to an inactive generation",
            )
        if key not in self.desired:
            raise DataPlaneError(
                DataPlaneReason.WS_UNKNOWN_SUBSCRIPTION,
                "unknown desired subscription",
            )
        non_negative_int(server_subscription_id, "server_subscription_id")
        if server_subscription_id in endpoint_state.server_ids.values():
            raise DataPlaneError(DataPlaneReason.INVALID_INPUT, "duplicate server id")
        endpoint_state.server_ids[key] = server_subscription_id
        endpoint_state.state = (
            SubscriptionState.ACTIVE
            if set(endpoint_state.server_ids) == set(self.desired)
            else SubscriptionState.RESUBSCRIBE_REQUIRED
        )

    def on_pong(self, endpoint_id: str, now_monotonic_ms: int) -> None:
        endpoint_state = self._state(endpoint_id)
        if not endpoint_state.connected:
            raise DataPlaneError(DataPlaneReason.WS_DISCONNECTED, "endpoint is down")
        endpoint_state.last_pong_ms = non_negative_int(
            now_monotonic_ms, "now_monotonic_ms"
        )

    def on_notification(
        self,
        endpoint_id: str,
        *,
        generation: int,
        key: str,
        context_slot: int,
        now_monotonic_ms: int,
    ) -> WsNotificationDecision:
        endpoint_state = self._state(endpoint_id)
        non_negative_int(context_slot, "context_slot")
        non_negative_int(now_monotonic_ms, "now_monotonic_ms")
        if not endpoint_state.connected:
            return _decision(False, DataPlaneReason.WS_DISCONNECTED, False)
        if (
            generation != endpoint_state.generation
            or key not in endpoint_state.server_ids
        ):
            endpoint_state.state = SubscriptionState.RESUBSCRIBE_REQUIRED
            return _decision(False, DataPlaneReason.WS_RESUBSCRIBE_REQUIRED, False)
        previous = endpoint_state.last_slots.get(key)
        if previous is not None and context_slot < previous:
            return _decision(False, DataPlaneReason.OUT_OF_ORDER, False)
        endpoint_state.last_slots[key] = context_slot
        if (
            previous is not None
            and context_slot - previous > self.policy.websocket_max_slot_gap
        ):
            endpoint_state.state = SubscriptionState.GAP_DETECTED
            endpoint_state.gap_from, endpoint_state.gap_to = (
                previous + 1,
                context_slot - 1,
            )
            return _decision(True, DataPlaneReason.SLOT_GAP, True)
        if endpoint_state.state != SubscriptionState.GAP_DETECTED:
            endpoint_state.state = SubscriptionState.ACTIVE
        return _decision(True, DataPlaneReason.OK, False)

    def mark_backfill_complete(self, endpoint_id: str, *, through_slot: int) -> None:
        endpoint_state = self._state(endpoint_id)
        non_negative_int(through_slot, "through_slot")
        if endpoint_state.state != SubscriptionState.GAP_DETECTED:
            return
        if endpoint_state.gap_to is None or through_slot < endpoint_state.gap_to:
            raise DataPlaneError(DataPlaneReason.SLOT_GAP, "gap is not fully covered")
        endpoint_state.gap_from = endpoint_state.gap_to = None
        endpoint_state.state = (
            SubscriptionState.ACTIVE
            if set(endpoint_state.server_ids) == set(self.desired)
            else SubscriptionState.RESUBSCRIBE_REQUIRED
        )

    def on_disconnected(self, endpoint_id: str) -> None:
        endpoint_state = self._state(endpoint_id)
        endpoint_state.connected = False
        endpoint_state.server_ids.clear()
        endpoint_state.state = SubscriptionState.DISCONNECTED

    def next_backoff_ms(self, endpoint_id: str, attempt: int) -> int:
        non_empty(endpoint_id, "endpoint_id")
        non_negative_int(attempt, "attempt")
        raw = min(
            self.policy.websocket_backoff_cap_ms,
            self.policy.websocket_backoff_base_ms * (2 ** min(attempt, 20)),
        )
        jitter = (
            8_000
            + int.from_bytes(
                hashlib.sha256(f"{endpoint_id}:{attempt}".encode()).digest()[:2],
                "big",
            )
            % 4_001
        )
        return max(1, raw * jitter // 10_000)

    def snapshot(self, endpoint_id: str) -> WsEndpointSnapshot:
        endpoint_state = self._state(endpoint_id)
        return WsEndpointSnapshot(
            endpoint_id,
            endpoint_state.generation,
            endpoint_state.connected,
            endpoint_state.state,
            tuple(sorted(set(self.desired) - set(endpoint_state.server_ids))),
            tuple(sorted(endpoint_state.server_ids)),
            (
                max(endpoint_state.last_slots.values())
                if endpoint_state.last_slots
                else None
            ),
            endpoint_state.gap_from,
            endpoint_state.gap_to,
        )

    def readiness(self, *, now_monotonic_ms: int) -> ReadinessReport:
        non_negative_int(now_monotonic_ms, "now_monotonic_ms")
        reasons: list[str] = []
        ready: list[str] = []
        for endpoint_id in sorted(self.endpoints):
            endpoint_state = self.endpoints[endpoint_id]
            heartbeat_expired = (
                not endpoint_state.connected
                or endpoint_state.last_pong_ms is None
                or now_monotonic_ms - endpoint_state.last_pong_ms
                > self.policy.websocket_heartbeat_timeout_ms
            )
            if heartbeat_expired:
                reasons.append(
                    f"{endpoint_id}:{DataPlaneReason.WS_HEARTBEAT_EXPIRED.value}"
                )
            elif endpoint_state.state == SubscriptionState.ACTIVE:
                ready.append(endpoint_id)
            else:
                reasons.append(f"{endpoint_id}:{endpoint_state.state}")
        if not self.endpoints:
            reasons.append(DataPlaneReason.WS_DISCONNECTED.value)
        readiness_state = (
            ReadinessState.READY
            if ready and not reasons
            else ReadinessState.DEGRADED if ready else ReadinessState.NOT_READY
        )
        return ReadinessReport.build(
            readiness_state,
            reasons,
            {"ready_endpoints": tuple(ready), "endpoint_count": len(self.endpoints)},
        )

    def _state(self, endpoint_id: str) -> _State:
        non_empty(endpoint_id, "endpoint_id")
        if endpoint_id not in self.endpoints:
            raise DataPlaneError(DataPlaneReason.WS_DISCONNECTED, "unknown endpoint")
        return self.endpoints[endpoint_id]


def _decision(
    accepted: bool, reason: DataPlaneReason, backfill: bool
) -> WsNotificationDecision:
    evidence = canonical_hash(
        {"accepted": accepted, "reason": reason.value, "backfill": backfill}
    )
    return WsNotificationDecision(accepted, reason, backfill, evidence)
