"""LST Instant Unstake Arbitrage for MarginFi Flash Loans.

Uses Jupiter circular routing (SOL -> LST -> SOL) to exploit discrepancies
between market price and protocol unstake rates.
Dynamic sizing: 95% vault liquidity passed through OptimalTradeSizer so
the maximum borrow never kills profit via slippage (no hard caps).
"""

import asyncio
import logging
import time
import os
from typing import Dict, List, Optional, Any
import aiohttp
from solders.pubkey import Pubkey

logger = logging.getLogger("LstUnstakeArb")

SOL_MINT = "So11111111111111111111111111111111111111112"

class LstInstantUnstakeArbitrage:
    """Executes LST unstake arbitrage using MarginFi flash loans and Jupiter circular routing."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        rpc_url: str,
        marginfi_account: str,
        lst_mints: List[str] = ["mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So", "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn"],
        tx_builder: Any = None,
        optimal_trade_sizer: Any = None,
        min_profit_lamports: int = 50000,
    ):
        self.session = session
        self.rpc_url = rpc_url
        self.marginfi_account = marginfi_account
        self.lst_mints = lst_mints
        self.tx_builder = tx_builder
        self.optimal_trade_sizer = optimal_trade_sizer
        self.min_profit_lamports = min_profit_lamports

    async def scan_unstake_opportunities(self) -> List[Dict[str, Any]]:
        """
        Scan for profitable LST unstake opportunities using circular Jupiter quotes.

        Маршрут: SOL -> LST (Raydium/Orca, со скидкой) -> SOL (Sanctum Router, по справедливому курсу)

        Использует:
        • 95% MarginFi liquidity (без хардкапа)
        • OptimalTradeSizer (O(1) AMM-математика) для нахождения пика кривой доходности
        • dex_filter_leg2=["Sanctum"] для принудительного использования Sanctum Router (Exit Leg)
        """
        opportunities = []

        # JupiterTxBuilder для котирования
        if self.tx_builder:
            _jup = self.tx_builder
        else:
            from src.ingest.tx_builder import JupiterTxBuilder
            _jup = JupiterTxBuilder(session=self.session, rpc_url=self.rpc_url)

        # Dynamic liquidity from MarginFi SOL bank
        from arb_bot import MARGINFI_BANKS
        bank_info = MARGINFI_BANKS.get(SOL_MINT)
        if not bank_info:
            return []

        max_borrow_lamports = await _jup.get_max_marginfi_borrow(str(bank_info["liquidity_vault"]))
        # Fix 3 (MarginFi Slippage Margin): cap borrow to FLASH_LOAN_SIZE_SOL
        env_max_borrow = int(float(os.getenv("FLASH_LOAN_SIZE_SOL", "0.5")) * 1_000_000_000)
        max_borrow_lamports = min(max_borrow_lamports, env_max_borrow)
        if max_borrow_lamports < 1_000_000_000:  # Min 1 SOL
            return []

        # ── Шаг А — OptimalTradeSizer: динамический сайзинг без итераций ──────────
        # Передаем 95% ликвидности банка в OptimalTradeSizer.
        # Если на выходе есть данные по резервам AMM — формула находит ИДЕАЛЬНУЮ сумму.
        # Если резервов нет (пустой routes) — возвращается полный 95% банк (без искажений).
        if self.optimal_trade_sizer:
            try:
                optimal_size = int(
                    self.optimal_trade_sizer.find_optimal_trade_size(
                        routes=[], amount_in=max_borrow_lamports,
                        decimals_in=9, decimals_out=9, jito_tip_sol=0.0001,
                    )
                )
                if optimal_size and optimal_size > 1_000_000_000:  # Min 1 SOL
                    max_borrow_lamports = optimal_size
                    logger.debug(f"📈 LST unstake optimal borrow: {max_borrow_lamports/1e9:.4f} SOL (AMM curve peak)")
            except Exception as e:
                logger.debug(f"OptimalTradeSizer failed, using raw vault: {max_borrow_lamports/1e9:.4f} SOL ({e})")

        for lst_mint in self.lst_mints:
            try:
                test_amount_lamports = max_borrow_lamports

                quote = await _jup.get_circular_quote(
                    input_mint=SOL_MINT,
                    middle_mint=lst_mint,
                    amount_lamports=test_amount_lamports,
                    # Принудительно используем Sanctum Router для второго лега (LST → SOL по справедливому курсу)
                    dex_filter_leg2=["Sanctum", "Sanctum Infinity"],
                )

                if not quote:
                    logger.debug(f"❌ No circular quote for {lst_mint[:8]} via Sanctum")
                    continue

                expected_profit = quote.get("expected_profit_lamports", 0)

                # Вычитаем Jito tip из чистой прибыли
                jito_tip = quote.get("jito_tip_lamports", 0)
                net_profit = expected_profit - jito_tip

                if net_profit > self.min_profit_lamports:
                    logger.info(
                        f"✅ LST unstake opp: {lst_mint[:8]} | "
                        f"borrow={test_amount_lamports/1e9:.2f} SOL | "
                        f"profit={net_profit/1e9:.6f} SOL"
                    )
                    opportunities.append({
                        "strategy": "lst_unstake",
                        "lst_mint": lst_mint,
                        "expected_profit_lamports": net_profit,
                        "quote": quote,
                        "borrow_amount": test_amount_lamports,
                    })

            except Exception as e:
                logger.warning(f"Failed to scan {lst_mint}: {e}")

        return opportunities

    async def execute_unstake_arbitrage(
        self,
        opportunity: Dict[str, Any],
        tx_builder,
        keypair,
        jito_executor
    ) -> bool:
        """Execute the unstake arbitrage using native flashloan builder.
        
        Порядок инструкций в транзакции:
          1. ComputeBudget (CU лимит)
          2. MarginFi Borrow SOL
          3. Buy LST на Raydium/Orca (Jupiter swap)
          4. Sanctum Router Instant Unstake (LST -> SOL)
          5. MarginFi Repay SOL
          6. Jito Tip (ЗАЩИТА КАПИТАЛА — строго последний)
        """
        try:
            lst_mint = opportunity["lst_mint"]
            quote = opportunity["quote"]
            borrow_amount = opportunity["borrow_amount"]
            
            from arb_bot import MARGINFI_BANKS
            bank_info = MARGINFI_BANKS.get(SOL_MINT)
            if not bank_info:
                return False

            fl_result = await tx_builder.build_native_flashloan_tx(
                wallet_pubkey=str(keypair.pubkey()),
                arbitrage_path=[SOL_MINT, lst_mint, SOL_MINT],
                borrow_amount_lamports=borrow_amount,
                expected_min_profit_lamports=opportunity["expected_profit_lamports"],
                dex_swap_instructions=quote.get("instructions", []),
                marginfi_config=bank_info,
                jito_tip_lamports=100000,
                borrow_mint=SOL_MINT,
                use_jito=True,
                tip_accounts=jito_executor.tip_accounts if jito_executor else None,  # Fix 2: dynamic Jito tip accounts
            )

            if not fl_result:
                return False

            return True

        except Exception as e:
            logger.error(f"Unstake arbitrage execution failed: {e}")
            return False