"""Durable single-use consumption ledger for externally signed approvals.

This is the campaign-side sibling of the PR-201 replay ledger
(:mod:`src.authorization_replay_pr201`).  The PR-201 owner itself imports the
signer-authorization graph, so the qualification-campaign import boundary
(tested by ``test_campaign_import_graph_cannot_load_signer_or_submission``)
forbids reusing it directly.  This module re-implements the same durable
state machine (reserved -> consumed with atomic compare-and-swap) for one
narrow purpose: an externally supplied operator envelope (domain + key_id +
payload hash + signature fingerprint) may authorize exactly one operation.
Replays, concurrent reservations, altered payloads and store errors fail
closed; re-presenting the identical envelope for the identical operation
returns the same idempotent receipt.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3

_SCHEMA_VERSION = "prequal.campaign-approval-replay.v1"
_PRODUCT_ID = "flashloan-bot.campaign-approval-replay"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")

RESERVED = "reserved"
CONSUMED = "consumed"
EXPIRED = "expired"


class ApprovalReplayError(RuntimeError):
    """Stable fail-closed error without secret-bearing backend text."""

    def __init__(self, failure: str, message: str) -> None:
        super().__init__(message)
        self.failure = failure


@dataclass(frozen=True, slots=True)
class ApprovalReceipt:
    result_kind: str
    payload_json: str
    result_sha256: str

    @classmethod
    def from_payload(
        cls, result_kind: str, payload: dict[str, object]
    ) -> "ApprovalReceipt":
        if not _ID_RE.fullmatch(result_kind):
            raise ApprovalReplayError(
                "result_invalid", "approval result kind is invalid"
            )
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if len(payload_json.encode()) > 128 * 1024:
            raise ApprovalReplayError("result_invalid", "approval result is too large")
        digest = hashlib.sha256(
            json.dumps(
                {
                    "domain": "flashloan-bot/campaign-approval-result",
                    "result_kind": result_kind,
                    "payload": json.loads(payload_json),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return cls(result_kind, payload_json, digest)

    def validate(self) -> None:
        expected = self.from_payload(self.result_kind, json.loads(self.payload_json))
        if expected.result_sha256 != self.result_sha256:
            raise ApprovalReplayError(
                "result_invalid", "stored approval result digest mismatch"
            )


@dataclass(frozen=True, slots=True)
class _Reservation:
    acquired: bool
    operation_id: str
    receipt: ApprovalReceipt | None = None


@dataclass(frozen=True, slots=True)
class ApprovalExecution:
    consumption_key: str
    operation_id: str
    receipt: ApprovalReceipt
    replayed: bool


def external_envelope_consumption_key(
    *,
    envelope_domain: str,
    schema_version: str,
    key_id: str,
    issued_at_utc: str,
    expires_at_utc: str,
    payload_sha256: str,
    signature_base58: str,
) -> str:
    """Canonical durable consumption key for one external signed envelope."""

    fingerprint = {
        "domain": "flashloan-bot/campaign-approval-envelope-fingerprint",
        "envelope_domain": envelope_domain,
        "schema_version": schema_version,
        "key_id": key_id,
        "issued_at": issued_at_utc,
        "expires_at": expires_at_utc,
        "payload_sha256": payload_sha256,
        "signature_base58": signature_base58,
    }
    encoded = json.dumps(fingerprint, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _identifier(label: str, value: str) -> None:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ApprovalReplayError("bad_identifier", f"{label} is invalid")


class SQLiteApprovalReplayLedger:
    """Durable single-use ledger with bounded SQLite lock waiting."""

    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 250) -> None:
        if not 0 <= busy_timeout_ms <= 5_000:
            raise ValueError("busy_timeout_ms must be between 0 and 5000")
        self.path = str(path)
        self.busy_timeout_ms = busy_timeout_ms
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        try:
            with self._connect() as connection:
                connection.executescript("""
                    CREATE TABLE IF NOT EXISTS campaign_approval_meta(
                      singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                      product_id TEXT NOT NULL,
                      schema_version TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS campaign_external_envelope_ledger(
                      consumption_key TEXT PRIMARY KEY,
                      envelope_domain TEXT NOT NULL,
                      key_id TEXT NOT NULL,
                      payload_sha256 TEXT NOT NULL,
                      signature_base58 TEXT NOT NULL,
                      state TEXT NOT NULL,
                      reserved_operation_id TEXT,
                      request_hash TEXT,
                      result_kind TEXT,
                      result_payload_json TEXT,
                      result_sha256 TEXT,
                      envelope_expires_at_ns INTEGER NOT NULL,
                      updated_at_ns INTEGER NOT NULL,
                      consumed_at_ns INTEGER,
                      conflict_reason TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_campaign_approval_state_expiry
                    ON campaign_external_envelope_ledger(state, envelope_expires_at_ns);
                    """)
                connection.execute(
                    """INSERT INTO campaign_approval_meta VALUES(1, ?, ?)
                    ON CONFLICT(singleton) DO NOTHING""",
                    (_PRODUCT_ID, _SCHEMA_VERSION),
                )
                row = connection.execute(
                    "SELECT product_id, schema_version FROM campaign_approval_meta"
                ).fetchone()
                if row is None or tuple(row) != (_PRODUCT_ID, _SCHEMA_VERSION):
                    raise ApprovalReplayError(
                        "store_error", "approval replay database identity mismatch"
                    )
        except ApprovalReplayError:
            raise
        except sqlite3.Error as exc:
            raise self._store_error("database initialization failed", exc)

    def reserve_external_envelope(
        self,
        *,
        consumption_key: str,
        envelope_domain: str,
        key_id: str,
        payload_sha256: str,
        signature_base58: str,
        envelope_expires_at_ns: int,
        operation_id: str,
        request_hash: str,
        now_ns: int,
    ) -> _Reservation:
        _identifier("operation_id", operation_id)
        _identifier("consumption_key", consumption_key)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM campaign_external_envelope_ledger "
                    "WHERE consumption_key=?",
                    (consumption_key,),
                ).fetchone()
                if row is None:
                    connection.execute(
                        """INSERT INTO campaign_external_envelope_ledger(
                          consumption_key, envelope_domain, key_id, payload_sha256,
                          signature_base58, state, reserved_operation_id, request_hash,
                          envelope_expires_at_ns, updated_at_ns
                        ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (
                            consumption_key,
                            envelope_domain,
                            key_id,
                            payload_sha256,
                            signature_base58,
                            RESERVED,
                            operation_id,
                            request_hash,
                            envelope_expires_at_ns,
                            now_ns,
                        ),
                    )
                    connection.execute("COMMIT")
                    return _Reservation(True, operation_id)
                state = row["state"]
                if state == CONSUMED:
                    if self._same_request(row, operation_id, request_hash):
                        receipt = self._receipt(row)
                        connection.execute("COMMIT")
                        return _Reservation(False, operation_id, receipt)
                    connection.execute("ROLLBACK")
                    raise ApprovalReplayError(
                        "replayed",
                        "external envelope already authorized a different operation",
                    )
                if state == RESERVED:
                    connection.execute("ROLLBACK")
                    if self._same_request(row, operation_id, request_hash):
                        raise ApprovalReplayError(
                            "in_progress", "external envelope reservation in progress"
                        )
                    raise ApprovalReplayError(
                        "conflicted", "external envelope reservation conflict"
                    )
                connection.execute("ROLLBACK")
                raise ApprovalReplayError(
                    "expired" if state == EXPIRED else "conflicted",
                    f"external envelope state is {state}",
                )
        except ApprovalReplayError:
            raise
        except sqlite3.Error as exc:
            raise self._store_error("failed to reserve external envelope", exc)

    def finalize_external_envelope(
        self,
        *,
        consumption_key: str,
        operation_id: str,
        request_hash: str,
        receipt: ApprovalReceipt,
        now_ns: int,
    ) -> ApprovalExecution:
        receipt.validate()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM campaign_external_envelope_ledger "
                    "WHERE consumption_key=?",
                    (consumption_key,),
                ).fetchone()
                if row is None:
                    connection.execute("ROLLBACK")
                    raise ApprovalReplayError(
                        "bad_envelope", "external envelope reservation is absent"
                    )
                state = row["state"]
                if state == CONSUMED:
                    stored = self._receipt(row)
                    if (
                        self._same_request(row, operation_id, request_hash)
                        and stored.result_sha256 == receipt.result_sha256
                    ):
                        connection.execute("COMMIT")
                        return ApprovalExecution(
                            consumption_key, operation_id, stored, True
                        )
                    connection.execute("ROLLBACK")
                    raise ApprovalReplayError(
                        "replayed",
                        "external envelope result conflicts with consumed record",
                    )
                if state != RESERVED or not self._same_request(
                    row, operation_id, request_hash
                ):
                    connection.execute("ROLLBACK")
                    raise ApprovalReplayError(
                        "conflicted",
                        "external envelope finalization does not match reservation",
                    )
                updated = connection.execute(
                    """UPDATE campaign_external_envelope_ledger
                    SET state=?, result_kind=?, result_payload_json=?, result_sha256=?,
                        consumed_at_ns=?, updated_at_ns=?
                    WHERE consumption_key=? AND state=? AND reserved_operation_id=?
                      AND request_hash=?""",
                    (
                        CONSUMED,
                        receipt.result_kind,
                        receipt.payload_json,
                        receipt.result_sha256,
                        now_ns,
                        now_ns,
                        consumption_key,
                        RESERVED,
                        operation_id,
                        request_hash,
                    ),
                ).rowcount
                if updated != 1:
                    connection.execute("ROLLBACK")
                    raise ApprovalReplayError(
                        "conflicted", "external envelope compare-and-swap failed"
                    )
                connection.execute("COMMIT")
                return ApprovalExecution(consumption_key, operation_id, receipt, False)
        except ApprovalReplayError:
            raise
        except sqlite3.Error as exc:
            raise self._store_error("failed to finalize external envelope", exc)

    @staticmethod
    def _same_request(row: sqlite3.Row, operation_id: str, request_hash: str) -> bool:
        return (
            row["reserved_operation_id"] == operation_id
            and row["request_hash"] == request_hash
        )

    @staticmethod
    def _receipt(row: sqlite3.Row) -> ApprovalReceipt:
        fields = (row["result_kind"], row["result_payload_json"], row["result_sha256"])
        if any(value is None for value in fields):
            raise ApprovalReplayError(
                "store_error", "consumed envelope has no durable result"
            )
        receipt = ApprovalReceipt(*fields)
        receipt.validate()
        return receipt

    @staticmethod
    def _store_error(message: str, exc: sqlite3.Error) -> ApprovalReplayError:
        return ApprovalReplayError("store_error", message)


__all__ = [
    "ApprovalExecution",
    "ApprovalReceipt",
    "ApprovalReplayError",
    "SQLiteApprovalReplayLedger",
    "external_envelope_consumption_key",
]
