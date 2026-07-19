from __future__ import annotations

import ast
import asyncio
import time
from pathlib import Path

import pytest

from src.application import ConfigurationError, build_application
from src.strategy.consumer import OpportunityConsumer, ShadowOnlyOpportunityHandler
from src.strategy.domain import Opportunity
from src.strategy.interfaces import StrategyContext, StrategyMode
from src.strategy.queue import OpportunityQueue
from src.strategy.registry import StrategyRegistry
from src.strategy.results import InMemoryOpportunityResultSink, OpportunityResultStatus
from src.strategy.runtime import StrategyRuntime
from src.strategy.strategies import BaseDetectionStrategy
from src.strategy.tracker import InMemoryOpportunityTracker

pytestmark = pytest.mark.unit


class Ranker:
    async def priority(self, opportunity: Opportunity) -> float:
        return float(opportunity.expected_gross_profit)


def make_opp(name="one", oid="id", profit=1.0, ttl=10):
    now = time.time()
    return Opportunity(
        strategy_name=name, opportunity_type="fixture", detected_at=now, detection_slot=1,
        input_mint="A", output_mint="B", proposed_amount_base_units=1,
        expected_gross_profit=profit, expires_at=now + ttl, metadata={}, opportunity_id=oid,
    )


class OneShot(BaseDetectionStrategy):
    def __init__(self, name="one", mode=StrategyMode.SHADOW):
        super().__init__(name, mode, poll_interval_seconds=60)
        self.sent = False

    async def detect_once(self):
        if self.sent:
            return ()
        self.sent = True
        return (make_opp(self.name, "fixture-opportunity"),)


class FailingHandler:
    async def handle(self, opportunity, *, mode):
        raise RuntimeError("handler boom")


@pytest.mark.asyncio
async def test_detector_queue_consumer_handler_terminal_result_no_task_leak():
    registry = StrategyRegistry(); registry.register(OneShot())
    tracker = InMemoryOpportunityTracker()
    queue = OpportunityQueue(10, Ranker(), tracker)
    sink = InMemoryOpportunityResultSink()
    handler = ShadowOnlyOpportunityHandler()
    consumer = OpportunityConsumer(queue, registry, tracker, handler, sink)
    runtime = StrategyRuntime(registry, queue, StrategyContext())
    consumer.start(); await runtime.start()
    for _ in range(20):
        if sink.results:
            break
        await asyncio.sleep(0.01)
    await runtime.stop(); await consumer.stop()
    assert len(sink.results) == 1
    result = sink.results[0]
    assert result.status is OpportunityResultStatus.SHADOW_NOT_EXECUTED
    assert result.executed is False
    assert result.reason_code == "execution_backend_out_of_scope"
    assert not runtime.supervisor.tasks
    assert consumer._task is None or consumer._task.done()


def test_default_manifest_disables_unimplemented_production_detectors():
    app = build_application()
    manifest = {entry.name: entry for entry in app.manifest()}
    assert manifest["lst_depeg"].effective_mode == "disabled"
    assert manifest["lst_depeg"].reason == "detector_not_implemented"
    assert manifest["lst_unstake"].reason == "detector_not_implemented"
    assert manifest["circular_arbitrage"].reason == "detector_not_implemented"


@pytest.mark.asyncio
async def test_live_mode_rejected_before_tasks_start():
    class Config:
        strategy_modes = {"lst_depeg": "live"}
        opportunity_queue_size = 10
    app = build_application(Config())
    with pytest.raises(ConfigurationError, match="live mode"):
        await app.run()
    assert not app.context.strategy_runtime.supervisor.tasks


@pytest.mark.asyncio
async def test_start_failure_reflected_in_manifest():
    class StartFail(OneShot):
        async def start(self, context):
            raise RuntimeError("start boom")
    r = StrategyRegistry(); r.register(StartFail("boom"))
    tracker = InMemoryOpportunityTracker(); q = OpportunityQueue(10, Ranker(), tracker)
    sink = InMemoryOpportunityResultSink(); c = OpportunityConsumer(q, r, tracker, ShadowOnlyOpportunityHandler(), sink)
    runtime = StrategyRuntime(r, q, StrategyContext())
    await runtime.start(); await runtime.stop()
    assert runtime.states["boom"] == "start_failed"
    assert runtime.reasons["boom"] == "start boom"


def test_invalid_mode_fails_closed():
    class Config:
        strategy_modes = {"lst_depeg": "paperish"}
    with pytest.raises(ConfigurationError, match="invalid strategy mode"):
        build_application(Config())


@pytest.mark.asyncio
async def test_lifecycle_dedupes_inflight_and_terminal_duplicates():
    r = StrategyRegistry(); r.register(OneShot())
    tracker = InMemoryOpportunityTracker(); q = OpportunityQueue(10, Ranker(), tracker)
    sink = InMemoryOpportunityResultSink(); c = OpportunityConsumer(q, r, tracker, ShadowOnlyOpportunityHandler(), sink)
    a = make_opp(oid="same"); b = make_opp(oid="same")
    assert await q.put(a) is True
    got = await q.get()
    assert await tracker.claim(got.opportunity_id) is True
    assert await q.put(b) is False
    await tracker.terminal(got.opportunity_id)
    assert await q.put(b) is False
    await c.process_one(make_opp(oid="new"))
    assert len(sink.results) == 1


@pytest.mark.asyncio
async def test_expired_opportunity_rejected_before_handler():
    r = StrategyRegistry(); r.register(OneShot())
    tracker = InMemoryOpportunityTracker(); q = OpportunityQueue(10, Ranker(), tracker)
    sink = InMemoryOpportunityResultSink(); c = OpportunityConsumer(q, r, tracker, ShadowOnlyOpportunityHandler(), sink)
    expired = make_opp(ttl=1)
    object.__setattr__(expired, "expires_at", time.time() - 1)
    await c.process_one(expired)
    assert sink.results[0].status is OpportunityResultStatus.REJECTED
    assert sink.results[0].reason_code == "opportunity_expired"


@pytest.mark.asyncio
async def test_full_queue_rejects_worse_and_displaces_worst():
    q = OpportunityQueue(2, Ranker())
    assert await q.put(make_opp(oid="a", profit=10))
    assert await q.put(make_opp(oid="b", profit=5))
    assert await q.put(make_opp(oid="c", profit=1)) is False
    assert await q.put(make_opp(oid="d", profit=20)) is True
    got = [await q.get(), await q.get()]
    assert {o.opportunity_id for o in got} == {"d", "a"}


@pytest.mark.asyncio
async def test_invalid_queue_size_and_rank_rejected():
    with pytest.raises(ValueError):
        OpportunityQueue(0, Ranker())
    class BadRanker:
        async def priority(self, opportunity):
            return float("nan")
    q = OpportunityQueue(1, BadRanker())
    with pytest.raises(ValueError, match="finite"):
        await q.put(make_opp())


@pytest.mark.asyncio
async def test_consumer_continues_after_handler_exception():
    r = StrategyRegistry(); r.register(OneShot())
    tracker = InMemoryOpportunityTracker(); q = OpportunityQueue(10, Ranker(), tracker)
    sink = InMemoryOpportunityResultSink(); c = OpportunityConsumer(q, r, tracker, FailingHandler(), sink)
    await c.process_one(make_opp(oid="bad"))
    c.handler = ShadowOnlyOpportunityHandler()
    await c.process_one(make_opp(oid="good"))
    assert [x.status for x in sink.results] == [OpportunityResultStatus.FAILED, OpportunityResultStatus.SHADOW_NOT_EXECUTED]


def test_active_import_boundaries_and_legacy_safety_regressions():
    forbidden_import_roots = {"src.legacy_arb_bot", "src.ingest.execution_router", "src.ingest.jito_executor"}
    for rel in ["arb_bot.py", "src/application.py"]:
        tree = ast.parse(Path(rel).read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        assert forbidden_import_roots.isdisjoint(imports)
    for path in Path("src/strategy").glob("**/*.py"):
        text = path.read_text()
        assert "jito_executor" not in text
        assert "send_transaction" not in text
        assert "send_bundle" not in text
    assert "await PreTradeGuard.check_gas_tank" in Path("src/ingest/lst_unstake_arbitrage.py").read_text()
    assert "await PreTradeGuard.check_gas_tank" in Path("src/ingest/execution_router.py").read_text()
    combined = Path("src/ingest/lst_unstake_arbitrage.py").read_text() + Path("src/ingest/execution_router.py").read_text()
    assert "5_000 * 1e9" not in combined
