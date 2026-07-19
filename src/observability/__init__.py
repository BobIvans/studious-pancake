"""PR-017 append-only observability API."""
from .events import EventEnvelope, EventType, Environment, Outcome, Severity, EvidenceRef, PnL, make_event
from .reasons import ReasonCode, REASON_REGISTRY, classify_exception
from .store import ObservabilityStore, ObservabilityError

__all__ = [
    "EventEnvelope", "EventType", "Environment", "Outcome", "Severity", "EvidenceRef", "PnL", "make_event",
    "ReasonCode", "REASON_REGISTRY", "classify_exception", "ObservabilityStore", "ObservabilityError",
]
