"""Execution Router for Hybrid Jito/Standard Transaction Switching."""

import asyncio
import base58
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
from spl.token.constants import TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID
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

        Raises RuntimeError if no MarginFi account is configured (P0-15).
        """
        accounts_str = os.getenv("MARGINFI_ACCOUNTS", "")
        if accounts_str.strip():
            accounts = [a.strip() for a in accounts_str.split(",") if a.strip()]
            logger.info(f"🏦 MarginFi Account Pool: {len(accounts)} accounts (MARGINFI_ACCOUNTS)")
        else:
            single = os.getenv("MARGINFI_ACCOUNT")
            if single and single.strip():
                accounts = [single.strip()]
                logger.info(f"🏦 MarginFi Account Pool: 1 account (MARGINFI_ACCOUNT)")
            else:
                raise RuntimeError(
                    "MARGINFI_ACCOUNT env var is required. "
                    "Refusing to start with hardcoded fallback (P0-15)."
                )

        if not accounts:
            raise RuntimeError(
                "No MarginFi accounts configured. "
                "Set MARGINFI_ACCOUNTS or MARGINFI_ACCOUNT in .env (P0-15)."
            )

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
            idx = self._current_index
            acct = self.accounts[idx]
            self._current_index = (self._current_index + 1) % len(self.accounts)
            self._last_used_slot[acct] = current_slot
            logger.warning(
                f"🏦 All accounts busy in slot {current_slot}, "
                f"re-using {acct[:8]}... (risk: AccountInUse)"
            )
            return acct, idx

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

# FIX 13: Shared global Jupiter rate limiter — quotes use the quote limiter
from .jupiter_api_client import get_quote_limiter

logger = logging.getLogger(__name__)

RENT_SPL_ATA_SOL = 0.00204
RENT_TOKEN2022_SOL = 0.0035

# Flash Loan Pivot: Jupiter swap helper constants
SOL_MINT = Pubkey.from_string("So11111111111111111111111111111111111111112")
USDC_MINT = Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
JUPITER_QUOTE_URL = os.getenv("JUPITER_QUOTE_API", "https://api.jup.ag/swap/v1/quote")
JUPITER_SWAP_IX_URL = os.getenv("SWAP_INSTRUCTIONS_API_URL", "https://api.jup.ag/swap/v1/swap-instructions")

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
        cfg=None,
        data_aggregator=None,
        data_collector=None,
        stats=None,
        stats_lock=None,
        blockhash_mgr=None,
        jito_bidding_manager=None,
    ):
        self.leader_tracker = leader_tracker
        self.jito_executor = jito_executor
        self.standard_tx_sender = StandardTransactionSender(session, rpc_url)
        self.cfg = cfg
        self.data_aggregator = data_aggregator
        self.data_collector = data_collector
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
        # JitoBiddingManager for dynamic tip calculation in LST strategy
        self.jito_bidding_manager = jito_bidding_manager
        # Epoch Shield: Block trades during epoch boundary storm (direct RPC, no stubs)
        self._epoch_info: Dict[str, Any] = {}
        self._epoch_last_update = 0.0
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
        # (uses shared instance from shared_state.pair_reputation)

        # ── Phase 49: Optimistic State ─────────────────────────────────────────
        # When a bundle is sent via Jito we do NOT wait for on-chain confirmation
        # before considering the MarginFi account free for the next trade.
        self.is_account_busy: bool = False

        # Fix 51: Jito Bundle Self-Cancellation — track stale bundles for overwrite
        # map: bundle_id -> {"sent_slot": int, "sent_at": float, "endpoint": str, "tip_lamports": int, "deducted_amount": float}
        self._pending_bundle_slots: Dict[str, Dict[str, Any]] = {}
        self._stale_bundle_ids: Set[str] = set()
        self._self_cancel_task: Optional[asyncio.Task] = None
        self._pending_lock = asyncio.Lock()  # P0-17: thread safety for _pending_bundle_slots

    def start_processor(self):
        if self._processor_task is None:
            self._processor_task = asyncio.create_task(self._process_queue())
            shared_state.active_tasks.add(self._processor_task)
            self._processor_task.add_done_callback(shared_state.active_tasks.discard)
        if self._self_cancel_task is None:
            self._self_cancel_task = asyncio.create_task(self._self_cancel_stale_bundles())
            shared_state.active_tasks.add(self._self_cancel_task)
            self._self_cancel_task.add_done_callback(shared_state.active_tasks.discard)
        # Fix 38: epoch_tracker removed — epoch info fetched lazily via RPC in _check_epoch_killswitch

    async def _process_queue(self):
        """Process execution tasks concurrently.

        Spawns each task as a background asyncio task so the queue never blocks
        on slow operations (Jito bundle send, balance checks, etc.).
        This enables true concurrent processing of multiple arbitrage opportunities
        across the MarginFi account pool (PERF, HFT Concurrency).
        """
        async def _execute_task_wrapper(task_item):
            try:
                await self._execute_task(task_item)
            finally:
                self.execution_queue.task_done()

        while True:
            try:
                task = await self.execution_queue.get()
                # Spawn a background task so the queue never blocks
                bg_task = asyncio.create_task(_execute_task_wrapper(task))
                shared_state.active_tasks.add(bg_task)
                bg_task.add_done_callback(shared_state.active_tasks.discard)
            except Exception as e:
                logger.error(f"Queue processing error: {e}")
                await asyncio.sleep(0.1)

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
                    try:
                        from src.ingest.dust_sweeper import DustSweeper
                        sweeper = DustSweeper(self.keypair, self.rpc_url, self.session)
                        asyncio.create_task(sweeper.sweep_after_successful_tx())
                    except Exception as _sweep_err:
                        logger.debug(f"Post-tx wSOL sweep schedule failed: {_sweep_err}")
                elif result.get("status") == "timeout" or "Slippage" in str(result):
                    self.execution_guard.record_failure()
                return result
            except asyncio.TimeoutError:
                logger.warning("⏰ Bundle ghosting timeout - transaction stuck, releasing lock")
                self.execution_guard.record_failure()
                # Mark as timeout error but don't block the queue
                return {"status": "timeout", "message": "Bundle stuck - timeout after 5.0s"}

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
            info = self._epoch_info
            # Lazy-fetch epoch info via RPC if stale
            if not info or (time.time() - self._epoch_last_update) > 30.0:
                try:
                    payload = {"jsonrpc": "2.0", "id": 1, "method": "getEpochInfo", "params": []}
                    async with self.session.post(self.rpc_url, json=payload, timeout=3.0) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            self._epoch_info = data.get("result", {})
                            self._epoch_last_update = time.time()
                            info = self._epoch_info
                except Exception as exc:
                    logger.debug(f"Epoch info fetch failed: {exc}")
            if not info:
                return True   # no epoch data yet — default safe

            slots_in_epoch = info.get("slotsInEpoch", 432000)
            slot_index     = info.get("slotIndex", 0)

            # ── Case 1: epoch just started (<60 s = ~150 slots at 400 ms) ──
            if slot_index < SECONDS_FROM_EPOCH_START * 2.5:
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
        # ── БЛОК 8: Stale Quote Guard — проверка свежести котировок ────────────
        if not await self._validate_quote_freshness(opportunity):
            return {
                "status": "stale_quote",
                "message": "Quote is stale (>1.5s) — rejected by Stale Quote Guard",
            }

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
        if strategy == "lst_unstake":
            ticker = "LST"
            mint = opportunity.get("lst_mint", "")
        else:
            ticker = opportunity.get("ticker", "")
            mint = opportunity.get("token_mint", "")
        pair_key = self._pair_key(ticker, mint)
        if self.is_pair_banned(pair_key):
            logger.warning(f"🚫 Pair {pair_key} rejected by Reputation Circuit Breaker (cooldown active)")
            return {"status": "rejected", "message": f"Pair {pair_key} in slippage cooldown"}

        try:
            strategy = opportunity.get("strategy")

            if strategy == "lst_unstake":
                import src.ingest.shared_state as shared_state
                current_balance_sol = shared_state.stats.get("last_balance", shared_state.stats.get("virtual_balance", 0.015))
                from .flywheel_scaler import FlywheelScaler
                _scaler = FlywheelScaler(initial_balance=current_balance_sol)
                _tier = _scaler.get_tier(current_balance_sol)
                _dynamic_min_profit_lamports = int(_tier.min_profit_sol * 1_000_000_000)

                # LST Instant Unstake Arbitrage
                from .lst_unstake_arbitrage import LstInstantUnstakeArbitrage
                lst_arb = LstInstantUnstakeArbitrage(
                    session=self.session,
                    rpc_url=self.rpc_url,
                    cfg=self.cfg,
                    data_aggregator=self.data_aggregator,
                    data_collector=getattr(self, 'data_collector', None),
                    marginfi_account=os.getenv("MARGINFI_ACCOUNT"),
                    tx_builder=JupiterTxBuilder(session=self.session, rpc_getter=self.rpc_getter),
                    optimal_trade_sizer=self.optimal_trade_sizer,
                    rpc_getter=self.rpc_getter,
                    ata_cache=self.ata_cache,
                    keypair=self.keypair,
                    min_profit_lamports=_dynamic_min_profit_lamports,
                    jito_bidding_manager=self.jito_bidding_manager
                )
                success = await lst_arb.execute_unstake_arbitrage(
                    opportunity=opportunity,
                    tx_builder=lst_arb.tx_builder,
                    keypair=self.keypair,
                    jito_executor=self.jito_executor,
                    jito_bidding_manager=self.jito_bidding_manager
                )
                result = {"status": "success" if success else "error"}

                pair_key = self._pair_key("LST", opportunity.get("lst_mint", ""))
                if result.get("status") == "error":
                    self.record_pair_slippage(pair_key)
                elif result.get("status") == "success":
                    self.reset_pair_reputation(pair_key)
                    try:
                        from src.ingest.dust_sweeper import DustSweeper
                        sweeper = DustSweeper(self.keypair, self.rpc_url, self.session)
                        asyncio.create_task(sweeper.sweep_after_successful_tx())
                    except Exception as _sweep_err:
                        logger.debug(f"Post-LST sweep schedule failed: {_sweep_err}")

                return result
            elif strategy == "wrapper_peg":
                # BTC Wrapper Peg Arbitrage — USDC → cheap BTC → expensive BTC → USDC
                pair = opportunity.get("pair", "unknown")
                logger.info(f"🔄 Wrapper Peg: {pair}")

                try:
                    from .tx_builder import JupiterTxBuilder
                    from .pre_trade_guard import PreTradeGuard
                    from solders.transaction import VersionedTransaction
                    from solders.message import MessageV0
                    from solders.address_lookup_table_account import AddressLookupTableAccount

                    cheap_mint = opportunity.get("cheap_mint", "")
                    expensive_mint = opportunity.get("expensive_mint", "")
                    borrow_amount = opportunity.get("borrow_amount_lamports", 0)
                    expected_profit_sol = opportunity.get("expected_profit_sol", 0.0)
                    jito_tip_pct = opportunity.get("jito_tip_pct", 0.40)

                    # Build swap instructions from the quotes
                    leg1_quote = opportunity.get("leg1_quote")
                    leg2_quote = opportunity.get("leg2_quote")
                    leg3_quote = opportunity.get("leg3_quote")

                    if not all([leg1_quote, leg2_quote, leg3_quote]):
                        logger.warning(f"Wrapper Peg {pair}: missing quotes")
                        return {"status": "error", "message": "missing quotes"}

                    # Get swap instructions from Jupiter for each leg
                    tx_builder = JupiterTxBuilder(
                        session=self.session,
                        rpc_getter=self.rpc_getter,
                    )

                    all_swap_ixs = []
                    wallet_pk = str(self.keypair.pubkey())
                    for leg_quote in [leg1_quote, leg2_quote, leg3_quote]:
                        ixs, _ = await tx_builder.get_swap_instructions(
                            leg_quote, wallet_pk, use_custom_cu=True
                        )
                        all_swap_ixs.extend(ixs)

                    if not all_swap_ixs:
                        logger.warning(f"Wrapper Peg {pair}: no swap instructions")
                        return {"status": "error", "message": "no swap instructions"}

                    # Jito tip via Dynamic Blue Ocean Engine (replace stale hardcoded jito_tip_sol = expected_profit_sol * jito_tip_pct)
                    import src.ingest.shared_state as shared_state
                    current_native_sol = shared_state.stats.get("last_balance", shared_state.stats.get("virtual_balance", 0.015))

                    if self.jito_bidding_manager:
                        jito_tip_lamports = self.jito_bidding_manager.calculate_blue_ocean_tip(
                            expected_profit_sol=expected_profit_sol,
                            strategy="wrapper_peg",
                            current_native_sol_balance=current_native_sol,
                        )
                    else:
                        fallback_tip_sol = expected_profit_sol * jito_tip_pct
                        jito_tip_lamports = max(int(fallback_tip_sol * 1e9), 10000)

                    # Blue Ocean returns 0 (not -1) when tip floor too high or profit too small
                    if jito_tip_lamports <= 0:
                        logger.warning(f"🚫 Wrapper Peg {pair}: Rejected by Jito Tip Floor Guard (margin too low)")
                        return {"status": "skipped", "message": "Rejected by Tip Floor Guard"}

                    jito_tip_sol = jito_tip_lamports / 1e9

                    # Dynamic ATA rent: only charge for ATAs not already in cache (remove hardcoded 0.0035 * 2)
                    ata_rent_sol = 0.0
                    for _mint in [str(USDC_MINT), cheap_mint, expensive_mint]:
                        if _mint not in self.ata_cache:
                            ata_rent_sol += 0.00203928

                    # Transaction builder already applies a dynamic priority fee — do not double-count it here
                    priority_fee_sol = 0.0

                    # Profit check via PreTradeGuard with is_circular=True (P0-8: fixed kwargs)
                    pre_trade_guard = PreTradeGuard(
                        session=self.session, rpc_url=self.rpc_url
                    )
                    is_profitable, reason, net_profit = await pre_trade_guard.check_profit_before_execution(
                        input_mint=str(USDC_MINT),
                        output_mint=expensive_mint,
                        amount_lamports=borrow_amount,
                        jito_tip_lamports=jito_tip_lamports,
                        base_fee_lamports=int(priority_fee_sol * 1e9),
                        expected_profit_lamports=int(expected_profit_sol * 1e9),
                        ata_rent_lamports=int(ata_rent_sol * 1e9),
                        is_circular=True,
                    )
                    if not is_profitable:
                        logger.warning(f"Wrapper Peg {pair}: {reason} (net={net_profit/1e9:.6f} SOL)")
                        return {"status": "skipped", "message": reason}

                    # Build native flash loan tx
                    marginfi_config = {
                        "program_id": "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA",
                        "marginfi_group": "4qp6Fx6tnZkY5Wropq9wUYgtFxXKwE6viZxFHg3rdAG8",
                        "bank_pubkey": "2s37akK2eyBbp8DZgCm7RtsaEz8eWhVKGfHGA3cKMEW2",
                        "bank_liquidity_vault": "73zNEAXx8vWeCReEwZgPZteXhH3RTo8gC1vC51g8x7j2",
                    }

                    tx_data = await tx_builder.build_native_flashloan_tx(
                        wallet_pubkey=wallet_pk,
                        arbitrage_path=[str(USDC_MINT), cheap_mint, expensive_mint, str(USDC_MINT)],
                        borrow_amount_lamports=borrow_amount,
                        expected_min_profit_lamports=int(expected_profit_sol * 1e9),
                        dex_swap_instructions=all_swap_ixs,
                        marginfi_config=marginfi_config,
                        jito_tip_lamports=jito_tip_lamports,
                        wsol_manager=None,
                        pool_state_manager=None,
                        use_jito=True,
                        tip_accounts=self.jito_executor.tip_accounts if self.jito_executor else None,
                    )

                    if not tx_data:
                        logger.warning(f"Wrapper Peg {pair}: failed to build tx")
                        return {"status": "error", "message": "tx build failed"}

                    # Compile instructions into VersionedTransaction
                    instructions = tx_data.get("instructions", [])
                    if not instructions:
                        logger.warning(f"Wrapper Peg {pair}: no instructions in tx_data")
                        return {"status": "error", "message": "no instructions"}

                    # Build ALTs from tx_data
                    alts = []
                    for alt_key in tx_data.get("address_lookup_table_pubkeys", []):
                        alt_account = None
                        if self.alt_manager:
                            alt_account = await self.alt_manager.resolve_alt(
                                Pubkey.from_string(alt_key)
                            )
                        alts.append(AddressLookupTableAccount(
                            key=Pubkey.from_string(alt_key),
                            addresses=alt_account or [],
                        ))

                    # Get recent blockhash
                    blockhash = Hash.default()
                    if self.blockhash_mgr:
                        bh = await self.blockhash_mgr.get_fresh_blockhash()
                        if bh:
                            blockhash = bh

                    msg = MessageV0.try_compile(
                        payer=self.keypair.pubkey(),
                        instructions=instructions,
                        address_lookup_table_accounts=alts,
                        recent_blockhash=blockhash,
                    )
                    versioned_tx = VersionedTransaction(msg, [self.keypair])

                    # Execute via Jito
                    result = await self._route_transaction(
                        self.session, self.cfg, self.rpc_url,
                        versioned_tx, jito_tip_lamports
                    )

                    if result.get("success"):
                        try:
                            from src.ingest.dust_sweeper import DustSweeper
                            sweeper = DustSweeper(self.keypair, self.rpc_url, self.session)
                            asyncio.create_task(sweeper.sweep_after_successful_tx())
                        except Exception as _sweep_err:
                            logger.debug(f"Post-wrapper-peg sweep schedule failed: {_sweep_err}")
                        logger.info(f"✅ Wrapper Peg executed: {pair} | tip={jito_tip_sol:.6f} SOL")
                        return {"status": "success", "pair": pair, **result}
                    else:
                        logger.warning(f"❌ Wrapper Peg failed: {pair} | {result.get('error')}")
                        return result

                except Exception as e:
                    logger.error(f"Wrapper Peg execution error: {e}")
                    return {"status": "error", "message": str(e)}
            else:
                logger.warning(f"Unknown strategy: {strategy}")
                return {"status": "error", "message": f"Unknown strategy: {strategy}"}

        except Exception as e:
            logger.error(f"Error executing arbitrage opportunity: {e}")
            self.consecutive_failures += 1
            return {"status": "error", "message": str(e)}

    # ─── БЛОК 8: Stale Quote Guard ────────────────────────────────────────────

    async def _validate_quote_freshness(self, opportunity: Dict[str, Any]) -> bool:
        """Проверяет свежесть всех котировок в opportunity.
        Если любая котировка старше 1.5 секунд — возвращает False (abort).
        """
        quote_fields = ["leg1_quote", "leg2_quote", "leg3_quote", "buy_quote", "sell_quote"]
        for field in quote_fields:
            quote = opportunity.get(field)
            if quote and isinstance(quote, dict):
                fetched_at = quote.get("fetched_at") or quote.get("full_quote_response", {}).get("fetched_at")
                if fetched_at is None:
                    logger.warning(
                        f"🚫 БЛОК 8: Quote missing fetched_at for {field}. Rejecting stale/malformed quote."
                    )
                    return False
                if time.time() - fetched_at > 1.5:
                    logger.warning(
                        f"🚫 БЛОК 8: Quote stale (>1.5s) for {field}. Age: {time.time() - fetched_at:.2f}s. Aborting."
                    )
                    return False
        # Also check nested quote in opportunity metadata
        route = opportunity.get("route")
        if route:
            for leg_key in ("buy_quote", "sell_quote"):
                leg = getattr(route, leg_key, None) or route.get(leg_key)
                if leg:
                    qr = getattr(leg, "full_quote_response", None) or (leg.get("full_quote_response") if isinstance(leg, dict) else None)
                    if isinstance(qr, dict):
                        fetched_at = qr.get("fetched_at")
                        if fetched_at and time.time() - fetched_at > 1.5:
                            logger.warning(
                                f"🚫 БЛОК 8: Quote stale (>1.5s) for route.{leg_key}. Aborting."
                            )
                            return False
        return True

    # ─── Reputation Circuit Breaker (per-pair slippage cooldown) ────────────────

    def _pair_key(self, ticker: str, mint: str) -> str:
        """Build a stable human-readable pair key for reputation tracking."""
        return f"{ticker}/{mint[:12]}"

    def record_pair_slippage(self, pair_key: str) -> None:
        """Record a slippage failure for a specific pair via the shared reputation instance."""
        shared_state.pair_reputation.record_failure(pair_key, "slippage")

    def is_pair_banned(self, pair_key: str) -> bool:
        """Return True if the pair is currently in cooldown via the shared reputation instance."""
        return shared_state.pair_reputation.is_banned(pair_key)

    def reset_pair_reputation(self, pair_key: str) -> None:
        """Manually reset the failure counter for a pair via the shared reputation instance."""
        shared_state.pair_reputation.record_success(pair_key)
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
            f"&amount={int(entry_amount)}&slippageBps=10&maxAccounts=28"
            f"&onlyDirectRoutes=true&restrictIntermediateTokens=true"
        )
        try:
            # FIX 13: Acquire global Jupiter rate limiter before each request
            limiter = get_quote_limiter()
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
            "maxAccounts": "28",
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
            f"&amount={exit_amount_ui}&slippageBps=10&maxAccounts=28"
            f"&onlyDirectRoutes=true&restrictIntermediateTokens=true"
        )
        try:
            # FIX 13: Acquire global Jupiter rate limiter before each request
            limiter = get_quote_limiter()
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
                            "maxAccounts": "28",
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
            shared_state.stats["consecutive_failures"] = self.consecutive_failures
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
            shared_state.stats["consecutive_failures"] = self.consecutive_failures

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
        shared_state.stats["consecutive_failures"] = 0
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
                            PreTradeGuard.enforce_hard_floor(balance_sol, keypair=self.keypair, rpc_url=self.rpc_url, session=self.session)
                        except Exception:
                            pass
                        # ──────────────────────────────────────────────────────────────

                        # Warn if balance is critically low
                        if balance_sol < self.critical_balance_threshold:
                            logger.warning(f"⚠️ Low balance after execution: {balance_sol:.6f} SOL (below {self.critical_balance_threshold} SOL threshold)")
                            
                            # ── Task 3: Event-Driven Gas Refill ───────────────────
                            # Hook into arb_bot's check_and_refill_gas for immediate replenishment
                            try:
                                from .gas_refiller import check_and_refill_gas
                                asyncio.create_task(check_and_refill_gas(self.session, shared_state.rpc, self.keypair))
                            except Exception as refill_err:
                                logger.debug(f"Event-driven refill trigger failed: {refill_err}")
                        async with shared_state.stats_lock:
                            shared_state.stats["last_balance"] = balance_sol
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
            # Account is already embedded in the transaction instructions.
            
            # ── JITO FIX: Remove stale hardcoded leader check ──────────
            # The hardcoded JITO_VALIDATOR_VOTES list in leader_tracker.py is always
            # stale (~100% outdated). Jito Block Engine auto-inserts bundles into the
            # next Jito slot within 5 slots — no local leader check needed.
            # See: https://jito-labs.gitbook.io/mev/searcher-resources/bundles

            # P0-9: Pre-trade guard — check gas tank before sending
            try:
                import src.ingest.shared_state as _ss
                _bal = _ss.stats.get("last_balance", _ss.stats.get("virtual_balance", 0.0))
                from src.ingest.pre_trade_guard import PreTradeGuard
                gas_ok, _ = PreTradeGuard.check_gas_tank(_bal)
                if not gas_ok:
                    logger.warning("🚫 Pre-trade guard: gas tank empty — skipping bundle")
                    return {"success": False, "error": "Gas tank empty"}
            except Exception as _gas_err:
                logger.debug(f"Pre-trade gas check error (non-fatal): {_gas_err}")

            logger.info(f"🎯 Sending bundle to Jito Block Engine unconditionally (slot={current_slot})...")
            # P0-16: Pass tip_amount_lamports and deducted_amount to send_bundle
            bundle_result = await self.jito_executor.send_bundle(
                [transaction],
                tip_amount_lamports=jito_tip_lamports,
                deducted_amount=jito_tip_lamports / 1e9,
            )
            if bundle_result.get("success") and bundle_result.get("bundle_id"):
                async with self._pending_lock:  # P0-17: thread-safe write
                    self._pending_bundle_slots[bundle_result["bundle_id"]] = {
                        "sent_slot": current_slot,
                        "sent_at": time.time(),
                        "tip_lamports": jito_tip_lamports,
                        "deducted_amount": jito_tip_lamports / 1_000_000_000,
                    }
                    # ── Этап 1: Inflight Bundle Persistence ──────────────────────
                    if self.data_aggregator and hasattr(self.data_aggregator, 'log_inflight_bundle'):
                        try:
                            sigs = [base58.b58encode(bytes(sig)).decode('ascii') for sig in transaction.signatures]
                            tip_deducted = jito_tip_lamports / 1e9
                            # PERF-002: Fire-and-forget — never block the hot path on DB I/O
                            asyncio.create_task(
                                self.data_aggregator.log_inflight_bundle(
                                    bundle_id=bundle_result["bundle_id"],
                                    signatures=sigs,
                                    deducted_sol=tip_deducted,
                                    tip_lamports=jito_tip_lamports,
                                )
                            )
                        except Exception as _log_err:
                            logger.debug(f"Inflight bundle logging failed: {_log_err}")
                # Phase 18 T5: Populate latency metrics
                try:
                    import src.ingest.shared_state as _ss_18
                    _sent_meta = self._pending_bundle_slots.get(bundle_result.get("bundle_id", ""), {})
                    if isinstance(_sent_meta, dict) and _sent_meta.get("sent_at", 0) > 0:
                        _elapsed = time.time() - _sent_meta["sent_at"]
                        _ss_18.append_latency(_elapsed)
                except Exception:
                    pass

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
            self.consecutive_failures += 1
            shared_state.stats["consecutive_failures"] = self.consecutive_failures
            return {"success": False, "error": str(e)}

    # ───────────── Fix 51: Jito Bundle Self-Cancellation + Ghost Balance Refund ──────────────────────

    async def _self_cancel_stale_bundles(self):
        """Detect bundles dropped by Jito (>5 seconds old) and log them.
        Refund is handled exclusively by jito_executor.py to prevent double-counting (P0-17).
        """
        while True:
            try:
                async with self._pending_lock:  # P0-17: thread-safe iteration
                    if not self._pending_bundle_slots:
                        await asyncio.sleep(0.5)
                        continue

                    current_time = time.time()
                    for bid, meta in list(self._pending_bundle_slots.items()):
                        if current_time - meta.get("sent_at", current_time) > 5.0:
                            logger.warning(
                                f"⚡ Bundle {bid[:8]} dropped by Jito. "
                                f"Refund handled by jito_executor (P0-17)."
                            )
                            self._stale_bundle_ids.add(bid)

                    # Cleanup stale bundle IDs
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

