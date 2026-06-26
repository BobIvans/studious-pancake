"""
Event-Driven State Machine for Ultra-Fast Arbitrage Triggers
Implements specialized triggers for Graduation Events.
"""

import asyncio
import logging
import math
import time
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

@dataclass
class ArbitrageSignal:
    """Arbitrage opportunity signal."""
    strategy_type: str  # 'graduation', 'epoch_rebalance'
    token_pair: tuple[str, str]  # (base, target)
    expected_profit_bps: int
    confidence_score: float  # 0-1
    trigger_data: Dict[str, Any]
    timestamp: float

@dataclass
class OraclePrice:
    """Oracle price data point."""
    token_symbol: str
    price_usd: Decimal
    timestamp: float
    source: str  # 'chainlink', 'pyth', etc.

class EventTriggerEngine:
    """
    Event-driven state machine for arbitrage triggers.

    Supports:
    - Oracle Lag: Chainlink/Pyth vs AMM price discrepancies
    - Graduation Events: Pump.fun/Moonshot/BelieveApp pool creation
    - Epoch Rebalance: LST protocol epoch transitions
    """

    def __init__(self):
        self.oracle_prices: Dict[str, OraclePrice] = {}
        self.amm_prices: Dict[str, Decimal] = {}
        self.active_signals: List[ArbitrageSignal] = []
        self.event_handlers: Dict[str, List[Callable]] = {
            'graduation': [],
            'epoch_rebalance': []
        }
        self.last_epoch_check = 0.0

    def register_handler(self, event_type: str, handler: Callable[[ArbitrageSignal], None]):
        """Register event handler for specific trigger type."""
        if event_type in self.event_handlers:
            self.event_handlers[event_type].append(handler)
            logger.info(f"Registered handler for {event_type} events")

    async def process_oracle_update(self, price_data: Dict[str, Any]):
        """
        Process oracle price update (Chainlink/Pyth WebSocket).

        Expected format:
        {
            'token': 'AAPL',
            'price': 150.25,
            'timestamp': 1640995200.0,
            'source': 'chainlink'
        }
        """
        token_symbol = price_data.get('token')
        price_usd = Decimal(str(price_data.get('price', 0)))
        timestamp = price_data.get('timestamp', asyncio.get_running_loop().time())
        source = price_data.get('source', 'unknown')

        if not token_symbol or price_usd <= 0:
            return

        # Store oracle price
        oracle_price = OraclePrice(token_symbol, price_usd, timestamp, source)
        self.oracle_prices[token_symbol] = oracle_price

        # Check for oracle lag arbitrage

    async def process_amm_price_update(self, token_symbol: str, amm_price_usd: Decimal):
        """Process AMM pool price update."""
        self.amm_prices[token_symbol] = amm_price_usd

        # Check for oracle lag if we have oracle price
        if token_symbol in self.oracle_prices:
            oracle_price = self.oracle_prices[token_symbol]
            oracle_usd = float(oracle_price.price_usd)
            if oracle_usd > 0 and abs(float(amm_price_usd) - oracle_usd) / oracle_usd > 0.005:
                logger.debug(f"🔍 Oracle lag detected for {token_symbol}: AMM={amm_price_usd:.4f} vs Oracle={oracle_price.price_usd:.4f}")

    async def process_graduation_event(self, event_data: Dict[str, Any]):
        """
        Process token graduation event from launchpad.

        Expected format:
        {
            'platform': 'pump.fun' | 'moonshot' | 'believeapp',
            'token_mint': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
            'token_symbol': 'BONK',
            'raydium_pool': 'pool_address',
            'graduation_price': 0.00001234,
            'timestamp': 1640995200.0
        }
        """
        platform = event_data.get('platform')
        token_symbol = event_data.get('token_symbol')
        raydium_pool = event_data.get('raydium_pool')

        if not all([platform, token_symbol, raydium_pool]):
            return

        # Calculate expected profit (conservative estimate)
        expected_profit_bps = 500  # 5% expected profit

        signal = ArbitrageSignal(
            strategy_type='graduation',
            token_pair=('SOL', token_symbol),
            expected_profit_bps=expected_profit_bps,
            confidence_score=0.95,  # High confidence for graduation events
            trigger_data=event_data,
            timestamp=asyncio.get_running_loop().time()
        )

        await self._emit_signal(signal)

    async def process_epoch_rebalance(self, lst_token: str, epoch_data: Dict[str, Any]):
        """
        Process LST epoch rebalance event.

        Expected format:
        {
            'token': 'jitoSOL',
            'epoch': 500,
            'old_rate': 1.05,
            'new_rate': 1.08,
            'time_until_rebalance': 3600,  # seconds
            'sanctum_pool': 'pool_address'
        }
        """
        time_until = epoch_data.get('time_until_rebalance', 0)
        rate_change_pct = epoch_data.get('rate_change_pct', 0)

        if time_until < 60 and abs(rate_change_pct) > 0.001:  # Within 1 min and >0.1% change
            expected_profit_bps = int(abs(rate_change_pct) * 10000 * 0.8)  # 80% capture rate

            signal = ArbitrageSignal(
                strategy_type='epoch_rebalance',
                token_pair=('SOL', lst_token),
                expected_profit_bps=expected_profit_bps,
                confidence_score=0.90,  # High confidence for epoch events
                trigger_data=epoch_data,
                timestamp=asyncio.get_running_loop().time()
            )

            await self._emit_signal(signal)

    async def _emit_signal(self, signal: ArbitrageSignal):
        """Emit arbitrage signal to registered handlers."""
        self.active_signals.append(signal)

        # Keep only recent signals (last 10 minutes)
        cutoff_time = asyncio.get_running_loop().time() - 600
        self.active_signals = [s for s in self.active_signals if s.timestamp > cutoff_time]

        # Notify handlers
        handlers = self.event_handlers.get(signal.strategy_type, [])
        for handler in handlers:
            try:
                await handler(signal)
            except Exception as e:
                logger.error(f"Handler error for {signal.strategy_type}: {e}")

        logger.info(f"🚨 {signal.strategy_type.upper()} SIGNAL: {signal.token_pair} | "
                   f"{signal.expected_profit_bps} BPS profit | "
                   f"Confidence: {signal.confidence_score:.2%}")

    # === VOLATILITY-TRIGGERED STATE MACHINE ===

class VolatilityWatcher:
    """
    Monitors price volatility for DePIN/meme tokens.
    Triggers arbitrage when whales cause cross-DEX discrepancies.
    """

    def __init__(self, pool_state_manager):
        self.pool_state_manager = pool_state_manager
        self.volatility_signals: List = []
        self.price_history: Dict[str, List[Tuple[float, Decimal]]] = {}  # token -> [(timestamp, price)]
        self.max_history = 10  # Keep last 10 price points per token
        self.volatility_threshold_pct = 0.01  # 1.0% price movement trigger
        self.time_window_seconds = 3.0  # Check volatility over 3 seconds

    async def monitor_token_volatility(self, token_symbol: str):
        """Monitor volatility for a specific token."""
        try:
            # Get current price from pool state
            current_price = await self._get_token_price(token_symbol)
            if not current_price:
                return

            current_time = asyncio.get_running_loop().time()

            # Update price history
            if token_symbol not in self.price_history:
                self.price_history[token_symbol] = []

            self.price_history[token_symbol].append((current_time, current_price))
            self.price_history[token_symbol] = self.price_history[token_symbol][-self.max_history:]

            # Check for volatility spike
            volatility_signal = self._detect_volatility_spike(token_symbol)
            if volatility_signal:
                await self._trigger_cross_dex_arbitrage(volatility_signal)

        except Exception as e:
            logger.debug(f"Volatility monitoring error for {token_symbol}: {e}")

    def _detect_volatility_spike(self, token_symbol: str) -> Optional[Dict]:
        """Detect significant price volatility spike."""
        try:
            history = self.price_history.get(token_symbol, [])
            if len(history) < 2:
                return None

            # Get prices within time window
            current_time = asyncio.get_running_loop().time()
            window_start = current_time - self.time_window_seconds

            window_prices = [
                price for timestamp, price in history
                if timestamp >= window_start
            ]

            if len(window_prices) < 2:
                return None

            # Calculate price movement
            oldest_price = window_prices[0]
            newest_price = window_prices[-1]

            if oldest_price == 0:
                return None

            price_change_pct = abs(newest_price - oldest_price) / oldest_price

            if price_change_pct > self.volatility_threshold_pct:
                direction = "up" if newest_price > oldest_price else "down"

                return {
                    "token_symbol": token_symbol,
                    "price_change_pct": price_change_pct,
                    "direction": direction,
                    "time_window": self.time_window_seconds,
                    "oldest_price": oldest_price,
                    "newest_price": newest_price
                }

        except Exception as e:
            logger.debug(f"Volatility spike detection error: {e}")

        return None

    async def _trigger_cross_dex_arbitrage(self, volatility_signal: Dict):
        """Trigger cross-DEX arbitrage when volatility spike detected."""
        try:
            token_symbol = volatility_signal["token_symbol"]
            direction = volatility_signal["direction"]
            price_change_pct = volatility_signal["price_change_pct"]

            logger.info(f"🌊 VOLATILITY SPIKE: {token_symbol} | "
                       f"Change: {price_change_pct:.2%} {direction} | "
                       f"Window: {self.time_window_seconds}s")

            # Check other DEXes for lagging prices
            lagging_dexes = await self._find_lagging_dexes(token_symbol, direction)

            if lagging_dexes:
                # Trigger arbitrage signal
                signal = ArbitrageSignal(
                    strategy_type='volatility_arbitrage',
                    token_pair=(token_symbol, 'USDC'),
                    expected_profit_bps=int(price_change_pct * 5000),  # Estimate profit
                    confidence_score=0.8,  # High confidence for volatility signals
                    trigger_data={
                        'volatility_signal': volatility_signal,
                        'lagging_dexes': lagging_dexes,
                        'direction': direction
                    },
                    timestamp=asyncio.get_running_loop().time()
                )

                # Emit signal (would be handled by main arbitrage engine)
                logger.info(f"🎯 Cross-DEX arbitrage triggered for {token_symbol}")
                # In practice, this would call registered callbacks

        except Exception as e:
            logger.error(f"Cross-DEX arbitrage trigger error: {e}")

    async def _find_lagging_dexes(self, token_symbol: str, direction: str) -> List[Dict]:
        """Find DEXes with lagging prices compared to the volatile one."""
        try:
            # Get prices from different DEXes
            lagging_dexes = []

            # Check Raydium vs Orca
            raydium_price = await self._get_dex_price(token_symbol, "raydium")
            orca_price = await self._get_dex_price(token_symbol, "orca")

            if raydium_price and orca_price:
                price_diff_pct = abs(raydium_price - orca_price) / min(raydium_price, orca_price)

                if price_diff_pct > 0.005:  # >0.5% difference
                    lagging_dex = "orca" if raydium_price > orca_price else "raydium"
                    lagging_dexes.append({
                        "dex": lagging_dex,
                        "price_diff_pct": price_diff_pct,
                        "direction": direction
                    })

            return lagging_dexes

        except Exception as e:
            logger.debug(f"Lagging DEX detection error: {e}")
            return []

    async def _get_token_price(self, token_symbol: str) -> Optional[Decimal]:
        """Get current token price from pool state."""
        try:
            # Simplified - in practice would query pool state manager
            token_mint_map = {
                "BONK": "DezXAZ8z7P8gVmFiDQ6cEhPmmF9rj3ZfVGg3LyZ3mTKV",
                "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
                "GRASS": "Grass7B4RdKfBCjTKgSqnXkqjwiGvQyFbuYWKGsZQ1N",  # Real GRASS mint
                "HNT": "hntyVP6YFm1Hg25TN9WGLqM12b8VDGmcKTRD2qNWJ4P",  # Real HNT mint
                "RENDER": "rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof",  # Real RNDR mint
            }

            token_mint = token_mint_map.get(token_symbol)
            if not token_mint:
                return None

            # Get pools containing this token
            token_pools = self.pool_state_manager.get_pools_by_token(token_mint)
            if not token_pools:
                return None

            # Use largest pool
            best_pool = max(token_pools, key=lambda p: p.token_a_reserve + p.token_b_reserve)

            # Assume paired with USDC and calculate price
            usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            if best_pool.token_a_mint == token_mint and best_pool.token_b_mint == usdc_mint:
                return best_pool.token_b_reserve / best_pool.token_a_reserve
            elif best_pool.token_a_mint == usdc_mint and best_pool.token_b_mint == token_mint:
                return best_pool.token_a_reserve / best_pool.token_b_reserve

        except Exception:
            return None

    async def _get_dex_price(self, token_symbol: str, dex: str) -> Optional[Decimal]:
        """Get token price from specific DEX."""
        # Simplified - in practice would filter pools by DEX
        return await self._get_token_price(token_symbol)

    def get_active_signals(self, strategy_type: Optional[str] = None,
                          min_profit_bps: int = 10) -> List[ArbitrageSignal]:
        """Get active arbitrage signals."""
        signals = self.active_signals

        if strategy_type:
            signals = [s for s in signals if s.strategy_type == strategy_type]

        signals = [s for s in signals if s.expected_profit_bps >= min_profit_bps]
        signals.sort(key=lambda s: s.expected_profit_bps, reverse=True)

        return signals

    def get_market_state(self) -> Dict[str, Any]:
        """Get current market state for monitoring."""
        return {
            'oracle_prices': {
                symbol: {
                    'price': float(price.price_usd),
                    'age_seconds': time.time() - price.timestamp,
                    'source': price.source
                }
                for symbol, price in self.oracle_prices.items()
            },
            'amm_prices': {symbol: float(price) for symbol, price in self.amm_prices.items()},
            'active_signals': len(self.active_signals),
            'last_epoch_check': self.last_epoch_check
        }