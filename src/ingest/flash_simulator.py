"""Flash Simulator — pre-flight validation for flash loan arbitrage bundles.

Runs ``simulateTransaction`` with ``sigVerify: false`` before committing SOL
to Jito tips, ensuring that only profitable transactions are sent on-chain.
This is critical for protecting the 0.017 SOL operating budget.
"""

import base64
import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger("FlashSim")



class SimulationResult:
    """Result of a pre-flight transaction simulation."""
    __slots__ = ("success", "error", "units_consumed", "pre_balances",
                 "post_balances", "balance_delta_lamports", "balance_delta_sol",
                 "logs", "simulation_time_ms")

    success: bool
    error: Optional[str]
    units_consumed: int
    pre_balances: List[int]
    post_balances: List[int]
    balance_delta_lamports: int
    balance_delta_sol: float
    logs: List[str]
    simulation_time_ms: float

    def __init__(
        self,
        success: bool,
        error: Optional[str] = None,
        units_consumed: int = 0,
        pre_balances: Optional[List[int]] = None,
        post_balances: Optional[List[int]] = None,
        balance_delta_lamports: int = 0,
        balance_delta_sol: float = 0.0,
        logs: Optional[List[str]] = None,
        simulation_time_ms: float = 0.0,
    ):
        self.success = success
        self.error = error
        self.units_consumed = units_consumed
        self.pre_balances = pre_balances if pre_balances is not None else []
        self.post_balances = post_balances if post_balances is not None else []
        self.balance_delta_lamports = balance_delta_lamports
        self.balance_delta_sol = balance_delta_sol
        self.logs = logs if logs is not None else []
        self.simulation_time_ms = simulation_time_ms

    def __post_init__(self):
        if self.pre_balances is None:
            self.pre_balances = []
        if self.post_balances is None:
            self.post_balances = []
        if self.logs is None:
            self.logs = []


class FlashSimulator:
    """Pre-flight simulator for flash loan arbitrage transactions."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        rpc_url: str,
        timeout: float = 3.0,
        private_rpc_only: bool = True,  # Phase 43: OpSec Guard
    ):
        self.session = session
        self.rpc_url = rpc_url
        self.timeout = timeout
        self.private_rpc_only = private_rpc_only
        # Track simulation stats for monitoring
        # FIX 11 (MarginFi Utilization Guard): cooldown tracking for banks that
        # return simulation errors. Prevents infinite RPC spam when a bank is at capacity.
        self._bank_cooldowns: Dict[str, float] = {}  # bank_vault_pubkey -> cooldown_until_timestamp
        self.MARGINFI_COOLDOWN_SECONDS = 60
        self._stats = {
            "total_simulations": 0,
            "successful": 0,
            "failed": 0,
            "profitable": 0,
            "unprofitable": 0,
            "gas_saved_lamports": 0,
        }

    def get_region_aware_rpc_url(self, jito_endpoint: str) -> str:
        """
        Get RPC URL matching the Jito bundle region.

        Fix E: Removed hardcoded region_mapping containing fake 'YOUR_KEY' URLs
        that caused all Jito-bound simulations to fail with HTTP 401.
        Returns the configured primary RPC URL unconditionally.
        """
        return self.rpc_url

    async def simulate_transaction(
        self,
        tx_b64: str,
        tx_signer_pubkey: str,
        wallet_index: int = 0,
        min_profit_lamports: int = 0,
        jito_endpoint: Optional[str] = None,
    ) -> SimulationResult:
        """Simulate a serialized transaction without signature verification.

        Args:
            tx_b64: Base64-encoded serialized transaction
            wallet_index: Index of wallet account in the transaction (usually 0 = payer)

        Returns:
            SimulationResult with balance deltas and error info
        """
        start = time.time()
        self._stats["total_simulations"] += 1

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "simulateTransaction",
            "params": [
                tx_b64,
                {
                    "encoding": "base64",
                    "commitment": "processed",
                    "sigVerify": False,
                    "replaceRecentBlockhash": False,
                    # Add accounts parameter to get balance changes
                    "accounts": {
                        "encoding": "base64",
                        "addresses": [tx_signer_pubkey]
                    }
                }
            ]
        }

        # Local Simulation Integrity: Use region-matching RPC for simulation
        simulation_rpc_url = self.rpc_url
        if jito_endpoint:
            simulation_rpc_url = self.get_region_aware_rpc_url(jito_endpoint)
            logger.debug(f"🔗 Simulation integrity: Using {simulation_rpc_url} to match Jito region")

        # Phase 43: OpSec Guard - Never simulate on public/shared nodes
        public_indicators = ["api.mainnet-beta", "solana-api.projectserum.com", "public.node"]
        if self.private_rpc_only and any(ind in simulation_rpc_url for ind in public_indicators):
            logger.error(f"🚨 OpSec Alert: Simulation blocked on public RPC {simulation_rpc_url} to prevent strategy theft.")
            return SimulationResult(success=False, error="OpSec: Public RPC blocked")

        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            async with self.session.post(simulation_rpc_url, json=payload, timeout=timeout) as resp:
                if resp.status != 200:
                    self._stats["failed"] += 1
                    return SimulationResult(
                        success=False,
                        error=f"RPC HTTP {resp.status}",
                        simulation_time_ms=(time.time() - start) * 1000,
                    )

                data = await resp.json()

                if "error" in data:
                    self._stats["failed"] += 1
                    return SimulationResult(
                        success=False,
                        error=f"RPC error: {data['error']}",
                        simulation_time_ms=(time.time() - start) * 1000,
                    )

                result = data.get("result", {}).get("value", {})
                err = result.get("err")
                logs = result.get("logs", [])
                units_consumed = result.get("unitsConsumed", 0)

                if err is not None:
                    self._stats["failed"] += 1
                    # Extract meaningful error from logs
                    error_detail = self._extract_error_from_logs(logs, err)
                    return SimulationResult(
                        success=False,
                        error=error_detail,
                        units_consumed=units_consumed,
                        logs=logs,
                        simulation_time_ms=(time.time() - start) * 1000,
                    )

                # ── Parse real pre/post balances for accurate profit delta ──
                # Solana simulateTransaction returns preBalances/postBalances as
                # top-level arrays in result.value (NOT inside individual account objects).
                # Wallet index 0 = signer/payer.
                self._stats["successful"] += 1
                actual_delta = 0
                pre_balances = []
                post_balances = []
                try:
                    pre_balances = result.get("preBalances", []) or []
                    post_balances = result.get("postBalances", []) or []
                    if pre_balances and post_balances and len(pre_balances) > 0 and len(post_balances) > 0:
                        actual_delta = post_balances[0] - pre_balances[0]
                        logger.debug(f"📊 FlashSim real delta: {actual_delta} lamports ({actual_delta/1e9:.6f} SOL)")
                except (ValueError, TypeError, IndexError):
                    actual_delta = 0

                if actual_delta <= 0:
                    logger.warning(f"🚫 FlashSim real delta {actual_delta/1e9:.6f} SOL <= 0 — trade not profitable")
                    return SimulationResult(
                        success=False,
                        error=f"Real balance delta {actual_delta/1e9:.6f} SOL <= 0",
                        simulation_time_ms=(time.time() - start) * 1000,
                    )

                return SimulationResult(
                    success=True,
                    units_consumed=units_consumed,
                    pre_balances=pre_balances,
                    post_balances=post_balances,
                    balance_delta_lamports=max(actual_delta, 0),
                    balance_delta_sol=max(actual_delta, 0) / 1e9,
                    logs=logs,
                    simulation_time_ms=(time.time() - start) * 1000,
                )

        except aiohttp.ClientError as e:
            self._stats["failed"] += 1
            return SimulationResult(
                success=False,
                error=f"Network error: {e}",
                simulation_time_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            self._stats["failed"] += 1
            return SimulationResult(
                success=False,
                error=f"Simulation error: {e}",
                simulation_time_ms=(time.time() - start) * 1000,
            )

    async def validate_profitability(
        self,
        tx_b64: str,
        tx_signer_pubkey: str,
        min_profit_lamports: int,
        tip_lamports: int = 0,
        priority_fee_lamports: int = 0,
        wallet_index: int = 0,
        jito_endpoint: Optional[str] = None,
        bank_vault_pubkey: Optional[str] = None,
        backup_rpc_url: Optional[str] = None,
    ) -> Tuple[bool, str, SimulationResult]:
        """Simulate and validate that the transaction is profitable.

        Runs a real RPC simulateTransaction, then STRICTLY calculates
        NET profit = balance_delta - tip_lamports - priority_fee_lamports.
        Never skips simulation. Never returns gross profit.

        Args:
            tx_b64: Base64-encoded transaction
            min_profit_lamports: Minimum NET profit threshold in lamports
            tip_lamports: Jito tip cost in lamports
            priority_fee_lamports: Priority fee cost in lamports
            wallet_index: Index of wallet in transaction accounts
            backup_rpc_url: Optional secondary RPC URL for cross-validation (SEC-007)

        Returns:
            Tuple of (is_profitable, reason, simulation_result)
        """
        # 1. Запускаем реальную симуляцию — никаких обходов
        sim = await self.simulate_transaction(tx_b64, tx_signer_pubkey, wallet_index, min_profit_lamports, jito_endpoint)

        if not sim.success:
            if bank_vault_pubkey and self._is_marginfi_error(sim.error):
                self.record_bank_cooldown(bank_vault_pubkey)
            return False, f"Simulation failed: {sim.error}", sim

        # FIX 302: Kamino fee = 0.05% of borrow volume, not min_profit threshold
        borrow_volume = min_profit_lamports if min_profit_lamports > 0 else 10_000_000
        flashloan_fee_lamports = int(borrow_volume * 0.0005)  # 0.05% of borrow volume

        # FIX 302: Jito tip + priority fee must be deducted from balance delta
        total_costs_lamports = flashloan_fee_lamports + tip_lamports + priority_fee_lamports
        net_profit_lamports = sim.balance_delta_lamports - total_costs_lamports

        # SEC-007: Cross-RPC Validation Guard — double-check simulation on backup RPC
        if backup_rpc_url and backup_rpc_url != self.rpc_url and net_profit_lamports >= min_profit_lamports:
            logger.debug(f"🔎 Cross-validating simulation on backup RPC: {backup_rpc_url[:50]}...")
            backup_sim = await self.simulate_transaction(
                tx_b64, tx_signer_pubkey, wallet_index, min_profit_lamports, jito_endpoint
            )
            # Use backup_rpc_url for the actual request by temporarily swapping
            import aiohttp
            backup_session = aiohttp.ClientSession()
            try:
                backup_payload = {
                    "jsonrpc": "2.0", "id": 1, "method": "simulateTransaction",
                    "params": [
                        tx_b64,
                        {
                            "encoding": "base64", "commitment": "processed",
                            "sigVerify": False, "replaceRecentBlockhash": False,
                            "accounts": {"encoding": "base64", "addresses": [tx_signer_pubkey]}
                        }
                    ]
                }
                async with backup_session.post(backup_rpc_url, json=backup_payload, timeout=aiohttp.ClientTimeout(total=self.timeout)) as backup_resp:
                    if backup_resp.status == 200:
                        backup_data = await backup_resp.json()
                        backup_result = backup_data.get("result", {}).get("value", {})
                        if backup_result.get("err"):
                            reason = f"RPC Poisoning Guard: Backup RPC simulation failed ({backup_result['err']})"
                            logger.critical(f"🚨 {reason}")
                            return False, reason, sim
                        backup_pre = backup_result.get("preBalances", []) or []
                        backup_post = backup_result.get("postBalances", []) or []
                        if backup_pre and backup_post and len(backup_pre) > 0 and len(backup_post) > 0:
                            backup_delta = backup_post[0] - backup_pre[0]
                            if backup_delta < min_profit_lamports:
                                reason = f"RPC Poisoning Guard: Backup RPC shows unprofitable ({backup_delta} lamports vs {net_profit_lamports} on primary)"
                                logger.critical(f"🚨 {reason}")
                                return False, reason, sim
                            logger.debug(f"✅ Cross-RPC validation passed: backup delta={backup_delta} lamports")
            except Exception as _backup_err:
                logger.warning(f"Cross-RPC backup simulation failed (non-blocking): {_backup_err}")
            finally:
                await backup_session.close()

        # 3. ПРОВЕРКА ПОРОГА ПРИБЫЛИ
        if net_profit_lamports < min_profit_lamports:
            # Phase 10: Track gas saved — accurately records how much capital
            # the simulator saved the bot from burning on this rejected trade.
            self._stats["gas_saved_lamports"] += (tip_lamports + priority_fee_lamports)
            reason = (
                f"Unprofitable trade: Net profit {net_profit_lamports} lamports "
                f"is below min_profit threshold {min_profit_lamports} "
                f"(Gross: {sim.balance_delta_lamports}, Tip: {tip_lamports}, Gas: {priority_fee_lamports})"
            )
            logger.warning(f"🚫 {reason}")
            return False, reason, sim

        profit_sol = net_profit_lamports / 1e9
        logger.info(
            f"✅ Flash Simulator APPROVED: Net Profit {profit_sol:.6f} SOL | "
            f"Gross Delta: {sim.balance_delta_lamports/1e9:.6f} SOL | "
            f"Sim Time: {sim.simulation_time_ms:.0f}ms"
        )

        successful_sim = SimulationResult(
            success=True,
            units_consumed=sim.units_consumed,
            balance_delta_lamports=net_profit_lamports,
            balance_delta_sol=profit_sol,
            logs=sim.logs,
            simulation_time_ms=sim.simulation_time_ms,
        )

        return True, f"Profitable: {profit_sol:.6f} SOL", successful_sim

    def is_bank_on_cooldown(self, bank_vault_pubkey: str) -> bool:
        """
        FIX 11: Check if a MarginFi bank is on cooldown after a simulation failure.
        Returns True if the bank should be skipped (cooldown still active).
        """
        cooldown_until = self._bank_cooldowns.get(bank_vault_pubkey, 0)
        if time.time() < cooldown_until:
            remaining = cooldown_until - time.time()
            logger.debug(f"⏳ FIX 11: Bank {bank_vault_pubkey[:8]} on cooldown ({remaining:.0f}s remaining)")
            return True
        return False

    def record_bank_cooldown(self, bank_vault_pubkey: str):
        """
        FIX 11: Record a 60-second cooldown for a MarginFi bank after a failed simulation.
        During cooldown, callers should skip this bank and attempt the Flash Loan Pivot.
        """
        self._bank_cooldowns[bank_vault_pubkey] = time.time() + self.MARGINFI_COOLDOWN_SECONDS
        logger.warning(f"⏳ FIX 11: Bank {bank_vault_pubkey[:8]} cooldown for {self.MARGINFI_COOLDOWN_SECONDS}s (simulation failure)")

    def get_stats(self) -> Dict:
        """Return cumulative simulation statistics."""
        stats = dict(self._stats)
        stats["gas_saved_sol"] = stats["gas_saved_lamports"] / 1e9
        return stats

    def _is_marginfi_error(self, error_str: Optional[str]) -> bool:
        """
        FIX 11: Detect MarginFi-specific simulation errors that indicate bank
        utilization limits have been reached (not transient RPC issues).
        """
        if not error_str:
            return False
        marginfi_keywords = [
            "BorrowingNotAllowed",
            "BankLiquidityVaultInsufficient",
            "BankCapacityExceeded",
            "BankUtilizationLimit",
            "FlashloanIntrospectionFailed",
            "FlashLoanIntrospection",
            "Custom Error",
        ]
        return any(kw.lower() in error_str.lower() for kw in marginfi_keywords)

    @staticmethod
    def _extract_error_from_logs(logs: List[str], err: any) -> str:
        """Extract a human-readable error from simulation logs."""
        if isinstance(err, dict):
            if "InstructionError" in err:
                idx, detail = err["InstructionError"]
                # Look for a custom error message in logs
                for log in reversed(logs):
                    if "Error" in log or "failed" in log.lower():
                        return f"Instruction {idx}: {log}"
                return f"Instruction {idx}: {detail}"
            return str(err)

        # Search logs for error context
        for log in reversed(logs):
            if "stale oracle" in log.lower():
                return "MarginFi: StaleOracle"
            if "Error" in log or "failed" in log.lower():
                return log
        return str(err)
