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
import src.ingest.shared_state as shared_state


# ════════════════════════════════════════════════════════════════════════
# Task 11: MarginFi Account Pooling
# ════════════════════════════════════════════════════════════════════════
class MarginFiAccountPool:
    """
    Round-Robin pool of MarginFi accounts for concurrent flashloan execution.

    Instead of locking to one slot (450ms sleep) when a single MARGINFI_ACCOUNT
    is in use, this pool lets the bot execute trades on different MarginFi
    accounts in the same slot — enabling parallel arb execution at scale.

    Usage:
        pool = MarginFiAccountPool.from_env()
        acct = pool.checkout(current_slot)
        # ... use acct for flashloan ...
        pool.checkin(acct)  # optional — slot guard is automatic
    """

    def __init__(self, accounts: List[str], bank_configs: Optional[Dict[str, Dict]] = None):
        if not accounts:
            raise ValueError("MarginFiAccountPool requires at least one account")
        self.accounts = list(accounts)
        self._last_used_slot: Dict[str, int] = {}  # account_pubkey -> last_used_slot
        self._current_index = 0
        self._lock = asyncio.Lock()
        # Optional: per-account bank config overrides (keyed by marginfi_account pubkey)
        self.bank_configs = bank_configs or {}

    @classmethod
    def from_env(cls) -> "MarginFiAccountPool":
        """
        Create pool from MARGINFI_ACCOUNTS env var (comma-separated list).
        Falls back to MARGINFI_ACCOUNT if only one account is configured.
        """
        accounts_str = os.getenv("MARGINFI_ACCOUNTS", "")
        if accounts_str.strip():
            accounts = [a.strip() for a in accounts_str.split(",") if a.strip()]
            logger.info(f"🏦 MarginFi Account Pool: {len(accounts)} accounts (MARGINFI_ACCOUNTS)")
        else:
            single = os.getenv("MARGINFI_ACCOUNT", "Fk4G5NB5e1NyULQCCpTNLWCmChCW2UbDwpkEofqAiHk2")
            accounts = [single.strip()] if single.strip() else []
            logger.info(f"🏦 MarginFi Account Pool: 1 account (MARGINFI_ACCOUNT fallback)")

        if not accounts:
            logger.warning("🏦 No MarginFi accounts configured — using hardcoded default")
            accounts = ["Fk4G5NB5e1NyULQCCpTNLWCmChCW2UbDwpkEofqAiHk2"]

        return cls(accounts)

    async def checkout(self, current_slot: int) -> Tuple[str, int]:
        """
        Get the next available MarginFi account for the given slot.

        Returns:
            Tuple of (account_pubkey_string, index_in_pool)
        """
        async with self._lock:
            for _ in range(len(self.accounts)):
                acct = self.accounts[self._current_index]
                idx = self._current_index
                self._current_index = (self._current_index + 1) % len(self.accounts)

                if self._last_used_slot.get(acct, 0) != current_slot:
                    self._last_used_slot[acct] = current_slot
                    logger.debug(
                        f"🏦 Pool checkout: acct={acct[:8]}... "
                        f"slot={current_slot} idx={idx}/{len(self.accounts)}"
                    )
                    return acct, idx

            # All accounts used in this slot — return the next one anyway
            # (better to risk AccountInUse than to delay 450ms)
            acct = self.accounts[self._current_index % len(self.accounts)]
            self._current_index = (self._current_index + 1) % len(self.accounts)
            self._last_used_slot[acct] = current_slot
            logger.warning(
                f"🏦 All accounts busy in slot {current_slot}, "
                f"re-using {acct[:8]}... (risk: AccountInUse)"
            )
            return acct, self._current_index

    def get_bank_config(self, account: str, default_config: Dict) -> Dict:
        """Get bank config for a specific account, falling back to default."""
        if account in self.bank_configs:
            cfg = dict(default_config)
            cfg.update(self.bank_configs[account])
            return cfg
        return dict(default_config)

    @property
    def count(self) -> int:
        return len(self.accounts)

    def is_using_single_account(self) -> bool:
        """Returns True if pool has only one account (no parallelism benefit)."""
        return len(self.accounts) <= 1

from .leader_tracker import LeaderTracker
from .g2_tip_manager import ExecutionGuard
from .tx_builder import JupiterTxBuilder
from .epoch_tracker import EpochTracker

# FIX 13: Shared global Jupiter rate limiter — 4 req/s across all modules
from .jupiter_api_client import get_jupiter_limiter

logger = logging.getLogger(__name__)

RENT_SPL_ATA_SOL = 0.00204
RENT_TOKEN2022_SOL = 0.0035

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

    def __init__(
        self,
        leader_tracker: LeaderTracker,
        jito_executor,
        session: aiohttp.ClientSession,
        rpc_url: str,
        keypair=None,
        alt_manager=None,
        rpc_getter: Optional[Callable[[], str]] = None,
        blockhash_getter: Optional[Callable[[], str]] = None,
        optimal_trade_sizer=None,
        ata_cache=None,
        flash_pivot_engine=None,
        cfg=None,
        data_aggregator=None,
        stats=None,
        stats_lock=None,
        blockhash_mgr=None,
    ):
        self.leader_tracker = leader_tracker
        self.jito_executor = jito_executor
        self.standard_tx_sender = StandardTransactionSender(session, rpc_url)
        self.cfg = cfg
        self.data_aggregator = data_aggregator
        self.stats = stats
        self.stats_lock = stats_lock
        self.execution_queue = asyncio.Queue(maxsize=100)
        self._processor_task = None
        self.keypair = keypair
        self.session = session
        self._static_rpc_url = rpc_url
        self.rpc_getter = rpc_getter
        self.blockhash_getter = blockhash_getter
        self.blockhash_mgr = blockhash_mgr
        self.rpc_url = rpc_url
        self.optimal_trade_sizer = optimal_trade_sizer
        self.ata_cache = ata_cache if ata_cache is not None else set()
        self.flash_pivot_engine = flash_pivot_engine # Task 18
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

        # ── Task 11: MarginFi Account Pool ───────────────────────────────────
        # Replace 450ms slot-mutex with round-robin pool checkout.
        # Can execute multiple independent flashloans in the same slot.
        self.marginfi_pool = MarginFiAccountPool.from_env()

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
        # Start Epoch Shield
        asyncio.create_task(self.epoch_tracker.start())

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
                result = await asyncio.wait_for(future, timeout=5.0)
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
                elif result.get("status") == "error":
                    self.consecutive_failures += 1
                    # ATA Rent Trap Protection: Aggressive cleanup on failure
                    await self._emergency_ata_cleanup()

                return result
            elif strategy == "lst_unstake":
                # LST Instant Unstake Arbitrage
                from .lst_unstake_arbitrage import LstInstantUnstakeArbitrage
                lst_arb = LstInstantUnstakeArbitrage(
                    session=self.session,
                    rpc_url=self.rpc_url,
                    cfg=self.cfg,
                    data_aggregator=self.data_aggregator,
                    marginfi_account=os.getenv("MARGINFI_ACCOUNT", ""),
                    tx_builder=JupiterTxBuilder(session=self.session, rpc_getter=self.rpc_getter),
                    optimal_trade_sizer=self.optimal_trade_sizer,
                    rpc_getter=self.rpc_getter,
                    ata_cache=self.ata_cache,
                    keypair=self.keypair
                )
                success = await lst_arb.execute_unstake_arbitrage(
                    opportunity=opportunity,
                    tx_builder=lst_arb.tx_builder,
                    keypair=self.keypair,
                    jito_executor=self.jito_executor
                )
                result = {"status": "success" if success else "error"}

                # Reputation Circuit Breaker: track slippage failures per pair
                pair_key = self._pair_key("LST", opportunity.get("lst_mint", ""))
                if result.get("status") == "error":
                    self.record_pair_slippage(pair_key)
                elif result.get("status") == "success":
                    self.reset_pair_reputation(pair_key)

                return result
            else:
                logger.warning(f"Unknown strategy: {strategy}")
                return {"status": "error", "message": f"Unknown strategy: {strategy}"}
        except Exception as e:
            logger.error(f"Error executing arbitrage opportunity: {e}")
            self.consecutive_failures += 1
            return {"status": "error", "message": str(e)}

    async def _refetch_xstock_quotes(
        self,
        quote: Dict[str, Any],
        amount_lamports: int,
        only_direct_routes: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Refetch xStock circular quotes with strict Jupiter route guards."""
        try:
            from .jupiter_api_client import JupiterClient

            step1 = quote.get("step1") or {}
            step2 = quote.get("step2") or {}
            if not step1 or not step2:
                return None

            input_mint = step1.get("inputMint")
            output_mint = step1.get("outputMint")
            if not input_mint or not output_mint:
                return None

            client = JupiterClient(self.session, timeout=4.0, max_retries=1)
            buy_quote = await client.get_quote(
                input_mint=input_mint,
                output_mint=output_mint,
                amount=int(amount_lamports),
                slippage_bps=max(30, int(step1.get("slippageBps", 100))),
                only_direct_routes=only_direct_routes,
            )
            if not buy_quote or "error" in buy_quote or int(buy_quote.get("outAmount", 0)) <= 0:
                return None

            sell_quote = await client.get_quote(
                input_mint=output_mint,
                output_mint=input_mint,
                amount=int(amount_lamports), # Repay exact borrow
                slippage_bps=max(30, int(step2.get("slippageBps", 100))),
                only_direct_routes=only_direct_routes,
                swap_mode="ExactOut", # Task 16
            )
            if not sell_quote or "error" in sell_quote or int(sell_quote.get("outAmount", 0)) <= 0:
                return None

            return {
                "step1": buy_quote,
                "step2": sell_quote,
                "buy_venues": quote.get("buy_venues", []),
                "sell_venues": quote.get("sell_venues", []),
                "is_cross_venue": quote.get("is_cross_venue", False),
                "circular_quote_out": int(sell_quote.get("outAmount", 0)),
                "risk_out": int(amount_lamports),
            }
        except Exception as e:
            logger.debug(f"xStock quote retry failed: {e}")
            return None

    async def _simulate_xstock_transaction(
        self,
        transaction,
        expected_profit_sol: float,
        min_profit_lamports: int,
        tip_lamports: int,
        bank_vault_pubkey: Optional[str] = None,
    ) -> Tuple[bool, str, Any]:
        """Run the local pre-flight simulation for an xStock transaction."""
        from .flash_simulator import FlashSimulator

        flash_sim = FlashSimulator(self.session, self.rpc_url)
        tx_b64 = base64.b64encode(bytes(transaction)).decode("ascii")
        return await flash_sim.validate_profitability(
            tx_b64=tx_b64,
            tx_signer_pubkey=str(self.keypair.pubkey()),
            min_profit_lamports=min_profit_lamports,
            tip_lamports=tip_lamports,
            priority_fee_lamports=0,
            expected_profit_sol=None,
            bank_vault_pubkey=bank_vault_pubkey,
        )

    async def _retry_xstock_opportunity(
        self,
        opportunity: Dict[str, Any],
        reason: str,
        current_amount: int,
        current_profit_sol: float,
    ) -> dict:
        """Apply Smart Retry rules before giving up on an xStock opportunity."""
        retry_state = opportunity.get("_smart_retry", {})
        if retry_state.get("used"):
            return {"status": "error", "message": reason}

        retry_opportunity = dict(opportunity)
        retry_opportunity["_smart_retry"] = {"used": True, "mode": "slippage" if ("slippage" in reason.lower() or "liquidity" in reason.lower() or "depth" in reason.lower()) else "route"}

        if "slippage" in reason.lower() or "liquidity" in reason.lower() or "depth" in reason.lower():
            new_amount = max(int(current_amount * 0.5), 1)
            retry_opportunity["optimal_size_lamports"] = new_amount
            retry_opportunity["expected_profit_sol"] = max(current_profit_sol * 0.5, 0.0)
            quote = await self._refetch_xstock_quotes(
                opportunity.get("quote", {}),
                new_amount,
                only_direct_routes=True,
            )
            if not quote:
                return {"status": "error", "message": f"Slippage retry quote rebuild failed: {reason}"}
            retry_opportunity["quote"] = quote
            logger.warning(f"Smart Retry: slippage cut xStock borrow to {new_amount} lamports")
            return await self._execute_xstock_opportunity(retry_opportunity)

        if "accountnotfound" in reason.lower() or "rent" in reason.lower() or "insufficient" in reason.lower() or "mtu" in reason.lower() or "size" in reason.lower():
            quote = await self._refetch_xstock_quotes(
                opportunity.get("quote", {}),
                current_amount,
                only_direct_routes=True,
            )
            if not quote:
                return {"status": "error", "message": f"Route retry quote rebuild failed: {reason}"}
            retry_opportunity["quote"] = quote
            logger.warning("Smart Retry: rebuilt xStock route with onlyDirectRoutes=true and restrictIntermediateTokens=true due to size/rent error")
            return await self._execute_xstock_opportunity(retry_opportunity)

        return {"status": "error", "message": reason}

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

            # Phase 48: Dynamic Bank Lookup (lazy import to avoid circular dependency)
            from arb_bot import MARGINFI_BANKS

            # ── Task 11: Check out a MarginFi account from the pool BEFORE
            # building the flashloan tx. This ensures the pooled account is
            # actually used in the instruction building, not just at send time.
            _pool_acct_for_build = None
            try:
                # Fetch current slot for pool checkout
                _slot_payload = {
                    "jsonrpc": "2.0", "id": 1,
                    "method": "getSlot", "params": []
                }
                async with self.session.post(
                    self.rpc_url, json=_slot_payload, timeout=2.0
                ) as _slot_resp:
                    if _slot_resp.status == 200:
                        _slot_data = await _slot_resp.json()
                        _current_slot = _slot_data["result"]
                        _pool_acct_for_build, _ = await self.marginfi_pool.checkout(_current_slot)
            except Exception as _pool_err:
                logger.debug(f"Task 11: Pool checkout before build failed ({_pool_err}) — using default account")

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
                    step1_ixs, _ = await tx_builder.get_swap_instructions(
                        step1_data, str(self.keypair.pubkey()), use_custom_cu=True,
                        expected_profit_sol=expected_profit_sol
                    )
                    if step1_ixs:
                        all_swap_ixs.extend(step1_ixs)

                step2_data = circular_quote.get("step2", {})
                if step2_data:
                    step2_ixs, _ = await tx_builder.get_swap_instructions(
                        step2_data, str(self.keypair.pubkey()), use_custom_cu=True,
                        expected_profit_sol=expected_profit_sol
                    )
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

                # FIX 12: Net profit check using exact pivot cost (borrow_lamports - out_exit)
                # Not price_impact_pct estimation which was mathematically unsound.
                # Guard: expected_profit_sol must exceed actual pivot cost + minimum buffer

                # ── PHASE 49: SMART PIVOT ANALYTICS ──────────────────────────────
                # Dynamically adjust the profit buffer based on current capital.
                # Micro-balances (0.015 SOL) cannot afford the risk of pivot slippage.
                try:
                    current_capital = shared_state.stats.get("last_balance", 0.015)
                except (ImportError, AttributeError):
                    current_capital = 0.015

                if current_capital < 0.1:
                    min_profit_buffer_sol = 0.001  # Safe margin for micro-balance
                else:
                    min_profit_buffer_sol = 0.0001 # Aggressive margin for large capital

                cost_sol = swap_cost_lamports / 1e9
                profit_after_pivot = expected_profit_sol - cost_sol
                
                # ── Task 5: Flash Loan Pivot Hard Margin ROI Filter ───────────
                # roi = (expected_profit_sol * sol_price) / (trade_amount_usdc)
                # But here we use a simplified ROI based on borrow amount.
                # Since borrow is in SOL (if pivoted), roi = expected_profit_sol / borrow_sol
                roi_pct = (expected_profit_sol / (optimal_size_lamports / 1e9)) * 100 # Rough estimate
                
                if profit_after_pivot <= min_profit_buffer_sol or roi_pct < 1.5:
                    logger.warning(
                        f"⚠️ ANALYTICS: Pivot rejected. "
                        f"Net Profit: {profit_after_pivot:.6f} SOL, ROI: {roi_pct:.2f}% | "
                        f"Limits: Net > {min_profit_buffer_sol}, ROI > 1.5%"
                    )
                    return {"status": "error", "message": "Pivot mathematically unprofitable or low ROI"}
                # ─────────────────────────────────────────────────────────────────

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

            # ── Task 15: Jito Tip Floor Guard ──────────────────────────────────
            # If (Profit * 40%) < Tip Floor AND Profit < 0.0005 SOL, abort.
            # Prevents overpaying for micro-trades where margin is too thin.
            if self.jito_executor:
                p50_floor = self.jito_executor.get_current_tip_info().get("recommended_tip", 10000)
                if (expected_profit_sol * 0.40 * 1e9) < p50_floor and expected_profit_sol < 0.0005:
                    logger.warning(
                        f"🚫 ABORT: Jito Tip Floor {p50_floor/1e9:.6f} SOL > 40% profit {expected_profit_sol*0.4:.6f} SOL "
                        f"on micro-trade for {ticker}. Waiting for cheaper floor."
                    )
                    return {"status": "error", "message": "Jito Tip Floor too high for micro-profit"}

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

            # ── Task 11: Inject MarginFi account into bank config ────────────
            # build_native_flashloan_tx expects marginfi_account inside the config
            # dict, but MARGINFI_BANKS doesn't include it (it's stored separately).
            # We inject it here, using the pooled account if available.
            active_bank_info = dict(active_bank_info)  # Clone to avoid mutating the global
            _acct_to_use = _pool_acct_for_build if _pool_acct_for_build else None
            if _acct_to_use is None:
                # Fallback: read from env like the rest of the bot does
                _acct_to_use = os.getenv("MARGINFI_ACCOUNT", "Fk4G5NB5e1NyULQCCpTNLWCmChCW2UbDwpkEofqAiHk2")
            active_bank_info["marginfi_account"] = Pubkey.from_string(_acct_to_use)
            logger.debug(
                f"🏦 Task 11: marginfi_account set to {_acct_to_use[:8]}... "
                f"(pooled={_pool_acct_for_build is not None})"
            )
            # ───────────────────────────────────────────────────────────────────

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

            # Get blockhash (HFT optimization: use cached blockhash to save 300ms latency)
            recent_blockhash = None
            if hasattr(self, 'blockhash_mgr') and self.blockhash_mgr:
                # ИСПРАВЛЕНИЕ: Защита вебхук-бандлов от slot drift отклонений Jito
                await self.blockhash_mgr.check_and_recover_drift()
                bh_obj = await self.blockhash_mgr.get_fresh_blockhash()
                if bh_obj:
                    recent_blockhash = str(bh_obj)

            if not recent_blockhash and self.blockhash_getter:
                recent_blockhash = self.blockhash_getter()
            if not recent_blockhash:
                logger.debug("Latency leak: blockhash not cached, fetching via RPC")
                blockhash_payload = {"jsonrpc": "2.0", "id": 1, "method": "getLatestBlockhash"}
                async with self.session.post(self.rpc_url, json=blockhash_payload) as resp:
                    bh_data = await resp.json()
                    recent_blockhash = bh_data["result"]["value"]["blockhash"]

            # Fix 3: MTU-Safe ALT resolution — pull resolved accounts from alt_manager cache
            from solders.address_lookup_table_account import AddressLookupTableAccount
            resolved_alts: List[AddressLookupTableAccount] = []
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
                    resolved_alts.append(AddressLookupTableAccount(key=Pubkey.from_string(alt_pk_str), addresses=_resolved))

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
                _ptg = PreTradeGuard(session=self.session, rpc_url=self.rpc_url)
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
            is_profitable, reason, sim_result = await self._simulate_xstock_transaction(
                transaction,
                expected_profit_sol=expected_profit_sol,
                min_profit_lamports=int(expected_profit_sol * 1e9),
                tip_lamports=jito_tip_lamports,
                bank_vault_pubkey=vault,
            )
            if not is_profitable:
                # Task 18: Smart Pivot Trigger
                if self.flash_pivot_engine and any(kw in reason for kw in ["BorrowingNotAllowed", "BankCapacityExceeded", "BankUtilizationLimit"]):
                    logger.warning(f"🚀 MarginFi capacity limit hit for {ticker}. Triggering FlashPivotEngine...")
                    # Pivot to USDC if SOL bank is full (Task 18c)
                    pivot_asset = "USDC" if borrow_mint_str == str(SOL_MINT) else "SOL"
                    logger.info(f"🔄 Attempting Flash Loan Pivot to {pivot_asset}...")
                    # We continue to retry, but next time usdc_available check will fail
                    # which triggers the internal pivot logic in this method.

                return await self._retry_xstock_opportunity(
                    opportunity,
                    reason,
                    int(optimal_size_lamports),
                    float(expected_profit_sol),
                )

            # ── Task 22: Webhook-Driven Paper Trading Interceptor ───────────────
            if self.cfg and getattr(self.cfg, 'PAPER_TRADING_ONLY', False):
                logger.info(f"🧪 [PAPER MODE] Simulation passed! Estimated Profit: {expected_profit_sol:.6f} SOL. Skipping real Jito submission.")
                
                if self.data_aggregator:
                    paper_trade_record = {
                        "trade_id": f"paper_{int(time.time())}",
                        "route": opportunity.get("pair", f"{ticker} Oracle Lag"),
                        "token_in": str(borrow_mint_str),
                        "token_out": str(token_mint),
                        "amount": float(optimal_size_lamports) / 1e9,
                        "actual_profit": float(expected_profit_sol),
                        "balance_after": shared_state.stats.get("virtual_balance", 0.0) + float(expected_profit_sol),
                        "dex_pair": opportunity.get("pair"),
                        "confidence": float(opportunity.get("score", 1.0))
                    }
                    await self.data_aggregator.log_paper_trade(paper_trade_record)
                
                if shared_state.stats_lock:
                    async with shared_state.stats_lock:
                        shared_state.stats["virtual_balance"] += float(expected_profit_sol)
                        shared_state.stats["trades"] += 1
                    
                return {"status": "success", "message": "Paper trade simulated and logged"}

            jito_result = await self.jito_executor.send_bundle([transaction])

            if jito_result.get("success"):
                # Fix 1 (wSOL Death Spiral): build_native_flashloan_tx closed wSOL + recreated ATA
                # inside the arb transaction.  Mark the atomic close so wallet_balance_listener
                # skips its own standalone CloseAccount×for the same ATA (saves one RPC tx / gas).
                try:
                    shared_state.mark_wsol_atomically_closed()
                except Exception:
                    pass  # non-fatal — listener has its own cooldown guard
                
                # General dust sweep for any other stranded accounts
                try:
                    from src.ingest.dust_sweeper import DustSweeper
                    dust_sweeper = DustSweeper(self.keypair, self.rpc_url, self.session)
                    logger.info("🧹 Triggering aggressive post-trade Dust Sweep to reclaim rent...")
                    asyncio.create_task(dust_sweeper.sweep_after_successful_tx())
                except Exception:
                    pass  # non-fatal
                    
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
        # FIX 12: actual pivot cost calculated as borrow_lamports - out_exit (exact math)
        # No more price_impact_pct estimation which was mathematically unsound.
        actual_pivot_cost = 0
        out_exit = 0

        # ── Entry: SOL → USDC ──────────────────────────────────────────────
        entry_quote_url = (
            f"{JUPITER_QUOTE_URL}?inputMint={sol_pk}&outputMint={usdc_pk}"
            f"&amount={int(entry_amount)}&slippageBps=10&maxAccounts=8"
            f"&onlyDirectRoutes=true&restrictIntermediateTokens=true"
        )
        try:
            # FIX 13: Acquire global Jupiter rate limiter before each request
            limiter = get_jupiter_limiter()
            if limiter is not None:
                async with limiter:
                    async with self.session.get(entry_quote_url, timeout=4.0) as resp:
                        if resp.status != 200:
                            if resp.status == 429:
                                logger.warning("Jupiter 429 on pivot entry — backoff 2.0s")
                                await asyncio.sleep(2.0)
                            logger.warning(f"Pivot entry quote failed: HTTP {resp.status}")
                            return None, [], []
                        entry_quote = await resp.json()
                        out_amount = int(entry_quote.get("outAmount", 0))
                        if out_amount == 0:
                            logger.warning("Pivot entry quote: outAmount == 0")
                            return None, [], []
            else:
                async with self.session.get(entry_quote_url, timeout=4.0) as resp:
                    if resp.status != 200:
                        if resp.status == 429:
                            logger.warning("Jupiter 429 on pivot entry — backoff 2.0s")
                            await asyncio.sleep(2.0)
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

        # Parse entry instructions (Task 19: filter None from ComputeBudget drops)
        if "swapInstruction" in entry_ix_data and entry_ix_data["swapInstruction"]:
            _parsed = self._parse_jupiter_ix(entry_ix_data["swapInstruction"])
            if _parsed:
                entry_ixs.append(_parsed)
        for setup_ix in (entry_ix_data.get("setupInstructions") or []):
            _parsed = self._parse_jupiter_ix(setup_ix)
            if _parsed:
                entry_ixs.append(_parsed)

        # FIX 12: Removed price_impact_pct estimation — mathematically unsound.
        # Actual pivot cost is calculated from the exit leg's outAmount below.

        # ── Exit: USDC → SOL ───────────────────────────────────────────────
        # Task 16: ensure int (outAmount may be Decimal/float in some paths)
        exit_amount_ui = int(out_amount)
        exit_quote_url = (
            f"{JUPITER_QUOTE_URL}?inputMint={usdc_pk}&outputMint={sol_pk}"
            f"&amount={exit_amount_ui}&slippageBps=10&maxAccounts=8"
            f"&onlyDirectRoutes=true&restrictIntermediateTokens=true"
        )
        try:
            # FIX 13: Acquire global Jupiter rate limiter before each request
            limiter = get_jupiter_limiter()
            if limiter is not None:
                async with limiter:
                    async with self.session.get(exit_quote_url, timeout=4.0) as resp:
                        if resp.status != 200:
                            if resp.status == 429:
                                logger.warning("Jupiter 429 on pivot exit — backoff 2.0s")
                                await asyncio.sleep(2.0)
                            logger.warning(f"Pivot exit quote failed: HTTP {resp.status}")
                            # fall through with entry only
                        else:
                            exit_quote = await resp.json()
                            out_exit = int(exit_quote.get("outAmount", 0))
            else:
                async with self.session.get(exit_quote_url, timeout=4.0) as resp:
                    if resp.status != 200:
                        if resp.status == 429:
                            logger.warning("Jupiter 429 on pivot exit — backoff 2.0s")
                            await asyncio.sleep(2.0)
                        logger.warning(f"Pivot exit quote failed: HTTP {resp.status}")
                        # fall through with entry only
                    else:
                        exit_quote = await resp.json()
                        out_exit = int(exit_quote.get("outAmount", 0))
                    # FIX 12: Calculate exact pivot cost from real outAmount
                    # actual cost = borrow_lamports - out_exit (SOL lost in pivot swap)
                    if out_exit > 0:
                        actual_pivot_cost = borrow_lamports - out_exit
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
                                        _parsed = self._parse_jupiter_ix(exit_ix_data["swapInstruction"])
                                        if _parsed:
                                            exit_ixs.append(_parsed)
                                    for setup_ix in (exit_ix_data.get("setupInstructions") or []):
                                        _parsed = self._parse_jupiter_ix(setup_ix)
                                        if _parsed:
                                            exit_ixs.append(_parsed)
        except Exception as e:
            logger.debug(f"Pivot exit swap setup error (non-fatal): {e}")

        if not entry_ixs:
            logger.warning("Pivot: no entry swap instructions fetched")
            return None, [], []

        logger.info(
            f"🔄 Flash Pivot swap instructions: entry={len(entry_ixs)} ixs, "
            f"exit={len(exit_ixs)} ixs, actual_cost={actual_pivot_cost/1e9:.6f} SOL"
        )
        return actual_pivot_cost, entry_ixs, exit_ixs

    def _parse_jupiter_ix(self, ix_data: dict) -> Optional[Instruction]:
        """Parse a raw Jupiter instruction dict into a solders Instruction.
        Task 19: Returns None for ComputeBudget instructions to prevent
        SVM duplicate ComputeBudget panic when combining with our custom CU limits.
        """
        # Task 19: Drop ComputeBudget instructions from Jupiter responses
        if str(ix_data.get("programId", "")) == "ComputeBudget111111111111111111111111111111":
            logger.debug("✂️ Dropped ComputeBudget instruction from Jupiter pivot response")
            return None

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
                        # If native SOL balance < 0.002 SOL, Solana GC will delete the
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
                            
                            # ── Task 3: Event-Driven Gas Refill ───────────────────
                            # Hook into arb_bot's check_and_refill_gas for immediate replenishment
                            try:
                                from .gas_manager import check_and_refill_gas
                                asyncio.create_task(check_and_refill_gas(self.session, shared_state.rpc, self.keypair))
                            except Exception as refill_err:
                                logger.debug(f"Event-driven refill trigger failed: {refill_err}")
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
            # ── ИСПРАВЛЕНИЕ: Мгновенное чтение слота из ОЗУ вместо HTTP-запроса ──
            import src.ingest.shared_state as shared_state
            current_slot = shared_state.stats.get("current_slot", 0)
            if current_slot == 0:
                # Фолбек на RPC, если в кэше пусто (первая секунда запуска)
                async with session.post(rpc_url, json=payload) as resp:
                    if resp.status != 200:
                        logger.error(f"Failed to get current slot. HTTP {resp.status}")
                        return {"success": False, "error": "RPC Error"}
                    data = await resp.json()
                    if "result" not in data:
                        logger.error(f"Failed to parse slot, invalid RPC response: {data}")
                        return {"success": False, "error": "RPC Format Error"}
                    current_slot = data["result"]

            # ── Task 11: MarginFi Account Pooling ───────────────────────────
            # Instead of blocking for 450ms when current_slot == last_slot_executed,
            # we use a round-robin pool of MarginFi accounts. Each account can be
            # used once per slot — with N accounts, we can handle N concurrent trades.
            pool_account, pool_idx = await self.marginfi_pool.checkout(current_slot)
            logger.debug(
                f"🏦 Pool provided account {pool_account[:8]}... "
                f"(idx={pool_idx}/{self.marginfi_pool.count}, slot={current_slot})"
            )
            
            self.last_slot_executed = current_slot  # Mark slot as used
            
            # ── JITO FIX: Remove stale hardcoded leader check ──────────
            # The hardcoded JITO_VALIDATOR_VOTES list in leader_tracker.py is always
            # stale (~100% outdated). Jito Block Engine auto-inserts bundles into the
            # next Jito slot within 5 slots — no local leader check needed.
            # See: https://jito-labs.gitbook.io/mev/searcher-resources/bundles
            logger.info(f"🎯 Sending bundle to Jito Block Engine unconditionally (slot={current_slot})...")
            bundle_result = await self.jito_executor.send_bundle([transaction])
            if bundle_result.get("success") and bundle_result.get("bundle_id"):
                self._pending_bundle_slots[bundle_result["bundle_id"]] = {
                    "sent_slot": current_slot,
                    "sent_at": time.time(),
                    "tip_lamports": jito_tip_lamports,
                    "deducted_amount": jito_tip_lamports / 1_000_000_000,
                }
                # ── Phase 49: Optimistic State ───────────────────────────────────
                tip_deducted = jito_tip_lamports / 1e9
                async with shared_state.stats_lock:
                    prev = shared_state.stats.get("virtual_balance", 0.0)
                    shared_state.stats["virtual_balance"] = max(0.0, prev - tip_deducted)
                    shared_state.stats["last_balance"] = shared_state.stats["virtual_balance"]
                self.is_account_busy = False   # MarginFi account is instantly free
                logger.debug(
                    f"⚡ Optimistic balance: virtual_balance {prev:.6f} → "
                    f"{shared_state.stats['virtual_balance']:.6f} SOL (tip {tip_deducted:.6f})"
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
                            refund_amount = meta.get("deducted_amount", 0)
                            async with shared_state.stats_lock:
                                shared_state.stats["virtual_balance"] += refund_amount
                        except (ImportError, AttributeError, KeyError) as e:
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

    def pop_and_clear_stale_bundle_id(self) -> Optional[str]:
        """Return and consume one stale bundle id so the caller can log it."""
        if self._stale_bundle_ids:
            return self._stale_bundle_ids.pop()
        return None

    @property
    def has_stale_bundle(self) -> bool:
        return bool(self._stale_bundle_ids)