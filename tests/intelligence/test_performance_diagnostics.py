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
        config_checksum="vertical-config-v1",
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
        config_checksum="vertical-config-v1",
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
        config_checksum="vertical-config-v1",
        strategy_ref="fixture-fault",
        controlled_replay={"reproduced": True, "located_stage": "simulation"},
    )
    tiers2 = {f["status"] for f in result2["sections"]["anomaly_candidates"]}
    assert STATUS_CAUSALITY_SUPPORTED in tiers2
    # A recorded methodology upgrades to CAUSALITY_PROVEN.
    result3 = build_diagnostics(
        store=adapter._store,
        repo_sha="0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54",
        config_checksum="vertical-config-v1",
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


def test_no_cross_cohort_contamination(tmp_path: Path) -> None:
    """Adversarial: two strategies, two config generations, two routes and
    UNATTRIBUTED events in one store. Each requested cohort must use only its
    own attributed, generation-matching events."""
    adapter = default_vertical_adapter(tmp_path / "events.sqlite")
    # Cohort A: strategy-alpha @ generation alpha, route r-alpha, clean stages.
    adapter._route = "r-alpha"
    for index in range(2):
        run_vertical(
            adapter,
            logical_opportunity_id=f"alpha-{index}",
            strategy_ref="strategy-alpha",
        )
    # Cohort B: strategy-beta @ generation beta, route r-beta; simulation
    # fails in 5 of 5 verticals (>= 5-sample threshold so the anomaly tier
    # is reachable without violating LOW_SAMPLE honesty).
    adapter._config_checksum = "gen-beta"
    adapter._route = "r-beta"
    for index in range(5):
        for offset, stage in enumerate(
            [
                (EventType.opportunity_detected, Outcome.accepted, "candidate"),
                (EventType.quote_received, Outcome.observed, "quote"),
                (EventType.simulation_rejected, Outcome.rejected, "simulation"),
            ]
        ):
            adapter.capture_stage(
                logical_opportunity_id=f"beta-{index}",
                sequence_no=offset + 1,
                event_type=stage[0],
                outcome=stage[1],
                stage=stage[2],
                critical=True,
                strategy_ref="strategy-beta",
            )
    # UNATTRIBUTED noise events.
    adapter.capture_stage(
        logical_opportunity_id="noise-1",
        sequence_no=1,
        event_type=EventType.simulation_rejected,
        outcome=Outcome.rejected,
        stage="simulation",
        critical=True,
    )
    result_alpha = build_diagnostics(
        store=adapter._store,
        repo_sha="0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54",
        config_checksum="vertical-config-v1",
        strategy_ref="strategy-alpha",
    )
    result_beta = build_diagnostics(
        store=adapter._store,
        repo_sha="0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54",
        config_checksum="gen-beta",
        strategy_ref="strategy-beta",
    )
    # Alpha: only its own 10 events; beta's failures and noise excluded.
    alpha_health = result_alpha["sections"]["function_callsite_health"]
    assert alpha_health["simulation"]["invocations_denominator"] == 2
    assert alpha_health["simulation"]["errors"] == 0
    assert result_alpha["cohort"]["excluded_other_strategy"] == 16
    assert result_alpha["cohort"]["unattributed_kept_separate"] == 1
    assert result_alpha["cohort"]["route"] == "r-alpha"
    assert result_beta["cohort"]["route"] == "r-beta"
    # Beta: only its own 9 events on generation beta.
    beta_health = result_beta["sections"]["function_callsite_health"]
    assert beta_health["simulation"]["invocations_denominator"] == 5
    assert beta_health["simulation"]["errors"] == 5
    assert result_beta["cohort"]["attribution_status"] == "ATTRIBUTED"
    # No cross-contamination: alpha shows no anomaly, beta does.
    alpha_statuses = {
        f["status"] for f in result_alpha["sections"]["anomaly_candidates"]
    }
    assert STATUS_OBSERVED_ANOMALY not in alpha_statuses
    beta_statuses = {f["status"] for f in result_beta["sections"]["anomaly_candidates"]}
    assert STATUS_OBSERVED_ANOMALY in beta_statuses
