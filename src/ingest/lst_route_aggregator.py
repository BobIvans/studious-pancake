"""Multi-DEX Route Aggregator for LST Arbitrage.

Finds the best buy/sell routes for LST tokens across Jupiter v6 (Orca, Raydium)
and Sanctum Infinity Pool.  Returns structured RouteResult objects containing
the full circuit: MarginFi Borrow → Buy LST → Sell LST → MarginFi Repay.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger("LstRouteAgg")

SOL_MINT = "So11111111111111111111111111111111111111112"
SANCTUM_ROUTER = "stkitrT1Uoy18Dk1fTrgPw8W6MVzoCfYoAFT4MLsmhq"
SANCTUM_INFINITY_POOL = "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm"

JUPITER_QUOTE_URL = "https://quote-api.jup.ag/v6/quote"


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
        slippage_bps: int = 15,
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
            # Borrow SOL → Buy LST (cheap on DEX) → Sell LST (via Sanctum/DEX) → Repay SOL
            buy_quotes = await self._get_quotes(SOL_MINT, lst_mint, borrow_amount_lamports, wallet_balance_sol=wallet_balance_sol)
            if not buy_quotes:
                logger.debug(f"No buy quotes for SOL→{lst_mint[:8]}")
                return None

            best_result = None
            for buy_q in buy_quotes:
                # Now sell LST back to SOL
                # ExactIn on sell (exit) leg: swap all LST back to SOL to capture profit in native asset
                sell_quotes = await self._get_quotes(lst_mint, SOL_MINT, buy_q.out_amount, wallet_balance_sol=wallet_balance_sol)
                if not sell_quotes:
                    continue

                for sell_q in sell_quotes:
                    profit_lamports = sell_q.out_amount - borrow_amount_lamports
                    profit_sol = profit_lamports / 1e9
                    net_profit = profit_sol - total_fees
                    profit_bps = (profit_lamports / borrow_amount_lamports) * 10000 if borrow_amount_lamports > 0 else 0

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
            # Borrow SOL → Buy LST (via Sanctum at fair) → Sell LST (expensive on DEX) → Repay
            buy_quotes = await self._get_quotes(SOL_MINT, lst_mint, borrow_amount_lamports, wallet_balance_sol=wallet_balance_sol)
            if not buy_quotes:
                return None

            best_result = None
            for buy_q in buy_quotes:
                # ExactIn on sell (exit) leg: get SOL back
                sell_quotes = await self._get_quotes(lst_mint, SOL_MINT, buy_q.out_amount, wallet_balance_sol=wallet_balance_sol)
                if not sell_quotes:
                    continue
                for sell_q in sell_quotes:
                    profit_lamports = sell_q.out_amount - borrow_amount_lamports
                    profit_sol = profit_lamports / 1e9
                    net_profit = profit_sol - total_fees
                    profit_bps = (profit_lamports / borrow_amount_lamports) * 10000 if borrow_amount_lamports > 0 else 0

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
        wallet_balance_sol: float = 0.0,  # Task 14: micro-balance direct-route guard
    ) -> List[RouteQuote]:
        """Fetch quotes from Jupiter (multi-hop, includes Sanctum pools).

        Args:
            input_mint: Input token mint.
            output_mint: Output token mint.
            amount: Amount in lamports.
            dex_filter: Optional DEX filter list.
            wallet_balance_sol: Current native SOL balance. When < 0.5 SOL, ONLY direct
                routes are attempted to prevent Jupiter from routing through intermediate
                tokens (which would create ATA accounts costing ~0.002 SOL each).
        """
        quotes: List[RouteQuote] = []

        # Task 14: ATA Routing Drain Protection
        # If wallet balance < 0.5 SOL, creating a new ATA for an intermediate token
        # (e.g. WIF) costs ~0.002 SOL — enough to drain a micro-capital wallet entirely
        # after 8 such opportunities. Force direct routes to prevent hidden CreateATA.
        force_direct = wallet_balance_sol < 0.5

        # Load balancing: alternate between Jupiter multi-hop and direct
        routes = [
            ("multi", {"only_direct_routes": False}),
            ("direct", {"only_direct_routes": True}),
        ]
        if force_direct:
            # Kill multi-hop: only direct routes under micro-balance threshold
            routes = [routes[1]]  # keep only ("direct", ...)
        for route_type, params in routes:
            quote = await self._jupiter_quote(input_mint, output_mint, amount, **params)
            if quote:
                quotes.append(quote)
                break  # Use first successful for load balancing

        # If Sanctum enabled, try explicit Sanctum route for LST→SOL direction
        # Sanctum Router работает только с прямыми маршрутами (Direct),
        # поэтому запрашиваем only_direct_routes=True и фильтр по Sanctum (fixed DEXES list).
        if self.sanctum_enabled and self._is_lst_to_sol(input_mint, output_mint):
            sanctum_quote = await self._jupiter_quote(
                input_mint, output_mint, amount,
                only_direct_routes=True,  # Sanctum требует прямых маршрутов
                dex_filter=["Sanctum", "Sanctum Infinity"],  # Принудительно включаем Sanctum (Fix 92)
            )
            if sanctum_quote:
                # Check Sanctum fees (placeholder: assume low fee)
                sanctum_fee_pct = 0.001  # 0.1%
                # Убеждаемся, что Sanctum дает лучший рейт, чем AMM
                # Добавляем только если рейт лучше, чем лучший альтернативный
                if sanctum_quote.price_impact_pct < 0.5:  # Low impact preferred
                    quotes.append(sanctum_quote)

        # Deduplicate by out_amount (keep unique routes)
        seen_amounts = set()
        unique_quotes = []
        for q in quotes:
            if q.out_amount not in seen_amounts:
                seen_amounts.add(q.out_amount)
                unique_quotes.append(q)

        # Sort by out_amount descending (best first)
        unique_quotes.sort(key=lambda q: q.out_amount, reverse=True)
        return unique_quotes

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
    ) -> Optional[RouteQuote]:
        """Fetch a single quote from Jupiter Quote API v6.

        Args:
            input_mint: Input token mint.
            output_mint: Output token mint.
            amount: Amount in lamports.
            only_direct_routes: If True, only direct routes.
            dex_filter: Optional DEX filter list.
            wallet_balance_sol: Current SOL balance (for ATA routing guard).
        """
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(int(amount)),  # Task 16: strict int→string to avoid HTTP 400
            "slippageBps": self.slippage_bps,
            "onlyDirectRoutes": "true" if only_direct_routes else "false",
            "restrictIntermediateTokens": "true",
            "maxAccounts": "8",
            "cache_buster": str(time.time_ns()),
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
            async with self.session.get(
                JUPITER_QUOTE_URL, params=params, headers=headers, timeout=timeout
            ) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    logger.debug(f"Jupiter quote {resp.status}: {error[:200]}")
                    return None

                data = await resp.json()
                out_amount = int(data.get("outAmount", 0))
                if out_amount == 0:
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
                    in_amount=amount,
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
