from __future__ import annotations

import asyncio
import time

import pytest

from src.strategy.domain import Opportunity
from src.strategy.execution import post_send_processing
from src.strategy.interfaces import StrategyContext, StrategyMode
from src.strategy.queue import OpportunityQueue
from src.strategy.registry import StrategyRegistry
from src.strategy.runtime import StrategyRuntime, TaskSupervisor
from src.strategy.strategies import BaseDetectionStrategy

pytestmark = pytest.mark.unit


class ConstantRanker:
    async def priority(self, opportunity: Opportunity) -> float:
        return float(opportunity.expected_gross_profit)


def opp(name="s", oid=None, ttl=10):
    return Opportunity.create(
        strategy_name=name, opportunity_type="test", detection_slot=1,
        input_mint="A", output_mint="B", proposed_amount_base_units=1,
        expected_gross_profit=1.0, ttl_seconds=ttl,
        metadata={"features": {}},
    ) if oid is None else Opportunity(
        opportunity_id=oid, strategy_name=name, opportunity_type="test", detected_at=time.time(),
        detection_slot=1, input_mint="A", output_mint="B", proposed_amount_base_units=1,
        expected_gross_profit=1.0, expires_at=time.time()+ttl, metadata={},
    )


class OneShotStrategy(BaseDetectionStrategy):
    def __init__(self, name="one", mode=StrategyMode.SHADOW):
        super().__init__(name, mode, poll_interval_seconds=60)
        self.started = False
        self.stopped = False
        self._sent = False

    async def start(self, context: StrategyContext) -> None:
        self.started = True
        assert not hasattr(context, "send_transaction")
        await super().start(context)

    async def stop(self) -> None:
        self.stopped = True
        await super().stop()

    async def detect_once(self):
        if self._sent:
            return ()
        self._sent = True
        return (opp(self.name),)


class FailingStrategy(OneShotStrategy):
    async def opportunities(self):
        raise RuntimeError("boom")
        yield


@pytest.mark.asyncio
async def test_disabled_strategies_do_not_start():
    s = OneShotStrategy(mode=StrategyMode.DISABLED)
    r = StrategyRegistry(); r.register(s)
    q = OpportunityQueue(10, ConstantRanker())
    rt = StrategyRuntime(r, q)
    await rt.start(); await rt.stop()
    assert not s.started


@pytest.mark.asyncio
async def test_shadow_strategies_detect_and_enqueue_opportunities():
    s = OneShotStrategy(mode=StrategyMode.SHADOW)
    r = StrategyRegistry(); r.register(s)
    q = OpportunityQueue(10, ConstantRanker())
    rt = StrategyRuntime(r, q)
    await rt.start()
    got = await asyncio.wait_for(q.get(), 1)
    await rt.stop()
    assert got.strategy_name == "one"


@pytest.mark.asyncio
async def test_one_strategy_failure_does_not_stop_others():
    r = StrategyRegistry(); r.register(FailingStrategy("bad")); r.register(OneShotStrategy("good"))
    q = OpportunityQueue(10, ConstantRanker())
    rt = StrategyRuntime(r, q)
    await rt.start()
    got = await asyncio.wait_for(q.get(), 1)
    await rt.stop()
    assert got.strategy_name == "good"
    assert q.metrics["bad"].last_error == "boom"


def test_duplicate_registration_fails():
    r = StrategyRegistry(); r.register(OneShotStrategy("dup"))
    with pytest.raises(ValueError):
        r.register(OneShotStrategy("dup"))


@pytest.mark.asyncio
async def test_duplicate_opportunities_are_deduplicated():
    q = OpportunityQueue(10, ConstantRanker())
    a = opp("s", oid="same"); b = opp("s", oid="same")
    assert await q.put(a) is True
    assert await q.put(b) is False
    assert q.qsize() == 1


def test_expired_opportunities_are_removed():
    q = OpportunityQueue(10, ConstantRanker())
    expired = Opportunity(
        opportunity_id="expired", strategy_name="s", opportunity_type="t", detected_at=time.time()-2,
        detection_slot=1, input_mint="A", output_mint="B", proposed_amount_base_units=1,
        expected_gross_profit=1.0, expires_at=time.time()-1, metadata={},
    )
    q._heap.append((-1.0, expired.expires_at, expired.opportunity_id, expired)); q._ids.add("expired")
    assert q.expire() == 1
    assert q.qsize() == 0


@pytest.mark.asyncio
async def test_shutdown_cancels_and_awaits_all_runtime_tasks():
    sup = TaskSupervisor()
    async def sleeper():
        await asyncio.sleep(100)
    sup.create(sleeper(), name="sleep")
    await sup.shutdown()
    assert not sup.tasks


def test_strategies_cannot_access_or_invoke_transaction_senders():
    ctx = StrategyContext(config={})
    assert not hasattr(ctx, "jito_executor")
    assert not hasattr(ctx, "send_transaction")


@pytest.mark.asyncio
async def test_post_processing_cannot_resubmit_transactions():
    result = await post_send_processing({"status": "failed"})
    assert result["resubmitted"] is False


def test_every_opportunity_has_unique_id_and_expiration():
    a = opp(); b = opp()
    assert a.opportunity_id != b.opportunity_id
    assert a.expires_at > a.detected_at
