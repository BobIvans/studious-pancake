from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from src.paper_shadow.a2_exact_attempt_runtime import (
    A2PaperOutcomeStatus,
    ExactAttemptRuntimeRecord,
    ExactAttemptRuntimeReport,
)
from src.paper_shadow.a2_supported_paper_runtime import (
    A2_RECORDED_EVIDENCE_SCHEMA,
    SupportedPaperRuntimeError,
    manifest_from_json,
    report_from_json,
    run_supported_paper_runtime,
)


DIGEST = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64
DIGEST_E = "e" * 64
DIGEST_F = "f" * 64


def _report(
    *,
    cycle_id: str = "cycle-1",
    status: A2PaperOutcomeStatus = A2PaperOutcomeStatus.RECONCILED_PAPER_SUCCESS,
    terminal_reason: str = "reconciled_sender_free_paper_success",
    records: tuple[ExactAttemptRuntimeRecord, ...] | None = None,
) -> ExactAttemptRuntimeReport:
    return ExactAttemptRuntimeReport(
        cycle_id=cycle_id,
        status=status,
        terminal_reason=terminal_reason,
        records=records
        if records is not None
        else (
            ExactAttemptRuntimeRecord(
                item_index=0,
                attempt_generation=1,
                status=status,
                reason_code=terminal_reason,
                provider_evidence_hash=DIGEST,
                result_hash=DIGEST_B,
                attempt_id="attempt-1",
                message_hash=DIGEST_C,
                reconciliation_hash=DIGEST_D,
            ),
        ),
    )


def _cycle_json(report: ExactAttemptRuntimeReport, *, evidence_hash: str = DIGEST_E):
    return {
        "cycle_id": report.cycle_id,
        "recorded_evidence_hash": evidence_hash,
        "exact_attempt_report_hash": hashlib.sha256(
            json.dumps(
                report.to_json(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest(),
        "report": report.to_json(),
    }


def _manifest_json(*reports: ExactAttemptRuntimeReport):
    return {
        "schema_version": A2_RECORDED_EVIDENCE_SCHEMA,
        "release_digest": DIGEST,
        "policy_bundle_hash": DIGEST_B,
        "source_wheel_parity_hash": DIGEST_C,
        "reviewed_by": "operator-review",
        "review_evidence_hash": DIGEST_D,
        "cycles": [_cycle_json(report) for report in reports],
    }


def test_recorded_evidence_runtime_persists_cycle_and_outbox(tmp_path):
    manifest = manifest_from_json(_manifest_json(_report()))
    db_path = tmp_path / "paper-runtime.sqlite"

    summary = run_supported_paper_runtime(
        manifest=manifest,
        state_db_path=db_path,
    )

    assert summary.cycles_processed == 1
    assert summary.final_status is A2PaperOutcomeStatus.RECONCILED_PAPER_SUCCESS
    assert summary.ready_for_next_cycle is True
    assert summary.outbox_events_written == 1
    assert summary.live_enabled is False
    assert summary.sender_reachable is False
    assert summary.signer_reachable is False
    assert summary.jsonl_authoritative is False

    with sqlite3.connect(db_path) as connection:
        cycles = connection.execute("SELECT cycle_id, status FROM paper_cycles").fetchall()
        outbox = connection.execute("SELECT event_type, delivered FROM paper_outbox").fetchall()

    assert cycles == [("cycle-1", "RECONCILED_PAPER_SUCCESS")]
    assert outbox == [("paper_cycle_recorded", 0)]


def test_replay_of_same_cycle_is_idempotent(tmp_path):
    manifest = manifest_from_json(_manifest_json(_report()))
    db_path = tmp_path / "paper-runtime.sqlite"

    first = run_supported_paper_runtime(manifest=manifest, state_db_path=db_path)
    second = run_supported_paper_runtime(manifest=manifest, state_db_path=db_path)

    assert first.outbox_events_written == 1
    assert second.outbox_events_written == 0
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT count(*) FROM paper_cycles").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM paper_outbox").fetchone()[0] == 1


def test_duplicate_cycle_with_different_hash_fails_closed(tmp_path):
    report = _report()
    manifest = manifest_from_json(_manifest_json(report))
    db_path = tmp_path / "paper-runtime.sqlite"
    run_supported_paper_runtime(manifest=manifest, state_db_path=db_path)

    changed = _report(terminal_reason="reconciled_sender_free_paper_success_v2")
    changed_manifest = manifest_from_json(_manifest_json(changed))

    with pytest.raises(SupportedPaperRuntimeError, match="different report hash"):
        run_supported_paper_runtime(manifest=changed_manifest, state_db_path=db_path)


def test_non_ready_cycle_stops_batch(tmp_path):
    blocked = _report(
        cycle_id="cycle-1",
        status=A2PaperOutcomeStatus.BLOCKED,
        terminal_reason="PR152_PROVIDER_EVIDENCE_EXPIRED",
        records=(
            ExactAttemptRuntimeRecord(
                item_index=0,
                attempt_generation=1,
                status=A2PaperOutcomeStatus.BLOCKED,
                reason_code="PR152_PROVIDER_EVIDENCE_EXPIRED",
                provider_evidence_hash=DIGEST,
                result_hash=DIGEST_B,
            ),
        ),
    )
    later = _report(cycle_id="cycle-2")
    manifest = manifest_from_json(_manifest_json(blocked, later))

    summary = run_supported_paper_runtime(
        manifest=manifest,
        state_db_path=tmp_path / "paper-runtime.sqlite",
    )

    assert summary.cycles_processed == 1
    assert summary.final_status is A2PaperOutcomeStatus.BLOCKED
    assert summary.ready_for_next_cycle is False


def test_report_hash_must_match_payload():
    payload = _manifest_json(_report())
    payload["cycles"][0]["exact_attempt_report_hash"] = DIGEST_F

    with pytest.raises(SupportedPaperRuntimeError, match="does not match"):
        manifest_from_json(payload)


def test_sender_or_submission_report_is_rejected():
    report_payload = _report().to_json()
    report_payload["sender_imported"] = True

    with pytest.raises(SupportedPaperRuntimeError):
        report_from_json(report_payload)


def test_manifest_rejects_missing_review_and_release_digests():
    payload = _manifest_json(_report())
    payload["reviewed_by"] = ""
    payload["release_digest"] = "not-a-digest"

    with pytest.raises(SupportedPaperRuntimeError):
        manifest_from_json(payload)


def test_jsonl_is_not_authoritative_in_summary(tmp_path):
    manifest = manifest_from_json(_manifest_json(_report()))
    summary = run_supported_paper_runtime(
        manifest=manifest,
        state_db_path=tmp_path / "paper-runtime.sqlite",
    )

    payload = summary.to_json()
    assert payload["jsonl_authoritative"] is False
    assert payload["profile"] == "recorded-evidence"
