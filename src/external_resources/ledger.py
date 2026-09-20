"""Durable mutation intent, terminal readback, and resource binding ledger."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterator, Mapping

from .models import PlanOperation, SealedPlan

LEDGER_SCHEMA = "mpr-rp-04.mutation-ledger.v1"


class MutationConflict(RuntimeError):
    """A plan or operation conflicts with already committed durable state."""


class MutationLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS plans (
                    plan_sha256 TEXT PRIMARY KEY,
                    desired_state_sha256 TEXT NOT NULL,
                    inventory_sha256 TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    created_unix_ns INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mutation_intents (
                    operation_id TEXT PRIMARY KEY,
                    plan_sha256 TEXT NOT NULL REFERENCES plans(plan_sha256),
                    resource_key TEXT NOT NULL,
                    operation_kind TEXT NOT NULL,
                    expected_remote_fingerprint TEXT,
                    state TEXT NOT NULL,
                    result_json TEXT,
                    created_unix_ns INTEGER NOT NULL,
                    updated_unix_ns INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS resource_bindings (
                    resource_key TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    resource_kind TEXT NOT NULL,
                    provider_resource_id TEXT NOT NULL,
                    remote_fingerprint TEXT NOT NULL,
                    updated_unix_ns INTEGER NOT NULL
                );
                """
            )

    def persist_plan(self, plan: SealedPlan) -> None:
        payload = json.dumps(plan.to_dict(), sort_keys=True, separators=(",", ":"))
        now = time.time_ns()
        with self._connect() as db:
            existing = db.execute(
                "SELECT plan_json FROM plans WHERE plan_sha256 = ?",
                (plan.plan_sha256,),
            ).fetchone()
            if existing is not None and existing["plan_json"] != payload:
                raise MutationConflict("plan digest collision in mutation ledger")
            db.execute(
                """
                INSERT OR IGNORE INTO plans(
                    plan_sha256, desired_state_sha256, inventory_sha256,
                    plan_json, created_unix_ns
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    plan.plan_sha256,
                    plan.desired_state_sha256,
                    plan.inventory_sha256,
                    payload,
                    now,
                ),
            )

    def persist_intent(
        self, plan: SealedPlan, operation: PlanOperation
    ) -> Mapping[str, Any] | None:
        now = time.time_ns()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                existing = db.execute(
                    "SELECT * FROM mutation_intents WHERE operation_id = ?",
                    (operation.operation_id,),
                ).fetchone()
                if existing is not None:
                    if existing["plan_sha256"] != plan.plan_sha256:
                        raise MutationConflict(
                            "operation id is already bound to another sealed plan"
                        )
                    db.execute("COMMIT")
                    if existing["state"] == "terminal" and existing["result_json"]:
                        return json.loads(existing["result_json"])
                    return None
                db.execute(
                    """
                    INSERT INTO mutation_intents(
                        operation_id, plan_sha256, resource_key, operation_kind,
                        expected_remote_fingerprint, state, result_json,
                        created_unix_ns, updated_unix_ns
                    ) VALUES (?, ?, ?, ?, ?, 'intent', NULL, ?, ?)
                    """,
                    (
                        operation.operation_id,
                        plan.plan_sha256,
                        operation.resource_key,
                        operation.kind.value,
                        operation.expected_remote_fingerprint,
                        now,
                        now,
                    ),
                )
                db.execute("COMMIT")
                return None
            except Exception:
                db.execute("ROLLBACK")
                raise

    def terminal_result(self, operation_id: str) -> Mapping[str, Any] | None:
        """Return the durable terminal result for an operation, when present."""

        with self._connect() as db:
            row = db.execute(
                "SELECT state, result_json FROM mutation_intents "
                "WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        if row is None or row["state"] != "terminal" or not row["result_json"]:
            return None
        return json.loads(row["result_json"])

    def record_terminal(
        self,
        operation: PlanOperation,
        result: Mapping[str, Any],
        *,
        provider_resource_id: str | None = None,
        remote_fingerprint: str | None = None,
    ) -> None:
        now = time.time_ns()
        payload = json.dumps(dict(result), sort_keys=True, separators=(",", ":"))
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                updated = db.execute(
                    """
                    UPDATE mutation_intents
                    SET state='terminal', result_json=?, updated_unix_ns=?
                    WHERE operation_id=?
                    """,
                    (payload, now, operation.operation_id),
                ).rowcount
                if updated != 1:
                    raise MutationConflict("terminal result has no durable intent")
                if provider_resource_id and remote_fingerprint:
                    db.execute(
                        """
                        INSERT INTO resource_bindings(
                            resource_key, provider, resource_kind,
                            provider_resource_id, remote_fingerprint, updated_unix_ns
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(resource_key) DO UPDATE SET
                            provider=excluded.provider,
                            resource_kind=excluded.resource_kind,
                            provider_resource_id=excluded.provider_resource_id,
                            remote_fingerprint=excluded.remote_fingerprint,
                            updated_unix_ns=excluded.updated_unix_ns
                        """,
                        (
                            operation.resource_key,
                            operation.provider,
                            operation.resource_kind,
                            provider_resource_id,
                            remote_fingerprint,
                            now,
                        ),
                    )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise

    def remove_binding(self, resource_key: str) -> None:
        with self._connect() as db:
            db.execute(
                "DELETE FROM resource_bindings WHERE resource_key = ?",
                (resource_key,),
            )

    def bindings(self) -> tuple[dict[str, Any], ...]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM resource_bindings ORDER BY resource_key"
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def status(self) -> dict[str, Any]:
        with self._connect() as db:
            plans = db.execute(
                "SELECT COUNT(*) AS count FROM plans"
            ).fetchone()["count"]
            intents = db.execute(
                "SELECT state, COUNT(*) AS count FROM mutation_intents GROUP BY state"
            ).fetchall()
        return {
            "schema_version": LEDGER_SCHEMA,
            "path": str(self.path),
            "plans": int(plans),
            "intents": {str(row["state"]): int(row["count"]) for row in intents},
            "bindings": list(self.bindings()),
        }
