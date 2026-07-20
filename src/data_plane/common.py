"""Shared PR-040 data-plane contracts and deterministic evidence helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Mapping

SCHEMA_VERSION = "pr040.data-plane-resilience.v1"


class CommitmentLevel(str, Enum):
    PROCESSED = "processed"
    CONFIRMED = "confirmed"
    FINALIZED = "finalized"

    @property
    def rank(self) -> int:
        return {
            CommitmentLevel.PROCESSED: 0,
            CommitmentLevel.CONFIRMED: 1,
            CommitmentLevel.FINALIZED: 2,
        }[self]


class DataPlaneReason(str, Enum):
    OK = "PR040_OK"
    NO_DATA = "PR040_NO_DATA"
    INVALID_INPUT = "PR040_INVALID_INPUT"
    LOW_COMMITMENT = "PR040_LOW_COMMITMENT"
    BELOW_MIN_CONTEXT_SLOT = "PR040_BELOW_MIN_CONTEXT_SLOT"
    STALE_OBSERVATION = "PR040_STALE_OBSERVATION"
    FUTURE_OBSERVATION = "PR040_FUTURE_OBSERVATION"
    OUT_OF_ORDER = "PR040_OUT_OF_ORDER"
    SLOT_GAP = "PR040_SLOT_GAP"
    RPC_GENESIS_MISMATCH = "PR040_RPC_GENESIS_MISMATCH"
    RPC_REQUEST_MISMATCH = "PR040_RPC_REQUEST_MISMATCH"
    RPC_SAME_SLOT_CONFLICT = "PR040_RPC_SAME_SLOT_CONFLICT"
    RPC_SLOT_DIVERGENCE = "PR040_RPC_SLOT_DIVERGENCE"
    RPC_INSUFFICIENT_EVIDENCE = "PR040_RPC_INSUFFICIENT_EVIDENCE"
    WS_DISCONNECTED = "PR040_WS_DISCONNECTED"
    WS_RESUBSCRIBE_REQUIRED = "PR040_WS_RESUBSCRIBE_REQUIRED"
    WS_HEARTBEAT_EXPIRED = "PR040_WS_HEARTBEAT_EXPIRED"
    WS_UNKNOWN_SUBSCRIPTION = "PR040_WS_UNKNOWN_SUBSCRIPTION"
    POLL_COOLDOWN = "PR040_POLL_COOLDOWN"
    POLL_CAPACITY_EXHAUSTED = "PR040_POLL_CAPACITY_EXHAUSTED"
    ORACLE_SOURCE_NOT_ALLOWED = "PR040_ORACLE_SOURCE_NOT_ALLOWED"
    ORACLE_NOT_TRADING = "PR040_ORACLE_NOT_TRADING"
    ORACLE_INVALID_PRICE = "PR040_ORACLE_INVALID_PRICE"
    ORACLE_CONFIDENCE_TOO_WIDE = "PR040_ORACLE_CONFIDENCE_TOO_WIDE"
    WEBHOOK_BODY_TOO_LARGE = "PR040_WEBHOOK_BODY_TOO_LARGE"
    WEBHOOK_AUTH_FAILED = "PR040_WEBHOOK_AUTH_FAILED"
    WEBHOOK_REPLAY = "PR040_WEBHOOK_REPLAY"
    WEBHOOK_TIMESTAMP_INVALID = "PR040_WEBHOOK_TIMESTAMP_INVALID"
    BACKPRESSURE = "PR040_BACKPRESSURE"
    DEGRADED = "PR040_DEGRADED"


class ReadinessState(str, Enum):
    READY = "ready"
    DEGRADED = "degraded"
    NOT_READY = "not_ready"


class DataPlaneError(ValueError):
    def __init__(
        self,
        reason: DataPlaneReason,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(f"{reason.value}: {message}")
        self.reason = reason
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class DataConsistencyPolicy:
    required_commitment: CommitmentLevel = CommitmentLevel.CONFIRMED
    max_observation_age_ms: int = 2_000
    max_future_clock_skew_ms: int = 1_000
    max_rpc_slot_delta: int = 2
    minimum_matching_rpc_sources: int = 2
    websocket_heartbeat_timeout_ms: int = 30_000
    websocket_max_slot_gap: int = 2
    websocket_backoff_base_ms: int = 250
    websocket_backoff_cap_ms: int = 30_000
    polling_min_interval_ms: int = 250
    polling_max_inflight: int = 4
    webhook_max_age_ms: int = 30_000
    webhook_nonce_ttl_ms: int = 120_000
    webhook_max_body_bytes: int = 1_048_576
    webhook_max_seen_deliveries: int = 10_000
    detector_max_inflight: int = 1_024

    def __post_init__(self) -> None:
        positive = (
            self.max_observation_age_ms,
            self.max_rpc_slot_delta,
            self.minimum_matching_rpc_sources,
            self.websocket_heartbeat_timeout_ms,
            self.websocket_max_slot_gap,
            self.websocket_backoff_base_ms,
            self.websocket_backoff_cap_ms,
            self.polling_min_interval_ms,
            self.polling_max_inflight,
            self.webhook_max_age_ms,
            self.webhook_nonce_ttl_ms,
            self.webhook_max_body_bytes,
            self.webhook_max_seen_deliveries,
            self.detector_max_inflight,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in positive
        ):
            raise ValueError("data-plane policy limits must be positive integers")
        if (
            isinstance(self.max_future_clock_skew_ms, bool)
            or not isinstance(self.max_future_clock_skew_ms, int)
            or self.max_future_clock_skew_ms < 0
        ):
            raise ValueError("max_future_clock_skew_ms must be a non-negative integer")
        if self.websocket_backoff_base_ms > self.websocket_backoff_cap_ms:
            raise ValueError("websocket backoff base must not exceed cap")


def canonical_hash(value: object) -> str:
    payload = json.dumps(
        json_safe(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def canonical_request_hash(method: str, params: object) -> str:
    non_empty(method, "method")
    return canonical_hash({"method": method, "params": json_safe(params)})


def canonical_payload_hash(payload: object) -> str:
    return canonical_hash(json_safe(payload))


def json_safe(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"value is not JSON-safe: {type(value).__name__}")


def time_reason(
    *,
    observed_wall_ms: int,
    observed_monotonic_ms: int,
    now_wall_ms: int,
    now_monotonic_ms: int,
    max_age_ms: int,
    max_future_skew_ms: int,
) -> DataPlaneReason | None:
    wall_age = now_wall_ms - observed_wall_ms
    monotonic_age = now_monotonic_ms - observed_monotonic_ms
    if wall_age < -max_future_skew_ms or monotonic_age < 0:
        return DataPlaneReason.FUTURE_OBSERVATION
    if wall_age > max_age_ms or monotonic_age > max_age_ms:
        return DataPlaneReason.STALE_OBSERVATION
    return None


def non_empty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def non_negative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def sha256_hex(value: object, name: str) -> str:
    checked = non_empty(value, name)
    if len(checked) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(checked, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a SHA-256 hex digest") from exc
    return checked.lower()
