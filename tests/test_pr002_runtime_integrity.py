from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from src.runtime.trusted_time import TrustedTimeSnapshot
from src.strategy.domain import Opportunity
from src.strategy.queue import OpportunityQueue, QueueAdmissionError, QueueState
from src.strategy.tracker import InMemoryOpportunityTracker, TrackerState


class Clock:
    def __init__(self, wall: float = 100.0, mono: int = 1_000) -> None:
        self.wall, self.mono = wall, mono
    def snapshot(self):
        return TrustedTimeSnapshot(self.mono, datetime.fromtimestamp(self.wall, UTC))


class Ranker:
    async def priority(self, opportunity): return opportunity.expected_gross_profit


def opportunity(clock: Clock, metadata=None):
    return Opportunity(strategy_name="detector", opportunity_type="route", detected_at=clock.wall,
                       detection_slot=7, input_mint="mint-a", output_mint="mint-b",
                       proposed_amount_base_units=10, expected_gross_profit=2,
                       expires_at=clock.wall + 10, metadata=metadata or {})


def test_opportunity_is_content_addressed_deeply_immutable_and_strict():
    clock = Clock(); original = {"route": [{"amount": 10}]}
    first = opportunity(clock, original); second = opportunity(clock, {"route": [{"amount": 10}]})
    original["route"][0]["amount"] = 99
    assert first.opportunity_id == second.opportunity_id
    assert first.metadata["route"][0]["amount"] == 10
    with pytest.raises(TypeError): first.metadata["route"][0]["amount"] = 2
    for invalid in (True, 1.0):
        with pytest.raises(TypeError):
            Opportunity(strategy_name="s", opportunity_type="r", detected_at=1, detection_slot=0,
                        input_mint="a", output_mint="b", proposed_amount_base_units=invalid,
                        expected_gross_profit=1, expires_at=2)
    with pytest.raises(ValueError): opportunity(Clock(float("nan")))


@pytest.mark.asyncio
async def test_expiry_terminalizes_identity_and_wakes_lifecycle():
    clock = Clock(); tracker = InMemoryOpportunityTracker(clock=clock); queue = OpportunityQueue(2, Ranker(), tracker, clock=clock)
    item = opportunity(clock); assert await queue.put(item)
    clock.wall += 11
    assert await queue.expire() == 1
    assert await tracker.state(item.opportunity_id) is TrackerState.EXPIRED
    assert queue.qsize() == 0


@pytest.mark.asyncio
async def test_queue_quiesce_rejects_admission_and_close_is_bounded():
    clock = Clock(); queue = OpportunityQueue(2, Ranker(), clock=clock)
    await queue.quiesce()
    with pytest.raises(QueueAdmissionError): await queue.put(opportunity(clock))
    assert await queue.close(deadline_monotonic_ns=clock.mono) == ()
    assert queue.state is QueueState.CLOSED


@pytest.mark.asyncio
async def test_get_creates_owned_lease_and_ack_terminalizes():
    clock = Clock(); tracker = InMemoryOpportunityTracker(clock=clock); queue = OpportunityQueue(2, Ranker(), tracker, clock=clock)
    item = opportunity(clock); await queue.put(item); assert await queue.get(consumer_id="consumer-1") == item
    assert queue.leases[0].consumer_id == "consumer-1"
    await queue.acknowledge(item.opportunity_id, "handled")
    assert not queue.leases and await tracker.state(item.opportunity_id) is TrackerState.TERMINAL


@pytest.mark.asyncio
async def test_tracker_terminal_replay_window_and_capacity_are_bounded():
    clock = Clock(); tracker = InMemoryOpportunityTracker(capacity=3, replay_ttl_ns=10, clock=clock)
    for item_id in ("a", "b", "c"):
        assert await tracker.mark_pending(item_id); await tracker.terminal(item_id)
    assert not await tracker.mark_pending("a")
    clock.mono += 11
    assert await tracker.mark_pending("d")
    assert len(tracker._states) <= 3
