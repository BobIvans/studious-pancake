"""PR-040 fail-closed RPC, WebSocket, oracle and webhook evidence boundary."""

from .aggregate import DataPlaneReadinessAggregator
from .common import (
    SCHEMA_VERSION,
    CommitmentLevel,
    DataConsistencyPolicy,
    DataPlaneError,
    DataPlaneReason,
    ReadinessState,
    canonical_payload_hash,
    canonical_request_hash,
)
from .guards import (
    AuthenticatedWebhookGuard,
    DetectorBackpressureGate,
    DetectorPermit,
    HmacSha256Verifier,
    PollPermit,
    PollingFallbackController,
    WebhookAdmission,
)
from .oracle import (
    OracleConsistencyGate,
    OracleDecision,
    OraclePolicy,
    OracleSample,
    OracleStatus,
)
from .readiness import ReadinessReport
from .rpc import RpcConsistencyDecision, RpcConsistencyGate, RpcSample
from .websocket import (
    SubscriptionSpec,
    SubscriptionState,
    WebSocketSubscriptionSupervisor,
    WsEndpointSnapshot,
    WsNotificationDecision,
)

__all__ = [
    "SCHEMA_VERSION",
    "AuthenticatedWebhookGuard",
    "CommitmentLevel",
    "DataConsistencyPolicy",
    "DataPlaneError",
    "DataPlaneReadinessAggregator",
    "DataPlaneReason",
    "DetectorBackpressureGate",
    "DetectorPermit",
    "HmacSha256Verifier",
    "OracleConsistencyGate",
    "OracleDecision",
    "OraclePolicy",
    "OracleSample",
    "OracleStatus",
    "PollPermit",
    "PollingFallbackController",
    "ReadinessReport",
    "ReadinessState",
    "RpcConsistencyDecision",
    "RpcConsistencyGate",
    "RpcSample",
    "SubscriptionSpec",
    "SubscriptionState",
    "WebSocketSubscriptionSupervisor",
    "WebhookAdmission",
    "WsEndpointSnapshot",
    "WsNotificationDecision",
    "canonical_payload_hash",
    "canonical_request_hash",
]
