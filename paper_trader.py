#!/usr/bin/env python3
"""
Paper Trading Simulator - MULTI-AGGREGATOR EDITION
Maximizes RPS across Jupiter, OKX, and OpenOcean.
Streams Pyth WebSockets for xStocks Oracle Lag detection.
"""

import asyncio
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any

sys.path.insert(0, str(Path(__file__).parent / "src"))
import aiohttp
from src.ingest.data_aggregator import DataAggregator
from src.config.xstocks_registry import XSTOCK_MINTS
from src.ingest.oracle_streams import OracleStreams

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
        self.starting_balance = 1.0
        self.current_balance = self.starting_balance
        self.total_profit = 0.0
        self.trades = 0
        self.session = None
        
        # Лимиты из .env
        self.jup_rps = int(os.getenv("JUPITER_QUOTE_RPS", 5))
        self.okx_rps = int(os.getenv("OKX_RPS", 5))
        self.oo_rps = int(os.getenv("OPENOCEAN_RPS", 2))
        
        # Семафоры для контроля параллелизма (не дадут забанить API)
        self.jup_sem = asyncio.Semaphore(self.jup_rps)
        self.okx_sem = asyncio.Semaphore(self.okx_rps)
        self.oo_sem = asyncio.Semaphore(self.oo_rps)

        logger.info(f"🚀 Инициализация. Лимиты RPS: JUP={self.jup_rps}, OKX={self.okx_rps}, OpenOcean={self.oo_rps}")
        logger.info(f"📊 Загружено токенов: LST({len(LST_TOKENS)}), xStocks({len(XSTOCK_MINTS)}), DePIN({len(DEPIN_MEME_TOKENS)})")

    async def initialize(self):
        connector = aiohttp.TCPConnector(limit=0, ttl_dns_cache=300) 
        self.session = aiohttp.ClientSession(connector=connector)

        # Подключаем Pyth Oracle Streams для акций (xStocks)
        self.oracle = OracleStreams(
            opportunity_callback=self._on_oracle_opportunity
        )
        asyncio.create_task(self.oracle.start())
        logger.info("🕸️ Pyth WebSockets запущены (Слушаем акции...)")

    async def _on_oracle_opportunity(self, opp: dict):
        """Коллбек, который срабатывает, когда WebSockets видят лаг оракула"""
        logger.info(f"🚨 [WEBSOCKET СИГНАЛ] Oracle Lag: {opp.get('ticker')} | Оракул: ${opp.get('oracle_price'):.2f} | Спред: {opp.get('price_diff_pct', 0)*100:.2f}%")

    async def _fetch_jupiter(self, input_mint: str, output_mint: str, amount: int):
        async with self.jup_sem:
            url = "https://quote-api.jup.ag/v6/quote"
            params = {"inputMint": input_mint, "outputMint": output_mint, "amount": str(amount), "slippageBps": "15"}
            try:
                async with self.session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {"source": "Jupiter", "out": int(data["outAmount"])}
            except Exception: pass
            await asyncio.sleep(1.0 / self.jup_rps) # Восстановление токена лимита
        return None

    async def _fetch_okx(self, input_mint: str, output_mint: str, amount: int):
        async with self.okx_sem:
            url = "https://web3.okx.com/api/v6/dex/aggregator/quote"
            params = {"chainId": "501", "fromTokenAddress": input_mint, "toTokenAddress": output_mint, "amount": str(amount), "slippage": "0.0015"}
            try:
                async with self.session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("data") and len(data["data"]) > 0:
                            return {"source": "OKX", "out": int(data["data"][0]["toTokenAmount"])}
            except Exception: pass
            await asyncio.sleep(1.0 / self.okx_rps)
        return None

    async def _fetch_openocean(self, input_mint: str, output_mint: str, amount: int):
        async with self.oo_sem:
            url = "https://open-api.openocean.finance/v4/solana/quote"
            params = {"inTokenAddress": input_mint, "outTokenAddress": output_mint, "amount": str(amount), "gasPrice": "5", "slippage": "0.15"}
            try:
                async with self.session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("data"):
                            return {"source": "OpenOcean", "out": int(data["data"]["outAmount"])}
            except Exception: pass
            await asyncio.sleep(1.0 / self.oo_rps)
        return None

    async def _scan_route(self, base_mint: str, target_mint: str, amount: int):
        """Параллельно запрашиваем 3 агрегатора и берем лучший результат"""
        base_name = next((k for k, v in ALL_TOKENS.items() if str(v) == base_mint), base_mint[:4])
        target_name = next((k for k, v in ALL_TOKENS.items() if str(v) == target_mint), target_mint[:4])
        
        # 1. Гонка агрегаторов на вход (Buy)
        buy_tasks = [
            self._fetch_jupiter(base_mint, target_mint, amount),
            self._fetch_okx(base_mint, target_mint, amount),
            self._fetch_openocean(base_mint, target_mint, amount)
        ]
        buy_results = await asyncio.gather(*buy_tasks)
        valid_buys = [r for r in buy_results if r is not None]
        
        if not valid_buys: 
            return

        # Выбираем агрегатор, который дал больше всего токенов
        best_buy = max(valid_buys, key=lambda x: x["out"])
        logger.info(f"🔎 {base_name} ➔ {target_name} | Лучший вход: {best_buy['source']}")

        # 2. Гонка агрегаторов на выход (Sell)
        sell_tasks = [
            self._fetch_jupiter(target_mint, base_mint, best_buy["out"]),
            self._fetch_okx(target_mint, base_mint, best_buy["out"]),
            self._fetch_openocean(target_mint, base_mint, best_buy["out"])
        ]
        sell_results = await asyncio.gather(*sell_tasks)
        valid_sells = [r for r in sell_results if r is not None]

        if not valid_sells:
            return

        best_sell = max(valid_sells, key=lambda x: x["out"])
        
        # 3. Подсчет профита
        final_amount = best_sell["out"]
        profit_lamports = final_amount - amount
        
        if profit_lamports > 0:
            profit_sol = profit_lamports / 1e9 if base_mint == BASE_TOKENS["SOL"] else (profit_lamports / 1e6) / 150
            
            # Вычитаем газ и чаевые (симуляция)
            net_profit = profit_sol - 0.00015 
            
            if net_profit > 0.0005:
                self.trades += 1
                self.total_profit += net_profit
                self.current_balance += net_profit
                logger.info(f"🔥 АРБИТРАЖ! {base_name} ({best_buy['source']}) ➔ {target_name} ➔ {base_name} ({best_sell['source']}) | Профит: +{net_profit:.5f} SOL")

    async def _monitor_loop(self):
        """Непрерывный цикл сканирования всех очередей"""
        sol_amount = int(1.0 * 1e9)  # 1 SOL
        usdc_amount = int(150 * 1e6) # 150 USDC

        while True:
            tasks = []
            
            # 1. Генерируем задачи для LST (к SOL)
            for lst in LST_TOKENS.values():
                tasks.append(self._scan_route(BASE_TOKENS["SOL"], lst, sol_amount))
                
            # 2. Генерируем задачи для xStocks (к USDC)
            for stock in XSTOCK_MINTS.values():
                tasks.append(self._scan_route(BASE_TOKENS["USDC"], str(stock), usdc_amount))
                
            # 3. Генерируем задачи для DePIN/Meme (к USDC)
            for depin in DEPIN_MEME_TOKENS.values():
                tasks.append(self._scan_route(BASE_TOKENS["USDC"], depin, usdc_amount))

            # Выполняем пачку задач
            # Благодаря Семафорам, они сами выстроятся в очередь и не превысят RPS (12 запросов в сек суммарно)
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
            if self.session: await self.session.close()

if __name__ == "__main__":
    asyncio.run(PaperTrader().run())