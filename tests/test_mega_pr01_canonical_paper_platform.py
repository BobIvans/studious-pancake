from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from src.canonical_paper.cli import main as paper_main
from src.canonical_paper import (
    BoundedRecordedBatchSource,
    CanonicalPaperConfig,
    CanonicalPaperPlatform,
    CanonicalPaperStore,
    DualClock,
    PaperOutcome,
    PersistenceError,
    RecordingError,
)


class StepClock:
    def __init__(self, values: list[int]) -> None:
        self.values = iter(values)

    def __call__(self) -> int:
        return next(self.values)


def _candidate(**overrides: object) -> dict[str, object]:
    message = hashlib.sha256(b"message").hexdigest()
    payload: dict[str, object] = {
        "candidate_id": "candidate-1",
        "provider_evidence_digest": hashlib.sha256(b"provider").hexdigest(),
        "compiled_message_digest": message,
        "simulation_message_digest": message,
        "principal_lamports": 1_000_000,
        "flash_fee_lamports": 1_000,
        "repayment_lamports": 1_001_000,
        "simulated_output_lamports": 1_050_000,
        "total_tx_fee_lamports": 5_000,
        "rent_lamports": 0,
        "tip_lamports": 0,
        "safety_buffer_lamports": 5_000,
        "observed_slot": 100,
        "rooted_slot": 98,
    }
    payload.update(overrides)
    return payload


def _write_recording(path: Path, candidates: list[dict[str, object]]) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "mega-pr-01.recorded-paper-batch.v1",
                "candidates": candidates,
            }
        )
    )
    return path


def _platform(tmp_path: Path, recording: Path) -> CanonicalPaperPlatform:
    return CanonicalPaperPlatform(
        CanonicalPaperConfig(
            db_path=tmp_path / "paper.sqlite3",
            recording_path=recording,
            config_digest=hashlib.sha256(b"config").hexdigest(),
        ),
        clock=DualClock(
            utc_ns=StepClock([1_000, 2_000]),
            monotonic_ns=StepClock([10, 25]),
        ),
    )


def test_positive_recorded_cycle_reaches_durable_paper_accepted(tmp_path: Path) -> None:
    recording = _write_recording(tmp_path / "recording.json", [_candidate()])
    report = _platform(tmp_path, recording).run_once()

    assert report.outcome is PaperOutcome.PAPER_ACCEPTED
    assert report.reason_code == "paper_accepted"
    assert report.accepted_count == 1
    assert report.duration_ns == 15
    assert not report.live_enabled
    assert not report.signer_loaded
    assert not report.sender_loaded

    with CanonicalPaperStore(tmp_path / "paper.sqlite3") as store:
        assert store.load(report.cycle_id) == report


def test_below_threshold_is_durable_no_trade_rejection(tmp_path: Path) -> None:
    recording = _write_recording(
        tmp_path / "recording.json",
        [_candidate(simulated_output_lamports=1_008_000)],
    )
    report = _platform(tmp_path, recording).run_once()
    assert report.outcome is PaperOutcome.PAPER_REJECTED
    assert report.reason_code == "no_candidate_meets_conservative_profit"
    assert report.rejected_count == 1
    assert report.decisions[0].reason_code == "rejected_conservative_profit_below_threshold"


def test_message_simulation_mutation_is_rejected(tmp_path: Path) -> None:
    recording = _write_recording(
        tmp_path / "recording.json",
        [_candidate(simulation_message_digest=hashlib.sha256(b"other").hexdigest())],
    )
    report = _platform(tmp_path, recording).run_once()
    assert report.decisions[0].reason_code == "rejected_message_simulation_digest_mismatch"


def test_repayment_formula_mismatch_is_rejected(tmp_path: Path) -> None:
    recording = _write_recording(
        tmp_path / "recording.json",
        [_candidate(repayment_lamports=1_000_000)],
    )
    report = _platform(tmp_path, recording).run_once()
    assert report.decisions[0].reason_code == "rejected_repayment_formula_mismatch"


def test_rooted_slot_skew_is_rejected(tmp_path: Path) -> None:
    recording = _write_recording(
        tmp_path / "recording.json",
        [_candidate(observed_slot=100, rooted_slot=1)],
    )
    report = _platform(tmp_path, recording).run_once()
    assert report.decisions[0].reason_code == "rejected_rooted_slot_skew"


def test_duplicate_candidate_ids_fail_closed_and_are_recorded(tmp_path: Path) -> None:
    recording = _write_recording(
        tmp_path / "recording.json",
        [_candidate(), _candidate()],
    )
    report = _platform(tmp_path, recording).run_once()
    assert report.outcome is PaperOutcome.BLOCKED
    assert report.reason_code == "blocked_recording_invalid"
    with CanonicalPaperStore(tmp_path / "paper.sqlite3") as store:
        assert store.load(report.cycle_id) is not None


def test_recording_limits_are_enforced_before_unbounded_parse(tmp_path: Path) -> None:
    path = tmp_path / "large.json"
    path.write_bytes(b"x" * 100)
    with pytest.raises(RecordingError, match="byte limit"):
        BoundedRecordedBatchSource(path, max_bytes=10).load()


def test_non_finite_json_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "nan.json"
    path.write_text(
        '{"schema_version":"mega-pr-01.recorded-paper-batch.v1","candidates":[NaN]}'
    )
    with pytest.raises(RecordingError, match="non-finite"):
        BoundedRecordedBatchSource(path).load()


def test_same_source_and_config_replay_is_idempotent(tmp_path: Path) -> None:
    recording = _write_recording(tmp_path / "recording.json", [_candidate()])
    first = _platform(tmp_path, recording).run_once()
    second = _platform(tmp_path, recording).run_once()
    assert second == first
    with sqlite3.connect(tmp_path / "paper.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM paper_cycles").fetchone()[0] == 1
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM paper_candidate_decisions"
            ).fetchone()[0]
            == 1
        )


def test_migration_checksum_tamper_hard_stops(tmp_path: Path) -> None:
    path = tmp_path / "paper.sqlite3"
    with CanonicalPaperStore(path):
        pass
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE paper_migrations SET checksum='bad'")
        connection.commit()
    with pytest.raises(PersistenceError, match="checksum"):
        CanonicalPaperStore(path)


def test_cli_default_package_recording_executes_sender_free_cycle(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = paper_main(["--db-path", str(tmp_path / "cli.sqlite3"), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["outcome"] == "PAPER_ACCEPTED"
    assert payload["accepted_count"] == 1
    assert payload["live_enabled"] is False
    assert payload["signer_loaded"] is False
    assert payload["sender_loaded"] is False


def test_root_wrapper_and_installed_cli_share_main_target() -> None:
    root = Path("arb_bot.py").read_text()
    installed = Path("pyproject.toml").read_text()
    assert 'CANONICAL_MAIN_TARGET = "src.cli_pr189:main"' in root
    assert "import_module(module_name)" in root
    assert "from src.cli_pr189 import" not in root
    assert 'flashloan-bot = "src.cli_pr189:main"' in installed
