"""Arbitrage Scoring Engine for prioritizing trading opportunities."""

import logging
import time
from typing import Dict, List, Any, Optional, Tuple
from decimal import Decimal, getcontext
import asyncio
import aiohttp

logger = logging.getLogger(__name__)

# Set high precision for scoring calculations
getcontext().prec = 28

class ArbitrageOpportunity:
    """Represents a single arbitrage opportunity with all relevant data."""
    __slots__ = ("pair", "expected_profit_sol", "slippage_pct", "liquidity_depth_usd", "network_congestion", "gas_cost_sol", "execution_time_ms", "timestamp", "metadata", "score")

    def __init__(
        self,
        pair: str,
        expected_profit_sol: float,
        slippage_pct: float,
        liquidity_depth_usd: float,
        network_congestion: float,
        gas_cost_sol: float,
        execution_time_ms: float,
        timestamp: float,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.pair = pair
        self.expected_profit_sol = expected_profit_sol
        self.slippage_pct = slippage_pct
        self.liquidity_depth_usd = liquidity_depth_usd
        self.network_congestion = network_congestion
        self.gas_cost_sol = gas_cost_sol
        self.execution_time_ms = execution_time_ms
        self.timestamp = timestamp
        self.metadata = metadata or {}
        self.score = 0.0

class ArbitrageScorer:
    """Mathematical scoring engine for arbitrage opportunities."""

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        rpc_url: Optional[str] = None,
        profit_weight: float = 0.5,
        liquidity_weight: float = 0.3,
        risk_weight: float = 0.2,
        time_penalty_factor: float = 0.001
    ):
        self.session = session
        self.rpc_url = rpc_url
        self.profit_weight = profit_weight
        self.liquidity_weight = liquidity_weight
        self.risk_weight = risk_weight
        self.time_penalty_factor = time_penalty_factor

        # Dynamic adjustment factors based on market conditions
        self.market_volatility = 1.0
        self.competition_level = 1.0

    async def score_opportunity(self, opportunity: ArbitrageOpportunity, wallet_balance: float = 0.0) -> float:
        """Calculate comprehensive score for an arbitrage opportunity."""
        try:
            # Base components
            profit_score = self._calculate_profit_score(opportunity)
            liquidity_score = self._calculate_liquidity_score(opportunity)
            risk_score = self._calculate_risk_score(opportunity)

            # Time-based penalty (opportunities lose value over time)
            time_penalty = opportunity.execution_time_ms * self.time_penalty_factor

            # Network congestion adjustment
            congestion_multiplier = 1.0 / (1.0 + opportunity.network_congestion)

            # Market condition adjustments
            volatility_adjustment = 1.0 / self.market_volatility  # Favor stability
            competition_adjustment = 1.0 / self.competition_level  # Favor low competition

            # Weighted final score
            base_score = (
                self.profit_weight * profit_score +
                self.liquidity_weight * liquidity_score -
                self.risk_weight * risk_score
            ) - time_penalty

            final_score = base_score * congestion_multiplier * volatility_adjustment * competition_adjustment

            # Priority Scoring: Boost stables if balance is low (< 0.02 SOL)
            stable_keywords = ["USD", "PYUSD", "USDe", "susDS"]
            is_stable = any(kw in opportunity.pair for kw in stable_keywords)
            if wallet_balance > 0 and wallet_balance < 0.02 and is_stable:
                final_score *= 1.5
                logger.debug(f"💎 Boosted stable score for {opportunity.pair} (Balance: {wallet_balance} SOL)")

            opportunity.score = float(final_score)
            return opportunity.score

        except Exception as e:
            logger.warning(f"Failed to score opportunity for {opportunity.pair}: {e}")
            return 0.0

    def _calculate_profit_score(self, opp: ArbitrageOpportunity) -> float:
        """Calculate profit attractiveness score (0-100) based on NET profit."""
        # Вычитаем стоимость газа и чаевые Jito
        net_profit = opp.expected_profit_sol - opp.gas_cost_sol

        # Если в метаданных сохранен размер чаевых, вычитаем его
        tip_sol = opp.metadata.get("tip_lamports", 0) / 1e9
        net_profit -= tip_sol

        if net_profit <= 0:
            return 0.0

        profit = net_profit

        if profit < 0.001:  # < 0.001 SOL
            return profit * 1000  # Linear for small profits
        elif profit < 0.01:  # 0.001 - 0.01 SOL
            return 10 + (profit - 0.001) * 900
        elif profit < 0.1:   # 0.01 - 0.1 SOL
            return 55 + (profit - 0.01) * 450
        else:  # > 0.1 SOL
            return 100  # Cap at maximum

    def _calculate_liquidity_score(self, opp: ArbitrageOpportunity) -> float:
        """Calculate liquidity depth score (0-100)."""
        liquidity = opp.liquidity_depth_usd

        if liquidity < 1000:  # < $1k
            return liquidity / 10  # 0-100 points
        elif liquidity < 10000:  # $1k - $10k
            return 100 + (liquidity - 1000) / 90  # 100-111 points
        elif liquidity < 100000:  # $10k - $100k
            return 111 + (liquidity - 10000) / 900  # 111-122 points
        else:  # > $100k
            return min(122 + (liquidity - 100000) / 10000, 150)  # Cap at 150

    def _calculate_risk_score(self, opp: ArbitrageOpportunity) -> float:
        """Calculate risk penalty score (0-50, higher = more risky)."""
        slippage_risk = opp.slippage_pct * 25  # 0-25 points for slippage
        gas_risk = opp.gas_cost_sol * 1000  # Gas cost penalty
        time_risk = opp.execution_time_ms / 10  # Time-based risk

        total_risk = slippage_risk + gas_risk + time_risk

        # Apply market condition adjustments
        total_risk *= self.market_volatility
        total_risk *= self.competition_level

        return min(total_risk, 50)  # Cap risk penalty

    async def update_market_conditions(self):
        """Update dynamic market condition factors."""
        try:
            if not self.session or not self.rpc_url:
                return

            # Get recent network congestion
            congestion = await self._get_network_congestion()
            self.competition_level = 1.0 + (congestion / 100.0)  # Higher congestion = more competition

            # Estimate market volatility from recent price changes
            volatility = await self._estimate_market_volatility()
            self.market_volatility = 1.0 + volatility

        except Exception as e:
            logger.debug(f"Failed to update market conditions: {e}")

    async def _get_network_congestion(self) -> float:
        """Get current network congestion level."""
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getRecentPrioritizationFees",
                "params": [{"last": 10}]
            }

            async with self.session.post(self.rpc_url, json=payload, timeout=aiohttp.ClientTimeout(total=1.0)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "result" in data and data["result"]:
                        fees = [fee["prioritizationFee"] for fee in data["result"]]
                        avg_fee = sum(fees) / len(fees) if fees else 0
                        # Normalize to 0-100 scale
                        return min(avg_fee / 1000, 100)  # Micro-lamports to congestion score
        except Exception as e:
            logger.debug(f"Failed to get network congestion: {e}")

        return 50  # Default moderate congestion

    async def _estimate_market_volatility(self) -> float:
        """Estimate current market volatility."""
        # Placeholder - would analyze recent price movements
        # For now, return moderate volatility
        return 0.5

    def get_score_thresholds(self) -> Dict[str, float]:
        """Get recommended score thresholds for different actions."""
        return {
            "execute_immediately": 80.0,
            "queue_high_priority": 60.0,
            "queue_normal": 40.0,
            "ignore": 20.0
        }


class PriorityArbitrageQueue:
    """Priority queue for arbitrage opportunities using scoring."""

    def __init__(self, max_size: int = 100):
        self.queue: List[Tuple[float, ArbitrageOpportunity]] = []
        self.max_size = max_size
        # Reactive event trigger: wake up processor instantly (0ms latency)
        self._event = asyncio.Event()

    def add_opportunity(self, opportunity: ArbitrageOpportunity):
        """Add opportunity to priority queue."""
        # Insert with negative score for max-heap behavior (highest score first)
        entry = (-opportunity.score, opportunity)

        # Insert in sorted order
        self.queue.append(entry)
        self.queue.sort(key=lambda x: x[0])  # Sort by negative score (highest first)

        # Maintain max size
        if len(self.queue) > self.max_size:
            self.queue.pop()  # Remove lowest priority

        # Trigger reactive event
        self._event.set()

    def get_next_opportunity(self) -> Optional[ArbitrageOpportunity]:
        """Get highest priority opportunity (synchronous)."""
        while self.queue:
            score, opportunity = self.queue.pop(0)

            # Check if opportunity is still fresh (not older than 5 seconds)
            if time.time() - opportunity.timestamp <= 5.0:
                return opportunity
            # Stale opportunity removed, continue to next

        return None

    async def get_next_opportunity_async(self) -> ArbitrageOpportunity:
        """Reactive task getter: sleeps until a signal arrives, then wakes up instantly."""
        while True:
            # If queue is empty, wait for the next set() call from add_opportunity
            if not self.queue:
                self._event.clear()
                await self._event.wait()

            current_time = time.time()
            # Flush stale signals (older than 5s) before processing
            self.queue = [
                (s, opp) for s, opp in self.queue if current_time - opp.timestamp <= 5.0
            ]

            if self.queue:
                score, opportunity = self.queue.pop(0)
                return opportunity
            else:
                # If all signals were stale, reset event and wait again
                self._event.clear()

    def peek_next_opportunity(self) -> Optional[ArbitrageOpportunity]:
        """Peek at next opportunity without removing it."""
        if not self.queue:
            return None

        score, opportunity = self.queue[0]

        if time.time() - opportunity.timestamp > 5.0:
            # Remove stale opportunity and try again
            self.queue.pop(0)
            return self.peek_next_opportunity()

        return opportunity

    def size(self) -> int:
        """Get current queue size."""
        # Clean stale entries
        current_time = time.time()
        self.queue = [(s, opp) for s, opp in self.queue if current_time - opp.timestamp <= 5.0]
        return len(self.queue)

    def clear(self):
        """Clear all opportunities."""
        self.queue.clear()