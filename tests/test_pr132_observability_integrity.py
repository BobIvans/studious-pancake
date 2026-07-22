from __future__ import annotations

from datetime import UTC, datetime
import json
import sqlite3
from pathlib import Path

import pytest

from src.observability.events import (
    Environment,
    EventEnvelope,
    EventType,
    Outcome,
    Severity,
)
from src.observability.export import export_jsonl
from src.observability.replay import replay_event_rows
from src.observability.store import ObservabilityError, ObservabilityStore


def _ns(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=UTC).timestamp() * 1_000_000_000)


def _event(
    *,
    event_type: EventType,
    sequence_no: int,
    occurred_at_utc_ns: int | None = None,
    attempt_id: str | None = "attempt-1",
    outcome: Outcome = Outcome.observed,
) -> EventEnvelope:
    aggregate_id = "agg-1"
    return EventEnvelope(
        event_id=f"{aggregate_id}-{sequence_no}-{event_type.value}",
        schema_version=1,
        occurred_at_utc_ns=occurred_at_utc_ns or _ns(2026, 1, 2),
        monotonic_ns=sequence_no,
        runtime_id="runtime-1",
        environment=Environment.test,
        trace_id="trace-1",
        logical_opportunity_id="opp-1",
        plan_hash="plan-hash-1",
        attempt_generation=1,
        attempt_id=attempt_id,
        message_hash=None,
        tx_signature=None,
        jito_bundle_id=None,
        event_type=event_type,
        aggregate_id=aggregate_id,
        sequence_no=sequence_no,
        stage=event_type.value,
        outcome=outcome,
        reason_code=None,
        severity=Severity.info,
        correlation_id=None,
        provider_id="provider-1",
        venue_id="venue-1",
        attributes={"sequence_no": sequence_no},
        producer_code_version="test",
        config_checksum="config-a",
        contract_fixture_version="contract-a",
        idempotency_key=f"{aggregate_id}:{sequence_no}:{event_type.value}",
    )


def test_pr132_schema_doctor_rejects_incomplete_claimed_migration(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "broken.db"
    db = sqlite3.connect(db_path)
    db.execute(
        "CREATE TABLE schema_migrations("
        "version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
    )
    db.execute("INSERT INTO schema_migrations(version, applied_at) VALUES(17, 1.0)")
    db.execute("CREATE TABLE event_log(event_id TEXT PRIMARY KEY)")
    db.commit()
    db.close()

    with pytest.raises(ObservabilityError, match="OBSERVABILITY_SCHEMA_INCOMPLETE"):
        ObservabilityStore(db_path)


def test_pr132_migration_stamps_version_after_postcondition(tmp_path: Path) -> None:
    store = ObservabilityStore(tmp_path / "ok.db")
    doctor = store.schema_doctor()

    assert doctor.ok is True
    row = store.db.execute(
        "SELECT schema_name, schema_checksum FROM schema_migrations WHERE version=17"
    ).fetchone()
    assert row["schema_name"] == "pr132.observability-store.v1"
    assert row["schema_checksum"] == doctor.schema_checksum


def test_pr132_projection_ignores_lower_sequence_and_preserves_terminal(
    tmp_path: Path,
) -> None:
    store = ObservabilityStore(tmp_path / "projection.db")

    assert store.append(
        _event(
            event_type=EventType.attempt_terminal,
            sequence_no=10,
            outcome=Outcome.succeeded,
        )
    )
    assert store.append(
        _event(
            event_type=EventType.route_planned,
            sequence_no=5,
            outcome=Outcome.observed,
        )
    )
    assert store.append(
        _event(
            event_type=EventType.quote_received,
            sequence_no=11,
            outcome=Outcome.observed,
        )
    )

    projection = store.db.execute(
        "SELECT * FROM attempt_projection WHERE attempt_id='attempt-1'"
    ).fetchone()
    assert projection["last_sequence_no"] == 11
    assert projection["terminal"] == 1
    assert projection["outcome"] == Outcome.succeeded.value


def test_pr132_export_uses_real_date_type_and_full_envelope(tmp_path: Path) -> None:
    store = ObservabilityStore(tmp_path / "export.db")
    store.append(
        _event(
            event_type=EventType.quote_received,
            sequence_no=1,
            occurred_at_utc_ns=_ns(2026, 2, 3),
        )
    )
    store.append(
        _event(
            event_type=EventType.route_planned,
            sequence_no=2,
            occurred_at_utc_ns=_ns(2026, 2, 4),
        )
    )

    result = export_jsonl(store, tmp_path / "out")

    assert result["event_count"] == 2
    assert result["manifest_count"] == 2
    exported_paths = {manifest["path"] for manifest in result["manifests"]}
    assert not any("1970-01-01" in path for path in exported_paths)
    assert any(
        "date_utc=2026-02-03/event_type=quote_received" in path
        for path in exported_paths
    )
    assert any(
        "date_utc=2026-02-04/event_type=route_planned" in path
        for path in exported_paths
    )

    first_path = sorted(exported_paths)[0]
    first_line = Path(first_path).read_text(encoding="utf-8").splitlines()[0]
    envelope = json.loads(first_line)
    assert envelope["schema_name"] == "pr132.observability-event-envelope.v1"
    assert envelope["event_id"]
    assert envelope["payload"]["event_id"] == envelope["event_id"]

    pending = store.db.execute(
        "SELECT COUNT(*) AS count FROM outbox WHERE status='pending'"
    ).fetchone()
    assert pending["count"] == 0


def test_pr132_export_marks_only_export_work_items(tmp_path: Path) -> None:
    store = ObservabilityStore(tmp_path / "outbox.db")
    store.append(_event(event_type=EventType.quote_received, sequence_no=1))
    store.db.execute(
        "UPDATE outbox SET work_type='metrics', status='pending' WHERE event_id=?",
        ("agg-1-1-quote_received",),
    )

    result = export_jsonl(store, tmp_path / "out")

    assert result["event_count"] == 0
    row = store.db.execute(
        "SELECT status, work_type FROM outbox WHERE event_id=?",
        ("agg-1-1-quote_received",),
    ).fetchone()
    assert row["work_type"] == "metrics"
    assert row["status"] == "pending"


def test_pr132_replay_verifies_payload_digest_and_terminal_regression(
    tmp_path: Path,
) -> None:
    store = ObservabilityStore(tmp_path / "replay.db")
    store.append(_event(event_type=EventType.attempt_terminal, sequence_no=1))
    store.append(_event(event_type=EventType.quote_received, sequence_no=2))

    rows = store.events_for(attempt_id="attempt-1")
    result = replay_event_rows(rows, verify=True)

    assert result["decision_replay_hash"]
    assert {
        "code": "TERMINAL_STATE_REGRESSION",
        "event_id": "agg-1-2-quote_received",
    } in result["divergences"]

    store.db.execute(
        "UPDATE event_log SET payload_digest='bad' WHERE event_id=?",
        ("agg-1-2-quote_received",),
    )
    corrupt = replay_event_rows(store.events_for(attempt_id="attempt-1"), verify=True)
    assert any(
        divergence["code"] == "PAYLOAD_DIGEST_DIVERGENCE"
        for divergence in corrupt["divergences"]
    )
