"""B2 Helius delivery-plane durability primitives.

This module implements an active reusable Helius delivery boundary.  It does no
strategy work and no live/sender action: deliveries are authorized, bounded,
normalized, deduplicated and durably enqueued first; downstream workers can
consume the SQLite inbox after acknowledgement.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import gzip
import hashlib
import hmac
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "b2.helius-delivery.v1"
AUTH_HEADER = "authorization"


class DeliveryDecision(str, Enum):
    ACK_DURABLE = "ACK_DURABLE"
    ACK_DUPLICATE = "ACK_DUPLICATE"
    REJECTED = "REJECTED"


class RejectReason(str, Enum):
    MISSING_AUTH = "MISSING_AUTH"
    INVALID_AUTH = "INVALID_AUTH"
    BODY_TOO_LARGE = "BODY_TOO_LARGE"
    DECOMPRESSED_BODY_TOO_LARGE = "DECOMPRESSED_BODY_TOO_LARGE"
    BAD_ENCODING = "BAD_ENCODING"
    BAD_JSON = "BAD_JSON"
    JSON_TOO_DEEP = "JSON_TOO_DEEP"
    JSON_TOO_LARGE = "JSON_TOO_LARGE"
    TOO_MANY_EVENTS = "TOO_MANY_EVENTS"
    NO_EVENTS = "NO_EVENTS"
    FAILED_TX_REJECTED_BY_POLICY = "FAILED_TX_REJECTED_BY_POLICY"
    STORE_ERROR = "STORE_ERROR"


class FailedTransactionPolicy(str, Enum):
    PRESERVE = "preserve"
    REJECT = "reject"
    DROP_WITH_AUDIT = "drop_with_audit"


@dataclass(frozen=True)
class DeliveryLimits:
    max_compressed_bytes: int = 256_000
    max_decompressed_bytes: int = 1_000_000
    max_json_depth: int = 16
    max_json_nodes: int = 20_000
    max_events: int = 250
    delivery_deadline_ms: int = 800
    max_slot_gap: int = 32


@dataclass(frozen=True)
class HeliusDeliveryConfig:
    auth_header: str
    store_path: str | Path
    limits: DeliveryLimits = DeliveryLimits()
    failed_transaction_policy: FailedTransactionPolicy = FailedTransactionPolicy.PRESERVE
    webhook_id: str = "helius-default"


@dataclass(frozen=True)
class DeliveryOutcome:
    schema_version: str
    decision: DeliveryDecision
    http_status: int
    reason: str | None
    delivery_id: str | None
    accepted_event_count: int
    duplicate_event_count: int
    payload_hash: str | None
    gap_detected: bool
    backfill_required: bool
    duration_ms: int
    live_enabled: bool = False
    sender_reachable: bool = False

    @property
    def acknowledged(self) -> bool:
        return self.http_status == 200


def _hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _auth_ok(expected: str, received: str | None) -> tuple[bool, RejectReason | None]:
    if not received:
        return False, RejectReason.MISSING_AUTH
    if not hmac.compare_digest(str(expected), str(received)):
        return False, RejectReason.INVALID_AUTH
    return True, None


def _headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {str(k).lower(): str(v) for k, v in headers.items()}


def _decode_body(raw_body: bytes, headers: Mapping[str, str], limits: DeliveryLimits) -> bytes:
    if len(raw_body) > limits.max_compressed_bytes:
        raise ValueError(RejectReason.BODY_TOO_LARGE.value)
    encoding = headers.get("content-encoding", "").lower().strip()
    if encoding == "gzip":
        try:
            decoded = gzip.decompress(raw_body)
        except Exception as exc:
            raise ValueError(RejectReason.BAD_ENCODING.value) from exc
    elif encoding in {"", "identity"}:
        decoded = raw_body
    else:
        raise ValueError(RejectReason.BAD_ENCODING.value)
    if len(decoded) > limits.max_decompressed_bytes:
        raise ValueError(RejectReason.DECOMPRESSED_BODY_TOO_LARGE.value)
    try:
        decoded.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(RejectReason.BAD_ENCODING.value) from exc
    return decoded


def _json_stats(value: Any, depth: int = 0) -> tuple[int, int]:
    if isinstance(value, dict):
        nodes = 1
        max_depth = depth
        for key, child in value.items():
            kn, kd = _json_stats(str(key), depth + 1)
            cn, cd = _json_stats(child, depth + 1)
            nodes += kn + cn
            max_depth = max(max_depth, kd, cd)
        return nodes, max_depth
    if isinstance(value, list):
        nodes = 1
        max_depth = depth
        for child in value:
            cn, cd = _json_stats(child, depth + 1)
            nodes += cn
            max_depth = max(max_depth, cd)
        return nodes, max_depth
    return 1, depth


def _parse_events(decoded: bytes, limits: DeliveryLimits) -> list[dict[str, Any]]:
    try:
        data = json.loads(decoded.decode("utf-8")) if decoded else []
    except json.JSONDecodeError as exc:
        raise ValueError(RejectReason.BAD_JSON.value) from exc
    nodes, depth = _json_stats(data)
    if depth > limits.max_json_depth:
        raise ValueError(RejectReason.JSON_TOO_DEEP.value)
    if nodes > limits.max_json_nodes:
        raise ValueError(RejectReason.JSON_TOO_LARGE.value)
    if isinstance(data, list):
        events = data
    elif isinstance(data, dict):
        inner = data.get("events")
        events = inner if isinstance(inner, list) else [data]
    else:
        events = []
    if not events:
        raise ValueError(RejectReason.NO_EVENTS.value)
    if len(events) > limits.max_events:
        raise ValueError(RejectReason.TOO_MANY_EVENTS.value)
    if not all(isinstance(event, dict) for event in events):
        raise ValueError(RejectReason.BAD_JSON.value)
    return list(events)


def _event_signature(event: Mapping[str, Any]) -> str:
    tx = event.get("transaction")
    if isinstance(tx, Mapping) and tx.get("signature"):
        return str(tx["signature"])
    if event.get("signature"):
        return str(event["signature"])
    return "synthetic:" + hashlib.sha256(
        json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _event_slot(event: Mapping[str, Any]) -> int | None:
    try:
        return int(event["slot"]) if event.get("slot") is not None else None
    except (TypeError, ValueError):
        return None


def _event_failed(event: Mapping[str, Any]) -> bool:
    if event.get("transactionError") or event.get("error"):
        return True
    tx = event.get("transaction")
    if isinstance(tx, Mapping) and (tx.get("error") or tx.get("err")):
        return True
    return str(event.get("status", "")).lower() in {"failed", "error"}


class HeliusDeliveryStore:
    """SQLite inbox with persistent delivery/event/dedup state."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(self.path))
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def initialize(self) -> None:
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS helius_delivery (
                    delivery_id TEXT PRIMARY KEY,
                    webhook_id TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    received_at_ns INTEGER NOT NULL,
                    event_count INTEGER NOT NULL,
                    duplicate_count INTEGER NOT NULL,
                    failed_event_count INTEGER NOT NULL,
                    gap_detected INTEGER NOT NULL,
                    backfill_required INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS helius_event_inbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dedup_key TEXT UNIQUE NOT NULL,
                    delivery_id TEXT NOT NULL REFERENCES helius_delivery(delivery_id),
                    signature TEXT NOT NULL,
                    slot INTEGER,
                    event_index INTEGER NOT NULL,
                    payload_hash TEXT NOT NULL,
                    failed INTEGER NOT NULL,
                    queued_at_ns INTEGER NOT NULL,
                    processed_at_ns INTEGER
                );
                CREATE TABLE IF NOT EXISTS helius_delivery_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    delivery_id TEXT,
                    reason TEXT NOT NULL,
                    detail_hash TEXT,
                    created_at_ns INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS helius_gap_state (
                    webhook_id TEXT PRIMARY KEY,
                    last_slot INTEGER,
                    gap_from_slot INTEGER,
                    gap_to_slot INTEGER,
                    updated_at_ns INTEGER NOT NULL
                );
                """
            )

    def enqueue(
        self,
        *,
        webhook_id: str,
        payload_hash: str,
        events: Sequence[Mapping[str, Any]],
        failed_policy: FailedTransactionPolicy,
        max_slot_gap: int,
    ) -> tuple[str, int, int, bool, bool]:
        self.initialize()
        delivery_id = hashlib.sha256(f"{webhook_id}:{payload_hash}".encode()).hexdigest()
        now_ns = time.time_ns()
        accepted = 0
        duplicates = 0
        failed_count = 0
        gap_detected = False
        backfill_required = False
        with self._connect() as con:
            if con.execute("SELECT 1 FROM helius_delivery WHERE delivery_id = ?", (delivery_id,)).fetchone():
                con.execute(
                    "INSERT INTO helius_delivery_audit(delivery_id, reason, detail_hash, created_at_ns)"
                    " VALUES (?, ?, ?, ?)",
                    (delivery_id, "duplicate_delivery", payload_hash, now_ns),
                )
                return delivery_id, 0, len(events), False, False

            row = con.execute(
                "SELECT last_slot FROM helius_gap_state WHERE webhook_id = ?",
                (webhook_id,),
            ).fetchone()
            last_slot = int(row[0]) if row and row[0] is not None else None
            max_seen_slot = last_slot
            event_records: list[tuple[str, str, int | None, int, str, int]] = []

            for idx, event in enumerate(events):
                signature = _event_signature(event)
                slot = _event_slot(event)
                event_hash = hashlib.sha256(
                    json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                failed = _event_failed(event)
                if failed:
                    failed_count += 1
                    if failed_policy == FailedTransactionPolicy.REJECT:
                        raise ValueError(RejectReason.FAILED_TX_REJECTED_BY_POLICY.value)
                    if failed_policy == FailedTransactionPolicy.DROP_WITH_AUDIT:
                        con.execute(
                            "INSERT INTO helius_delivery_audit(delivery_id, reason, detail_hash, created_at_ns)"
                            " VALUES (?, ?, ?, ?)",
                            (delivery_id, "failed_event_dropped_by_policy", event_hash, now_ns),
                        )
                        continue
                if slot is not None and last_slot is not None and slot > last_slot + max_slot_gap:
                    gap_detected = True
                    backfill_required = True
                    con.execute(
                        "INSERT OR REPLACE INTO helius_gap_state(webhook_id, last_slot, gap_from_slot, gap_to_slot, updated_at_ns)"
                        " VALUES (?, ?, ?, ?, ?)",
                        (webhook_id, last_slot, last_slot + 1, slot - 1, now_ns),
                    )
                if slot is not None:
                    max_seen_slot = max(slot, max_seen_slot or slot)
                dedup_key = hashlib.sha256(
                    f"{webhook_id}:{signature}:{slot}:{idx}:{event_hash}".encode()
                ).hexdigest()
                event_records.append((dedup_key, signature, slot, idx, event_hash, int(failed)))

            con.execute(
                "INSERT INTO helius_delivery(delivery_id, webhook_id, payload_hash, received_at_ns,"
                " event_count, duplicate_count, failed_event_count, gap_detected, backfill_required)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (delivery_id, webhook_id, payload_hash, now_ns, len(event_records), 0, failed_count, int(gap_detected), int(backfill_required)),
            )
            for record in event_records:
                try:
                    con.execute(
                        "INSERT INTO helius_event_inbox(dedup_key, delivery_id, signature, slot,"
                        " event_index, payload_hash, failed, queued_at_ns) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (record[0], delivery_id, record[1], record[2], record[3], record[4], record[5], now_ns),
                    )
                    accepted += 1
                except sqlite3.IntegrityError:
                    duplicates += 1
            con.execute(
                "UPDATE helius_delivery SET event_count = ?, duplicate_count = ? WHERE delivery_id = ?",
                (accepted, duplicates, delivery_id),
            )
            if max_seen_slot is not None:
                con.execute(
                    "INSERT OR REPLACE INTO helius_gap_state(webhook_id, last_slot, gap_from_slot, gap_to_slot, updated_at_ns)"
                    " VALUES (?, ?, COALESCE((SELECT gap_from_slot FROM helius_gap_state WHERE webhook_id = ?), NULL),"
                    " COALESCE((SELECT gap_to_slot FROM helius_gap_state WHERE webhook_id = ?), NULL), ?)",
                    (webhook_id, max_seen_slot, webhook_id, webhook_id, now_ns),
                )
        return delivery_id, accepted, duplicates, gap_detected, backfill_required

    def inbox_count(self) -> int:
        self.initialize()
        with self._connect() as con:
            return int(con.execute("SELECT COUNT(*) FROM helius_event_inbox").fetchone()[0])

    def audit_reasons(self) -> list[str]:
        self.initialize()
        with self._connect() as con:
            return [str(row[0]) for row in con.execute("SELECT reason FROM helius_delivery_audit ORDER BY id")]


class HeliusDeliveryPlane:
    """Validate and durably enqueue Helius deliveries before HTTP 200."""

    def __init__(self, config: HeliusDeliveryConfig):
        self.config = config
        self.store = HeliusDeliveryStore(config.store_path)
        self.store.initialize()

    def accept_delivery(
        self,
        *,
        headers: Mapping[str, str],
        raw_body: bytes,
        webhook_id: str | None = None,
    ) -> DeliveryOutcome:
        started = time.monotonic()
        canonical_headers = _headers(headers)
        payload_hash: str | None = None
        try:
            ok, reason = _auth_ok(self.config.auth_header, canonical_headers.get(AUTH_HEADER))
            if not ok:
                return self._reject(reason or RejectReason.INVALID_AUTH, started, None)
            decoded = _decode_body(raw_body, canonical_headers, self.config.limits)
            payload_hash = _hash_bytes(decoded)
            events = _parse_events(decoded, self.config.limits)
            delivery_id, accepted, duplicates, gap, backfill = self.store.enqueue(
                webhook_id=webhook_id or self.config.webhook_id,
                payload_hash=payload_hash,
                events=events,
                failed_policy=self.config.failed_transaction_policy,
                max_slot_gap=self.config.limits.max_slot_gap,
            )
            decision = DeliveryDecision.ACK_DUPLICATE if accepted == 0 and duplicates else DeliveryDecision.ACK_DURABLE
            return DeliveryOutcome(
                SCHEMA_VERSION,
                decision,
                200,
                None,
                delivery_id,
                accepted,
                duplicates,
                payload_hash,
                gap,
                backfill,
                self._elapsed_ms(started),
            )
        except ValueError as exc:
            value = str(exc)
            reason = RejectReason(value) if value in RejectReason._value2member_map_ else RejectReason.BAD_JSON
            return self._reject(reason, started, payload_hash)
        except sqlite3.DatabaseError:
            return self._reject(RejectReason.STORE_ERROR, started, payload_hash)

    def _elapsed_ms(self, started: float) -> int:
        return max(0, int((time.monotonic() - started) * 1000))

    def _reject(self, reason: RejectReason, started: float, payload_hash: str | None) -> DeliveryOutcome:
        status = 401 if reason in {RejectReason.MISSING_AUTH, RejectReason.INVALID_AUTH} else 400
        if reason in {RejectReason.BODY_TOO_LARGE, RejectReason.DECOMPRESSED_BODY_TOO_LARGE}:
            status = 413
        if reason == RejectReason.STORE_ERROR:
            status = 503
        return DeliveryOutcome(
            SCHEMA_VERSION,
            DeliveryDecision.REJECTED,
            status,
            reason.value,
            None,
            0,
            0,
            payload_hash,
            False,
            False,
            self._elapsed_ms(started),
        )
