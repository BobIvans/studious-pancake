#!/usr/bin/env python3
"""
PR-023 QUARANTINE: this is not the supported canonical paper runner.

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
from src.ingest.circuit_breaker import CapitalProtection  # FIX #45
from src.config.addresses import XSTOCK_MINTS
from src.domain.money import (
    BasisPoints,
    ComputeBudget,
    ComputeUnitPrice,
    FeeComponentKind,
    LAMPORTS_PER_SOL,
    Lamports,
    TokenAmount,
    USDC_MINT,
    WSOL_MINT,
)
from src.domain.cost_model import (
    ConversionSnapshot,
    FeeComponent,
    FlashLoanTerms,
    TradeAmounts,
    TradeCostModel,
)

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
        self.existing_atas = set()
        # FIX #45: Integrate CapitalProtection circuit breaker for paper mode
        self.circuit_breaker = CapitalProtection(self.starting_balance, state_path="paper_circuit_breaker.json")

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
        await self.aggregator.start_batch_writer()  # FIX: Agent forgot to start DB writer
        self.simulator = None  # Simulator implemented elsewhere
        self.oracle = None
        self.pyth_feeder = get_pyth_core_feeder()
        if self.oracle:
            asyncio.create_task(self.oracle.start())
        logger.info("🕸️ OracleStreams отключен (oracle_streams.py удалён)")

    async def _on_oracle_opportunity(self, opp: dict):
        """Коллбек, который срабатывает, когда WebSockets видят лаг оракула"""
        logger.info(f"🚨 [WEBSOCKET СИГНАЛ] Oracle Lag: {opp.get('ticker')} | Оракул: ${opp.get('oracle_price'):.2f} | Спред: {opp.get('price_diff_pct', 0)*100:.2f}%")

    async def _fetch_jupiter(self, input_mint: str, output_mint: str, amount: int) -> dict:
        async with self.jup_sem:
            url = os.getenv("JUPITER_QUOTE_API", "https://api.jup.ag/swap/v2/quote")
            jup_key = os.getenv("JUPITER_API_KEY", "")
            headers = {
                "x-api-key": jup_key,
                "Authorization": f"Bearer {jup_key}"
            } if jup_key else {}
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
                        out = int(data["outAmount"])
                        price_impact = float(data.get("priceImpactPct", 0) or 0)
                        fee_bps = int(data.get("feeBps", 0) or 0)
                        return {
                            "source": "Jupiter",
                            "out": out,
                            "priceImpactPct": price_impact,
                            "feeBps": fee_bps,
                        }
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

        # FIX 304: Remove double slippage haircut — Jupiter already returns slippage-adjusted outAmount
        final_amount = int(sell["out"])

        buy_price_impact = buy.get("priceImpactPct", 0.0) if buy else 0.0
        sell_price_impact = sell.get("priceImpactPct", 0.0) if sell else 0.0
        combined_impact_pct = max(buy_price_impact, sell_price_impact)
        fee_bps = sell.get("feeBps", 0) if sell else 0
        _usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        _usdt_mint = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
        _is_stable_6dec = base_mint.endswith(_usdc_mint) or base_mint.endswith(_usdt_mint)
        _base_dec = 6 if _is_stable_6dec else 9

        dex_fee_pct = (fee_bps / 10000.0) if fee_bps else (0.0004 if combined_impact_pct < 0.005 else 0.01)
        amount_ui = amount / (10 ** _base_dec)
        raw_fee_base_token = amount_ui * dex_fee_pct  # Комиссия в единицах базового токена (например, USDC)

        # PR-010: no hardcoded SOL price fallback; price must come from an adapter snapshot.
        sol_price = None
        if self.pyth_feeder:
            live_price = self.pyth_feeder.get_price("So11111111111111111111111111111111111111112")
            if live_price and live_price > 0:
                sol_price = live_price
        if sol_price is None:
            logger.warning("🚫 SOL price unavailable from adapter snapshot — quote-only paper trade skipped fail-closed")
            return

        if _base_dec == 6:  # Если базовый токен USDC/USDT (6 децималов)
            dex_fee_sol = raw_fee_base_token / sol_price
        else:
            # Базовый актив — SOL, конвертация не требуется
            dex_fee_sol = raw_fee_base_token

        gross_profit_native = final_amount - amount  # in token native units (e.g. USDC micro-units)

        if gross_profit_native > 0:
            # Step 1: convert gross profit to SOL immediately
            gross_profit_ui = gross_profit_native / (10 ** _base_dec)  # UI units (e.g. 1.5 USDC)
            sol_price = self.pyth_feeder.get_price("So11111111111111111111111111111111111111112") if self.pyth_feeder else None
            if sol_price is None:
                logger.warning("🚫 SOL price unavailable from Pyth oracle — skipping trade (Fail-Closed)")
                return
            if _base_dec == 6:
                gross_profit_sol = gross_profit_ui / sol_price  # convert USDC → SOL via USD bridge
            else:
                gross_profit_sol = gross_profit_ui  # already in SOL

            # Step 2: all fees strictly in the declared settlement asset via TradeCostModel.
            slippage_bps = 15
            settlement_mint = WSOL_MINT if _base_dec == 9 else USDC_MINT
            input_amount = TokenAmount.from_base_units(settlement_mint, amount, _base_dec)
            expected_output = TokenAmount.from_base_units(settlement_mint, final_amount, _base_dec)
            minimum_output = TokenAmount.from_base_units(settlement_mint, int(sell.get("otherAmountThreshold", final_amount)), _base_dec)
            if _base_dec == 6:
                dex_fee_units = int(raw_fee_base_token * (10 ** _base_dec))
                network_fee_units = int(5000 / sol_price * (10 ** _base_dec))
                priority_fee_units = int(ComputeBudget(200_000, ComputeUnitPrice(50_000)).priority_fee().value / sol_price * (10 ** _base_dec))
                jito_tip_units = 0  # PR-010: quote-only paper path has no fresh Jito tip snapshot.
                ata_rent_units = 0 if target_mint in self.existing_atas else 0  # PR-010: rent unknown; do not fake lamports as token units.
            else:
                dex_fee_units = int(raw_fee_base_token * (10 ** _base_dec))
                network_fee_units = Lamports(5000).value
                priority_fee_units = ComputeBudget(200_000, ComputeUnitPrice(50_000)).priority_fee().value
                jito_tip_units = 0  # PR-010: quote-only paper path has no fresh Jito tip snapshot.
                ata_rent_units = 0 if target_mint in self.existing_atas else 0  # PR-010: rent unknown; canonical engine requires RPC snapshot.
            fees = [
                FeeComponent(FeeComponentKind.FLASH_LOAN, TokenAmount.from_base_units(settlement_mint, 0, _base_dec), False, "MarginFi paper terms"),
                FeeComponent(FeeComponentKind.DEX, TokenAmount.from_base_units(settlement_mint, dex_fee_units, _base_dec), True, "Jupiter quote fee embedded"),
                FeeComponent(FeeComponentKind.NETWORK_BASE, TokenAmount.from_base_units(settlement_mint, network_fee_units, _base_dec), False),
                FeeComponent(FeeComponentKind.PRIORITY, TokenAmount.from_base_units(settlement_mint, priority_fee_units, _base_dec), False),
                FeeComponent(FeeComponentKind.JITO_TIP, TokenAmount.from_base_units(settlement_mint, jito_tip_units, _base_dec), False),
                FeeComponent(FeeComponentKind.ATA_CREATION, TokenAmount.from_base_units(settlement_mint, ata_rent_units, _base_dec), False),
                FeeComponent(FeeComponentKind.SLIPPAGE_BUFFER, TokenAmount.from_base_units(settlement_mint, 0, _base_dec), True),
            ]
            cost_decision = TradeCostModel().evaluate(
                settlement_mint=settlement_mint, amounts=TradeAmounts(input_amount, expected_output, minimum_output),
                flash_loan_terms=FlashLoanTerms("MarginFi", settlement_mint, BasisPoints(0)), fees=fees,
                conversions=ConversionSnapshot(tuple()), min_net_profit=TokenAmount.from_base_units(settlement_mint, int(0.0001 * (10 ** _base_dec)), _base_dec),
                safety_buffer=TokenAmount.from_base_units(settlement_mint, 0, _base_dec),
            )
            breakdown = cost_decision.to_dict()
            net_profit_lamports = int(breakdown["net_profit_base_units"] if _base_dec == 9 else breakdown["net_profit_base_units"] / sol_price * 1000)
            net_profit_sol = float(net_profit_lamports) / LAMPORTS_PER_SOL
            total_fees_sol = float(breakdown["total_cost_base_units"]) / (10 ** _base_dec) / (1 if _base_dec == 9 else sol_price)
            roi_pct = float(breakdown["roi"]) * 100
            decision = "FEASIBLE_PRE_SIMULATION" if cost_decision.should_execute else cost_decision.reason.value.upper()
            sim_success = 0
            sim_error = "transaction not built or simulated in paper mode" if cost_decision.should_execute else cost_decision.reason.value

            trade_data = {
                "route": f"{base_name}->{target_name}->{base_name}",
                "token_in": base_mint,
                "token_out": target_mint,
                "amount_lamports": amount,
                "expected_profit_lamports": int(breakdown["gross_profit_base_units"]),
                "gross_revenue_lamports": final_amount,
                "flashloan_fee_lamports": 0,
                "dex_fee_lamports": dex_fee_units,
                "slippage_bps": slippage_bps,
                "network_fee_lamports": network_fee_units,
                "priority_fee_lamports": priority_fee_units,
                "jito_tip_lamports": jito_tip_units,
                "ata_rent_lamports": ata_rent_units,
                "total_cost_lamports": int(breakdown["total_cost_base_units"]),
                "net_profit_lamports": net_profit_lamports,
                "roi_pct": roi_pct,
                "decision": decision,
                "executed": 0,
                "sim_success": sim_success,
                "sim_error": sim_error,
                "price_impact_pct": combined_impact_pct,
                "sol_usd_price": sol_price,
                "cost_breakdown": breakdown,
                "decision_reason": cost_decision.reason.value,
                "minimum_output_base_units": breakdown["guaranteed_minimum_output_base_units"],
                "required_repayment_base_units": breakdown["required_repayment_base_units"],
            }
            await self.aggregator.log_paper_trade(trade_data)

            # FIX #45: Record trade/failure in circuit breaker for P&L tracking
            if decision == "FEASIBLE_PRE_SIMULATION":
                pass  # PR-010: no realized PnL before full simulation/reconciliation.
            elif decision == "SKIP_LOW_MARGIN" and total_fees_sol > 0:
                self.circuit_breaker.record_failed_attempt(Lamports(5000).to_sol_decimal())

            if False and net_profit_sol > 0.0005:
                self.trades += 1
                self.total_profit += net_profit_sol
                self.current_balance += net_profit_sol
                self.existing_atas.add(target_mint)
                logger.info(
                    f"🔥 АРБИТРАЖ (Jupiter) | {base_name} ➔ {target_name} ➔ {base_name} | "
                    f"Профит: +{net_profit_sol:.5f} SOL"
                )

    async def _monitor_loop(self):
        """Непрерывный цикл сканирования всех очередей"""
        # FIX 304: Scale trade volume to 95% of real wallet balance
        sol_amount = Lamports.from_sol(self.current_balance * 0.95).value
        usdc_amount = int(self.current_balance * sol_price * 0.95 * 1_000_000)

        while True:
            # FIX #45: Check circuit breaker before any trade execution
            stop, reason = self.circuit_breaker.should_stop()
            if stop:
                logger.critical(f"🛑 PAPER TRADER HALTED BY CIRCUIT BREAKER: {reason}")
                break

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
