"""PR-017/PR-042 append-only observability and health API."""

from .authoritative_store_pr195 import AuthoritativeObservabilityStore
from .events import (
    Environment,
    EventEnvelope,
    EventType,
    EvidenceRef,
    Outcome,
    PnL,
    Severity,
    make_event,
)
from .health import (
    DependencyState,
    DependencyStatus,
    RuntimeHttpConfig,
    RuntimeStatusHttpServer,
    build_health_payload,
    build_metrics_text,
    build_readiness_payload,
    build_status_payload,
    check_http_health,
)
from .reasons import REASON_REGISTRY, ReasonCode, classify_exception
from .store import ObservabilityError, ObservabilityStore

__all__ = [
    "AuthoritativeObservabilityStore",
    "DependencyState",
    "DependencyStatus",
    "Environment",
    "EventEnvelope",
    "EventType",
    "EvidenceRef",
    "Outcome",
    "PnL",
    "REASON_REGISTRY",
    "ReasonCode",
    "RuntimeHttpConfig",
    "RuntimeStatusHttpServer",
    "Severity",
    "ObservabilityError",
    "ObservabilityStore",
    "build_health_payload",
    "build_metrics_text",
    "build_readiness_payload",
    "build_status_payload",
    "check_http_health",
    "classify_exception",
    "make_event",
]
