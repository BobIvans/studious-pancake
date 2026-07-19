import pytest
import pytest
pytestmark = pytest.mark.unit
pytestmark = pytest.mark.unit

import unittest
import asyncio
import time
from src.ingest.arbitrage_scorer import ArbitrageScorer, PriorityArbitrageQueue, ArbitrageOpportunity
from src.ingest.data_collector import DataCollector, ArbitrageTradeRecord


class TestAITradingSystem(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.get_event_loop()
        self.scorer = ArbitrageScorer()
        self.queue = PriorityArbitrageQueue(max_size=10)

    def test_scoring_prioritization_logic(self):
        """Проверяет, что сделка с высоким профитом и низким риском получает больший приоритет."""
        opp_high_profit = ArbitrageOpportunity(
            pair="SOL/USDC",
            expected_profit_sol=0.015,
            slippage_pct=0.01,
            liquidity_depth_usd=150000,
            network_congestion=10.0,
            gas_cost_sol=0.0001,
            execution_time_ms=10,
            timestamp=time.time()
        )
        opp_high_risk = ArbitrageOpportunity(
            pair="SOL/USDC",
            expected_profit_sol=0.001,
            slippage_pct=0.08,
            liquidity_depth_usd=5000,
            network_congestion=80.0,
            gas_cost_sol=0.001,
            execution_time_ms=150,
            timestamp=time.time()
        )

        score_high = self.loop.run_until_complete(
            self.scorer.score_opportunity(opp_high_profit, wallet_balance=0.017)
        )
        score_low = self.loop.run_until_complete(
            self.scorer.score_opportunity(opp_high_risk, wallet_balance=0.017)
        )

        self.assertGreater(score_high, score_low)

    def test_priority_queue_ordering(self):
        """Проверяет строгость соблюдения очередности выполнения по весу (Score)."""
        opp1 = ArbitrageOpportunity("SOL/USDC", 0.002, 0.01, 10000, 10, 0.0001, 10, time.time())
        opp1.score = 50.0

        opp2 = ArbitrageOpportunity("SOL/USDT", 0.010, 0.01, 50000, 10, 0.0001, 10, time.time())
        opp2.score = 90.0

        opp3 = ArbitrageOpportunity("SOL/PYUSD", 0.001, 0.01, 5000, 10, 0.0001, 10, time.time())
        opp3.score = 30.0

        self.queue.add_opportunity(opp1)
        self.queue.add_opportunity(opp2)
        self.queue.add_opportunity(opp3)

        next_opp = self.queue.get_next_opportunity()
        self.assertEqual(next_opp.pair, "SOL/USDT")
        self.assertEqual(next_opp.score, 90.0)


if __name__ == "__main__":
    unittest.main()
