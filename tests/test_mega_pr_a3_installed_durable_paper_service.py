from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3

import pytest

from src.config.runtime import load_runtime_config
from src.paper_shadow.a2_exact_attempt_runtime import (
    A2PaperOutcomeStatus,
    ExactAttemptRuntimeReport,
)
from src.paper_shadow.durable_service_a3 import (
    A3_B3_EVIDENCE_MISSING,
    A3ExactAttemptBatch,
    A3PaperServiceStatus,
    A3ProviderEvidenceState,
    InstalledDurablePaperService,
    InstalledDurablePaperServiceReport,
    InstalledPaperServiceConfig,
)

pytestmark = pytest.mark.unit


def _sha(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def test_a3_default_installed_service_fail_closes_into_sqlite(tmp_path):
    config = load_runtime_config()
    db_path = tmp_path / "paper-service.sqlite3"
    service = InstalledDurablePaperService(
        config,
        InstalledPaperServiceConfig(db_path=db_path, run_id="a3-default"),
        clock_ns=iter((100, 200)).__next__,
    )

    report = asyncio.run(service.run_once())

    assert report.status is A3PaperServiceStatus.BLOCKED
    assert report.terminal_reason == A3_B3_EVIDENCE_MISSING
    assert report.ready_for_next_cycle is False
    assert report.sender_imported is False
    assert report.submission_allowed is False
    assert report.live_enabled is False

    with sqlite3.connect(db_path) as db:
        cycle = db.execute(
            "SELECT status, terminal_reason, sender_imported, "
            "submission_allowed, live_enabled FROM a3_paper_service_cycles"
        ).fetchone()
        outbox = db.execute(
            "SELECT topic, status FROM a3_paper_service_outbox"
        ).fetchone()

    assert cycle == ("BLOCKED", A3_B3_EVIDENCE_MISSING, 0, 0, 0)
    assert outbox == ("paper.service.cycle_recorded", "pending")


def test_a3_ready_batch_runs_a2_projection_and_persists_no_trade(tmp_path):
    config = load_runtime_config()
    evidence = A3ProviderEvidenceState(
        provider_evidence_hash=_sha({"provider": "captured-b3"}),
        ready=True,
    )

    async def runtime_cycle(cycle_id, items):
        assert cycle_id
        assert items == ("request-1",)
        return ExactAttemptRuntimeReport(
            runtime_cycle_id=cycle_id,
            status=A2PaperOutcomeStatus.NO_TRADE,
            terminal_reason="no_trade",
            report_hash=_sha({"cycle": cycle_id, "status": "no_trade"}),
            ready_for_next_cycle=True,
            records=(),
        )

    service = InstalledDurablePaperService(
        config,
        InstalledPaperServiceConfig(
            db_path=tmp_path / "paper-service.sqlite3",
            run_id="a3-ready",
        ),
        batch_source=lambda: A3ExactAttemptBatch(evidence, ("request-1",)),
        runtime_cycle=runtime_cycle,
        clock_ns=iter((100, 200)).__next__,
    )

    report = asyncio.run(service.run_once())

    assert report.status is A3PaperServiceStatus.NO_TRADE
    assert report.ready_for_next_cycle is True
    assert report.provider_evidence_hash == evidence.provider_evidence_hash
    assert report.sender_imported is False
    assert report.submission_allowed is False
    assert report.live_enabled is False


def test_a3_rejects_sender_or_submission_surface_as_indeterminate():
    with pytest.raises(ValueError, match="unsafe sender/submission evidence"):
        InstalledDurablePaperServiceReport(
            cycle_id="cycle",
            status=A3PaperServiceStatus.RECONCILED_PAPER_SUCCESS,
            terminal_reason="paper_success",
            db_path=":memory:",
            provider_evidence_hash=_sha({"provider": "evidence"}),
            report_hash=_sha({"report": "success"}),
            ready_for_next_cycle=True,
            sequence=1,
            sender_imported=True,
        )


def test_a3_service_is_the_installed_paper_mode_authority():
    source = open("src/cli.py", encoding="utf-8").read()

    assert "build_installed_durable_paper_service" in source
    assert 'if mode == "paper":' in source
    assert "_run_installed_paper_service_once" in source
    assert "INSTALLED_PAPER_SERVICE" in source
