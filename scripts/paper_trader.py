#!/usr/bin/env python3
"""
Paper Trading Simulator — SINGLE-AGGREGATOR (Jupiter)
Mirrors arb_bot atomic execution: one aggregator per leg, no cross-exchange hybrids.
Cross-aggregator mixing (buy Jupiter / sell OKX) is impossible in a single atomic
flashloan transaction and was removed to eliminate profit illusions.
"""

import asyncio
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any

sys.path.insert(0, str(Path(__file__).parent.parent))
import socket
import aiohttp
from src.ingest.data_aggregator import DataAggregator
from src.ingest.pyth_core_price_feeder import get_pyth_core_feeder
from src.config.addresses import XSTOCK_MINTS

# ============================================================================
# ДИНАМИЧЕСКАЯ ЗАГРУЗКА ПАР ИЗ ТВОИХ РЕЕСТРОВ
# ============================================================================
BASE_TOKENS = {
    "SOL": "So11111111111111111111111111111111111111112",
    "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
}

LST_TOKENS = {
    "INF": "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm",
    "jitoSOL": "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
    "mSOL": "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",
    "bSOL": "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",
    "JupSOL": "jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v",
}

DEPIN_MEME_TOKENS = {
    "JUP": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "RENDER": "rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof",
    "GRASS": "Grass7B4RdKfBCjTKgSqnXkqjwiGvQyFbuYWKGsZQ1N",
    "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "BONK": "DezXAZ8z7P8gVmFiDQ6cEhPmmF9rj3ZfVGg3LyZ3mTKV"
}

# Объединяем все в один словарь для удобного поиска имени по адресу
ALL_TOKENS = {**BASE_TOKENS, **LST_TOKENS, **XSTOCK_MINTS, **DEPIN_MEME_TOKENS}

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger("MultiTrader")

class PaperTrader:
    def __init__(self):
        self.starting_balance = float(os.getenv("PAPER_TRADE_SIZE_SOL", "0.015"))
        self.current_balance = self.starting_balance
        self.total_profit = 0.0
        self.trades = 0
        self.session = None

        # RPS limits
        self.jup_rps = int(os.getenv("JUPITER_QUOTE_RPS", 5))

        # Semaphore for Jupiter RPS control
        self.jup_sem = asyncio.Semaphore(self.jup_rps)

        logger.info(f"🚀 Инициализация. Jupiter RPS: {self.jup_rps}")
        logger.info(f"📊 Загружено токенов: LST({len(LST_TOKENS)}), DePIN({len(DEPIN_MEME_TOKENS)})")

    async def initialize(self):
        connector = aiohttp.TCPConnector(limit=0, ttl_dns_cache=300, family=socket.AF_INET)
        self.session = aiohttp.ClientSession(connector=connector)

        self.aggregator = DataAggregator(os.getenv("PAPER_TRADING_DB", "paper_trading.db"))
        self.simulator = None  # Simulator implemented elsewhere
        self.oracle = None
        self.pyth_feeder = get_pyth_core_feeder()
        if self.oracle:
            asyncio.create_task(self.oracle.start())
        logger.info("🕸️ OracleStreams отключен (oracle_streams.py удалён)")

    async def _on_oracle_opportunity(self, opp: dict):
        """Коллбек, который срабатывает, когда WebSockets видят лаг оракула"""
        logger.info(f"🚨 [WEBSOCKET СИГНАЛ] Oracle Lag: {opp.get('ticker')} | Оракул: ${opp.get('oracle_price'):.2f} | Спред: {opp.get('price_diff_pct', 0)*100:.2f}%")

    async def _fetch_jupiter(self, input_mint: str, output_mint: str, amount: int):
        async with self.jup_sem:
            url = os.getenv("JUPITER_QUOTE_API", "https://api.jup.ag/swap/v1/quote")
            jup_key = os.getenv("JUPITER_API_KEY", "")
            headers = {
                "x-api-key": jup_key,
                "Authorization": f"Bearer {jup_key}"
            } if jup_key else {}
            # Fix 77: Safe str() wrapping on input_mint/output_mint to prevent
            # TypeError when Pubkey objects are passed instead of strings
            params = {
                "inputMint": str(input_mint),
                "outputMint": str(output_mint),
                "amount": str(int(amount)),
                "slippageBps": "15",
                "onlyDirectRoutes": "false",
                "restrictIntermediateTokens": "false",
            }
            try:
                async with self.session.get(url, params=params, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {"source": "Jupiter", "out": int(data["outAmount"])}
            except Exception as e:
                logger.warning(f"Jupiter query failed: {repr(e)}")
            await asyncio.sleep(1.0 / self.jup_rps)
        return None

    async def _scan_route(self, base_mint: str, target_mint: str, amount: int):
        """Single-aggregator Jupiter-only scan — mirrors arb_bot atomic execution.

        Cross-aggregator hybrids (buy Jupiter / sell OKX) are impossible in a
        single atomic flashloan transaction and were removed.
        """
        base_name = next((k for k, v in ALL_TOKENS.items() if str(v) == base_mint), base_mint[:4])
        target_name = next((k for k, v in ALL_TOKENS.items() if str(v) == target_mint), target_mint[:4])

        # Buy leg: Jupiter only
        buy = await self._fetch_jupiter(base_mint, target_mint, amount)
        if not buy:
            return
        logger.info(f"🔎 {base_name} ➔ {target_name} | Jupiter buy confirmed")

        # Sell leg: same Jupiter only — atomic single-aggregator outcome
        sell = await self._fetch_jupiter(target_mint, base_mint, buy["out"])
        if not sell:
            return

        final_amount = int(sell["out"] * (1 - 15 / 10000))

        # Phase 12: Cross-Currency Accounting — normalize ALL profit to SOL before
        # subtracting fees (which are always in SOL).  Old code subtracted SOL lamports
        # directly from USDC micro-units, corrupting profit for non-SOL routes.
        _usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        _usdt_mint = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
        _is_stable_6dec = base_mint.endswith(_usdc_mint) or base_mint.endswith(_usdt_mint)
        _base_dec = 6 if _is_stable_6dec else 9

        gross_profit_native = final_amount - amount  # in token native units (e.g. USDC micro-units)

        if gross_profit_native > 0:
            # Step 1: convert gross profit to SOL immediately
            gross_profit_ui = gross_profit_native / (10 ** _base_dec)  # UI units (e.g. 1.5 USDC)
            sol_price = self.pyth_feeder.get_price("So11111111111111111111111111111111111111112") if self.pyth_feeder else 150.0
            if _base_dec == 6:
                gross_profit_sol = gross_profit_ui / sol_price  # convert USDC → SOL via USD bridge
            else:
                gross_profit_sol = gross_profit_ui  # already in SOL

            # Step 2: all fees strictly in SOL
            flashloan_fee_sol = 0.0  # MarginFi flashloan fee is 0%
            dex_fee_sol = (amount * 0.003) / 1e9
            slippage_bps = 15
            compute_cost_sol = 5000 / 1e9
            network_fee_sol = 5000 / 1e9
            priority_fee_sol = 10000 / 1e9
            jito_tip_sol = gross_profit_sol * 0.4
            ata_rent_sol = 2_039_280 / 1e9  # ATA rent if new account needed
            total_fees_sol = (
                flashloan_fee_sol + dex_fee_sol + compute_cost_sol +
                network_fee_sol + priority_fee_sol + jito_tip_sol +
                ata_rent_sol
            )
            net_profit_sol = gross_profit_sol - total_fees_sol
            net_profit_lamports = int(net_profit_sol * 1e9)
            roi_pct = (net_profit_sol / (gross_profit_sol + 1e-12)) * 100 if amount > 0 else 0.0
            decision = "EXECUTE" if net_profit_sol > 0.0005 else "SKIP_LOW_MARGIN"

            trade_data = {
                "route": f"{base_name}->{target_name}->{base_name}",
                "token_in": base_mint,
                "token_out": target_mint,
                "amount_lamports": amount,
                "gross_revenue_lamports": final_amount,
                "flashloan_fee_lamports": int(flashloan_fee_sol * 1e9),
                "dex_fee_lamports": int(dex_fee_sol * 1e9),
                "slippage_bps": slippage_bps,
                "compute_cost_lamports": int(compute_cost_sol * 1e9),
                "network_fee_lamports": int(network_fee_sol * 1e9),
                "priority_fee_lamports": int(priority_fee_sol * 1e9),
                "jito_tip_lamports": int(jito_tip_sol * 1e9),
                "ata_rent_lamports": int(ata_rent_sol * 1e9),
                "total_cost_lamports": int(total_fees_sol * 1e9),
                "net_profit_lamports": net_profit_lamports,
                "roi_pct": roi_pct,
                "decision": decision,
            }
            await self.aggregator.log_paper_trade(trade_data)

            if net_profit_sol > 0.0005:
                self.trades += 1
                self.total_profit += net_profit_sol
                self.current_balance += net_profit_sol
                logger.info(
                    f"🔥 АРБИТРАЖ (Jupiter) | {base_name} ➔ {target_name} ➔ {base_name} | "
                    f"Профит: +{net_profit_sol:.5f} SOL"
                )

    async def _monitor_loop(self):
        """Непрерывный цикл сканирования всех очередей"""
        sol_amount = int(self.starting_balance * 1e9)
        usdc_amount = int(150 * 1e6) # 150 USDC

        while True:
            tasks = []

            # 1. Генерируем задачи для LST (к SOL)
            for lst in LST_TOKENS.values():
                tasks.append(self._scan_route(BASE_TOKENS["SOL"], lst, sol_amount))

            for stock in XSTOCK_MINTS.values():
                tasks.append(self._scan_route(BASE_TOKENS["USDC"], str(stock), usdc_amount))

            # 3. Генерируем задачи для DePIN/Meme (к USDC)
            for depin in DEPIN_MEME_TOKENS.values():
                tasks.append(self._scan_route(BASE_TOKENS["USDC"], depin, usdc_amount))

            # Выполняем пачку задач
            await asyncio.gather(*tasks)

            # Печать статистики после каждого круга
            logger.info("=" * 50)
            logger.info(f"💰 Баланс: {self.current_balance:.5f} SOL | 📈 P&L: +{self.total_profit:.5f} SOL | Сделок: {self.trades}")
            logger.info("=" * 50)

            await asyncio.sleep(1) # Короткая пауза между кругами

    async def run(self):
        await self.initialize()
        try:
            await self._monitor_loop()
        except KeyboardInterrupt:
            logger.info("🛑 Симулятор остановлен")
        finally:
            if self.session:
                await self.session.close()


if __name__ == "__main__":
    import uvloop
    uvloop.install()
    asyncio.run(PaperTrader().run())
