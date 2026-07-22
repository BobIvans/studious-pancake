"""PR-135 provider-conformant webhook authentication and durable dedup.

This module is intentionally side-effect free except for its explicit SQLite
store.  It models the Helius webhook ingestion boundary without importing the
runtime webhook server, senders, RPC clients, or trading paths.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Sequence


class WebhookProvider(StrEnum):
    HELIUS = "helius"


class WebhookPayloadKind(StrEnum):
    RAW_TRANSACTION = "raw_transaction"
    ENHANCED_TRANSACTION = "enhanced_transaction"


class WebhookAuthDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class WebhookQueueDecision(StrEnum):
    ENQUEUED = "enqueued"
    DUPLICATE = "duplicate"


class WebhookGapDecision(StrEnum):
    CURRENT = "current"
    GAP_RECOVERY_REQUIRED = "gap_recovery_required"


class WebhookConfigDecision(StrEnum):
    MATCHED = "matched"
    DRIFTED = "drifted"


class WebhookSchemaError(ValueError):
    """Raised when a webhook payload lacks deterministic identity fields."""


@dataclass(frozen=True, slots=True)
class HeliusWebhookAuthConfig:
    """Expected Helius authHeader contract.

    Helius repeats the configured ``authHeader`` value in the HTTP
    ``Authorization`` header.  The value is a secret locator at configuration
    time; this object stores the resolved expected value only inside the
    verification boundary and never includes it in repr output.
    """

    expected_authorization: str
    secret_ref: str
    network: str
    webhook_type: WebhookPayloadKind

    def __post_init__(self) -> None:
        if not self.expected_authorization:
            raise ValueError("expected_authorization must be non-empty")
        if not self.secret_ref:
            raise ValueError("secret_ref must be non-empty")
        if not self.network:
            raise ValueError("network must be non-empty")

    def __repr__(self) -> str:
        return (
            "HeliusWebhookAuthConfig("
            "expected_authorization=<redacted>, "
            f"secret_ref={self.secret_ref!r}, "
            f"network={self.network!r}, "
            f"webhook_type={self.webhook_type.value!r})"
        )


@dataclass(frozen=True, slots=True)
class WebhookAuthResult:
    provider: WebhookProvider
    decision: WebhookAuthDecision
    redacted_auth_hash: str
    reason: str


@dataclass(frozen=True, slots=True)
class DurableWebhookIdentity:
    provider: WebhookProvider
    signature: str
    slot: int
    event_index: int
    payload_hash: str

    @property
    def key(self) -> str:
        return "|".join(
            (
                self.provider.value,
                self.signature,
                str(self.slot),
                str(self.event_index),
                self.payload_hash,
            )
        )


@dataclass(frozen=True, slots=True)
class WebhookEnvelope:
    identity: DurableWebhookIdentity
    payload_kind: WebhookPayloadKind
    payload_schema: str
    received_unix_ms: int
    failed_transaction: bool
    redacted_auth_hash: str
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class WebhookQueueResult:
    decision: WebhookQueueDecision
    status_code: int
    identity_key: str
    stored_sequence: int | None

    @property
    def should_process_async(self) -> bool:
        return self.decision is WebhookQueueDecision.ENQUEUED


@dataclass(frozen=True, slots=True)
class GapRecoveryCursor:
    last_seen_slot: int | None
    incoming_slot: int
    max_allowed_slot_gap: int

    def evaluate(self) -> WebhookGapDecision:
        if self.last_seen_slot is None:
            return WebhookGapDecision.CURRENT
        if self.incoming_slot <= self.last_seen_slot + self.max_allowed_slot_gap:
            return WebhookGapDecision.CURRENT
        return WebhookGapDecision.GAP_RECOVERY_REQUIRED


@dataclass(frozen=True, slots=True)
class ExpectedWebhookConfig:
    webhook_id: str
    network: str
    webhook_type: WebhookPayloadKind
    monitored_addresses_hash: str
    auth_header_secret_ref: str
    active: bool


@dataclass(frozen=True, slots=True)
class ObservedWebhookConfig:
    webhook_id: str
    network: str
    webhook_type: WebhookPayloadKind
    monitored_addresses_hash: str
    auth_header_secret_ref: str
    active: bool


@dataclass(frozen=True, slots=True)
class WebhookConfigDriftResult:
    decision: WebhookConfigDecision
    drift_fields: tuple[str, ...]


def stable_json_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def redacted_secret_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def verify_helius_authorization(
    headers: Mapping[str, str],
    config: HeliusWebhookAuthConfig,
) -> WebhookAuthResult:
    observed = _get_header(headers, "authorization")
    expected = config.expected_authorization
    accepted = observed is not None and hmac.compare_digest(observed, expected)
    if accepted:
        return WebhookAuthResult(
            provider=WebhookProvider.HELIUS,
            decision=WebhookAuthDecision.ACCEPTED,
            redacted_auth_hash=redacted_secret_hash(expected),
            reason="authorization_header_matches_configured_auth_header",
        )
    return WebhookAuthResult(
        provider=WebhookProvider.HELIUS,
        decision=WebhookAuthDecision.REJECTED,
        redacted_auth_hash=redacted_secret_hash(observed or ""),
        reason="authorization_header_mismatch",
    )


def _get_header(headers: Mapping[str, str], name: str) -> str | None:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return None


def extract_helius_identity(
    payload: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    event_index: int = 0,
) -> DurableWebhookIdentity:
    event = _event_at(payload, event_index)
    signature = _extract_signature(event)
    slot = _extract_slot(event)
    return DurableWebhookIdentity(
        provider=WebhookProvider.HELIUS,
        signature=signature,
        slot=slot,
        event_index=event_index,
        payload_hash=stable_json_hash(event),
    )


def build_helius_envelope(
    payload: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    payload_kind: WebhookPayloadKind,
    received_unix_ms: int,
    auth_result: WebhookAuthResult,
    event_index: int = 0,
) -> WebhookEnvelope:
    if auth_result.decision is not WebhookAuthDecision.ACCEPTED:
        raise PermissionError(auth_result.reason)
    event = _event_at(payload, event_index)
    identity = extract_helius_identity(payload, event_index=event_index)
    return WebhookEnvelope(
        identity=identity,
        payload_kind=payload_kind,
        payload_schema=_schema_name(payload_kind, event),
        received_unix_ms=received_unix_ms,
        failed_transaction=_is_failed_transaction(event),
        redacted_auth_hash=auth_result.redacted_auth_hash,
        payload=event,
    )


def _event_at(
    payload: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    event_index: int,
) -> Mapping[str, Any]:
    if event_index < 0:
        raise WebhookSchemaError("event_index must be non-negative")
    if isinstance(payload, Mapping):
        if event_index != 0:
            raise WebhookSchemaError("single webhook event only has index 0")
        return payload
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        try:
            event = payload[event_index]
        except IndexError as exc:
            raise WebhookSchemaError("event_index is outside payload array") from exc
        if not isinstance(event, Mapping):
            raise WebhookSchemaError("webhook array item must be an object")
        return event
    raise WebhookSchemaError("webhook payload must be an object or array")


def _extract_signature(event: Mapping[str, Any]) -> str:
    value = event.get("signature")
    if isinstance(value, str) and value:
        return value
    signatures = event.get("signatures")
    if (
        isinstance(signatures, Sequence)
        and not isinstance(signatures, (str, bytes))
        and signatures
        and isinstance(signatures[0], str)
        and signatures[0]
    ):
        return signatures[0]
    transaction = event.get("transaction")
    if isinstance(transaction, Mapping):
        nested = transaction.get("signatures")
        if (
            isinstance(nested, Sequence)
            and not isinstance(nested, (str, bytes))
            and nested
            and isinstance(nested[0], str)
            and nested[0]
        ):
            return nested[0]
    raise WebhookSchemaError("webhook event must include a transaction signature")


def _extract_slot(event: Mapping[str, Any]) -> int:
    value = event.get("slot")
    if value is None:
        meta = event.get("meta")
        if isinstance(meta, Mapping):
            value = meta.get("slot")
    try:
        slot = int(value)
    except (TypeError, ValueError) as exc:
        raise WebhookSchemaError("webhook event must include an integer slot") from exc
    if slot < 0:
        raise WebhookSchemaError("webhook slot must be non-negative")
    return slot


def _is_failed_transaction(event: Mapping[str, Any]) -> bool:
    if event.get("transactionError") is not None:
        return True
    meta = event.get("meta")
    if isinstance(meta, Mapping) and meta.get("err") is not None:
        return True
    return False


def _schema_name(payload_kind: WebhookPayloadKind, event: Mapping[str, Any]) -> str:
    if payload_kind is WebhookPayloadKind.ENHANCED_TRANSACTION:
        if "type" not in event:
            raise WebhookSchemaError("enhanced Helius event must include type")
        return "helius_enhanced_transaction"
    if "transaction" not in event and "signatures" not in event:
        raise WebhookSchemaError("raw Helius event must include transaction/signatures")
    return "helius_raw_transaction"


class DurableWebhookStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.connection = sqlite3.connect(str(self.path))
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.migrate()

    def migrate(self) -> None:
        with self.connection:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS webhook_events (
                    sequence_no INTEGER PRIMARY KEY AUTOINCREMENT,
                    identity_key TEXT NOT NULL UNIQUE,
                    provider TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    slot INTEGER NOT NULL,
                    event_index INTEGER NOT NULL,
                    payload_hash TEXT NOT NULL,
                    payload_kind TEXT NOT NULL,
                    payload_schema TEXT NOT NULL,
                    received_unix_ms INTEGER NOT NULL,
                    failed_transaction INTEGER NOT NULL,
                    redacted_auth_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    processing_state TEXT NOT NULL DEFAULT 'queued'
                )
                """
            )
            self.connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_webhook_events_slot
                ON webhook_events(slot, sequence_no)
                """
            )

    def enqueue(self, envelope: WebhookEnvelope) -> WebhookQueueResult:
        payload_json = json.dumps(
            envelope.payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        try:
            with self.connection:
                cursor = self.connection.execute(
                    """
                    INSERT INTO webhook_events (
                        identity_key,
                        provider,
                        signature,
                        slot,
                        event_index,
                        payload_hash,
                        payload_kind,
                        payload_schema,
                        received_unix_ms,
                        failed_transaction,
                        redacted_auth_hash,
                        payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        envelope.identity.key,
                        envelope.identity.provider.value,
                        envelope.identity.signature,
                        envelope.identity.slot,
                        envelope.identity.event_index,
                        envelope.identity.payload_hash,
                        envelope.payload_kind.value,
                        envelope.payload_schema,
                        envelope.received_unix_ms,
                        int(envelope.failed_transaction),
                        envelope.redacted_auth_hash,
                        payload_json,
                    ),
                )
        except sqlite3.IntegrityError:
            return WebhookQueueResult(
                decision=WebhookQueueDecision.DUPLICATE,
                status_code=200,
                identity_key=envelope.identity.key,
                stored_sequence=None,
            )
        return WebhookQueueResult(
            decision=WebhookQueueDecision.ENQUEUED,
            status_code=200,
            identity_key=envelope.identity.key,
            stored_sequence=int(cursor.lastrowid),
        )

    def count(self) -> int:
        row = self.connection.execute("SELECT COUNT(*) FROM webhook_events").fetchone()
        return int(row[0])

    def last_seen_slot(self) -> int | None:
        row = self.connection.execute("SELECT MAX(slot) FROM webhook_events").fetchone()
        if row is None or row[0] is None:
            return None
        return int(row[0])

    def close(self) -> None:
        self.connection.close()


def evaluate_gap_recovery(
    store: DurableWebhookStore,
    incoming_slot: int,
    *,
    max_allowed_slot_gap: int,
) -> WebhookGapDecision:
    cursor = GapRecoveryCursor(
        last_seen_slot=store.last_seen_slot(),
        incoming_slot=incoming_slot,
        max_allowed_slot_gap=max_allowed_slot_gap,
    )
    return cursor.evaluate()


def compare_webhook_config(
    expected: ExpectedWebhookConfig,
    observed: ObservedWebhookConfig,
) -> WebhookConfigDriftResult:
    drift_fields: list[str] = []
    for field in (
        "webhook_id",
        "network",
        "webhook_type",
        "monitored_addresses_hash",
        "auth_header_secret_ref",
        "active",
    ):
        if getattr(expected, field) != getattr(observed, field):
            drift_fields.append(field)
    if drift_fields:
        return WebhookConfigDriftResult(
            decision=WebhookConfigDecision.DRIFTED,
            drift_fields=tuple(drift_fields),
        )
    return WebhookConfigDriftResult(
        decision=WebhookConfigDecision.MATCHED,
        drift_fields=(),
    )


__all__ = [
    "DurableWebhookIdentity",
    "DurableWebhookStore",
    "ExpectedWebhookConfig",
    "GapRecoveryCursor",
    "HeliusWebhookAuthConfig",
    "ObservedWebhookConfig",
    "WebhookAuthDecision",
    "WebhookAuthResult",
    "WebhookConfigDecision",
    "WebhookConfigDriftResult",
    "WebhookGapDecision",
    "WebhookPayloadKind",
    "WebhookProvider",
    "WebhookQueueDecision",
    "WebhookQueueResult",
    "WebhookSchemaError",
    "build_helius_envelope",
    "compare_webhook_config",
    "evaluate_gap_recovery",
    "extract_helius_identity",
    "redacted_secret_hash",
    "stable_json_hash",
    "verify_helius_authorization",
]
