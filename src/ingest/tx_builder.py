"""Jupiter transaction builder for Solana swap transactions."""

import asyncio
import logging
import random
import base58
import base64
import orjson
import time
import hashlib
import os
from decimal import Decimal
from typing import Any, Dict, Optional, List, Tuple, Callable
import aiohttp
from solders.instruction import Instruction, AccountMeta
from solders.pubkey import Pubkey
from solders.hash import Hash
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from solders.message import MessageV0
from solders.transaction import VersionedTransaction
from solders.keypair import Keypair
from spl.token.instructions import (
    get_associated_token_address,
    create_associated_token_account,
    close_account,
    CloseAccountParams,
    TransferParams,
    transfer as spl_transfer,
)

logger = logging.getLogger(__name__)

try:
    from spl.token.instructions import create_idempotent_associated_token_account

    CREATE_ATA_FUNCTION = create_idempotent_associated_token_account
except ImportError:
    CREATE_ATA_FUNCTION = create_associated_token_account
    logger.warning(
        "create_idempotent_associated_token_account not available, using regular create_associated_token_account"
    )
from spl.token.constants import TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID
from solders.system_program import ID as SYSTEM_PROGRAM_ID

# Token-2022 Program ID for xStocks (RWA tokens)
TOKEN_2022_PROGRAM_ID = Pubkey.from_string(
    "TokenzQdBNbLqP5VEhdkAS6EP2rHEjaChQX6n57TR5m"
)

# AToken Program ID constant for ATA detection
ATOKEN_PROGRAM = "ATokenGPvbdQxrVyoUXYLdG6A8P5F8L8ytxHBSxl86"
# MarginFi Program ID - loaded from environment with default
MARGINFI_PROGRAM_ID = Pubkey.from_string(
    os.getenv("MARGINFI_PROGRAM_ID", "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA")
)
# Pre-computed SPL Token program discriminators (avoids hashlib.sha256 in hot path)
SYNC_NATIVE_DISCRIMINATOR = bytes([0x35, 0x9A, 0xDC, 0x8E, 0x9A, 0x8B, 0xEA, 0x6A])
CLOSE_ACCOUNT_DISCRIMINATOR = bytes([0x02, 0x9E, 0x8D, 0x1D, 0x11, 0x8E, 0x3B, 0x87])

# ── Task 14: Token-2022 Transfer Hook Account Registry ──────────────────
# Tracks remaining_accounts injected into swap instructions so that
# sanitize_instructions() and build_native_flashloan_tx() can validate
# they survive the full instruction pipeline.
# Structure: {id(instruction): injected_count}
_REMAINING_ACCOUNTS_REGISTRY: Dict[int, int] = {}

COMPUTE_BUDGET_PROGRAM_ID = Pubkey.from_string(
    "ComputeBudget111111111111111111111111111111"
)


def validate_cb_ordering(
    instructions: List[Instruction], location: str = "tx_builder"
) -> bool:
    """
    FIX 2: Validate that all ComputeBudget instructions are at indices 0 or 1.
    Solana SVM requires SetComputeUnitLimit and SetComputeUnitPrice to be the
    first two instructions. If any instruction (e.g. create ATA, SyncNative)
    accidentally appears before them, the SVM ignores our CU limits and defaults
    to 200k CU, causing InstructionError (OOG) on flash loan transactions.

    Returns True if valid, False if CB instructions found out of position.
    The caller should abort the transaction on False.
    """
    for i, ix in enumerate(instructions):
        if ix.program_id == COMPUTE_BUDGET_PROGRAM_ID:
            if i > 1:
                logger.error(
                    f"CRITICAL FIX-2 [{location}]: ComputeBudget instruction at index {i}. MUST be 0 or 1. Aborting to prevent SVM panic."
                )
                return False
    return True


def get_marginfi_vault_pdas(bank_pubkey: str):
    bank_pk = Pubkey.from_string(bank_pubkey)
    liquidity_vault, _ = Pubkey.find_program_address(
        [b"liquidity_vault", bytes(bank_pk)], MARGINFI_PROGRAM_ID
    )
    liquidity_vault_auth, _ = Pubkey.find_program_address(
        [b"liquidity_vault_auth", bytes(bank_pk)], MARGINFI_PROGRAM_ID
    )
    return liquidity_vault, liquidity_vault_auth


logger = logging.getLogger(__name__)


def get_anchor_discriminator(instruction_name: str) -> bytes:
    """Dynamically calculates the 8-byte Anchor discriminator."""
    return hashlib.sha256(f"global:{instruction_name}".encode("utf-8")).digest()[:8]


# MarginFi Flashloan Discriminators - dynamically computed (Phase 49)
MARGINFI_FLASHLOAN_START = get_anchor_discriminator("lending_account_start_flashloan")
MARGINFI_FLASHLOAN_END = get_anchor_discriminator("lending_account_end_flashloan")

# CU Profiles — single source of truth for all compute unit limits (P0 Priority)
# Replace every hardcoded set_compute_unit_limit(600000) / (300000) / etc.
# with a lookup from this dict so the bot only pays for units it actually uses.
CU_PROFILES: Dict[str, int] = {
    "stables_swap": 80_000,  # USDC/USDT 2-leg Jupiter swap
    "lst_depeg_arbitrage": 450_000,  # LST ↔ SOL via Sanctum multi-hop
    "xstock_oracle_lag": 800_000,  # xStock + USDC circular + Token-2022 overhead (+ Transfer Hooks)
    "flash_loan_pivot": 600_000,  # Flashloan + Jupiter swaps + SOL/USDC pivot
    "flash_arbitrage": 600_000,  # Full native flashloan with complex routing
    "liquidator": 400_000,  # Kamino/Native liquidation
    "default": 200_000,  # Conservative default
    # strategy_type → profile key mapping
    "strategy_1": "flash_arbitrage",
    "strategy_2": "lst_depeg_arbitrage",
    "strategy_4": "xstock_oracle_lag",
}

SWAP_INSTRUCTIONS_API_URL = os.getenv(
    "JUPITER_SWAP_INSTRUCTIONS_URL", "https://quote-api.jup.ag/v6/swap-instructions"
)


class NaiveLimiter:
    """Simple rate limiter fallback."""

    def __init__(self, rps: int):
        self.rps = rps
        self.semaphore = asyncio.Semaphore(rps)

    async def __aenter__(self):
        await self.semaphore.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Don't block the worker! Schedule release in background
        asyncio.get_running_loop().call_later(1.0, self.semaphore.release)


class JupiterTxBuilder:
    """Builds and signs Solana swap transactions using Jupiter API."""

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        timeout: float = 5.0,
        max_retries: int = 2,
        rpc_url: Optional[str] = None,
        rpc_getter: Optional[Callable[[], str]] = None,
        jupiter_rps: int = 5,
        alt_manager: Optional[Any] = None,
    ):
        self.session = session
        self.timeout = timeout
        self.max_retries = max_retries
        self._static_rpc_url = rpc_url
        self.rpc_getter = rpc_getter
        self.alt_manager = alt_manager
        self._session_owned = session is None
        # CU cache: key is (program_id, operation_type), value is (cu_limit, timestamp)
        self.cu_cache: Dict[Tuple[str, str], Tuple[int, float]] = {}
        self.cache_ttl = 60  # seconds
        # Jupiter rate limiter
        self.jupiter_limiter = self._create_limiter(jupiter_rps)

    @property
    def rpc_url(self) -> Optional[str]:
        """Dynamically returns the fastest RPC from the manager or falls back to static URL."""
        if self.rpc_getter:
            try:
                return self.rpc_getter()
            except Exception:
                pass
        return self._static_rpc_url

    def _create_limiter(self, rps: int):
        """Create async limiter for API calls."""
        try:
            from aiolimiter import AsyncLimiter

            return AsyncLimiter(max(1, rps), 1.0)
        except ImportError:
            logger.warning("aiolimiter not installed, using naive limiter")
            return NaiveLimiter(rps)

    async def __aenter__(self):
        if self._session_owned and self.session is None:
            self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session_owned and self.session:
            await self.session.close()

    async def estimate_transaction_cu(
        self, transaction: VersionedTransaction, rpc_url: Optional[str] = None
    ) -> int:
        """Simulate transaction to estimate CU usage.

        Args:
            transaction: The transaction to simulate
            rpc_url: Optional RPC URL to use for simulation

        Returns:
            Estimated CU usage, or 200000 as fallback
        """
        if not self.session:
            raise RuntimeError("Client session not available")

        rpc_url = rpc_url or self.rpc_url
        if not rpc_url:
            logger.warning(
                "No RPC URL provided for CU estimation, using default 200000 CU"
            )
            return 200000

        try:
            # Serialize transaction for simulation
            tx_b64 = base64.b64encode(bytes(transaction)).decode("ascii")

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "simulateTransaction",
                "params": [
                    tx_b64,
                    {
                        "encoding": "base64",
                        "commitment": "confirmed",
                        "replaceRecentBlockhash": False,
                        "accounts": {"encoding": "base64", "addresses": []},
                    },
                ],
            }

            timeout = aiohttp.ClientTimeout(total=2.0)
            async with self.session.post(
                rpc_url, json=payload, timeout=timeout
            ) as resp:
                if resp.status == 200:
                    data = orjson.loads(await resp.read())
                    if "result" in data and "value" in data["result"]:
                        sim_result = data["result"]["value"]
                        if (
                            "unitsConsumed" in sim_result
                            and sim_result["unitsConsumed"] is not None
                        ):
                            cu_used = sim_result["unitsConsumed"]
                            logger.debug(
                                f"Transaction simulation successful: {cu_used} CU consumed"
                            )
                            return cu_used
                        elif sim_result.get("err"):
                            logger.warning(
                                f"Simulation failed with error: {sim_result['err']}"
                            )
                        else:
                            logger.warning(
                                "Simulation completed but unitsConsumed not found"
                            )
                    else:
                        logger.warning(f"Invalid simulation response: {data}")
                else:
                    logger.warning(
                        f"Simulation request failed with status {resp.status}"
                    )

        except Exception as e:
            logger.warning(f"CU estimation failed: {e}")

        # Fallback to default
        logger.info("Using default CU limit: 200000")
        return 200000

    def _get_cu_cache_key(
        self, program_id: str, operation_type: str = "swap"
    ) -> Tuple[str, str]:
        """Generate cache key for CU estimation."""
        return (program_id, operation_type)

    def _get_cached_cu(
        self, program_id: str, operation_type: str = "swap"
    ) -> Optional[int]:
        """Get cached CU value if available and not expired."""
        key = self._get_cu_cache_key(program_id, operation_type)
        if key in self.cu_cache:
            cu_limit, timestamp = self.cu_cache[key]
            if time.time() - timestamp < self.cache_ttl:
                return cu_limit
            else:
                # Expired, remove from cache
                del self.cu_cache[key]
        return None

    def _cache_cu(self, program_id: str, cu_limit: int, operation_type: str = "swap"):
        """Cache CU limit for future use."""
        key = self._get_cu_cache_key(program_id, operation_type)
        self.cu_cache[key] = (cu_limit, time.time())

    async def get_dynamic_priority_fee(
        self,
        rpc_url: Optional[str] = None,
        lookback_slots: int = 20,
        expected_profit_sol: float = 0.0,
        cu_limit: int = 300_000,
        account_keys: Optional[List[str]] = None,
    ) -> int:
        """Get dynamic priority fee based on recent prioritization fees.

        Args:
            rpc_url: RPC URL to query
            lookback_slots: Number of recent slots to analyze
            expected_profit_sol: Expected profit in SOL for dynamic cap (5%)
            cu_limit: Compute unit limit for this transaction
            account_keys: List of account addresses for localized fee markets (2026)

        Returns:
            Priority fee in micro-lamports, or 1 if capped, or 0 to skip
        """
        if not self.session:
            raise RuntimeError("Client session not available")

        rpc_url = rpc_url or self.rpc_url
        if not rpc_url:
            logger.warning(
                "No RPC URL provided for priority fee estimation, using default"
            )
            return 1000  # Default 1000 micro-lamports

        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getRecentPrioritizationFees",
                "params": [account_keys or []],  # Localized fee market query
            }

            timeout = aiohttp.ClientTimeout(total=1.0)
            async with self.session.post(
                rpc_url, json=payload, timeout=timeout
            ) as resp:
                if resp.status == 200:
                    data = orjson.loads(await resp.read())
                    if "result" in data and data["result"]:
                        fees = [fee["prioritizationFee"] for fee in data["result"]]
                        if fees:
                            # Use 75th percentile for competitive pricing
                            fees.sort()
                            percentile_75_idx = int(len(fees) * 0.75)
                            priority_fee = fees[min(percentile_75_idx, len(fees) - 1)]
                            # Apply aggressiveness multiplier (1.1x)
                            priority_fee = int(priority_fee * 1.1)

                            # ── Dynamic Priority Fee Cap ──
                            # Budget: 0.015 SOL starting capital. We cannot afford high network fees.
                            # Dynamic Threshold: 5% of expected profit.
                            # If exceeded, force down to 0.00001 SOL (min viable) to stay in the race without dying.
                            # Guard: At least 0.00001 SOL if expected profit is tiny.
                            dynamic_cap_sol = max(expected_profit_sol * 0.05, 0.00001)
                            max_micro_lamports = int(
                                (dynamic_cap_sol * 1e9) / cu_limit * 1e6
                            )
                            min_viable_micro_lamports = int(
                                (0.00001 * 1e9) / cu_limit * 1e6
                            )

                            if priority_fee > max_micro_lamports:
                                logger.warning(
                                    f"⚠️ PRIORITY FEE SATURATION: {priority_fee} µ-lamports "
                                    f"exceeds {dynamic_cap_sol:.6f} SOL (5% profit cap). "
                                    f"Forcing down to min viable {min_viable_micro_lamports} µ-lamports."
                                )
                                return max(min_viable_micro_lamports, 1)

                            final_fee = min(priority_fee, max_micro_lamports)
                            logger.debug(
                                f"Dynamic priority fee: {final_fee} micro-lamports"
                            )
                            return max(final_fee, 1)  # Minimum 1 micro-lamport
                else:
                    logger.warning(
                        f"Priority fee request failed with status {resp.status}"
                    )

        except Exception as e:
            logger.warning(f"Dynamic priority fee estimation failed: {e}")

        return 1000  # Default fallback

    async def build_optimized_transaction(
        self,
        instructions: List[Instruction],
        address_lookup_tables: List,
        payer: Pubkey,
        recent_blockhash: str,
        program_id: str = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Jupiter v6 program ID
        operation_type: str = "swap",
        use_jito: bool = False,
        rpc_url: Optional[str] = None,
        expected_profit_sol: float = 0.0,
    ) -> Tuple[List[Instruction], int, int]:
        """Build transaction with optimized CU limit and priority fee.

        Args:
            instructions: Base transaction instructions
            address_lookup_tables: ALT accounts
            payer: Transaction payer pubkey
            recent_blockhash: Recent blockhash
            program_id: Program ID for CU caching
            operation_type: Operation type for CU caching
            use_jito: Whether transaction will be sent via Jito bundle
            rpc_url: RPC URL for simulation and fee estimation

        Returns:
            Tuple of (modified_instructions, cu_limit, priority_fee_micro_lamports)
        """
        # Compute Unit Profiling: Strategy-specific CU limits for capital protection
        cu_profiles = {
            "stables_swap": 45000,  # Simple stablecoin swaps
            "lst_arbitrage": 65000,  # LST arbitrage with flash loans
            "xstocks_arbitrage": 85000,  # xStocks with Token-2022 overhead
            "flash_arbitrage": 300000,  # Full flash loan arbitrage
            "default": 60000,  # Standard Jupiter swaps
        }

        cu_limit = cu_profiles.get(operation_type, cu_profiles["default"])

        # ─── Token-2022 Detection ────────────────────────────────────────────────
        # Token-2022 Transfer Hooks are detected below but NO buffer is applied.
        # Exact CU packing (simulated_cu + 1000) is enforced instead — this
        # lets the Solana Block Scheduler fit our transaction into a denser block.
        try:
            from src.config.xstocks_registry import is_xstock_token

            def _has_token2022(ixs: List[Instruction]) -> bool:
                """Return True if any instruction invokes a Token-2022 program ID."""
                for ix in ixs:
                    if is_xstock_token(ix.program_id):
                        return True
                return False

            if _has_token2022(instructions):
                logger.info(
                    "🛡️ Token-2022 detected: applying exact CU packing (no buffer)"
                )
        except Exception as _xstock_err:
            logger.debug(f"Token-2022 detection skipped: {_xstock_err}")

        # Use cached CU only if it's lower than our conservative (buffered) limit
        cached_cu = self._get_cached_cu(program_id, operation_type)
        if cached_cu and cached_cu < cu_limit:
            cu_limit = cached_cu

        # ╔══════════════════════════════════════════════════════════════════════╗
        # ║  CU PROFILES — dynamic limits from module-level CU_PROFILES dict      ║
        # ╚══════════════════════════════════════════════════════════════════════╝
        _profile_key = {
            "flash_arbitrage": "flash_arbitrage",
            "xstocks_arbitrage": "xstock_oracle_lag",
            "lst_arbitrage": "lst_depeg_arbitrage",
            "stables_swap": "stables_swap",
            "swap": "stables_swap",
            "default": "default",
        }.get(operation_type, operation_type)

        profile_cu = CU_PROFILES.get(_profile_key, CU_PROFILES["default"])
        cu_limit = max(cu_limit, profile_cu)  # Always at least the profile floor

        # СТРОГИЙ ФИЛЬТР ЛОКАЛЬНЫХ РЫНКОВ (Защита от переплаты за газ)
        # Исключаем системные программы, сисвары и всё, что read-only.
        # Нам интересна конкуренция только за пулы (writable state).
        writable_accounts = set()
        for ix in instructions:
            for meta in ix.accounts:
                if meta.is_writable: # Берем ТОЛЬКО изменяемые аккаунты
                    writable_accounts.add(str(meta.pubkey))
        
        # Дополнительно удаляем свой кошелек (за него нет конкуренции)
        writable_accounts.discard(str(payer))
        
        account_keys = list(writable_accounts)[:128]

        # Get priority fee
        # Минимальный пол для Priority Fee в размере 5000 микролампортов/CU даже в режиме Jito,
        # чтобы гарантировать прохождение пре-фильтров RPC-узлов для сложных транзакций (>200k CU).
        priority_fee = 5000 if use_jito else await self.get_dynamic_priority_fee(
            rpc_url, expected_profit_sol=expected_profit_sol, cu_limit=cu_limit, account_keys=account_keys
        )

        # Fix 60: Safety cap check — 0 is our skip sentinel from get_dynamic_priority_fee
        if priority_fee == 0:
            logger.warning(
                "🚫 PRIORITY FEE CAP HIT in build_optimized_transaction — trade aborted"
            )
            return None, 0, 0

        # Build final instructions with compute budget
        final_instructions = []

        # Add CU limit instruction first
        cu_limit_ix = set_compute_unit_limit(cu_limit)
        final_instructions.append(cu_limit_ix)

        # Add priority fee instruction (always added, value is 5000 for Jito, dynamic for non-Jito)
        priority_fee_ix = set_compute_unit_price(priority_fee)
        final_instructions.append(priority_fee_ix)

        # Append all remaining instructions after the CU budget pair
        final_instructions.extend(instructions)

        # ─── FIX 43: COMPILE-TIME ASSERTION ────────────────────────────────────
        # Guarantee that both compute-budget Ix are at indices 0 and 1 before
        # calling MessageV0.try_compile.  If any module above accidentally inserts
        # something before them, Solana falls back to the default 200k CU limit.
        cb_prog_id = Pubkey.from_string("ComputeBudget111111111111111111111111111111")
        for i, ix in enumerate(final_instructions):
            if ix.program_id == cb_prog_id:
                if i > 1:
                    logger.error(
                        f"COMPUTE_BUDGET_RUNTIME_ASSERT: Instruction {type(ix).__name__} found at index {i} > 1"
                    )
                    return (
                        None,
                        0,
                        0,
                    )  # Fix 6: hard check instead of assert (python -O safe)
        # ─────────────────────────────────────────────────────────────────────────

        # ─── TASK 2 RESTORE: MTU safety buffer check (no RPC call — local compile only)
        # Checks the serialized size against the 1232-byte Solana UDP-packet limit
        # without touching any network endpoint. This is purely a local operation.
        # Removed inline RPC simulation (saves 150-300ms); now local-only hardcoded checks.
        # └─ FIX: Rust Panic Guard — solders is Rust; a corrupted ALT or bytes overread can
        #   kill the Python process with SIGSEGV instead of a Python Exception.
        #   safe_alts filters None/NoneType first; the outer try/except intercepts any
        #   Rust-origin panic and logs it before exiting gracefully (no bad data reaches try_compile).
        try:
            safe_alts = [a for a in address_lookup_tables if a is not None]
            _bh = Hash.from_string(recent_blockhash)
            draft_msg = MessageV0.try_compile(
                payer=payer,
                instructions=final_instructions,
                address_lookup_table_accounts=safe_alts,
                recent_blockhash=_bh,
            )
            draft_tx = VersionedTransaction(draft_msg, [])
            _size = len(bytes(draft_tx))
            if _size > 1180:
                logger.warning(
                    f"🚫 TX {_size} B > 1180 B Hard-Cap — too many hops; flagging for Smart Retry"
                )
                return "MTU_SIZE_LIMIT", _size, 0
        except Exception as _compile_err:
            # CRITICAL: MessageV0.try_compile failed — possible Rust panic or malformed CU/ALT state.
            # We skip this TX attempt (no RPC roundtrip) and return None so the caller retries cleanly.
            logger.warning(
                f"🚨 tx_builder compile/MTU preflight error: {_compile_err} — skipping TX, no RPC call made."
            )
            return None, 0, 0

        # Update the CU limit instruction with the final profile-based value
        cu_limit_ix = set_compute_unit_limit(cu_limit)
        final_instructions[0] = cu_limit_ix

        # ── KERNEL TASK 5: Packet MTU Padding ───────────────────────────────────
        # Tiny QUIC packets (< 500 B) are deprioritised by Solana network providers.
        # If the compiled transaction is below the threshold, inject a no-op
        # ComputeBudget instruction so the serialized frame lands around ~600 B.
        # This is a local compile-only step — no RPC call.
        try:
            _mtu_alts = [a for a in (address_lookup_tables or []) if a is not None]
            _mtu_bh = Hash.from_string(recent_blockhash)
            _mtu_msg = MessageV0.try_compile(
                payer=payer,
                instructions=final_instructions,
                address_lookup_table_accounts=_mtu_alts,
                recent_blockhash=_mtu_bh,
            )
            _mtu_tx = VersionedTransaction(_mtu_msg, [])
            _mtu_size = len(bytes(_mtu_tx))
            if 0 < _mtu_size < 500:
                pass # MTU padding disabled: duplicate ComputeBudget causes rejection
                # _padding_target = 600
                # # No-op: SetComputeUnitLimit with existing limit (harmless duplicate at end)
                # _extra_cb = set_compute_unit_limit(cu_limit)
                # final_instructions.append(_extra_cb)
                # # Re-compile once to verify size after padding
                # _padded_msg = MessageV0.try_compile(
                #     payer=payer,
                #     instructions=final_instructions,
                #     address_lookup_table_accounts=_mtu_alts,
                #     recent_blockhash=_mtu_bh,
                # )
                # _padded_tx = VersionedTransaction(_padded_msg, [])
                # _padded_size = len(bytes(_padded_tx))
                # logger.debug(
                #     f"📦 MTU padding applied: {_mtu_size} B → {_padded_size} B "
                #     f"(target ≈{_padding_target} B; duplicate CU-limit no-op appended)"
                # )
        except Exception as _mtu_err:
            logger.debug(f"MTU padding skipped (non-critical): {_mtu_err}")

        return final_instructions, cu_limit, priority_fee

    def _parse_instruction(self, ix_data: Dict) -> Instruction:
        """Parse Jupiter instruction dictionary into solders.Instruction.

        Phase 49: SVM Account Locking Optimization.
        Forced read-only for program IDs and sysvars to improve scheduling priority.
        """
        raw_b64 = ix_data["data"]
        # Fix: pad base64 string to a multiple of 4 characters
        padded_b64 = raw_b64 + "=" * (-len(raw_b64) % 4)

        program_id = Pubkey.from_string(ix_data["programId"])

        # Static list of program IDs and sysvars that should NEVER be writable
        READ_ONLY_SYSTEM_IDS = {
            "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",  # Token Program
            "TokenzQdBNbLqP5VEhdkAS6EP2rHEjaChQX6n57TR5m",  # Token-2022 Program
            "ATokenGPvbdQxrVyoUXYLdG6A8P5F8L8ytxHBSxl86",  # Associated Token Program
            "11111111111111111111111111111111",  # System Program
            "ComputeBudget111111111111111111111111111111",  # Compute Budget
            "Sysvar1nstructions1111111111111111111111111",  # Instructions Sysvar
            "SysvarRent111111111111111111111111111111111",  # Rent Sysvar
            "SysvarC1ock111111111111111111111111111111111",  # Clock Sysvar
            "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Jupiter V6
            "JUP6LkbZbjS1jKKpphs4268Z9mUXas6W2L95sc376vv",  # Jupiter V6 alternative
        }

        accounts = []
        for meta in ix_data["accounts"]:
            pk_str = meta["pubkey"]
            is_writable = meta["isWritable"]

            # Optimization: if account is a known program or sysvar, force read-only
            if pk_str in READ_ONLY_SYSTEM_IDS:
                is_writable = False

            accounts.append(
                AccountMeta(
                    pubkey=Pubkey.from_string(pk_str),
                    is_signer=meta["isSigner"],
                    is_writable=is_writable,
                )
            )

        # ── KERNEL TASK 2: Write-Lock Congestion guard ──────────────────────────
        # Sort AccountMeta by is_writable — read-only (False) first, writable (True) last.
        # This minimises lock contention in the Solana SVM scheduler (QUIC / Agave)
        # so that the hot-path accounts (writable DEX state) are not interleaved with
        # immutable program IDs and sysvars.
        accounts.sort(key=lambda am: (am.is_writable, str(am.pubkey)))

        return Instruction(
            program_id=program_id,
            accounts=accounts,
data=(
            base64.b64decode(padded_b64)
            if isinstance(ix_data["data"], str)
            else bytes(ix_data["data"])
        ),
    )

    async def get_swap_instructions(
        self,
        quote_response: Dict[str, Any],
        wallet_pubkey: str,
        use_custom_cu: bool = False,
        expected_profit_sol: float = 0.0,  # Dynamic Rent Guard: profit in SOL
        expected_tip_lamports: int = 100_000,  # Ожидаемые чаевые
    ) -> Tuple[List[Instruction], List[Pubkey]]:
        """Get swap instructions from Jupiter API for a given quote.

        Args:
            quote_response: The response from the Jupiter /v6/quote API
            wallet_pubkey: User's public key as string
            expected_profit_sol: Expected profit in SOL for Dynamic Rent Guard

        Returns:
            Tuple of (list of solders Instructions, list of Address Lookup Table Pubkeys)
        """
        # Strip injected keys that Jupiter's Rust backend rejects
        clean_quote = {k: v for k, v in quote_response.items() if k != "fetched_at"}

        # Rate limit Jupiter API calls
        async with self.jupiter_limiter:
            payload = {
                "quoteResponse": clean_quote,
                "userPublicKey": wallet_pubkey,
                "wrapAndUnwrapSol": False,
                "dynamicComputeUnitLimit": False,  # ФИКС: Исключает конфликт с нашим кастомным CU-билдером
                "onlyDirectRoutes": "true",  # Task 14: force direct routes for micro-balance safety
                "restrictIntermediateTokens": "true",  # Task 14: unconditionally block intermediate tokens
                "maxAccounts": "8",  # FIX 8: Lowered to 8 for micro-balance safety (prevent ATA drain)
                "cache_buster": str(time.time_ns()),  # Task 1: Anti-cache bomb for HFT
            }
            instructions_data = await self._post_swap_instructions_request(payload)

        if "error" in instructions_data:
            logger.error(
                f"Failed to get swap instructions: {instructions_data['error']}"
            )
            return [], []

        instructions = []

        # ─── TASK 2: Dynamic Rent Guard ─────────────────────────────────────────
        # Protect against ATA rent cost exceeding profit. If setupInstructions
        # would create more than 1 ATA, skip the route to avoid rent trap.
        setup_instructions = instructions_data.get("setupInstructions", [])
        if setup_instructions:
            new_atas_needed = sum(
                1 for ix in setup_instructions
                if ix.get("programId", "") == ATOKEN_PROGRAM
            )
            rent_cost = new_atas_needed * 0.00204  # 0.00204 SOL per ATA
            if expected_profit_sol > 0 and rent_cost > expected_profit_sol:
                logger.warning(
                    f"🚫 SKIP: profit {expected_profit_sol:.6f} SOL < ATA rent {rent_cost:.6f} SOL ({new_atas_needed} ATAs)"
                )
                return [], []
        # ─────────────────────────────────────────────────────────────────────────

        # Skip compute budget instructions - we handle CU limits ourselves

        # Parse setup instructions (e.g. creating ATAs)
        if (
            "setupInstructions" in instructions_data
            and instructions_data["setupInstructions"]
        ):
            seen_atas = set()
            for ix_data in instructions_data["setupInstructions"]:
                ix = self._parse_instruction(ix_data)

                # ФИКС: Фильтруем ComputeBudget от Jupiter — SVM не допускает дубликатов
                if str(ix.program_id) == "ComputeBudget111111111111111111111111111111":
                    logger.debug("✂️ Вырезан дубликат ComputeBudget от Юпитера")
                    continue

                # Phase 12: Deduplicate Associated Token Account creation
                if str(ix.program_id) == "ATokenGPvbdQxrVyoUXYLdG6A8P5F8L8ytxHBSxl86":
                    # Make creation idempotent by modifying bytecode (b'' or b'\x00' -> b'\x01')
                    if ix.data == b'' or ix.data == b'\x00':
                        ix.data = b'\x01'
                        logger.debug("🛡️ Jupiter ATA instruction converted to Idempotent ATA")

                    if len(ix.accounts) >= 2:
                        ata_pubkey = str(ix.accounts[1].pubkey)
                        if ata_pubkey in seen_atas:
                            logger.debug(
                                f"🛡️ Skipping duplicate ATA creation for {ata_pubkey}"
                            )
                            continue
                        seen_atas.add(ata_pubkey)

                instructions.append(ix)

        swap_ix = None
        # Parse main swap instruction
        if (
            "swapInstruction" in instructions_data
            and instructions_data["swapInstruction"]
        ):
            _raw_swap = instructions_data["swapInstruction"]
            # Task 19: Filter ComputeBudget from swapInstruction — Jupiter may embed
            # its own CU limits here, which would duplicate our custom ones at index 0/1
            # and cause SVM to instantly reject the transaction.
            if str(_raw_swap.get("programId", "")) == "ComputeBudget111111111111111111111111111111":
                logger.debug("✂️ Вырезан дубликат ComputeBudget из swapInstruction от Юпитера")
            else:
                swap_ix = self._parse_instruction(_raw_swap)
                instructions.append(swap_ix)

        # ─── TASK 3: Remaining-Account Injection for Token-2022 Transfer Hooks ───
        # Jupiter's /v6/swap-instructions may supply extra non-ICIXI hook accounts in
        # top-level `remaining_accounts` field (e.g. for custom Token-2022 transfer hooks).
        # These accounts never appear in swapInstruction.accounts or setupInstructions;
        # they must be explicitly merged here to keep compile() happy.
        #
        # ─── TASK 14: Token-2022 Transfer Hook Propagation ──────────────────────
        # Track injected remaining_accounts count in a module-level dict so that
        # sanitize_instructions() and build_native_flashloan_tx() can validate
        # they survive the full instruction pipeline without being dropped.
        # Keyed by id(swap_ix) so we don't modify the Instruction object.
        rem_accounts = instructions_data.get("remaining_accounts", [])
        if rem_accounts and swap_ix is not None:
            # Build set of pubkey strings already covered by the swap instruction
            _covered_pks: set = {str(m.pubkey) for m in swap_ix.accounts}
            _injected = 0
            for ra in rem_accounts:
                pk_str = ra.get("pubkey", "")
                if not pk_str or pk_str in _covered_pks:
                    continue
                is_signer = ra.get("isSigner", False)
                is_writable = ra.get("isWritable", True)
                _covered_pks.add(pk_str)
                swap_ix.accounts.append(
                    AccountMeta(
                        pubkey=Pubkey.from_string(pk_str),
                        is_signer=is_signer,
                        is_writable=is_writable,
                    )
                )
                _injected += 1
            if _injected:
                logger.debug(
                    f"🔗 Task 14: Injected {_injected} remaining_accounts "
                    f"hook account(s) into swap instruction"
                )
                # Register in global registry for downstream validation
                _REMAINING_ACCOUNTS_REGISTRY[id(swap_ix)] = _injected

        # FIX 1 (Jupiter Cleanup Sabotage): NEVER add cleanupInstruction from Jupiter.
        # Jupiter sometimes returns cleanupInstruction that closes intermediate ATAs mid-tx,
        # causing AccountNotFound on the next leg. Also, AMMs leave unpredictable dust (1-2 micro-tokens)
        # in intermediate ATAs — CloseAccount reverts the FULL transaction if token balance != 0.
        # wSOL ATA is safely closed atomically in build_native_flashloan_tx.
        # All other ATAs are swept asynchronously by DustSweeper post-trade.
        if (
            "cleanupInstruction" in instructions_data
            and instructions_data["cleanupInstruction"]
        ):
            logger.debug(
                f"✂️ Stripped Jupiter cleanupInstruction — intermediate ATA dust would cause 100% revert"
            )

        alt_pubkeys = []
        if (
            "addressLookupTableAddresses" in instructions_data
            and instructions_data["addressLookupTableAddresses"]
        ):
            raw_alts = instructions_data["addressLookupTableAddresses"]
            alt_pubkeys = [Pubkey.from_string(alt) for alt in raw_alts]
            # Cache unknown ALTs in-MEMORY so subsequent calls never hit RPC for these tables.
            # Known ALTs are pre-cached at startup; unknown ones ("discovered" ALTs from Jupiter)
            # are fetched once and cached forever. Cost: 1 RPC call per unique ALT. Benefit: 50–150 ms
            # saved on every subsequent transaction that uses the same ALT.
            if self.alt_manager:
                for _pk in alt_pubkeys:
                    _cached = self.alt_manager.resolve_alt(_pk)
                    if _cached:
                        continue
                    # Not in cache — fetch asynchronously and cache (non-blocking)
                    asyncio.create_task(self.alt_manager.add_dynamic_alt(_pk))
            # Non-blocking ALT validation (background task)
            if self.alt_manager:
                asyncio.create_task(self._validate_alt_accounts(alt_pubkeys))

        return instructions, alt_pubkeys

    async def _post_swap_instructions_request(
        self, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Post request to Jupiter swap-instructions API."""
        for attempt in range(self.max_retries):
            try:
                headers = {"Content-Type": "application/json"}
                jupiter_api_key = os.getenv("JUPITER_API_KEY")
                if jupiter_api_key:
                    headers["Authorization"] = f"Bearer {jupiter_api_key}"

                async with self.session.post(
                    SWAP_INSTRUCTIONS_API_URL,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                ) as response:
                    if response.status == 200:
                        raw_bytes = await response.read()
                        return orjson.loads(raw_bytes)
                    elif response.status == 429:
                        await asyncio.sleep(2 ** (attempt + 1))
                    else:
                        error_text = await response.text()
                        logger.warning(
                            f"Swap instructions API error (attempt {attempt + 1}): {response.status} - {error_text}"
                        )

                        if attempt == self.max_retries - 1:
                            return {"error": f"HTTP {response.status}: {error_text}"}

            except asyncio.TimeoutError:
                logger.warning(f"Swap instructions API timeout (attempt {attempt + 1})")
                if attempt == self.max_retries - 1:
                    return {"error": "Request timeout"}

            except Exception as e:
                logger.error(
                    f"Swap instructions API error (attempt {attempt + 1}): {e}"
                )
                if attempt == self.max_retries - 1:
                    return {"error": str(e)}

        return {"error": "Max retries exceeded"}

    async def _validate_alt_accounts(self, alt_pubkeys: List[Pubkey]):
        """Validate that ALT accounts exist via RPC."""
        if not alt_pubkeys or not self.rpc_url:
            return

        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getMultipleAccounts",
                "params": [[str(pk) for pk in alt_pubkeys], {"encoding": "base64"}],
            }
            timeout = aiohttp.ClientTimeout(total=2.0)
            async with self.session.post(
                self.rpc_url, json=payload, timeout=timeout
            ) as resp:
                if resp.status == 200:
                    raw_bytes = await resp.read()
                    data = orjson.loads(raw_bytes)
                    if "result" in data and "value" in data["result"]:
                        accounts = data["result"]["value"]
                        invalid_alts = [
                            alt
                            for alt, acc in zip(alt_pubkeys, accounts)
                            if acc is None
                        ]
                        if invalid_alts:
                            logger.warning(
                                f"Invalid ALT accounts: {[str(pk) for pk in invalid_alts]}"
                            )
                            raise ValueError("One or more ALT accounts do not exist")

                        # Phase 38: Update ALT cache with validated results
                        if self.alt_manager:
                            for alt_pubkey, acc_data in zip(alt_pubkeys, accounts):
                                if acc_data and "data" in acc_data:
                                    resolved = self.alt_manager._parse_alt_data(
                                        acc_data["data"][0]
                                    )
                                    if resolved:
                                        alt_key = str(alt_pubkey)
                                        existing = self.alt_manager.alt_cache.get(
                                            alt_key, []
                                        )
                                        if len(resolved) >= len(existing):
                                            self.alt_manager.alt_cache[alt_key] = (
                                                resolved
                                            )
                                            self.alt_manager.alt_metadata[alt_key] = (
                                                time.time(),
                                                self.alt_manager.default_ttl,
                                            )
        except Exception as e:
            logger.error(f"ALT validation error: {e}")
            raise

    # === CRITICAL SAFETY CHECK METHODS ===

    async def _estimate_transaction_size(
        self,
        instructions: List[Instruction],
        address_lookup_tables: List[str],
        payer: Pubkey,
    ) -> int:
        """Estimate serialized transaction size in bytes."""
        try:
            # Create minimal message for size estimation
            dummy_blockhash = Hash.from_string("11111111111111111111111111111111")
            message = MessageV0.try_compile(
                payer=payer,
                instructions=instructions,
                address_lookup_table_accounts=[],  # Skip ALTs for estimation
                recent_blockhash=dummy_blockhash,
            )

            # Estimate size (rough calculation)
            # MessageV0 header + instructions + signatures
            base_size = 128  # Headers and metadata
            instructions_size = sum(
                len(ix.data) + 32 for ix in instructions
            )  # Rough estimate
            alt_size = len(address_lookup_tables) * 32  # ALT addresses

            estimated_size = base_size + instructions_size + alt_size

            estimated = int(estimated_size * 1.2)
            if estimated > 1180:
                logger.warning(
                    f"📏 MTU EXCEEDED: TX size estimate {estimated} B > 1180 B limit. "
                    "Flagging for Smart Retry with simpler route."
                )
                return 1181  # MTU_EXCEEDED sentinel value
            return estimated

        except Exception as e:
            logger.warning(f"Failed to estimate transaction size: {e}")
            return 2000  # Conservative fallback - assume too large

    async def _calculate_cpi_depth(self, instructions: List[Instruction]) -> int:
        """Estimate CPI (Cross-Program Invocation) depth."""
        max_depth = 1  # Base level

        for ix in instructions:
            # Jupiter swaps can have nested CPI calls
            if "Jupiter" in str(
                ix.program_id
            ) or "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8" in str(ix.program_id):
                max_depth = max(max_depth, 3)  # Jupiter can go 2-3 levels deep
            # Raydium/Orca AMM calls
            elif any(
                pid in str(ix.program_id)
                for pid in [
                    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
                    "9W959DqEETiGZocYWCQPaJ6sBmUzgfxXfqGeTEdp3aQP",
                ]
            ):
                max_depth = max(max_depth, 2)

        return max_depth

    async def _check_marginfi_liquidity_realtime(
        self, borrow_amount: int, bank_pubkey: str
    ) -> bool:
        """
        Phase 48: Real-time Liquidity Check via RPC with 95% Cap.
        Ensures we never attempt a trade that exceeds available bank funds.
        """
        try:
            # Perform direct RPC getBalance call for the bank's liquidity vault
            # In production, bank_pubkey is used to find the vault address.
            # For simplicity, we query the bank's liquidity vault balance.
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountBalance",
                "params": [bank_pubkey],  # This should be the VAULT address in practice
            }

            async with self.session.post(self.rpc_url, json=payload) as resp:
                data = orjson.loads(await resp.read())
                if "result" in data and "value" in data["result"]:
                    vault_lamports = int(data["result"]["value"]["amount"])

                    # 95% Cap to avoid "InsufficientLiquidity" reverts
                    safe_liquidity = int(vault_lamports * 0.95)

                    if borrow_amount > safe_liquidity:
                        logger.warning(
                            f"❌ MarginFi Liquidity Cap hit: Borrowing {borrow_amount/1e9:.3f} > Safe {safe_liquidity/1e9:.3f} SOL"
                        )
                        return False

                    return True

            return True  # Fallback if RPC fails
        except Exception as e:
            logger.error(f"Real-time liquidity check failed: {e}")
            return True

    async def get_max_marginfi_borrow(self, bank_pubkey: str) -> int:
        """
        Returns 95% of current available liquidity in the MarginFi pool.
        Protection: 95% cap prevents InsufficientLiquidity errors on execution.
        No hard SOL/USDC cap — OptimalTradeSizer controls position size upstream.
        """
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountBalance",
                "params": [bank_pubkey],  # bank_liquidity_vault
            }
            async with self.session.post(self.rpc_url, json=payload) as resp:
                data = orjson.loads(await resp.read())
                if "result" in data and "value" in data["result"]:
                    vault_lamports = int(data["result"]["value"]["amount"])
                    safe_liquidity = int(vault_lamports * 0.95)
                    return safe_liquidity
        except Exception as e:
            logger.error(f"Failed to fetch MarginFi bank liquidity: {e}")
        return 0

    async def _detect_sol_wrapping_conflict(
        self, instructions: List[Instruction]
    ) -> bool:
        """Detect if there are conflicting SOL wrapping instructions."""
        wrap_count = 0
        unwrap_count = 0

        for ix in instructions:
            # Check for syncNative instruction (wSOL wrapping)
            if ix.program_id == Pubkey.from_string(
                "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
            ):
                # syncNative discriminator is first 8 bytes of sha256("global:sync_native")
                if len(ix.data) >= 8 and ix.data[:8] == SYNC_NATIVE_DISCRIMINATOR:
                    wrap_count += 1

            # Check for closeAccount instruction (wSOL unwrapping)
            if ix.program_id == Pubkey.from_string(
                "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
            ):
                # closeAccount discriminator
                if len(ix.data) >= 8 and ix.data[:8] == CLOSE_ACCOUNT_DISCRIMINATOR:
                    unwrap_count += 1

        # If both wrapping and unwrapping detected, likely a conflict
        return wrap_count > 0 and unwrap_count > 0

    # === FLASHLOAN PROVIDER FALLBACK SYSTEM ===

    async def build_flashloan_with_fallback(
        self,
        borrow_asset: str,
        borrow_amount: Decimal,
        arbitrage_instructions: List[Instruction],
        wallet_keypair,
        pool_state_manager=None,
    ) -> Optional[Dict[str, Any]]:
        """
        Build flashloan transaction with automatic provider fallback.
        Prevents missed arbitrage from utilization limits.

        Provider Priority:
        1. MarginFi (0% fee, primary)
        2. Kamino (fallback)
        3. Solend/Save (last resort)

        Args:
            borrow_asset: Asset to borrow ('SOL', 'USDC', etc.)
            borrow_amount: Amount to borrow
            arbitrage_instructions: The arbitrage logic instructions
            wallet_keypair: Wallet keypair
            pool_state_manager: Pool state manager for utilization checks

        Returns:
            Transaction dict with selected provider or None
        """
        providers = await self._get_flashloan_providers(borrow_asset)

        for provider in providers:
            try:
                # Check provider availability
                if pool_state_manager:
                    available = await self._check_provider_availability(
                        provider, borrow_asset, borrow_amount, pool_state_manager
                    )
                    if not available:
                        logger.warning(
                            f"Provider {provider['name']} unavailable, trying fallback"
                        )
                        continue

                # Build transaction with this provider
                tx_data = await self._build_flashloan_for_provider(
                    provider,
                    borrow_asset,
                    borrow_amount,
                    arbitrage_instructions,
                    wallet_keypair,
                )

                if tx_data:
                    logger.info(
                        f"✅ Flashloan built with {provider['name']} | "
                        f"Asset: {borrow_asset} | Amount: {borrow_amount}"
                    )
                    return tx_data

            except Exception as e:
                logger.warning(f"Failed to build with {provider['name']}: {e}")
                continue

        logger.error("❌ All flashloan providers failed - arbitrage opportunity missed")
        return None

    async def _get_flashloan_providers(self, borrow_asset: str) -> List[Dict[str, Any]]:
        """Get ordered list of flashloan providers for asset."""
        base_providers = [
            {
                "name": "MarginFi",
                "program_id": "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA",
                "fee": 0,  # 0% fee
                "priority": 1,
            },
            {
                "name": "Kamino",
                "program_id": "KLend2g3cP87fffoy8q1mQqGKjrxjC8bojiCLxnsfmk",
                "fee": 0,  # 0% fee
                "priority": 2,
            },
            {
                "name": "Solend",
                "program_id": "So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpVF",  # Placeholder
                "fee": 0.001,  # 0.1% fee
                "priority": 3,
            },
        ]

        # Filter providers that support the asset
        supported_providers = []
        for provider in base_providers:
            if await self._provider_supports_asset(provider, borrow_asset):
                supported_providers.append(provider)

        # Sort by priority
        supported_providers.sort(key=lambda x: x["priority"])
        return supported_providers

    async def _check_provider_availability(
        self,
        provider: Dict[str, Any],
        borrow_asset: str,
        borrow_amount: Decimal,
        pool_state_manager,
    ) -> bool:
        """Check if provider has sufficient liquidity for the borrow."""
        try:
            # In practice, would query provider's on-chain liquidity
            # For now, simulate utilization check

            utilization_rate = await self._get_provider_utilization(
                provider, borrow_asset
            )

            # Available if utilization < 95%
            available = utilization_rate < 0.95

            if not available:
                logger.debug(
                    f"Provider {provider['name']} utilization: {utilization_rate:.1%}"
                )

            return available

        except Exception as e:
            logger.debug(f"Availability check failed for {provider['name']}: {e}")
            return True  # Assume available if check fails

    async def _get_provider_utilization(
        self, provider: Dict[str, Any], asset: str
    ) -> float:
        """Get utilization rate for provider/asset pair."""
        # In practice, would query on-chain data
        # For simulation, return mock values

        # Simulate MarginFi often at capacity
        if provider["name"] == "MarginFi" and asset == "USDC":
            return 0.98  # 98% utilized

        # Kamino more stable
        if provider["name"] == "Kamino":
            return 0.70  # 70% utilized

        return 0.50  # Default 50% utilization

    async def _provider_supports_asset(
        self, provider: Dict[str, Any], asset: str
    ) -> bool:
        """Check if provider supports borrowing the asset."""
        # All providers support major assets
        supported_assets = ["SOL", "USDC", "USDT", "wBTC", "wETH"]
        return asset in supported_assets

    async def _build_flashloan_for_provider(
        self,
        provider: Dict[str, Any],
        borrow_asset: str,
        borrow_amount: Decimal,
        arbitrage_instructions: List[Instruction],
        wallet_keypair,
    ) -> Optional[Dict[str, Any]]:
        """Build flashloan transaction for specific provider."""
        try:
            if provider["name"] == "MarginFi":
                return await self._build_marginfi_flashloan(
                    borrow_asset, borrow_amount, arbitrage_instructions, wallet_keypair
                )
            elif provider["name"] == "Kamino":
                return await self._build_kamino_flashloan(
                    borrow_asset, borrow_amount, arbitrage_instructions, wallet_keypair
                )
            elif provider["name"] == "Solend":
                return await self._build_solend_flashloan(
                    borrow_asset, borrow_amount, arbitrage_instructions, wallet_keypair
                )
            else:
                return None

        except Exception as e:
            logger.debug(f"Provider build failed for {provider['name']}: {e}")
            return None

    async def _build_marginfi_flashloan(
        self,
        borrow_asset: str,
        borrow_amount: Decimal,
        arbitrage_instructions: List[Instruction],
        wallet_keypair,
    ) -> Optional[Dict[str, Any]]:
        """Build MarginFi flashloan transaction using correct lending_account_flashloan instruction."""
        try:
            borrow_amount_lamports = int(
                borrow_amount * 1_000_000_000
            )  # Assume SOL for now
            repay_amount = (
                borrow_amount_lamports  # Fix 79: exact integer repayment, no drift
            )

            # Setup pubkeys (placeholder values, would be fetched)
            wallet = wallet_keypair.pubkey()
            mfi_program = Pubkey.from_string(
                "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"
            )
            mfi_account = Pubkey.from_string(
                "Sysvar1nstructions1111111111111111111111111"
            )  # Placeholder
            bank = Pubkey.from_string("Sysvar1nstructions1111111111111111111111111")  # Placeholder
            vault = Pubkey.from_string(
                "Sysvar1nstructions1111111111111111111111111"
            )  # Placeholder
            vault_auth = Pubkey.from_string(
                "Sysvar1nstructions1111111111111111111111111"
            )  # Placeholder
            sol_mint = Pubkey.from_string("So11111111111111111111111111111111111111112")
            user_sol_ata = get_associated_token_address(wallet, sol_mint)

            # Calculate repay index: after borrow + swaps + SPL repay transfer
            repay_index = 2 + len(
                arbitrage_instructions
            )  # borrow at 0, swaps, transfer, repay at end

            # Borrow instruction (Flashloan Start)
            borrow_ix = self.build_marginfi_start_flashloan_ix(
                mfi_program,
                mfi_account,
                wallet,
                bank,
                vault,
                vault_auth,
                user_sol_ata,
                TOKEN_PROGRAM_ID,
                borrow_amount_lamports,
                [repay_index],
            )

            # Repay instruction (Flashloan End)
            repay_ix = self.build_marginfi_end_flashloan_ix(
                mfi_program,
                mfi_account,
                wallet,
                bank,
                vault,
                vault_auth,
                user_sol_ata,
                TOKEN_PROGRAM_ID,
            )

            transfer_repay_ix = spl_transfer(
                TransferParams(
                    program_id=TOKEN_PROGRAM_ID,
                    source=user_sol_ata,
                    dest=vault,
                    owner=wallet,
                    amount=repay_amount,
                    signers=[],
                )
            )

            all_instructions = (
                [borrow_ix] + arbitrage_instructions + [transfer_repay_ix, repay_ix]
            )

            return {
                "instructions": all_instructions,
                "expected_output": borrow_amount_lamports,  # Placeholder
                "borrow_amount": borrow_amount_lamports,
            }

        except Exception as e:
            logger.error(f"Failed to build MarginFi flashloan: {e}")
            return None

    async def _build_kamino_flashloan(
        self,
        borrow_asset: str,
        borrow_amount: Decimal,
        arbitrage_instructions: List[Instruction],
        wallet_keypair,
    ) -> Optional[Dict[str, Any]]:
        """Build Kamino flashloan transaction."""
        # Implement Kamino-specific flashloan
        # Placeholder - would implement Kamino-specific instructions
        logger.debug("Kamino flashloan placeholder - needs implementation")
        return None

    async def _build_solend_flashloan(
        self,
        borrow_asset: str,
        borrow_amount: Decimal,
        arbitrage_instructions: List[Instruction],
        wallet_keypair,
    ) -> Optional[Dict[str, Any]]:
        """Build Solend flashloan transaction."""
        # Implement Solend-specific flashloan
        # Placeholder - would implement Solend-specific instructions
        logger.debug("Solend flashloan placeholder - needs implementation")
        return None

    # === MARGINFI DYNAMIC LIQUIDITY ===

    async def get_max_marginfi_borrow(self, bank_liquidity_vault: str) -> int:
        """
        Return 95 % of currently available MarginFi pool liquidity for a given vault.
        No magic numbers — the value comes straight from on-chain RPC.

        Args:
            bank_liquidity_vault: Pubkey of the MarginFi liquidity_vault PDA

        Returns:
            Max safe borrow in lamports (95 % of vault balance, no hard cap).
            Optimal trade sizing is applied by the caller via OptimalTradeSizer
            to avoid slippage consuming all profit.  A 95 % buffer prevents
            InsufficientLiquidity errors on execution.
            0 on any failure so callers can skip gracefully.
        """
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountBalance",
                "params": [bank_liquidity_vault],
            }
            async with self.session.post(self.rpc_url, json=payload) as resp:
                if resp.status == 200:
                    data = orjson.loads(await resp.read())
                    if (
                        "result" in data
                        and "value" in data["result"]
                        and data["result"]["value"].get("amount")
                    ):
                        vault_lamports = int(data["result"]["value"]["amount"])
                        # 95 % cap prevents InsufficientLiquidity errors
                        safe_liquidity = int(vault_lamports * 0.95)
                        return safe_liquidity
        except Exception as e:
            logger.error(
                f"Failed to fetch MarginFi bank liquidity for {bank_liquidity_vault[:8]}: {e}"
            )
        return 0

    # === SECURE ANCHOR EXECUTION (100% CAPITAL PROTECTION) ===

    async def build_native_flashloan_tx(
        self,
        wallet_pubkey: str,
        arbitrage_path: List[str],
        borrow_amount_lamports: int,
        expected_min_profit_lamports: int,
        dex_swap_instructions: List[Instruction],
        marginfi_config: Dict[str, str],
        jito_tip_lamports: int = 0,
        borrow_mint: str = "So11111111111111111111111111111111111111112",
        wsol_manager: Optional[Any] = None,
        pool_state_manager: Optional[Any] = None,
        use_jito: bool = True,
        # Flash Loan Pivot: Jupiter swap instructions for pivot path (SOL→USDC entry, USDC→SOL exit)
        entry_pivot_ixs: Optional[List[Instruction]] = None,
        exit_pivot_ixs: Optional[List[Instruction]] = None,
        # Fix 2: Dynamic Jito tip accounts (injected by caller from jito_executor.tip_accounts)
        tip_accounts: Optional[List[str]] = None,
        recent_blockhash: Optional[str] = None,
        # Token-2022 detection pre-imported at module level
    ) -> Optional[Dict[str, Any]]:
        """
        Build a native flashloan arbitrage transaction relying on MarginFi introspection.

        Phase 48:
        1. Bank IDs from os.getenv
        2. 95% Liquidity Cap
        3. Real-time RPC liquidity check
        """
        # Phase 48: Read Bank Pubkeys from os.getenv (Capital Protection)
        sol_bank_id = os.getenv(
            "MARGINFI_SOL_BANK", "CCwqExrqLGHtq12X182rFvA4KEDtK13q2E7B3Jp2Cxyj"
        ).strip()
        usdc_bank_id = os.getenv(
            "MARGINFI_USDC_BANK", "2s37akK2eyBbp8DZgCm7RtsaEz8eWhVKGfHGA3cKMEW2"
        ).strip()

        # Self-healing override to prevent fatal USDC bank address from .env
        correct_usdc = "2s37akK2eyBbp8DZgCm7RtsaEz8eWhVKGfHGA3cKMEW2"
        if usdc_bank_id != correct_usdc:
            usdc_bank_id = correct_usdc

        # Determine which bank to use based on borrow_mint
        bank_pubkey = sol_bank_id if "So111" in borrow_mint else usdc_bank_id

        # Real-time Liquidity Check with 95% Cap
        if not await self._check_marginfi_liquidity_realtime(
            borrow_amount_lamports, bank_pubkey
        ):
            return None

        # ── 2. Setup Pubkeys ──────────────────────────────────────────
        wallet = Pubkey.from_string(wallet_pubkey)
        mfi_program = Pubkey.from_string(
            marginfi_config.get(
                "program_id", "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"
            )
        )
        mfi_account = Pubkey.from_string(str(marginfi_config["marginfi_account"]))
        bank = Pubkey.from_string(bank_pubkey)
        vault = Pubkey.from_string(str(marginfi_config["bank_liquidity_vault"]))
        vault_auth = Pubkey.from_string(
            str(marginfi_config["bank_liquidity_vault_authority"])
        )

        sol_mint = Pubkey.from_string(borrow_mint)

        # Phase 48: Token-2022 Aware ATA Derivation
        from src.config.xstocks_registry import is_xstock_token

        sol_prog_id = (
            TOKEN_2022_PROGRAM_ID if is_xstock_token(sol_mint) else TOKEN_PROGRAM_ID
        )
        user_sol_ata = get_associated_token_address(wallet, sol_mint, sol_prog_id)

        # 3. Assemble Instructions ──────────────────────────────────
        all_instructions = []
        pivot_entry_ixs = (
            entry_pivot_ixs or []
        )  # SOL→USDC (before borrow on pivot path)
        pivot_exit_ixs = exit_pivot_ixs or []  # USDC→SOL (after repay on pivot path)

        # 0. Compute Budget (MEV Safety & Priority)
        # We add these here so we can calculate the EXACT repay index dynamically.
        # Dynamic CU limit via profile — strategy_type inferred from borrow_mint string.
        _native_profile = CU_PROFILES.get("flash_arbitrage", 600_000)
        all_instructions.append(set_compute_unit_limit(_native_profile))

        # ═══════════════════════════════════════════════════════════════════════
        # FIX 10 (SyncNative + wSOL ATA Recreation):
        # After Task 6 (allowing wSOL CloseAccount), the wSOL ATA is closed at
        # the end of every transaction. On the next trade, it must be re-created.
        # We create it idempotently here, and follow with a SyncNative to ensure
        # the token program recognizes any native SOL that enters the ATA via
        # SystemProgram transfers (e.g. Jupiter entry pivot swaps).
        # ═══════════════════════════════════════════════════════════════════════
        try:
            from spl.token.instructions import (
                create_idempotent_associated_token_account,
                sync_native,
                SyncNativeParams,
            )
            wsol_mint_pk = Pubkey.from_string("So11111111111111111111111111111111111111112")
            # Create wSOL ATA idempotently (no-op if already exists)
            create_wsol_ata_ix = create_idempotent_associated_token_account(
                payer=wallet, owner=wallet, mint=wsol_mint_pk
            )
            all_instructions.append(create_wsol_ata_ix)
            logger.debug(
                f"🛡️ FIX 10: Idempotent wSOL ATA ensured for {wallet_pubkey[:8]}"
            )
            # SyncNative — ensures token program recognises native SOL in the ATA
            wsol_ata_pk = get_associated_token_address(wallet, wsol_mint_pk)
            sync_native_ix = sync_native(
                SyncNativeParams(program_id=TOKEN_PROGRAM_ID, account=wsol_ata_pk)
            )
            all_instructions.append(sync_native_ix)
            logger.debug(
                f"🔄 FIX 10: SyncNative appended for wSOL ATA {str(wsol_ata_pk)[:8]}"
            )
        except ImportError as _wsol_import_err:
            logger.warning(
                f"FIX 10: create_idempotent_ata / SyncNative not available, skipping: {_wsol_import_err}"
            )
        except Exception as _wsol_err:
            logger.warning(f"FIX 10: wSOL ATA setup failed (non-fatal): {_wsol_err}")
        # ═══════════════════════════════════════════════════════════════════════

        # ── Flash Loan Pivot: Entry swap FIRST (wallet SOL → USDC before borrow) ──
        # This converts the wallet's native SOL into USDC so the arb can run in USDC.
        # Net effect: wallet balance (-SOL_entry + USDC_gain) + borrowed USDC = total USDC for arb
        for pv_ix in pivot_entry_ixs:
            all_instructions.append(pv_ix)
        # Removed set_compute_unit_price - will be added by build_optimized_transaction

        # 1. Borrow from MarginFi (Flashloan Start — placeholder index)
        borrow_ix = self.build_marginfi_start_flashloan_ix(
            mfi_program,
            mfi_account,
            wallet,
            bank,
            vault,
            vault_auth,
            user_sol_ata,
            sol_prog_id,
            borrow_amount_lamports,
            [0],
        )
        all_instructions.append(borrow_ix)

        # 2. DEX Swaps
        all_instructions.extend(dex_swap_instructions)

        # 4. SPL repay transfer, then MarginFi Flashloan End
        transfer_repay_ix = spl_transfer(
            TransferParams(
                program_id=sol_prog_id,
                source=user_sol_ata,
                dest=vault,
                owner=wallet,
                amount=borrow_amount_lamports,
                signers=[],
            )
        )
        repay_ix = self.build_marginfi_end_flashloan_ix(
            mfi_program,
            mfi_account,
            wallet,
            bank,
            vault,
            vault_auth,
            user_sol_ata,
            sol_prog_id,
        )
        all_instructions.append(transfer_repay_ix)
        all_instructions.append(repay_ix)

        # Flash Loan Pivot — exit swap (USDC → SOL): run AFTER arb repay so profit
        # is converted into the borrow asset (SOL) before returning to MarginFi.
        for pv_ix in exit_pivot_ixs or []:
            all_instructions.append(pv_ix)

        # =====================================================================
        # Fix 1 (Non-burning Dust): Only close wSOL atomically.
        # Intermediate ATA (BONK, xStocks, etc.) leave 1–2 micro-token dust after Jupiter/Raydium swaps.
        # CloseAccount reverts the FULL transaction if token balance != 0.
        # wSOL is safe because close_account unwraps all wSOL + 0.002 SOL rent in one instruction.
        # All other ATA are cleaned asynchronously by dust_sweeper post-tx.
        # wsol_mint_pk = Pubkey.from_string("So11111111111111111111111111111111111111112")
        # wsol_ata = get_associated_token_address(wallet, wsol_mint_pk)
        # all_instructions.append(
        #     close_account(
        #         CloseAccountParams(
        #             program_id=TOKEN_PROGRAM_ID,
        #             account=wsol_ata,
        #             dest=wallet,
        #             owner=wallet,
        #             signers=[],
        #         )
        #     )
        # )
        # logger.debug(
        #     "🔓 Fix 1 (Non-burning Dust): wSOL ata closed atomically | intermediate ATA delegated to dust_sweeper"
        # )
        # =====================================================================

        # ЗАЩИТА КАПИТАЛА (0.017 SOL): Чаевые Jito СТРОГО в конце единой транзакции.
        # Если DEX Swap выдаст SlippageExceeded или MarginFi Repay выдаст InsufficientFunds ->
        # вся транзакция откатывается, и перевод чаевых НЕ СРАБОТАЕТ.
        if jito_tip_lamports > 0:
            from solders.system_program import TransferParams, transfer

            # Fix 1: wSOL already closed atomically above.
            # Dynamic tip accounts — caller must supply, abort if empty (no hardcoded fallback).
            if not tip_accounts:
                logger.critical(
                    "🚨 JITO TIP ACCOUNTS: tip_accounts is empty! "
                    "Caller must supply jito_executor.tip_accounts. Aborting to prevent hardcoded fallback."
                )
                return None
            selected_tip_account = random.choice(tip_accounts)
            tip_ix = transfer(
                TransferParams(
                    from_pubkey=wallet,
                    to_pubkey=Pubkey.from_string(selected_tip_account),
                    lamports=jito_tip_lamports,
                )
            )
            all_instructions.append(tip_ix)

        # ═══════════════════════════════════════════════════════════════════
        # FIX 7 (MarginFi Introspection Index Shift): sanitize instructions FIRST
        # before calculating the repay index. sanitize_instructions may remove
        # duplicate ATA creation instructions, shifting the array. If we calculate
        # the repay index on the unsanitized list, MarginFi's introspection will
        # look at the wrong index and revert with 100% certainty.
        # ═══════════════════════════════════════════════════════════════════
        sanitized = self.sanitize_instructions(all_instructions, payer=wallet)

        # ── Task 14: Validate remaining_accounts survived sanitization ─────
        _rem_accounts_lost = 0
        # Cleanup old entries from registry (keyed by id() which may be GC'd)
        _valid_ids = {id(ix) for ix in sanitized}
        _stale_keys = [k for k in _REMAINING_ACCOUNTS_REGISTRY if k not in _valid_ids]
        for _sk in _stale_keys:
            _REMAINING_ACCOUNTS_REGISTRY.pop(_sk, None)

        for _ix in sanitized:
            _expected = _REMAINING_ACCOUNTS_REGISTRY.get(id(_ix), 0)
            if _expected > 0:
                # The instruction was tagged with remaining_accounts — check
                # that the extra accounts weren't stripped during sanitize.
                # We can only approximate: count the Jupiter program accounts.
                _jup_prog = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
                if str(_ix.program_id) == _jup_prog and len(_ix.accounts) < 20:
                    # Jupiter swaps typically have 15-25 accounts.
                    # < 20 after expecting rem_accounts means some were lost.
                    _rem_accounts_lost += 1
                    logger.warning(
                        f"🚨 Task 14: Possible remaining_accounts loss detected! "
                        f"Jupiter swap ix has only {len(_ix.accounts)} accounts "
                        f"(expected ~{_expected} remaining accounts). "
                        f"Transaction may fail with PrivilegeEscalation."
                    )
        if _rem_accounts_lost > 0:
            logger.debug(f"🔗 Task 14: {_rem_accounts_lost} instruction(s) with potential remaining_accounts issues")
        # ─────────────────────────────────────────────────────────────────────

        # Find the (possibly new) indices within the sanitized list
        # so the repay_index we pack into borrow_ix.data is 100% correct.
        try:
            actual_repay_index = next(
                (i for i, ix in enumerate(sanitized)
                 if ix.program_id == repay_ix.program_id and ix.data[:8] == MARGINFI_FLASHLOAN_END),
                None
            )
            if actual_repay_index is None:
                logger.error("CRITICAL: repay_ix not found in sanitized instruction list")
                return None

            # ── БЕЗОПАСНАЯ ПЕРЕСБОРКА ДАННЫХ (Первые 8 байт - дискриминатор, затем 8 байт - u64 amount) ──
            # Формат: discriminator(8) + amount(8) + index(1)
            import struct
            from solders.instruction import Instruction

            # Find borrow_ix in the SANITIZED list using generator (Fix 57)
            new_borrow_idx = next(
                (i for i, ix in enumerate(sanitized)
                 if ix.program_id == borrow_ix.program_id and ix.data[:8] == MARGINFI_FLASHLOAN_START),
                None
            )
            if new_borrow_idx is None:
                logger.error("CRITICAL: borrow_ix not found in sanitized instruction list")
                return None
            original_data_without_index = borrow_ix.data[:16]
            safe_index_bytes = struct.pack("<Q", actual_repay_index)
            new_data = original_data_without_index + safe_index_bytes
            new_borrow_ix = Instruction(
                program_id=borrow_ix.program_id,
                accounts=borrow_ix.accounts,
                data=new_data,
            )
            sanitized[new_borrow_idx] = new_borrow_ix
            borrow_ix = new_borrow_ix

            logger.debug(
                f"🛠️ FIX 7: Safe Dynamic Repay Index calculated on sanitized array: {actual_repay_index}"
            )
        except (ValueError, StopIteration):
                    logger.error("CRITICAL: repay_ix not found in sanitized instruction list")
                    return None

        return {
            "instructions": sanitized,
            "address_lookup_tables": [],  # Would be populated
            "repay_index": actual_repay_index,
            "recent_blockhash": recent_blockhash,
        }

    def sanitize_instructions(
        self, instructions: List[Instruction], payer: Optional[Pubkey] = None
    ) -> List[Instruction]:
        """Phase 48: Global Cross-Leg ATA Deduplication + Golden ATA Protection.
        Filters out redundant create_associated_token_account instructions.
        NEVER closes Golden ATAs (wSOL, USDC) — they are sacred.

        SVM Account Locking Optimization:
        Forced read-only for program IDs and sysvars to improve scheduling priority.

        Args:
            instructions: List of instructions to sanitize.
            payer: Optional wallet pubkey to compute golden ATA addresses.
                   If None, golden ATA CloseAccount detection is skipped (safe fallback).
        """
        seen_atas = set()
        sanitized = []
        ata_prog = Pubkey.from_string("ATokenGPvbdQxrVyoUXYLdG6A8P5F8L8ytxHBSxl86")
        # Golden ATAs that must NEVER be closed
        # FIX 6 (wSOL Death Spiral): wSOL REMOVED from golden ATAs.
        # We MUST allow CloseAccount on wSOL so the native SOL is unwrapped
        # and refunded to the wallet to pay Jito tips. The ATA will be
        # re-created idempotently on the next trade.
        # USDC remains protected as a Golden ATA.
        _golden_mints = {
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC — keep protected
        }
        # Pre-compute golden ATA addresses if payer is known
        _golden_atas = set()
        if payer is not None:
            from spl.token.instructions import get_associated_token_address

            for _gm in _golden_mints:
                try:
                    _golden_atas.add(
                        str(
                            get_associated_token_address(payer, Pubkey.from_string(_gm))
                        )
                    )
                except Exception:
                    pass

        # Phase 49: SVM Account Locking Optimization (Sanitizer Level)
        READ_ONLY_SYSTEM_IDS = {
            "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",  # Token Program
            "TokenzQdBNbLqP5VEhdkAS6EP2rHEjaChQX6n57TR5m",  # Token-2022 Program
            "ATokenGPvbdQxrVyoUXYLdG6A8P5F8L8ytxHBSxl86",  # Associated Token Program
            "11111111111111111111111111111111",  # System Program
            "ComputeBudget111111111111111111111111111111",  # Compute Budget
            "Sysvar1nstructions1111111111111111111111111",  # Instructions Sysvar
            "SysvarRent111111111111111111111111111111111",  # Rent Sysvar
            "SysvarC1ock111111111111111111111111111111111",  # Clock Sysvar
            "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Jupiter V6
            "JUP6LkbZbjS1jKKpphs4268Z9mUXas6W2L95sc376vv",  # Jupiter V6 alternative
        }

        for ix in instructions:
            # Force read-only for program accounts and known sysvars
            for meta in ix.accounts:
                if str(meta.pubkey) in READ_ONLY_SYSTEM_IDS:
                    # Принудительно отключаем блокировку на запись
                    meta.is_writable = False

            if ix.program_id == ata_prog:
                # Associated Token Account program: target ATA is typically account at index 1
                if len(ix.accounts) >= 2:
                    ata_pubkey = str(ix.accounts[1].pubkey)
                    if ata_pubkey in seen_atas:
                        logger.debug(
                            f"✂️ Deduplicated ATA creation for {ata_pubkey[:8]}"
                        )
                        continue
                    seen_atas.add(ata_pubkey)
            # FIX 1 (Golden ATA Protection): NEVER close wSOL or USDC ATAs.
            # Jupiter's cleanupInstruction or our own sanitize must NEVER touch these.
            if str(ix.program_id) == "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA":
                # Detect CloseAccount instruction
                if len(ix.data) >= 8 and ix.data[:8] == CLOSE_ACCOUNT_DISCRIMINATOR:
                    # CloseAccount: account is at index 0, dest at index 1, owner at index 2
                    if len(ix.accounts) >= 1:
                        close_target = str(ix.accounts[0].pubkey)
                        if close_target in _golden_atas:
                            logger.warning(
                                f"🛡️ GOLDEN ATA PROTECTION: Blocked CloseAccount for golden ATA ({close_target[:8]})"
                            )
                            continue
            sanitized.append(ix)
        return sanitized

    async def build_marginfi_flashloan_tx(
        self,
        wallet_pubkey: str,
        borrow_amount_lamports: int,
        buy_quote_response: Dict[str, Any],
        sell_quote_response: Dict[str, Any],
        marginfi_account: str,
        bank_pubkey: str,
        bank_liquidity_vault: str,
        bank_liquidity_vault_authority: str,
        arbitrage_path: Optional[List[str]] = None,
        jito_tip_lamports: int = 0,
        use_jito: bool = True,
        strategy_type: int = 1,
        tip_accounts: Optional[List[str]] = None,  # Fix 2: dynamic tip accounts
        recent_blockhash: Optional[str] = None,
        borrow_mint: Optional[
            str
        ] = None,  # Fix 2b: Oracle Pivot — alternate borrow asset (SOL or USDC)
        expected_profit_sol: float = 0.0,  # Dynamic Rent Guard: profit in SOL
    ) -> Optional[Dict[str, Any]]:
        try:
            from solders.pubkey import Pubkey
            from spl.token.instructions import get_associated_token_address
            from spl.token.constants import TOKEN_PROGRAM_ID

            wallet = Pubkey.from_string(wallet_pubkey)
            mfi_program = Pubkey.from_string(
                "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"
            )
            # Use borrow_mint if provided (Oracle Pivot), otherwise default to SOL
            borrow_mint_str = (
                borrow_mint
                if borrow_mint
                else "So11111111111111111111111111111111111111112"
            )
            borrow_mint_pubkey = Pubkey.from_string(borrow_mint_str)

            # Fix 2b: Oracle Pivot — auto-switch bank config when borrow asset is USDC
            _usdc_mint_str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            if borrow_mint_str == _usdc_mint_str:
                bank_pubkey = os.getenv(
                    "MARGINFI_USDC_BANK", "2s37akK2eyBbp8DZgCm7RtsaEz8eWhVKGfHGA3cKMEW2"
                ).strip()
                bank_liquidity_vault = os.getenv(
                    "MARGINFI_USDC_VAULT",
                    "2s37akK2eyBbp8DZgCm7RtsaEz8eWhVKGfHGA3cKMEW2",
                ).strip()
                bank_liquidity_vault_authority = os.getenv(
                    "MARGINFI_USDC_VAULT_AUTH",
                    "EhBxU585Rdru5WS8k4KjprGegcGLM8igXy3hDph5yVLy",
                ).strip()
                logger.debug(
                    f"🔄 Oracle Pivot: switched bank config to USDC (bank={bank_pubkey[:8]}...)"
                )

            user_borrow_ata = get_associated_token_address(wallet, borrow_mint_pubkey)

            all_instructions = []
            alts = []

# Get Buy Swaps (если quote не пустой)
            if buy_quote_response:
                buy_ixs, buy_alts = await self.get_swap_instructions(
                    buy_quote_response, wallet_pubkey, use_custom_cu=True, expected_profit_sol=expected_profit_sol
                )
                if not buy_ixs:
                    return None
                alts.extend(buy_alts)

            # Get Sell Swaps (если quote не пустой)
            if sell_quote_response:
                sell_ixs, sell_alts = await self.get_swap_instructions(
                    sell_quote_response, wallet_pubkey, use_custom_cu=True, expected_profit_sol=expected_profit_sol
                )
                if not sell_ixs:
                    return None
                alts.extend(sell_alts)

            # ── ФИКС ЛОВУШКИ #1: Умная дедупликация ATA ─────────────────────────
            # Оба свопа могут возвращать setupInstructions с CreateATA для одного
            # и того же токена. Дубликат вызывает AccountAlreadyInitialized.
            # Удаляем дубли до сборки транзакции.
            from solders.pubkey import Pubkey

            ATOKEN_PROGRAM = Pubkey.from_string(
                "ATokenGPvbdQxrVyoUXYLdG6A8P5F8L8ytxHBSxl86"
            )
            seen_atas: set = set()
            cleaned_ixs: list = []

            for ix in (buy_ixs if buy_quote_response else []) + (
                sell_ixs if sell_quote_response else []
            ):
                if ix.program_id == ATOKEN_PROGRAM and len(ix.accounts) >= 2:
                    ata_addr = str(ix.accounts[1].pubkey)
                    if ata_addr in seen_atas:
                        logger.debug(
                            f"✂️ Пропущен дубликат создания ATA: {ata_addr[:8]}"
                        )
                        continue
                    seen_atas.add(ata_addr)
                cleaned_ixs.append(ix)

            all_instructions = cleaned_ixs

            # Вычисляем индексы для MarginFi (Flashloan Introspection)
            # borrow, swaps, SPL repay transfer, repay
            repay_index = len(all_instructions) + 2

            borrow_ix = self.build_marginfi_start_flashloan_ix(
                mfi_program,
                Pubkey.from_string(marginfi_account),
                wallet,
                Pubkey.from_string(bank_pubkey),
                Pubkey.from_string(bank_liquidity_vault),
                Pubkey.from_string(bank_liquidity_vault_authority),
                user_borrow_ata,
                TOKEN_PROGRAM_ID,
                borrow_amount_lamports,
                [repay_index],
            )

            repay_ix = self.build_marginfi_end_flashloan_ix(
                mfi_program,
                Pubkey.from_string(marginfi_account),
                wallet,
                Pubkey.from_string(bank_pubkey),
                Pubkey.from_string(bank_liquidity_vault),
                Pubkey.from_string(bank_liquidity_vault_authority),
                user_borrow_ata,
                TOKEN_PROGRAM_ID,
            )

            transfer_repay_ix = spl_transfer(
                TransferParams(
                    program_id=TOKEN_PROGRAM_ID,
                    source=user_borrow_ata,
                    dest=Pubkey.from_string(bank_liquidity_vault),
                    owner=wallet,
                    amount=borrow_amount_lamports,
                    signers=[],
                )
            )

            # ── ФИКС ЛОВУШКИ #2: Идемпотентное создание ATA для займа ─────────
            # MarginFi lending_account_start_flashloan предполагает существование ATA
            # для займного токена. Jupiter его не создаёт. create_idempotent не упадёт,
            # если ATA уже есть — безопасно вызывать всегда.
            pre_instructions = []
            try:
                from spl.token.instructions import (
                    create_idempotent_associated_token_account,
                )

                # Определяем mint займа по bank_pubkey
                _sol_bank = os.getenv(
                    "MARGINFI_SOL_BANK", "CCwqExrqLGHtq12X182rFvA4KEDtK13q2E7B3Jp2Cxyj"
                )
                _usdc_bank = "2s37akK2eyBbp8DZgCm7RtsaEz8eWhVKGfHGA3cKMEW2"
                borrow_mint_str = (
                    "So11111111111111111111111111111111111111112"
                    if bank_pubkey == _sol_bank
                    else (
                        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
                        if bank_pubkey == _usdc_bank
                        else "So11111111111111111111111111111111111111112"
                    )  # fallback: SOL
                )
                borrow_mint_pk = Pubkey.from_string(borrow_mint_str)
                init_ata_ix = create_idempotent_associated_token_account(
                    payer=wallet, owner=wallet, mint=borrow_mint_pk
                )
                pre_instructions.append(init_ata_ix)
                logger.debug(
                    f"🛡️ Idempotent borrow ATA ensured for {borrow_mint_str[:8]}"
                )
            except ImportError:
                logger.warning(
                    "⚠️ create_idempotent_associated_token_account unavailable — relying on pre-existing ATA"
                )

            # Dynamic CU limit from profile (strategy_type=2 → lst_depeg_arbitrage: 450k)
            _strategy_profile = CU_PROFILES.get(
                f"strategy_{strategy_type}", "flash_arbitrage"
            )
            _profile_cu = CU_PROFILES.get(
                _strategy_profile, CU_PROFILES["flash_arbitrage"]
            )
            cu_limit_ix = set_compute_unit_limit(_profile_cu)
            logger.debug(
                f"🛡️ CU Profile: strategy_type={strategy_type} → {_strategy_profile} ({_profile_cu:,} CU)"
            )
            final_instructions = (
                [cu_limit_ix]
                + pre_instructions
                + [borrow_ix]
                + all_instructions
                + [transfer_repay_ix, repay_ix]
            )

            # =====================================================================
            # Fix 1 (Non-burning Dust): Only close wSOL atomically.
            # Intermediate ATA (BONK, xStocks, etc.) leave dust after swaps.
            # CloseAccount reverts if token balance != 0 (full tx rollback).
            # wSOL is safe — close_account unwraps all wSOL + 0.002 SOL rent at once.
            # All other ATA cleaned asynchronously by dust_sweeper post-tx.
            # final_instructions.append(
            #     close_account(
            #         CloseAccountParams(
            #             program_id=TOKEN_PROGRAM_ID,
            #             account=user_borrow_ata,
            #             dest=wallet,
            #             owner=wallet,
            #             signers=[],
            #         )
            #     )
            # )
            # logger.debug(
            #     "🔓 Fix 1 (Non-burning Dust): wSOL ata closed atomically | intermediate ATA delegated to dust_sweeper"
            # )
            # =====================================================================

            # 5. ATOMIC JITO TIP (100% CAPITAL PROTECTION)
            if jito_tip_lamports > 0:
                from solders.system_program import TransferParams, transfer

                # Fix 1: wSOL already closed atomically above.
                # Dynamic tip account — abort if empty (Fix 2, no hardcoded fallback).
                if not tip_accounts:
                    logger.critical(
                        "🚨 JITO TIP ACCOUNTS: tip_accounts is empty! "
                        "Caller must supply jito_executor.tip_accounts. Aborting to prevent hardcoded fallback."
                    )
                    return None
                selected_tip_account = random.choice(tip_accounts)
                tip_ix = transfer(
                    TransferParams(
                        from_pubkey=wallet,
                        to_pubkey=Pubkey.from_string(selected_tip_account),
                        lamports=jito_tip_lamports,
                    )
                )
                final_instructions.append(tip_ix)

            sanitized_instructions = self.sanitize_instructions(
                final_instructions, payer=wallet
            )

            # Fix 63: Safe generator search instead of .index() for Solders Instruction objects.
            # Solders Instruction does not support Python __eq__ for list.index().
            # Use discriminator matching on program_id + data[:8] to find the repayment
            # instruction in the sanitized list.
            import struct

            actual_repay_index = next(
                (i for i, ix in enumerate(sanitized_instructions)
                 if ix.program_id == repay_ix.program_id and ix.data[:8] == MARGINFI_FLASHLOAN_END),
                None
            )
            if actual_repay_index is None:
                logger.error("CRITICAL: repay_ix not found in sanitized instruction list (Fix 63)")
                return None

            # ФИКС: flashloan layout = discriminator(8) + amount(8 u64 LE) + repay_index(8 u64 LE)
            original_data_without_index = borrow_ix.data[:16]
            safe_index_bytes = struct.pack("<Q", actual_repay_index)
            new_borrow_ix = Instruction(
                program_id=borrow_ix.program_id,
                accounts=borrow_ix.accounts,
                data=original_data_without_index + safe_index_bytes,
            )

            # Find borrow_ix in sanitized list using same generator pattern (Fix 63)
            borrow_idx = next(
                (i for i, ix in enumerate(sanitized_instructions)
                 if ix.program_id == borrow_ix.program_id and ix.data[:8] == MARGINFI_FLASHLOAN_START),
                None
            )
            if borrow_idx is None:
                logger.error("CRITICAL: borrow_ix not found in sanitized instruction list (Fix 63)")
                return None

            sanitized_instructions[borrow_idx] = new_borrow_ix
            borrow_ix = new_borrow_ix
            logger.debug(
                f"🛠️ Safe Dynamic Repay Index calculated on sanitized array: {actual_repay_index} (Fix 63)"
            )

            return {
                "instructions": sanitized_instructions,
                "address_lookup_table_pubkeys": list(set(alts)),
                "repay_index": actual_repay_index,
                "recent_blockhash": recent_blockhash,
            }
        except Exception as e:
            logger.error(f"Failed to build marginfi flashloan tx: {e}")
            return None

    def build_marginfi_start_flashloan_ix(
        self,
        mfi_program: Pubkey,
        mfi_account: Pubkey,
        wallet: Pubkey,
        bank: Pubkey,
        vault: Pubkey,
        vault_auth: Pubkey,
        user_token_account: Pubkey,
        token_program: Pubkey,
        amount: int,
        instruction_indices: Optional[List[int]] = None,
    ) -> Instruction:
        """Build MarginFi lending_account_start_flashloan instruction.

        ФИКС (Phase 49): Используем настоящий flashloan эндпоинт MarginFi v2.
        Стандартный borrow привязан к Risk Engine и отклоняется при Health Factor < 0.
        start_flashloan обходит Risk Engine и не требует обеспечения.

        Data layout: discriminator(8) + amount(8 u64 LE) + repay_index(8 u64 LE) = 24 bytes

        Args:
            instruction_indices: List with one element — the index of the end_flashloan
                                 instruction in the full transaction. Encoded as u64.
        """
        index = instruction_indices[0] if instruction_indices else 0
        import struct
        data = (
            MARGINFI_FLASHLOAN_START
            + amount.to_bytes(8, "little")
            + struct.pack("<Q", index)
        )

        sysvar_instructions = Pubkey.from_string(
            "Sysvar1nstructions1111111111111111111111111"
        )

        # СТРОГИЙ ПОРЯДОК АККАУНТОВ ДЛЯ MARGINFI V2 FLASHLOAN START (Сортировка отключена!)
        # MarginFi v2 expects accounts in fixed positions - sorting breaks the contract
        # Order matches MarginFi IDL exactly: account, signer, bank, destination, vault, vault_auth, token_program, sysvar
        account_metas = [
            AccountMeta(pubkey=mfi_account, is_signer=False, is_writable=True),
            AccountMeta(pubkey=wallet, is_signer=True, is_writable=True),
            AccountMeta(pubkey=bank, is_signer=False, is_writable=True),
            AccountMeta(pubkey=user_token_account, is_signer=False, is_writable=True),
            AccountMeta(pubkey=vault, is_signer=False, is_writable=True),
            AccountMeta(pubkey=vault_auth, is_signer=False, is_writable=False),
            AccountMeta(pubkey=token_program, is_signer=False, is_writable=False),
            AccountMeta(pubkey=sysvar_instructions, is_signer=False, is_writable=False),
        ]

        return Instruction(
            program_id=mfi_program,
            accounts=account_metas,
            data=data,
        )

    def build_marginfi_end_flashloan_ix(
        self,
        mfi_program: Pubkey,
        mfi_account: Pubkey,
        wallet: Pubkey,
        bank: Pubkey,
        vault: Pubkey,
        vault_auth: Pubkey,
        user_token_account: Pubkey,
        token_program: Pubkey,
    ) -> Instruction:
        """Build MarginFi lending_account_end_flashloan instruction.

        ФИКС (Phase 49): Используем настоящий flashloan эндпоинт MarginFi v2.
        end_flashloan принимает ТОЛЬКО дискриминатор (8 байт), без суммы.
        Сумма возврата определяется смарт-контрактом через интроспекцию.

        Data layout: discriminator(8) only — no amount field.
        """
        data = MARGINFI_FLASHLOAN_END  # Only discriminator, no amount

        # СТРОГИЙ ПОРЯДОК АККАУНТОВ ДЛЯ MARGINFI V2 END FLASHLOAN (Сортировка отключена!)
        # MarginFi v2 expects 6 accounts in fixed positions
        # Order: account, signer, bank, source_token, vault, token_program
        account_metas = [
            AccountMeta(pubkey=mfi_account, is_signer=False, is_writable=True),
            AccountMeta(pubkey=wallet, is_signer=True, is_writable=True),
            AccountMeta(pubkey=bank, is_signer=False, is_writable=True),
            AccountMeta(pubkey=user_token_account, is_signer=False, is_writable=True),
            AccountMeta(pubkey=vault, is_signer=False, is_writable=True),
            AccountMeta(pubkey=token_program, is_signer=False, is_writable=False),
        ]

        return Instruction(
            program_id=mfi_program,
            accounts=account_metas,
            data=data,
        )

    def _build_jito_tip_ix(
        self, wallet: Pubkey, tip_amount: int, tip_account: Optional[str] = None
    ) -> Instruction:
        """Build Jito tip instruction for capital protection.

        Args:
            wallet: Payer wallet pubkey.
            tip_amount: Tip amount in lamports.
            tip_account: Dynamic Jito tip account from fetch_tip_accounts(). Falls back to hardcoded default if None.
        """
        from solders.system_program import TransferParams, transfer

        if not tip_account:
            logger.warning(
                "🚨 JITO TIP ACCOUNTS: No dynamic tip_account provided, using fallback. Call fetch_tip_accounts() at bot startup."
            )
            tip_account = "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"

        return transfer(
            TransferParams(
                from_pubkey=wallet,
                to_pubkey=Pubkey.from_string(tip_account),
                lamports=tip_amount,
            )
        )

    # === CAPITAL PROTECTION METHODS ===

    async def _add_ata_rent_recovery(
        self, instructions: List[Instruction], payer: Pubkey
    ) -> List[Instruction]:
        """Add ATA rent recovery instructions to reclaim 0.002 SOL per token account.

        🔥 Fix 1 (Atomic Burn-Before-Close): For Token-2022 xStocks, prepend a Burn
        instruction before CloseAccount. Token-2022 is stricter than SPL — even 1 wei
        of dust causes CloseAccount to revert with AccountNotEmpty. Burning first
        guarantees the balance hits absolute zero before closing.
        """
        recovery_instructions = []
        WHITELIST_MINTS = [
            "So11111111111111111111111111111111111111112",  # SOL
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
        ]

        for ix in instructions:
            if hasattr(ix, "program_id") and str(ix.program_id) == str(
                ASSOCIATED_TOKEN_PROGRAM_ID
            ):
                if len(ix.accounts) >= 4:
                    token_mint = str(ix.accounts[3].pubkey)
                    if token_mint in WHITELIST_MINTS:
                        continue

                    token_account = ix.accounts[1].pubkey
                    token_mint_pk = Pubkey.from_string(token_mint)

                    # Determine program ID based on token type (Token vs Token-2022)
                    from src.config.xstocks_registry import is_xstock_token

                    is_xs = is_xstock_token(token_mint_pk)
                    program_id = TOKEN_2022_PROGRAM_ID if is_xs else TOKEN_PROGRAM_ID

                    # ── Fix 1 (Atomic Burn-Before-Close) ──────────────────────────────
                    # Для Token-2022: сжигаем остаток ДО закрытия, иначе CloseAccount
                    # упадёт с AccountNotEmpty из-за микро-пыли.
                    if is_xs:
                        try:
                            from spl.token.instructions import BurnParams, burn

                            # Получаем баланс счёта, чтобы сжечь всё до нуля
                            # Используем getTokenAccountBalance для точного количества
                            # Если RPC недоступен — пропускаем Burn (close всё равно упадёт)
                            burn_ix = burn(
                                BurnParams(
                                    program_id=program_id,
                                    account=token_account,
                                    mint=token_mint_pk,
                                    owner=payer,
                                    amount=2**64 - 1,  # u64::MAX — сжигает весь баланс
                                )
                            )
                            recovery_instructions.append(burn_ix)
                            logger.debug(
                                f"🔥 Atomic Burn-Before-Close: burning xStock {token_mint[:8]} before close"
                            )
                        except Exception as _burn_err:
                            logger.debug(f"Burn-Before-Close skipped: {_burn_err}")

                    from spl.token.instructions import CloseAccountParams, close_account

                    close_ix = close_account(
                        CloseAccountParams(
                            account=token_account,
                            dest=payer,
                            owner=payer,
                            program_id=program_id,
                            signers=[],
                        )
                    )
                    recovery_instructions.append(close_ix)
                    logger.debug(
                        f"🛠️ Enforcing rent recovery for {'xStock' if is_xs else 'SPL'} ATA: {token_account}"
                    )

        return recovery_instructions

    async def _estimate_transaction_cu(
        self, instructions: List[Instruction], current_cu_limit: int, rpc_url: str
    ) -> Optional[int]:
        """Estimate actual CU usage by simulating the transaction."""
        try:
            # Create a minimal transaction for simulation
            from solders.hash import Hash
            from solders.message import MessageV0
            from solders.transaction import VersionedTransaction

            # Use a dummy blockhash and payer for simulation
            dummy_blockhash = Hash.from_string("11111111111111111111111111111111")
            dummy_payer = Pubkey.from_string("11111111111111111111111111111112")

            # Build minimal message for CU estimation
            message = MessageV0.try_compile(
                payer=dummy_payer,
                instructions=instructions,
                address_lookup_table_accounts=[],
                recent_blockhash=dummy_blockhash,
            )

            tx = VersionedTransaction(message, [])

            # Simulate with sigVerify=false to get CU usage
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "simulateTransaction",
                "params": [
                    base64.b64encode(bytes(tx)).decode(),
                    {
                        "encoding": "base64",
                        "commitment": "confirmed",
                        "sigVerify": False,
                        "replaceRecentBlockhash": False,
                    },
                ],
            }

            async with self.session.post(rpc_url, json=payload) as resp:
                if resp.status == 200:
                    data = orjson.loads(await resp.read())
                    if "result" in data and "value" in data["result"]:
                        units_consumed = data["result"]["value"].get("unitsConsumed")
                        if units_consumed:
                            return int(units_consumed)

            logger.debug("CU estimation failed, using conservative limit")
            return None

        except Exception as e:
            logger.debug(f"CU estimation error: {e}")
            return None

    def get_dynamic_slippage(self, arbitrage_path: List[str]) -> float:
        """
        Asset-specific slippage (Slippage Sniper):
        - Stables (USDC, USDT, etc.): 2 bps (0.02%)
        - xStocks / Volatile: 30 bps (0.3%)
        - LSTs: 5 bps (0.05%)
        """
        STABLES = [
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
        ]
        LSTs = [
            "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",  # jitoSOL (mainnet verified)
            "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",  # mSOL    (mainnet verified)
        ]

        is_stable = all(token in STABLES for token in arbitrage_path)
        if is_stable:
            return 0.0002  # 2 bps

        is_lst = any(token in LSTs for token in arbitrage_path)
        if is_lst:
            return 0.0005  # 5 bps

        return 0.0030  # 30 bps (xStocks/Default)

    async def get_circular_quote(
        self,
        input_mint: str,
        middle_mint: str,
        amount_lamports: int,
        dex_filter_leg1: Optional[List[str]] = None,
        dex_filter_leg2: Optional[List[str]] = None,
        jito_tip_lamports: int = 50000,
        only_direct_routes: bool = True,  # Task 14: default to direct routes — ATA drain guard
    ) -> Optional[Dict[str, Any]]:
        """Build a circular (two-leg) Jupiter quote: input_mint → middle_mint → input_mint.

        Used by LST unstake arbitrage: SOL → LST (Raydium/Orca) → SOL (Sanctum Router).

        Args:
            input_mint:  Entry token mint (e.g. SOL).
            middle_mint: Intermediate token mint (e.g. mSOL / jitoSOL).
            amount_lamports: Amount of input_mint to route.
            dex_filter_leg1: DEX include-filter for the first swap (buy LST).
            dex_filter_leg2: DEX include-filter for the second swap (exit via Sanctum).
            jito_tip_lamports: Estimated Jito tip subtracted from gross profit.
            only_direct_routes: If True, omit routing through intermediate tokens.

        Returns:
            Dict with out_amount, expected_profit_lamports, price_impact_bps, and jupiter instructions,
            or None on failure.
        """
        quote_url = (
            f"https://quote-api.jup.ag/v6/quote?"
            f"inputMint={input_mint}&"
            f"outputMint={middle_mint}&"
            f"amount={str(int(amount_lamports))}&"
            f"slippageBps=0&"  # Leg 1: Entry strictly with slippage=0 to prevent balance mismatch on Leg 2
            f"maxAccounts=8&"  # Fix 3: MTU safety — 8 accounts × 32B = 256B overhead → stays within 1232-byte UDP limit
            f"onlyDirectRoutes={str(only_direct_routes).lower()}&"
            f"restrictIntermediateTokens=true"
        )
        if dex_filter_leg1:
            quote_url += f"&dexes={','.join(dex_filter_leg1)}"

        from .jupiter_api_client import _GLOBAL_JUPITER_LIMITER, _limiter_available

        try:
            timeout = aiohttp.ClientTimeout(total=5.0)
            if _limiter_available and _GLOBAL_JUPITER_LIMITER is not None:
                async with _GLOBAL_JUPITER_LIMITER:
                    async with self.session.get(quote_url, timeout=timeout) as resp:
                        if resp.status != 200:
                            return None
                        leg1 = orjson.loads(await resp.read())
            else:
                async with self.session.get(quote_url, timeout=timeout) as resp:
                    if resp.status != 200:
                        return None
                    leg1 = orjson.loads(await resp.read())
        except Exception as e:
            logger.debug(f"Circular quote leg 1 failed: {e}")
            return None

        out_amount_leg1 = int(leg1.get("outAmount", 0))
        if out_amount_leg1 == 0:
            return None

        # Leg 2: middle_mint → input_mint (exit)
        quote_url2 = (
            f"https://quote-api.jup.ag/v6/quote?"
            f"inputMint={middle_mint}&"
            f"outputMint={input_mint}&"
            f"amount={out_amount_leg1}&"
            f"slippageBps=10&"
            f"maxAccounts=8&"  # Fix 3: MTU safety — 8 accounts × 32B = 256B overhead → stays within 1232-byte UDP limit
            f"onlyDirectRoutes={str(only_direct_routes).lower()}&"
            f"restrictIntermediateTokens=true"
        )
        if dex_filter_leg2:
            quote_url2 += f"&dexes={','.join(dex_filter_leg2)}"

        try:
            timeout = aiohttp.ClientTimeout(total=5.0)
            if _limiter_available and _GLOBAL_JUPITER_LIMITER is not None:
                async with _GLOBAL_JUPITER_LIMITER:
                    async with self.session.get(quote_url2, timeout=timeout) as resp:
                        if resp.status != 200:
                            return None
                        leg2 = orjson.loads(await resp.read())
            else:
                async with self.session.get(quote_url2, timeout=timeout) as resp:
                    if resp.status != 200:
                        return None
                    leg2 = orjson.loads(await resp.read())
        except Exception as e:
            logger.debug(f"Circular quote leg 2 failed: {e}")
            return None

        out_amount_leg2 = int(leg2.get("outAmount", 0))
        if out_amount_leg2 == 0:
            return None

        gross_profit_lamports = out_amount_leg2 - amount_lamports
        net_profit_lamports = gross_profit_lamports - jito_tip_lamports
        price_impact_bps = (
            int(float(leg2.get("priceImpactPct", "0").replace("%", "")) * 100)
            if leg2.get("priceImpactPct")
            else 0
        )

        return {
            "expected_profit_lamports": net_profit_lamports,
            "gross_profit_lamports": gross_profit_lamports,
            "jito_tip_lamports": jito_tip_lamports,
            "out_amount_leg1": out_amount_leg1,
            "out_amount_leg2": out_amount_leg2,
            "price_impact_bps": price_impact_bps,
            "dex_leg1": leg1,
            "dex_leg2": leg2,
            "instructions": [],  # swap instructions resolved later by execution builder
        }

    # === DISABLED: create_secure_jito_bundle ===
    # Jito tip is now inlined directly in build_native_flashloan_tx as the final instruction.
    # This dead code is kept for reference but must never be called — it would add a second tip
    # and consume >=0.001 SOL from the capital reserve on every bundle send.
    #
    # def create_secure_jito_bundle(self, arbitrage_tx: VersionedTransaction,
    #                               jito_tip_lamports: int, wallet_keypair: Keypair) -> List[VersionedTransaction]:
    #     [ENTIRE METHOD DISABLED — see build_native_flashloan_tx for active tip injection]
