"""B2/B3 Helius delivery-plane durability primitives.

Deliveries are authenticated, bounded, decoded, canonically ordered, deduplicated
and committed to SQLite before acknowledgement.  The module performs no strategy,
signer, sender or live action.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Callable, Mapping, Sequence
import zlib

SCHEMA_VERSION = "b3.helius-delivery.v2"
AUTH_HEADER = "authorization"
_CHUNK_BYTES = 64 * 1024


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
    DUPLICATE_JSON_KEY = "DUPLICATE_JSON_KEY"
    NON_FINITE_JSON_NUMBER = "NON_FINITE_JSON_NUMBER"
    JSON_TOO_DEEP = "JSON_TOO_DEEP"
    JSON_TOO_LARGE = "JSON_TOO_LARGE"
    TOO_MANY_EVENTS = "TOO_MANY_EVENTS"
    NO_EVENTS = "NO_EVENTS"
    DELIVERY_DEADLINE_EXCEEDED = "DELIVERY_DEADLINE_EXCEEDED"
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

    def __post_init__(self) -> None:
        values = (
            self.max_compressed_bytes,
            self.max_decompressed_bytes,
            self.max_json_depth,
            self.max_json_nodes,
            self.max_events,
            self.delivery_deadline_ms,
            self.max_slot_gap,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in values[:-1]
        ):
            raise ValueError("delivery limits must be positive integers")
        if (
            isinstance(self.max_slot_gap, bool)
            or not isinstance(self.max_slot_gap, int)
            or self.max_slot_gap < 0
        ):
            raise ValueError("max_slot_gap must be a non-negative integer")


@dataclass(frozen=True)
class HeliusDeliveryConfig:
    auth_header: str
    store_path: str | Path
    limits: DeliveryLimits = DeliveryLimits()
    failed_transaction_policy: FailedTransactionPolicy = (
        FailedTransactionPolicy.PRESERVE
    )
    webhook_id: str = "helius-default"

    def __post_init__(self) -> None:
        if not self.auth_header:
            raise ValueError("auth_header is required")
        if not self.webhook_id:
            raise ValueError("webhook_id is required")


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
    return {str(key).lower(): str(value) for key, value in headers.items()}


def _check_deadline(
    *,
    started_ns: int,
    limits: DeliveryLimits,
    clock_ns: Callable[[], int],
) -> None:
    elapsed_ns = clock_ns() - started_ns
    if elapsed_ns < 0 or elapsed_ns > limits.delivery_deadline_ms * 1_000_000:
        raise ValueError(RejectReason.DELIVERY_DEADLINE_EXCEEDED.value)


def _gzip_bounded(
    raw_body: bytes,
    limits: DeliveryLimits,
    *,
    started_ns: int,
    clock_ns: Callable[[], int],
) -> bytes:
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    output = bytearray()
    try:
        for offset in range(0, len(raw_body), _CHUNK_BYTES):
            _check_deadline(
                started_ns=started_ns,
                limits=limits,
                clock_ns=clock_ns,
            )
            pending = raw_body[offset : offset + _CHUNK_BYTES]
            while pending:
                remaining = limits.max_decompressed_bytes - len(output)
                chunk = inflater.decompress(pending, remaining + 1)
                if len(chunk) > remaining:
                    raise ValueError(
                        RejectReason.DECOMPRESSED_BODY_TOO_LARGE.value
                    )
                output.extend(chunk)
                pending = inflater.unconsumed_tail
        remaining = limits.max_decompressed_bytes - len(output)
        tail = inflater.flush(remaining + 1)
        if len(tail) > remaining:
            raise ValueError(RejectReason.DECOMPRESSED_BODY_TOO_LARGE.value)
        output.extend(tail)
    except ValueError:
        raise
    except zlib.error as exc:
        raise ValueError(RejectReason.BAD_ENCODING.value) from exc
    if not inflater.eof:
        raise ValueError(RejectReason.BAD_ENCODING.value)
    return bytes(output)


def _decode_body(
    raw_body: bytes,
    headers: Mapping[str, str],
    limits: DeliveryLimits,
    *,
    started_ns: int,
    clock_ns: Callable[[], int],
) -> bytes:
    if len(raw_body) > limits.max_compressed_bytes:
        raise ValueError(RejectReason.BODY_TOO_LARGE.value)
    _check_deadline(started_ns=started_ns, limits=limits, clock_ns=clock_ns)
    encoding = headers.get("content-encoding", "").lower().strip()
    if encoding == "gzip":
        decoded = _gzip_bounded(
            raw_body,
            limits,
            started_ns=started_ns,
            clock_ns=clock_ns,
        )
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
    _check_deadline(started_ns=started_ns, limits=limits, clock_ns=clock_ns)
    return decoded


def _strict_json_loads(decoded: bytes) -> Any:
    def reject_constant(_: str) -> None:
        raise ValueError(RejectReason.NON_FINITE_JSON_NUMBER.value)

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(RejectReason.DUPLICATE_JSON_KEY.value)
            result[key] = value
        return result

    try:
        return json.loads(
            decoded.decode("utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=object_pairs,
        )
    except ValueError as exc:
        if str(exc) in RejectReason._value2member_map_:
            raise
        raise ValueError(RejectReason.BAD_JSON.value) from exc


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
    return 1, depth


def _event_signature(event: Mapping[str, Any]) -> str:
    transaction = event.get("transaction")
    if isinstance(transaction, Mapping) and transaction.get("signature"):
        return str(transaction["signature"])
    if event.get("signature"):
        return str(event["signature"])
    return "synthetic:" + _event_payload_hash(event)


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
    transaction = event.get("transaction")
    if isinstance(transaction, Mapping) and (
        transaction.get("error") or transaction.get("err")
    ):
        return True
    return str(event.get("status", "")).lower() in {"failed", "error"}


def _canonical_event_json(event: Mapping[str, Any]) -> str:
    return json.dumps(
        event,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _event_payload_hash(event: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_event_json(event).encode("utf-8")).hexdigest()


def canonical_event_identity(
    *,
    webhook_id: str,
    signature: str,
    slot: int | None,
    payload_hash: str,
) -> str:
    material = {
        "domain": "helius-event",
        "webhook_id": webhook_id,
        "signature": signature,
        "slot": slot,
        "payload_hash": payload_hash,
    }
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_event_order(
    events: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    return sorted(
        events,
        key=lambda event: (
            _event_slot(event) is None,
            _event_slot(event) if _event_slot(event) is not None else 2**64,
            _event_signature(event),
            _event_payload_hash(event),
        ),
    )


def _parse_events(
    decoded: bytes,
    limits: DeliveryLimits,
    *,
    started_ns: int,
    clock_ns: Callable[[], int],
) -> list[Mapping[str, Any]]:
    data = _strict_json_loads(decoded) if decoded else []
    _check_deadline(started_ns=started_ns, limits=limits, clock_ns=clock_ns)
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
    _check_deadline(started_ns=started_ns, limits=limits, clock_ns=clock_ns)
    return ordered


class HeliusDeliveryStore:
    """SQLite inbox with persistent delivery, event, dedup and gap state."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path))
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
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
                    payload_json TEXT,
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
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(helius_event_inbox)")
            }
            if "payload_json" not in columns:
                connection.execute(
                    "ALTER TABLE helius_event_inbox ADD COLUMN payload_json TEXT"
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
        delivery_id = hashlib.sha256(
            f"{webhook_id}:{payload_hash}".encode("utf-8")
        ).hexdigest()
        now_ns = time.time_ns()
        accepted = 0
        duplicates = 0
        failed_count = 0
        gap_detected = False
        with self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM helius_delivery WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone():
                connection.execute(
                    """
                    INSERT INTO helius_delivery_audit(
                        delivery_id, reason, detail_hash, created_at_ns
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (delivery_id, "duplicate_delivery", payload_hash, now_ns),
                )
                return delivery_id, 0, len(events), False, False

            gap_row = connection.execute(
                """
                SELECT last_slot, gap_from_slot, gap_to_slot
                FROM helius_gap_state
                WHERE webhook_id = ?
                """,
                (webhook_id,),
            ).fetchone()
            last_slot = (
                int(gap_row[0])
                if gap_row is not None and gap_row[0] is not None
                else None
            )
            existing_gap_from = (
                int(gap_row[1])
                if gap_row is not None and gap_row[1] is not None
                else None
            )
            existing_gap_to = (
                int(gap_row[2])
                if gap_row is not None and gap_row[2] is not None
                else None
            )
            unresolved_gap = (
                existing_gap_from is not None and existing_gap_to is not None
            )
            contiguous_slot = last_slot
            new_gap_from = existing_gap_from
            new_gap_to = existing_gap_to
            event_records: list[
                tuple[str, str, int | None, int, str, str, int]
            ] = []

            for index, event in enumerate(_canonical_event_order(events)):
                signature = _event_signature(event)
                slot = _event_slot(event)
                event_json = _canonical_event_json(event)
                event_hash = hashlib.sha256(event_json.encode("utf-8")).hexdigest()
                failed = _event_failed(event)
                if failed:
                    failed_count += 1
                    if failed_policy == FailedTransactionPolicy.REJECT:
                        raise ValueError(
                            RejectReason.FAILED_TX_REJECTED_BY_POLICY.value
                        )
                    if failed_policy == FailedTransactionPolicy.DROP_WITH_AUDIT:
                        connection.execute(
                            """
                            INSERT INTO helius_delivery_audit(
                                delivery_id, reason, detail_hash, created_at_ns
                            ) VALUES (?, ?, ?, ?)
                            """,
                            (
                                delivery_id,
                                "failed_event_dropped_by_policy",
                                event_hash,
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
                    else:
                        contiguous_slot = max(contiguous_slot, slot)

                dedup_key = canonical_event_identity(
                    webhook_id=webhook_id,
                    signature=signature,
                    slot=slot,
                    payload_hash=event_hash,
                )
                event_records.append(
                    (
                        dedup_key,
                        signature,
                        slot,
                        index,
                        event_hash,
                        event_json,
                        int(failed),
                    )
                )

            backfill_required = unresolved_gap
            connection.execute(
                """
                INSERT INTO helius_delivery(
                    delivery_id, webhook_id, payload_hash, received_at_ns,
                    event_count, duplicate_count, failed_event_count,
                    gap_detected, backfill_required
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    delivery_id,
                    webhook_id,
                    payload_hash,
                    now_ns,
                    len(event_records),
                    0,
                    failed_count,
                    int(gap_detected),
                    int(backfill_required),
                ),
            )
            for record in event_records:
                try:
                    connection.execute(
                        """
                        INSERT INTO helius_event_inbox(
                            dedup_key, delivery_id, signature, slot,
                            event_index, payload_hash, payload_json,
                            failed, queued_at_ns
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record[0],
                            delivery_id,
                            record[1],
                            record[2],
                            record[3],
                            record[4],
                            record[5],
                            record[6],
                            now_ns,
                        ),
                    )
                    accepted += 1
                except sqlite3.IntegrityError:
                    duplicates += 1
            connection.execute(
                """
                UPDATE helius_delivery
                SET event_count = ?, duplicate_count = ?
                WHERE delivery_id = ?
                """,
                (accepted, duplicates, delivery_id),
            )
            connection.execute(
                """
                INSERT INTO helius_gap_state(
                    webhook_id, last_slot, gap_from_slot, gap_to_slot,
                    updated_at_ns
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(webhook_id) DO UPDATE SET
                    last_slot = excluded.last_slot,
                    gap_from_slot = excluded.gap_from_slot,
                    gap_to_slot = excluded.gap_to_slot,
                    updated_at_ns = excluded.updated_at_ns
                """,
                (webhook_id, contiguous_slot, new_gap_from, new_gap_to, now_ns),
            )
        return delivery_id, accepted, duplicates, gap_detected, backfill_required

    def inbox_count(self) -> int:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM helius_event_inbox"
            ).fetchone()
            if row is None:
                raise RuntimeError("helius inbox count returned no row")
            return int(row[0])

    def audit_reasons(self) -> list[str]:
        self.initialize()
        with self._connect() as connection:
            return [
                str(row[0])
                for row in connection.execute(
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
    ):
        self.config = config
        self.store = HeliusDeliveryStore(config.store_path)
        self.store.initialize()
        self._clock_monotonic_ns = clock_monotonic_ns

    def accept_delivery(
        self,
        *,
        headers: Mapping[str, str],
        raw_body: bytes,
        webhook_id: str | None = None,
        started_monotonic_ns: int | None = None,
    ) -> DeliveryOutcome:
        started_ns = (
            self._clock_monotonic_ns()
            if started_monotonic_ns is None
            else started_monotonic_ns
        )
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
                started_ns=started_ns,
                clock_ns=self._clock_monotonic_ns,
            )
            payload_hash = _hash_bytes(decoded)
            events = _parse_events(
                decoded,
                self.config.limits,
                started_ns=started_ns,
                clock_ns=self._clock_monotonic_ns,
            )
            _check_deadline(
                started_ns=started_ns,
                limits=self.config.limits,
                clock_ns=self._clock_monotonic_ns,
            )
            delivery_id, accepted, duplicates, gap, backfill = self.store.enqueue(
                webhook_id=webhook_id or self.config.webhook_id,
                payload_hash=payload_hash,
                events=events,
                failed_policy=self.config.failed_transaction_policy,
                max_slot_gap=self.config.limits.max_slot_gap,
            )
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
        elapsed = self._clock_monotonic_ns() - started_ns
        return max(0, int(elapsed // 1_000_000))

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
    "AUTH_HEADER",
    "SCHEMA_VERSION",
    "DeliveryDecision",
    "DeliveryLimits",
    "DeliveryOutcome",
    "FailedTransactionPolicy",
    "HeliusDeliveryConfig",
    "HeliusDeliveryPlane",
    "HeliusDeliveryStore",
    "RejectReason",
    "canonical_event_identity",
]
