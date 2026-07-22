from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import stat

import pytest

from src.observability.events import EventType, make_event
from src.observability.replay import replay_event_rows
from src.observability.store import ObservabilityStore


def _append_two(store: ObservabilityStore) -> list[sqlite3.Row]:
    first = make_event(
        event_type=EventType.opportunity_detected,
        logical_opportunity_id="opp-1",
        plan_hash="plan-1",
        aggregate_id="agg-1",
        sequence_no=0,
        stage="discovery",
        producer_code_version="release-1",
        config_checksum="a" * 64,
    )
    second = make_event(
        event_type=EventType.quote_requested,
        logical_opportunity_id="opp-1",
        plan_hash="plan-1",
        aggregate_id="agg-1",
        sequence_no=1,
        stage="quote",
        producer_code_version="release-1",
        config_checksum="a" * 64,
    )
    assert store.append(first) is True
    assert store.append(second) is True
    return store.events_for(aggregate_id="agg-1")


def _drop_immutability_triggers(store: ObservabilityStore) -> None:
    store.db.execute("DROP TRIGGER IF EXISTS event_log_no_update")
    store.db.execute("DROP TRIGGER IF EXISTS event_log_no_delete")


def test_store_creates_restrictive_database_and_valid_chain(tmp_path: Path) -> None:
    db_path = tmp_path / "observability.sqlite3"
    with ObservabilityStore(db_path) as store:
        rows = _append_two(store)
        report = replay_event_rows(rows, verify=True)

    assert report["divergences"] == []
    assert rows[0]["previous_chain_digest"] == "0" * 64
    assert rows[1]["previous_chain_digest"] == rows[0]["chain_digest"]
    assert stat.S_IMODE(db_path.stat().st_mode) == 0o600


def test_store_preserves_pr132_and_adds_pr184_migrations(tmp_path: Path) -> None:
    with ObservabilityStore(tmp_path / "events.sqlite3") as store:
        rows = store.db.execute(
            "SELECT version, schema_name FROM schema_migrations ORDER BY version"
        ).fetchall()

    migrations = {row["version"]: row["schema_name"] for row in rows}
    assert migrations[17] == "pr132.observability-store.v1"
    assert migrations[18] == "pr184.tamper-evident-observability-store.v1"


def test_payload_and_digest_rewrite_breaks_chain(tmp_path: Path) -> None:
    with ObservabilityStore(tmp_path / "tamper.sqlite3") as store:
        rows = _append_two(store)
        _drop_immutability_triggers(store)

        payload = json.loads(rows[0]["payload_json"])
        payload["stage"] = "attacker-stage"
        payload_json = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        payload_digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        store.db.execute(
            """
            UPDATE event_log
            SET payload_json=?, payload_digest=?, stage=?
            WHERE event_id=?
            """,
            (
                payload_json,
                payload_digest,
                "attacker-stage",
                rows[0]["event_id"],
            ),
        )
        report = replay_event_rows(
            store.events_for(aggregate_id="agg-1"),
            verify=True,
        )

    codes = {item["code"] for item in report["divergences"]}
    assert "CHAIN_DIGEST_DIVERGENCE" in codes


def test_denormalized_column_rewrite_is_detected(tmp_path: Path) -> None:
    with ObservabilityStore(tmp_path / "column.sqlite3") as store:
        rows = _append_two(store)
        _drop_immutability_triggers(store)
        store.db.execute(
            "UPDATE event_log SET stage='attacker-stage' WHERE event_id=?",
            (rows[0]["event_id"],),
        )
        report = replay_event_rows(
            store.events_for(aggregate_id="agg-1"),
            verify=True,
        )

    codes = {item["code"] for item in report["divergences"]}
    assert "DENORMALIZED_COLUMN_DIVERGENCE" in codes
    assert "CHAIN_DIGEST_DIVERGENCE" in codes


def test_deleting_middle_event_breaks_previous_chain(tmp_path: Path) -> None:
    with ObservabilityStore(tmp_path / "delete.sqlite3") as store:
        rows = _append_two(store)
        _drop_immutability_triggers(store)
        store.db.execute(
            "DELETE FROM outbox WHERE event_id=?",
            (rows[0]["event_id"],),
        )
        store.db.execute(
            "DELETE FROM event_log WHERE event_id=?",
            (rows[0]["event_id"],),
        )
        report = replay_event_rows(
            store.events_for(aggregate_id="agg-1"),
            verify=True,
        )

    codes = {item["code"] for item in report["divergences"]}
    assert "PREVIOUS_CHAIN_DIVERGENCE" in codes


def test_reopening_database_preserves_chain_and_detects_rewrite(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "reopen.sqlite3"
    with ObservabilityStore(db_path) as store:
        _append_two(store)

    with ObservabilityStore(db_path) as reopened:
        report = replay_event_rows(
            reopened.events_for(aggregate_id="agg-1"),
            verify=True,
        )
        assert report["divergences"] == []
        reopened.db.execute(
            "UPDATE event_log SET stage='rewritten' WHERE sequence_no=0"
        )
        tampered = replay_event_rows(
            reopened.events_for(aggregate_id="agg-1"),
            verify=True,
        )
        codes = {item["code"] for item in tampered["divergences"]}
        assert "DENORMALIZED_COLUMN_DIVERGENCE" in codes
        assert "CHAIN_DIGEST_DIVERGENCE" in codes


def test_exact_duplicate_returns_original_idempotent_result(tmp_path: Path) -> None:
    event = make_event(
        event_type=EventType.opportunity_detected,
        logical_opportunity_id="opp-dup",
        plan_hash="plan-dup",
        aggregate_id="agg-dup",
        sequence_no=0,
        event_id="event-dup",
        idempotency_key="idem-dup",
    )
    with ObservabilityStore(tmp_path / "duplicate.sqlite3") as store:
        assert store.append(event) is True
        assert store.append(event) is False
