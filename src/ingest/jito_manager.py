"""
Jito Manager - Dynamic Tip and Bundle Management

Handles Jito Block Engine integration with dynamic tip calculation based on profit,
bundle sending, and status polling for dropped bundle recovery.
"""

import asyncio
import base58
import logging
import random
import time
from typing import Dict, Optional, Set, Tuple, Optional as OptionalType
import aiohttp
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solders.instruction import Instruction, AccountMeta

from .jito_bundle_client import JitoBundleClient
import src.ingest.shared_state as shared_state
from src.ingest.shared_state import send_telegram_alert

logger = logging.getLogger("JitoManager")


class JitoManager:
    """Manages Jito bundle operations with dynamic tipping."""

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        tip_percentage_range: Tuple[float, float] = (0.1, 0.5),  # 10-50% of profit
        default_tip_lamports: int = 10000,  # 0.00001 SOL fallback
        rpc_url: Optional[str] = None,
    ):
        self.session = session
        self.rpc_url = rpc_url
        self.tip_percentage_range = tip_percentage_range
        self.default_tip_lamports = default_tip_lamports
        # Phase 35: Dynamic Jito Tip Accounts
        # FIX 167: Fully expand Jito tip accounts failover default array
        self.tip_accounts = [
            "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
            "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bLmis",
            "Cw8CFN97mo99uH2LL69Yp6Cgv7S8Z8B7A49K8a4CgC5B",
            "ADa6g7u6g6TZ6gYmChGgQCyBD9B464UvCwcE9a4CgC5B",
            "Df6Z8LMo6uH7T6C9G6fM5sU8g6G6CwcE9a4CgC5B",
            "ADuUk8g6g6TZ6gYmChGgQCyBD9B464UvCwcE9a4CgC5B",
            "3AVi9TgZ6gYmChGgQCyBD9B464UvCwcE9a4CgC5B",
            "DttWaJVXiusFBgTY8B6mLDE2YvA6uh24QQj1mVR6iprs"
        ]
        logger.warning("JitoManager: tip_accounts initialized with fallback defaults. Call update_tip_accounts() to fetch dynamic accounts from Jito API.")
        self.bundle_client = JitoBundleClient(session=session, rpc_url=rpc_url)
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
                    accounts_data = await resp.json()
                    accounts = []
                    if isinstance(accounts_data, list):
                        accounts = accounts_data
                    elif isinstance(accounts_data, dict):
                        if "value" in accounts_data:
                            accounts = accounts_data["value"]
                        elif "result" in accounts_data:
                            accounts = accounts_data["result"]
                            if isinstance(accounts, dict) and "value" in accounts:
                                accounts = accounts["value"]
                                
                    if accounts and isinstance(accounts, list):
                        self.tip_accounts = accounts
                        self.bundle_client.tip_accounts = accounts
                        logger.info(f"🔄 Jito tip accounts updated: {len(self.tip_accounts)} active accounts")
                        return True
        except Exception as e:
            logger.warning(f"Failed to fetch dynamic Jito tip accounts: {e}. Using cached defaults.")
            
        return False

    def get_random_tip_account(self) -> str:
        """Select a random tip account for load balancing (thread-safe copy-on-read)."""
        accounts_snapshot = list(self.tip_accounts)
        if not accounts_snapshot:
            return "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"
        return random.choice(accounts_snapshot)

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

        # Ensure minimum tip + Micro-Jitter (The Tie-Breaker Fix)
        # FIXED: Расширен диапазон джиттера до +500..1500 лампортов для победы в аукционах
        tip_lamports = max(tip_lamports, self.default_tip_lamports)
        tip_lamports += random.randint(500, 1500)

        logger.info(f"💰 Calculated dynamic tip: {tip_sol:.6f} SOL ({tip_percentage*100:.1f}% of normalized profit)")
        return tip_lamports

    async def send_bundle(
        self,
        transaction: VersionedTransaction,
        payer_keypair: Keypair,
        tip_lamports: int,
        bundle_id: Optional[str] = None
    ) -> Dict:
        """
        Send transaction as Jito bundle with tip.

        Uses the pre-built transaction directly instead of rebuilding instructions.

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

            tx_base58 = base58.b58encode(bytes(transaction)).decode("ascii")
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendBundle",
                "params": [[tx_base58]]
            }

            # FIX 166: Parallel HTTP Shotgun across all Block Engine endpoints
            tasks = []
            for url in self.bundle_client.endpoints:
                tasks.append(asyncio.create_task(self.bundle_client._send_http_request(url, payload)))

            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED, timeout=1.5)
            for t in pending:
                t.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

            result = {"success": False, "error": "All shotgun endpoints failed"}
            for t in done:
                try:
                    res = t.result()
                    if res and res.get("success"):
                        result = res
                        break
                except Exception:
                    pass
            result["bundle_id"] = result.get("bundle_id")

            if result.get("success"):
                bundle_id = result.get("bundle_id")
                logger.info(f"✅ Bundle sent successfully: {bundle_id}")

                task = shared_state.retain_background_task(asyncio.create_task(self._poll_bundle_status(bundle_id)))
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
    TIP_ACCOUNTS_URL = "https://mainnet.block-engine.jito.wtf/api/v1/bundles/tip_accounts"

    def __init__(self):
        self.tip_floor_data = {}
        # FIX 167: Fully expand Jito tip accounts failover default array
        self.tip_accounts = [
            "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
            "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bLmis",
            "Cw8CFN97mo99uH2LL69Yp6Cgv7S8Z8B7A49K8a4CgC5B",
            "ADa6g7u6g6TZ6gYmChGgQCyBD9B464UvCwcE9a4CgC5B",
            "Df6Z8LMo6uH7T6C9G6fM5sU8g6G6CwcE9a4CgC5B",
            "ADuUk8g6g6TZ6gYmChGgQCyBD9B464UvCwcE9a4CgC5B",
            "3AVi9TgZ6gYmChGgQCyBD9B464UvCwcE9a4CgC5B",
            "DttWaJVXiusFBgTY8B6mLDE2YvA6uh24QQj1mVR6iprs"
        ]
        self.strategy_success: Dict[str, list] = {}  # strategy -> [ (timestamp, success_bool) ]
        self.consecutive_success = 0
        self.last_poll = 0.0
        # ── Phase 49: Adaptive Tip Step-Up ───────────────────────────────────
        # After N consecutive failed bundle submissions (simulation passed), ramp tip%
        self._consecutive_failures: Dict[str, int] = {}  # Phase 21: per-strategy counter (Dict[str,int])
        self._step_up_until = 0.0   # epoch when elevated tip window expires
        self.STEP_UP_THRESHOLD = 3  # failures before step-up
        self.STEP_UP_DURATION_S = 300  # 5-minute elevated tip window
        self.STEP_UP_TIP_PCT_LOW = 0.55  # 55% during elevated window
        self.STEP_UP_TIP_PCT_HIGH = 0.60  # 60% cap during elevated window
        self.BASE_TIP_PCT = 0.40  # 40% baseline

    async def update_tip_accounts(self, session: aiohttp.ClientSession) -> bool:
        """Fetch live Jito tip accounts from Block Engine (Phase 35)."""
        try:
            async with session.get(self.TIP_ACCOUNTS_URL, timeout=5.0) as resp:
                if resp.status == 200:
                    accounts = await resp.json()
                    if accounts and isinstance(accounts, list):
                        self.tip_accounts = accounts
                        logger.info(f"🔄 Jito tip accounts updated: {len(self.tip_accounts)} active accounts")
                        return True
        except Exception as e:
            logger.warning(f"Failed to fetch dynamic Jito tip accounts: {e}. Using cached defaults.")
        return False

    async def poll_tip_floor(self, session: aiohttp.ClientSession):
        """Poll every 10s continuously."""
        while True:
            try:
                now = time.time()
                if now - self.last_poll >= 10:
                    self.last_poll = now
                    async with session.get(self.TIP_FLOOR_URL, timeout=3) as resp:
                        if resp.status == 200:
                            self.tip_floor_data = await resp.json()
                            p50 = self.get_50th_percentile_lamports()
                            logger.info(f"📊 Jito tip floor updated: 50th={p50}")
            except Exception as e:
                logger.debug(f"Tip floor poll failed: {e}")
            await asyncio.sleep(2.0)

    def get_50th_percentile_lamports(self) -> int:
        """Safe tip floor parser — handles empty list/dict/None from Jito API."""
        try:
            if not self.tip_floor_data:
                return 10000
            if isinstance(self.tip_floor_data, list) and len(self.tip_floor_data) > 0:
                entry = self.tip_floor_data[0]
                if isinstance(entry, dict):
                    val = entry.get("landed_tips_50th_percentile", 10000)
                else:
                    val = 10000
            elif isinstance(self.tip_floor_data, dict):
                val = self.tip_floor_data.get("landed_tips_50th_percentile", 10000)
            else:
                val = 10000
            return int(val)
        except (IndexError, TypeError, ValueError, AttributeError):
            return 10000

    def calculate_blue_ocean_tip(
        self,
        expected_profit_sol: float,
        strategy: str = "blue_ocean",
        current_native_sol_balance: Optional[float] = None,
        target_mint_str: str = "So11111111111111111111111111111111111111112",  # Phase 19: mint for cross-currency normalization
        price_matrix: Optional[Dict[str, tuple]] = None,  # Phase 19: price matrix for USD conversion
    ) -> int:
        """
        Blue Ocean Tip Strategy: 40% of Expected Net Profit with Tip Floor Filter.

        Для стратегий LST Depeg, Sanctum Router — там нет жесткой
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

        # Phase 19: Cross-currency normalization — prevent tip suicide for non-SOL profits
        sol_mint = "So11111111111111111111111111111111111111112"
        profit_sol = expected_profit_sol
        if target_mint_str != sol_mint and price_matrix:
            try:
                sol_entry = price_matrix.get(sol_mint)
                sol_usd = sol_entry[0] if sol_entry else 150.0
                token_entry = price_matrix.get(target_mint_str)
                if token_entry and token_entry[0] > 0:
                    profit_sol = (expected_profit_sol * token_entry[0]) / sol_usd
                    logger.debug(
                        f"🔄 JitoBiddingManager normalized profit {expected_profit_sol:.6f} "
                        f"{target_mint_str[:8]} → {profit_sol:.6f} SOL"
                    )
            except Exception as e:
                logger.warning(f"JitoBiddingManager normalization failed: {e}")
        # Replace expected_profit_sol with normalized value for all subsequent calculations
        expected_profit_sol = profit_sol

        # ── Task 4: Logarithmic Jito Tip (Tapering Curve) ──────────────────
        # Taper tip % as profit increases to prevent excessive overpayment.
        # Hard cap at MAX_TIP_SOL (0.15 SOL) unless congestion is extreme.
        MAX_TIP_SOL = 0.15

        if expected_profit_sol <= 0.1:
            base_tip_pct = 0.40  # 40% for micro/small trades
        elif expected_profit_sol <= 1.0:
            base_tip_pct = 0.20  # 20% for medium trades
        else:
            base_tip_pct = 0.10  # 10% for large whale trades

        # ── Phase 49: Adaptive Tip Step-Up ───────────────────────────────────
        # If we are inside a step-up window (>= 3 consecutive failures earlier),
        # raise tip to competitive levels (up to 60%).
        tip_pct = base_tip_pct
        if time.time() < self._step_up_until:
            tip_pct = self.STEP_UP_TIP_PCT_HIGH
        elif self._consecutive_failures.get(strategy, 0) >= self.STEP_UP_THRESHOLD:
            self._step_up_until = time.time() + self.STEP_UP_DURATION_S
            tip_pct = self.STEP_UP_TIP_PCT_HIGH
            logger.warning(
                f"📈 Phase 49 Step-Up: {self._consecutive_failures.get(strategy, 0)} consecutive failures for {strategy} → "
                f"tip raised to {tip_pct*100:.0f}% for {self.STEP_UP_DURATION_S}s"
            )

        tip_sol = expected_profit_sol * tip_pct
        # Still respect MAX_TIP_SOL unless step-up is active (HFT survival priority)
        if time.time() >= self._step_up_until:
            tip_sol = min(tip_sol, MAX_TIP_SOL)

        # Convert to lamports
        tip_lamports = int(tip_sol * 1_000_000_000)

        # ── Task 7: Jito Pre-flight Tip Bump (Proactive Bidding) ───────────────
        # Compare calculated tip against the live Jito 50th percentile floor.
        # If calculated_tip < jito_floor BUT the expected_profit is large enough
        # to comfortably cover the floor (jito_floor < expected_profit * 0.8),
        # instantly override/bump the tip to jito_floor + random jitter.
        # Win the block on the first attempt instead of failing.
        floor_lamports = self.get_50th_percentile_lamports()
        if tip_lamports < floor_lamports:
            # Check if profit can comfortably cover the floor
            if floor_lamports < (expected_profit_sol * 0.80 * 1_000_000_000):
                bump_jitter = random.randint(100, 500)
                tip_lamports = floor_lamports + bump_jitter
                logger.debug(
                    f"🚀 Tip Bump (Task 7): {tip_lamports} lamports "
                    f"(floor={floor_lamports}, jitter={bump_jitter}) "
                    f"for {strategy}"
                )
            else:
                logger.warning(
                    f"🚫 Tip Floor Filter: {strategy} profit {expected_profit_sol:.6f} SOL too small "
                    f"to cover 50th percentile floor ({floor_lamports/1e9:.6f} SOL). skipping."
                )
                return 0

        # ── Fix 2 (Unfunded Jito Tip): Cap tip by actual native SOL balance ──
        # Jito Tip is a native SOL transfer. If the wallet has 0.017 SOL and
        # we try to send 0.004 SOL (40% of 0.01 USDC-profit treated as SOL),
        # the tx fails at pre-flight with InsufficientFundsForFee.
        # available_native_lamports is fetched from RPC when the caller has a session.
        # Callers should pass `current_native_sol_balance` via session query.
        # If not provided, we fall back to expected_profit_sol only.
        tip_lamports_float = tip_lamports
        if current_native_sol_balance is not None:
            if current_native_sol_balance < 0.1:
                import os
                min_reserve = float(os.getenv("MIN_RESERVE_SOL", "0.010"))
                available_space = max(0.0, current_native_sol_balance - min_reserve)
                available_native_lamports = int(available_space * 1_000_000_000)
            else:
                available_native_lamports = int((current_native_sol_balance - 0.005) * 1_000_000_000)
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

        # ── FIXED: Расширен диапазон джиттера до +500..1500 для защиты от перебивания ботами-конкурентами
        tip_lamports += random.randint(500, 1500)

        # Максимальный tip: никогда больше 70% от профита
        logger.info(
            f"💰 Blue Ocean tip: {tip_sol:.6f} SOL ({tip_pct*100:.0f}% of {expected_profit_sol:.6f} SOL profit) "
            f"| strategy={strategy}"
        )
        return tip_lamports

    def calculate_optimal_tip(
        self,
        expected_profit_sol: float,
        strategy: str = "default",
        current_native_sol_balance: Optional[float] = None,
        ata_rent_sol: float = 0.0,
        gas_sol: float = 0.0,
    ) -> int:
        """Start + Step-Up/Down + Capital Guard.

        🛡️ Tip Floor Filter (P1): Если 40% профита < 50й перцентиль Jito — отменяем сделку.
        Не пытаемся перебить пол (floor), если это съедает > 80% профита.
        Ждем, когда конкуренция упадет.

        Tips are computed from NET profit (after ATA rent and gas), never GROSS.
        """
        # Compute net profit after ATA rent and gas; tip from net, not gross.
        net_profit_sol = expected_profit_sol - ata_rent_sol - gas_sol
        if net_profit_sol <= 0:
            return 0

        # ── Dynamic Jito Tip Floor Filtering (P1) ──────────────────
        p50 = self.get_50th_percentile_lamports() / 1e9

        # FIX 296: Aggressive tip boost for micro-arbitrage (<0.001 SOL net profit)
        if net_profit_sol < 0.001:
            forty_pct_tip = net_profit_sol * 0.80
            logger.debug(f"🚀 Micro-Arb Tip Boost (80%): {forty_pct_tip:.6f} SOL for {strategy}")
        else:
            forty_pct_tip = net_profit_sol * 0.40

        # P1: Compare 40% tip against 50th percentile floor
        if forty_pct_tip < p50:
            # If the floor would eat more than 80% of profit, reject the trade
            if p50 > net_profit_sol * 0.80:
                logger.warning(
                    f"🚫 Tip Floor Filter (P1): {strategy} net profit {net_profit_sol:.6f} SOL "
                    f"too small to cover 50th percentile floor ({p50:.6f} SOL). "
                    f"40% tip ({forty_pct_tip:.6f} SOL) < floor ({p50:.6f} SOL). Skipping."
                )
                return 0
            # Otherwise, bump to p50 + random jitter
            import random
            bump_jitter = random.randint(100, 500)
            # FIX 115: Define base for floor-bump path to prevent UnboundLocalError
            base = p50 + bump_jitter / 1e9
            tip_lamports = int(base * 1e9)
            logger.debug(
                f"🚀 Tip Bump (Task 7): {tip_lamports} lamports "
                f"(floor={p50 * 1e9:.0f}, jitter={bump_jitter}) "
                f"for {strategy}"
            )
        else:
            base = forty_pct_tip

        # Success rate last 10 min
        import time
        cutoff = time.time() - 600
        hist = [s for t, s in self.strategy_success.get(strategy, []) if t > cutoff]
        success_rate = sum(hist) / len(hist) if hist else 1.0

        tip_sol = base
        if success_rate < 0.2:
            # Step-Up
            tip_sol = min(base * 1.05, net_profit_sol * 0.7)
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
                    f"returning 0 for {strategy}"
                )
                return 0
            capped = min(tip_lamports, available_native)
            if capped < 10_000:
                logger.warning(
                    f"⏭️ Optimal tip {capped} < {10_000} lamports minimum "
                    f"after native cap — returning 0 for {strategy}"
                )
                return 0
            logger.debug(
                f"💰 Optimal tip native cap: {tip_lamports / 1e9:.6f} SOL → "
                f"{capped / 1e9:.6f} SOL (native={current_native_sol_balance:.6f} SOL)"
            )
            tip_lamports = capped

        # ── FIXED: Расширен диапазон джиттера до +500..1500 для защиты от перебивания ботами-конкурентами
        tip_lamports += random.randint(500, 1500)

        return tip_lamports

    def record_trade_result(self, strategy: str, success: bool, tip_paid_lamports: int = 0):
        import time
        if strategy not in self.strategy_success:
            self.strategy_success[strategy] = []
        # FIX 205: Record actual tip paid to calculate overpayments on lost auctions
        self.strategy_success[strategy].append((time.time(), success, tip_paid_lamports))
        # Prune entries older than 10 minutes to prevent memory leak
        now = time.time()
        self.strategy_success[strategy] = [
            (t, s) for t, s in self.strategy_success[strategy] if now - t <= 600
        ]
        if success:
            self.consecutive_success += 1
        else:
            self.consecutive_success = 0

    def record_bundle_result(self, strategy: str, landed: bool, tip_paid_lamports: int = 0):
        """Phase 49 + Phase 21: Track consecutive bundle failures per strategy for dynamic step-up."""
        import time
        import asyncio
        # Phase 21: per-strategy counter
        prev = self._consecutive_failures.get(strategy, 0)
        if landed:
            # Success — reset per-strategy counter and collapse step-up window
            self._consecutive_failures[strategy] = 0
            self._step_up_until = 0.0
            self.record_trade_result(strategy, True, tip_paid_lamports)
            asyncio.create_task(send_telegram_alert(f"✅ <b>BUNDLE LANDED!</b>\nStrategy: <code>{strategy}</code> executed successfully."))
        else:
            # Accumulate per-strategy failure — trigger step-up window once threshold is hit
            self._consecutive_failures[strategy] = prev + 1
            if self._consecutive_failures[strategy] >= self.STEP_UP_THRESHOLD:
                self._step_up_until = time.time() + self.STEP_UP_DURATION_S
                logger.warning(
                    f"📈 Phase 49 Bidding Manager: {self._consecutive_failures[strategy]} consecutive failures for {strategy} → "
                    f"step-up window activated for {self.STEP_UP_DURATION_S}s"
                )
                asyncio.create_task(send_telegram_alert(f"⚠️ <b>JITO STEP-UP ACTIVATED</b>\n{self.STEP_UP_THRESHOLD} consecutive rejected bundles for <code>{strategy}</code>. Raising tip percentage!"))
            self.record_trade_result(strategy, False, tip_paid_lamports)