"""PR-196 verification and deterministic projection rebuild."""
from __future__ import annotations

import json
import sqlite3
from typing import Callable, Mapping, Protocol

from ..events import EventEnvelope, EventType, Outcome
from .model import (
    AuthoritativeTruthBundle,
    CanonicalOutcome,
    PlaneWatermark,
    ReconciliationResult,
    TerminalTruthState,
    VerifiedTerminalProjection,
    hash_json,
    placeholder,
    valid_sha,
)
from .store import CrossPlaneTruthStore

_TERMINAL_TYPES = frozenset(
    {
        EventType.attempt_terminal,
        EventType.balance_reconciled,
        EventType.reconciliation_completed,
        EventType.evidence_corrected,
    }
)


class ObservabilityStorePort(Protocol):
    db: sqlite3.Connection


BundleProvider = Callable[[EventEnvelope], AuthoritativeTruthBundle | None]


class CrossPlaneTerminalReconciler:
    def __init__(self, truth_store: CrossPlaneTruthStore) -> None:
        self.truth_store = truth_store

    def reconcile(
        self,
        event: EventEnvelope,
        bundle: AuthoritativeTruthBundle | None,
    ) -> ReconciliationResult:
        projection, watermarks = verify_event(event, bundle)
        return self.truth_store.put(projection, watermarks)

    def rebuild(
        self,
        observability: ObservabilityStorePort,
        bundle_provider: BundleProvider,
    ) -> str:
        self.truth_store.clear_projection()
        rows = observability.db.execute(
            "SELECT payload_json FROM event_log "
            "ORDER BY aggregate_id,sequence_no,event_id"
        ).fetchall()
        for row in rows:
            decoded = json.loads(str(row[0]))
            if not isinstance(decoded, dict):
                raise ValueError("PR196_EVENT_PAYLOAD_NOT_OBJECT")
            event = event_from_payload(decoded)
            if event.event_type in _TERMINAL_TYPES:
                self.reconcile(event, bundle_provider(event))
        return self.truth_store.projection_checksum()


def verify_event(
    event: EventEnvelope,
    bundle: AuthoritativeTruthBundle | None,
) -> tuple[VerifiedTerminalProjection, tuple[PlaneWatermark, ...]]:
    reasons: list[str] = []
    if event.event_type not in _TERMINAL_TYPES:
        return (
            projection_for(
                event,
                TerminalTruthState.NON_TERMINAL,
                None,
                ("PR196_NON_TERMINAL_EVENT",),
                None,
            ),
            (),
        )
    if event.attempt_id is None:
        reasons.append("PR196_ATTEMPT_ID_MISSING")
    if event.attempt_generation < 0:
        reasons.append("PR196_ATTEMPT_GENERATION_INVALID")
    for value, code in (
        (event.producer_code_version, "PR196_PRODUCER_PROVENANCE_MISSING"),
        (event.config_checksum, "PR196_CONFIG_PROVENANCE_MISSING"),
        (event.contract_fixture_version, "PR196_CONTRACT_PROVENANCE_MISSING"),
    ):
        if placeholder(value):
            reasons.append(code)
    if not valid_sha(event.plan_hash):
        reasons.append("PR196_PLAN_HASH_INVALID")
    if bundle is None:
        reasons.append("PR196_AUTHORITATIVE_BUNDLE_MISSING")
        return (
            projection_for(
                event,
                TerminalTruthState.AMBIGUOUS,
                None,
                tuple(reasons),
                None,
            ),
            (),
        )

    lifecycle = bundle.lifecycle
    if event.attempt_id != lifecycle.attempt_id:
        reasons.append("PR196_LIFECYCLE_ATTEMPT_MISMATCH")
    if event.attempt_generation != lifecycle.attempt_generation:
        reasons.append("PR196_LIFECYCLE_GENERATION_MISMATCH")
    if event.logical_opportunity_id != lifecycle.logical_opportunity_id:
        reasons.append("PR196_LIFECYCLE_OPPORTUNITY_MISMATCH")
    if event.plan_hash != lifecycle.plan_hash:
        reasons.append("PR196_LIFECYCLE_PLAN_MISMATCH")
    validate_authority_attributes(event, bundle, reasons)

    expected_outcome = (
        CanonicalOutcome.SUCCESS
        if event.outcome is Outcome.succeeded
        else CanonicalOutcome.FAILURE
        if event.outcome is Outcome.failed
        else None
    )
    if expected_outcome is None:
        reasons.append("PR196_TERMINAL_OUTCOME_AMBIGUOUS")
    elif expected_outcome is not lifecycle.outcome:
        reasons.append("PR196_LIFECYCLE_OUTCOME_MISMATCH")

    settlement = bundle.settlement
    ledger = bundle.ledger
    if lifecycle.outcome is CanonicalOutcome.SUCCESS:
        if settlement is None:
            reasons.append("PR196_FINALIZED_SETTLEMENT_MISSING")
        if ledger is None:
            reasons.append("PR196_LEDGER_POSTING_MISSING")
    if settlement is not None:
        if event.message_hash != settlement.message_hash:
            reasons.append("PR196_MESSAGE_HASH_MISMATCH")
        if event.tx_signature and event.tx_signature != settlement.finalized_signature:
            reasons.append("PR196_SIGNATURE_MISMATCH")
        if (
            settlement.attempt_id != lifecycle.attempt_id
            or settlement.attempt_generation != lifecycle.attempt_generation
        ):
            reasons.append("PR196_SETTLEMENT_ATTEMPT_MISMATCH")
        if settlement.outcome is not lifecycle.outcome:
            reasons.append("PR196_SETTLEMENT_OUTCOME_MISMATCH")
    if ledger is not None:
        if (
            ledger.attempt_id != lifecycle.attempt_id
            or ledger.attempt_generation != lifecycle.attempt_generation
        ):
            reasons.append("PR196_LEDGER_ATTEMPT_MISMATCH")
        if ledger.outcome is not lifecycle.outcome:
            reasons.append("PR196_LEDGER_OUTCOME_MISMATCH")
    if settlement is not None and ledger is not None:
        if (
            settlement.settlement_evidence_digest
            != ledger.settlement_evidence_digest
        ):
            reasons.append("PR196_SETTLEMENT_LEDGER_DIGEST_MISMATCH")
        if settlement.asset_mint != ledger.asset_mint:
            reasons.append("PR196_ASSET_MISMATCH")
        if settlement.amount_base_units != ledger.amount_base_units:
            reasons.append("PR196_AMOUNT_MISMATCH")

    validate_realized_pnl(event, bundle, reasons)
    state = (
        TerminalTruthState.TERMINAL_SUCCESS
        if not reasons and lifecycle.outcome is CanonicalOutcome.SUCCESS
        else TerminalTruthState.TERMINAL_FAILURE
        if not reasons and lifecycle.outcome is CanonicalOutcome.FAILURE
        else TerminalTruthState.AMBIGUOUS
    )
    watermarks = [lifecycle.watermark]
    if settlement is not None:
        watermarks.append(settlement.watermark)
    if ledger is not None:
        watermarks.append(ledger.watermark)
    outcome = lifecycle.outcome if not reasons else None
    return (
        projection_for(event, state, outcome, tuple(reasons), bundle),
        tuple(watermarks),
    )


def validate_authority_attributes(
    event: EventEnvelope,
    bundle: AuthoritativeTruthBundle,
    reasons: list[str],
) -> None:
    authority = event.attributes.get("terminal_authority")
    if not isinstance(authority, Mapping):
        reasons.append("PR196_TERMINAL_AUTHORITY_MISSING")
        return
    lifecycle = bundle.lifecycle
    expected: dict[str, object] = {
        "lifecycle_event_id": lifecycle.lifecycle_event_id,
        "lifecycle_event_hash": lifecycle.lifecycle_event_hash,
        "reservation_state": lifecycle.reservation_state.value,
        "release_hash": bundle.release_policy.release_hash,
        "policy_bundle_hash": bundle.release_policy.policy_bundle_hash,
    }
    if bundle.settlement is not None:
        expected.update(
            {
                "settlement_evidence_digest": (
                    bundle.settlement.settlement_evidence_digest
                ),
                "asset_mint": bundle.settlement.asset_mint,
                "amount_base_units": bundle.settlement.amount_base_units,
                "finalized_signature": bundle.settlement.finalized_signature,
                "finalized_slot": bundle.settlement.finalized_slot,
            }
        )
    if bundle.ledger is not None:
        expected.update(
            {
                "ledger_posting_id": bundle.ledger.posting_id,
                "ledger_posting_hash": bundle.ledger.posting_hash,
            }
        )
    for key, value in expected.items():
        if authority.get(key) != value:
            reasons.append(
                f"PR196_TERMINAL_AUTHORITY_{key.upper()}_MISMATCH"
            )


def validate_realized_pnl(
    event: EventEnvelope,
    bundle: AuthoritativeTruthBundle,
    reasons: list[str],
) -> None:
    if bundle.lifecycle.outcome is not CanonicalOutcome.SUCCESS:
        return
    settlement = bundle.settlement
    ledger = bundle.ledger
    realized = event.attributes.get("realized_pnl")
    if not isinstance(realized, Mapping):
        reasons.append("PR196_REALIZED_PNL_MISSING")
    elif settlement is not None and ledger is not None:
        required = {
            "asset_mint": settlement.asset_mint,
            "amount_base_units": settlement.amount_base_units,
            "settlement_evidence_digest": settlement.settlement_evidence_digest,
            "ledger_posting_id": ledger.posting_id,
            "finalized_signature": settlement.finalized_signature,
            "finalized_slot": settlement.finalized_slot,
        }
        for key, expected in required.items():
            if realized.get(key) != expected:
                reasons.append(
                    f"PR196_REALIZED_PNL_{key.upper()}_MISMATCH"
                )
    if (
        event.evidence_ref is None
        or settlement is None
        or event.evidence_ref.digest != settlement.settlement_evidence_digest
    ):
        reasons.append("PR196_EVIDENCE_REFERENCE_MISMATCH")


def projection_for(
    event: EventEnvelope,
    state: TerminalTruthState,
    outcome: CanonicalOutcome | None,
    reasons: tuple[str, ...],
    bundle: AuthoritativeTruthBundle | None,
) -> VerifiedTerminalProjection:
    lifecycle = bundle.lifecycle if bundle else None
    settlement = bundle.settlement if bundle else None
    ledger = bundle.ledger if bundle else None
    release = bundle.release_policy if bundle else None

    attempt_id = event.attempt_id or "missing-attempt"
    message_hash = settlement.message_hash if settlement else event.message_hash
    lifecycle_event_id = lifecycle.lifecycle_event_id if lifecycle else None
    settlement_digest = (
        settlement.settlement_evidence_digest if settlement else None
    )
    ledger_posting_id = ledger.posting_id if ledger else None
    release_hash = release.release_hash if release else None
    policy_bundle_hash = release.policy_bundle_hash if release else None
    asset_mint = settlement.asset_mint if settlement else None
    amount_base_units = settlement.amount_base_units if settlement else None
    finalized_signature = settlement.finalized_signature if settlement else None
    finalized_slot = settlement.finalized_slot if settlement else None
    release_ready = state in {
        TerminalTruthState.TERMINAL_SUCCESS,
        TerminalTruthState.TERMINAL_FAILURE,
    }

    payload: dict[str, object] = {
        "schema": "pr196.cross-plane-terminal-truth.v1",
        "attempt_id": attempt_id,
        "attempt_generation": event.attempt_generation,
        "logical_opportunity_id": event.logical_opportunity_id,
        "state": state.value,
        "outcome": outcome.value if outcome else None,
        "plan_hash": event.plan_hash,
        "message_hash": message_hash,
        "lifecycle_event_id": lifecycle_event_id,
        "settlement_evidence_digest": settlement_digest,
        "ledger_posting_id": ledger_posting_id,
        "release_hash": release_hash,
        "policy_bundle_hash": policy_bundle_hash,
        "asset_mint": asset_mint,
        "amount_base_units": amount_base_units,
        "finalized_signature": finalized_signature,
        "finalized_slot": finalized_slot,
        "source_event_id": event.event_id,
        "source_sequence_no": event.sequence_no,
        "reason_codes": list(reasons),
        "release_ready": release_ready,
    }
    return VerifiedTerminalProjection(
        attempt_id=attempt_id,
        attempt_generation=event.attempt_generation,
        logical_opportunity_id=event.logical_opportunity_id,
        state=state,
        outcome=outcome,
        plan_hash=event.plan_hash,
        message_hash=message_hash,
        lifecycle_event_id=lifecycle_event_id,
        settlement_evidence_digest=settlement_digest,
        ledger_posting_id=ledger_posting_id,
        release_hash=release_hash,
        policy_bundle_hash=policy_bundle_hash,
        asset_mint=asset_mint,
        amount_base_units=amount_base_units,
        finalized_signature=finalized_signature,
        finalized_slot=finalized_slot,
        source_event_id=event.event_id,
        source_sequence_no=event.sequence_no,
        reason_codes=reasons,
        projection_hash=hash_json(payload),
        release_ready=release_ready,
    )


def _required_value(payload: Mapping[str, object], key: str) -> object:
    if key not in payload:
        raise ValueError(f"PR196_EVENT_PAYLOAD_FIELD_MISSING:{key}")
    return payload[key]


def _required_str(payload: Mapping[str, object], key: str) -> str:
    value = _required_value(payload, key)
    if not isinstance(value, str):
        raise ValueError(f"PR196_EVENT_PAYLOAD_FIELD_NOT_STRING:{key}")
    return value


def _required_int(payload: Mapping[str, object], key: str) -> int:
    value = _required_value(payload, key)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"PR196_EVENT_PAYLOAD_FIELD_NOT_INTEGER:{key}")
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(
            f"PR196_EVENT_PAYLOAD_FIELD_NOT_INTEGER:{key}"
        ) from exc


def _string_value(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"PR196_EVENT_PAYLOAD_FIELD_NOT_STRING:{field_name}")
    return value


def _optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"PR196_EVENT_PAYLOAD_FIELD_NOT_STRING:{field_name}")
    return value


def _attributes_from_payload(payload: Mapping[str, object]) -> dict[str, object]:
    value = payload.get("attributes", {})
    if not isinstance(value, Mapping):
        raise ValueError("PR196_EVENT_ATTRIBUTES_NOT_OBJECT")
    return {str(key): item for key, item in value.items()}


def event_from_payload(payload: Mapping[str, object]) -> EventEnvelope:
    from ..events import Environment, EvidenceRef, Severity
    from ..reasons import ReasonCode

    reason_raw = payload.get("reason_code")
    evidence_raw = payload.get("evidence_ref")
    evidence_ref: EvidenceRef | None = None
    if evidence_raw is not None:
        if not isinstance(evidence_raw, Mapping):
            raise ValueError("PR196_EVIDENCE_REFERENCE_NOT_OBJECT")
        evidence_ref = EvidenceRef(
            digest=_required_str(evidence_raw, "digest"),
            size_bytes=_required_int(evidence_raw, "size_bytes"),
            classification=_required_str(evidence_raw, "classification"),
            uri=_optional_str(evidence_raw.get("uri"), "evidence_ref.uri"),
        )

    return EventEnvelope(
        event_id=_required_str(payload, "event_id"),
        schema_version=_required_int(payload, "schema_version"),
        occurred_at_utc_ns=_required_int(payload, "occurred_at_utc_ns"),
        monotonic_ns=_required_int(payload, "monotonic_ns"),
        runtime_id=_required_str(payload, "runtime_id"),
        environment=Environment(_required_str(payload, "environment")),
        trace_id=_required_str(payload, "trace_id"),
        logical_opportunity_id=_required_str(payload, "logical_opportunity_id"),
        plan_hash=_required_str(payload, "plan_hash"),
        attempt_generation=_required_int(payload, "attempt_generation"),
        attempt_id=_optional_str(payload.get("attempt_id"), "attempt_id"),
        message_hash=_optional_str(payload.get("message_hash"), "message_hash"),
        tx_signature=_optional_str(payload.get("tx_signature"), "tx_signature"),
        jito_bundle_id=_optional_str(
            payload.get("jito_bundle_id"), "jito_bundle_id"
        ),
        event_type=EventType(_required_str(payload, "event_type")),
        aggregate_id=_required_str(payload, "aggregate_id"),
        sequence_no=_required_int(payload, "sequence_no"),
        stage=_required_str(payload, "stage"),
        outcome=Outcome(_required_str(payload, "outcome")),
        reason_code=(
            ReasonCode(_string_value(reason_raw, "reason_code"))
            if reason_raw is not None
            else None
        ),
        severity=Severity(_required_str(payload, "severity")),
        correlation_id=_optional_str(
            payload.get("correlation_id"), "correlation_id"
        ),
        provider_id=_optional_str(payload.get("provider_id"), "provider_id"),
        venue_id=_optional_str(payload.get("venue_id"), "venue_id"),
        attributes=_attributes_from_payload(payload),
        evidence_ref=evidence_ref,
        producer_code_version=str(
            payload.get("producer_code_version", "unknown")
        ),
        config_checksum=str(payload.get("config_checksum", "unknown")),
        contract_fixture_version=str(
            payload.get("contract_fixture_version", "unknown")
        ),
        idempotency_key=str(payload.get("idempotency_key", "")),
    )
