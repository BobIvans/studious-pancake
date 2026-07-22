"""PR-04 repeated supervisor for the installed sender-free paper service.

The supervisor deliberately reuses the durable A3 cycle authority. It does not
create another lifecycle database and it cannot sign, submit, or enable live
trading. A new cycle is admitted only after the previous durable report says it
is safe to continue.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
import time
from typing import Protocol

from src.paper_shadow.durable_service_a3 import InstalledDurablePaperServiceReport

PR04_SCHEMA = "pr04.repeated-installed-paper-service.v1"


class PaperCycleRunner(Protocol):
    """Small protocol implemented by the existing durable A3 service."""

    async def run_once(self) -> InstalledDurablePaperServiceReport: ...


class RepeatedPaperServiceStopReason(StrEnum):
    SIGNALLED = "signalled"
    MAX_CYCLES = "max_cycles"
    CYCLE_NOT_READY = "cycle_not_ready"


class UnsafePaperServiceReportError(RuntimeError):
    """Raised when a supposedly sender-free cycle exposes an unsafe surface."""


@dataclass(frozen=True, slots=True)
class RepeatedPaperServiceConfig:
    """Bounded scheduling policy frozen for the lifetime of the supervisor."""

    max_cycles: int | None = None
    idle_delay_seconds: float = 0.25
    stop_when_not_ready: bool = True

    def __post_init__(self) -> None:
        if self.max_cycles is not None and self.max_cycles <= 0:
            raise ValueError("max_cycles must be positive or None")
        if self.idle_delay_seconds < 0:
            raise ValueError("idle_delay_seconds must be non-negative")


@dataclass(frozen=True, slots=True)
class RepeatedPaperServiceSummary:
    """Auditable supervisor result without duplicating cycle authority."""

    stop_reason: RepeatedPaperServiceStopReason
    reports: tuple[InstalledDurablePaperServiceReport, ...] = field(
        default_factory=tuple
    )
    started_at_ns: int = 0
    completed_at_ns: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "reports", tuple(self.reports))
        if self.started_at_ns < 0 or self.completed_at_ns < self.started_at_ns:
            raise ValueError("invalid supervisor timestamps")
        for report in self.reports:
            _assert_sender_free(report)

    @property
    def cycle_count(self) -> int:
        return len(self.reports)

    @property
    def final_report(self) -> InstalledDurablePaperServiceReport | None:
        return self.reports[-1] if self.reports else None

    @property
    def summary_hash(self) -> str:
        encoded = _canonical_json(self.to_dict(include_hash=False)).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self, *, include_hash: bool = True) -> dict[str, object]:
        final_report = self.final_report
        payload: dict[str, object] = {
            "schema_version": PR04_SCHEMA,
            "stop_reason": self.stop_reason.value,
            "cycle_count": self.cycle_count,
            "started_at_ns": self.started_at_ns,
            "completed_at_ns": self.completed_at_ns,
            "cycle_ids": [report.cycle_id for report in self.reports],
            "statuses": [report.status.value for report in self.reports],
            "final_report_hash": (
                final_report.report_hash if final_report is not None else None
            ),
            "sender_imported": False,
            "submission_allowed": False,
            "live_enabled": False,
        }
        if include_hash:
            payload["summary_hash"] = self.summary_hash
        return payload


class RepeatedInstalledPaperService:
    """Run durable paper cycles sequentially until a reviewed stop boundary."""

    def __init__(
        self,
        cycle_runner: PaperCycleRunner,
        config: RepeatedPaperServiceConfig | None = None,
        *,
        on_report: Callable[[InstalledDurablePaperServiceReport], None] | None = None,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self.cycle_runner = cycle_runner
        self.config = config or RepeatedPaperServiceConfig()
        self.on_report = on_report
        self.clock_ns = clock_ns
        self._run_lock = asyncio.Lock()

    async def run(self, stop_event: asyncio.Event) -> RepeatedPaperServiceSummary:
        """Run one cycle at a time; never overlap durable attempt ownership."""

        if self._run_lock.locked():
            raise RuntimeError("PR04_SUPERVISOR_ALREADY_RUNNING")
        async with self._run_lock:
            started_at_ns = self.clock_ns()
            reports: list[InstalledDurablePaperServiceReport] = []
            stop_reason = RepeatedPaperServiceStopReason.SIGNALLED

            while True:
                if stop_event.is_set():
                    stop_reason = RepeatedPaperServiceStopReason.SIGNALLED
                    break
                if self._max_cycles_reached(reports):
                    stop_reason = RepeatedPaperServiceStopReason.MAX_CYCLES
                    break

                report = await self.cycle_runner.run_once()
                _assert_sender_free(report)
                reports.append(report)
                if self.on_report is not None:
                    self.on_report(report)

                if not report.ready_for_next_cycle and self.config.stop_when_not_ready:
                    stop_reason = RepeatedPaperServiceStopReason.CYCLE_NOT_READY
                    break
                if self._max_cycles_reached(reports):
                    stop_reason = RepeatedPaperServiceStopReason.MAX_CYCLES
                    break
                if await _wait_for_stop(
                    stop_event,
                    timeout=self.config.idle_delay_seconds,
                ):
                    stop_reason = RepeatedPaperServiceStopReason.SIGNALLED
                    break

            return RepeatedPaperServiceSummary(
                stop_reason=stop_reason,
                reports=tuple(reports),
                started_at_ns=started_at_ns,
                completed_at_ns=self.clock_ns(),
            )

    def _max_cycles_reached(
        self,
        reports: Sequence[InstalledDurablePaperServiceReport],
    ) -> bool:
        maximum = self.config.max_cycles
        return maximum is not None and len(reports) >= maximum


async def _wait_for_stop(stop_event: asyncio.Event, *, timeout: float) -> bool:
    if stop_event.is_set():
        return True
    if timeout == 0:
        await asyncio.sleep(0)
        return stop_event.is_set()
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=timeout)
    except TimeoutError:
        return False
    return True


def _assert_sender_free(report: InstalledDurablePaperServiceReport) -> None:
    if report.sender_imported or report.submission_allowed or report.live_enabled:
        raise UnsafePaperServiceReportError(
            "PR04_UNSAFE_SENDER_SUBMISSION_OR_LIVE_EVIDENCE"
        )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


__all__ = [
    "PR04_SCHEMA",
    "PaperCycleRunner",
    "RepeatedInstalledPaperService",
    "RepeatedPaperServiceConfig",
    "RepeatedPaperServiceStopReason",
    "RepeatedPaperServiceSummary",
    "UnsafePaperServiceReportError",
]
