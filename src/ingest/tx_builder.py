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
import struct
import urllib.parse
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
from solders.signature import Signature
from spl.token.instructions import (
    get_associated_token_address,
    create_associated_token_account,
    TransferParams,
    transfer as spl_transfer,
)
try:
    from spl.token.instructions import create_idempotent_associated_token_account

    CREATE_ATA_FUNCTION = create_idempotent_associated_token_account
except ImportError:
    CREATE_ATA_FUNCTION = create_associated_token_account
    logger.warning("create_idempotent_associated_token_account not available")
from spl.token.constants import TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID
from solders.system_program import ID as SYSTEM_PROGRAM_ID

# AToken Program ID constant for ATA detection
ATOKEN_PROGRAM = str(ASSOCIATED_TOKEN_PROGRAM_ID)
# MarginFi Program ID - loaded from environment with default
MARGINFI_PROGRAM_ID = Pubkey.from_string(
    os.getenv("MARGINFI_PROGRAM_ID", "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA")
)
MARGINFI_GROUP = Pubkey.from_string("4qp6Fx6tnZkY5Wropq9wUYgtFxXKwE6viZxFHg3rdAG8")
# Pre-computed SPL Token program discriminators (avoids hashlib.sha256 in hot path)
SYNC_NATIVE_DISCRIMINATOR = bytes([0x11])
CLOSE_ACCOUNT_DISCRIMINATOR = bytes([0x09])

# Kamino Lending flashloan discriminators
KAMINO_PROGRAM_ID = Pubkey.from_string("KLend2g3cP87fffoy8q1mQqGKjrxjC8bojiCLxnsfmk")
KAMINO_FLASH_BORROW = hashlib.sha256(
    b"global:flash_borrow_reserve_liquidity"
).digest()[:8]
KAMINO_FLASH_REPAY = hashlib.sha256(
    b"global:flash_repay_reserve_liquidity"
).digest()[:8]

# ── Task 14: Token-2022 Transfer Hook Account Registry ──────────────────
# Tracks remaining_accounts injected into swap instructions so that
# sanitize_instructions() and build_native_flashloan_tx() can validate
# they survive the full instruction pipeline.
# Structure: {id(instruction): injected_count}
_REMAINING_ACCOUNTS_REGISTRY: Dict[int, int] = {}

# Jupiter v6 and Raydium AMM v4 program IDs
JUPITER_V6_PROGRAM_ID = Pubkey.from_string("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4")  # True Jupiter v6
RAYDIUM_AMM_V4_PROGRAM_ID = Pubkey.from_string("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")  # Raydium AMM v4
COMPUTE_BUDGET_PROGRAM_ID = Pubkey.from_string(
    "ComputeBudget111111111111111111111111111111"
)

INSTRUCTIONS_SYSVAR = Pubkey.from_string(
    "Sysvar1nstructions1111111111111111111111111"
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


def redact_url(url: str) -> str:
    """Redact API keys from URLs for safe logging."""
    if not url:
        return url
    try:
        parsed = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        redacted = False
        for sensitive_key in {"api-key", "apikey", "api_key", "token", "key"}:
            if sensitive_key in query_params:
                query_params[sensitive_key] = ["[REDACTED]"]
                redacted = True
        if redacted:
            new_query = urllib.parse.urlencode(query_params, doseq=True)
            return urllib.parse.urlunparse(
                (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment)
            )
        return url
    except Exception:
        return url


def get_anchor_discriminator(instruction_name: str) -> bytes:
    """Dynamically calculates the 8-byte Anchor discriminator."""
    return hashlib.sha256(f"global:{instruction_name}".encode("utf-8")).digest()[:8]


# MarginFi Flashloan Discriminators - dynamically computed (Phase 49)
MARGINFI_FLASHLOAN_START = get_anchor_discriminator("lending_account_start_flashloan")
MARGINFI_FLASHLOAN_END = get_anchor_discriminator("lending_account_end_flashloan")
MARGINFI_WITHDRAW = get_anchor_discriminator("lending_account_withdraw")
MARGINFI_REPAY = get_anchor_discriminator("lending_account_repay")

# CU Profiles — single source of truth for all compute unit limits (P0 Priority)
# Replace every hardcoded set_compute_unit_limit(600000) / (300000) / etc.
# with a lookup from this dict so the bot only pays for units it actually uses.
CU_PROFILES: Dict[str, int] = {
    "stables_swap": 80_000,  # USDC/USDT 2-leg Jupiter swap
    "lst_depeg_arbitrage": 450_000,  # LST ↔ SOL via Sanctum multi-hop
    "flash_loan_pivot": 600_000,  # Flashloan + Jupiter swaps + SOL/USDC pivot
    "flash_arbitrage": 600_000,  # Full native flashloan with complex routing
    "liquidator": 400_000,  # Kamino/Native liquidation
    "default": 200_000,  # Conservative default
    # strategy_type → profile key mapping
    "strategy_1": "flash_arbitrage",
    "strategy_2": "lst_depeg_arbitrage",
}

SWAP_INSTRUCTIONS_API_URL = os.getenv(
    "SWAP_INSTRUCTIONS_API_URL", "https://api.jup.ag/swap/v1/swap-instructions"
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
            return 0  # Fallback: skip sentinel (TX will be aborted to prevent MicroFee trap)

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

                            # ── Phase 8: Cost Accounting — Priority Fee Floor & Cap ──
                            # Budget: 0.015 SOL starting capital. We cannot afford high network fees.
                            # Dynamic Threshold: 5% of expected profit.
                            # If exceeded, return 0 (skip sentinel) to abort the trade entirely
                            # rather than paying a fee that eats all profit.
                            # Strict floor: 5000 micro-lamports for Jito/Helius reliability.
                            dynamic_cap_sol = max(expected_profit_sol * 0.05, 0.00001)
                            max_micro_lamports = int(
                                (dynamic_cap_sol * 1e9) / cu_limit * 1e6
                            )
                            min_viable_micro_lamports = 5000  # Phase 8: Jito/Helius reliability minimum

                            if priority_fee > max_micro_lamports:
                                logger.warning(
                                    f"⚠️ PRIORITY FEE SATURATION: {priority_fee} µ-lamports "
                                    f"exceeds {dynamic_cap_sol:.6f} SOL (5% profit cap). "
                                    f"Returning 0 (skip sentinel) to protect capital."
                                )
                                return 0  # Phase 8: 0 = skip sentinel, caller will abort

                            final_fee = min(priority_fee, max_micro_lamports)
                            logger.debug(
                                f"Dynamic priority fee: {final_fee} micro-lamports"
                            )
                            return max(final_fee, min_viable_micro_lamports)  # Minimum 5000 micro-lamport floor
                else:
                    logger.warning(
                        f"Priority fee request failed with status {resp.status}"
                    )

        except Exception as e:
            logger.warning(f"Dynamic priority fee estimation failed: {e}")

        return 0  # Fallback: skip sentinel (TX will be aborted to prevent MicroFee trap)

    async def build_optimized_transaction(
        self,
        instructions: List[Instruction],
        address_lookup_tables: List,
        payer: Pubkey,
        recent_blockhash: str,
        program_id: str = str(JUPITER_V6_PROGRAM_ID),
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
        _operation_profile_map = {
            "flash_arbitrage": "flash_arbitrage",
            "lst_arbitrage": "lst_depeg_arbitrage",
            "stables_swap": "stables_swap",
            "swap": "stables_swap",
            "default": "default",
        }
        _profile_key = _operation_profile_map.get(operation_type, operation_type)

        profile_cu = CU_PROFILES.get(_profile_key, CU_PROFILES["default"])
        cu_limit = profile_cu

        # СТРОГИЙ ФИЛЬТР ЛОКАЛЬНЫХ РЫНКОВ (Защита от переплаты за газ)
        # Исключаем системные программы, сисвары и всё, что read-only.
        # Нам интересна конкуренция только за пулы (writable state).
        writable_accounts = set()
        for ix in instructions:
            for meta in ix.accounts:
                if meta.is_writable:  # Берем ТОЛЬКО изменяемые аккаунты
                    writable_accounts.add(str(meta.pubkey))

        # Дополнительно удаляем свой кошелек (за него нет конкуренции)
        writable_accounts.discard(str(payer))

        account_keys = list(writable_accounts)[:128]

        # Get priority fee
        # Минимальный пол для Priority Fee в размере 5000 микролампортов/CU даже в режиме Jito,
        # чтобы гарантировать прохождение пре-фильтров RPC-узлов для сложных транзакций (>200k CU).
        priority_fee = (
            5000
            if use_jito
            else await self.get_dynamic_priority_fee(
                rpc_url,
                expected_profit_sol=expected_profit_sol,
                cu_limit=cu_limit,
                account_keys=account_keys,
            )
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
            if not recent_blockhash:
                logger.error(
                    "🚨 Blockhash is None! Aborting TX build to prevent Rust Panic."
                )
                return None, 0, 0
            _bh = Hash.from_string(str(recent_blockhash))
            draft_msg = MessageV0.try_compile(
                payer=payer,
                instructions=final_instructions,
                address_lookup_table_accounts=safe_alts,
                recent_blockhash=_bh,
            )
            # Fix: use dummy signature for size estimation — empty [] causes Rust panic in solders
            _dummy_signature = Signature.from_bytes(bytes([0] * 64))
            draft_tx = VersionedTransaction(draft_msg, [_dummy_signature])
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
            if not recent_blockhash:
                logger.error(
                    "🚨 Blockhash is None! Aborting TX build to prevent Rust Panic."
                )
                return None, 0, 0
            _mtu_bh = Hash.from_string(str(recent_blockhash))
            _mtu_msg = MessageV0.try_compile(
                payer=payer,
                instructions=final_instructions,
                address_lookup_table_accounts=_mtu_alts,
                recent_blockhash=_mtu_bh,
            )
            # Fix: use dummy signature for MTU size estimation — empty [] causes Rust panic
            _mtu_dummy = Signature.from_bytes(bytes([0] * 64))
            _mtu_tx = VersionedTransaction(_mtu_msg, [_mtu_dummy])
            _mtu_size = len(bytes(_mtu_tx))
            if 0 < _mtu_size < 500:
                pass  # MTU padding disabled: duplicate ComputeBudget causes rejection
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
                # _padded_tx = VersionedTransaction(_padded_msg, [Keypair.from_bytes(bytes([0]*64))])
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

        if isinstance(raw_b64, str):
            padded_b64 = raw_b64 + "=" * (-len(raw_b64) % 4)
            data_bytes = base64.b64decode(padded_b64)
        elif isinstance(raw_b64, (bytes, bytearray)):
            data_bytes = bytes(raw_b64)
        else:
            raise ValueError(f"Unexpected data type in instruction: {type(raw_b64)}")

        program_id = Pubkey.from_string(ix_data["programId"])

        READ_ONLY_SYSTEM_IDS = {
            str(TOKEN_PROGRAM_ID),
            str(TOKEN_2022_PROGRAM_ID),
            str(ASSOCIATED_TOKEN_PROGRAM_ID),
            "11111111111111111111111111111111",  # System Program
            "ComputeBudget111111111111111111111111111111",  # Compute Budget
            "Sysvar1nstructions1111111111111111111111111",  # Instructions Sysvar
            "SysvarRent111111111111111111111111111111111",  # Rent Sysvar
            "SysvarC1ock111111111111111111111111111111111",  # Clock Sysvar
            str(RAYDIUM_AMM_V4_PROGRAM_ID),  # Raydium AMM v4
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

        # Task 25: Removed accounts.sort() - Solana ABI requires strict account ordering
        # The order of accounts in instructions is defined by the program's IDL/ABI.
        # Sorting breaks the expected layout and causes InvalidAccountData errors.

        return Instruction(
            program_id=program_id,
            accounts=accounts,
            data=data_bytes,
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
                "dynamicComputeUnitLimit": False,
                "cache_buster": str(time.time_ns()),
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
                1
                for ix in setup_instructions
                if ix.get("programId", "") == ATOKEN_PROGRAM
            )
            # Phase 9: unified ATA rent constant from shared_state
            from src.ingest.shared_state import ATA_RENT_SOL_SPL
            rent_cost = new_atas_needed * ATA_RENT_SOL_SPL
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
                if str(ix.program_id) == ATOKEN_PROGRAM:
                    # Task 23: Make creation idempotent by recreating Instruction (b'' or b'\x00' -> b'\x01')
                    # Cannot mutate ix.data directly - Rust structs are frozen
                    if ix.data == b"" or ix.data == b"\x00":
                        ix = Instruction(
                            program_id=ix.program_id,
                            accounts=ix.accounts,
                            data=b"\x01",
                        )
                        logger.debug(
                            "🛡️ Jupiter ATA instruction converted to Idempotent ATA"
                        )

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
            if (
                str(_raw_swap.get("programId", ""))
                == "ComputeBudget111111111111111111111111111111"
            ):
                logger.debug(
                    "✂️ Вырезан дубликат ComputeBudget из swapInstruction от Юпитера"
                )
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
            new_accounts_for_swap = list(swap_ix.accounts)
            for ra in rem_accounts:
                pk_str = ra.get("pubkey", "")
                if not pk_str or pk_str in _covered_pks:
                    continue
                is_signer = ra.get("isSigner", False)
                is_writable = ra.get("isWritable", True)
                _covered_pks.add(pk_str)
                # Task 24A: Append to list copy, then recreate Instruction (accounts are immutable)
                new_accounts_for_swap.append(
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
                old_swap_ix = swap_ix
                swap_ix = Instruction(
                    program_id=swap_ix.program_id,
                    accounts=new_accounts_for_swap,
                    data=swap_ix.data,
                )
                for i in range(len(instructions)):
                    if instructions[i] == old_swap_ix:
                        instructions[i] = swap_ix
                        break
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
            # БЛОК 15: строгая дедупликация ALT pubkeys через set() — предотвращает
            # MTU_OVERFLOW при дублировании ALTs от Jupiter для multi-hop маршрутов.
            # Когда несколько пулов возвращают одинаковые ALTs, дубликаты раздувают
            # транзакцию за пределы лимита в 1232 байта.
            alt_pubkeys = list({Pubkey.from_string(alt) for alt in raw_alts})
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
                    import src.ingest.shared_state as _ss
                    _ss.retain_background_task(asyncio.create_task(self.alt_manager.add_dynamic_alt(_pk)))
            # Non-blocking ALT validation (background task)
            if self.alt_manager:
                import src.ingest.shared_state as _ss
                _ss.retain_background_task(asyncio.create_task(self._validate_alt_accounts(alt_pubkeys)))

        return instructions, alt_pubkeys

    async def _post_swap_instructions_request(
        self, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Post request to Jupiter swap-instructions API."""
        from src.ingest.jupiter_api_client import get_swap_limiter

        for attempt in range(self.max_retries):
            try:
                headers = {"Content-Type": "application/json"}
                if os.getenv("JUPITER_API_KEY"):
                    headers["x-api-key"] = os.getenv("JUPITER_API_KEY")
                limiter = get_swap_limiter()
                if limiter is not None:
                    async with limiter:
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
                                backoff = min(10.0, (2 ** attempt) + random.uniform(0, 0.5))
                                logger.warning(
                                    f"Jupiter swap-instructions 429 on {SWAP_INSTRUCTIONS_API_URL} — backoff {backoff}s (attempt {attempt + 1})"
                                )
                                await asyncio.sleep(backoff)
                            else:
                                error_text = await response.text()
                                logger.warning(
                                    f"Swap instructions API error (attempt {attempt + 1}): {response.status} - {error_text}"
                                )

                                if attempt == self.max_retries - 1:
                                    return {
                                        "error": f"HTTP {response.status}: {error_text}"
                                    }
                else:
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
                            backoff = min(10.0, (2 ** attempt) + random.uniform(0, 0.5))
                            logger.warning(
                                f"Jupiter swap-instructions 429 on {SWAP_INSTRUCTIONS_API_URL} — backoff {backoff}s (attempt {attempt + 1})"
                            )
                            await asyncio.sleep(backoff)
                        else:
                            error_text = await response.text()
                            logger.warning(
                                f"Swap instructions API error (attempt {attempt + 1}): {response.status} - {error_text}"
                            )

                            if attempt == self.max_retries - 1:
                                return {
                                    "error": f"HTTP {response.status}: {error_text}"
                                }

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
            if JUPITER_V6_PROGRAM_ID in str(ix.program_id):
                max_depth = max(max_depth, 3)
            elif any(
                pid in str(ix.program_id)
                for pid in [
                    RAYDIUM_AMM_V4_PROGRAM_ID,
                    "9W959DqEETiGZocYWCQPaJ6sBmUzgfxXfqGeTEdp3aQP",
                ]
            ):
                max_depth = max(max_depth, 2)

        return max_depth

    async def _check_marginfi_liquidity_realtime(
        self, borrow_amount: int, vault_pubkey: str
    ) -> bool:
        """
        Phase 48: Real-time Liquidity Check via RPC with 95% Cap.
        Ensures we never attempt a trade that exceeds available bank funds.
        """
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountBalance",
                "params": [vault_pubkey],
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
                else:
                    return False  # Fail-Closed: abort if RPC response invalid
        except Exception as e:
            logger.error(f"Real-time liquidity check failed: {e}")
            return False  # Fail-Closed: abort trade if RPC unavailable

    async def get_max_marginfi_borrow(self, bank_pubkey: str) -> int:
        try:
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getTokenAccountBalance",
                "params": [str(bank_pubkey)]
            }
            async with self.session.post(self.rpc_url, json=payload) as resp:
                data = await resp.json()
                if "result" in data and "value" in data["result"]:
                    val = data["result"]["value"]
                    if isinstance(val, dict) and "amount" in val:
                        vault_lamports = int(val["amount"])
                    elif isinstance(val, (int, float)):
                        vault_lamports = int(val)
                    else:
                        return 0
                    return int(vault_lamports * 0.95)
            return 0
        except Exception as e:
            logger.error(f"CRITICAL: get_max_marginfi_borrow failed! RPC: {redact_url(self.rpc_url)} | Error: {e}")
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
                if len(ix.data) >= 1 and ix.data[:1] == SYNC_NATIVE_DISCRIMINATOR:
                    wrap_count += 1

            # Check for closeAccount instruction (wSOL unwrapping)
            if ix.program_id == Pubkey.from_string(
                "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
            ):
                # closeAccount discriminator
                if len(ix.data) >= 1 and ix.data[:1] == CLOSE_ACCOUNT_DISCRIMINATOR:
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
                "fee": 0.0005,  # 0.05% flash loan fee
                "priority": 2,
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
        # Default conservative utilization until on-chain parser is implemented
        return 0.50

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
            if provider["name"] == "Kamino":
                return await self._build_kamino_flashloan(
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
        """Build MarginFi flashloan transaction using correct MarginFi v2 lending_account instructions.

        Fix: replaces legacy spl_transfer() repay with proper withdraw_ix + repay_ix + end_ix.
        """
        try:
            borrow_amount_lamports = int(
                borrow_amount * 1_000_000_000
            )  # Assume SOL for now

            # Setup pubkeys (placeholder values, would be fetched)
            wallet = wallet_keypair.pubkey()
            mfi_program = Pubkey.from_string(
                "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"
            )
            mfi_account = Pubkey.from_string(
                "Sysvar1nstructions1111111111111111111111111"
            )  # Placeholder
            bank = Pubkey.from_string(
                "Sysvar1nstructions1111111111111111111111111"
            )  # Placeholder
            vault = Pubkey.from_string(
                "Sysvar1nstructions1111111111111111111111111"
            )  # Placeholder
            vault_auth = Pubkey.from_string(
                "Sysvar1nstructions1111111111111111111111111"
            )  # Placeholder
            sol_mint = Pubkey.from_string("So11111111111111111111111111111111111111112")
            user_sol_ata = get_associated_token_address(wallet, sol_mint)

            # Calculate repay index: [cu_limit] + [borrow, withdraw] + swaps + [repay, end]
            # Phase 18: repay_index MUST point to repay_ix (end_index - 1), NOT end_ix
            # MarginFi v2 introspection expects repay_index to point to the Repay instruction,
            # not the EndFlashloan instruction.  Pointing to end_ix causes the program to parse
            # the end-flashloan discriminator as a repay discriminator, failing with
            # FlashloanIntrospectionFailed (Error 6000+).
            repay_index = 1 + 2 + len(arbitrage_instructions) + 1  # end_ix is last (repay_index points to repay_ix = end_ix - 1)

            # Borrow instruction (Flashloan Start) - 9 accounts per MarginFi v2 IDL
            borrow_ix = self.build_marginfi_start_flashloan_ix(
                marginfi_group=MARGINFI_GROUP,
                marginfi_account=mfi_account,
                bank=bank,
                liquidity_vault=vault,
                bank_liquidity_vault_authority=vault_auth,
                token_program=TOKEN_PROGRAM_ID,
                instructions_sysvar=INSTRUCTIONS_SYSVAR,
                signer=wallet,
                fee_payer=wallet,
                bank_index=0,
                amount=borrow_amount_lamports,
                repay_index=repay_index,
            )

            # Withdraw from bank (actual token transfer) - MarginFi v2 requires this
            withdraw_ix = self.build_marginfi_withdraw_ix(
                mfi_program=mfi_program,
                mfi_group=MARGINFI_GROUP,
                mfi_account=mfi_account,
                wallet=wallet,
                bank=bank,
                user_token_account=user_sol_ata,
                vault=vault,
                vault_auth=vault_auth,
                token_program=TOKEN_PROGRAM_ID,
                amount=borrow_amount_lamports,
            )

            # Repay instruction (lending_account_repay) - properly repays the debt
            repay_ix = self.build_marginfi_repay_ix(
                mfi_program=mfi_program,
                mfi_group=MARGINFI_GROUP,
                mfi_account=mfi_account,
                wallet=wallet,
                bank=bank,
                user_token_account=user_sol_ata,
                vault=vault,
                vault_auth=vault_auth,
                token_program=TOKEN_PROGRAM_ID,
                amount=borrow_amount_lamports,
            )

            # End flashloan instruction - validates completion via introspection
            end_ix = self.build_marginfi_end_flashloan_ix(
                marginfi_group=MARGINFI_GROUP,
                marginfi_account=mfi_account,
                bank=bank,
                liquidity_vault=vault,
                bank_liquidity_vault_authority=vault_auth,
                token_program=TOKEN_PROGRAM_ID,
                instructions_sysvar=INSTRUCTIONS_SYSVAR,
                signer=wallet,
                repay_index=repay_index,
            )

            # Build CU limit instruction
            cu_limit_ix = set_compute_unit_limit(
                CU_PROFILES.get("flash_arbitrage", 600_000)
            )

            all_instructions = (
                [cu_limit_ix]
                + [borrow_ix, withdraw_ix]
                + arbitrage_instructions
                + [repay_ix, end_ix]
            )

            return {
                "instructions": all_instructions,
                "expected_output": borrow_amount_lamports,  # Placeholder
                "borrow_amount": borrow_amount_lamports,
            }

        except Exception as e:
            logger.error(f"Failed to build MarginFi flashloan: {e}")
            return None

    # Removed: _build_kamino_flashloan and _build_solend_flashloan (stubs, not implemented)

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
        # Phase 21: str() cast prevents TypeError: argument of type 'Pubkey' is not iterable
        bank_pubkey = sol_bank_id if "So111" in str(borrow_mint) else usdc_bank_id

        # Real-time Liquidity Check with 95% Cap
        if not await self._check_marginfi_liquidity_realtime(
            borrow_amount_lamports, str(marginfi_config["bank_liquidity_vault"])
        ):
            return None

        # ── 2. Setup Pubkeys ──────────────────────────────────────────
        wallet = Pubkey.from_string(wallet_pubkey)
        mfi_program = Pubkey.from_string(
            marginfi_config.get(
                "program_id", "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"
            )
        )
        # Глобальный пул аккаунтов через shared_state
        pool_acct_str = str(marginfi_config["marginfi_account"])
        mfi_account = Pubkey.from_string(pool_acct_str)
        bank = Pubkey.from_string(bank_pubkey)
        vault = Pubkey.from_string(str(marginfi_config["bank_liquidity_vault"]))
        vault_auth = Pubkey.from_string(
            str(marginfi_config["bank_liquidity_vault_authority"])
        )

        sol_mint = Pubkey.from_string(borrow_mint)

        sol_prog_id = TOKEN_PROGRAM_ID
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
        # ── ИСПРАВЛЕНИЕ: Минимальная плата за приоритет для прохождения фильтров RPC ──
        from solders.compute_budget import set_compute_unit_price

        all_instructions.append(set_compute_unit_price(5000))  # 5,000 micro-lamports

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

            wsol_mint_pk = Pubkey.from_string(
                "So11111111111111111111111111111111111111112"
            )
            wsol_ata_pk = get_associated_token_address(wallet, wsol_mint_pk)
            import src.ingest.shared_state as _ss

            # Skip create_idempotent ATA + SyncNative if wSOL ATA is already cached.
            # Saves ~1500 CU and transaction size bytes on the hot-path.
            if str(wsol_ata_pk) not in _ss.ATA_CACHE:
                # Create wSOL ATA idempotently (no-op if already exists)
                create_wsol_ata_ix = create_idempotent_associated_token_account(
                    payer=wallet, owner=wallet, mint=wsol_mint_pk
                )
                all_instructions.append(create_wsol_ata_ix)
                logger.debug(
                    f"🛡️ FIX 10: Idempotent wSOL ATA ensured for {wallet_pubkey[:8]}"
                )
                # SyncNative — ensures token program recognises native SOL in the ATA
                sync_native_ix = sync_native(
                    SyncNativeParams(program_id=TOKEN_PROGRAM_ID, account=wsol_ata_pk)
                )
                all_instructions.append(sync_native_ix)
                logger.debug(
                    f"🔄 FIX 10: SyncNative appended for wSOL ATA {str(wsol_ata_pk)[:8]}"
                )
            else:
                logger.debug(
                    f"⚡ wSOL ATA {str(wsol_ata_pk)[:8]} already cached — skipping create+sync instructions"
                )
            # Phase 9: Re-cache wSOL ATA after creation — DustSweeper._drain_wsol_ata
            # removes it from ATA_CACHE when closing wSOL, but we recreate it here.
            # Without this re-add, the next trade loop deducts 0.00204 SOL rent
            # from expected profit (phantom rent tax ~27% of 0.015 SOL capital).
            _ss.ATA_CACHE.add(str(wsol_ata_pk))
        except ImportError as _wsol_import_err:
            logger.warning(
                f"FIX 10: create_idempotent_ata / SyncNative not available, skipping: {_wsol_import_err}"
            )
        except Exception as _wsol_err:
            logger.warning(f"FIX 10: wSOL ATA setup failed (non-fatal): {_wsol_err}")
        # ═══════════════════════════════════════════════════════════════════════

        # ═══════════════════════════════════════════════════════════════════
        # БЛОК 8: Anti-Sandwich Slippage — проверка otherAmountThreshold
        # для build_native_flashloan_tx. Гарантирует, что минимальный выход
        # со свопа >= borrow_amount + jito_tip.
        # Параметр передаётся через marginfi_config["sell_quote_threshold"]
        # или проверяется на уровне caller.
        # ═══════════════════════════════════════════════════════════════════
        _sell_threshold = marginfi_config.get("sell_quote_threshold", 0)
        _required_repay = borrow_amount_lamports + jito_tip_lamports
        if _sell_threshold == 0:
            # Anti-Sandwich: the caller didn't pass a threshold, so we CANNOT verify
            # that the swap output covers the flashloan repay + tip. Block the bundle
            # rather than risk a sandwich that leaves us unable to repay.
            logger.warning(
                "🚫 БЛОК 8 [native]: sell_quote_threshold not set in marginfi_config — "
                "otherAmountThreshold check cannot be skipped (anti-sandwich). Aborting bundle."
            )
            return None
        if _sell_threshold < _required_repay:
            logger.warning(
                f"🚫 БЛОК 8 [native]: otherAmountThreshold ({_sell_threshold}) < "
                f"repay + jito_tip ({_required_repay}). Aborting bundle."
            )
            return None
        logger.debug(
            f"🛡️ БЛОК 8 [native]: otherAmountThreshold OK ({_sell_threshold} >= {_required_repay})"
        )

        # ── Flash Loan Pivot: Entry swap FIRST (wallet SOL → USDC before borrow) ──
        # This converts the wallet's native SOL into USDC so the arb can run in USDC.
        # Net effect: wallet balance (-SOL_entry + USDC_gain) + borrowed USDC = total USDC for arb
        for pv_ix in pivot_entry_ixs:
            all_instructions.append(pv_ix)
        # Removed set_compute_unit_price - will be added by build_optimized_transaction

        # 1. MarginFi Flashloan Start (9 accounts per MarginFi v2 IDL)
        end_index = len(all_instructions) + 3 + len(dex_swap_instructions) + len(exit_pivot_ixs or [])
        borrow_ix = self.build_marginfi_start_flashloan_ix(
            marginfi_group=MARGINFI_GROUP,
            marginfi_account=mfi_account,
            bank=bank,
            liquidity_vault=vault,
            bank_liquidity_vault_authority=vault_auth,
            token_program=sol_prog_id,
            instructions_sysvar=INSTRUCTIONS_SYSVAR,
            signer=wallet,
            fee_payer=wallet,
            bank_index=0,
            amount=borrow_amount_lamports,
            repay_index=end_index - 1,
        )
        all_instructions.append(borrow_ix)

        # 2. Withdraw from bank (actual token transfer) - Phase 50 MarginFi Protocol Fix
        withdraw_ix = self.build_marginfi_withdraw_ix(
            mfi_program=mfi_program,
            mfi_group=MARGINFI_GROUP,
            mfi_account=mfi_account,
            wallet=wallet,
            bank=bank,
            user_token_account=user_sol_ata,
            vault=vault,
            vault_auth=vault_auth,
            token_program=sol_prog_id,
            amount=borrow_amount_lamports,
        )
        all_instructions.append(withdraw_ix)

        # 3. DEX Swaps
        all_instructions.extend(dex_swap_instructions)

        # 4. Flash Loan Pivot — exit swap (USDC → SOL) BEFORE repay
        # При пивоте: бот занял SOL, свапнул в USDC, заработал профит в USDC,
        # свап обратно в SOL ДОЛЖЕН быть ДО возврата долга, иначе InsufficientFunds.
        for pv_ix in exit_pivot_ixs or []:
            all_instructions.append(pv_ix)

        # 5. Repay via MarginFi (updates liability state correctly) - Phase 50 Fix
        repay_ix = self.build_marginfi_repay_ix(
            mfi_program=mfi_program,
            mfi_group=MARGINFI_GROUP,
            mfi_account=mfi_account,
            wallet=wallet,
            bank=bank,
            user_token_account=user_sol_ata,
            vault=vault,
            vault_auth=vault_auth,
            token_program=sol_prog_id,
            amount=borrow_amount_lamports,
        )
        all_instructions.append(repay_ix)

        # 6. MarginFi Flashloan End (8 accounts per MarginFi v2 IDL)
        end_ix = self.build_marginfi_end_flashloan_ix(
            marginfi_group=MARGINFI_GROUP,
            marginfi_account=mfi_account,
            bank=bank,
            liquidity_vault=vault,
            bank_liquidity_vault_authority=vault_auth,
            token_program=sol_prog_id,
            instructions_sysvar=INSTRUCTIONS_SYSVAR,
            signer=wallet,
            repay_index=end_index - 1,
        )
        all_instructions.append(end_ix)

        # P0-10: Removed unconditional close_account(wsol_ata) from flashloan tx.
        # wSOL ATA closing is handled asynchronously by DustSweeper between trades.
        # CloseAccount in the middle of a flashloan reverts if Jupiter leaves 1-lamport dust.

        # ЗАЩИТА КАПИТАЛА (0.017 SOL): Чаевые Jito СТРОГО в конце единой транзакции.
        # Если DEX Swap выдаст SlippageExceeded или MarginFi Repay выдаст InsufficientFunds ->
        # вся транзакция откатывается, и перевод чаевых НЕ СРАБОТАЕТ.
        if jito_tip_lamports > 0:
            from solders.system_program import TransferParams, transfer

            # wSOL ATA closing is handled asynchronously by DustSweeper between trades.
            # CloseAccount in the middle of a flashloan reverts if Jupiter leaves 1-lamport dust.
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
                _jup_prog = str(JUPITER_V6_PROGRAM_ID)
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
            logger.debug(
                f"🔗 Task 14: {_rem_accounts_lost} instruction(s) with potential remaining_accounts issues"
            )
        # ─────────────────────────────────────────────────────────────────────

        # Find the (possibly new) indices within the sanitized list
        # so the repay_index we pack into borrow_ix.data is 100% correct.
        try:
            actual_repay_index = next(
                (
                    i
                    for i, ix in enumerate(sanitized)
                    if ix.program_id == repay_ix.program_id
                    and ix.data[:8] == MARGINFI_FLASHLOAN_END
                ),
                None,
            )
            if actual_repay_index is None:
                logger.error(
                    "CRITICAL: repay_ix not found in sanitized instruction list"
                )
                return None

            # ── БЕЗОПАСНАЯ ПЕРЕСБОРКА ДАННЫХ (discriminator 8 + bank_index 2 + amount 8 + repay_index 2) ──
            # Формат: discriminator(8) + bank_index(2 u16 LE) + amount(8 u64 LE) + repay_index(2 u16 LE)
            # reconstruct from scratch, avoiding slice mutation which loses bank_index
            import struct
            from solders.instruction import Instruction

            # Find borrow_ix in the SANITIZED list using generator (Fix 57)
            new_borrow_idx = next(
                (
                    i
                    for i, ix in enumerate(sanitized)
                    if ix.program_id == borrow_ix.program_id
                    and ix.data[:8] == MARGINFI_FLASHLOAN_START
                ),
                None,
            )
            if new_borrow_idx is None:
                logger.error(
                    "CRITICAL: borrow_ix not found in sanitized instruction list"
                )
                return None

            # Extract bank_index from original data (bytes 8-10)
            bank_index_val = struct.unpack("<H", borrow_ix.data[8:10])[0] if len(borrow_ix.data) >= 10 else 0
            # Extract amount from original data (bytes 10-18)
            amount_val = struct.unpack("<Q", borrow_ix.data[10:18])[0] if len(borrow_ix.data) >= 18 else 0

            new_data = (
                MARGINFI_FLASHLOAN_START
                + struct.pack("<H", bank_index_val)
                + struct.pack("<Q", amount_val)
                + struct.pack("<H", actual_repay_index)
            )
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
        ata_prog = ASSOCIATED_TOKEN_PROGRAM_ID
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
            str(TOKEN_PROGRAM_ID),
            str(TOKEN_2022_PROGRAM_ID),
            str(ASSOCIATED_TOKEN_PROGRAM_ID),
            "11111111111111111111111111111111",  # System Program
            "ComputeBudget111111111111111111111111111111",  # Compute Budget
            "Sysvar1nstructions1111111111111111111111111",  # Instructions Sysvar
            "SysvarRent111111111111111111111111111111111",  # Rent Sysvar
            "SysvarC1ock111111111111111111111111111111111",  # Clock Sysvar
            str(RAYDIUM_AMM_V4_PROGRAM_ID),  # Raydium AMM v4
        }

        for ix in instructions:
            # Task 22: Recreate AccountMeta objects instead of mutating immutable Rust structs
            new_accounts = []
            modified = False
            for meta in ix.accounts:
                if str(meta.pubkey) in READ_ONLY_SYSTEM_IDS:
                    if meta.is_writable:
                        new_accounts.append(
                            AccountMeta(
                                pubkey=meta.pubkey,
                                is_signer=meta.is_signer,
                                is_writable=False,
                            )
                        )
                        modified = True
                    else:
                        new_accounts.append(meta)
                else:
                    new_accounts.append(meta)

            # Use new instruction if accounts were modified, otherwise keep original
            if modified:
                ix = Instruction(
                    program_id=ix.program_id,
                    accounts=new_accounts,
                    data=ix.data,
                )

            # Phase 9: Safe ATA parsing — verify program_id is AToken AND len(accounts) >= 2
            # before accessing accounts[1].pubkey.  Jupiter may pass SystemProgram
            # instructions that look similar but would crash with IndexError.
            if (
                str(ix.program_id) == ATOKEN_PROGRAM
                and len(ix.accounts) >= 2
            ):
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
                if len(ix.data) >= 1 and ix.data[:1] == CLOSE_ACCOUNT_DISCRIMINATOR:
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
                # Task 1.2: Use vault from shared_state or derive dynamically - NOT hardcoded fallback
                from src.ingest.shared_state import MARGINFI_LIQUIDITY_VAULTS
                bank_liquidity_vault = MARGINFI_LIQUIDITY_VAULTS.get(
                    bank_pubkey, bank_pubkey
                )
                # Derive vault authority dynamically
                bank_liquidity_vault_authority = str(
                    Pubkey.from_string(
                        get_marginfi_vault_pdas(bank_pubkey)[1]
                    )
                )
                logger.debug(
                    f"🔄 Oracle Pivot: switched bank config to USDC (bank={bank_pubkey[:8]}...)"
                )

            user_borrow_ata = get_associated_token_address(wallet, borrow_mint_pubkey)

            all_instructions = []
            alts = []

            # ═══════════════════════════════════════════════════════════════════
            # БЛОК 8: Anti-Sandwich Slippage — otherAmountThreshold Guard
            # Проверяем, что минимально гарантированный выход со свопа
            # (otherAmountThreshold) покрывает repay_amount + jito_tip.
            # Если нет — отменяем отправку бандла, чтобы не попасть в
            # ситуацию, когда своп не даёт достаточно средств для возврата
            # долга MarginFi + оплаты Jito.
            # ═══════════════════════════════════════════════════════════════════
            if sell_quote_response:
                _threshold = int(sell_quote_response.get(
                    "otherAmountThreshold", sell_quote_response.get("outAmount", 0)
                ))
                _fee_buffer_lamports = 5000  # base fee
                _priority_fee_estimate_lamports = 100_000  # conservative buffer
                _required = borrow_amount_lamports + jito_tip_lamports + _fee_buffer_lamports + _priority_fee_estimate_lamports
                if _threshold < _required:
                    logger.warning(
                        f"🚫 БЛОК 8: otherAmountThreshold ({_threshold}) < "
                        f"repay_amount + jito_tip + fees ({_required}). "
                        f"Anti-Sandwich guard aborts bundle to prevent InsufficientFunds."
                    )
                    return None
                logger.debug(
                    f"🛡️ БЛОК 8: otherAmountThreshold OK ({_threshold} >= {_required})"
                )

            # Get Buy Swaps (если quote не пустой)
            if buy_quote_response:
                buy_ixs, buy_alts = await self.get_swap_instructions(
                    buy_quote_response,
                    wallet_pubkey,
                    use_custom_cu=True,
                    expected_profit_sol=expected_profit_sol,
                )
                if not buy_ixs:
                    return None
                alts.extend(buy_alts)

            # Get Sell Swaps (если quote не пустой)
            if sell_quote_response:
                sell_ixs, sell_alts = await self.get_swap_instructions(
                    sell_quote_response,
                    wallet_pubkey,
                    use_custom_cu=True,
                    expected_profit_sol=expected_profit_sol,
                )
                if not sell_ixs:
                    return None
                alts.extend(sell_alts)

            # ── ФИКС ЛОВУШКИ #1: Умная дедупликация ATA ─────────────────────────
            # Оба свопа могут возвращать setupInstructions с CreateATA для одного
            # и того же токена. Дубликат вызывает AccountAlreadyInitialized.
            # Удаляем дубли до сборки транзакции.
            from solders.pubkey import Pubkey

            seen_atas: set = set()
            cleaned_ixs: list = []

            for ix in (buy_ixs if buy_quote_response else []) + (
                sell_ixs if sell_quote_response else []
            ):
                if ix.program_id == Pubkey.from_string(ATOKEN_PROGRAM) and len(ix.accounts) >= 2:
                    ata_addr = str(ix.accounts[1].pubkey)
                    if ata_addr in seen_atas:
                        logger.debug(
                            f"✂️ Пропущен дубликат создания ATA: {ata_addr[:8]}"
                        )
                        continue
                    seen_atas.add(ata_addr)
                cleaned_ixs.append(ix)

            all_instructions = cleaned_ixs

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

            # Вычисляем индексы для MarginFi (Flashloan Introspection)
            # cu_limit, pre_instructions, borrow_ix, withdraw_ix, swaps, repay_ix, end_ix
            repay_index = len(all_instructions) + 3 + len(pre_instructions)

            borrow_ix = self.build_marginfi_start_flashloan_ix(
                marginfi_group=MARGINFI_GROUP,
                marginfi_account=Pubkey.from_string(marginfi_account),
                bank=Pubkey.from_string(bank_pubkey),
                liquidity_vault=Pubkey.from_string(bank_liquidity_vault),
                bank_liquidity_vault_authority=Pubkey.from_string(bank_liquidity_vault_authority),
                token_program=TOKEN_PROGRAM_ID,
                instructions_sysvar=INSTRUCTIONS_SYSVAR,
                signer=wallet,
                fee_payer=wallet,
                bank_index=0,
                amount=borrow_amount_lamports,
                repay_index=repay_index,
            )

            withdraw_ix = self.build_marginfi_withdraw_ix(
                mfi_program=mfi_program,
                mfi_group=MARGINFI_GROUP,
                mfi_account=Pubkey.from_string(marginfi_account),
                wallet=wallet,
                bank=Pubkey.from_string(bank_pubkey),
                user_token_account=user_borrow_ata,
                vault=Pubkey.from_string(bank_liquidity_vault),
                vault_auth=Pubkey.from_string(bank_liquidity_vault_authority),
                token_program=TOKEN_PROGRAM_ID,
                amount=borrow_amount_lamports,
            )

            repay_ix = self.build_marginfi_repay_ix(
                mfi_program=mfi_program,
                mfi_group=MARGINFI_GROUP,
                mfi_account=Pubkey.from_string(marginfi_account),
                wallet=wallet,
                bank=Pubkey.from_string(bank_pubkey),
                user_token_account=user_borrow_ata,
                vault=Pubkey.from_string(bank_liquidity_vault),
                vault_auth=Pubkey.from_string(bank_liquidity_vault_authority),
                token_program=TOKEN_PROGRAM_ID,
                amount=borrow_amount_lamports,
            )

            end_ix = self.build_marginfi_end_flashloan_ix(
                marginfi_group=MARGINFI_GROUP,
                marginfi_account=Pubkey.from_string(marginfi_account),
                bank=Pubkey.from_string(bank_pubkey),
                liquidity_vault=Pubkey.from_string(bank_liquidity_vault),
                bank_liquidity_vault_authority=Pubkey.from_string(bank_liquidity_vault_authority),
                token_program=TOKEN_PROGRAM_ID,
                instructions_sysvar=INSTRUCTIONS_SYSVAR,
                signer=wallet,
                repay_index=repay_index,
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
                + [borrow_ix, withdraw_ix]
                + all_instructions
                + [repay_ix, end_ix]
            )

            # P0-10: Removed unconditional close_account(wsol_ata) from build_marginfi_flashloan_tx.
            # wSOL ATA closing is handled asynchronously by DustSweeper between trades.

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
                (
                    i
                    for i, ix in enumerate(sanitized_instructions)
                    if ix.program_id == repay_ix.program_id
                    and ix.data[:8] == MARGINFI_FLASHLOAN_END
                ),
                None,
            )
            if actual_repay_index is None:
                logger.error(
                    "CRITICAL: repay_ix not found in sanitized instruction list (Fix 63)"
                )
                return None

            # ФИКС: flashloan layout = discriminator(8) + bank_index(2 u16 LE) + amount(8 u64 LE) + repay_index(2 u16 LE)
            # Extract bank_index (bytes 8-10) and amount (bytes 10-18) from original, repack with correct repay_index
            bank_index_val = struct.unpack("<H", borrow_ix.data[8:10])[0] if len(borrow_ix.data) >= 10 else 0
            amount_val = struct.unpack("<Q", borrow_ix.data[10:18])[0] if len(borrow_ix.data) >= 18 else 0
            new_borrow_ix = Instruction(
                program_id=borrow_ix.program_id,
                accounts=borrow_ix.accounts,
                data=(
                    MARGINFI_FLASHLOAN_START
                    + struct.pack("<H", bank_index_val)
                    + struct.pack("<Q", amount_val)
                    + struct.pack("<H", actual_repay_index)
                ),
            )

            # Find borrow_ix in sanitized list using same generator pattern (Fix 63)
            borrow_idx = next(
                (
                    i
                    for i, ix in enumerate(sanitized_instructions)
                    if ix.program_id == borrow_ix.program_id
                    and ix.data[:8] == MARGINFI_FLASHLOAN_START
                ),
                None,
            )
            if borrow_idx is None:
                logger.error(
                    "CRITICAL: borrow_ix not found in sanitized instruction list (Fix 63)"
                )
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
        marginfi_group: Pubkey,
        marginfi_account: Pubkey,
        bank: Pubkey,
        liquidity_vault: Pubkey,
        bank_liquidity_vault_authority: Pubkey,
        token_program: Pubkey,
        instructions_sysvar: Pubkey,
        signer: Pubkey,
        fee_payer: Pubkey,
        bank_index: int = 0,
        amount: int = 0,
        repay_index: int = 0,
    ) -> Instruction:
        """Build MarginFi lending_account_start_flashloan instruction.

        MarginFi v2 flashloan start instruction layout:
        - Accounts: 9 (marginfi_group, marginfi_account, bank, liquidity_vault,
          bank_liquidity_vault_authority, token_program, instructions_sysvar, signer, fee_payer)
        - Data: 20 bytes = discriminator (8) + bank_index (u16, 2) + amount (u64, 8) + repay_index (u16, 2)
        """
        data = (
            MARGINFI_FLASHLOAN_START
            + struct.pack("<H", bank_index)
            + struct.pack("<Q", amount)
            + struct.pack("<H", repay_index)
        )

        account_metas = [
            AccountMeta(pubkey=marginfi_group, is_signer=False, is_writable=False),
            AccountMeta(pubkey=marginfi_account, is_signer=False, is_writable=True),
            AccountMeta(pubkey=bank, is_signer=False, is_writable=True),
            AccountMeta(pubkey=liquidity_vault, is_signer=False, is_writable=True),
            AccountMeta(pubkey=bank_liquidity_vault_authority, is_signer=False, is_writable=False),
            AccountMeta(pubkey=token_program, is_signer=False, is_writable=False),
            AccountMeta(pubkey=instructions_sysvar, is_signer=False, is_writable=False),
            AccountMeta(pubkey=signer, is_signer=True, is_writable=True),
            AccountMeta(pubkey=fee_payer, is_signer=True, is_writable=True),
        ]

        mfi_program = Pubkey.from_string("MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA")

        return Instruction(
            program_id=mfi_program,
            accounts=account_metas,
            data=data,
        )

    def build_marginfi_end_flashloan_ix(
        self,
        marginfi_group: Pubkey,
        marginfi_account: Pubkey,
        bank: Pubkey,
        liquidity_vault: Pubkey,
        bank_liquidity_vault_authority: Pubkey,
        token_program: Pubkey,
        instructions_sysvar: Pubkey,
        signer: Pubkey,
        repay_index: int = 0,
    ) -> Instruction:
        """Build MarginFi lending_account_end_flashloan instruction.

        MarginFi v2 flashloan end instruction layout:
        - Accounts: 8 (marginfi_group, marginfi_account, bank, liquidity_vault,
          bank_liquidity_vault_authority, token_program, instructions_sysvar, signer)
        - Data: 10 bytes = discriminator (8) + repay_index (u16, 2)
        """
        data = MARGINFI_FLASHLOAN_END + struct.pack("<H", repay_index)

        account_metas = [
            AccountMeta(pubkey=marginfi_group, is_signer=False, is_writable=False),
            AccountMeta(pubkey=marginfi_account, is_signer=False, is_writable=True),
            AccountMeta(pubkey=bank, is_signer=False, is_writable=True),
            AccountMeta(pubkey=liquidity_vault, is_signer=False, is_writable=True),
            AccountMeta(pubkey=bank_liquidity_vault_authority, is_signer=False, is_writable=False),
            AccountMeta(pubkey=token_program, is_signer=False, is_writable=False),
            AccountMeta(pubkey=instructions_sysvar, is_signer=False, is_writable=False),
            AccountMeta(pubkey=signer, is_signer=True, is_writable=True),
        ]

        mfi_program = Pubkey.from_string("MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA")

        return Instruction(
            program_id=mfi_program,
            accounts=account_metas,
            data=data,
        )

    def build_marginfi_withdraw_ix(
        self,
        mfi_program: Pubkey,
        mfi_group: Pubkey,
        mfi_account: Pubkey,
        wallet: Pubkey,
        bank: Pubkey,
        user_token_account: Pubkey,
        vault: Pubkey,
        vault_auth: Pubkey,
        token_program: Pubkey,
        amount: int,
    ) -> Instruction:
        """Build MarginFi lending_account_withdraw instruction.

        Withdraws tokens from the bank to user's token account.
        This is the actual borrow step after start_flashloan.
        """
        import struct

        data = MARGINFI_WITHDRAW + amount.to_bytes(8, "little")

        account_metas = [
            AccountMeta(
                pubkey=mfi_group, is_signer=False, is_writable=False
            ),  # <-- ДОБАВИТЬ ЭТО
            AccountMeta(pubkey=mfi_account, is_signer=False, is_writable=True),
            AccountMeta(pubkey=wallet, is_signer=True, is_writable=False),
            AccountMeta(pubkey=bank, is_signer=False, is_writable=True),
            AccountMeta(pubkey=user_token_account, is_signer=False, is_writable=True),
            AccountMeta(pubkey=vault, is_signer=False, is_writable=True),
            AccountMeta(pubkey=vault_auth, is_signer=False, is_writable=False),
            AccountMeta(pubkey=token_program, is_signer=False, is_writable=False),
        ]

        return Instruction(
            program_id=mfi_program,
            accounts=account_metas,
            data=data,
        )

    def build_marginfi_repay_ix(
        self,
        mfi_program: Pubkey,
        mfi_group: Pubkey,
        mfi_account: Pubkey,
        wallet: Pubkey,
        bank: Pubkey,
        user_token_account: Pubkey,
        vault: Pubkey,
        vault_auth: Pubkey,
        token_program: Pubkey,
        amount: int,
    ) -> Instruction:
        """Build MarginFi lending_account_repay instruction.

        Repays borrowed tokens back to the bank.
        This properly updates the account's liability state.
        """
        import struct

        data = MARGINFI_REPAY + amount.to_bytes(8, "little")

        account_metas = [
            AccountMeta(
                pubkey=mfi_group, is_signer=False, is_writable=False
            ),  # <-- ДОБАВИТЬ ЭТО
            AccountMeta(pubkey=mfi_account, is_signer=False, is_writable=True),
            AccountMeta(pubkey=wallet, is_signer=True, is_writable=True),
            AccountMeta(pubkey=bank, is_signer=False, is_writable=True),
            AccountMeta(pubkey=user_token_account, is_signer=False, is_writable=True),
            AccountMeta(pubkey=vault, is_signer=False, is_writable=True),
            AccountMeta(pubkey=vault_auth, is_signer=False, is_writable=False),
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
            try:
                from src.ingest.jito_manager import JitoBiddingManager
                _jbm = JitoBiddingManager()
                tip_account = _jbm.get_random_tip_account()
            except Exception:
                logger.critical("🚨 JITO TIP ACCOUNTS: No dynamic tip_account provided and jito_manager unavailable. Aborting.")
                return None

        return transfer(
            TransferParams(
                from_pubkey=wallet,
                to_pubkey=Pubkey.from_string(tip_account),
                lamports=tip_amount,
            )
        )

    # === CAPITAL PROTECTION METHODS ===

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

            _dummy_keypair = Keypair.from_bytes(bytes([0] * 64))
            tx = VersionedTransaction(message, [_dummy_keypair])

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

        return 0.0030  # 30 bps for volatile tokens

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
        jup_quote_url = os.getenv(
            "JUPITER_QUOTE_API", "https://api.jup.ag/swap/v1/quote"
        )
        jup_key = os.getenv("JUPITER_API_KEY", "")
        jup_headers = {"Accept": "application/json"}
        if jup_key:
            jup_headers["x-api-key"] = jup_key
        quote_url = (
            f"{jup_quote_url}?"
            f"inputMint={input_mint}&"
            f"outputMint={middle_mint}&"
            f"amount={str(int(amount_lamports))}&"
            f"slippageBps=5&"
            f"onlyDirectRoutes=false&"
            f"restrictIntermediateTokens=false"
        )
        if dex_filter_leg1:
            quote_url += f"&dexes={','.join(dex_filter_leg1)}"

        from .jupiter_api_client import _GLOBAL_JUPITER_LIMITER, _limiter_available

        try:
            timeout = aiohttp.ClientTimeout(total=5.0)
            if _limiter_available and _GLOBAL_JUPITER_LIMITER is not None:
                async with _GLOBAL_JUPITER_LIMITER:
                    async with self.session.get(
                        quote_url, headers=jup_headers, timeout=timeout
                    ) as resp:
                        if resp.status != 200:
                            return None
                        leg1 = orjson.loads(await resp.read())
            else:
                async with self.session.get(
                    quote_url, headers=jup_headers, timeout=timeout
                ) as resp:
                    if resp.status != 200:
                        return None
                    leg1 = orjson.loads(await resp.read())
        except Exception as e:
            logger.debug(f"Circular quote leg 1 failed: {e}")
            return None

        out_amount_leg1 = int(leg1.get("outAmount", 0))
        if out_amount_leg1 == 0:
            return None

        quote_url2 = (
            f"{jup_quote_url}?"
            f"inputMint={middle_mint}&"
            f"outputMint={input_mint}&"
            f"amount={out_amount_leg1}&"
            f"slippageBps=10&"
            f"onlyDirectRoutes=false&"
            f"restrictIntermediateTokens=false"
        )
        if dex_filter_leg2:
            quote_url2 += f"&dexes={','.join(dex_filter_leg2)}"

        try:
            timeout = aiohttp.ClientTimeout(total=5.0)
            if _limiter_available and _GLOBAL_JUPITER_LIMITER is not None:
                async with _GLOBAL_JUPITER_LIMITER:
                    async with self.session.get(
                        quote_url2, headers=jup_headers, timeout=timeout
                    ) as resp:
                        if resp.status != 200:
                            return None
                        leg2 = orjson.loads(await resp.read())
            else:
                async with self.session.get(
                    quote_url2, headers=jup_headers, timeout=timeout
                ) as resp:
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
            "instructions": [],
        }

    async def get_three_hop_circular_quote(
        self,
        input_mint: str,
        middle_mint_1: str,
        middle_mint_2: str,
        amount_lamports: int,
        jito_tip_lamports: int = 50000,
    ) -> Optional[Dict[str, Any]]:
        """Three-hop circular quote: input -> middle_1 -> middle_2 -> input.

        Used for Wrapper Peg Arbitrage: USDC -> Cheap BTC -> Expensive BTC -> USDC.

        Returns profit in lamports (converted to SOL by caller).
        """
        jup_quote_url = os.getenv(
            "JUPITER_QUOTE_API", "https://api.jup.ag/swap/v1/quote"
        )
        jup_key = os.getenv("JUPITER_API_KEY", "")
        jup_headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        if jup_key:
            jup_headers["x-api-key"] = jup_key

        try:
            timeout = aiohttp.ClientTimeout(total=5.0)
            async with self.session.get(
                f"{jup_quote_url}?inputMint={input_mint}&outputMint={middle_mint_1}&amount={amount_lamports}&slippageBps=5",
                headers=jup_headers,
                timeout=timeout,
            ) as resp:
                if resp.status != 200:
                    return None
                leg1 = orjson.loads(await resp.read())

            out1 = int(leg1.get("outAmount", 0))
            if out1 == 0:
                return None

            async with self.session.get(
                f"{jup_quote_url}?inputMint={middle_mint_1}&outputMint={middle_mint_2}&amount={out1}&slippageBps=5",
                headers=jup_headers,
                timeout=timeout,
            ) as resp:
                if resp.status != 200:
                    return None
                leg2 = orjson.loads(await resp.read())

            out2 = int(leg2.get("outAmount", 0))
            if out2 == 0:
                return None

            async with self.session.get(
                f"{jup_quote_url}?inputMint={middle_mint_2}&outputMint={input_mint}&amount={out2}&slippageBps=10",
                headers=jup_headers,
                timeout=timeout,
            ) as resp:
                if resp.status != 200:
                    return None
                leg3 = orjson.loads(await resp.read())

            out3 = int(leg3.get("outAmount", 0))
            if out3 == 0:
                return None

            gross_profit = out3 - amount_lamports
            net_profit = gross_profit - jito_tip_lamports

            return {
                "expected_profit_lamports": net_profit,
                "gross_profit_lamports": gross_profit,
                "jito_tip_lamports": jito_tip_lamports,
                "out_amount_leg1": out1,
                "out_amount_leg2": out2,
                "out_amount_leg3": out3,
                "dex_leg1": leg1,
                "dex_leg2": leg2,
                "dex_leg3": leg3,
            }
        except Exception as e:
            logger.debug(f"Three-hop circular quote failed: {e}")
            return None

    # === DISABLED: create_secure_jito_bundle ===
    # Jito tip is now inlined directly in build_native_flashloan_tx as the final instruction.
    # This dead code is kept for reference but must never be called — it would add a second tip
    # and consume >=0.001 SOL from the capital reserve on every bundle send.
    #
    # def create_secure_jito_bundle(self, arbitrage_tx: VersionedTransaction,
    #                               jito_tip_lamports: int, wallet_keypair: Keypair) -> List[VersionedTransaction]:
    #     [ENTIRE METHOD DISABLED — see build_native_flashloan_tx for active tip injection]
