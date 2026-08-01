"""Application-level opportunity consumer; never builds or sends transactions."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from .domain import Opportunity
from .interfaces import StrategyMode
from .queue import OpportunityQueue
from .registry import StrategyRegistry
from .results import (
    OpportunityResult,
    OpportunityResultSink,
    OpportunityResultStatus,
    make_result,
)
from .tracker import InMemoryOpportunityTracker, TrackerState
from src.runtime.trusted_time import SystemTrustedTime, TrustedTime
from .queue import QueueClosed


@dataclass(frozen=True, slots=True)
class PrecheckDecision:
    allowed: bool
    reason_code: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


class OpportunityPrecheck(Protocol):
    async def assess(self, opportunity: Opportunity) -> PrecheckDecision: ...


class ConfiguredCapitalPrecheck:
    """Fail-closed PR-199 economic precheck for shadow candidates.

    The legacy implementation compared ``gross_profit_base_units`` directly
    with lamport-denominated policy values. PR-199 replaces that with a
    native/wSOL-only, fee/rent/tip/protocol-cost-bound capital gate while
    preserving the historical weak-edge rejection code for existing telemetry.
    """

    def __init__(self, config: Any = None) -> None:
        self.config = config

    async def assess(self, opportunity: Opportunity) -> PrecheckDecision:
        from src.economics.execution_vertical_pr199 import (
            assess_shadow_opportunity_pr199,
        )

        report = assess_shadow_opportunity_pr199(opportunity, self.config)
        return PrecheckDecision(
            allowed=report.allowed,
            reason_code=report.reason_code,
            details=dict(report.details),
        )


class OpportunityHandler(Protocol):
    async def handle(
        self, opportunity: Opportunity, *, mode: StrategyMode
    ) -> OpportunityResult: ...


class ShadowOnlyOpportunityHandler:
    async def handle(
        self, opportunity: Opportunity, *, mode: StrategyMode
    ) -> OpportunityResult:
        started_at = time.time()
        return make_result(
            opportunity_id=opportunity.opportunity_id,
            strategy_name=opportunity.strategy_name,
            mode=mode,
            status=OpportunityResultStatus.SHADOW_NOT_EXECUTED,
            reason_code="execution_backend_out_of_scope",
            started_at=started_at,
        )


class CapitalAwareShadowOpportunityHandler:
    """Run a read-only capital precheck before accepting shadow candidates."""

    def __init__(
        self,
        precheck: OpportunityPrecheck,
        delegate: OpportunityHandler | None = None,
    ) -> None:
        self.precheck = precheck
        self.delegate = delegate or ShadowOnlyOpportunityHandler()

    async def handle(
        self, opportunity: Opportunity, *, mode: StrategyMode
    ) -> OpportunityResult:
        started_at = time.time()
        decision = await self.precheck.assess(opportunity)
        if not decision.allowed:
            return make_result(
                opportunity_id=opportunity.opportunity_id,
                strategy_name=opportunity.strategy_name,
                mode=mode,
                status=OpportunityResultStatus.REJECTED,
                reason_code=decision.reason_code,
                started_at=started_at,
                details=dict(decision.details),
            )
        return await self.delegate.handle(opportunity, mode=mode)


@dataclass(slots=True)
class OpportunityConsumerMetrics:
    handled: int = 0
    rejected: int = 0
    failed: int = 0
    cancelled: int = 0
    duplicates: int = 0
    last_error: str | None = None


class OpportunityConsumer:
    def __init__(
        self,
        queue: OpportunityQueue,
        registry: StrategyRegistry,
        tracker: InMemoryOpportunityTracker,
        handler: OpportunityHandler,
        sink: OpportunityResultSink,
        *, clock: TrustedTime | None = None,
    ) -> None:
        self.queue = queue
        self.registry = registry
        self.tracker = tracker
        self.handler = handler
        self.sink = sink
        self.clock = clock or SystemTrustedTime()
        self.metrics = OpportunityConsumerMetrics()
        self._task: asyncio.Task | None = None
        self._stopping = False
        self.ready = False

    def start(self) -> None:
        if self._task and not self._task.done():
            raise RuntimeError("opportunity consumer already started")
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name="opportunity-consumer")
        self.ready = True

    async def stop(self) -> None:
        self._stopping = True
        self.ready = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        try:
            while True:
                opp = await self.queue.get(consumer_id="opportunity-consumer")
                await self.process_one(opp)
        except QueueClosed:
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            self.ready = False
            raise

    async def process_one(self, opp: Opportunity) -> None:
        started = self.clock.snapshot().utc.timestamp()
        leased = any(lease.item_id == opp.opportunity_id for lease in self.queue.leases)
        if not leased and not await self.tracker.claim(opp.opportunity_id):
            self.metrics.duplicates += 1
            return
        terminal = False
        try:
            if opp.expires_at <= started:
                await self._record(
                    opp,
                    StrategyMode.DISABLED,
                    OpportunityResultStatus.REJECTED,
                    "opportunity_expired",
                    started,
                )
            else:
                strategy = self.registry.get(opp.strategy_name)
                if strategy is None:
                    await self._record(opp, StrategyMode.DISABLED, OpportunityResultStatus.REJECTED, "unknown_strategy", started)
                elif strategy.mode is StrategyMode.DISABLED:
                    await self._record(opp, strategy.mode, OpportunityResultStatus.REJECTED,
                                       strategy.disabled_reason or "strategy_disabled", started)
                elif strategy.mode is StrategyMode.LIVE:
                    await self._record(opp, strategy.mode, OpportunityResultStatus.REJECTED,
                                       "live_execution_out_of_scope", started)
                elif strategy.mode is StrategyMode.SHADOW:
                    result = await self.handler.handle(opp, mode=strategy.mode)
                    await self.sink.record(result)
                    if result.status is OpportunityResultStatus.REJECTED:
                        self.metrics.rejected += 1
                    else:
                        self.metrics.handled += 1
                else:
                    await self._record(opp, StrategyMode.DISABLED, OpportunityResultStatus.REJECTED,
                                       "invalid_strategy_mode", started)
            terminal = True
        except asyncio.CancelledError:
            self.metrics.cancelled += 1
            await self._record(
                opp,
                StrategyMode.DISABLED,
                OpportunityResultStatus.CANCELLED,
                "consumer_cancelled",
                started,
            )
            raise
        except Exception as exc:
            self.metrics.failed += 1
            self.metrics.last_error = str(exc)
            await self._record(
                opp,
                StrategyMode.DISABLED,
                OpportunityResultStatus.FAILED,
                "handler_exception",
                started,
                {"error_type": type(exc).__name__},
            )
            terminal = True
        finally:
            if any(lease.item_id == opp.opportunity_id for lease in self.queue.leases):
                if terminal:
                    await self.queue.acknowledge(opp.opportunity_id, "terminal")
                else:
                    self.ready = False
                    await self.queue.recover(opp, quarantine=True)
            else:
                await self.tracker.terminal(
                    opp.opportunity_id,
                    TrackerState.TERMINAL if terminal else TrackerState.QUARANTINED,
                )

    async def _record(
        self,
        opp: Opportunity,
        mode: StrategyMode,
        status: OpportunityResultStatus,
        reason: str,
        started: float,
        details: dict[str, Any] | None = None,
    ) -> None:
        if status is OpportunityResultStatus.REJECTED:
            self.metrics.rejected += 1
        await self.sink.record(
            make_result(
                opportunity_id=opp.opportunity_id,
                strategy_name=opp.strategy_name,
                mode=mode,
                status=status,
                reason_code=reason,
                started_at=started,
                details=details,
            )
        )
