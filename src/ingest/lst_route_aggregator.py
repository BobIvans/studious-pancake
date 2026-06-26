"""Multi-DEX Route Aggregator for LST Arbitrage.

Finds the best buy/sell routes for LST tokens across Jupiter v6 (Orca, Raydium)
and Sanctum Infinity Pool.  Returns structured RouteResult objects containing
the full circuit: MarginFi Borrow → Buy LST → Sell LST → MarginFi Repay.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import aiohttp

# FIX 13: Shared global Jupiter rate limiter — 4 req/s across all modules
from .jupiter_api_client import get_jupiter_limiter

# Backward compatibility aliases for older code that still uses _GLOBAL_JUPITER_LIMITER or _limiter_available
_GLOBAL_JUPITER_LIMITER = None
_limiter_available = False

logger = logging.getLogger("LstRouteAgg")

SOL_MINT = "So11111111111111111111111111111111111111112"
SANCTUM_ROUTER = "stkitrT1Uoy18Dk1fTrgPw8W6MVzoCfYoAFT4MLsmhq"
SANCTUM_INFINITY_POOL = "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm"

JUPITER_QUOTE_URL = os.getenv("JUPITER_QUOTE_API", "https://api.jup.ag/swap/v1/quote")


@dataclass
class RouteQuote:
    """A single leg quote (buy or sell)."""
    __slots__ = ("source", "dex_label", "input_mint", "output_mint", "in_amount", "out_amount", "price_impact_pct", "slippage_bps", "full_quote_response", "route_plan")
    source: str                # "jupiter", "sanctum", etc.
    dex_label: str             # human-readable: "Orca", "Raydium CLMM", "Sanctum Infinity"
    input_mint: str
    output_mint: str
    in_amount: int             # lamports / raw
    out_amount: int            # lamports / raw
    price_impact_pct: float
    slippage_bps: int
    full_quote_response: Dict  # original Jupiter response for TX building
    route_plan: List[str]      # list of DEX names in the route


class RouteResult:
    """Full arbitrage circuit result."""
    __slots__ = ("profit_sol", "profit_bps", "buy_quote", "sell_quote",
                 "borrow_amount_lamports", "route_path", "is_profitable",
                 "total_fees_sol", "timestamp")

    profit_sol: float
    profit_bps: float
    buy_quote: RouteQuote
    sell_quote: RouteQuote
    borrow_amount_lamports: int
    route_path: str
    is_profitable: bool
    total_fees_sol: float
    timestamp: float

    def __init__(
        self,
        profit_sol: float,
        profit_bps: float,
        buy_quote: RouteQuote,
        sell_quote: RouteQuote,
        borrow_amount_lamports: int,
        route_path: str,
        is_profitable: bool,
        total_fees_sol: float,
        timestamp: Optional[float] = None,
    ):
        self.profit_sol = profit_sol
        self.profit_bps = profit_bps
        self.buy_quote = buy_quote
        self.sell_quote = sell_quote
        self.borrow_amount_lamports = borrow_amount_lamports
        self.route_path = route_path
        self.is_profitable = is_profitable
        self.total_fees_sol = total_fees_sol
        self.timestamp = timestamp if timestamp is not None else time.time()


class LstRouteAggregator:
    """Finds optimal buy/sell routes for LST ↔ SOL arbitrage."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        jupiter_api_key: str = "",
        slippage_bps: int = 10,
        sanctum_enabled: bool = True,
    ):
        self.session = session
        self.jupiter_api_key = jupiter_api_key
        self.slippage_bps = slippage_bps
        self.sanctum_enabled = sanctum_enabled

    # ── Public API ────────────────────────────────────────────────────────

    async def find_best_route(
        self,
        borrow_amount_lamports: int,
        lst_mint: str,
        direction: str,         # "BUY_LST" or "SELL_LST"
        base_fee_sol: float = 0.000005,
        priority_fee_sol: float = 0.0001,
        jito_tip_sol: float = 0.0001,
        min_profit_buffer_sol: float = 0.0005,
        wallet_balance_sol: float = 0.0,  # Task 14: wallet balance — forces direct routes when < 0.5 SOL
    ) -> Optional[RouteResult]:
        """Find the best buy+sell route for a given LST depeg opportunity.

        For BUY_LST direction:
          Leg 1 (Buy):  SOL → LST (market is underpriced → buy cheap)
          Leg 2 (Sell): LST → SOL (sell back at fair price via best route)

        For SELL_LST direction:
          Leg 1 (Sell): LST → SOL (market overpriced → sell expensive)
          Leg 2 (Buy):  SOL → LST (buy back at fair price)
          Note: In flash-loan context we always borrow SOL, so SELL_LST
                means: borrow SOL → buy LST at fair → sell at market → repay

        Returns the best RouteResult or None if no profitable route found.
        """
        total_fees = base_fee_sol + priority_fee_sol + jito_tip_sol

        if direction == "BUY_LST":
            # ── Task 16: ExactOut Repayment Guard (Atomic Reliability) ───────────
            # Leg 1: SOL → LST (ExactIn) — Buy as much LST as borrow allows
            buy_quotes = await self._get_quotes(SOL_MINT, lst_mint, borrow_amount_lamports, wallet_balance_sol=wallet_balance_sol)
            if not buy_quotes:
                return None
            
            best_result = None
            for buy_q in buy_quotes:
                # Leg 2: LST → SOL (ExactOut) — Force exact repayment amount
                # We request exactly borrow_amount_lamports output.
                # The in_amount will be the amount of LST needed.
                sell_quotes = await self._get_quotes(
                    lst_mint, SOL_MINT, borrow_amount_lamports, 
                    wallet_balance_sol=wallet_balance_sol, swap_mode="ExactOut"
                )
                if not sell_quotes:
                    continue

                for sell_q in sell_quotes:
                    # Profit calculation for ExactOut:
                    # Total LST bought (buy_q.out_amount) - LST needed for repayment (sell_q.in_amount)
                    # The residual LST is our profit. 
                    # To calculate SOL profit, we use the buy_q price.
                    lst_profit = buy_q.out_amount - sell_q.in_amount
                    if lst_profit <= 0:
                        continue
                        
                    # SOL equivalent of profit using actual exchange rate from sell quote
                    # Fix 35: Use real sell rate (out/in) instead of assuming 1:1 LST:SOL
                    sell_rate = sell_q.out_amount / max(sell_q.in_amount, 1)  # SOL per LST
                    profit_sol = lst_profit * sell_rate / 1e9
                    net_profit = profit_sol - total_fees
                    profit_bps = (lst_profit / buy_q.out_amount) * 10000

                    result = RouteResult(
                        profit_sol=net_profit,
                        profit_bps=profit_bps,
                        buy_quote=buy_q,
                        sell_quote=sell_q,
                        borrow_amount_lamports=borrow_amount_lamports,
                        route_path=f"SOL →({buy_q.dex_label})→ {lst_mint[:8]} →({sell_q.dex_label})→ SOL",
                        is_profitable=net_profit >= min_profit_buffer_sol,
                        total_fees_sol=total_fees,
                    )

                    if best_result is None or result.profit_sol > best_result.profit_sol:
                        best_result = result

            return best_result

        elif direction == "SELL_LST":
            # SELL_LST: Market overprices LST → borrow SOL → mint LST at fair (Sanctum/Jupiter) → sell at market (Jupiter) → repay
            # Leg 1: SOL → LST via Sanctum/Jupiter (fair/cheap mint) — try Sanctum first, fallback Jupiter
            if self.sanctum_enabled:
                buy_quotes = []
                sanctum_q = await self._jupiter_quote(
                    SOL_MINT, lst_mint, borrow_amount_lamports,
                    only_direct_routes=True,
                    dex_filter=["Sanctum", "Sanctum Infinity"],
                    wallet_balance_sol=wallet_balance_sol,
                )
                if sanctum_q and sanctum_q.price_impact_pct < 0.5:
                    buy_quotes.append(sanctum_q)
                else:
                    # Fallback to Jupiter multi-hop
                    fallback = await self._get_quotes(SOL_MINT, lst_mint, borrow_amount_lamports,
                                                      wallet_balance_sol=wallet_balance_sol)
                    if fallback:
                        buy_quotes = fallback
            else:
                buy_quotes = await self._get_quotes(SOL_MINT, lst_mint, borrow_amount_lamports,
                                                    wallet_balance_sol=wallet_balance_sol)

            if not buy_quotes:
                return None

            best_result = None
            for buy_q in buy_quotes:
                # Leg 2: LST → SOL via Jupiter (sell at market-high price) — ExactIn to maximize profit
                sell_quotes = await self._get_quotes(
                    lst_mint, SOL_MINT, buy_q.out_amount,
                    wallet_balance_sol=wallet_balance_sol
                )
                if not sell_quotes:
                    continue
                for sell_q in sell_quotes:
                    lst_profit = sell_q.out_amount - borrow_amount_lamports
                    if lst_profit <= 0:
                        continue

                    profit_sol = lst_profit / 1e9
                    net_profit = profit_sol - total_fees
                    profit_bps = (lst_profit / borrow_amount_lamports) * 10000

                    result = RouteResult(
                        profit_sol=net_profit,
                        profit_bps=profit_bps,
                        buy_quote=buy_q,
                        sell_quote=sell_q,
                        borrow_amount_lamports=borrow_amount_lamports,
                        route_path=f"SOL →({buy_q.dex_label})→ {lst_mint[:8]} →({sell_q.dex_label})→ SOL",
                        is_profitable=net_profit >= min_profit_buffer_sol,
                        total_fees_sol=total_fees,
                    )
                    if best_result is None or result.profit_sol > best_result.profit_sol:
                        best_result = result

            return best_result

        else:
            logger.error(f"Unknown direction: {direction}")
            return None

    # ── Quote fetching ────────────────────────────────────────────────────

    async def _get_quotes(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        dex_filter: Optional[List[str]] = None,
        wallet_balance_sol: float = 0.0,
        swap_mode: str = "ExactIn",
    ) -> List[RouteQuote]:
        """Fetch quotes from Jupiter (multi-hop, includes Sanctum pools)."""
        quotes: List[RouteQuote] = []

        # Task 11: Always use multi-hop to find profitable triangular arbs.
        # The bot has a Deep Rent Guard, so we don't need to force direct routes.
        quote = await self._jupiter_quote(
            input_mint,
            output_mint,
            amount,
            wallet_balance_sol=wallet_balance_sol,
            swap_mode=swap_mode,
            only_direct_routes=False
        )
        if quote:
            quotes.append(quote)

        # If Sanctum enabled, try explicit Sanctum route for LST→SOL direction
        # Sanctum Router работает только с прямыми маршрутами (Direct),
        # поэтому запрашиваем only_direct_routes=True и фильтр по Sanctum (fixed DEXES list).
        if self.sanctum_enabled and self._is_lst_to_sol(input_mint, output_mint):
            sanctum_quote = await self._jupiter_quote(
                input_mint, output_mint, amount,
                only_direct_routes=True,  # Sanctum требует прямых маршрутов
                dex_filter=["Sanctum", "Sanctum Infinity"],  # Принудительно включаем Sanctum (Fix 92)
                wallet_balance_sol=wallet_balance_sol,
                swap_mode=swap_mode,
            )
            if sanctum_quote:
                # Check Sanctum fees (placeholder: assume low fee)
                sanctum_fee_pct = 0.001  # 0.1%
                # Убеждаемся, что Sanctum дает лучший рейт, чем AMM
                # Добавляем только если рейт лучше, чем лучший альтернативный
                if sanctum_quote.price_impact_pct < 0.5:  # Low impact preferred
                    quotes.append(sanctum_quote)

        # Deduplicate by guaranteed output (slippage floor), not optimistic outAmount.
        seen_amounts = set()
        unique_quotes = []
        for q in quotes:
            guaranteed_amount = self._guaranteed_out_amount(q)
            if guaranteed_amount not in seen_amounts:
                seen_amounts.add(guaranteed_amount)
                unique_quotes.append(q)

        # Sort by guaranteed output descending (worst-case slippage floor first).
        unique_quotes.sort(key=self._guaranteed_out_amount, reverse=True)
        return unique_quotes

    @staticmethod
    def _guaranteed_out_amount(q: RouteQuote) -> int:
        return int(q.full_quote_response.get("otherAmountThreshold", q.out_amount))

    def _is_lst_to_sol(self, input_mint: str, output_mint: str) -> bool:
        """Check if this is an LST → SOL swap (Sanctum excels here)."""
        lst_mints = {
            "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",  # jitoSOL
            "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",   # mSOL
            "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",   # bSOL
            "jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v",   # JupSOL
            "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm",   # INF
        }
        return input_mint in lst_mints and output_mint == SOL_MINT

    async def _jupiter_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        only_direct_routes: bool = False,
        dex_filter: Optional[List[str]] = None,
        wallet_balance_sol: float = 0.0,
        swap_mode: str = "ExactIn",
    ) -> Optional[RouteQuote]:
        """Fetch a single quote from Jupiter Quote API v6.

        Args:
            input_mint: Input token mint.
            output_mint: Output token mint.
            amount: Amount in lamports.
            only_direct_routes: If True, only direct routes.
            dex_filter: Optional DEX filter list.
            wallet_balance_sol: Current SOL balance (for ATA routing guard).
            swap_mode: Jupiter swap mode: "ExactIn" or "ExactOut".
        """
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(int(amount)),  # Task 16: strict int→string to avoid HTTP 400
            "slippageBps": self.slippage_bps,
            "onlyDirectRoutes": "true" if only_direct_routes else "false",
            "restrictIntermediateTokens": "false",
            "swapMode": swap_mode,
            "maxAccounts": "28",  # FIX 8: Lowered to 8 for micro-balance safety (prevent ATA drain)
            "cache_buster": str(time.time_ns()),
            # Fix 60: Explicitly exclude Marinade Delayed Unstake accounts
            # Delayed unstake takes 1-2 epochs, would cause flash loan revert
            "excludeDexes": "Marinade",
        }

        # Add DEX filter if specified
        if dex_filter:
            params["dexes"] = ",".join(dex_filter)

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        }
        if self.jupiter_api_key:
            headers["Authorization"] = f"Bearer {self.jupiter_api_key}"

        try:
            timeout = aiohttp.ClientTimeout(total=5.0)

            # Helper to perform the request
            async def do_request() -> Optional[Dict]:
                async with self.session.get(
                    JUPITER_QUOTE_URL, params=params, headers=headers, timeout=timeout
                ) as resp:
                    if resp.status != 200:
                        if resp.status == 429:
                            logger.warning("Jupiter 429 rate limit hit — backoff 2.0s")
                            await asyncio.sleep(2.0)
                            return None
                        error = await resp.text()
                        logger.debug(f"Jupiter quote {resp.status}: {error[:200]}")
                        return None
                    return await resp.json()

            # FIX 13: Acquire global Jupiter rate limiter before each request
            limiter = get_jupiter_limiter()
            if limiter is not None:
                async with limiter:
                    data = await do_request()
            else:
                data = await do_request()

            if not data:
                return None

            in_amount = int(data.get("inAmount", 0))
            out_amount = int(data.get("outAmount", 0))
            if out_amount == 0 or in_amount == 0:
                return None

            # Extract route plan for labeling
            route_plan = data.get("routePlan", [])
            dex_labels = []
            for step in route_plan:
                swap_info = step.get("swapInfo", {})
                label = swap_info.get("label", "Unknown")
                dex_labels.append(label)

            dex_label = " → ".join(dex_labels) if dex_labels else "Jupiter"
            price_impact = float(data.get("priceImpactPct", 0))

            return RouteQuote(
                source="jupiter",
                dex_label=dex_label,
                input_mint=input_mint,
                output_mint=output_mint,
                in_amount=in_amount,
                out_amount=out_amount,
                price_impact_pct=price_impact,
                slippage_bps=self.slippage_bps,
                full_quote_response=data,
                route_plan=dex_labels,
            )

        except asyncio.TimeoutError:
            logger.debug(f"Jupiter quote timeout: {input_mint[:8]}→{output_mint[:8]}")
        except Exception as e:
            logger.warning(f"Jupiter quote error: {e}")
        return None
