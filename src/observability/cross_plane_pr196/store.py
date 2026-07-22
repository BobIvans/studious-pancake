"""PR-196 separate database product for verified terminal projections."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import sqlite3
import time
from typing import Iterable

from .model import (
    CanonicalOutcome,
    CrossPlaneTruthError,
    PR196_DATABASE_PRODUCT,
    PR196_METRICS_SCHEMA,
    PR196_SCHEMA,
    PlaneWatermark,
    ReconciliationResult,
    TerminalTruthState,
    TruthPlane,
    VerifiedTerminalProjection,
    canonical_json,
    conflicted_projection,
    hash_json,
    projection_from_json,
    projection_json,
)


class CrossPlaneTruthStore:
    """Verified projection isolated from the append-only observability ledger."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=5000")
        if self.path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "CrossPlaneTruthStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _migrate(self) -> None:
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS truth_product_meta(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS verified_terminal_projection(
                attempt_id TEXT NOT NULL,
                attempt_generation INTEGER NOT NULL,
                logical_opportunity_id TEXT NOT NULL,
                state TEXT NOT NULL,
                outcome TEXT,
                plan_hash TEXT NOT NULL,
                message_hash TEXT,
                lifecycle_event_id TEXT,
                settlement_evidence_digest TEXT,
                ledger_posting_id TEXT,
                release_hash TEXT,
                policy_bundle_hash TEXT,
                asset_mint TEXT,
                amount_base_units INTEGER,
                finalized_signature TEXT,
                finalized_slot INTEGER,
                source_event_id TEXT NOT NULL,
                source_sequence_no INTEGER NOT NULL,
                reason_codes_json TEXT NOT NULL,
                projection_json TEXT NOT NULL,
                projection_hash TEXT NOT NULL,
                release_ready INTEGER NOT NULL,
                updated_at_ns INTEGER NOT NULL,
                PRIMARY KEY(attempt_id, attempt_generation)
            );
            CREATE TABLE IF NOT EXISTS projection_watermark(
                plane TEXT PRIMARY KEY,
                database_epoch TEXT NOT NULL,
                sequence_no INTEGER NOT NULL,
                observed_at_ns INTEGER NOT NULL,
                updated_at_ns INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS truth_incident(
                incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
                attempt_id TEXT NOT NULL,
                attempt_generation INTEGER NOT NULL,
                code TEXT NOT NULL,
                details_hash TEXT NOT NULL,
                created_at_ns INTEGER NOT NULL
            );
            """
        )
        existing = self.db.execute(
            "SELECT value FROM truth_product_meta WHERE key='product_id'"
        ).fetchone()
        if existing is not None and str(existing[0]) != PR196_DATABASE_PRODUCT:
            raise CrossPlaneTruthError("PR196_FOREIGN_DATABASE_PRODUCT")
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO truth_product_meta(key,value) "
                "VALUES('product_id',?)",
                (PR196_DATABASE_PRODUCT,),
            )
            self.db.execute(
                "INSERT OR IGNORE INTO truth_product_meta(key,value) "
                "VALUES('schema',?)",
                (PR196_SCHEMA,),
            )

    def clear_projection(self) -> None:
        with self.db:
            self.db.execute("DELETE FROM verified_terminal_projection")
            self.db.execute("DELETE FROM projection_watermark")
            self.db.execute("DELETE FROM truth_incident")

    def get(
        self,
        attempt_id: str,
        attempt_generation: int,
    ) -> VerifiedTerminalProjection | None:
        row = self.db.execute(
            "SELECT projection_json FROM verified_terminal_projection "
            "WHERE attempt_id=? AND attempt_generation=?",
            (attempt_id, attempt_generation),
        ).fetchone()
        return projection_from_json(str(row[0])) if row else None

    def rows(self) -> list[VerifiedTerminalProjection]:
        return [
            projection_from_json(str(row[0]))
            for row in self.db.execute(
                "SELECT projection_json FROM verified_terminal_projection "
                "ORDER BY attempt_id,attempt_generation"
            )
        ]

    def watermarks(self) -> tuple[PlaneWatermark, ...]:
        return tuple(
            PlaneWatermark(
                plane=TruthPlane(str(row[0])),
                database_epoch=str(row[1]),
                sequence_no=int(row[2]),
                observed_at_ns=int(row[3]),
            )
            for row in self.db.execute(
                "SELECT plane,database_epoch,sequence_no,observed_at_ns "
                "FROM projection_watermark ORDER BY plane"
            )
        )

    def projection_checksum(self) -> str:
        payload = [asdict(row) for row in self.rows()]
        for item in payload:
            item["state"] = str(item["state"])
            item["outcome"] = str(item["outcome"]) if item["outcome"] else None
        return hash_json(payload)

    def metrics(self) -> dict[str, object]:
        rows = self.rows()
        states = {state.value: 0 for state in TerminalTruthState}
        pnl_by_asset: dict[str, int] = {}
        successes = failures = 0
        release_ready = True
        for row in rows:
            states[row.state.value] += 1
            release_ready = release_ready and row.release_ready
            if row.state in {
                TerminalTruthState.AMBIGUOUS,
                TerminalTruthState.CONFLICTED,
            }:
                release_ready = False
            if row.outcome is CanonicalOutcome.SUCCESS and row.release_ready:
                successes += 1
                assert row.asset_mint is not None
                assert row.amount_base_units is not None
                pnl_by_asset[row.asset_mint] = (
                    pnl_by_asset.get(row.asset_mint, 0) + row.amount_base_units
                )
            elif row.outcome is CanonicalOutcome.FAILURE and row.release_ready:
                failures += 1
        watermarks = {
            mark.plane.value: {
                "database_epoch": mark.database_epoch,
                "sequence_no": mark.sequence_no,
                "observed_at_ns": mark.observed_at_ns,
            }
            for mark in self.watermarks()
        }
        required = {plane.value for plane in TruthPlane}
        if rows and any(row.outcome is CanonicalOutcome.SUCCESS for row in rows):
            release_ready = release_ready and not (required - set(watermarks))
        return {
            "schema": PR196_METRICS_SCHEMA,
            "source": "verified_terminal_projection",
            "raw_event_success_counted": False,
            "verified_successes": successes,
            "verified_failures": failures,
            "states": states,
            "realized_pnl_base_units_by_asset": pnl_by_asset,
            "watermarks": watermarks,
            "projection_checksum": self.projection_checksum(),
            "release_ready": bool(rows) and release_ready,
        }

    def put(
        self,
        projection: VerifiedTerminalProjection,
        watermarks: Iterable[PlaneWatermark],
    ) -> ReconciliationResult:
        now = time.time_ns()
        existing = self.get(projection.attempt_id, projection.attempt_generation)
        replayed = (
            existing is not None
            and existing.projection_hash == projection.projection_hash
        )
        if (
            existing is not None
            and not replayed
            and existing.outcome is not None
            and projection.outcome is not None
            and existing.outcome is not projection.outcome
        ):
            projection = conflicted_projection(existing, projection)
        with self.db:
            for watermark in watermarks:
                self._advance_watermark(watermark, now)
            self.db.execute(
                """
                INSERT INTO verified_terminal_projection(
                    attempt_id,attempt_generation,logical_opportunity_id,state,outcome,
                    plan_hash,message_hash,lifecycle_event_id,settlement_evidence_digest,
                    ledger_posting_id,release_hash,policy_bundle_hash,asset_mint,
                    amount_base_units,finalized_signature,finalized_slot,source_event_id,
                    source_sequence_no,reason_codes_json,projection_json,projection_hash,
                    release_ready,updated_at_ns
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(attempt_id,attempt_generation) DO UPDATE SET
                    logical_opportunity_id=excluded.logical_opportunity_id,
                    state=excluded.state,outcome=excluded.outcome,
                    plan_hash=excluded.plan_hash,message_hash=excluded.message_hash,
                    lifecycle_event_id=excluded.lifecycle_event_id,
                    settlement_evidence_digest=excluded.settlement_evidence_digest,
                    ledger_posting_id=excluded.ledger_posting_id,
                    release_hash=excluded.release_hash,
                    policy_bundle_hash=excluded.policy_bundle_hash,
                    asset_mint=excluded.asset_mint,
                    amount_base_units=excluded.amount_base_units,
                    finalized_signature=excluded.finalized_signature,
                    finalized_slot=excluded.finalized_slot,
                    source_event_id=excluded.source_event_id,
                    source_sequence_no=excluded.source_sequence_no,
                    reason_codes_json=excluded.reason_codes_json,
                    projection_json=excluded.projection_json,
                    projection_hash=excluded.projection_hash,
                    release_ready=excluded.release_ready,
                    updated_at_ns=excluded.updated_at_ns
                """,
                self._values(projection, now),
            )
            for code in projection.reason_codes:
                if code.startswith("PR196_"):
                    self.db.execute(
                        "INSERT INTO truth_incident("
                        "attempt_id,attempt_generation,code,details_hash,created_at_ns"
                        ") VALUES(?,?,?,?,?)",
                        (
                            projection.attempt_id,
                            projection.attempt_generation,
                            code,
                            projection.projection_hash,
                            now,
                        ),
                    )
        return ReconciliationResult(
            attempt_id=projection.attempt_id,
            attempt_generation=projection.attempt_generation,
            state=projection.state,
            outcome=projection.outcome,
            reason_codes=projection.reason_codes,
            projection_hash=projection.projection_hash,
            reconciled_sequence=projection.source_sequence_no,
            release_ready=projection.release_ready,
            replayed=replayed,
        )

    def _advance_watermark(self, watermark: PlaneWatermark, now: int) -> None:
        current = self.db.execute(
            "SELECT database_epoch,sequence_no FROM projection_watermark "
            "WHERE plane=?",
            (watermark.plane.value,),
        ).fetchone()
        if current is not None:
            if str(current[0]) != watermark.database_epoch:
                raise CrossPlaneTruthError("PR196_WATERMARK_EPOCH_CHANGED")
            if int(current[1]) > watermark.sequence_no:
                raise CrossPlaneTruthError("PR196_WATERMARK_REGRESSION")
        self.db.execute(
            """
            INSERT INTO projection_watermark(
                plane,database_epoch,sequence_no,observed_at_ns,updated_at_ns
            ) VALUES(?,?,?,?,?)
            ON CONFLICT(plane) DO UPDATE SET
                sequence_no=excluded.sequence_no,
                observed_at_ns=excluded.observed_at_ns,
                updated_at_ns=excluded.updated_at_ns
            """,
            (
                watermark.plane.value,
                watermark.database_epoch,
                watermark.sequence_no,
                watermark.observed_at_ns,
                now,
            ),
        )

    @staticmethod
    def _values(
        projection: VerifiedTerminalProjection,
        now: int,
    ) -> tuple[object, ...]:
        return (
            projection.attempt_id,
            projection.attempt_generation,
            projection.logical_opportunity_id,
            projection.state.value,
            projection.outcome.value if projection.outcome else None,
            projection.plan_hash,
            projection.message_hash,
            projection.lifecycle_event_id,
            projection.settlement_evidence_digest,
            projection.ledger_posting_id,
            projection.release_hash,
            projection.policy_bundle_hash,
            projection.asset_mint,
            projection.amount_base_units,
            projection.finalized_signature,
            projection.finalized_slot,
            projection.source_event_id,
            projection.source_sequence_no,
            canonical_json(list(projection.reason_codes)),
            projection_json(projection),
            projection.projection_hash,
            int(projection.release_ready),
            now,
        )
