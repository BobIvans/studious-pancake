"""PR-122 deterministic opportunity identity and persistent dedup primitives."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from typing import Any

IDENTITY_SCHEMA_VERSION = "pr122.logical-opportunity-identity.v1"
LEDGER_SCHEMA_VERSION = "pr122.persistent-opportunity-dedup.v1"
LOGICAL_ID_PREFIX = "lop_"
MATERIAL_INVALIDATION_REASONS: frozenset[str] = frozenset(
    {
        "quote_hash_changed",
        "route_hash_changed",
        "state_slot_changed",
        "policy_version_changed",
        "amount_changed",
        "manual_operator_reset",
    }
)


class OpportunityIdentityError(ValueError):
    """Raised when identity or dedup inputs are not safe."""


@dataclass(frozen=True, slots=True)
class LogicalOpportunityIdentity:
    logical_opportunity_id: str
    evidence_hash: str
    schema_version: str
    identity_payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "logical_opportunity_id": self.logical_opportunity_id,
            "evidence_hash": self.evidence_hash,
            "identity_payload": dict(self.identity_payload),
        }


@dataclass(frozen=True, slots=True)
class DedupAdmission:
    admitted: bool
    logical_opportunity_id: str
    reason_code: str
    first_seen_ns: int | None
    last_seen_ns: int | None
    attempts_seen: int


def build_logical_opportunity_identity(
    *,
    strategy_name: str,
    opportunity_type: str,
    pair_id: str,
    exact_amount_base_units: int,
    first_leg: Mapping[str, Any],
    second_leg: Mapping[str, Any],
    policy_version: str,
    slot_bucket: int | None = None,
) -> LogicalOpportunityIdentity:
    payload = {
        "schema_version": IDENTITY_SCHEMA_VERSION,
        "strategy_name": _required_text(strategy_name, "strategy_name"),
        "opportunity_type": _required_text(opportunity_type, "opportunity_type"),
        "pair_id": _required_text(pair_id, "pair_id"),
        "exact_amount_base_units": _positive_int(
            exact_amount_base_units,
            "exact_amount_base_units",
        ),
        "policy_version": _required_text(policy_version, "policy_version"),
        "slot_bucket": _optional_slot(slot_bucket),
        "first_leg": _route_leg_payload(first_leg, leg_name="first"),
        "second_leg": _route_leg_payload(second_leg, leg_name="second"),
    }
    evidence_hash = canonical_sha256(payload)
    return LogicalOpportunityIdentity(
        logical_opportunity_id=f"{LOGICAL_ID_PREFIX}{evidence_hash}",
        evidence_hash=evidence_hash,
        schema_version=IDENTITY_SCHEMA_VERSION,
        identity_payload=payload,
    )


def canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _jsonable(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class PersistentOpportunityDedupLedger:
    """SQLite-backed logical opportunity dedup ledger."""

    def __init__(
        self,
        path: str | Path,
        *,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self.path = str(path)
        self.clock_ns = clock_ns
        self.db: sqlite3.Connection = sqlite3.connect(self.path, isolation_level=None)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA trusted_schema=OFF")
        self._migrate()

    def __enter__(self) -> PersistentOpportunityDedupLedger:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.db.close()

    def admit(
        self,
        identity: LogicalOpportunityIdentity,
        *,
        strategy_name: str,
        pair_id: str,
        exact_amount_base_units: int,
        policy_version: str,
        invalidation_reason: str | None = None,
    ) -> DedupAdmission:
        if invalidation_reason is not None:
            _material_invalidation_reason(invalidation_reason)
        now = int(self.clock_ns())
        with self.db:
            row = self.db.execute(
                "SELECT evidence_hash, first_seen_ns, attempts_seen "
                "FROM opportunity_identity_dedup WHERE logical_opportunity_id=?",
                (identity.logical_opportunity_id,),
            ).fetchone()
            if row is None:
                self.db.execute(
                    "INSERT INTO opportunity_identity_dedup "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        identity.logical_opportunity_id,
                        identity.evidence_hash,
                        _required_text(strategy_name, "strategy_name"),
                        _required_text(pair_id, "pair_id"),
                        _positive_int(
                            exact_amount_base_units,
                            "exact_amount_base_units",
                        ),
                        _required_text(policy_version, "policy_version"),
                        now,
                        now,
                        1,
                        "admitted",
                        invalidation_reason,
                    ),
                )
                return DedupAdmission(
                    True,
                    identity.logical_opportunity_id,
                    "admitted_new_logical_opportunity",
                    now,
                    now,
                    1,
                )
            evidence_hash, first_seen_ns_raw, attempts_seen_raw = tuple(row)
            if str(evidence_hash) != identity.evidence_hash:
                raise OpportunityIdentityError("identity/evidence hash mismatch")
            attempts_seen = int(attempts_seen_raw) + 1
            self.db.execute(
                "UPDATE opportunity_identity_dedup SET attempts_seen=?, last_seen_ns=? "
                "WHERE logical_opportunity_id=?",
                (attempts_seen, now, identity.logical_opportunity_id),
            )
            if invalidation_reason is None:
                return DedupAdmission(
                    False,
                    identity.logical_opportunity_id,
                    "duplicate_logical_opportunity_blocked",
                    int(first_seen_ns_raw),
                    now,
                    attempts_seen,
                )
            return DedupAdmission(
                True,
                identity.logical_opportunity_id,
                f"admitted_after_material_invalidation:{invalidation_reason}",
                int(first_seen_ns_raw),
                now,
                attempts_seen,
            )

    def _migrate(self) -> None:
        with self.db:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS opportunity_identity_dedup(
                    logical_opportunity_id TEXT PRIMARY KEY,
                    evidence_hash TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    pair_id TEXT NOT NULL,
                    exact_amount_base_units INTEGER NOT NULL,
                    policy_version TEXT NOT NULL,
                    first_seen_ns INTEGER NOT NULL,
                    last_seen_ns INTEGER NOT NULL,
                    attempts_seen INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL,
                    invalidation_reason TEXT
                );
                """
            )
            self.db.execute("PRAGMA user_version=122")


def _route_leg_payload(
    leg: Mapping[str, Any],
    *,
    leg_name: str,
) -> dict[str, Any]:
    required = (
        "provider",
        "input_mint",
        "output_mint",
        "slot",
        "request_fingerprint",
        "response_hash",
        "in_amount",
        "out_amount",
    )
    missing = [field for field in required if _missing(leg.get(field))]
    if missing:
        raise OpportunityIdentityError(
            f"{leg_name} leg missing identity fields: {','.join(missing)}"
        )
    return {
        "provider": _required_text(leg["provider"], f"{leg_name}.provider"),
        "input_mint": _required_text(leg["input_mint"], f"{leg_name}.input_mint"),
        "output_mint": _required_text(
            leg["output_mint"],
            f"{leg_name}.output_mint",
        ),
        "slot": _non_negative_int(leg["slot"], f"{leg_name}.slot"),
        "request_fingerprint": _required_text(
            leg["request_fingerprint"],
            f"{leg_name}.request_fingerprint",
        ),
        "response_hash": _required_text(
            leg["response_hash"],
            f"{leg_name}.response_hash",
        ),
        "in_amount": _positive_int(leg["in_amount"], f"{leg_name}.in_amount"),
        "out_amount": _non_negative_int(leg["out_amount"], f"{leg_name}.out_amount"),
        "quote_id": leg.get("quote_id"),
        "source": leg.get("source"),
        "commitment": leg.get("commitment"),
        "provider_timestamp": leg.get("provider_timestamp"),
        "correlation_labels": _labels(leg.get("correlation_labels", ())),
    }


def _labels(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return sorted(str(item) for item in value)
    return []


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _required_text(value: object, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise OpportunityIdentityError(f"{field_name} is required")
    return text


def _positive_int(value: object, field_name: str) -> int:
    number = _non_negative_int(value, field_name)
    if number <= 0:
        raise OpportunityIdentityError(f"{field_name} must be positive")
    return number


def _non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OpportunityIdentityError(f"{field_name} must be a non-negative int")
    return value


def _optional_slot(value: int | None) -> int | None:
    if value is None:
        return None
    return _non_negative_int(value, "slot_bucket")


def _material_invalidation_reason(value: str) -> str:
    reason = _required_text(value, "invalidation_reason")
    if reason not in MATERIAL_INVALIDATION_REASONS:
        raise OpportunityIdentityError("unsupported invalidation reason")
    return reason


def _missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())
