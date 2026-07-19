from __future__ import annotations
import hashlib, json, time, uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any
from .redaction import sanitized_with_stats
from .reasons import ReasonCode, REASON_REGISTRY

SCHEMA_VERSION = 1
class Environment(str, Enum): test="test"; shadow="shadow"; paper="paper"
class Outcome(str, Enum): observed="observed"; accepted="accepted"; rejected="rejected"; ambiguous="ambiguous"; succeeded="succeeded"; failed="failed"
class Severity(str, Enum): debug="debug"; info="info"; warning="warning"; error="error"; critical="critical"
class EventType(str, Enum):
    opportunity_detected="opportunity_detected"; quote_requested="quote_requested"; quote_received="quote_received"; quote_rejected="quote_rejected"; route_planned="route_planned"; feasibility_rejected="feasibility_rejected"; transaction_built="transaction_built"; simulation_started="simulation_started"; simulation_completed="simulation_completed"; simulation_rejected="simulation_rejected"; submission_attempted="submission_attempted"; submission_accepted="submission_accepted"; bundle_landed="bundle_landed"; bundle_rejected="bundle_rejected"; bundle_expired="bundle_expired"; transaction_reverted="transaction_reverted"; balance_reconciled="balance_reconciled"; attempt_terminal="attempt_terminal"; provider_health_changed="provider_health_changed"; quota_window_updated="quota_window_updated"; observability_degraded="observability_degraded"; evidence_corrected="evidence_corrected"; reconciliation_completed="reconciliation_completed"

@dataclass(frozen=True)
class EvidenceRef:
    digest: str; size_bytes: int; classification: str; uri: str | None = None
@dataclass(frozen=True)
class PnL:
    kind: str; amount_base_units: int; mint: str; evidence_digest: str | None = None
@dataclass(frozen=True)
class EventEnvelope:
    event_id: str; schema_version: int; occurred_at_utc_ns: int; monotonic_ns: int; runtime_id: str; environment: Environment
    trace_id: str; logical_opportunity_id: str; plan_hash: str; attempt_generation: int; attempt_id: str | None; message_hash: str | None
    tx_signature: str | None; jito_bundle_id: str | None; event_type: EventType; aggregate_id: str; sequence_no: int; stage: str; outcome: Outcome
    reason_code: ReasonCode | None; severity: Severity; correlation_id: str | None; provider_id: str | None; venue_id: str | None
    attributes: dict[str, Any] = field(default_factory=dict); evidence_ref: EvidenceRef | None = None; producer_code_version: str = "unknown"; config_checksum: str = "unknown"; contract_fixture_version: str = "unknown"; idempotency_key: str = ""
    def __post_init__(self):
        if self.environment not in Environment: raise ValueError("environment must be explicit test/shadow/paper")
        if self.event_type.value in {"submitted","confirmed"}: raise ValueError("fictional paper/shadow event")
        if self.sequence_no < 0: raise ValueError("sequence_no must be non-negative")
        if self.reason_code and self.reason_code not in REASON_REGISTRY: raise ValueError("unknown reason")
        for pnl_key in ("theoretical_pnl","quoted_pnl","simulated_pnl","realized_pnl"):
            if pnl_key in self.attributes and not isinstance(self.attributes[pnl_key], dict): raise ValueError("PnL must be structured")
        if "realized_pnl" in self.attributes and self.event_type not in {EventType.balance_reconciled, EventType.reconciliation_completed, EventType.attempt_terminal}: raise ValueError("realized_pnl requires reconciliation event")
    def redacted_payload(self) -> tuple[dict[str, Any], int]:
        data = asdict(self); data["environment"] = self.environment.value; data["event_type"] = self.event_type.value; data["outcome"] = self.outcome.value; data["severity"] = self.severity.value; data["reason_code"] = self.reason_code.value if self.reason_code else None
        return sanitized_with_stats(data)
    def payload_digest(self) -> str:
        payload,_ = self.redacted_payload(); return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",",":"), ensure_ascii=False).encode()).hexdigest()

def make_event(*, event_type: EventType, logical_opportunity_id: str, plan_hash: str, sequence_no: int, environment: Environment = Environment.test, aggregate_id: str | None = None, trace_id: str | None = None, attempt_generation: int = 0, stage: str | None = None, outcome: Outcome = Outcome.observed, reason_code: ReasonCode | None = None, severity: Severity = Severity.info, attributes: dict[str,Any] | None = None, critical: bool = False, **kwargs: Any) -> EventEnvelope:
    mono = time.monotonic_ns(); wall = time.time_ns(); agg = aggregate_id or f"opp:{logical_opportunity_id}"
    idem = kwargs.pop("idempotency_key", f"{agg}:{sequence_no}:{event_type.value}")
    return EventEnvelope(event_id=kwargs.pop("event_id", str(uuid.uuid4())), schema_version=SCHEMA_VERSION, occurred_at_utc_ns=wall, monotonic_ns=mono, runtime_id=kwargs.pop("runtime_id", "test-runtime"), environment=environment, trace_id=trace_id or logical_opportunity_id, logical_opportunity_id=logical_opportunity_id, plan_hash=plan_hash, attempt_generation=attempt_generation, attempt_id=kwargs.pop("attempt_id", None), message_hash=kwargs.pop("message_hash", None), tx_signature=kwargs.pop("tx_signature", None), jito_bundle_id=kwargs.pop("jito_bundle_id", None), event_type=event_type, aggregate_id=agg, sequence_no=sequence_no, stage=stage or event_type.value, outcome=outcome, reason_code=reason_code, severity=severity, correlation_id=kwargs.pop("correlation_id", None), provider_id=kwargs.pop("provider_id", None), venue_id=kwargs.pop("venue_id", None), attributes={**(attributes or {}), "critical": critical}, evidence_ref=kwargs.pop("evidence_ref", None), producer_code_version=kwargs.pop("producer_code_version", "unknown"), config_checksum=kwargs.pop("config_checksum", "unknown"), contract_fixture_version=kwargs.pop("contract_fixture_version", "unknown"), idempotency_key=idem)
