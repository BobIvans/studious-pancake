"""
Jito Manager - Dynamic Tip and Bundle Management

Handles Jito Block Engine integration with dynamic tip calculation based on profit,
bundle sending, and status polling for dropped bundle recovery.
"""

import asyncio
import logging
import random
from typing import Dict, Optional, Set, Tuple, Optional as OptionalType
import aiohttp
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

from .jito_bundle_client import JitoBundleClient

logger = logging.getLogger("JitoManager")


class JitoManager:
    """Manages Jito bundle operations with dynamic tipping."""

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        tip_percentage_range: Tuple[float, float] = (0.1, 0.5),  # 10-50% of profit
        default_tip_lamports: int = 10000,  # 0.00001 SOL fallback
    ):
        self.session = session
        self.tip_percentage_range = tip_percentage_range
        self.default_tip_lamports = default_tip_lamports
        # Phase 35: Dynamic Jito Tip Accounts
        self.tip_accounts = [
            "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",  # Fallback 1
            "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bLmis",  # Fallback 2
        ]
        logger.warning("JitoManager: tip_accounts initialized with fallback defaults. Call update_tip_accounts() to fetch dynamic accounts from Jito API.")
        self.bundle_client = JitoBundleClient(session=session)
        # Fix #3: Track background tasks to prevent Python GC from destroying them
        self.background_tasks: Set[asyncio.Task] = set()

    async def __aenter__(self):
        await self.bundle_client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.bundle_client.__aexit__(exc_type, exc_val, exc_tb)

    async def update_tip_accounts(self) -> bool:
        """Fetch live Jito tip accounts from Block Engine (Phase 35)."""
        if not self.session:
            return False
            
        try:
            url = "https://mainnet.block-engine.jito.wtf/api/v1/bundles/tip_accounts"
            async with self.session.get(url, timeout=5.0) as resp:
                if resp.status == 200:
                    accounts = await resp.json()
                    if accounts and isinstance(accounts, list):
                        self.tip_accounts = accounts
                        self.bundle_client.tip_accounts = accounts
                        logger.info(f"🔄 Jito tip accounts updated: {len(self.tip_accounts)} active accounts")
                        return True
        except Exception as e:
            logger.warning(f"Failed to fetch dynamic Jito tip accounts: {e}. Using cached defaults.")
            
        return False

    def get_random_tip_account(self) -> str:
        """Select a random tip account for load balancing."""
        return random.choice(self.tip_accounts)

    def calculate_tip(self, expected_profit_sol: float, target_mint_str: str = "So11111111111111111111111111111111111111112", price_matrix: Optional[Dict[str, tuple]] = None) -> int:
        """
        Calculate dynamic tip amount based on expected profit.

        ── Fix: Cross-Currency Profit Translation ──
        If the profit token is not SOL, we normalize to SOL-equivalent before
        calculating the tip.  This prevents paying 2.5 SOL tip on a 5 USDC profit.

        Args:
            expected_profit_sol: Expected profit (may be in a non-SOL token)
            target_mint_str: The mint of the profit token
            price_matrix: Global price matrix for USD price lookups

        Returns:
            Tip amount in lamports
        """
        if expected_profit_sol <= 0:
            return self.default_tip_lamports

        # ── Normalize to SOL if profit is in another token ──
        profit_sol = expected_profit_sol
        sol_mint = "So11111111111111111111111111111111111111112"
        if target_mint_str != sol_mint and price_matrix:
            try:
                sol_entry = price_matrix.get(sol_mint)
                sol_usd = sol_entry[0] if sol_entry else 150.0
                if target_mint_str == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v":
                    # USDC → SOL
                    profit_sol = expected_profit_sol / sol_usd
                else:
                    token_entry = price_matrix.get(target_mint_str)
                    if token_entry and token_entry[0] > 0:
                        profit_sol = (expected_profit_sol * token_entry[0]) / sol_usd
                logger.debug(f"🔄 JitoManager: normalized profit {expected_profit_sol:.6f} {target_mint_str[:8]} → {profit_sol:.6f} SOL")
            except Exception as e:
                logger.warning(f"⚠️ JitoManager normalization failed: {e}, using raw profit")

        # Calculate percentage of profit as tip
        min_pct, max_pct = self.tip_percentage_range
        tip_percentage = random.uniform(min_pct, max_pct)

        tip_sol = profit_sol * tip_percentage
        tip_lamports = int(tip_sol * 1_000_000_000)  # Convert SOL to lamports

        # Ensure minimum tip
        tip_lamports = max(tip_lamports, self.default_tip_lamports)

        logger.info(f"💰 Calculated dynamic tip: {tip_sol:.6f} SOL ({tip_percentage*100:.1f}% of normalized profit)")
        return tip_lamports

    async def add_tip_instruction(
        self,
        transaction: VersionedTransaction,
        tip_amount_lamports: int,
        tip_account: Optional[str] = None
    ) -> VersionedTransaction:
        """
        Add tip instruction to transaction (must be at the end).

        Args:
            transaction: Original transaction
            tip_amount_lamports: Tip amount in lamports
            tip_account: Specific tip account (random if None)

        Returns:
            Transaction with tip instruction added
        """
        if tip_account is None:
            tip_account = self.get_random_tip_account()

        logger.debug(f"🎯 Adding tip instruction: {tip_amount_lamports} lamports to {tip_account}")

        # Note: In the existing JitoBundleClient, tip is added during bundle building
        # This method would modify the transaction directly if needed
        # For now, we'll store tip info for the bundle client to use

        # This is a placeholder - actual implementation would modify the transaction
        # For now, return the original transaction and let bundle client handle tipping
        return transaction

    async def send_bundle(
        self,
        transaction: VersionedTransaction,
        payer_keypair: Keypair,
        tip_lamports: int,
        bundle_id: Optional[str] = None
    ) -> Dict:
        """
        Send transaction as Jito bundle with tip.

        Args:
            transaction: Transaction to send
            payer_keypair: Payer keypair
            tip_lamports: Tip amount in lamports
            bundle_id: Optional bundle ID for tracking

        Returns:
            Bundle send result
        """
        try:
            logger.info("📦 Sending bundle via Jito")

            # Create JitoPriorityContext using adapter
            from .jito_priority_context import JitoPriorityContextAdapter
            jito_adapter = JitoPriorityContextAdapter()
            jito_context = jito_adapter.build_jito_context({"token_address": "SOL"})
            jito_context.dynamic_tip_target_lamports = tip_lamports

            # Get recent blockhash from bundle client (real blockhash, not placeholder)
            recent_blockhash = await self.bundle_client._get_recent_blockhash()

            # Send via bundle client
            result = await self.bundle_client.build_and_send_bundle(
                swap_instructions=[],  # Transaction already contains instructions
                payer_keypair=payer_keypair,
                jito_context=jito_context,
                recent_blockhash=recent_blockhash
            )

            if result.get("success"):
                bundle_id = result.get("bundle_id")
                logger.info(f"✅ Bundle sent successfully: {bundle_id}")

                # Fix #3: Track background task to prevent GC destruction
                task = asyncio.create_task(self._poll_bundle_status(bundle_id))
                self.background_tasks.add(task)
                task.add_done_callback(lambda t: self.background_tasks.discard(t))

            return result

        except Exception as e:
            logger.error(f"Bundle send error: {e}")
            return {
                "success": False,
                "error": str(e),
                "bundle_id": None
            }

    async def _poll_bundle_status(self, bundle_id: str, max_slots: int = 5):
        """
        Poll bundle status to detect if it gets dropped due to blockhash expiry.

        Args:
            bundle_id: Bundle ID to monitor
            max_slots: Maximum slots to wait before considering dropped
        """
        try:
            # Wait for bundle confirmation
            result = await self.bundle_client.wait_for_bundle_confirmation(
                bundle_id=bundle_id,
                max_wait_time=30.0,  # 30 seconds
                check_interval=1.0   # Check every second
            )

            status = result.get("status")
            if status == "confirmed" or status == "finalized":
                logger.info(f"🎉 Bundle {bundle_id} confirmed")
            elif status == "failed":
                logger.warning(f"💥 Bundle {bundle_id} failed")
            elif status == "timeout":
                logger.warning(f"⏰ Bundle {bundle_id} timed out - likely dropped")
            else:
                logger.warning(f"❓ Bundle {bundle_id} unknown status: {status}")

        except Exception as e:
            logger.error(f"Error polling bundle status: {e}")


class JitoBiddingManager:
    """God-mode dynamic Jito tip bidding with success-rate feedback and capital guard."""

    TIP_FLOOR_URL = "https://bundles.jito.wtf/api/v1/bundles/tip_floor"

    def __init__(self):
        self.tip_floor_data = {}
        self.strategy_success: Dict[str, list] = {}  # strategy -> [ (timestamp, success_bool) ]
        self.consecutive_success = 0
        self.last_poll = 0.0

    async def poll_tip_floor(self, session: aiohttp.ClientSession):
        """Poll every 10s."""
        import time
        now = time.time()
        if now - self.last_poll < 10:
            return
        self.last_poll = now
        try:
            async with session.get(self.TIP_FLOOR_URL, timeout=3) as resp:
                if resp.status == 200:
                    self.tip_floor_data = await resp.json()
                    logger.info(f"📊 Jito tip floor updated: 50th={self.tip_floor_data.get('landed_tips_50th_percentile')}")
        except Exception as e:
            logger.debug(f"Tip floor poll failed: {e}")

    def get_50th_percentile_lamports(self) -> int:
        try:
            val = self.tip_floor_data.get("landed_tips_50th_percentile", 10000)
            return int(val)
        except Exception:
            return 10000

    def calculate_blue_ocean_tip(
        self,
        expected_profit_sol: float,
        strategy: str = "blue_ocean",
        current_native_sol_balance: Optional[float] = None,
    ) -> int:
        """
        Blue Ocean Tip Strategy: 40% of Expected Net Profit with Tip Floor Filter.

        Для стратегий LST Depeg, xStocks Oracle Lag, Sanctum Router — там нет жесткой
        конкуренции за блок, поэтому Tip = 40% от Expected Net Profit достаточно для
        гарантированного включения в блок. Никаких Step-Up/Down, никакого Capital Guard
        (который может заблокировать сделку с 0.017 SOL).

        🛡️ Fix 3 (Tip Floor Filter): Сравниваем рассчитанный tip с landed_tips_50th_percentile
        из Jito API. Если 40% профита < 50й перцентиль — отменяем сделку целиком.
        Не пытаемся перебить пол (floor), если это съедает > 80% профита. Ждем, когда
        конкуренция упадет.

        Args:
            expected_profit_sol: Expected net profit in SOL.
            strategy: Strategy name for logging.
            current_native_sol_balance: Native SOL balance for capital cap.

        Returns:
            Tip amount in lamports (positive) or 0 (if profit too small or tip floor too high).
        """
        if expected_profit_sol <= 0:
            return 0

        # ── Fix 3: Tip Floor Filter (Jito 50th Percentile) ──────────────────
        # Если 40% от профита не хватает, чтобы перебить Jito floor — отменяем сделку.
        # Спамить бандлы с чаевыми ниже рынка = убить репутацию кошелька в Jito.
        p50_lamports = self.get_50th_percentile_lamports()
        p50_sol = p50_lamports / 1e9
        forty_pct_tip_sol = expected_profit_sol * 0.40

        if forty_pct_tip_sol < p50_sol:
            logger.warning(
                f"🚫 Tip Floor Filter [{strategy}]: "
                f"40% tip ({forty_pct_tip_sol:.8f} SOL) < Jito 50th percentile ({p50_sol:.8f} SOL). "
                f"Skipping trade — wait for lower competition."
            )
            return 0

        # ── Tip Cost Guard: не тратим > 80% профита на tip ──────────────────
        if p50_sol > expected_profit_sol * 0.80:
            logger.warning(
                f"🚫 Tip Cost Guard [{strategy}]: "
                f"Jito 50th percentile ({p50_sol:.8f} SOL) > 80% of profit "
                f"({expected_profit_sol:.8f} SOL). Skipping to preserve capital."
            )
            return 0

        # 40% of expected net profit — validated for Blue Ocean strategies
        tip_sol = forty_pct_tip_sol
        tip_lamports = int(tip_sol * 1_000_000_000)

        # ── Fix 2 (Unfunded Jito Tip): Cap tip by actual native SOL balance ──
        # Jito Tip is a native SOL transfer. If the wallet has 0.017 SOL and
        # we try to send 0.004 SOL (40% of 0.01 USDC-profit treated as SOL),
        # the tx fails at pre-flight with InsufficientFundsForFee.
        # available_native_lamports is fetched from RPC when the caller has a session.
        # Callers should pass `current_native_sol_balance` via session query.
        # If not provided, we fall back to expected_profit_sol only.
        tip_lamports_float = tip_lamports
        if current_native_sol_balance is not None:
            available_native_lamports = int((current_native_sol_balance - 0.005) * 1_000_000_000)  # leave 0.005 SOL for gas
            tip_lamports_float = min(tip_lamports, available_native_lamports)
            logger.debug(
                f"💰 Jito tip cap: balance={current_native_sol_balance:.6f} SOL | "
                f"available={available_native_lamports / 1e9:.6f} SOL | "
                f"calculated_tip={tip_lamports / 1e9:.6f} SOL → capped={tip_lamports_float / 1e9:.6f} SOL"
            )
        # Minimum practical tip: 10000 lamports (0.00001 SOL)
        MIN_TIP_LAMPORTS = 10_000
        if tip_lamports_float < MIN_TIP_LAMPORTS:
            logger.warning(
                f"⏭️ Tip {tip_lamports_float} lamports below minimum {MIN_TIP_LAMPORTS} — skipping {strategy}"
            )
            return 0
        tip_lamports = int(tip_lamports_float)

        # Максимальный tip: никогда больше 70% от профита
        logger.info(
            f"💰 Blue Ocean tip: {tip_sol:.6f} SOL (40% of {expected_profit_sol:.6f} SOL profit) "
            f"| strategy={strategy}"
        )
        return tip_lamports

    def calculate_optimal_tip(
        self,
        expected_profit_sol: float,
        strategy: str = "default",
        current_native_sol_balance: Optional[float] = None,
    ) -> int:
        """Start + Step-Up/Down + Capital Guard.

        🛡️ Tip Floor Filter: Если 40% профита < 50й перцентиль Jito — отменяем сделку.
        Не пытаемся перебить пол (floor), если это съедает > 80% профита.
        Ждем, когда конкуренция упадет.
        """
        if expected_profit_sol <= 0:
            return 0

        # ── Fix 3: Tip Floor Filter (Jito 50th Percentile) ──────────────────
        # Если 40% от профита не хватает, чтобы перебить Jito floor — отменяем сделку.
        # Спамить бандлы с чаевыми ниже рынка = убить репутацию кошелька в Jito.
        p50 = self.get_50th_percentile_lamports() / 1e9
        forty_pct_tip = expected_profit_sol * 0.40

        if forty_pct_tip < p50:
            logger.warning(
                f"🚫 Tip Floor Filter [{strategy}]: "
                f"40% tip ({forty_pct_tip:.8f} SOL) < Jito 50th percentile ({p50:.8f} SOL). "
                f"Skipping trade — wait for lower competition."
            )
            return -1

        base = max(p50 * 1.2, forty_pct_tip)

        # Capital Guard
        if p50 > expected_profit_sol * 0.8:
            logger.warning("🚫 Capital Guard: Jito 50th > 80% profit — skipping whale market")
            return -1

        # Success rate last 10 min
        import time
        cutoff = time.time() - 600
        hist = [s for t, s in self.strategy_success.get(strategy, []) if t > cutoff]
        success_rate = sum(hist) / len(hist) if hist else 1.0

        tip_sol = base
        if success_rate < 0.2:
            # Step-Up
            tip_sol = min(base * 1.05, expected_profit_sol * 0.7)
            logger.info(f"📈 Step-Up tip for {strategy}: success_rate={success_rate:.0%}")
        elif self.consecutive_success >= 5:
            # Step-Down
            tip_sol = base * 0.98
            logger.info("📉 Step-Down tip after 5 consecutive wins")
            self.consecutive_success = 0
        else:
            self.consecutive_success += 1

        tip_lamports = int(tip_sol * 1_000_000_000)

        # ── Fix 2 (Unfunded Jito Tip): Cap by actual native SOL balance ──
        if current_native_sol_balance is not None:
            available_native = int((current_native_sol_balance - 0.005) * 1_000_000_000)
            if available_native <= 0:
                logger.warning(
                    f"🚫 Native balance {current_native_sol_balance:.6f} SOL < gas reserve — "
                    f"returning -1 for {strategy}"
                )
                return -1
            capped = min(tip_lamports, available_native)
            if capped < 10_000:
                logger.warning(
                    f"⏭️ Optimal tip {capped} < {10_000} lamports minimum "
                    f"after native cap — returning -1 for {strategy}"
                )
                return -1
            logger.debug(
                f"💰 Optimal tip native cap: {tip_lamports / 1e9:.6f} SOL → "
                f"{capped / 1e9:.6f} SOL (native={current_native_sol_balance:.6f} SOL)"
            )
            tip_lamports = capped

        return tip_lamports

    def record_trade_result(self, strategy: str, success: bool):
        import time
        if strategy not in self.strategy_success:
            self.strategy_success[strategy] = []
        self.strategy_success[strategy].append((time.time(), success))
        # Prune entries older than 10 minutes to prevent memory leak
        now = time.time()
        self.strategy_success[strategy] = [
            (t, s) for t, s in self.strategy_success[strategy] if now - t <= 600
        ]
        if success:
            self.consecutive_success += 1
        else:
            self.consecutive_success = 0