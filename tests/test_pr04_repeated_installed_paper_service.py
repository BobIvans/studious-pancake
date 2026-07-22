from __future__ import annotations

import asyncio
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
    def __init__(self, reports):
        self.reports = list(reports)
        self.calls = 0
        self.active = 0
        self.max_active = 0

    async def run_once(self):
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0)
        try:
  return self.reports.pop(0)
        finally:
  self.active -= 1


def test_pr04_repeats_ready_cycles_until_configured_bound():
    runner = _Runner((_report(1), _report(2), _report(3)))
    observed = []
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


def test_pr04_stops_immediately_when_durable_cycle_is_not_ready():
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


def test_pr04_honours_shutdown_during_idle_boundary():
    runner = _Runner((_report(1), _report(2)))
    stop_event = asyncio.Event()

    def observe(_report):
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


def test_pr04_rejects_any_sender_submission_or_live_evidence():
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


def test_pr04_rejects_invalid_scheduler_configuration():
    with pytest.raises(ValueError, match="max_cycles"):
        RepeatedPaperServiceConfig(max_cycles=0)
    with pytest.raises(ValueError, match="idle_delay"):
        RepeatedPaperServiceConfig(idle_delay_seconds=-0.1)


def test_pr04_cli_paper_mode_uses_repeated_supervisor():
    source = open("src/cli.py", encoding="utf-8").read()

    assert "RepeatedInstalledPaperService" in source
    assert "_run_installed_durable_paper_service(config)" in source
    paper_branch = source.split('if mode == "paper":', 1)[1].split(
        'if mode == "disabled":', 1
    )[0]
    assert "_run_installed_durable_paper_service_once" not in paper_branch
    assert "sendTransaction" not in open(
        "src/paper_shadow/repeated_service_pr04.py", encoding="utf-8"
    ).read()
