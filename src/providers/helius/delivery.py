"""Bounded Helius webhook ingress with canonical chain-event identity.

The delivery plane is sender-free.  It authenticates, bounds, validates and
durably enqueues webhook events before returning HTTP 200.  PR-188 removes
payload/index-dependent deduplication and makes delivery deadlines enforceable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
import time
from typing import Any, Callable, Mapping, Sequence
import zlib

SCHEMA_VERSION = "pr188.helius-delivery.v2"
AUTH_HEADER = "authorization"
_GZIP_WINDOW_BITS = 16 + zlib.MAX_WBITS
_READ_CHUNK_BYTES = 16_384


class DeliveryDecision(str, Enum):
    ACK_DURABLE = "ACK_DURABLE"
    ACK_DUPLICATE = "ACK_DUPLICATE"
    REJECTED = "REJECTED"


class RejectReason(str, Enum):
    MISSING_AUTH = "MISSING_AUTH"
    INVALID_AUTH = "INVALID_AUTH"
    BODY_TOO_LARGE = "BODY_TOO_LARGE"
    DECOMPRESSED_BODY_TOO_LARGE = "DECOMPRESSED_BODY_TOO_LARGE"
    COMPRESSION_RATIO_EXCEEDED = "COMPRESSION_RATIO_EXCEEDED"
    BAD_ENCODING = "BAD_ENCODING"
    BAD_JSON = "BAD_JSON"
    DUPLICATE_JSON_KEY = "DUPLICATE_JSON_KEY"
    NON_FINITE_JSON_NUMBER = "NON_FINITE_JSON_NUMBER"
    JSON_TOO_DEEP = "JSON_TOO_DEEP"
    JSON_TOO_LARGE = "JSON_TOO_LARGE"
    TOO_MANY_EVENTS = "TOO_MANY_EVENTS"
    NO_EVENTS = "NO_EVENTS"
    FAILED_TX_REJECTED_BY_POLICY = "FAILED_TX_REJECTED_BY_POLICY"
    DELIVERY_DEADLINE_EXCEEDED = "DELIVERY_DEADLINE_EXCEEDED"
    STORE_ERROR = "STORE_ERROR"


class FailedTransactionPolicy(str, Enum):
    PRESERVE = "preserve"
    REJECT = "reject"
    DROP_WITH_AUDIT = "drop_with_audit"


class EventRepresentation(str, Enum):
    NEW = "new"
    EXACT_DUPLICATE = "exact_duplicate"
    REPRESENTATION_DUPLICATE = "representation_duplicate"
    CORRECTION = "correction"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class DeliveryLimits:
    max_compressed_bytes: int = 256_000
    max_decompressed_bytes: int = 1_000_000
    max_compression_ratio: int = 200
    max_json_depth: int = 16
    max_json_nodes: int = 20_000
    max_events: int = 250
    delivery_deadline_ms: int = 800
    sqlite_busy_timeout_ms: int = 250
    max_slot_gap: int = 32

    def __post_init__(self) -> None:
        numeric = (
            self.max_compressed_bytes,
            self.max_decompressed_bytes,
            self.max_compression_ratio,
            self.max_json_depth,
            self.max_json_nodes,
            self.max_events,
            self.delivery_deadline_ms,
            self.sqlite_busy_timeout_ms,
            self.max_slot_gap,
        )
        if any(value <= 0 for value in numeric):
            raise ValueError("delivery limits must be positive")


@dataclass(frozen=True)
class HeliusDeliveryConfig:
    auth_header: str
    store_path: str | Path
    limits: DeliveryLimits = DeliveryLimits()
    failed_transaction_policy: FailedTransactionPolicy = (
        FailedTransactionPolicy.PRESERVE
    )
    webhook_id: str = "helius-default"
    cluster_genesis: str = "mainnet-beta"

    def __post_init__(self) -> None:
        if not self.auth_header:
            raise ValueError("auth_header is required")
        if not self.webhook_id.strip() or not self.cluster_genesis.strip():
            raise ValueError("webhook_id and cluster_genesis are required")


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


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _auth_ok(expected: str, received: str | None) -> tuple[bool, RejectReason | None]:
    if not received:
        return False, RejectReason.MISSING_AUTH
    if not hmac.compare_digest(str(expected), str(received)):
        return False, RejectReason.INVALID_AUTH
    return True, None


def _headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in headers.items()}


def _check_deadline(deadline_ns: int, monotonic_ns: Callable[[], int]) -> None:
    if monotonic_ns() >= deadline_ns:
        raise ValueError(RejectReason.DELIVERY_DEADLINE_EXCEEDED.value)


def _decode_body(
    raw_body: bytes,
    headers: Mapping[str, str],
    limits: DeliveryLimits,
    *,
    deadline_ns: int,
    monotonic_ns: Callable[[], int],
) -> bytes:
    if len(raw_body) > limits.max_compressed_bytes:
        raise ValueError(RejectReason.BODY_TOO_LARGE.value)
    _check_deadline(deadline_ns, monotonic_ns)

    encoding = headers.get("content-encoding", "").lower().strip()
    if encoding in {"", "identity"}:
        if len(raw_body) > limits.max_decompressed_bytes:
            raise ValueError(RejectReason.DECOMPRESSED_BODY_TOO_LARGE.value)
        decoded = raw_body
    elif encoding == "gzip":
        decoded = _decompress_gzip_bounded(
            raw_body,
            limits,
            deadline_ns=deadline_ns,
            monotonic_ns=monotonic_ns,
        )
    else:
        raise ValueError(RejectReason.BAD_ENCODING.value)

    try:
        decoded.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(RejectReason.BAD_ENCODING.value) from exc
    return decoded


def _decompress_gzip_bounded(
    raw_body: bytes,
    limits: DeliveryLimits,
    *,
    deadline_ns: int,
    monotonic_ns: Callable[[], int],
) -> bytes:
    decoder = zlib.decompressobj(_GZIP_WINDOW_BITS)
    output: list[bytes] = []
    output_size = 0
    ratio_ceiling = max(1, len(raw_body)) * limits.max_compression_ratio

    try:
        for offset in range(0, len(raw_body), _READ_CHUNK_BYTES):
            _check_deadline(deadline_ns, monotonic_ns)
            pending = raw_body[offset : offset + _READ_CHUNK_BYTES]
            while pending:
                remaining = limits.max_decompressed_bytes - output_size
                if remaining < 0:
                    raise ValueError(RejectReason.DECOMPRESSED_BODY_TOO_LARGE.value)
                chunk = decoder.decompress(pending, remaining + 1)
                if chunk:
                    output.append(chunk)
                    output_size += len(chunk)
                if output_size > limits.max_decompressed_bytes:
                    raise ValueError(RejectReason.DECOMPRESSED_BODY_TOO_LARGE.value)
                if output_size > ratio_ceiling:
                    raise ValueError(RejectReason.COMPRESSION_RATIO_EXCEEDED.value)
                pending = decoder.unconsumed_tail
                if not pending:
                    break

        _check_deadline(deadline_ns, monotonic_ns)
        remaining = limits.max_decompressed_bytes - output_size
        tail = decoder.flush(remaining + 1)
        if tail:
            output.append(tail)
            output_size += len(tail)
    except zlib.error as exc:
        raise ValueError(RejectReason.BAD_ENCODING.value) from exc

    if output_size > limits.max_decompressed_bytes:
        raise ValueError(RejectReason.DECOMPRESSED_BODY_TOO_LARGE.value)
    if output_size > ratio_ceiling:
        raise ValueError(RejectReason.COMPRESSION_RATIO_EXCEEDED.value)
    if not decoder.eof or decoder.unused_data:
        raise ValueError(RejectReason.BAD_ENCODING.value)
    return b"".join(output)


def _preflight_json_structure(text: str, limits: DeliveryLimits) -> None:
    depth = 0
    nodes = 0
    in_string = False
    escaped = False

    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
            nodes += 1
        elif character in "[{":
            depth += 1
            nodes += 1
            if depth > limits.max_json_depth:
                raise ValueError(RejectReason.JSON_TOO_DEEP.value)
        elif character in "]}":
            depth -= 1
            if depth < 0:
                raise ValueError(RejectReason.BAD_JSON.value)
        elif character in ",:":
            nodes += 1
        if nodes > limits.max_json_nodes * 4:
            raise ValueError(RejectReason.JSON_TOO_LARGE.value)

    if in_string or depth != 0:
        raise ValueError(RejectReason.BAD_JSON.value)


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(RejectReason.DUPLICATE_JSON_KEY.value)
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise ValueError(RejectReason.NON_FINITE_JSON_NUMBER.value)


def _json_stats(value: Any, depth: int = 0) -> tuple[int, int]:
    if isinstance(value, dict):
        nodes = 1
        max_depth = depth
        for key, child in value.items():
            key_nodes, key_depth = _json_stats(str(key), depth + 1)
            child_nodes, child_depth = _json_stats(child, depth + 1)
            nodes += key_nodes + child_nodes
            max_depth = max(max_depth, key_depth, child_depth)
        return nodes, max_depth
    if isinstance(value, list):
        nodes = 1
        max_depth = depth
        for child in value:
            child_nodes, child_depth = _json_stats(child, depth + 1)
            nodes += child_nodes
            max_depth = max(max_depth, child_depth)
        return nodes, max_depth
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(RejectReason.NON_FINITE_JSON_NUMBER.value)
    return 1, depth


def _parse_events(
    decoded: bytes,
    limits: DeliveryLimits,
    *,
    deadline_ns: int,
    monotonic_ns: Callable[[], int],
) -> list[dict[str, Any]]:
    try:
        text = decoded.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(RejectReason.BAD_ENCODING.value) from exc

    _preflight_json_structure(text, limits)
    _check_deadline(deadline_ns, monotonic_ns)
    try:
        data = (
            json.loads(
                text,
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=_reject_constant,
            )
            if decoded
            else []
        )
    except ValueError:
        raise
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
    ordered = _canonical_event_order(events)
    _check_deadline(deadline_ns, monotonic_ns)
    return [dict(event) for event in ordered]


def _event_signature(event: Mapping[str, Any]) -> str:
    tx = event.get("transaction")
    if isinstance(tx, Mapping) and tx.get("signature"):
        return str(tx["signature"])
    if event.get("signature"):
        return str(event["signature"])
    return "synthetic:" + hashlib.sha256(_canonical_json(event).encode()).hexdigest()


def _provider_event_id(event: Mapping[str, Any]) -> str | None:
    for key in ("eventId", "event_id", "webhookEventId", "webhook_event_id"):
        value = event.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def _event_discriminator(event: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "type",
        "eventType",
        "event_type",
        "instructionIndex",
        "instruction_index",
        "logIndex",
        "log_index",
    ):
        value = event.get(key)
        if value is not None and str(value).strip():
            parts.append(f"{key}={value}")
    return "|".join(parts) or "transaction"


def canonical_event_identity(
    *,
    webhook_id: str,
    signature: str,
    slot: int | None,
    payload_hash: str,
    cluster_genesis: str = "mainnet-beta",
    event_discriminator: str = "transaction",
) -> str:
    """Return stable primary identity.

    ``slot`` and ``payload_hash`` remain accepted for B3 compatibility but are
    deliberately excluded from primary identity because both may change across
    provider representations of the same transaction.
    """

    del slot, payload_hash
    material = (
        "pr188.canonical-chain-event.v1\0"
        f"{cluster_genesis}\0{webhook_id}\0"
        f"transaction:{signature}:{event_discriminator}"
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _canonical_event_id(
    *,
    cluster_genesis: str,
    webhook_id: str,
    event: Mapping[str, Any],
) -> str:
    native_id = _provider_event_id(event)
    if native_id is not None:
        material = (
            "pr188.canonical-chain-event.v1\0"
            f"{cluster_genesis}\0{webhook_id}\0provider:{native_id}"
        )
        return hashlib.sha256(material.encode()).hexdigest()
    return canonical_event_identity(
        webhook_id=webhook_id,
        signature=_event_signature(event),
        slot=_event_slot(event),
        payload_hash=_hash_bytes(_canonical_json(event).encode()),
        cluster_genesis=cluster_genesis,
        event_discriminator=_event_discriminator(event),
    )


def _event_slot(event: Mapping[str, Any]) -> int | None:
    value = event.get("slot")
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _event_failed(event: Mapping[str, Any]) -> bool:
    if event.get("transactionError") or event.get("error"):
        return True
    tx = event.get("transaction")
    if isinstance(tx, Mapping) and (tx.get("error") or tx.get("err")):
        return True
    return str(event.get("status", "")).lower() in {"failed", "error"}


def _canonical_event_order(
    events: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    return sorted(
        events,
        key=lambda event: (
            _event_slot(event) is None,
            _event_slot(event) if _event_slot(event) is not None else 2**64,
            _event_signature(event),
            _event_discriminator(event),
            _hash_bytes(_canonical_json(event).encode()),
        ),
    )


class HeliusDeliveryStore:
    """SQLite inbox with canonical identity and correction-aware representations."""

    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 250):
        self.path = Path(path)
        self.busy_timeout_ms = busy_timeout_ms

    def _harden_storage(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            os.chmod(self.path.parent, 0o700)
            for candidate in (
                self.path,
                Path(str(self.path) + "-wal"),
                Path(str(self.path) + "-shm"),
            ):
                if candidate.exists():
                    mode = stat.S_IMODE(candidate.stat().st_mode)
                    if mode != 0o600:
                        os.chmod(candidate, 0o600)

    def _connect(
        self,
        *,
        deadline_ns: int | None = None,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> sqlite3.Connection:
        self._harden_storage()
        timeout_ms = self.busy_timeout_ms
        if deadline_ns is not None:
            remaining_ms = max(0, (deadline_ns - monotonic_ns()) // 1_000_000)
            timeout_ms = min(timeout_ms, int(remaining_ms))
            if timeout_ms <= 0:
                raise ValueError(RejectReason.DELIVERY_DEADLINE_EXCEEDED.value)
        con = sqlite3.connect(str(self.path), timeout=timeout_ms / 1000)
        con.execute(f"PRAGMA busy_timeout={timeout_ms}")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        con.execute("PRAGMA foreign_keys=ON")
        self._harden_storage()
        return con

    @staticmethod
    def _column_names(con: sqlite3.Connection, table: str) -> set[str]:
        return {
            str(row[1]) for row in con.execute(f"PRAGMA table_info({table})").fetchall()
        }

    @classmethod
    def _ensure_column(
        cls,
        con: sqlite3.Connection,
        table: str,
        name: str,
        definition: str,
    ) -> None:
        if name not in cls._column_names(con, table):
            con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def initialize(
        self,
        *,
        deadline_ns: int | None = None,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        if deadline_ns is not None:
            _check_deadline(deadline_ns, monotonic_ns)
        with self._connect(
            deadline_ns=deadline_ns,
            monotonic_ns=monotonic_ns,
        ) as con:
            con.executescript("""
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
                    payload_json TEXT,
                    failed INTEGER NOT NULL,
                    queued_at_ns INTEGER NOT NULL,
                    processed_at_ns INTEGER,
                    state TEXT NOT NULL DEFAULT 'queued',
                    correction_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS helius_event_representation (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_event_id TEXT NOT NULL,
                    representation_hash TEXT NOT NULL,
                    delivery_id TEXT NOT NULL REFERENCES helius_delivery(delivery_id),
                    classification TEXT NOT NULL,
                    slot INTEGER,
                    payload_json TEXT NOT NULL,
                    observed_at_ns INTEGER NOT NULL,
                    UNIQUE(canonical_event_id, representation_hash)
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
                CREATE TABLE IF NOT EXISTS helius_backfill_job (
                    backfill_id TEXT PRIMARY KEY,
                    webhook_id TEXT NOT NULL,
                    gap_from_slot INTEGER NOT NULL,
                    gap_to_slot INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    lease_owner TEXT,
                    lease_expires_at_ns INTEGER,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    reconciliation_state TEXT NOT NULL DEFAULT 'pending',
                    created_at_ns INTEGER NOT NULL,
                    updated_at_ns INTEGER NOT NULL,
                    UNIQUE(webhook_id, gap_from_slot, gap_to_slot)
                );
                """)
            self._ensure_column(
                con,
                "helius_event_inbox",
                "payload_json",
                "TEXT",
            )
            self._ensure_column(
                con,
                "helius_event_inbox",
                "state",
                "TEXT NOT NULL DEFAULT 'queued'",
            )
            self._ensure_column(
                con,
                "helius_event_inbox",
                "correction_count",
                "INTEGER NOT NULL DEFAULT 0",
            )
        self._harden_storage()

    def enqueue(
        self,
        *,
        webhook_id: str,
        payload_hash: str,
        events: Sequence[Mapping[str, Any]],
        failed_policy: FailedTransactionPolicy,
        max_slot_gap: int,
        cluster_genesis: str = "mainnet-beta",
        deadline_ns: int | None = None,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> tuple[str, int, int, bool, bool]:
        self.initialize(deadline_ns=deadline_ns, monotonic_ns=monotonic_ns)
        delivery_id = hashlib.sha256(
            f"pr188.delivery.v1\0{webhook_id}\0{payload_hash}".encode()
        ).hexdigest()
        now_ns = time.time_ns()
        accepted = 0
        duplicates = 0
        failed_count = 0
        gap_detected = False
        backfill_required = False

        try:
            with self._connect(
                deadline_ns=deadline_ns,
                monotonic_ns=monotonic_ns,
            ) as con:
                con.execute("BEGIN IMMEDIATE")
                if deadline_ns is not None:
                    _check_deadline(deadline_ns, monotonic_ns)
                existing_delivery = con.execute(
                    "SELECT 1 FROM helius_delivery WHERE delivery_id = ?",
                    (delivery_id,),
                ).fetchone()
                if existing_delivery:
                    con.execute(
                        "INSERT INTO helius_delivery_audit"
                        "(delivery_id, reason, detail_hash, created_at_ns)"
                        " VALUES (?, ?, ?, ?)",
                        (
                            delivery_id,
                            "duplicate_delivery",
                            payload_hash,
                            now_ns,
                        ),
                    )
                    return delivery_id, 0, len(events), False, False

                con.execute(
                    "INSERT INTO helius_delivery"
                    "(delivery_id, webhook_id, payload_hash, received_at_ns,"
                    " event_count, duplicate_count, failed_event_count,"
                    " gap_detected, backfill_required)"
                    " VALUES (?, ?, ?, ?, 0, 0, 0, 0, 0)",
                    (delivery_id, webhook_id, payload_hash, now_ns),
                )
                row = con.execute(
                    "SELECT last_slot, gap_from_slot, gap_to_slot"
                    " FROM helius_gap_state WHERE webhook_id = ?",
                    (webhook_id,),
                ).fetchone()
                last_slot = int(row[0]) if row and row[0] is not None else None
                existing_gap_from = int(row[1]) if row and row[1] is not None else None
                existing_gap_to = int(row[2]) if row and row[2] is not None else None
                unresolved_gap = (
                    existing_gap_from is not None and existing_gap_to is not None
                )
                contiguous_slot = last_slot
                new_gap_from = existing_gap_from
                new_gap_to = existing_gap_to

                for index, event in enumerate(events):
                    if deadline_ns is not None:
                        _check_deadline(deadline_ns, monotonic_ns)
                    signature = _event_signature(event)
                    slot = _event_slot(event)
                    payload_json = _canonical_json(event)
                    representation_hash = hashlib.sha256(
                        payload_json.encode()
                    ).hexdigest()
                    canonical_event_id = _canonical_event_id(
                        cluster_genesis=cluster_genesis,
                        webhook_id=webhook_id,
                        event=event,
                    )
                    failed = _event_failed(event)
                    if failed:
                        failed_count += 1
                        if failed_policy == FailedTransactionPolicy.REJECT:
                            raise ValueError(
                                RejectReason.FAILED_TX_REJECTED_BY_POLICY.value
                            )
                        if failed_policy == FailedTransactionPolicy.DROP_WITH_AUDIT:
                            con.execute(
                                "INSERT INTO helius_delivery_audit"
                                "(delivery_id, reason, detail_hash, created_at_ns)"
                                " VALUES (?, ?, ?, ?)",
                                (
                                    delivery_id,
                                    "failed_event_dropped_by_policy",
                                    representation_hash,
                                    now_ns,
                                ),
                            )
                            continue

                    if slot is not None and not unresolved_gap:
                        if contiguous_slot is None:
                            contiguous_slot = slot
                        elif slot > contiguous_slot + max_slot_gap:
                            gap_detected = True
                            unresolved_gap = True
                            new_gap_from = contiguous_slot + 1
                            new_gap_to = slot - 1
                            self._upsert_backfill_job(
                                con,
                                webhook_id=webhook_id,
                                gap_from_slot=new_gap_from,
                                gap_to_slot=new_gap_to,
                                now_ns=now_ns,
                            )
                        else:
                            contiguous_slot = max(contiguous_slot, slot)
                    backfill_required = unresolved_gap

                    existing = con.execute(
                        "SELECT payload_hash, slot FROM helius_event_inbox"
                        " WHERE dedup_key = ?",
                        (canonical_event_id,),
                    ).fetchone()
                    if existing is None:
                        con.execute(
                            "INSERT INTO helius_event_inbox"
                            "(dedup_key, delivery_id, signature, slot,"
                            " event_index, payload_hash, payload_json, failed,"
                            " queued_at_ns, state, correction_count)"
                            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', 0)",
                            (
                                canonical_event_id,
                                delivery_id,
                                signature,
                                slot,
                                index,
                                representation_hash,
                                payload_json,
                                int(failed),
                                now_ns,
                            ),
                        )
                        classification = EventRepresentation.NEW
                        accepted += 1
                    else:
                        duplicates += 1
                        original_hash = str(existing[0])
                        original_slot = (
                            int(existing[1]) if existing[1] is not None else None
                        )
                        if original_hash == representation_hash:
                            classification = EventRepresentation.EXACT_DUPLICATE
                        elif (
                            original_slot is not None
                            and slot is not None
                            and original_slot != slot
                        ):
                            classification = EventRepresentation.CONFLICT
                        else:
                            classification = EventRepresentation.CORRECTION
                        if classification in {
                            EventRepresentation.CORRECTION,
                            EventRepresentation.CONFLICT,
                        }:
                            con.execute(
                                "UPDATE helius_event_inbox"
                                " SET correction_count = correction_count + 1"
                                " WHERE dedup_key = ?",
                                (canonical_event_id,),
                            )
                            con.execute(
                                "INSERT INTO helius_delivery_audit"
                                "(delivery_id, reason, detail_hash, created_at_ns)"
                                " VALUES (?, ?, ?, ?)",
                                (
                                    delivery_id,
                                    f"event_{classification.value}",
                                    representation_hash,
                                    now_ns,
                                ),
                            )

                    con.execute(
                        "INSERT OR IGNORE INTO helius_event_representation"
                        "(canonical_event_id, representation_hash, delivery_id,"
                        " classification, slot, payload_json, observed_at_ns)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            canonical_event_id,
                            representation_hash,
                            delivery_id,
                            classification.value,
                            slot,
                            payload_json,
                            now_ns,
                        ),
                    )

                con.execute(
                    "UPDATE helius_delivery SET event_count = ?,"
                    " duplicate_count = ?, failed_event_count = ?,"
                    " gap_detected = ?, backfill_required = ?"
                    " WHERE delivery_id = ?",
                    (
                        accepted,
                        duplicates,
                        failed_count,
                        int(gap_detected),
                        int(backfill_required),
                        delivery_id,
                    ),
                )
                con.execute(
                    "INSERT INTO helius_gap_state"
                    "(webhook_id, last_slot, gap_from_slot, gap_to_slot,"
                    " updated_at_ns) VALUES (?, ?, ?, ?, ?)"
                    " ON CONFLICT(webhook_id) DO UPDATE SET"
                    " last_slot = excluded.last_slot,"
                    " gap_from_slot = excluded.gap_from_slot,"
                    " gap_to_slot = excluded.gap_to_slot,"
                    " updated_at_ns = excluded.updated_at_ns",
                    (
                        webhook_id,
                        contiguous_slot,
                        new_gap_from,
                        new_gap_to,
                        now_ns,
                    ),
                )
                if deadline_ns is not None:
                    _check_deadline(deadline_ns, monotonic_ns)
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                if deadline_ns is not None:
                    raise ValueError(
                        RejectReason.DELIVERY_DEADLINE_EXCEEDED.value
                    ) from exc
            raise
        finally:
            self._harden_storage()

        return (
            delivery_id,
            accepted,
            duplicates,
            gap_detected,
            backfill_required,
        )

    @staticmethod
    def _upsert_backfill_job(
        con: sqlite3.Connection,
        *,
        webhook_id: str,
        gap_from_slot: int,
        gap_to_slot: int,
        now_ns: int,
    ) -> None:
        backfill_id = hashlib.sha256(
            (
                "pr188.backfill.v1\0" f"{webhook_id}\0{gap_from_slot}\0{gap_to_slot}"
            ).encode()
        ).hexdigest()
        con.execute(
            "INSERT INTO helius_backfill_job"
            "(backfill_id, webhook_id, gap_from_slot, gap_to_slot, status,"
            " created_at_ns, updated_at_ns)"
            " VALUES (?, ?, ?, ?, 'pending', ?, ?)"
            " ON CONFLICT(webhook_id, gap_from_slot, gap_to_slot)"
            " DO UPDATE SET updated_at_ns = excluded.updated_at_ns",
            (
                backfill_id,
                webhook_id,
                gap_from_slot,
                gap_to_slot,
                now_ns,
                now_ns,
            ),
        )

    def inbox_count(self) -> int:
        self.initialize()
        with self._connect() as con:
            return int(
                con.execute("SELECT COUNT(*) FROM helius_event_inbox").fetchone()[0]
            )

    def backfill_count(self) -> int:
        self.initialize()
        with self._connect() as con:
            return int(
                con.execute("SELECT COUNT(*) FROM helius_backfill_job").fetchone()[0]
            )

    def representation_classifications(self) -> list[str]:
        self.initialize()
        with self._connect() as con:
            return [
                str(row[0])
                for row in con.execute(
                    "SELECT classification FROM helius_event_representation"
                    " ORDER BY id"
                )
            ]

    def audit_reasons(self) -> list[str]:
        self.initialize()
        with self._connect() as con:
            return [
                str(row[0])
                for row in con.execute(
                    "SELECT reason FROM helius_delivery_audit ORDER BY id"
                )
            ]


class HeliusDeliveryPlane:
    """Validate and durably enqueue Helius deliveries before HTTP 200."""

    def __init__(
        self,
        config: HeliusDeliveryConfig,
        *,
        clock_monotonic_ns: Callable[[], int] = time.monotonic_ns,
        monotonic_ns: Callable[[], int] | None = None,
    ):
        self.config = config
        self._monotonic_ns = monotonic_ns or clock_monotonic_ns
        self.store = HeliusDeliveryStore(
            config.store_path,
            busy_timeout_ms=config.limits.sqlite_busy_timeout_ms,
        )
        self.store.initialize()

    def accept_delivery(
        self,
        *,
        headers: Mapping[str, str],
        raw_body: bytes,
        webhook_id: str | None = None,
        started_monotonic_ns: int | None = None,
    ) -> DeliveryOutcome:
        started_ns = (
            self._monotonic_ns()
            if started_monotonic_ns is None
            else started_monotonic_ns
        )
        deadline_ns = started_ns + self.config.limits.delivery_deadline_ms * 1_000_000
        canonical_headers = _headers(headers)
        payload_hash: str | None = None
        try:
            ok, reason = _auth_ok(
                self.config.auth_header,
                canonical_headers.get(AUTH_HEADER),
            )
            if not ok:
                return self._reject(
                    reason or RejectReason.INVALID_AUTH,
                    started_ns,
                    None,
                )
            decoded = _decode_body(
                raw_body,
                canonical_headers,
                self.config.limits,
                deadline_ns=deadline_ns,
                monotonic_ns=self._monotonic_ns,
            )
            payload_hash = _hash_bytes(decoded)
            events = _parse_events(
                decoded,
                self.config.limits,
                deadline_ns=deadline_ns,
                monotonic_ns=self._monotonic_ns,
            )
            (
                delivery_id,
                accepted,
                duplicates,
                gap,
                backfill,
            ) = self.store.enqueue(
                webhook_id=webhook_id or self.config.webhook_id,
                payload_hash=payload_hash,
                events=events,
                failed_policy=self.config.failed_transaction_policy,
                max_slot_gap=self.config.limits.max_slot_gap,
                cluster_genesis=self.config.cluster_genesis,
                deadline_ns=deadline_ns,
                monotonic_ns=self._monotonic_ns,
            )
            _check_deadline(deadline_ns, self._monotonic_ns)
            decision = (
                DeliveryDecision.ACK_DUPLICATE
                if accepted == 0 and duplicates
                else DeliveryDecision.ACK_DURABLE
            )
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
                self._elapsed_ms(started_ns),
            )
        except ValueError as exc:
            value = str(exc)
            reason = (
                RejectReason(value)
                if value in RejectReason._value2member_map_
                else RejectReason.BAD_JSON
            )
            return self._reject(reason, started_ns, payload_hash)
        except sqlite3.DatabaseError:
            return self._reject(
                RejectReason.STORE_ERROR,
                started_ns,
                payload_hash,
            )

    def _elapsed_ms(self, started_ns: int) -> int:
        return max(0, (self._monotonic_ns() - started_ns) // 1_000_000)

    def _reject(
        self,
        reason: RejectReason,
        started_ns: int,
        payload_hash: str | None,
    ) -> DeliveryOutcome:
        status = (
            401
            if reason in {RejectReason.MISSING_AUTH, RejectReason.INVALID_AUTH}
            else 400
        )
        if reason in {
            RejectReason.BODY_TOO_LARGE,
            RejectReason.DECOMPRESSED_BODY_TOO_LARGE,
            RejectReason.COMPRESSION_RATIO_EXCEEDED,
        }:
            status = 413
        if reason in {
            RejectReason.STORE_ERROR,
            RejectReason.DELIVERY_DEADLINE_EXCEEDED,
        }:
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
            self._elapsed_ms(started_ns),
        )


__all__ = [
    "DeliveryDecision",
    "DeliveryLimits",
    "DeliveryOutcome",
    "EventRepresentation",
    "FailedTransactionPolicy",
    "HeliusDeliveryConfig",
    "HeliusDeliveryPlane",
    "HeliusDeliveryStore",
    "RejectReason",
    "canonical_event_identity",
]
