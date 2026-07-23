"""PR-195 durable webhook intake boundary.

This module is deliberately sender-free. It provides the offline durable-before-ACK
inbox semantics required before a webhook listener can be considered safe: batch
validation before receipt, one durable transaction for accepted events, immutable
chain identity separated from payload hashes, retry/DLQ state, and claim recovery.

It performs no network access, signing, transaction construction, or live trading.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

PR195_DURABLE_WEBHOOK_SCHEMA = "pr195.durable-webhook-intake.v1"


class WebhookIntakeError(RuntimeError):
    """Base error for durable webhook intake violations."""


class WebhookSchemaError(WebhookIntakeError):
    """Raised when a provider payload is rejected before durable receipt."""


class WebhookClaimError(WebhookIntakeError):
    """Raised when claim/ack/nack ownership is stale or missing."""


@dataclass(frozen=True, slots=True)
class WebhookEventIdentity:
    provider: str
    webhook_id: str
    slot: int
    event_index: int
    signature: str
    event_type: str

    @property
    def key(self) -> str:
        return _hash_json(
            {
                "event_index": self.event_index,
                "event_type": self.event_type,
                "provider": self.provider,
                "signature": self.signature,
                "slot": self.slot,
                "webhook_id": self.webhook_id,
            }
        )


@dataclass(frozen=True, slots=True)
class WebhookReceipt:
    schema_version: str
    batch_id: str
    events_committed: int
    duplicates: int
    conflicts_quarantined: int
    ack_allowed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "batch_id": self.batch_id,
            "events_committed": self.events_committed,
            "duplicates": self.duplicates,
            "conflicts_quarantined": self.conflicts_quarantined,
            "ack_allowed": self.ack_allowed,
        }


@dataclass(frozen=True, slots=True)
class ClaimedWebhookEvent:
    event_id: str
    event_key: str
    payload_hash: str
    payload: Mapping[str, Any]
    attempt_count: int
    claim_owner: str


@dataclass(frozen=True, slots=True)
class WebhookInboxCounts:
    pending: int
    claimed: int
    processed: int
    dead_letter: int
    conflicts: int
    total_events: int

    def to_dict(self) -> dict[str, int]:
        return {
            "pending": self.pending,
            "claimed": self.claimed,
            "processed": self.processed,
            "dead_letter": self.dead_letter,
            "conflicts": self.conflicts,
            "total_events": self.total_events,
        }


class DurableWebhookInbox:
    """SQLite-backed durable-before-ACK inbox for PR-195 webhook intake."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_attempts: int = 3,
        busy_timeout_ms: int = 5_000,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.path = str(path)
        self.max_attempts = max_attempts
        self.db = sqlite3.connect(
            self.path,
            isolation_level=None,
            timeout=busy_timeout_ms / 1000,
        )
        self.db.row_factory = sqlite3.Row
        self._configure_database(busy_timeout_ms)
        self._migrate()

    def __enter__(self) -> DurableWebhookInbox:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.db.close()

    def _configure_database(self, busy_timeout_ms: int) -> None:
        for pragma in (
            f"PRAGMA busy_timeout={busy_timeout_ms}",
            "PRAGMA foreign_keys=ON",
            "PRAGMA synchronous=FULL",
            "PRAGMA trusted_schema=OFF",
        ):
            self.db.execute(pragma)
        if self.path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")

    def _migrate(self) -> None:
        with self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS pr195_webhook_batches(
                  batch_id TEXT PRIMARY KEY,
                  provider TEXT NOT NULL,
                  webhook_id TEXT NOT NULL,
                  event_count INTEGER NOT NULL CHECK(event_count>=0),
                  payload_hash TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pr195_webhook_events(
                  event_id TEXT PRIMARY KEY,
                  batch_id TEXT NOT NULL
                    REFERENCES pr195_webhook_batches(batch_id) ON DELETE RESTRICT,
                  event_key TEXT NOT NULL UNIQUE,
                  provider TEXT NOT NULL,
                  webhook_id TEXT NOT NULL,
                  slot INTEGER NOT NULL CHECK(slot>=0),
                  event_index INTEGER NOT NULL CHECK(event_index>=0),
                  signature TEXT NOT NULL,
                  event_type TEXT NOT NULL,
                  payload_hash TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  state TEXT NOT NULL,
                  attempt_count INTEGER NOT NULL CHECK(attempt_count>=0),
                  claim_owner TEXT,
                  lease_expires_ns INTEGER,
                  last_error TEXT
                );

                CREATE TABLE IF NOT EXISTS pr195_webhook_conflicts(
                  conflict_id TEXT PRIMARY KEY,
                  event_key TEXT NOT NULL,
                  existing_payload_hash TEXT NOT NULL,
                  incoming_payload_hash TEXT NOT NULL,
                  incoming_payload_json TEXT NOT NULL,
                  reason_code TEXT NOT NULL
                );
                """)

    def receive_batch(
        self,
        *,
        provider: str,
        webhook_id: str,
        events: Sequence[Mapping[str, Any]],
    ) -> WebhookReceipt:
        provider = _required_text(provider, "provider")
        webhook_id = _required_text(webhook_id, "webhook_id")
        normalized = _validate_batch(events)
        identities = tuple(
            _identity_from_event(
                provider=provider,
                webhook_id=webhook_id,
                event=event,
                event_index=index,
            )
            for index, event in enumerate(normalized)
        )
        payload_jsons = tuple(_stable_json(event) for event in normalized)
        payload_hashes = tuple(_sha256_text(payload) for payload in payload_jsons)
        batch_id = _hash_json(
            {
                "event_keys": [identity.key for identity in identities],
                "payload_hashes": list(payload_hashes),
                "provider": provider,
                "schema": PR195_DURABLE_WEBHOOK_SCHEMA,
                "webhook_id": webhook_id,
            }
        )

        self.db.execute("BEGIN IMMEDIATE")
        committed = 0
        duplicates = 0
        conflicts = 0
        try:
            self.db.execute(
                "INSERT OR IGNORE INTO pr195_webhook_batches VALUES(?,?,?,?,?)",
                (
                    batch_id,
                    provider,
                    webhook_id,
                    len(normalized),
                    _hash_json({"payload_hashes": list(payload_hashes)}),
                ),
            )
            for identity, payload_json, payload_hash in zip(
                identities,
                payload_jsons,
                payload_hashes,
                strict=True,
            ):
                existing = self.db.execute(
                    "SELECT payload_hash FROM pr195_webhook_events "
                    "WHERE event_key=?",
                    (identity.key,),
                ).fetchone()
                if existing is not None:
                    if str(existing["payload_hash"]) == payload_hash:
                        duplicates += 1
                    else:
                        self._quarantine_conflict(
                            identity.key,
                            str(existing["payload_hash"]),
                            payload_hash,
                            payload_json,
                        )
                        conflicts += 1
                    continue
                self._insert_event(identity, batch_id, payload_hash, payload_json)
                committed += 1
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")
        return WebhookReceipt(
            schema_version=PR195_DURABLE_WEBHOOK_SCHEMA,
            batch_id=batch_id,
            events_committed=committed,
            duplicates=duplicates,
            conflicts_quarantined=conflicts,
            ack_allowed=True,
        )

    def _quarantine_conflict(
        self,
        event_key: str,
        existing_payload_hash: str,
        incoming_payload_hash: str,
        incoming_payload_json: str,
    ) -> None:
        self.db.execute(
            "INSERT INTO pr195_webhook_conflicts VALUES(?,?,?,?,?,?)",
            (
                uuid4().hex,
                event_key,
                existing_payload_hash,
                incoming_payload_hash,
                incoming_payload_json,
                "PAYLOAD_HASH_DRIFT_FOR_CHAIN_IDENTITY",
            ),
        )

    def _insert_event(
        self,
        identity: WebhookEventIdentity,
        batch_id: str,
        payload_hash: str,
        payload_json: str,
    ) -> None:
        self.db.execute(
            "INSERT INTO pr195_webhook_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                uuid4().hex,
                batch_id,
                identity.key,
                identity.provider,
                identity.webhook_id,
                identity.slot,
                identity.event_index,
                identity.signature,
                identity.event_type,
                payload_hash,
                payload_json,
                "pending",
                0,
                None,
                None,
                None,
            ),
        )

    def claim_next(
        self,
        *,
        owner: str,
        lease_expires_ns: int,
    ) -> ClaimedWebhookEvent | None:
        owner = _required_text(owner, "owner")
        if lease_expires_ns < 0:
            raise ValueError("lease_expires_ns must be non-negative")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT * FROM pr195_webhook_events WHERE state='pending' "
                "ORDER BY slot,event_index,event_id LIMIT 1"
            ).fetchone()
            if row is None:
                self.db.execute("COMMIT")
                return None
            self.db.execute(
                "UPDATE pr195_webhook_events SET state='claimed',"
                "attempt_count=?,claim_owner=?,lease_expires_ns=? "
                "WHERE event_id=? AND state='pending'",
                (
                    int(row["attempt_count"]) + 1,
                    owner,
                    lease_expires_ns,
                    str(row["event_id"]),
                ),
            )
            claimed = self._event_row(str(row["event_id"]))
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")
        if claimed is None:
            raise WebhookClaimError("claimed event disappeared")
        return _claimed_from_row(claimed)

    def ack_event(self, *, event_id: str, owner: str) -> None:
        event_id = _required_text(event_id, "event_id")
        owner = _required_text(owner, "owner")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            updated = self.db.execute(
                "UPDATE pr195_webhook_events SET state='processed',"
                "claim_owner=NULL,lease_expires_ns=NULL,last_error=NULL "
                "WHERE event_id=? AND state='claimed' AND claim_owner=?",
                (event_id, owner),
            )
            if updated.rowcount != 1:
                raise WebhookClaimError("event claim was not owned by caller")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")

    def nack_event(self, *, event_id: str, owner: str, error: str) -> None:
        event_id = _required_text(event_id, "event_id")
        owner = _required_text(owner, "owner")
        error = _required_text(error, "error")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT * FROM pr195_webhook_events "
                "WHERE event_id=? AND state='claimed' AND claim_owner=?",
                (event_id, owner),
            ).fetchone()
            if row is None:
                raise WebhookClaimError("event claim was not owned by caller")
            next_state = "dead_letter"
            if int(row["attempt_count"]) < self.max_attempts:
                next_state = "pending"
            self.db.execute(
                "UPDATE pr195_webhook_events SET state=?,claim_owner=NULL,"
                "lease_expires_ns=NULL,last_error=? WHERE event_id=?",
                (next_state, error, event_id),
            )
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")

    def reclaim_expired_claims(self, *, now_ns: int) -> int:
        if now_ns < 0:
            raise ValueError("now_ns must be non-negative")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            updated = self.db.execute(
                "UPDATE pr195_webhook_events SET state='pending',"
                "claim_owner=NULL,lease_expires_ns=NULL "
                "WHERE state='claimed' AND lease_expires_ns IS NOT NULL "
                "AND lease_expires_ns<=?",
                (now_ns,),
            )
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")
        return int(updated.rowcount)

    def counts(self) -> WebhookInboxCounts:
        state_counts = {
            str(row["state"]): int(row["count"])
            for row in self.db.execute(
                "SELECT state,COUNT(*) AS count "
                "FROM pr195_webhook_events GROUP BY state"
            )
        }
        conflicts = self.db.execute(
            "SELECT COUNT(*) AS count FROM pr195_webhook_conflicts"
        ).fetchone()
        return WebhookInboxCounts(
            pending=state_counts.get("pending", 0),
            claimed=state_counts.get("claimed", 0),
            processed=state_counts.get("processed", 0),
            dead_letter=state_counts.get("dead_letter", 0),
            conflicts=int(conflicts["count"] or 0),
            total_events=sum(state_counts.values()),
        )

    def _event_row(self, event_id: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM pr195_webhook_events WHERE event_id=?",
            (event_id,),
        ).fetchone()


def _identity_from_event(
    *,
    provider: str,
    webhook_id: str,
    event: Mapping[str, Any],
    event_index: int,
) -> WebhookEventIdentity:
    slot = event.get("slot")
    if not isinstance(slot, int) or slot < 0:
        raise WebhookSchemaError("event slot must be a non-negative integer")
    signature = event.get("signature")
    transaction = event.get("transaction")
    if signature is None and isinstance(transaction, Mapping):
        signature = transaction.get("signature")
    return WebhookEventIdentity(
        provider=provider,
        webhook_id=webhook_id,
        slot=slot,
        event_index=event_index,
        signature=_required_text(str(signature or ""), "signature"),
        event_type=_required_text(str(event.get("type", "unknown")), "event_type"),
    )


def _validate_batch(
    events: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    if isinstance(events, (bytes, str)) or not isinstance(events, Sequence):
        raise WebhookSchemaError("events must be a non-empty sequence")
    if not events:
        raise WebhookSchemaError("events must not be empty")
    normalized: list[Mapping[str, Any]] = []
    for event in events:
        if not isinstance(event, Mapping):
            raise WebhookSchemaError("every event must be a mapping")
        normalized.append(event)
    return tuple(normalized)


def _required_text(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise WebhookSchemaError(f"{name} is required")
    return normalized


def _stable_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_json(value: Mapping[str, Any]) -> str:
    return _sha256_text(_stable_json(value))


def _claimed_from_row(row: sqlite3.Row) -> ClaimedWebhookEvent:
    raw = json.loads(str(row["payload_json"]))
    if not isinstance(raw, Mapping):
        raise WebhookClaimError("stored payload is not a mapping")
    return ClaimedWebhookEvent(
        event_id=str(row["event_id"]),
        event_key=str(row["event_key"]),
        payload_hash=str(row["payload_hash"]),
        payload=raw,
        attempt_count=int(row["attempt_count"]),
        claim_owner=str(row["claim_owner"]),
    )


__all__ = [
    "ClaimedWebhookEvent",
    "DurableWebhookInbox",
    "PR195_DURABLE_WEBHOOK_SCHEMA",
    "WebhookClaimError",
    "WebhookEventIdentity",
    "WebhookInboxCounts",
    "WebhookIntakeError",
    "WebhookReceipt",
    "WebhookSchemaError",
]
