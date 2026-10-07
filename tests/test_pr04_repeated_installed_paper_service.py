from __future__ import annotations

import asyncio
from collections.abc import Sequence
import hashlib
import json

import pytest

from src.paper_shadow.durable_service_a3 import (
    A3PaperServiceStatus,
    InstalledDurablePaperServiceReport,
)
from src.paper_shadow.repeated_service_pr04 import (
    RepeatedInstalledPaperService,
    RepeatedPaperServiceConfig,
    RepeatedPaperServiceStopReason,
    UnsafePaperServiceReportError,
)

pytestmark = pytest.mark.unit


def _sha(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _report(
    sequence: int,
    *,
    ready: bool = True,
    status: A3PaperServiceStatus = A3PaperServiceStatus.NO_TRADE,
    sender_imported: bool = False,
) -> InstalledDurablePaperServiceReport:
    return InstalledDurablePaperServiceReport(
        cycle_id=_sha({"cycle": sequence}),
        status=status,
        terminal_reason="no_trade" if ready else "blocked_missing_evidence",
        db_path=":memory:",
        provider_evidence_hash=_sha({"provider": sequence}),
        report_hash=_sha({"report": sequence}),
        ready_for_next_cycle=ready,
        sequence=sequence,
        sender_imported=sender_imported,
    )


class _Runner:
    def __init__(
        self,
        reports: Sequence[InstalledDurablePaperServiceReport],
    ) -> None:
        self.reports = list(reports)
        self.calls = 0
        self.active = 0
        self.max_active = 0

    async def run_once(self) -> InstalledDurablePaperServiceReport:
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0)
        try:
            return self.reports.pop(0)
        finally:
            self.active -= 1


def test_pr04_repeats_ready_cycles_until_configured_bound() -> None:
    runner = _Runner((_report(1), _report(2), _report(3)))
    observed: list[InstalledDurablePaperServiceReport] = []
    service = RepeatedInstalledPaperService(
        runner,
        RepeatedPaperServiceConfig(max_cycles=3, idle_delay_seconds=0),
        on_report=observed.append,
        clock_ns=iter((100, 200)).__next__,
    )

    summary = asyncio.run(service.run(asyncio.Event()))

    assert summary.stop_reason is RepeatedPaperServiceStopReason.MAX_CYCLES
    assert summary.cycle_count == 3
    assert summary.final_report == observed[-1]
    assert runner.calls == 3
    assert runner.max_active == 1
    assert summary.to_dict()["sender_imported"] is False


def test_pr04_stops_immediately_when_durable_cycle_is_not_ready() -> None:
    runner = _Runner((_report(1, ready=False), _report(2)))
    service = RepeatedInstalledPaperService(
        runner,
        RepeatedPaperServiceConfig(max_cycles=10, idle_delay_seconds=0),
        clock_ns=iter((100, 200)).__next__,
    )

    summary = asyncio.run(service.run(asyncio.Event()))

    assert summary.stop_reason is RepeatedPaperServiceStopReason.CYCLE_NOT_READY
    assert summary.cycle_count == 1
    assert runner.calls == 1


def test_pr04_honours_shutdown_during_idle_boundary() -> None:
    runner = _Runner((_report(1), _report(2)))
    stop_event = asyncio.Event()

    def observe(_report: InstalledDurablePaperServiceReport) -> None:
        stop_event.set()

    service = RepeatedInstalledPaperService(
        runner,
        RepeatedPaperServiceConfig(idle_delay_seconds=10),
        on_report=observe,
        clock_ns=iter((100, 200)).__next__,
    )

    summary = asyncio.run(service.run(stop_event))

    assert summary.stop_reason is RepeatedPaperServiceStopReason.SIGNALLED
    assert summary.cycle_count == 1
    assert runner.calls == 1


def test_pr04_rejects_any_sender_submission_or_live_evidence() -> None:
    runner = _Runner(
        (
            _report(
                1,
                ready=False,
                status=A3PaperServiceStatus.INDETERMINATE,
                sender_imported=True,
            ),
        )
    )
    service = RepeatedInstalledPaperService(runner)

    with pytest.raises(
        UnsafePaperServiceReportError,
        match="PR04_UNSAFE_SENDER_SUBMISSION_OR_LIVE_EVIDENCE",
    ):
        asyncio.run(service.run(asyncio.Event()))


def test_pr04_rejects_invalid_scheduler_configuration() -> None:
    with pytest.raises(ValueError, match="max_cycles"):
        RepeatedPaperServiceConfig(max_cycles=0)
    with pytest.raises(ValueError, match="idle_delay"):
        RepeatedPaperServiceConfig(idle_delay_seconds=-0.1)


def test_pressure_boundary_runs_once_per_batch_before_collection():
    from src.intelligence.common import seal

    runner = _Runner([_report(1), _report(2)])
    seen = []

    def boundary(*, batch_id, trigger):
        seen.append((batch_id, trigger, runner.calls))
        return seal({"admission_pause_required": False})

    service = RepeatedInstalledPaperService(
        runner,
        RepeatedPaperServiceConfig(max_cycles=2, idle_delay_seconds=0),
        pressure_boundary=boundary,
    )
    summary = asyncio.run(service.run(asyncio.Event()))
    assert [row[2] for row in seen] == [0, 1]
    assert len({row[0] for row in seen}) == 2
    assert summary.storage_pressure_status == "WIRED"


def test_critical_pressure_pauses_before_new_batch_and_records_blocker():
    from src.intelligence.common import seal

    runner = _Runner([_report(1)])
    blockers = []
    runner.record_storage_pressure_blocker = lambda reason, batch: blockers.append(
        (reason, batch)
    )
    service = RepeatedInstalledPaperService(
        runner, pressure_boundary=lambda **_k: seal({"admission_pause_required": True})
    )
    summary = asyncio.run(service.run(asyncio.Event()))
    assert runner.calls == 0
    assert summary.stop_reason is RepeatedPaperServiceStopReason.STORAGE_PRESSURE
    assert blockers[0][0] == "STORAGE_PRESSURE_ADMISSION_PAUSED"


def test_typed_admission_block_triggers_after_append_rollback(tmp_path):
    from src.agg02.storage import DurableRawJournal
    from src.intelligence.common import seal
    from tests.intelligence.test_pressure_manager import event

    calls = []
    with DurableRawJournal(tmp_path / "raw.db", max_journal_bytes=1) as journal:

        class Collector:
            async def run_once(self):
                journal.append(event(1, b"x"), b"x")

        def boundary(*, batch_id, trigger):
            assert not journal._db.in_transaction
            calls.append(trigger)
            return seal({"admission_pause_required": False})

        summary = asyncio.run(
            RepeatedInstalledPaperService(Collector(), pressure_boundary=boundary).run(
                asyncio.Event()
            )
        )
        assert calls == ["BATCH_BOUNDARY", "AGG02_STORAGE_PRESSURE_ADMISSION_BLOCKED"]
        assert journal.cursor("provider", "pairs") is None
        assert summary.stop_reason is RepeatedPaperServiceStopReason.STORAGE_PRESSURE


def test_unwired_and_failed_pressure_ports_never_retry_blocked_collection():
    from src.agg02.contracts import Agg02Error

    class Collector:
        def __init__(self):
            self.calls = 0
            self.blockers = []

        async def run_once(self):
            self.calls += 1
            raise Agg02Error("AGG02_STORAGE_PRESSURE_ADMISSION_BLOCKED")

        def record_storage_pressure_blocker(self, reason, batch):
            self.blockers.append(reason)

    runner = Collector()
    summary = asyncio.run(RepeatedInstalledPaperService(runner).run(asyncio.Event()))
    assert runner.calls == 1 and runner.blockers == ["BLOCKED_NOT_WIRED"]
    assert summary.storage_pressure_status == "BLOCKED_NOT_WIRED"
    failed = Collector()
    summary = asyncio.run(
        RepeatedInstalledPaperService(failed, pressure_boundary=lambda **_k: {}).run(
            asyncio.Event()
        )
    )
    assert failed.calls == 0
    assert failed.blockers == ["STORAGE_PRESSURE_CYCLE_FAILED"]


def test_pr04_cli_paper_mode_uses_repeated_supervisor() -> None:
    source = open("src/cli.py", encoding="utf-8").read()

    assert "RepeatedInstalledPaperService" in source
    assert "_run_installed_durable_paper_service(config)" in source
    paper_branch = source.split('if mode == "paper":', 1)[1].split(
        'if mode == "disabled":', 1
    )[0]
    assert "_run_installed_durable_paper_service_once" not in paper_branch
    assert (
        "sendTransaction"
        not in open(
            "src/paper_shadow/repeated_service_pr04.py",
            encoding="utf-8",
        ).read()
    )
