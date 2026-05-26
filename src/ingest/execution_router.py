"""Execution Router for Hybrid Jito/Standard Transaction Switching."""

import asyncio
import logging
import base64
import re
import time
import struct
import os
from typing import Optional, Dict, Any, Set, List, Tuple, Callable
import aiohttp
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from solders.instruction import Instruction, AccountMeta
from solders.hash import Hash
from solders.message import MessageV0
from solders.system_program import TransferParams, transfer
from spl.token.instructions import get_associated_token_address
from spl.token.constants import TOKEN_PROGRAM_ID

from .leader_tracker import LeaderTracker
from .g2_tip_manager import ExecutionGuard
from .tx_builder import JupiterTxBuilder
from .epoch_tracker import EpochTracker
# Phase 48: Import dynamic bank info from arb_bot
try:
    from arb_bot import MARGINFI_BANKS
except ImportError:
    MARGINFI_BANKS = {}

logger = logging.getLogger(__name__)

# Token-2022 Program ID for xStocks pivot helper
TOKEN_2022_PROGRAM_ID = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EP2rHEjaChQX6n57TR5m")

# Flash Loan Pivot: Jupiter swap helper constants
SOL_MINT = Pubkey.from_string("So11111111111111111111111111111111111111112")
USDC_MINT = Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
JUPITER_QUOTE_URL = "https://quote-api.jup.ag/v6/quote"
JUPITER_SWAP_IX_URL = "https://quote-api.jup.ag/v6/swap-instructions"

STRATEGY_EXTRA_ACCOUNTS: Dict[str, Set[str]] = {}  # Fix 91: auto-discovered remaining accounts for transfer hooks

def _build_extra_account_metas(strategy_key: str) -> list:
    """Fix 91: Build AccountMeta list from STRATEGY_EXTRA_ACCOUNTS for injection into instructions."""
    extras = STRATEGY_EXTRA_ACCOUNTS.get(strategy_key, set())
    if not extras:
        return []
    # Read-only, non-signer — these are writable state accounts the RPC complained about
    return [AccountMeta(pubkey=Pubkey.from_string(pk), is_signer=False, is_writable=True) for pk in extras]

class StandardTransactionSender:
    """Sends standard transactions with priority fees."""

    def __init__(self, session: aiohttp.ClientSession, rpc_url: str):
        self.session = session
        self.rpc_url = rpc_url

    async def send_transaction(self, transaction: VersionedTransaction, priority_fee_sol: float) -> bool:
        """
        Phase 48: Standard Sender DISABLED for Capital Protection.
        Trades with 0.017 SOL cannot risk standard RPC delays/front-running.
        """
        logger.warning("🚫 Standard transaction blocked by STRICT_JITO_MODE.")
        return False

class ExecutionRouter:
    """Routes transactions between Jito bundles and standard transactions based on slot leader with sequential queue."""

    def __init__(self, leader_tracker: LeaderTracker, jito_executor, session: aiohttp.ClientSession, rpc_url: str, keypair=None, alt_manager=None, rpc_getter: Optional[Callable[[], str]] = None):
        self.leader_tracker = leader_tracker
        self.jito_executor = jito_executor
        self.standard_tx_sender = StandardTransactionSender(session, rpc_url)
        self.execution_queue = asyncio.Queue(maxsize=100)
        self._processor_task = None
        self.keypair = keypair
        self.session = session
        self._static_rpc_url = rpc_url
        self.rpc_getter = rpc_getter
        self.rpc_url = rpc_url
        # Epoch Shield: Block trades during epoch boundary storm
        self.epoch_tracker = EpochTracker(rpc_url=rpc_url, session=session)
        self._epoch_killswitch_active = False
        self._epoch_last_reason = ""
        # Fix 3: ALT Manager for MTU-safe tx compilation
        self.alt_manager = alt_manager

        # Circuit Breaker: Anti-Dust protection
        self.critical_balance_threshold = 0.017  # SOL - panic if rent recovery fails
        self.dust_alert_triggered = False
        self.consecutive_failures = 0
        self.last_slot_executed = 0  # Fix 78: Slot mutex for single MARGINFI_ACCOUNT
        self.max_consecutive_failures = 3

        # Execution Guard (Circuit Breaker for consecutive failures)
        self.execution_guard = ExecutionGuard()

        # Reputation Circuit Breaker: per-pair cooldown after 3 consecutive slippage fails
        # Format: pair_key -> {"failures": int, "banned_until": float, "last_error": str}
        self._pair_reputation: Dict[str, Dict[str, Any]] = {}
        self.PAIR_SLIPPAGE_LIMIT = 3          # 3 consecutive slippage errors → cooldown
        self.PAIR_COOLDOWN_SECONDS = 600      # 10 minutes cooldown per pair

        # ── Phase 49: Optimistic State ─────────────────────────────────────────
        # When a bundle is sent via Jito we do NOT wait for on-chain confirmation
        # before considering the MarginFi account free for the next trade.
        self.is_account_busy: bool = False

        # Fix 51: Jito Bundle Self-Cancellation — track stale bundles for overwrite
        # map: bundle_id -> {"sent_slot": int, "sent_at": float, "endpoint": str, "tip_lamports": int, "deducted_amount": float}
        self._pending_bundle_slots: Dict[str, Dict[str, Any]] = {}
        self._stale_bundle_ids: Set[str] = set()
        self._self_cancel_task: Optional[asyncio.Task] = None

    def start_processor(self):
        """Start the sequential execution processor."""
        if self._processor_task is None:
            self._processor_task = asyncio.create_task(self._process_queue())
        if self._self_cancel_task is None:
            self._self_cancel_task = asyncio.create_task(self._self_cancel_stale_bundles())

    async def _process_queue(self):
        """Process execution tasks sequentially."""
        while True:
            try:
                task = await self.execution_queue.get()
                await self._execute_task(task)
                self.execution_queue.task_done()
            except Exception as e:
                logger.error(f"Queue processing error: {e}")
                await asyncio.sleep(0.1) # Prevent tight loop on error

    async def _execute_task(self, task):
        """Execute a single task."""
        session, cfg, rpc_url, transaction, jito_tip_lamports, future = task
        try:
            result = await self._route_transaction(session, cfg, rpc_url, transaction, jito_tip_lamports)
            if not future.done():
                future.set_result(result)
        except Exception as e:
            logger.error(f"Task execution error: {e}")
            if not future.done():
                future.set_exception(e)

    async def execute_opportunity(self, session: aiohttp.ClientSession, cfg, rpc_url: str, transaction: VersionedTransaction, jito_tip_lamports: int) -> dict:
        """Execute transaction using appropriate method based on slot leader via sequential queue."""
        # 1. Check ExecutionGuard (Circuit Breaker)
        if not self.execution_guard.can_execute():
            logger.warning("🚫 Circuit breaker active — skipping execution")
            return {"status": "error", "message": "Circuit breaker active"}

        future = asyncio.Future()

        # Bundle Ghosting Timeout: 2.0s hard limit to prevent stale-bundle race
        try:
            # Use put_nowait for urgent HFT tasks to avoid blocking
            self.execution_queue.put_nowait((session, cfg, rpc_url, transaction, jito_tip_lamports, future))

            # Wait for result with 2.0s timeout — prevents bundle ghosting race
            try:
                result = await asyncio.wait_for(future, timeout=2.0)
                # Post-execution balance check — prevents retry on insufficient funds
                if result.get("status") == "success":
                    await self._check_wallet_balance_after_execution()
                    self.execution_guard.record_success()
                elif result.get("status") == "timeout" or "Slippage" in str(result):
                    self.execution_guard.record_failure()
                return result
            except asyncio.TimeoutError:
                logger.warning("⏰ Bundle ghosting timeout - transaction stuck, releasing lock")
                self.execution_guard.record_failure()
                # Mark as timeout error but don't block the queue
                return {"status": "timeout", "message": "Bundle stuck - timeout after 2.0s"}

        except asyncio.QueueFull:
            logger.error("Execution queue is full - dropping transaction to prevent deadlock")
            return {"status": "error", "message": "Execution queue full"}

    async def _check_epoch_killswitch(self) -> bool:
        """
        Epoch Shield: block all trades during the epoch boundary consensus storm.
        - First 60 s after a new epoch starts (leader schedules are being recalculated)
        - Last 30 s before the current epoch ends
        Returns True  → epoch is safe, trading may proceed
        Returns False → killswitch active, trading blocked
        """
        SECONDS_FROM_EPOCH_START = 60
        SECONDS_TO_EPOCH_END = 30

        try:
            info = self.epoch_tracker.epoch_info
            if not info:
                return True   # no epoch data yet — default safe

            slots_in_epoch = info.get("slotsInEpoch", 432000)
            slot_index     = info.get("slotIndex", 0)

            # ── Case 1: epoch just started (<60 s = ~150 slots at 400 ms) ──
            if slot_index < SECONDS_FROM_EPOCH_START * 3:
                self._epoch_killswitch_active = True
                self._epoch_last_reason = (
                    f"Epoch just started (slotIndex={slot_index}, "
                    f"leaders still recalculating)"
                )
                return False

            # ── Case 2: less than 30 s until epoch end ──
            slots_remaining = slots_in_epoch - slot_index
            secs_remaining  = int(slots_remaining * 0.4)
            if 0 < secs_remaining <= SECONDS_TO_EPOCH_END:
                self._epoch_killswitch_active = True
                self._epoch_last_reason = (
                    f"Consensus storm: {secs_remaining}s until epoch end"
                )
                return False

            self._epoch_killswitch_active = False
            return True

        except Exception as exc:
            logger.debug(f"Epoch killswitch check failed ({exc}) — default safe")
            return True

    async def execute_arbitrage_opportunity(self, opportunity: Dict[str, Any]) -> dict:
        """
        Execute arbitrage opportunity by strategy type.
        Applies Reputation Circuit Breaker: rejects pairs with 3+ consecutive slippage errors.

        Args:
            opportunity: Arbitrage opportunity dict with strategy-specific data

        Returns:
            Execution result dict
        """
        # ── Epoch Shield: never trade near epoch boundary ───────────────────────
        if not await self._check_epoch_killswitch():
            logger.warning(f"🛡️ Epoch killswitch: {self._epoch_last_reason} — trade rejected")
            return {
                "status": "epoch_blocked",
                "message": self._epoch_last_reason,
            }

        # Circuit Breaker: Check for dust accumulation before execution
        if await self._check_dust_circuit_breaker():
            return {
                "status": "circuit_breaker",
                "message": "Dust accumulation detected - trading halted for safety"
            }

        # Reputation Circuit Breaker: reject banned pairs
        strategy = opportunity.get("strategy", "")
        ticker  = opportunity.get("ticker", "")
        mint    = opportunity.get("token_mint", "")
        pair_key = self._pair_key(ticker, mint)
        if self.is_pair_banned(pair_key):
            logger.warning(f"🚫 Pair {pair_key} rejected by Reputation Circuit Breaker (cooldown active)")
            return {"status": "rejected", "message": f"Pair {pair_key} in slippage cooldown"}

        try:
            strategy = opportunity.get("strategy")
            if strategy == "xstock_oracle_lag":
                result = await self._execute_xstock_opportunity(opportunity)

                # Reputation Circuit Breaker: track slippage failures per pair
                pair_key = self._pair_key(opportunity.get("ticker", ""), opportunity.get("token_mint", ""))
                if result.get("status") == "error" and "slippage" in str(result.get("message", "")).lower():
                    self.record_pair_slippage(pair_key)
                elif result.get("status") == "success":
                    # Reset failure counter on success
                    entry = self._pair_reputation.get(pair_key)
                    if entry and entry.get("failures", 0) > 0:
                        entry["failures"] = 0
                        logger.info(f"✅ Pair {pair_key} reputation cleared after successful trade")

                # Check rent recovery success
                if result.get("status") == "success":
                    await self._verify_rent_recovery()
                    # Fix 1 (Non-burning Dust): Post-tx dust sweep — clean intermediate ATA
                    # that passed through atomically (non-zero dust stays in ATA, CloseAccount
                    # no longer blocks the tx, dust is swept here after commit).
                    try:
                        from src.ingest.dust_sweeper import DustSweeper
                        sweeper = DustSweeper(self.keypair, self.rpc_url, self.session)
                        await sweeper.sweep_after_successful_tx()
                    except Exception as _e:
                        logger.debug(f"Post-tx dust sweep skipped: {_e}")
                elif result.get("status") == "error":
                    self.consecutive_failures += 1
                    # ATA Rent Trap Protection: Aggressive cleanup on failure
                    await self._emergency_ata_cleanup()

                return result
            else:
                logger.warning(f"Unknown strategy: {strategy}")
                return {"status": "error", "message": f"Unknown strategy: {strategy}"}
        except Exception as e:
            logger.error(f"Error executing arbitrage opportunity: {e}")
            self.consecutive_failures += 1
            return {"status": "error", "message": str(e)}

    async def _execute_xstock_opportunity(self, opportunity: Dict[str, Any]) -> dict:
        """Execute xStock oracle lag arbitrage opportunity with Flash Loan Pivot support."""
        try:
            from .tx_builder import JupiterTxBuilder
            tx_builder = JupiterTxBuilder(
                session=self.session,
                rpc_getter=self.rpc_getter,
            )

            # Extract opportunity data
            ticker = opportunity["ticker"]
            token_mint = opportunity["token_mint"]
            direction = opportunity["direction"]
            optimal_size_lamports = opportunity["optimal_size_lamports"]
            expected_profit_sol = opportunity["expected_profit_sol"]
            circular_quote = opportunity.get("quote")
            dex_swap_instructions = opportunity.get("dex_swap_instructions")

            logger.info(
                f"🎯 Executing xStock arbitrage: {ticker} {direction} | "
                f"Size: {optimal_size_lamports} lamports | Expected profit: {expected_profit_sol:.4f} SOL"
            )

            # ── Fetch Jupiter swap instructions for the atomic circular route ──────
            all_swap_ixs: List[Instruction] = []

            if dex_swap_instructions:
                all_swap_ixs = dex_swap_instructions

            if not all_swap_ixs and circular_quote:
                step1_data = circular_quote.get("step1", {})
                if step1_data:
                    step1_ixs, _ = await tx_builder.get_swap_instructions(step1_data, str(self.keypair.pubkey()), use_custom_cu=True)
                    if step1_ixs:
                        all_swap_ixs.extend(step1_ixs)

                step2_data = circular_quote.get("step2", {})
                if step2_data:
                    step2_ixs, _ = await tx_builder.get_swap_instructions(step2_data, str(self.keypair.pubkey()), use_custom_cu=True)
                    if step2_ixs:
                        all_swap_ixs.extend(step2_ixs)

            if not all_swap_ixs:
                logger.warning(f"No swap instructions available for {ticker} xStock arbitrage — dropping")
                return {"status": "error", "message": "Missing swap instructions"}

            # Phase 48: Dynamic Bank Lookup (Removed Placeholders)
            # xStocks trade against USDC, so we flashloan USDC.
            usdc_mint_str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            bank_info = MARGINFI_BANKS.get(usdc_mint_str, {})

            if not bank_info:
                logger.error(f"❌ No MarginFi bank info found for USDC flashloan")
                return {"status": "error", "message": "Missing USDC bank config"}

            # ════════════════════════════════════════════════════════════════════
            # FLASH LOAN PIVOT: If USDC bank is unavailable → borrow SOL + pivot
            # ════════════════════════════════════════════════════════════════════
            usdc_vault = str(bank_info["liquidity_vault"])
            usdc_available = await self._is_bank_liquid(usdc_vault, optimal_size_lamports)

            borrow_mint_str = usdc_mint_str   # default: USDC
            sol_borrow_bank_info = None
            entry_pivot_ixs: List[Instruction] = []   # SOL → USDC (only needed on pivot)
            exit_pivot_ixs: List[Instruction] = []    # USDC → SOL (only needed on pivot)

            if not usdc_available:
                logger.warning(
                    f"⚠️ USDC bank empty/at capacity for {ticker} — "
                    f"attempting Flash Loan Pivot via SOL"
                )
                sol_bank_id = os.getenv("MARGINFI_SOL_BANK",
                                        "CCwqExrqLGHtq12X182rFvA4KEDtK13q2E7B3Jp2Cxyj").strip()
                sol_bank_info = MARGINFI_BANKS.get(
                    "So11111111111111111111111111111111111111112", {}
                )
                if not sol_bank_info:
                    logger.error("❌ SOL bank info missing — cannot pivot")
                    return {"status": "error", "message": "Pivot failed: no SOL bank"}

                sol_vault = str(sol_bank_info["liquidity_vault"])
                sol_available = await self._is_bank_liquid(sol_vault, optimal_size_lamports)
                if not sol_available:
                    logger.error("❌ SOL bank also empty — both pivot targets exhausted")
                    return {"status": "error", "message": "Both USDC and SOL banks unavailable"}

                # Estimate swap costs for pivot
                swap_cost_lamports, sol_entry_ixs, sol_exit_ixs = \
                    await self._build_jupiter_pivot_ixs(optimal_size_lamports, expected_profit_sol)
                if swap_cost_lamports is None:
                    logger.error("❌ Failed to get Jupiter swap instructions for pivot")
                    return {"status": "error", "message": "Pivot Jupiter swap failed"}

                entry_pivot_ixs = sol_entry_ixs
                exit_pivot_ixs = sol_exit_ixs
                borrow_mint_str = "So11111111111111111111111111111111111111112"
                sol_borrow_bank_info = sol_bank_info

                # Net profit check after pivot swap costs
                cost_sol = swap_cost_lamports / 1e9
                if expected_profit_sol <= cost_sol * 2:  # Both entry + exit
                    logger.warning(
                        f"⚠️ Pivot not profitable: profit={expected_profit_sol:.6f} SOL "
                        f"< 2×swap_cost={cost_sol*2:.6f} SOL"
                    )
                    return {"status": "error", "message": "Pivot not profitable after fees"}

                logger.info(
                    f"🔄 FLASH PIVOT active: borrow SOL → swap→USDC → {ticker} arb → "
                    f"swap back → repay SOL | cost={cost_sol:.6f} SOL"
                )
            # ════════════════════════════════════════════════════════════════════

            bank_pubkey = str(bank_info["bank"])
            vault = str(bank_info["liquidity_vault"])
            vault_auth = str(bank_info["liquidity_vault_authority"])

            # Calculate dynamic tip based on expected profit and recommended Jito tip floor
            recommended_tip = 10000  # Default floor (0.00001 SOL)
            _dynamic_tip_accounts = None  # Fix 2: dynamic tip accounts
            if self.jito_executor:
                tip_info = self.jito_executor.get_current_tip_info()
                if tip_info:
                    recommended_tip = tip_info.get("recommended_tip", 10000)
                    _dynamic_tip_accounts = self.jito_executor.tip_accounts

            tip_percent = 0.40
            tip_lamports = int(expected_profit_sol * tip_percent * 1e9)
            jito_tip_lamports = max(recommended_tip, tip_lamports)

            # ── Fix 2 (Unfunded Jito Tip): Cap tip by actual native SOL balance ──
            # Jito tip is a native SOL transfer. Pre-flight simulation rejects
            # InsufficientFundsForFee if tip > current native balance.
            # Fetch balance and cap tip before building/bundling the transaction.
            try:
                bal_payload = {
                    "jsonrpc": "2.0", "id": 1,
                    "method": "getBalance",
                    "params": [str(self.keypair.pubkey())],
                }
                async with self.session.post(self.rpc_url, json=bal_payload, timeout=3.0) as bal_resp:
                    if bal_resp.status == 200:
                        bal_data = await bal_resp.json()
                        native_lamports = bal_data.get("result", {}).get("value", 0)
                        native_sol = native_lamports / 1e9
                        available_native = native_sol - 0.005  # reserve 0.005 SOL for gas
                        if available_native <= 0:
                            logger.warning(f"🚫 Insufficient native SOL for tip: {native_sol:.6f} SOL — skipping {ticker}")
                            return {"status": "error", "message": "Insufficient native SOL for tip"}
                        tip_before = jito_tip_lamports / 1e9
                        jito_tip_lamports = min(jito_tip_lamports, int(available_native * 1e9))
                        if jito_tip_lamports < 10000:
                            logger.warning(
                                f"⏭️ Tip {jito_tip_lamports / 1e9:.6f} SOL after balance cap below 10k lamports minimum — skipping {ticker}"
                            )
                            return {"status": "error", "message": "Tip below minimum after balance cap"}
                        logger.debug(
                            f"💰 Tip balance guard: native={native_sol:.6f} SOL | "
                            f"available={available_native:.6f} SOL | "
                            f"tip {tip_before:.6f} → {jito_tip_lamports / 1e9:.6f} SOL"
                        )
            except Exception as e:
                logger.debug(f"Native balance check failed ({e}), tip unchanged")

            logger.info(f"💰 Dynamic Jito tip calculated: {jito_tip_lamports} lamports (expected profit: {expected_profit_sol:.6f} SOL)")

            # Build arbitrage path: [borrow_asset, intermediate, return_asset]
            if borrow_mint_str == "So11111111111111111111111111111111111111112":
                # Pivot path: SOL → (entry swap) → USDC → xStock → USDC → (exit swap) → SOL
                arbitrage_path = [borrow_mint_str, usdc_mint_str, token_mint, usdc_mint_str, borrow_mint_str]
            else:
                arbitrage_path = [usdc_mint_str, token_mint, usdc_mint_str]

            active_bank_info = sol_borrow_bank_info if sol_borrow_bank_info else bank_info

            fl_result = await tx_builder.build_native_flashloan_tx(
                wallet_pubkey=str(self.keypair.pubkey()),
                arbitrage_path=arbitrage_path,
                borrow_amount_lamports=optimal_size_lamports,
                expected_min_profit_lamports=int(expected_profit_sol * 1e9),
                dex_swap_instructions=all_swap_ixs,
                marginfi_config=active_bank_info,
                jito_tip_lamports=jito_tip_lamports,
                borrow_mint=borrow_mint_str,
                use_jito=True,
                entry_pivot_ixs=entry_pivot_ixs,
                exit_pivot_ixs=exit_pivot_ixs,
                tip_accounts=_dynamic_tip_accounts,  # Fix 2: pass dynamic tip accounts from jito_executor
            )

            if not fl_result:
                return {"status": "error", "message": "Failed to build flashloan transaction"}

            # Fix 91: Auto-inject STRATEGY_EXTRA_ACCOUNTS discovered from prior "remaining account" errors
            strategy_key = "xstock_oracle_lag"
            extra_metas = _build_extra_account_metas(strategy_key)
            if extra_metas:
                logger.info(f"🔧 Injecting {len(extra_metas)} discovered extra accounts for {strategy_key}")
                for ix in reversed(fl_result["instructions"]):
                    if ix.program_id == Pubkey.from_string("MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"):
                        ix.accounts.extend(extra_metas)
                        break

            # Convert to VersionedTransaction
            from solders.message import MessageV0
            from solders.transaction import VersionedTransaction
            from solders.hash import Hash

            # Get blockhash
            blockhash_payload = {"jsonrpc": "2.0", "id": 1, "method": "getLatestBlockhash"}
            async with self.session.post(self.rpc_url, json=blockhash_payload) as resp:
                bh_data = await resp.json()
                recent_blockhash = bh_data["result"]["value"]["blockhash"]

            # Fix 3: MTU-Safe ALT resolution — pull resolved accounts from alt_manager cache
            resolved_alts: List[Pubkey] = []
            _flavor_alt_pubkeys = (
                fl_result.get("address_lookup_table_pubkeys") or  # build_marginfi_flashloan_tx key
                fl_result.get("address_lookup_tables") or          # build_native_flashloan_tx key
                []
            )
            for alt_pk_str in _flavor_alt_pubkeys:
                if not alt_pk_str or not self.alt_manager:
                    continue
                _resolved = await self.alt_manager.resolve_alt(Pubkey.from_string(alt_pk_str))
                if _resolved:
                    resolved_alts.extend(_resolved)

            message = MessageV0.try_compile(
                payer=self.keypair.pubkey(),
                instructions=fl_result["instructions"],
                address_lookup_table_accounts=resolved_alts,
                recent_blockhash=Hash.from_string(recent_blockhash)
            )
            transaction = VersionedTransaction(message, [self.keypair])

            # ─── Pre-Trade Guard: profit re-check in last ~50 ms ──────────────────
            # Verify the swap legs still deliver positive profit after fees right
            # before the transaction is signed and handed to Jito.  If the pool
            # price moved >0.1% in the 100-300 ms between quote fetch and now,
            # abort early — cheaper than burning tip + gas.
            try:
                from .pre_trade_guard import PreTradeGuard
                _ptg = PreTradeGuard()
                _base_fee = 5000  # 0.000005 SOL in lamports (base network fee)
                prof_ok, prof_reason, actual_net = await _ptg.check_profit_before_execution(
                    input_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",   # USDC leg in
                    output_mint=token_mint,                                  # xStock leg out
                    amount_lamports=optimal_size_lamports,
                    jito_tip_lamports=jito_tip_lamports,
                    base_fee_lamports=_base_fee,
                    expected_profit_lamports=int(expected_profit_sol * 1e9),
                )
                if not prof_ok:
                    logger.warning(f"🚫 Pre-trade guard blocked: {prof_reason}")
                    return {"status": "blocked", "message": prof_reason}
                logger.debug(f"✅ Pre-trade profit OK: {actual_net/1e9:.6f} SOL")
            except Exception as _ptg_e:
                logger.debug(f"Pre-trade re-check skipped ({_ptg_e}) — proceeding")

            # Send via Jito
            jito_result = await self.jito_executor.send_bundle([transaction])

            if jito_result.get("success"):
                # Fix 1 (wSOL Death Spiral): build_native_flashloan_tx closed wSOL + recreated ATA
                # inside the arb transaction.  Mark the atomic close so wallet_balance_listener
                # skips its own standalone CloseAccount×for the same ATA (saves one RPC tx / gas).
                try:
                    from arb_bot import mark_wsol_atomically_closed
                    await mark_wsol_atomically_closed()
                except Exception:
                    pass  # non-fatal — listener has its own cooldown guard
                return {
                    "status": "success",
                    "bundle_id": jito_result.get("bundle_id"),
                    "strategy": "xstock_oracle_lag",
                    "ticker": ticker,
                    "pivoted": not usdc_available,
                }
            else:
                return {"status": "error", "message": jito_result.get("error")}

        except Exception as e:
            logger.error(f"Error executing xStock opportunity: {e}")
            return {"status": "error", "message": str(e)}

    # ─── Reputation Circuit Breaker (per-pair slippage cooldown) ────────────────

    def _pair_key(self, ticker: str, mint: str) -> str:
        """Build a stable human-readable pair key for reputation tracking."""
        return f"{ticker}/{mint[:12]}"

    def record_pair_slippage(self, pair_key: str) -> None:
        """Record a slippage failure for a specific pair. Ban it if limit exceeded."""
        now = time.time()
        entry = self._pair_reputation.get(pair_key)
        if entry is None or entry.get("banned_until", 0) < now:
            # Either first failure or cooldown expired — reset counter
            self._pair_reputation[pair_key] = {
                "failures": 1,
                "banned_until": 0,
                "last_error": "slippage",
            }
            logger.debug(f"📊 Pair {pair_key}: 1st slippage noted (cooldown not yet active)")
            return

        entry["failures"] += 1
        entry["last_error"] = "slippage"
        if entry["failures"] >= self.PAIR_SLIPPAGE_LIMIT:
            entry["banned_until"] = now + self.PAIR_COOLDOWN_SECONDS
            logger.critical(
                f"🚨 REPUTATION BREAKER: Pair {pair_key} banned for "
                f"{self.PAIR_COOLDOWN_SECONDS}s ({entry['failures']} consecutive slippage fails)"
            )
        else:
            logger.warning(
                f"⚠️ Pair {pair_key}: {entry['failures']}/{self.PAIR_SLIPPAGE_LIMIT} "
                f"consecutive slippage failures"
            )

    def is_pair_banned(self, pair_key: str) -> bool:
        """Return True if the pair is currently in cooldown."""
        now = time.time()
        entry = self._pair_reputation.get(pair_key)
        if entry and entry.get("banned_until", 0) > now:
            return True
        return False

    def reset_pair_reputation(self, pair_key: str) -> None:
        """Manually reset the failure counter for a pair (e.g. after a successful trade)."""
        self._pair_reputation.pop(pair_key, None)
        logger.info(f"🔄 Pair reputation reset: {pair_key}")

    # ─── Flash Loan Pivot Helpers ───────────────────────────────────────────────

    async def _is_bank_liquid(self, vault_pubkey: str, required_lamports: int) -> bool:
        """Check if a MarginFi bank vault has enough free liquidity (95% cap)."""
        try:
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getTokenAccountBalance",
                "params": [vault_pubkey],
            }
            async with self.session.post(self.rpc_url, json=payload, timeout=3.0) as resp:
                data = await resp.json()
                if "result" in data and "value" in data["result"]:
                    vault_lamports = int(data["result"]["value"]["amount"])
                    safe = int(vault_lamports * 0.95)
                    return required_lamports <= safe
        except Exception as e:
            logger.debug(f"Bank liquidity check failed for {vault_pubkey[:8]}: {e}")
        return False  # Conservative: treat failures as unavailable

    async def _build_jupiter_pivot_ixs(
        self, borrow_lamports: int, expected_profit_sol: float
    ) -> Tuple[Optional[int], List[Instruction], List[Instruction]]:
        """Fetch Jupiter swap instructions for the Flash Loan Pivot legs.

        Returns (total_swap_cost_lamports, entry_ixs, exit_ixs).
        entry_ixs: SOL → USDC (enter the arb)
        exit_ixs:  USDC → SOL (exit + repay in SOL)
        On any failure the first element is None.
        """
        wallet_pk = str(self.keypair.pubkey())
        sol_pk = str(SOL_MINT)
        usdc_pk = str(USDC_MINT)
        # Use 10% of borrow amount as conservative entry size
        entry_amount = max(borrow_lamports // 10, 1_000_000)  # min 0.001 SOL
        exit_amount = entry_amount  # same size for return leg

        entry_ixs: List[Instruction] = []
        exit_ixs: List[Instruction] = []
        total_cost = 0

        # ── Entry: SOL → USDC ──────────────────────────────────────────────
        entry_quote_url = (
            f"{JUPITER_QUOTE_URL}?inputMint={sol_pk}&outputMint={usdc_pk}"
            f"&amount={int(entry_amount)}&slippageBps=30&maxAccounts=8"
            f"&onlyDirectRoutes=true&restrictIntermediateTokens=true"
        )
        try:
            async with self.session.get(entry_quote_url, timeout=4.0) as resp:
                if resp.status != 200:
                    logger.warning(f"Pivot entry quote failed: HTTP {resp.status}")
                    return None, [], []
                entry_quote = await resp.json()
                out_amount = int(entry_quote.get("outAmount", 0))
                if out_amount == 0:
                    logger.warning("Pivot entry quote: outAmount == 0")
                    return None, [], []
        except Exception as e:
            logger.warning(f"Pivot entry quote error: {e}")
            return None, [], []

        entry_swap_payload = {
            "quoteResponse": entry_quote,
            "userPublicKey": wallet_pk,
            "wrapAndUnwrapSol": False,
            "dynamicComputeUnitLimit": False,
            "maxAccounts": "8",
        }
        try:
            async with self.session.post(
                JUPITER_SWAP_IX_URL, json=entry_swap_payload, timeout=5.0
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"Pivot entry swap-ix failed: HTTP {resp.status}")
                    return None, [], []
                entry_ix_data = await resp.json()
                if "error" in entry_ix_data:
                    logger.warning(f"Pivot entry swap-ix error: {entry_ix_data['error']}")
                    return None, [], []
                for ix_raw in entry_ix_data.get("swapInstruction", []), *(
                    entry_ix_data.get("setupInstructions", []) or []
                ):
                    pass  # parsed below
        except Exception as e:
            logger.warning(f"Pivot entry swap-ix request error: {e}")
            return None, [], []

        # Parse entry instructions
        if "swapInstruction" in entry_ix_data and entry_ix_data["swapInstruction"]:
            entry_ixs.append(self._parse_jupiter_ix(entry_ix_data["swapInstruction"]))
        for setup_ix in (entry_ix_data.get("setupInstructions") or []):
            entry_ixs.append(self._parse_jupiter_ix(setup_ix))

        price_impact_pct = entry_quote.get("priceImpactPct", "0")
        try:
            price_impact = float(price_impact_pct.replace("%", "")) if isinstance(price_impact_pct, str) else float(price_impact_pct)
        except (ValueError, AttributeError):
            price_impact = 0.0
        total_cost += int(entry_amount * price_impact / 100)

        # ── Exit: USDC → SOL ───────────────────────────────────────────────
        # Task 16: ensure int (outAmount may be Decimal/float in some paths)
        exit_amount_ui = int(out_amount)
        exit_quote_url = (
            f"{JUPITER_QUOTE_URL}?inputMint={usdc_pk}&outputMint={sol_pk}"
            f"&amount={exit_amount_ui}&slippageBps=30&maxAccounts=8"
            f"&onlyDirectRoutes=true&restrictIntermediateTokens=true"
        )
        try:
            async with self.session.get(exit_quote_url, timeout=4.0) as resp:
                if resp.status != 200:
                    logger.warning(f"Pivot exit quote failed: HTTP {resp.status}")
                    # fall through with entry only
                else:
                    exit_quote = await resp.json()
                    out_exit = int(exit_quote.get("outAmount", 0))
                    if out_exit > 0:
                        exit_swap_payload = {
                            "quoteResponse": exit_quote,
                            "userPublicKey": wallet_pk,
                            "wrapAndUnwrapSol": False,
                            "dynamicComputeUnitLimit": False,
                            "maxAccounts": "8",
                        }
                        async with self.session.post(
                            JUPITER_SWAP_IX_URL, json=exit_swap_payload, timeout=5.0
                        ) as resp2:
                            if resp2.status == 200:
                                exit_ix_data = await resp2.json()
                                if "error" not in exit_ix_data:
                                    if "swapInstruction" in exit_ix_data and exit_ix_data["swapInstruction"]:
                                        exit_ixs.append(self._parse_jupiter_ix(exit_ix_data["swapInstruction"]))
                                    for setup_ix in (exit_ix_data.get("setupInstructions") or []):
                                        exit_ixs.append(self._parse_jupiter_ix(setup_ix))
        except Exception as e:
            logger.debug(f"Pivot exit swap setup error (non-fatal): {e}")

        if not entry_ixs:
            logger.warning("Pivot: no entry swap instructions fetched")
            return None, [], []

        logger.info(
            f"🔄 Flash Pivot swap instructions: entry={len(entry_ixs)} ixs, "
            f"exit={len(exit_ixs)} ixs, cost≈{total_cost/1e9:.6f} SOL"
        )
        return total_cost, entry_ixs, exit_ixs

    def _parse_jupiter_ix(self, ix_data: dict) -> Instruction:
        """Parse a raw Jupiter instruction dict into a solders Instruction."""
        raw_b64 = ix_data["data"]
        padded = raw_b64 + "=" * (-len(raw_b64) % 4)
        return Instruction(
            program_id=Pubkey.from_string(ix_data["programId"]),
            accounts=[
                AccountMeta(
                    pubkey=Pubkey.from_string(m["pubkey"]),
                    is_signer=m["isSigner"],
                    is_writable=m["isWritable"],
                )
                for m in ix_data["accounts"]
            ],
            data=base64.b64decode(padded) if isinstance(raw_b64, str) else bytes(raw_b64),
        )

    async def _check_dust_circuit_breaker(self) -> bool:
        """
        Check if dust accumulation has triggered circuit breaker.
        Returns True if trading should be halted.
        """
        if self.dust_alert_triggered:
            return True

        # Check consecutive failure rate
        if self.consecutive_failures >= self.max_consecutive_failures:
            logger.critical(f"🚨 CIRCUIT BREAKER: {self.consecutive_failures} consecutive failures detected")
            self.dust_alert_triggered = True
            return True

        return False

    async def _verify_rent_recovery(self):
        """
        Verify that rent recovery worked correctly after successful transaction.
        If SOL balance didn't return, trigger dust alert.
        """
        try:
            # This would check actual wallet balance vs expected
            # For now, reset consecutive failures on success
            self.consecutive_failures = max(0, self.consecutive_failures - 1)

        except Exception as e:
            logger.error(f"Rent recovery verification error: {e}")

    async def _emergency_ata_cleanup(self):
        """Emergency ATA cleanup to prevent rent trap accumulation."""
        try:
            # Import DustSweeper here to avoid circular imports
            from src.ingest.dust_sweeper import DustSweeper

            # Create DustSweeper instance
            dust_sweeper = DustSweeper(self.keypair, self.rpc_url, self.session)

            # Aggressive sweep - close all empty ATAs immediately
            recovered_lamports = await dust_sweeper._sweep_dust()
            recovered_sol = recovered_lamports / 1_000_000_000

            if recovered_lamports > 0:
                logger.warning(f"🚨 Emergency ATA cleanup: Recovered {recovered_sol:.6f} SOL from stranded accounts")
            else:
                logger.debug("Emergency ATA cleanup: No stranded accounts found")

        except Exception as e:
            logger.error(f"Emergency ATA cleanup failed: {e}")

    def reset_circuit_breaker(self):
        """Reset circuit breaker (for manual intervention)."""
        self.dust_alert_triggered = False
        self.consecutive_failures = 0
        logger.info("🔄 Circuit breaker reset - trading resumed")

    async def _check_wallet_balance_after_execution(self):
        """Check wallet balance after successful execution to detect insufficient funds issues."""
        try:
            if not self.keypair or not hasattr(self, 'session') or not hasattr(self, 'rpc_url'):
                return

            # Get current balance
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBalance",
                "params": [str(self.keypair.pubkey())]
            }

            async with self.session.post(self.rpc_url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "result" in data and "value" in data["result"]:
                        balance_lamports = data["result"]["value"]
                        balance_sol = balance_lamports / 1_000_000_000
                        logger.debug(f"💰 Post-execution balance check: {balance_sol:.6f} SOL")

                        # ── Task 4: Main Wallet Rent-Exemption Killswitch ────────────
                        # If native SOL balance < 0.003 SOL, Solana GC will delete the
                        # wallet account. Kill process immediately to prevent that.
                        try:
                            from src.ingest.pre_trade_guard import PreTradeGuard
                            PreTradeGuard.enforce_hard_floor(balance_sol)
                        except Exception:
                            pass
                        # ──────────────────────────────────────────────────────────────

                        # Warn if balance is critically low
                        if balance_sol < self.critical_balance_threshold:
                            logger.warning(f"⚠️ Low balance after execution: {balance_sol:.6f} SOL (below {self.critical_balance_threshold} SOL threshold)")
                    else:
                        logger.warning("Failed to parse balance from RPC response")
                else:
                    logger.warning(f"Failed to get balance: HTTP {resp.status}")

        except Exception as e:
            logger.error(f"Balance check failed: {e}")

    def discover_extra_account(self, error_msg: str, token_key: str):
        """Fix 91: Extract missing remaining account Pubkey from RPC error and cache it."""
        # Поиск Base58 строки (Pubkey) в тексте ошибки
        match = re.search(r'([1-9A-HJ-NP-Za-km-z]{32,44})', error_msg)
        if match:
            pk = match.group(1)
            # STRATEGY_EXTRA_ACCOUNTS — глобальный словарь
            STRATEGY_EXTRA_ACCOUNTS.setdefault(token_key, set()).add(pk)
            logger.warning(f"🔧 Self-Healing: Discovered missing remaining account {pk} for {token_key}")

    async def _route_transaction(self, session: aiohttp.ClientSession, cfg, rpc_url: str, transaction: VersionedTransaction, jito_tip_lamports: int) -> dict:
        """Route transaction using appropriate method based on current slot leader."""
        try:
            # Get current slot
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSlot",
                "params": []
            }
            async with session.post(rpc_url, json=payload) as resp:
                if resp.status != 200:
                    logger.error("Failed to get current slot")
                    return False
                data = await resp.json()
                current_slot = data["result"]

            # Fix 78: Slot-Level Execution Mutex - prevent parallel writes to single MARGINFI_ACCOUNT
            if current_slot == self.last_slot_executed:
                logger.warning(f"⏳ Slot {current_slot} already executed - queuing for next slot")
                await asyncio.sleep(0.45)  # Wait ~1 slot (400ms)
                # Re-fetch slot after sleep
                async with session.post(rpc_url, json=payload) as resp:
                    if resp.status == 200:
                        current_slot = (await resp.json())["result"]
            
            # ── JITO FIX: Remove stale hardcoded leader check ──────────
            # The hardcoded JITO_VALIDATOR_VOTES list in leader_tracker.py is always
            # stale (~100% outdated). Jito Block Engine auto-inserts bundles into the
            # next Jito slot within 5 slots — no local leader check needed.
            # See: https://jito-labs.gitbook.io/mev/searcher-resources/bundles
            logger.info(f"🎯 Sending bundle to Jito Block Engine unconditionally (slot={current_slot})...")
            
            self.last_slot_executed = current_slot  # Mark slot as used
            bundle_result = await self.jito_executor.send_bundle([transaction])
            if bundle_result.get("success") and bundle_result.get("bundle_id"):
                self._pending_bundle_slots[bundle_result["bundle_id"]] = {
                    "sent_slot": current_slot,
                    "sent_at": time.time(),
                    "tip_lamports": jito_tip_lamports,
                    "deducted_amount": jito_tip_lamports / 1_000_000_000,
                }
                # ── Phase 49: Optimistic State ───────────────────────────────────
                from arb_bot import stats, stats_lock
                tip_deducted = jito_tip_lamports / 1e9
                async with stats_lock:
                    prev = stats.get("virtual_balance", 0.0)
                    stats["virtual_balance"] = max(0.0, prev - tip_deducted)
                    stats["last_balance"] = stats["virtual_balance"]
                self.is_account_busy = False   # MarginFi account is instantly free
                logger.debug(
                    f"⚡ Optimistic balance: virtual_balance {prev:.6f} → "
                    f"{stats['virtual_balance']:.6f} SOL (tip {tip_deducted:.6f})"
                )
            return bundle_result

        except Exception as e:
            err = str(e)
            if "remaining account" in err.lower():
                self.discover_extra_account(err, "current_strategy")
            logger.error(f"Execution routing failed: {e}")
            return {"success": False, "error": str(e)}

    # ───────────── Fix 51: Jito Bundle Self-Cancellation + Ghost Balance Refund ──────────────────────

    async def _self_cancel_stale_bundles(self):
        """Detect bundles dropped by Jito (>5 seconds old) and refund the virtual balance.
        Prevents "Ghost Balance" bug where virtual_balance is never returned after a dropped bundle.
        """
        while True:
            try:
                if not self._pending_bundle_slots:
                    await asyncio.sleep(0.5)
                    continue

                current_time = time.time()
                for bid, meta in list(self._pending_bundle_slots.items()):
                    # Если прошло больше 5 секунд (бандл 100% умер в Jito)
                    if current_time - meta.get("sent_at", current_time) > 5.0:
                        logger.warning(
                            f"⚡ Bundle {bid[:8]} dropped by Jito. Refunding virtual balance."
                        )

                        # ВОЗВРАЩАЕМ БАЛАНС
                        try:
                            from arb_bot import stats
                            from arb_bot import stats_lock
                            refund_amount = meta.get("deducted_amount", 0)
                            async with stats_lock:
                                stats["virtual_balance"] += refund_amount
                        except (ImportError, KeyError) as e:
                            logger.debug(f"Ghost balance refund unavailable: {e}")

                        self._stale_bundle_ids.add(bid)

                # Очистка
                for bid in list(self._stale_bundle_ids):
                    self._pending_bundle_slots.pop(bid, None)
                    self._stale_bundle_ids.discard(bid)

            except Exception as e:
                logger.debug(f"Reconciliation error: {e}")
            await asyncio.sleep(1.0)

    def pop_and_clear_stale_bundle_id(self) -> Optional[str]:
        """Return and consume one stale bundle id so the caller can log it."""
        if self._stale_bundle_ids:
            return self._stale_bundle_ids.pop()
        return None

    @property
    def has_stale_bundle(self) -> bool:
        return bool(self._stale_bundle_ids)