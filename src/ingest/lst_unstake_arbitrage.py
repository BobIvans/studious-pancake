"""LST Instant Unstake Arbitrage for MarginFi Flash Loans.

Uses Jupiter circular routing (SOL -> LST -> SOL) to exploit discrepancies
between market price and protocol unstake rates.
Dynamic sizing: 95% vault liquidity passed through OptimalTradeSizer so
the maximum borrow never kills profit via slippage (no hard caps).
"""

import asyncio
import base64
import logging
import time
import os
from typing import Dict, List, Optional, Any, Callable
import aiohttp
from solders.hash import Hash
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

logger = logging.getLogger("LstUnstakeArb")

SOL_MINT = "So11111111111111111111111111111111111111112"
RENT_SPL_ATA_SOL = 0.00204
RENT_TOKEN2022_SOL = 0.0035

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
        rpc_getter: Optional[Callable[[], str]] = None,
        ata_cache: Optional[set] = None,
        keypair: Any = None,
        cfg=None,
        data_aggregator=None,
        stats=None,
        stats_lock=None,
        min_deviation_pct: Optional[float] = None,
    ):
        self.session = session
        self._static_rpc_url = rpc_url
        self.rpc_getter = rpc_getter
        self.marginfi_account = marginfi_account
        self.lst_mints = lst_mints
        self.tx_builder = tx_builder
        self.optimal_trade_sizer = optimal_trade_sizer
        self.min_profit_lamports = min_profit_lamports
        self.ata_cache = ata_cache if ata_cache is not None else set()
        self.keypair = keypair
        self.cfg = cfg
        self.data_aggregator = data_aggregator
        self.stats = stats
        self.stats_lock = stats_lock
        self.min_deviation_pct = min_deviation_pct

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
            _jup = JupiterTxBuilder(session=self.session, rpc_getter=self.rpc_getter)

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
        
        # Check current balance for capital-aware sizing
        import src.ingest.shared_state as shared_state
        current_balance = shared_state.stats.get("last_balance", shared_state.stats.get("virtual_balance", 0.015))
        current_virtual_balance = shared_state.stats.get("virtual_balance", current_balance)

        for lst_mint in self.lst_mints:
            try:
                # Check how many new ATAs we need
                from spl.token.instructions import get_associated_token_address
                from solders.pubkey import Pubkey
                num_new_atas = 0
                try:
                    # Check LST ATA
                    from spl.token.constants import TOKEN_PROGRAM_ID
                    if self.keypair:
                        ata_addr = str(get_associated_token_address(self.keypair.pubkey(), Pubkey.from_string(lst_mint), TOKEN_PROGRAM_ID))
                        if ata_addr not in self.ata_cache:
                            num_new_atas += 1
                except Exception:
                    pass

                test_amount_lamports = max_borrow_lamports
                
                if self.optimal_trade_sizer:
                    try:
                        optimal_size = int(
                            self.optimal_trade_sizer.get_slippage_pegged_borrow_lamports(
                                wallet_native_balance_sol=current_balance,
                                pool_slippage_pct=0.005, # Conservative estimate for scan
                                bank_liquidity_lamports=max_borrow_lamports,
                                virtual_balance=current_virtual_balance,
                                num_new_atas=num_new_atas,
                                expected_profit_sol=self.min_profit_lamports / 1e9,
                            )
                        )
                        if optimal_size and optimal_size > 1_000_000_000:  # Min 1 SOL
                            test_amount_lamports = optimal_size
                            logger.debug(f"📈 LST unstake optimal borrow: {test_amount_lamports/1e9:.4f} SOL (AMM curve peak)")
                    except Exception as e:
                        logger.debug(f"OptimalTradeSizer failed, using raw vault: {test_amount_lamports/1e9:.4f} SOL ({e})")

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

    async def _refetch_circular_quote(
        self,
        quote: Dict[str, Any],
        lst_mint: str,
        borrow_amount: int,
        only_direct_routes: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Refetch the circular quote with strict Jupiter route guards."""
        if not self.tx_builder:
            return None
        try:
            circular = await self.tx_builder.get_circular_quote(
                input_mint=SOL_MINT,
                middle_mint=lst_mint,
                amount_lamports=borrow_amount,
                dex_filter_leg1=quote.get("dex_filter_leg1"),
                dex_filter_leg2=quote.get("dex_filter_leg2"),
                jito_tip_lamports=quote.get("jito_tip_lamports", 0),
                only_direct_routes=only_direct_routes,
            )
            if not circular:
                return None
            circular["dex_leg1"] = circular.get("dex_leg1") or circular.get("step1")
            circular["dex_leg2"] = circular.get("dex_leg2") or circular.get("step2")
            return circular
        except Exception as e:
            logger.debug(f"LST circular quote retry failed: {e}")
            return None

    async def _simulate_transaction(
        self,
        transaction,
        keypair,
        expected_profit_lamports: int,
        tip_lamports: int,
        bank_vault_pubkey: Optional[str] = None,
    ) -> tuple:
        """Run the local pre-flight simulation for an LST transaction."""
        from .flash_simulator import FlashSimulator

        flash_sim = FlashSimulator(self.session, self._static_rpc_url)
        tx_b64 = base64.b64encode(bytes(transaction)).decode("ascii")
        return await flash_sim.validate_profitability(
            tx_b64=tx_b64,
            tx_signer_pubkey=str(keypair.pubkey()),
            min_profit_lamports=expected_profit_lamports,
            tip_lamports=tip_lamports,
            priority_fee_lamports=0,
            expected_profit_sol=None,
            bank_vault_pubkey=bank_vault_pubkey,
        )

    async def _smart_retry_execute(
        self,
        opportunity: Dict[str, Any],
        tx_builder,
        keypair,
        jito_executor,
        jito_bidding_manager: Optional[Any] = None,
        reason: str = "",
        current_borrow_amount: int = 0,
        current_expected_profit: int = 0
    ) -> bool:
        """Apply Smart Retry rules for LST unstake arbitrage."""
        retry_state = opportunity.get("_smart_retry", {})
        if retry_state.get("used"):
            logger.warning(f"LST Smart Retry exhausted: {reason}")
            return False

        retry_opportunity = dict(opportunity)
        retry_opportunity["_smart_retry"] = {"used": True, "mode": "slippage" if ("slippage" in reason.lower() or "liquidity" in reason.lower() or "depth" in reason.lower()) else "route"}

        if "slippage" in reason.lower() or "liquidity" in reason.lower() or "depth" in reason.lower():
            new_borrow = max(int(current_borrow_amount * 0.5), 1)
            retry_opportunity["borrow_amount"] = new_borrow
            retry_opportunity["expected_profit_lamports"] = max(int(current_expected_profit * 0.5), 1)
            retry_quote = await self._refetch_circular_quote(
                opportunity.get("quote", {}),
                opportunity["lst_mint"],
                new_borrow,
                only_direct_routes=True,
            )
            if not retry_quote:
                logger.warning(f"LST Smart Retry failed: quote rebuild for slippage failed: {reason}")
                return False
            retry_opportunity["quote"] = retry_quote
            logger.warning(f"LST Smart Retry: cut borrow to {new_borrow} lamports")
            return await self.execute_unstake_arbitrage(
                retry_opportunity,
                tx_builder,
                keypair,
                jito_executor,
                jito_bidding_manager
            )

        if "accountnotfound" in reason.lower() or "rent" in reason.lower() or "insufficient" in reason.lower():
            retry_quote = await self._refetch_circular_quote(
                opportunity.get("quote", {}),
                opportunity["lst_mint"],
                current_borrow_amount,
                only_direct_routes=True,
            )
            if not retry_quote:
                logger.warning(f"LST Smart Retry failed: route rebuild failed: {reason}")
                return False
            retry_opportunity["quote"] = retry_quote
            logger.warning("LST Smart Retry: rebuilt route with onlyDirectRoutes=true and restrictIntermediateTokens=true")
            return await self.execute_unstake_arbitrage(
                retry_opportunity,
                tx_builder,
                keypair,
                jito_executor,
                jito_bidding_manager
            )

        logger.warning(f"LST Smart Retry skipped for reason: {reason}")
        return False

    async def execute_unstake_arbitrage(
        self,
        opportunity: Dict[str, Any],
        tx_builder,
        keypair,
        jito_executor,
        jito_bidding_manager: Optional[Any] = None
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

            # Clone bank_info and inject marginfi_account to prevent compile KeyError
            active_bank_info = dict(bank_info)
            _acct_to_use = os.getenv("MARGINFI_ACCOUNT", "Fk4G5NB5e1NyULQCCpTNLWCmChCW2UbDwpkEofqAiHk2")
            active_bank_info["marginfi_account"] = Pubkey.from_string(_acct_to_use)

            dex_leg1 = quote.get("dex_leg1", {})
            dex_leg2 = quote.get("dex_leg2", {})
            wallet_pubkey = str(keypair.pubkey())

            all_swap_ixs = []

            try:
                # Pass expected_profit_sol for Dynamic Rent Guard in Leg1
                expected_profit_sol = opportunity["expected_profit_lamports"] / 1e9
                leg1_ixs, _ = await tx_builder.get_swap_instructions(dex_leg1, wallet_pubkey, use_custom_cu=True, expected_profit_sol=expected_profit_sol)
                if leg1_ixs:
                    all_swap_ixs.extend(leg1_ixs)
            except Exception as _leg1_err:
                logger.warning(f"Leg1 swap-instructions fetch failed (non-fatal): {_leg1_err}")

            try:
                # Pass expected_profit_sol for Dynamic Rent Guard in Leg2
                leg2_ixs, _ = await tx_builder.get_swap_instructions(dex_leg2, wallet_pubkey, use_custom_cu=True, expected_profit_sol=expected_profit_sol)
                if leg2_ixs:
                    all_swap_ixs.extend(leg2_ixs)
                else:
                    logger.error("LEG2 (exit) swap instructions empty — aborting")
                    return False
            except Exception as _leg2_err:
                logger.error(f"LEG2 swap-instructions fetch failed: {_leg2_err} — aborting")
                return False

            # Calculate dynamic Jito tip using JitoBiddingManager (Fix: replace hardcoded 100000)
            jito_tip_lamports = 0
            if jito_bidding_manager:
                jito_tip_lamports = jito_bidding_manager.calculate_blue_ocean_tip(
                    expected_profit_sol=expected_profit_sol,
                    strategy="lst_unstake"
                )
            else:
                # Fallback to quote's calculated tip or default
                jito_tip_lamports = quote.get("jito_tip_lamports", 100000)

            if jito_tip_lamports <= 0:
                logger.warning(f"LST Unstake tip calculation returned 0 or negative ({jito_tip_lamports}), using fallback 100000")
                jito_tip_lamports = 100000

            fl_result = await tx_builder.build_native_flashloan_tx(
                wallet_pubkey=str(keypair.pubkey()),
                arbitrage_path=[SOL_MINT, lst_mint, SOL_MINT],
                borrow_amount_lamports=borrow_amount,
                expected_min_profit_lamports=opportunity["expected_profit_lamports"],
                dex_swap_instructions=all_swap_ixs,
                marginfi_config=active_bank_info,
                jito_tip_lamports=jito_tip_lamports,
                borrow_mint=SOL_MINT,
                use_jito=True,
                tip_accounts=jito_executor.tip_accounts if jito_executor else None,  # Fix 2: dynamic Jito tip accounts
            )

            if not fl_result:
                return False

            # Convert to VersionedTransaction
            recent_blockhash = None
            if self.rpc_getter:
                rpc_url = self.rpc_getter()
                payload = {"jsonrpc": "2.0", "id": 1, "method": "getLatestBlockhash"}
                async with self.session.post(rpc_url, json=payload) as resp:
                    bh_data = await resp.json()
                    recent_blockhash = bh_data.get("result", {}).get("value", {}).get("blockhash")

            if not recent_blockhash:
                return False

            # Resolve ALT accounts properly
            from solders.address_lookup_table_account import AddressLookupTableAccount
            alt_pubkey_strs = fl_result.get("address_lookup_table_pubkeys", [])
            resolved_alts = []
            import src.ingest.shared_state as shared_state
            if shared_state.alt_manager:
                for alt_str in alt_pubkey_strs:
                    _res = await shared_state.alt_manager.resolve_alt(Pubkey.from_string(alt_str))
                    if _res:
                        resolved_alts.append(AddressLookupTableAccount(key=Pubkey.from_string(alt_str), addresses=_res))

            message = MessageV0.try_compile(
                payer=keypair.pubkey(),
                instructions=fl_result["instructions"],
                address_lookup_table_accounts=resolved_alts,
                recent_blockhash=Hash.from_string(recent_blockhash)
            )
            transaction = VersionedTransaction(message, [keypair])

            # Simulate before execution
            is_profitable, reason, _ = await self._simulate_transaction(
                transaction,
                keypair,
                opportunity["expected_profit_lamports"],
                jito_tip_lamports,
                str(bank_info["liquidity_vault"])
            )

            if not is_profitable:
                return await self._smart_retry_execute(
                    opportunity,
                    tx_builder,
                    keypair,
                    jito_executor,
                    jito_bidding_manager,
                    reason,
                    borrow_amount,
                    opportunity["expected_profit_lamports"]
                )

            # Send via Jito
            jito_result = await jito_executor.send_bundle([transaction])
            
            if jito_result.get("success"):
                logger.info(f"🚀 LST unstake bundle sent: {jito_result.get('bundle_id')}")
                return True
            else:
                logger.error(f"LST Jito bundle failed: {jito_result.get('error')}")
                return False

        except Exception as e:
            logger.error(f"Unstake arbitrage execution failed: {e}")
            return False
