"""MPR-2602 positive paper terminal, restart replay and A3 authenticity tests."""

from __future__ import annotations

import asyncio
import json

import pytest

from src.paper_shadow.a2_exact_attempt_runtime import (
    A2PaperOutcomeStatus,
    ExactAttemptRuntimeItem,
    ExactAttemptRuntimeReport,
    derive_runtime_operation_id,
)
from src.paper_shadow.durable_service_a3 import (
    A3ExactAttemptBatch,
    A3PaperServiceStatus,
    A3ProviderEvidenceState,
    InstalledPaperServiceConfig,
)
from src.paper_shadow.mpr2602_completion import (
    DurableCompletedExactAttemptRuntime,
    MPR2602_PAPER_SUCCESS_REASON,
)
from src.paper_shadow.mpr2602_verified_a3 import (
    A3_UNVERIFIED_PAPER_TERMINAL,
    VerifiedTerminalInstalledPaperService,
)
from tests.test_mpr2602_prepared_exact_attempt import _attempt, _scalar

pytestmark = pytest.mark.unit


def _item(request):
    generation = request.attempt_key.generation
    return ExactAttemptRuntimeItem(
        request=request,
        attempt_generation=generation,
        runtime_idempotency_key=derive_runtime_operation_id(request, generation),
    )


@pytest.mark.asyncio
async def test_positive_wsol_completion_is_atomic_and_restart_replay_has_no_rpc(tmp_path):
    store, orchestrator, request, rpc, _holder = _attempt(tmp_path)
    runtime = DurableCompletedExactAttemptRuntime(
        orchestrator=orchestrator, authority=store
    )
    item = _item(request)
    try:
        first = await runtime("cycle-1", (item,))
        assert first.status is A2PaperOutcomeStatus.RECONCILED_PAPER_SUCCESS
        assert first.terminal_reason == MPR2602_PAPER_SUCCESS_REASON
        assert first.ready_for_next_cycle
        assert rpc.calls == 2
        assert _scalar(store, "SELECT state FROM durable_reservations") == "released"
        assert _scalar(store, "SELECT COUNT(*) FROM pr02_terminal_records") == 1
        assert _scalar(store, "SELECT COUNT(*) FROM pr02_outbox_event") == 1
        event = store.db.execute(
            "SELECT event_type,from_state,to_state FROM durable_events "
            "WHERE event_type='mpr2602_paper_terminal_committed'"
        ).fetchone()
        assert event is not None
        assert event[0] == "mpr2602_paper_terminal_committed"
        assert event[1] == event[2] == "planned"

        before_changes = store.db.total_changes
        replay = await runtime("cycle-2", (item,))
        assert replay.status is A2PaperOutcomeStatus.RECONCILED_PAPER_SUCCESS
        assert replay.ready_for_next_cycle
        assert rpc.calls == 2
        assert _scalar(store, "SELECT COUNT(*) FROM pr02_terminal_records") == 1
        assert _scalar(store, "SELECT COUNT(*) FROM pr02_outbox_event") == 1
        # Reserve/intent lookups are idempotent; terminal replay itself adds nothing.
        assert store.db.total_changes == before_changes
    finally:
        store.close()


@pytest.mark.asyncio
async def test_changed_prepared_semantics_cannot_reuse_completed_terminal(tmp_path):
    store, orchestrator, request, rpc, _holder = _attempt(tmp_path)
    runtime = DurableCompletedExactAttemptRuntime(
        orchestrator=orchestrator, authority=store
    )
    try:
        first = await runtime("cycle-1", (_item(request),))
        assert first.status is A2PaperOutcomeStatus.RECONCILED_PAPER_SUCCESS
        original_factory = request.candidate_factory

        def changed_factory(reservation):
            candidate = original_factory(reservation)
            from dataclasses import replace

            leg = replace(candidate.request.leg_a, route_plan=({"label": "drift"},))
            return replace(candidate, request=replace(candidate.request, leg_a=leg))

        from dataclasses import replace

        changed_request = replace(request, candidate_factory=changed_factory)
        with pytest.raises(Exception, match="IMMUTABILITY|AUTHORITY_CONFLICT"):
            await runtime("cycle-2", (_item(changed_request),))
        assert rpc.calls == 2
        assert _scalar(store, "SELECT COUNT(*) FROM pr02_terminal_records") == 1
    finally:
        store.close()


@pytest.mark.asyncio
async def test_verified_a3_accepts_real_terminal_and_rejects_forged_success(tmp_path):
    store, orchestrator, request, rpc, _holder = _attempt(tmp_path)
    runtime = DurableCompletedExactAttemptRuntime(
        orchestrator=orchestrator, authority=store
    )
    evidence = A3ProviderEvidenceState(
        provider_evidence_hash=request.provider_evidence.evidence_hash,
        ready=True,
    )
    item = _item(request)
    service = VerifiedTerminalInstalledPaperService(
        orchestrator.runtime_config if hasattr(orchestrator, "runtime_config") else __import__(
            "src.config.runtime", fromlist=["load_runtime_config"]
        ).load_runtime_config(),
        InstalledPaperServiceConfig(
            db_path=tmp_path / "paper-service.sqlite3", run_id="mpr2602-complete"
        ),
        batch_source=lambda: A3ExactAttemptBatch(evidence, (item,)),
        runtime_cycle=runtime,
        authority=store,
    )
    try:
        report = await service.run_once()
        assert report.status is A3PaperServiceStatus.RECONCILED_PAPER_SUCCESS
        assert report.ready_for_next_cycle
        assert rpc.calls == 2
    finally:
        service.close()
        store.close()

    # A success label without a durable attempt terminal is never sufficient.
    store2, _orchestrator2, request2, _rpc2, _holder2 = _attempt(tmp_path / "forged")
    evidence2 = A3ProviderEvidenceState(
        provider_evidence_hash=request2.provider_evidence.evidence_hash,
        ready=True,
    )

    async def forged(cycle_id, items):
        return ExactAttemptRuntimeReport(
            cycle_id=cycle_id,
            status=A2PaperOutcomeStatus.RECONCILED_PAPER_SUCCESS,
            terminal_reason="forged-success",
            records=(),
        )

    service2 = VerifiedTerminalInstalledPaperService(
        __import__("src.config.runtime", fromlist=["load_runtime_config"]).load_runtime_config(),
        InstalledPaperServiceConfig(
            db_path=tmp_path / "forged" / "paper-service.sqlite3",
            run_id="mpr2602-forged",
        ),
        batch_source=lambda: A3ExactAttemptBatch(evidence2, (_item(request2),)),
        runtime_cycle=forged,
        authority=store2,
    )
    try:
        rejected = await service2.run_once()
        assert rejected.status is A3PaperServiceStatus.INDETERMINATE
        assert rejected.terminal_reason == A3_UNVERIFIED_PAPER_TERMINAL
        assert not rejected.ready_for_next_cycle
    finally:
        service2.close()
        store2.close()


def test_terminal_payload_and_outbox_are_bound_to_same_report(tmp_path):
    store, orchestrator, request, _rpc, _holder = _attempt(tmp_path)
    runtime = DurableCompletedExactAttemptRuntime(
        orchestrator=orchestrator, authority=store
    )
    try:
        report = asyncio.run(runtime("cycle-1", (_item(request),)))
        assert report.status is A2PaperOutcomeStatus.RECONCILED_PAPER_SUCCESS
        terminal = store.db.execute("SELECT * FROM pr02_terminal_records").fetchone()
        outbox = store.db.execute("SELECT * FROM pr02_outbox_event").fetchone()
        payload = json.loads(terminal["payload_json"])
        assert payload["paper_only"] is True
        assert payload["outcome"] == "RECONCILED_PAPER_SUCCESS"
        outbox_payload = json.loads(outbox["payload_json"])
        assert outbox_payload["report_hash"] == terminal["report_hash"]
        assert outbox_payload["terminal_id"] == terminal["terminal_id"]
    finally:
        store.close()
