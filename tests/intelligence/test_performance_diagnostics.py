"""OCA-W20 tests: diagnostics over the real W10 vertical + fault injection."""

from __future__ import annotations

from pathlib import Path

from src.intelligence.performance_diagnostics import (
    STATUS_ASSOCIATED_STAGE,
    STATUS_CAUSALITY_SUPPORTED,
    STATUS_CAUSALITY_PROVEN,
    STATUS_LOW_SAMPLE,
    STATUS_OBSERVED_ANOMALY,
    STATUS_UNKNOWN,
    build_diagnostics,
)
from src.observability.events import EventType, Outcome
from src.observability.runtime_capture import (
    default_vertical_adapter,
    run_vertical,
)
from src.observability.store import ObservabilityError


def _captured_store(tmp_path: Path, *, opportunities: int = 2, strategy_ref=None):
    adapter = default_vertical_adapter(tmp_path / "events.sqlite")
    for index in range(opportunities):
        run_vertical(
            adapter,
            logical_opportunity_id=f"opp-{index}",
            strategy_ref=strategy_ref,
        )
    return adapter._store


def test_diagnostics_over_real_vertical(tmp_path: Path) -> None:
    store = _captured_store(tmp_path, strategy_ref="fixture-atomic-vertical")
    result = build_diagnostics(
        store=store,
        repo_sha="0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54",
        config_checksum="vertical-config-v1",
        strategy_ref="fixture-atomic-vertical",
        static_callers=["src/planning/atomic_marginfi_jupiter.py"],
    )
    assert result["schema"] == "studious.performance-diagnostics.v1"
    health = result["sections"]["function_callsite_health"]
    assert health["candidate"]["invocations_denominator"] == 2
    assert health["candidate"]["telemetry_status"] == "OBSERVED"
    # Static callers are labelled context, never runtime invocations.
    dep = result["sections"]["dependency_trace"]
    assert dep["labelling"].startswith("STATIC_ONLY")
    # Without reconciliation evidence, economics stay UNKNOWN.
    assert result["sections"]["strategy_outcome"]["status"] == STATUS_UNKNOWN
    # Cohort carries sample size + compatibility.
    assert result["cohort"]["sample_size"] == 10
    assert result["cohort"]["compatibility"].startswith("COMPATIBLE_BASELINE")


def test_missing_telemetry_is_unknown_not_zero(tmp_path: Path) -> None:
    empty = default_vertical_adapter(tmp_path / "empty.sqlite")._store
    result = build_diagnostics(
        store=empty,
        repo_sha="0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54",
        config_checksum="cfg",
        strategy_ref="fixture",
    )
    assert result["status"] == STATUS_UNKNOWN
    assert any("never zero failures" in item for item in result["unknowns"])


def test_low_sample_never_ranks(tmp_path: Path) -> None:
    adapter = default_vertical_adapter(tmp_path / "events.sqlite")
    # Capture only 2 critical stages (well below the 5-sample threshold).
    for sequence in (1, 2):
        adapter.capture_stage(
            logical_opportunity_id="opp-small",
            sequence_no=sequence,
            event_type=EventType.opportunity_detected,
            strategy_ref="fixture-small",
        )
    result = build_diagnostics(
        store=adapter._store,
        repo_sha="0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54",
        config_checksum="cfg",
        strategy_ref="fixture-small",
    )
    statuses = {
        finding["status"] for finding in result["sections"]["anomaly_candidates"]
    }
    assert STATUS_LOW_SAMPLE in statuses
    assert STATUS_OBSERVED_ANOMALY not in statuses


def test_fault_injection_localizes_with_causality_gate(tmp_path: Path) -> None:
    adapter = default_vertical_adapter(tmp_path / "events.sqlite")
    # Baseline cohort: 4 clean verticals.
    for index in range(4):
        run_vertical(adapter, logical_opportunity_id=f"clean-{index}")
    # Fault injection: a cohort where the simulation stage fails repeatedly.
    for sequence in range(1, 6):
        adapter.capture_stage(
            logical_opportunity_id=f"fault-{sequence}",
            sequence_no=sequence,
            event_type=EventType.simulation_rejected,
            outcome=Outcome.rejected,
            stage="simulation",
            reason_code="SIMULATION_INSTRUCTION_ERROR",
            critical=True,
            strategy_ref="fixture-fault",
        )
    result = build_diagnostics(
        store=adapter._store,
        repo_sha="0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54",
        config_checksum="cfg",
        strategy_ref="fixture-fault",
        baseline_cohort={"sample_size": 20, "error_rate": 0.0},
    )
    findings = result["sections"]["anomaly_candidates"]
    anomaly = next(
        f
        for f in findings
        if f["status"] == STATUS_OBSERVED_ANOMALY and f["stage"] == "simulation"
    )
    assert anomaly["denominator"] >= 5
    # Without a controlled replay record, no causality tier may be emitted.
    assert not any(
        f["status"] in {"CAUSALITY_SUPPORTED_BY_CONTROLLED_TEST", "CAUSALITY_PROVEN"}
        for f in findings
    )
    assert STATUS_ASSOCIATED_STAGE in {f["status"] for f in findings}
    # With a controlled replay record localizing the stage, the tier unlocks.
    result2 = build_diagnostics(
        store=adapter._store,
        repo_sha="0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54",
        config_checksum="cfg",
        strategy_ref="fixture-fault",
        controlled_replay={"reproduced": True, "located_stage": "simulation"},
    )
    tiers2 = {f["status"] for f in result2["sections"]["anomaly_candidates"]}
    assert STATUS_CAUSALITY_SUPPORTED in tiers2
    # A recorded methodology upgrades to CAUSALITY_PROVEN.
    result3 = build_diagnostics(
        store=adapter._store,
        repo_sha="0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54",
        config_checksum="cfg",
        strategy_ref="fixture-fault",
        controlled_replay={
            "reproduced": True,
            "located_stage": "simulation",
            "methodology_recorded": True,
        },
    )
    tiers3 = {f["status"] for f in result3["sections"]["anomaly_candidates"]}
    assert STATUS_CAUSALITY_PROVEN in tiers3


def test_replay_after_restart_reproduces_diagnostics(tmp_path: Path) -> None:
    db = tmp_path / "events.sqlite"
    adapter = default_vertical_adapter(db)
    run_vertical(adapter, logical_opportunity_id="opp-replay")
    before = build_diagnostics(
        store=adapter._store,
        repo_sha="0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54",
        config_checksum="vertical-config-v1",
        strategy_ref="fixture-replay",
    )
    # Restart from the durable store (fresh adapter instance, same files).
    adapter2 = default_vertical_adapter(db)
    after = build_diagnostics(
        store=adapter2._store,
        repo_sha="0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54",
        config_checksum="vertical-config-v1",
        strategy_ref="fixture-replay",
    )
    assert before == after
