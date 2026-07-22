"""PR-184 tamper-evident observability ledger primitives.

This module is deliberately network-free. It provides deterministic row-envelope
hashing, strict payload/column verification, and chain-continuity checks used by
the active SQLite store and offline replay.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

ZERO_CHAIN_DIGEST = "0" * 64
CHAIN_SCHEMA = "pr184.audit-chain.v1"

PAYLOAD_COLUMN_BINDINGS: tuple[tuple[str, str], ...] = (
    ("event_id", "event_id"),
    ("aggregate_id", "aggregate_id"),
    ("sequence_no", "sequence_no"),
    ("idempotency_key", "idempotency_key"),
    ("occurred_at_utc_ns", "occurred_at_utc_ns"),
    ("monotonic_ns", "monotonic_ns"),
    ("event_type", "event_type"),
    ("schema_version", "schema_version"),
    ("reason_code", "reason_code"),
    ("outcome", "outcome"),
    ("stage", "stage"),
    ("severity", "severity"),
    ("environment", "environment"),
    ("logical_opportunity_id", "logical_opportunity_id"),
    ("plan_hash", "plan_hash"),
    ("attempt_generation", "attempt_generation"),
    ("attempt_id", "attempt_id"),
    ("message_hash", "message_hash"),
    ("tx_signature", "tx_signature"),
    ("jito_bundle_id", "jito_bundle_id"),
    ("provider_id", "provider_id"),
    ("venue_id", "venue_id"),
    ("config_checksum", "config_checksum"),
    ("producer_code_version", "producer_code_version"),
    ("contract_fixture_version", "contract_fixture_version"),
)


class AuditIntegrityError(ValueError):
    """Raised when an audit row cannot be canonically verified."""


def canonical_json(payload: object) -> str:
    """Serialize only JSON-native finite values with deterministic identity."""

    _validate_json_value(payload)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def strict_json_loads(raw: str) -> Any:
    """Reject duplicate keys and non-finite constants."""

    def reject_constant(value: str) -> None:
        raise AuditIntegrityError(f"non-finite JSON constant: {value}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AuditIntegrityError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (json.JSONDecodeError, AuditIntegrityError) as exc:
        raise AuditIntegrityError("invalid audit payload JSON") from exc
    _validate_json_value(value)
    return value


def sha256_json(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def event_chain_envelope(
    *,
    row: Mapping[str, Any],
    previous_chain_digest: str,
    database_epoch: str,
    writer_generation: str,
    release_id: str,
    policy_bundle_hash: str,
) -> dict[str, Any]:
    """Build the immutable row identity committed by the aggregate chain."""

    return {
        "chain_schema": CHAIN_SCHEMA,
        "previous_chain_digest": previous_chain_digest,
        "database_epoch": database_epoch,
        "writer_generation": writer_generation,
        "release_id": release_id,
        "policy_bundle_hash": policy_bundle_hash,
        "event_id": row["event_id"],
        "aggregate_id": row["aggregate_id"],
        "sequence_no": row["sequence_no"],
        "idempotency_key": row["idempotency_key"],
        "occurred_at_utc_ns": row["occurred_at_utc_ns"],
        "monotonic_ns": row["monotonic_ns"],
        "event_type": row["event_type"],
        "schema_version": row["schema_version"],
        "reason_code": row["reason_code"],
        "outcome": row["outcome"],
        "stage": row["stage"],
        "severity": row["severity"],
        "environment": row["environment"],
        "logical_opportunity_id": row["logical_opportunity_id"],
        "plan_hash": row["plan_hash"],
        "attempt_generation": row["attempt_generation"],
        "attempt_id": row["attempt_id"],
        "message_hash": row["message_hash"],
        "tx_signature": row["tx_signature"],
        "jito_bundle_id": row["jito_bundle_id"],
        "provider_id": row["provider_id"],
        "venue_id": row["venue_id"],
        "payload_digest": row["payload_digest"],
        "config_checksum": row["config_checksum"],
        "redaction_version": row["redaction_version"],
        "redaction_hits": row["redaction_hits"],
        "producer_code_version": row["producer_code_version"],
        "contract_fixture_version": row["contract_fixture_version"],
    }


def compute_chain_digest(
    *,
    row: Mapping[str, Any],
    previous_chain_digest: str,
    database_epoch: str,
    writer_generation: str,
    release_id: str,
    policy_bundle_hash: str,
) -> str:
    return sha256_json(
        event_chain_envelope(
            row=row,
            previous_chain_digest=previous_chain_digest,
            database_epoch=database_epoch,
            writer_generation=writer_generation,
            release_id=release_id,
            policy_bundle_hash=policy_bundle_hash,
        )
    )


def verify_payload_columns(
    row: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> tuple[str, ...]:
    """Return denormalized columns that disagree with the canonical payload."""

    mismatches: list[str] = []
    for payload_key, column_key in PAYLOAD_COLUMN_BINDINGS:
        if payload_key not in payload:
            mismatches.append(column_key)
            continue
        if payload[payload_key] != row[column_key]:
            mismatches.append(column_key)
    return tuple(mismatches)


def row_keys(row: Any) -> set[str]:
    keys = getattr(row, "keys", None)
    if callable(keys):
        return set(keys())
    if isinstance(row, Mapping):
        return set(row)
    return set()


def verify_chain_row(
    row: Mapping[str, Any],
    *,
    expected_previous_digest: str,
) -> tuple[dict[str, object], ...]:
    """Verify one PR-184 row and return stable divergence records."""

    event_id = str(row["event_id"])
    divergences: list[dict[str, object]] = []
    try:
        payload = strict_json_loads(str(row["payload_json"]))
    except AuditIntegrityError:
        return ({"code": "PAYLOAD_JSON_INVALID", "event_id": event_id},)

    if not isinstance(payload, Mapping):
        divergences.append({"code": "PAYLOAD_NOT_OBJECT", "event_id": event_id})
        return tuple(divergences)

    actual_payload_digest = sha256_json(payload)
    if actual_payload_digest != row["payload_digest"]:
        divergences.append(
            {"code": "PAYLOAD_DIGEST_DIVERGENCE", "event_id": event_id}
        )

    mismatches = verify_payload_columns(row, payload)
    if mismatches:
        divergences.append(
            {
                "code": "DENORMALIZED_COLUMN_DIVERGENCE",
                "event_id": event_id,
                "columns": list(mismatches),
            }
        )

    keys = row_keys(row)
    chain_columns = {
        "previous_chain_digest",
        "chain_digest",
        "database_epoch",
        "writer_generation",
        "release_id",
        "policy_bundle_hash",
    }
    if not chain_columns.issubset(keys):
        divergences.append(
            {"code": "AUDIT_CHAIN_COLUMNS_MISSING", "event_id": event_id}
        )
        return tuple(divergences)

    if row["previous_chain_digest"] != expected_previous_digest:
        divergences.append(
            {
                "code": "PREVIOUS_CHAIN_DIVERGENCE",
                "event_id": event_id,
            }
        )

    expected_chain = compute_chain_digest(
        row=row,
        previous_chain_digest=str(row["previous_chain_digest"]),
        database_epoch=str(row["database_epoch"]),
        writer_generation=str(row["writer_generation"]),
        release_id=str(row["release_id"]),
        policy_bundle_hash=str(row["policy_bundle_hash"]),
    )
    if row["chain_digest"] != expected_chain:
        divergences.append(
            {"code": "CHAIN_DIGEST_DIVERGENCE", "event_id": event_id}
        )
    return tuple(divergences)


def _validate_json_value(value: object, *, depth: int = 0) -> None:
    if depth > 64:
        raise AuditIntegrityError("JSON depth exceeds audit limit")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AuditIntegrityError("non-finite audit number")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise AuditIntegrityError("audit object key must be a string")
            _validate_json_value(item, depth=depth + 1)
        return
    raise AuditIntegrityError(f"unsupported audit JSON type: {type(value).__name__}")


__all__ = [
    "AuditIntegrityError",
    "CHAIN_SCHEMA",
    "PAYLOAD_COLUMN_BINDINGS",
    "ZERO_CHAIN_DIGEST",
    "canonical_json",
    "compute_chain_digest",
    "event_chain_envelope",
    "row_keys",
    "sha256_json",
    "strict_json_loads",
    "verify_chain_row",
    "verify_payload_columns",
]
