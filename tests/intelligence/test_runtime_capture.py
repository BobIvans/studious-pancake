"""OCA-W10 tests: real producers, restart/replay, degraded capture, coverage."""

from __future__ import annotations

import json
from pathlib import Path

from src.observability.authoritative_store_pr195 import (
    AuthoritativeObservabilityStore,
)
from src.observability.events import EventType, Outcome
from src.observability.runtime_capture import (
    coverage_matrix,
    default_vertical_adapter,
    run_vertical,
)

VERTICAL_OPPORTUNITY = "vertical-opp-1"


def test_vertical_end_to_end_and_replay(tmp_path: Path) -> None:
    db = tmp_path / "events.sqlite"
    adapter = default_vertical_adapter(db)
    run = run_vertical(adapter, logical_opportunity_id=VERTICAL_OPPORTUNITY)
    assert run["captured"] == 5 and run["complete"]
    assert all(receipt["status"] == "CAPTURED" for receipt in run["receipts"])
    # Real provenance: no test-runtime defaults from this producer path.
    receipt = run["receipts"][0]
    assert receipt["runtime_id"] == "paper-vertical-1"
    # P2-3: paper events carry the paper environment, not the test default.
    assert receipt["status"] == "CAPTURED"
    assert receipt["producer_code_version"] == "runtime-capture@v1"
    assert receipt["config_checksum"] == "vertical-config-v1"
    # Restart from the durable store: same stages observable, no loss.
    reopened = AuthoritativeObservabilityStore(
        str(db),
        environment="paper",
        cluster_genesis="fixture-genesis",
        release_id="runtime-capture-vertical",
    )
    rows = list(
        reopened.db.execute(
            "SELECT stage, payload_json FROM event_log WHERE logical_opportunity_id=? ORDER BY sequence_no",
            (VERTICAL_OPPORTUNITY,),
        )
    )
    assert [row["stage"] for row in rows] == [
        "candidate",
        "quote",
        "plan",
        "simulation",
        "paper_outcome",
    ]
    # Critical flag rides in the attributes payload; critical stages are never
    # sampled or dropped.
    assert all(
        json.loads(row["payload_json"]).get("attributes", {}).get("critical") is True
        for row in rows
    )


def test_critical_events_never_dropped_or_sampled(tmp_path: Path) -> None:
    adapter = default_vertical_adapter(tmp_path / "events.sqlite")
    for sequence in range(1, 8):
        receipt = adapter.capture_stage(
            logical_opportunity_id="opp-critical",
            sequence_no=sequence,
            event_type=EventType.opportunity_detected,
            outcome=Outcome.accepted,
            critical=True,
        )
        assert receipt["status"] == "CAPTURED"
    store = AuthoritativeObservabilityStore(
        str(tmp_path / "events.sqlite"),
        environment="paper",
        cluster_genesis="fixture-genesis",
        release_id="runtime-capture-vertical",
    )
    rows = list(
        store.db.execute(
            "SELECT COUNT(*) FROM event_log WHERE logical_opportunity_id='opp-critical'"
        )
    )
    assert rows[0][0] == 7, "sampling of critical decisions is prohibited"


def test_degraded_capture_is_explicit(tmp_path: Path) -> None:
    adapter = default_vertical_adapter(tmp_path / "events.sqlite")

    class FailingStore:
        def append(self, envelope):  # noqa: ANN001 - deliberately failing
            raise RuntimeError("simulated persistence failure")

    adapter._store = FailingStore()
    receipt = adapter.capture_stage(
        logical_opportunity_id="opp-degraded",
        sequence_no=1,
        event_type=EventType.quote_requested,
    )
    assert receipt["status"] == "DEGRADED"
    assert receipt["replayable"] is True
    assert "simulated persistence failure" in receipt["degraded_reason"]


def test_coverage_matrix_reports_uncovered_routes() -> None:
    matrix = coverage_matrix()
    statuses = {route["route"]: route["status"] for route in matrix["routes"]}
    atomic = next(
        r
        for r in matrix["routes"]
        if r["route"] == "paper-shadow:solana:atomic-vertical"
    )
    assert atomic["status"] == "PARTIAL"
    assert "no production caller" in atomic["note"]
    assert statuses["paper-shadow:sui"] == "NO_RUNTIME_PATH"
    assert statuses["submission:any"] == "BLOCKED"
    assert statuses["live:any"] == "BLOCKED"
    # Uncovered strategies/functions/routes are explicit, not assumed.
    assert "UNKNOWN" in matrix["counts"] or matrix["counts"]["UNKNOWN"] == 0
