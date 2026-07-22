"""PR-191 immutable terminal accounting and split delivery state.

The compatibility cutover keeps ``live_control`` public imports stable while
making terminal outcome replay exactly-once by immutable operation identity.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
import re
import sqlite3
import time
from typing import Any, Mapping

_legacy = importlib.import_module("src.execution.live_control")
_ORIGINAL_STORE = _legacy.LiveControlStore
_ORIGINAL_RECORD_ACTUAL_OUTCOME = _legacy.record_actual_outcome

PR191_ACCOUNTING_SCHEMA = "pr191.terminal-accounting.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class TerminalAccountingConflict(RuntimeError):
    """The same terminal identity was presented with different accounting data."""


@dataclass(frozen=True, slots=True)
class TerminalOutcomeIdentity:
    attempt_id: str
    attempt_generation: int
    asset: str
    finalized_signature: str
    settlement_evidence_hash: str
    accounting_operation: str

    def __post_init__(self) -> None:
        if not self.attempt_id.strip() or not self.asset.strip():
            raise ValueError("attempt_id and asset are required")
        if self.attempt_generation < 0:
            raise ValueError("attempt_generation must be non-negative")
        if not self.finalized_signature.strip():
            raise ValueError("finalized_signature is required")
        if not _SHA256_RE.fullmatch(self.settlement_evidence_hash):
            raise ValueError("settlement_evidence_hash must be lowercase sha256")
        if not self.accounting_operation.strip():
            raise ValueError("accounting_operation is required")

    @property
    def terminal_id(self) -> str:
        return _sha256_json(
            {
                "domain": PR191_ACCOUNTING_SCHEMA,
                "attempt_id": self.attempt_id,
                "attempt_generation": self.attempt_generation,
                "asset": self.asset,
                "finalized_signature": self.finalized_signature,
                "settlement_evidence_hash": self.settlement_evidence_hash,
                "accounting_operation": self.accounting_operation,
            }
        )


@dataclass(frozen=True, slots=True)
class TerminalOutcomeCommit:
    outcome_id: int
    terminal_id: str
    outbox_id: str
    outcome_hash: str
    replayed: bool
    supersedes_outcome_id: int | None = None


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in db.execute(f"PRAGMA table_info({table})")}


def _safe_provenance(provenance: Mapping[str, Any]) -> dict[str, Any]:
    redacted = _legacy._redact(dict(provenance))
    if not isinstance(redacted, dict):
        raise ValueError("provenance must remain a mapping after redaction")
    return redacted


class ImmutableLiveControlStore(_ORIGINAL_STORE):
    """PR-191 extension of the existing live-control SQLite authority."""

    def migrate(self) -> None:
        super().migrate()
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=5000")
        columns = _columns(self.db, "live_actual_outcomes")
        additions = {
            "terminal_id": "TEXT",
            "attempt_generation": "INTEGER NOT NULL DEFAULT 0",
            "finalized_signature": "TEXT",
            "settlement_evidence_hash": "TEXT",
            "accounting_operation": "TEXT NOT NULL DEFAULT 'legacy'",
            "outcome_hash": "TEXT",
            "supersedes_outcome_id": "INTEGER",
            "conflict_state": "TEXT NOT NULL DEFAULT 'clear'",
            "schema_version": f"TEXT NOT NULL DEFAULT '{PR191_ACCOUNTING_SCHEMA}'",
        }
        for name, ddl in additions.items():
            if name not in columns:
                self.db.execute(
                    f"ALTER TABLE live_actual_outcomes ADD COLUMN {name} {ddl}"
                )

        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS live_accounting_conflicts (
                conflict_id INTEGER PRIMARY KEY AUTOINCREMENT,
                terminal_id TEXT NOT NULL,
                existing_outcome_id INTEGER NOT NULL,
                existing_outcome_hash TEXT NOT NULL,
                conflicting_outcome_hash TEXT NOT NULL,
                evidence TEXT NOT NULL,
                created_at REAL NOT NULL,
                resolved_at REAL,
                resolution_outcome_id INTEGER,
                FOREIGN KEY(existing_outcome_id)
                    REFERENCES live_actual_outcomes(id) ON DELETE RESTRICT,
                FOREIGN KEY(resolution_outcome_id)
                    REFERENCES live_actual_outcomes(id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS live_terminal_outbox_event (
                outbox_id TEXT PRIMARY KEY,
                outcome_id INTEGER NOT NULL UNIQUE,
                terminal_id TEXT NOT NULL UNIQUE,
                payload_hash TEXT NOT NULL CHECK(length(payload_hash)=64),
                kind TEXT NOT NULL,
                created_at REAL NOT NULL,
                schema_version TEXT NOT NULL,
                FOREIGN KEY(outcome_id)
                    REFERENCES live_actual_outcomes(id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS live_terminal_outbox_delivery (
                outbox_id TEXT PRIMARY KEY,
                state TEXT NOT NULL CHECK(state IN (
                    'pending','leased','sent','acknowledged',
                    'failed-retryable','dead-letter','superseded'
                )),
                owner TEXT,
                fencing_token INTEGER NOT NULL DEFAULT 0,
                lease_expires_at REAL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                next_retry_at REAL,
                last_error_code TEXT,
                acknowledged_at REAL,
                updated_at REAL NOT NULL,
                FOREIGN KEY(outbox_id)
                    REFERENCES live_terminal_outbox_event(outbox_id)
                    ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS live_terminal_outbox_attempt (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                outbox_id TEXT NOT NULL,
                owner TEXT NOT NULL,
                fencing_token INTEGER NOT NULL,
                result_state TEXT NOT NULL,
                error_code TEXT,
                created_at REAL NOT NULL,
                FOREIGN KEY(outbox_id)
                    REFERENCES live_terminal_outbox_event(outbox_id)
                    ON DELETE RESTRICT
            );
            """
        )
        self._backfill_legacy_outcomes()
        self.db.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_pr191_terminal_identity
            ON live_actual_outcomes(terminal_id)
            """
        )
        self.db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_pr191_terminal_delivery
            ON live_terminal_outbox_delivery(state,next_retry_at)
            """
        )

    def _backfill_legacy_outcomes(self) -> None:
        rows = self.db.execute(
            """
            SELECT * FROM live_actual_outcomes
            WHERE terminal_id IS NULL OR outcome_hash IS NULL
               OR finalized_signature IS NULL
               OR settlement_evidence_hash IS NULL
            """
        ).fetchall()
        for row in rows:
            provenance = json.loads(row["provenance"])
            settlement_hash = _sha256_json(
                {
                    "legacy_row_id": row["id"],
                    "provenance": provenance,
                    "reconciled_at": row["reconciled_at"],
                }
            )
            identity = TerminalOutcomeIdentity(
                attempt_id=row["attempt_id"],
                attempt_generation=int(row["attempt_generation"] or 0),
                asset=row["asset"],
                finalized_signature=f"legacy-row:{row['id']}",
                settlement_evidence_hash=settlement_hash,
                accounting_operation=str(row["accounting_operation"] or "legacy"),
            )
            payload = {
                "schema_version": PR191_ACCOUNTING_SCHEMA,
                "terminal_id": identity.terminal_id,
                "config_hash": row["config_hash"],
                "actual_delta": row["actual_delta"],
                "simulated_delta": row["simulated_delta"],
                "divergence_abs": row["divergence_abs"],
                "tolerance": row["tolerance"],
                "provenance": provenance,
                "reconciled_at": row["reconciled_at"],
                "legacy_backfill": True,
            }
            self.db.execute(
                """
                UPDATE live_actual_outcomes
                SET terminal_id=?,attempt_generation=?,finalized_signature=?,
                    settlement_evidence_hash=?,accounting_operation=?,
                    outcome_hash=?,schema_version=?
                WHERE id=?
                """,
                (
                    identity.terminal_id,
                    identity.attempt_generation,
                    identity.finalized_signature,
                    identity.settlement_evidence_hash,
                    identity.accounting_operation,
                    _sha256_json(payload),
                    PR191_ACCOUNTING_SCHEMA,
                    row["id"],
                ),
            )

    def record_actual_outcome(self, **kwargs: Any) -> TerminalOutcomeCommit:
        return record_actual_outcome(self, **kwargs)

    def acknowledge_terminal_outbox(
        self, outbox_id: str, *, acknowledged_at: float | None = None
    ) -> bool:
        when = time.time() if acknowledged_at is None else acknowledged_at
        with self.db:
            changed = self.db.execute(
                """
                UPDATE live_terminal_outbox_delivery
                SET state='acknowledged',owner=NULL,lease_expires_at=NULL,
                    acknowledged_at=COALESCE(acknowledged_at,?),updated_at=?
                WHERE outbox_id=? AND state!='acknowledged'
                """,
                (when, when, outbox_id),
            ).rowcount
        return bool(changed)


def _resolved_identity(
    *,
    attempt_id: str,
    attempt_generation: int,
    asset: str,
    finalized_signature: str | None,
    settlement_evidence_hash: str | None,
    accounting_operation: str,
    provenance: Mapping[str, Any],
) -> TerminalOutcomeIdentity:
    signature = (
        finalized_signature
        or str(provenance.get("finalized_signature") or "")
        or str(provenance.get("signature") or "")
        or f"legacy:{attempt_id}:{attempt_generation}"
    )
    evidence_hash = (
        settlement_evidence_hash
        or str(provenance.get("settlement_evidence_hash") or "")
    )
    if not _SHA256_RE.fullmatch(evidence_hash):
        evidence_hash = _sha256_json(
            {
                "domain": "pr191.legacy-settlement-evidence",
                "attempt_id": attempt_id,
                "attempt_generation": attempt_generation,
                "asset": asset,
                "provenance": _safe_provenance(provenance),
            }
        )
    return TerminalOutcomeIdentity(
        attempt_id=attempt_id,
        attempt_generation=attempt_generation,
        asset=asset,
        finalized_signature=signature,
        settlement_evidence_hash=evidence_hash,
        accounting_operation=accounting_operation,
    )


def record_actual_outcome(
    store: Any,
    *,
    attempt_id: str,
    config_hash: str,
    asset: str,
    actual_delta: int,
    simulated_delta: int | None,
    tolerance: int,
    provenance: dict[str, Any],
    attempt_generation: int = 0,
    finalized_signature: str | None = None,
    settlement_evidence_hash: str | None = None,
    accounting_operation: str = "actual_outcome",
    correction_of: int | None = None,
) -> TerminalOutcomeCommit:
    """Post one immutable terminal outcome and one immutable outbox event.

    Exact replay returns the original posting. A different payload under the
    same terminal identity records a durable conflict, freezes the reservation,
    latches the control plane and raises ``TerminalAccountingConflict``.
    """
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")
    if not isinstance(actual_delta, int) or (
        simulated_delta is not None and not isinstance(simulated_delta, int)
    ):
        raise TypeError("actual and simulated deltas must be integers")
    if not isinstance(store, _ORIGINAL_STORE):
        raise TypeError("store must be a LiveControlStore")

    store.migrate()
    safe_provenance = _safe_provenance(provenance)
    identity = _resolved_identity(
        attempt_id=attempt_id,
        attempt_generation=attempt_generation,
        asset=asset,
        finalized_signature=finalized_signature,
        settlement_evidence_hash=settlement_evidence_hash,
        accounting_operation=accounting_operation,
        provenance=safe_provenance,
    )
    divergence = (
        None if simulated_delta is None else abs(actual_delta - simulated_delta)
    )
    reconciled_at = time.time()
    immutable_payload = {
        "schema_version": PR191_ACCOUNTING_SCHEMA,
        "terminal_id": identity.terminal_id,
        "attempt_id": identity.attempt_id,
        "attempt_generation": identity.attempt_generation,
        "config_hash": config_hash,
        "asset": identity.asset,
        "finalized_signature": identity.finalized_signature,
        "settlement_evidence_hash": identity.settlement_evidence_hash,
        "accounting_operation": identity.accounting_operation,
        "actual_delta": actual_delta,
        "simulated_delta": simulated_delta,
        "divergence_abs": divergence,
        "tolerance": tolerance,
        "provenance": safe_provenance,
        "supersedes_outcome_id": correction_of,
    }
    outcome_hash = _sha256_json(immutable_payload)
    outbox_id = _sha256_json(
        {
            "domain": "pr191.terminal-outbox",
            "terminal_id": identity.terminal_id,
            "outcome_hash": outcome_hash,
        }
    )

    db = store.db
    db.execute("BEGIN IMMEDIATE")
    try:
        existing = db.execute(
            """
            SELECT id,outcome_hash,supersedes_outcome_id
            FROM live_actual_outcomes WHERE terminal_id=?
            """,
            (identity.terminal_id,),
        ).fetchone()
        if existing is not None:
            if existing["outcome_hash"] == outcome_hash:
                event = db.execute(
                    """
                    SELECT outbox_id FROM live_terminal_outbox_event
                    WHERE outcome_id=?
                    """,
                    (existing["id"],),
                ).fetchone()
                db.commit()
                return TerminalOutcomeCommit(
                    outcome_id=int(existing["id"]),
                    terminal_id=identity.terminal_id,
                    outbox_id=event["outbox_id"] if event else outbox_id,
                    outcome_hash=outcome_hash,
                    replayed=True,
                    supersedes_outcome_id=existing["supersedes_outcome_id"],
                )

            evidence = _canonical_json(
                {
                    "attempt_id": attempt_id,
                    "attempt_generation": attempt_generation,
                    "asset": asset,
                    "accounting_operation": accounting_operation,
                }
            )
            db.execute(
                """
                INSERT INTO live_accounting_conflicts(
                    terminal_id,existing_outcome_id,existing_outcome_hash,
                    conflicting_outcome_hash,evidence,created_at
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    identity.terminal_id,
                    existing["id"],
                    existing["outcome_hash"],
                    outcome_hash,
                    evidence,
                    reconciled_at,
                ),
            )
            db.execute(
                """
                UPDATE live_actual_outcomes SET conflict_state='frozen'
                WHERE id=?
                """,
                (existing["id"],),
            )
            db.execute(
                """
                UPDATE live_budget_reservations SET status='accounting_conflict'
                WHERE attempt_id=? AND status IN ('reserved','settled')
                """,
                (attempt_id,),
            )
            db.execute(
                """
                INSERT INTO live_latches(active,reason,evidence,triggered_at)
                VALUES(1,?,?,?)
                """,
                (
                    _legacy.LatchReason.JOURNAL_INVARIANT_VIOLATION.value,
                    evidence,
                    reconciled_at,
                ),
            )
            db.commit()
            raise TerminalAccountingConflict("PR191_TERMINAL_ACCOUNTING_CONFLICT")

        if correction_of is not None:
            correction_target = db.execute(
                "SELECT id FROM live_actual_outcomes WHERE id=?",
                (correction_of,),
            ).fetchone()
            if correction_target is None:
                raise TerminalAccountingConflict("PR191_CORRECTION_TARGET_MISSING")

        cursor = db.execute(
            """
            INSERT INTO live_actual_outcomes(
                attempt_id,config_hash,asset,actual_delta,simulated_delta,
                divergence_abs,tolerance,reconciled_at,provenance,terminal_id,
                attempt_generation,finalized_signature,settlement_evidence_hash,
                accounting_operation,outcome_hash,supersedes_outcome_id,
                conflict_state,schema_version
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                attempt_id,
                config_hash,
                asset,
                actual_delta,
                simulated_delta,
                divergence,
                tolerance,
                reconciled_at,
                _canonical_json(safe_provenance),
                identity.terminal_id,
                attempt_generation,
                identity.finalized_signature,
                identity.settlement_evidence_hash,
                accounting_operation,
                outcome_hash,
                correction_of,
                "clear",
                PR191_ACCOUNTING_SCHEMA,
            ),
        )
        outcome_id = int(cursor.lastrowid)
        db.execute(
            """
            UPDATE live_budget_reservations SET status='settled'
            WHERE attempt_id=? AND status='reserved'
            """,
            (attempt_id,),
        )
        db.execute(
            """
            INSERT INTO live_terminal_outbox_event(
                outbox_id,outcome_id,terminal_id,payload_hash,kind,
                created_at,schema_version
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                outbox_id,
                outcome_id,
                identity.terminal_id,
                outcome_hash,
                "terminal_financial_outcome",
                reconciled_at,
                PR191_ACCOUNTING_SCHEMA,
            ),
        )
        db.execute(
            """
            INSERT INTO live_terminal_outbox_delivery(
                outbox_id,state,updated_at
            ) VALUES(?,'pending',?)
            """,
            (outbox_id, reconciled_at),
        )

        if actual_delta < 0 and abs(actual_delta) > tolerance:
            db.execute(
                """
                INSERT INTO live_latches(active,reason,evidence,triggered_at)
                VALUES(1,?,?,?)
                """,
                (
                    _legacy.LatchReason.PER_TRADE_CAP_BREACH.value,
                    _canonical_json(
                        {
                            "attempt_id": attempt_id,
                            "asset": asset,
                            "actual_delta": actual_delta,
                        }
                    ),
                    reconciled_at,
                ),
            )
        if divergence is not None and divergence > tolerance:
            db.execute(
                """
                INSERT INTO live_latches(active,reason,evidence,triggered_at)
                VALUES(1,?,?,?)
                """,
                (
                    _legacy.LatchReason.SIMULATION_LIVE_DIVERGENCE.value,
                    _canonical_json(
                        {
                            "attempt_id": attempt_id,
                            "asset": asset,
                            "divergence_abs": divergence,
                            "tolerance": tolerance,
                        }
                    ),
                    reconciled_at,
                ),
            )
        db.commit()
        return TerminalOutcomeCommit(
            outcome_id=outcome_id,
            terminal_id=identity.terminal_id,
            outbox_id=outbox_id,
            outcome_hash=outcome_hash,
            replayed=False,
            supersedes_outcome_id=correction_of,
        )
    except Exception:
        if db.in_transaction:
            db.rollback()
        raise


def install_pr191_accounting_cutover() -> None:
    """Replace active ``live_control`` symbols with PR-191 implementations."""
    if _legacy.LiveControlStore is not ImmutableLiveControlStore:
        _legacy.LegacyLiveControlStore = _ORIGINAL_STORE
        _legacy.LegacyRecordActualOutcome = _ORIGINAL_RECORD_ACTUAL_OUTCOME
        _legacy.LiveControlStore = ImmutableLiveControlStore
        _legacy.record_actual_outcome = record_actual_outcome


install_pr191_accounting_cutover()


__all__ = [
    "ImmutableLiveControlStore",
    "PR191_ACCOUNTING_SCHEMA",
    "TerminalAccountingConflict",
    "TerminalOutcomeCommit",
    "TerminalOutcomeIdentity",
    "install_pr191_accounting_cutover",
    "record_actual_outcome",
]
