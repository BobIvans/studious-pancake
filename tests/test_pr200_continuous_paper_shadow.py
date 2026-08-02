import sys
from pathlib import Path

import pytest

from src.paper_shadow.continuous_pr200 import (
    PR200CandidateEvent,
    PR200ChaosScenario,
    PR200ContinuousConfig,
    PR200ContinuousPaperService,
    PR200DatasetSource,
    PR200DeterministicReplayHarness,
    PR200InvariantViolation,
    PR200Mode,
    build_pr200_run_identity,
)


def _identity(events):
    return build_pr200_run_identity(
        release="test-release",
        config={"mode": "paper", "max_cycles": 3},
        code_files={"src/paper_shadow/continuous_pr200.py": "test"},
        events=events,
    )


def _event(candidate_id="candidate-a", pnl=10):
    return PR200CandidateEvent(
        candidate_id=candidate_id,
        source=PR200DatasetSource.RECORDED,
        payload={"simulated_pnl_lamports": pnl, "pair": "SOL/USDC"},
        received_at_millis=100,
    )


def test_replay_is_deterministic_for_same_recorded_input():
    event = _event()
    identity = _identity([dict(event.payload)])
    replay = PR200DeterministicReplayHarness(identity, PR200Mode.PAPER)

    first = replay.simulate(event)
    second = replay.simulate(event)

    assert first.attempt_id == second.attempt_id
    assert first.outcome_hash == second.outcome_hash
    assert first.source is PR200DatasetSource.SIMULATED


def test_continuous_service_writes_sender_free_artifacts(tmp_path: Path):
    events = [_event("a", 12), _event("b", 0)]
    service = PR200ContinuousPaperService(
        PR200ContinuousConfig(max_cycles=2, output_dir=tmp_path),
        _identity([dict(event.payload) for event in events]),
        events,
        clock_millis=lambda: 1_000,
    )

    report = service.run()

    assert report.accepted_events == 2
    assert report.terminal_outcomes == 2
    assert report.rejection_counters["no_positive_simulated_pnl"] == 1
    assert report.to_dict()["soak_artifact_hash"] == report.artifact_hash
    assert (tmp_path / "events.jsonl").exists()
    assert (tmp_path / "outcomes.jsonl").exists()
    assert (tmp_path / "reports.jsonl").exists()


def test_duplicate_terminal_outcomes_are_counted_not_rewritten(tmp_path: Path):
    event = _event("same", 5)
    service = PR200ContinuousPaperService(
        PR200ContinuousConfig(max_cycles=1, max_events_per_cycle=2, output_dir=tmp_path),
        _identity([dict(event.payload)]),
        [event, event],
        clock_millis=lambda: 1_000,
    )

    report = service.run()

    assert report.accepted_events == 2
    assert report.terminal_outcomes == 1
    assert report.duplicate_terminal_outcomes == 1


def test_sender_module_import_fails_closed(tmp_path: Path, monkeypatch):
    module_name = "src.execution.senders.fake_sender"
    service = PR200ContinuousPaperService(
        PR200ContinuousConfig(max_cycles=1, output_dir=tmp_path),
        _identity([]),
        [],
        clock_millis=lambda: 1_000,
    )
    monkeypatch.setitem(sys.modules, module_name, object())

    with pytest.raises(PR200InvariantViolation):
        service.run()


def test_chaos_kill_records_partial_report_without_live_side_effects(tmp_path: Path):
    events = [_event("a", 1), _event("b", 2)]
    service = PR200ContinuousPaperService(
        PR200ContinuousConfig(max_cycles=3, output_dir=tmp_path),
        _identity([dict(event.payload) for event in events]),
        events,
        clock_millis=lambda: 1_000,
        chaos=PR200ChaosScenario(name="kill-after-one", fail_after_events=1),
    )

    report = service.run()

    assert report.accepted_events == 1
    assert "chaos_kill_after_events" in report.invariant_violations
    assert (tmp_path / "reports.jsonl").exists()


def test_negative_simulated_pnl_is_rejected_before_accounting():
    event = _event("negative", -1)
    identity = _identity([dict(event.payload)])
    replay = PR200DeterministicReplayHarness(identity, PR200Mode.SHADOW)

    outcome = replay.simulate(event)

    assert outcome.simulated_pnl_lamports == 0
    assert outcome.rejection_code == "no_positive_simulated_pnl"
