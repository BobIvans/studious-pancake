from __future__ import annotations

import json
import sqlite3

import pytest

from src.evidence.shadow_soak import (
    EvidenceError,
    SCHEMA_VERSION,
    ShadowOutcomeRecord,
    ShadowSoakAnalyzer,
    ShadowSoakThresholds,
)

SECONDS_72H = 72 * 60 * 60


def _record(
    attempt_id: str,
    *,
    created_at: int = 1_700_000_000,
    completed_at: int | None = None,
    terminal_reason: str = "SHADOW_RECONCILED",
    conservative_quote_pnl: int = 10_000,
    simulated_executable_pnl: int = 9_000,
    simulation_success: bool = True,
    repayment_proven: bool = True,
) -> ShadowOutcomeRecord:
    return ShadowOutcomeRecord(
        opportunity_id=f"opp-{attempt_id}",
        attempt_id=attempt_id,
        plan_hash=f"plan-{attempt_id}",
        message_hash=f"message-{attempt_id}",
        reconciliation_hash=f"recon-{attempt_id}",
        terminal_reason=terminal_reason,
        created_at=created_at,
        completed_at=completed_at if completed_at is not None else created_at + 2,
        context_slot=123,
        response_hash=f"response-{attempt_id}",
        theoretical_quote_pnl=11_000,
        conservative_quote_pnl=conservative_quote_pnl,
        simulated_executable_pnl=simulated_executable_pnl,
        simulation_success=simulation_success,
        units_consumed=100_000,
        fee_lamports=5_000,
        required_repayment=1_000,
        observed_repayment=1_000 if repayment_proven else 0,
        repayment_proven=repayment_proven,
        provenance={"source": "unit-fixture"},
    )


def test_passing_bundle_is_deterministic_and_still_requires_human_review() -> None:
    records = [
        _record("b", created_at=1_700_000_010, completed_at=1_700_000_020),
        _record("a", created_at=1_700_000_000, completed_at=1_700_000_000 + SECONDS_72H),
    ]
    thresholds = ShadowSoakThresholds(minimum_samples=2)

    bundle = ShadowSoakAnalyzer(records, thresholds=thresholds).build_bundle()
    rebuilt = ShadowSoakAnalyzer(reversed(records), thresholds=thresholds).build_bundle()

    assert bundle.schema_version == SCHEMA_VERSION
    assert bundle.passed is True
    assert bundle.live_enabled is False
    assert bundle.human_review_required is True
    assert bundle.metrics.sample_count == 2
    assert bundle.metrics.duration_seconds == SECONDS_72H
    assert bundle.metrics.reason_counts == {"SHADOW_RECONCILED": 2}
    assert bundle.replay_digest.digest == rebuilt.replay_digest.digest
    assert bundle.evidence_hash == rebuilt.evidence_hash
    assert json.loads(bundle.to_json())["evidence_hash"] == bundle.evidence_hash


def test_thresholds_block_short_soak_and_false_positive_mismatch() -> None:
    record = _record(
        "bad",
        terminal_reason="REPAYMENT_NOT_PROVEN",
        conservative_quote_pnl=10_000,
        simulated_executable_pnl=-5_000,
        simulation_success=False,
        repayment_proven=False,
    )

    bundle = ShadowSoakAnalyzer([record]).build_bundle()

    assert bundle.passed is False
    assert "SOAK_DURATION_BELOW_THRESHOLD" in bundle.blocking_reasons
    assert "REPAYMENT_OR_SERIALIZATION_MISMATCH_PRESENT" in bundle.blocking_reasons
    assert "FALSE_POSITIVE_RATE_ABOVE_THRESHOLD" in bundle.blocking_reasons
    assert bundle.metrics.false_positive_rate_bps == 10_000
    assert bundle.metrics.mismatch_count == 1


def test_jsonl_loader_and_validation_are_fail_closed(tmp_path) -> None:
    path = tmp_path / "shadow.jsonl"
    path.write_text(
        json.dumps(
            {
                "opportunity_id": "opp-jsonl",
                "attempt_id": "attempt-jsonl",
                "plan_hash": "plan-jsonl",
                "message_hash": "message-jsonl",
                "reconciliation_hash": "recon-jsonl",
                "terminal_reason": "SHADOW_RECONCILED",
                "created_at": "1700000000",
                "completed_at": "1700259200",
                "simulation_success": 1,
                "repayment_proven": "true",
                "conservative_quote_pnl": "10",
                "simulated_executable_pnl": "9",
                "fee_lamports": "5",
                "provenance": {"fixture": True},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    bundle = ShadowSoakAnalyzer.from_jsonl(
        path,
        thresholds=ShadowSoakThresholds(minimum_samples=1),
    ).build_bundle()

    assert bundle.passed is True
    assert bundle.metrics.total_fee_lamports == 5

    bad_path = tmp_path / "bad.jsonl"
    bad_path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(EvidenceError, match="must be an object"):
        ShadowSoakAnalyzer.from_jsonl(bad_path)


def test_shadow_sqlite_loader_reads_pr013_shadow_outcomes(tmp_path) -> None:
    db_path = tmp_path / "shadow.sqlite"
    with sqlite3.connect(db_path) as db:
        db.execute(
            """
            CREATE TABLE shadow_outcomes (
                opportunity_id TEXT NOT NULL,
                attempt_id TEXT NOT NULL,
                plan_hash TEXT NOT NULL,
                message_hash TEXT NOT NULL,
                response_hash TEXT,
                reconciliation_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                completed_at INTEGER,
                context_slot INTEGER,
                terminal_reason TEXT NOT NULL,
                theoretical_quote_pnl TEXT NOT NULL,
                conservative_quote_pnl TEXT NOT NULL,
                simulated_executable_pnl TEXT NOT NULL,
                simulation_success INTEGER NOT NULL,
                units_consumed INTEGER,
                fee_lamports TEXT,
                required_repayment TEXT NOT NULL,
                observed_repayment TEXT NOT NULL,
                repayment_proven INTEGER NOT NULL,
                provenance_json TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            INSERT INTO shadow_outcomes VALUES (
                'opp-sqlite',
                'attempt-sqlite',
                'plan-sqlite',
                'message-sqlite',
                'response-sqlite',
                'recon-sqlite',
                1700000000,
                1700259200,
                42,
                'SHADOW_RECONCILED',
                '11',
                '10',
                '9',
                1,
                123456,
                '5000',
                '1000',
                '1000',
                1,
                '{"sqlite": true}'
            )
            """
        )

    bundle = ShadowSoakAnalyzer.from_shadow_sqlite(
        db_path,
        thresholds=ShadowSoakThresholds(minimum_samples=1),
    ).build_bundle()

    assert bundle.passed is True
    assert bundle.metrics.started_at == 1_700_000_000
    assert bundle.metrics.completed_at == 1_700_259_200
    assert bundle.metrics.total_fee_lamports == 5_000
