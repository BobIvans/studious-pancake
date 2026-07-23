from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from src.canonical_paper.model import PersistenceError, RECORDING_SCHEMA
from src.canonical_paper.platform import CanonicalPaperConfig, CanonicalPaperPlatform
from src.canonical_paper.store import CanonicalPaperStore
from src.new_mega_pr_01_retirement_gate import (
    RetiredAuthorityEvidence,
    RetirementState,
    evaluate_legacy_retirement,
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _write_recording(path: Path) -> None:
    payload = {
        "schema_version": RECORDING_SCHEMA,
        "candidates": [
            {
                "candidate_id": "candidate-1",
                "provider_evidence_digest": _digest("provider"),
                "compiled_message_digest": _digest("message"),
                "simulation_message_digest": _digest("message"),
                "principal_lamports": 1_000_000,
                "flash_fee_lamports": 1_000,
                "repayment_lamports": 1_001_000,
                "simulated_output_lamports": 1_200_000,
                "total_tx_fee_lamports": 5_000,
                "rent_lamports": 0,
                "tip_lamports": 0,
                "safety_buffer_lamports": 10_000,
                "observed_slot": 108,
                "rooted_slot": 104,
            }
        ],
    }
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


class StepClock:
    def __init__(self) -> None:
        self._utc = 1_000
        self._mono = 10_000

    def utc_ns(self) -> int:
        self._utc += 1_000
        return self._utc

    def monotonic_ns(self) -> int:
        self._mono += 100
        return self._mono


def test_repeated_canonical_paper_invocation_gets_unique_cycle_identity(
    tmp_path: Path,
) -> None:
    recording_path = tmp_path / "recording.json"
    _write_recording(recording_path)
    config = CanonicalPaperConfig(
        db_path=tmp_path / "paper.sqlite3",
        recording_path=recording_path,
        config_digest=_digest("config"),
    )
    platform = CanonicalPaperPlatform(config, clock=StepClock())

    first = platform.run_once()
    second = platform.run_once()

    assert first.input_identity == second.input_identity
    assert first.run_sequence == 1
    assert second.run_sequence == 2
    assert first.cycle_id != second.cycle_id
    assert first.report_hash != second.report_hash
    assert first.accepted_count == second.accepted_count == 1


def test_cycle_sequence_is_durable_across_store_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "paper.sqlite3"
    input_identity = _digest("same-input")
    with CanonicalPaperStore(db_path) as store:
        assert store.allocate_run_sequence(input_identity) == 1
    with CanonicalPaperStore(db_path) as store:
        assert store.allocate_run_sequence(input_identity) == 2


def test_canonical_paper_store_rejects_preexisting_incompatible_schema(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "paper.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE paper_cycles (cycle_id TEXT PRIMARY KEY, source_digest TEXT NOT NULL)"
    )
    connection.commit()
    connection.close()

    with pytest.raises(PersistenceError, match="schema mismatch"):
        CanonicalPaperStore(db_path)


def test_canonical_paper_store_preserves_both_repeated_reports(tmp_path: Path) -> None:
    recording_path = tmp_path / "recording.json"
    _write_recording(recording_path)
    config = CanonicalPaperConfig(
        db_path=tmp_path / "paper.sqlite3",
        recording_path=recording_path,
        config_digest=_digest("config"),
    )
    platform = CanonicalPaperPlatform(config, clock=StepClock())

    first = platform.run_once()
    second = platform.run_once()

    with CanonicalPaperStore(config.db_path) as store:
        assert store.load(first.cycle_id) == first
        assert store.load(second.cycle_id) == second


def test_legacy_retirement_gate_blocks_importable_production_authority() -> None:
    report = evaluate_legacy_retirement(
        [
            RetiredAuthorityEvidence(
                module="src.strategy.runtime",
                importable=True,
                production_packaged=True,
                direct_invocation_blocked=False,
            )
        ]
    )

    assert report.state is RetirementState.BLOCKED
    assert "retired_authority_importable:src.strategy.runtime" in report.blockers
    assert (
        "retired_authority_direct_invocation_not_blocked:src.strategy.runtime"
        in report.blockers
    )
    assert report.live_enabled is False
    assert report.signer_loaded is False
    assert report.sender_loaded is False


def test_legacy_retirement_gate_accepts_removed_or_blocked_authority() -> None:
    report = evaluate_legacy_retirement(
        [
            RetiredAuthorityEvidence(
                module="src.strategy.runtime",
                importable=False,
                production_packaged=False,
                direct_invocation_blocked=True,
            )
        ]
    )

    assert report.state is RetirementState.READY
    assert report.blockers == ()
