from __future__ import annotations
import asyncio, json, sqlite3, time
from pathlib import Path
from typing import Any
from .models import ExecutionJournalEntry, ExecutionState, JournalAttemptRecord, BlockhashContext

MIGRATION_VERSION = 14

class SQLiteAttemptJournal:
    """Crash-safe PR-014 attempt journal backed by SQLite WAL."""
    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 2500):
        self.path = str(path)
        self._lock = asyncio.Lock()
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=busy_timeout_ms/1000, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.migrate()

    def migrate(self) -> None:
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts(
          id INTEGER PRIMARY KEY,
          logical_opportunity_id TEXT NOT NULL,
          plan_hash TEXT NOT NULL,
          attempt_generation INTEGER NOT NULL,
          state TEXT NOT NULL,
          revision INTEGER NOT NULL DEFAULT 0,
          message_digest TEXT, signed_transaction_digest TEXT, transaction_signatures TEXT NOT NULL DEFAULT '[]',
          blockhash TEXT, last_valid_block_height INTEGER, source_slot INTEGER, min_context_slot INTEGER, commitment TEXT,
          compiler_hash TEXT, simulation_hash TEXT, route_provider_snapshot_hash TEXT, monitored_account_snapshot_hash TEXT,
          transport TEXT, submission_intent_at REAL, claim_owner TEXT, lease_expires_at REAL,
          rpc_returned_signatures TEXT NOT NULL DEFAULT '[]', jito_bundle_id TEXT, jito_headers TEXT NOT NULL DEFAULT '{}',
          status_observations TEXT NOT NULL DEFAULT '[]', provider_trace_ids TEXT NOT NULL DEFAULT '[]',
          tip_owner TEXT, tip_account TEXT, tip_instruction_count INTEGER NOT NULL DEFAULT 0, tip_amount_lamports INTEGER, tip_amount_hash TEXT,
          pre_snapshot_ref TEXT, post_snapshot_ref TEXT, expected_repayment_facts TEXT, observed_reconciliation_slot INTEGER,
          token_native_deltas TEXT, reconciliation_outcome TEXT,
          created_at REAL NOT NULL, updated_at REAL NOT NULL,
          UNIQUE(logical_opportunity_id, plan_hash, attempt_generation)
        );
        CREATE TABLE IF NOT EXISTS attempt_events(
          id INTEGER PRIMARY KEY, attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE RESTRICT,
          from_state TEXT, to_state TEXT NOT NULL, revision INTEGER NOT NULL, reason_code TEXT, error TEXT, evidence TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL
        );
        """)
        self.db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?,?)", (MIGRATION_VERSION, time.time()))

    async def create_attempt(self, logical_opportunity_id: str, plan_hash: str, attempt_generation: int, *, state: ExecutionState = ExecutionState.PLANNED, **fields: Any) -> JournalAttemptRecord:
        async with self._lock:
            now=time.time()
            cols={"logical_opportunity_id":logical_opportunity_id,"plan_hash":plan_hash,"attempt_generation":attempt_generation,"state":state.value,"created_at":now,"updated_at":now, **fields}
            keys=','.join(cols); qs=','.join('?' for _ in cols)
            with self.db:
                cur=self.db.execute(f"INSERT INTO attempts({keys}) VALUES({qs})", tuple(cols.values()))
                self.db.execute("INSERT INTO attempt_events(attempt_id,to_state,revision,created_at) VALUES(?,?,?,?)", (cur.lastrowid,state.value,0,now))
            return await SQLiteAttemptJournal.get(self, logical_opportunity_id, plan_hash, attempt_generation)  # type: ignore

    async def get(self, logical_opportunity_id: str, plan_hash: str, attempt_generation: int) -> JournalAttemptRecord | None:
        row=self.db.execute("SELECT * FROM attempts WHERE logical_opportunity_id=? AND plan_hash=? AND attempt_generation=?", (logical_opportunity_id,plan_hash,attempt_generation)).fetchone()
        return self._record(row) if row else None

    async def transition(self, identity: tuple[str,str,int], from_revision: int, to_state: ExecutionState, *, reason_code: str | None=None, error: str | None=None, evidence: dict[str,Any] | None=None) -> bool:
        async with self._lock:
            now=time.time(); opp,plan,gen=identity
            with self.db:
                row=self.db.execute("SELECT id,state,revision FROM attempts WHERE logical_opportunity_id=? AND plan_hash=? AND attempt_generation=?", identity).fetchone()
                if not row or row["revision"] != from_revision: return False
                rev=from_revision+1
                cur=self.db.execute("UPDATE attempts SET state=?, revision=?, updated_at=? WHERE id=? AND revision=?", (to_state.value,rev,now,row["id"],from_revision))
                if cur.rowcount != 1: return False
                self.db.execute("INSERT INTO attempt_events(attempt_id,from_state,to_state,revision,reason_code,error,evidence,created_at) VALUES(?,?,?,?,?,?,?,?)", (row["id"],row["state"],to_state.value,rev,reason_code,error,json.dumps(evidence or {},sort_keys=True),now))
                return True

    async def record_submission_intent(self, identity: tuple[str,str,int], *, owner: str, lease_seconds: float, transport: str, signatures: tuple[str,...], message_digest: str, signed_transaction_digest: str, blockhash_context: BlockhashContext) -> bool:
        async with self._lock:
            now=time.time(); lease=now+lease_seconds
            with self.db:
                row=self.db.execute("SELECT id,revision,state,claim_owner,lease_expires_at FROM attempts WHERE logical_opportunity_id=? AND plan_hash=? AND attempt_generation=?", identity).fetchone()
                if not row or row["state"] != ExecutionState.SIGNED.value: return False
                if row["claim_owner"] and (row["lease_expires_at"] or 0) > now: return False
                rev=row["revision"]+1
                self.db.execute("UPDATE attempts SET state=?,revision=?,submission_intent_at=?,claim_owner=?,lease_expires_at=?,transport=?,transaction_signatures=?,message_digest=?,signed_transaction_digest=?,blockhash=?,last_valid_block_height=?,source_slot=?,min_context_slot=?,commitment=?,updated_at=? WHERE id=? AND revision=?", (ExecutionState.SUBMISSION_INTENT_RECORDED.value,rev,now,owner,lease,transport,json.dumps(signatures),message_digest,signed_transaction_digest,blockhash_context.blockhash,blockhash_context.last_valid_block_height,blockhash_context.source_slot,blockhash_context.source_slot,blockhash_context.commitment,now,row["id"],row["revision"]))
                self.db.execute("INSERT INTO attempt_events(attempt_id,from_state,to_state,revision,reason_code,evidence,created_at) VALUES(?,?,?,?,?,?,?)", (row["id"],row["state"],ExecutionState.SUBMISSION_INTENT_RECORDED.value,rev,"SUBMISSION_INTENT_RECORDED",json.dumps({"transport":transport,"signatures":signatures}),now))
                return True

    async def recover_ambiguous_intents(self) -> int:
        with self.db:
            cur=self.db.execute("UPDATE attempts SET state=?, revision=revision+1, updated_at=? WHERE state=?", (ExecutionState.SUBMISSION_UNCERTAIN.value,time.time(),ExecutionState.SUBMISSION_INTENT_RECORDED.value))
            return cur.rowcount

    async def reserve_submission(self, opportunity_id: str, message_hash: str, *, attempt_number: int = 1) -> bool:
        try:
            await self.create_attempt(opportunity_id, message_hash, attempt_number, state=ExecutionState.SUBMISSION_INTENT_RECORDED, message_digest=message_hash)
            return True
        except sqlite3.IntegrityError:
            return False

    def _record(self,row: sqlite3.Row)->JournalAttemptRecord:
        return JournalAttemptRecord(row["logical_opportunity_id"],row["plan_hash"],row["attempt_generation"],ExecutionState(row["state"]),row["revision"],row["message_digest"],row["signed_transaction_digest"],tuple(json.loads(row["transaction_signatures"] or '[]')),row["blockhash"],row["last_valid_block_height"],row["source_slot"],row["min_context_slot"],row["commitment"],row["transport"],row["jito_bundle_id"],row["claim_owner"],row["lease_expires_at"])

class InMemoryExecutionJournal(SQLiteAttemptJournal):
    """Compatibility shim; active code should inject SQLiteAttemptJournal."""
    def __init__(self):
        super().__init__(":memory:")

    def get(self, opportunity_id: str, message_hash: str) -> ExecutionJournalEntry | None:  # type: ignore[override]
        row = self.db.execute(
            "SELECT * FROM attempts WHERE logical_opportunity_id=? AND plan_hash=? ORDER BY attempt_generation DESC LIMIT 1",
            (opportunity_id, message_hash),
        ).fetchone()
        if not row:
            return None
        return ExecutionJournalEntry(
            row["logical_opportunity_id"],
            row["attempt_generation"],
            row["plan_hash"],
            submitted=row["state"] in {ExecutionState.SUBMISSION_INTENT_RECORDED.value, ExecutionState.ACCEPTED.value},
            bundle_id=row["jito_bundle_id"],
            transaction_signatures=tuple(json.loads(row["transaction_signatures"] or "[]")),
        )
