from __future__ import annotations
import json, sqlite3, time
from pathlib import Path
from .events import EventEnvelope
from .redaction import REDACTION_VERSION

MIGRATION_VERSION = 17
class ObservabilityError(RuntimeError): pass

class ObservabilityStore:
    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 2500):
        self.path = str(path); self.db = sqlite3.connect(self.path, isolation_level=None, timeout=busy_timeout_ms/1000)
        self.db.row_factory = sqlite3.Row
        self.db.execute(f"PRAGMA busy_timeout={busy_timeout_ms}"); self.db.execute("PRAGMA journal_mode=WAL"); self.db.execute("PRAGMA foreign_keys=ON")
        self.migrate()
    def migrate(self) -> None:
        try:
            with self.db:
                self.db.executescript('''
                CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL);
                CREATE TABLE event_log(event_id TEXT PRIMARY KEY, aggregate_id TEXT NOT NULL, sequence_no INTEGER NOT NULL, idempotency_key TEXT NOT NULL UNIQUE, occurred_at_utc_ns INTEGER NOT NULL, monotonic_ns INTEGER NOT NULL, event_type TEXT NOT NULL, schema_version INTEGER NOT NULL, reason_code TEXT, outcome TEXT NOT NULL, stage TEXT NOT NULL, severity TEXT NOT NULL, environment TEXT NOT NULL, logical_opportunity_id TEXT NOT NULL, plan_hash TEXT NOT NULL, attempt_generation INTEGER NOT NULL, attempt_id TEXT, message_hash TEXT, tx_signature TEXT, jito_bundle_id TEXT, provider_id TEXT, venue_id TEXT, payload_json TEXT NOT NULL, payload_digest TEXT NOT NULL, config_checksum TEXT NOT NULL, redaction_version TEXT NOT NULL, redaction_hits INTEGER NOT NULL, producer_code_version TEXT, contract_fixture_version TEXT, created_at REAL NOT NULL, UNIQUE(aggregate_id, sequence_no));
                CREATE TABLE attempt_projection(attempt_id TEXT PRIMARY KEY, aggregate_id TEXT NOT NULL, last_sequence_no INTEGER NOT NULL, terminal INTEGER NOT NULL, outcome TEXT, reason_code TEXT, updated_at REAL NOT NULL);
                CREATE TABLE opportunity_projection(logical_opportunity_id TEXT PRIMARY KEY, aggregate_id TEXT NOT NULL, last_sequence_no INTEGER NOT NULL, terminal INTEGER NOT NULL, updated_at REAL NOT NULL);
                CREATE TABLE evidence_blob(digest TEXT PRIMARY KEY, classification TEXT NOT NULL, size_bytes INTEGER NOT NULL, payload_json TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE TABLE outbox(id INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE, work_type TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL, completed_at REAL, FOREIGN KEY(event_id) REFERENCES event_log(event_id));
                CREATE TABLE export_manifest(manifest_id TEXT PRIMARY KEY, partition_path TEXT NOT NULL UNIQUE, checksum TEXT NOT NULL, event_count INTEGER NOT NULL, first_event_id TEXT, last_event_id TEXT, schema_version INTEGER NOT NULL, redaction_version TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE TABLE retention_ledger(id INTEGER PRIMARY KEY, target_digest TEXT NOT NULL, target_type TEXT NOT NULL, action TEXT NOT NULL, dry_run INTEGER NOT NULL, eligible_after_ns INTEGER NOT NULL, manifest_id TEXT, created_at REAL NOT NULL);
                ''')
                self.db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?,?)", (MIGRATION_VERSION, time.time()))
        except sqlite3.OperationalError as e:
            if "already exists" not in str(e): raise
            self.db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?,?)", (MIGRATION_VERSION, time.time()))
    def append(self, event: EventEnvelope) -> bool:
        payload, hits = event.redacted_payload(); digest = event.payload_digest(); now = time.time()
        try:
            with self.db:
                cur = self.db.execute('''INSERT OR IGNORE INTO event_log(event_id,aggregate_id,sequence_no,idempotency_key,occurred_at_utc_ns,monotonic_ns,event_type,schema_version,reason_code,outcome,stage,severity,environment,logical_opportunity_id,plan_hash,attempt_generation,attempt_id,message_hash,tx_signature,jito_bundle_id,provider_id,venue_id,payload_json,payload_digest,config_checksum,redaction_version,redaction_hits,producer_code_version,contract_fixture_version,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (event.event_id,event.aggregate_id,event.sequence_no,event.idempotency_key,event.occurred_at_utc_ns,event.monotonic_ns,event.event_type.value,event.schema_version,event.reason_code.value if event.reason_code else None,event.outcome.value,event.stage,event.severity.value,event.environment.value,event.logical_opportunity_id,event.plan_hash,event.attempt_generation,event.attempt_id,event.message_hash,event.tx_signature,event.jito_bundle_id,event.provider_id,event.venue_id,json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False),digest,event.config_checksum,REDACTION_VERSION,hits,event.producer_code_version,event.contract_fixture_version,now))
                if cur.rowcount == 0:
                    existing = self.db.execute("SELECT event_id FROM event_log WHERE idempotency_key=?", (event.idempotency_key,)).fetchone()
                    if existing and existing["event_id"] == event.event_id:
                        return False
                    raise ObservabilityError("OBSERVABILITY_DURABLE_WRITE_FAILED")
                self.db.execute("INSERT OR IGNORE INTO outbox(event_id,work_type,status,created_at) VALUES(?,?,?,?)", (event.event_id,"export","pending",now))
                terminal = 1 if event.event_type.value in {"attempt_terminal","balance_reconciled","reconciliation_completed"} else 0
                if event.attempt_id:
                    self.db.execute("INSERT OR REPLACE INTO attempt_projection(attempt_id,aggregate_id,last_sequence_no,terminal,outcome,reason_code,updated_at) VALUES(?,?,?,?,?,?,?)", (event.attempt_id,event.aggregate_id,event.sequence_no,terminal,event.outcome.value,event.reason_code.value if event.reason_code else None,now))
                self.db.execute("INSERT OR REPLACE INTO opportunity_projection(logical_opportunity_id,aggregate_id,last_sequence_no,terminal,updated_at) VALUES(?,?,?,?,?)", (event.logical_opportunity_id,event.aggregate_id,event.sequence_no,terminal,now))
                return True
        except sqlite3.Error as exc:
            raise ObservabilityError("OBSERVABILITY_DURABLE_WRITE_FAILED") from exc
    def events_for(self, *, aggregate_id: str | None=None, opportunity_id: str | None=None, attempt_id: str | None=None) -> list[sqlite3.Row]:
        if aggregate_id: return list(self.db.execute("SELECT * FROM event_log WHERE aggregate_id=? ORDER BY sequence_no", (aggregate_id,)))
        if attempt_id: return list(self.db.execute("SELECT * FROM event_log WHERE attempt_id=? ORDER BY sequence_no", (attempt_id,)))
        if opportunity_id: return list(self.db.execute("SELECT * FROM event_log WHERE logical_opportunity_id=? ORDER BY sequence_no", (opportunity_id,)))
        raise ValueError("one selector required")
