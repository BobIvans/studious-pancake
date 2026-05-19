"""Execution Router for Hybrid Jito/Standard Transaction Switching."""

import asyncio
import logging
import base64
import re
import time
from typing import Optional, Dict, Any, Set
import aiohttp
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from .leader_tracker import LeaderTracker
from .g2_tip_manager import ExecutionGuard
# Phase 48: Import dynamic bank info from arb_bot
try:
    from arb_bot import MARGINFI_BANKS
except ImportError:
    MARGINFI_BANKS = {}

logger = logging.getLogger(__name__)

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

    def __init__(self, leader_tracker: LeaderTracker, jito_executor, session: aiohttp.ClientSession, rpc_url: str, keypair=None):
        self.leader_tracker = leader_tracker
        self.jito_executor = jito_executor
        self.standard_tx_sender = StandardTransactionSender(session, rpc_url)
        self.execution_queue = asyncio.Queue(maxsize=100)  # Increased from 1 to prevent deadlocks
        self._processor_task = None
        self.keypair = keypair
        self.session = session
        self.rpc_url = rpc_url

        # Circuit Breaker: Anti-Dust protection
        self.critical_balance_threshold = 0.017  # SOL - panic if rent recovery fails
        self.dust_alert_triggered = False
        self.consecutive_failures = 0
        self.last_slot_executed = 0  # Fix 78: Slot mutex for single MARGINFI_ACCOUNT
        self.max_consecutive_failures = 3

        # Execution Guard (Circuit Breaker for consecutive failures)
        self.execution_guard = ExecutionGuard()

        # Fix 51: Jito Bundle Self-Cancellation — track stale bundles for overwrite
        # map: bundle_id -> {"sent_slot": int, "sent_at": float, "endpoint": str, "tip_lamports": int, "deducted_amount": int}
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

    async def execute_arbitrage_opportunity(self, opportunity: Dict[str, Any]) -> dict:
        """
        Execute arbitrage opportunity by strategy type.

        Args:
            opportunity: Arbitrage opportunity dict with strategy-specific data

        Returns:
            Execution result dict
        """
        # Circuit Breaker: Check for dust accumulation before execution
        if await self._check_dust_circuit_breaker():
            return {
                "status": "circuit_breaker",
                "message": "Dust accumulation detected - trading halted for safety"
            }

        try:
            strategy = opportunity.get("strategy")
            if strategy == "xstock_oracle_lag":
                result = await self._execute_xstock_opportunity(opportunity)

                # Check rent recovery success
                if result.get("status") == "success":
                    await self._verify_rent_recovery()
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
        """Execute xStock oracle lag arbitrage opportunity."""
        try:
            from .tx_builder import JupiterTxBuilder
            tx_builder = JupiterTxBuilder(session=self.session, rpc_url=self.rpc_url)

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
            # The opportunity must carry pre-fetched instructions for BOTH legs.
            # If not present, attempt one last fetch from the circular quote data.
            all_swap_ixs: List[Instruction] = []

            if dex_swap_instructions:
                all_swap_ixs = dex_swap_instructions

            if not all_swap_ixs and circular_quote:
                # Fetch leg 1: xStock → USDC
                step1_data = circular_quote.get("step1", {})
                if step1_data:
                    step1_ixs, _ = await tx_builder.get_swap_instructions(step1_data, str(self.keypair.pubkey()), use_custom_cu=True)
                    if step1_ixs:
                        all_swap_ixs.extend(step1_ixs)

                # Fetch leg 2: USDC → xStock (the return leg — what makes this immediate/atomic)
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
            usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            bank_info = MARGINFI_BANKS.get(usdc_mint, {})
            
            if not bank_info:
                logger.error(f"❌ No MarginFi bank info found for USDC flashloan")
                return {"status": "error", "message": "Missing USDC bank config"}

            bank_pubkey = str(bank_info["bank"])
            vault = str(bank_info["liquidity_vault"])
            vault_auth = str(bank_info["liquidity_vault_authority"])
            
            # Calculate dynamic tip based on expected profit and recommended Jito tip floor
            recommended_tip = 10000  # Default floor (0.00001 SOL)
            if self.jito_executor:
                tip_info = self.jito_executor.get_current_tip_info()
                if tip_info:
                    recommended_tip = tip_info.get("recommended_tip", 10000)
            
            tip_percent = 0.40
            tip_lamports = int(expected_profit_sol * tip_percent * 1e9)
            jito_tip_lamports = max(recommended_tip, tip_lamports)

            logger.info(f"💰 Dynamic Jito tip calculated: {jito_tip_lamports} lamports (expected profit: {expected_profit_sol:.6f} SOL)")

            fl_result = await tx_builder.build_native_flashloan_tx(
                wallet_pubkey=str(self.keypair.pubkey()),
                arbitrage_path=[usdc_mint, token_mint, usdc_mint],
                borrow_amount_lamports=optimal_size_lamports,
                expected_min_profit_lamports=int(expected_profit_sol * 1e9), # Simplified
                dex_swap_instructions=all_swap_ixs,
                marginfi_config=bank_info,
                jito_tip_lamports=jito_tip_lamports,
                borrow_mint=usdc_mint,
                use_jito=True
            )

            if not fl_result:
                return {"status": "error", "message": "Failed to build flashloan transaction"}

            # Fix 91: Auto-inject STRATEGY_EXTRA_ACCOUNTS discovered from prior "remaining account" errors
            strategy_key = "xstock_oracle_lag"
            extra_metas = _build_extra_account_metas(strategy_key)
            if extra_metas:
                logger.info(f"🔧 Injecting {len(extra_metas)} discovered extra accounts for {strategy_key}")
                # Append each extra account to the repay instruction's AccountMeta list
                # The repay instruction is the last MarginFi instruction in the list
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

            message = MessageV0.try_compile(
                payer=self.keypair.pubkey(),
                instructions=fl_result["instructions"],
                address_lookup_table_accounts=[], 
                recent_blockhash=Hash.from_string(recent_blockhash)
            )
            transaction = VersionedTransaction(message, [self.keypair])

            # Send via Jito
            jito_result = await self.jito_executor.send_bundle([transaction])
            
            if jito_result.get("success"):
                return {
                    "status": "success",
                    "bundle_id": jito_result.get("bundle_id"),
                    "strategy": "xstock_oracle_lag",
                    "ticker": ticker
                }
            else:
                return {"status": "error", "message": jito_result.get("error")}

        except Exception as e:
            logger.error(f"Error executing xStock opportunity: {e}")
            return {"status": "error", "message": str(e)}

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
        match = re.search(r'([1-9A-HJ-NP-Za-km-z]{32,44})', error_msg)
        if match:
            pk = match.group(1)
            STRATEGY_EXTRA_ACCOUNTS.setdefault(token_key, set()).add(pk)
            logger.warning(f"🔧 Discovered extra account {pk} for {token_key}")

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
            
            # Check if Jito slot
            if self.leader_tracker.is_jito_slot(current_slot):
                logger.info(f"🎯 Jito slot detected (leader: {self.leader_tracker.get_current_slot_leader(current_slot)[:8]}...) - using Jito bundle")
                
                self.last_slot_executed = current_slot  # Mark slot as used
                # Fix 51: Record the slot so the self-cancel task can detect staleness
                bundle_result = await self.jito_executor.send_bundle([transaction])
                if bundle_result.get("success") and bundle_result.get("bundle_id"):
                    self._pending_bundle_slots[bundle_result["bundle_id"]] = {
                        "sent_slot": current_slot,
                        "sent_at": time.time(),
                        "tip_lamports": jito_tip_lamports,
                        "deducted_amount": 0,
                    }
                return bundle_result
            else:
                # Phase 48: STRICT_JITO_MODE is now mandatory
                logger.warning(f"⏳ Non-Jito slot ({current_slot}). Trade queued/skipped for capital protection.")
                return {
                    "success": False,
                    "error": "non_jito_slot",
                    "message": "Trade skipped (STRICT_JITO_MODE enabled)."
                }

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