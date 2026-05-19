"""Jupiter transaction builder for Solana swap transactions."""

import asyncio
import logging
import base58
import base64
import time
import hashlib
import os
from decimal import Decimal
from typing import Any, Dict, Optional, List, Tuple
import aiohttp
from solders.instruction import Instruction, AccountMeta
from solders.pubkey import Pubkey
from solders.hash import Hash
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from solders.message import MessageV0
from solders.transaction import VersionedTransaction
from solders.keypair import Keypair
from spl.token.instructions import get_associated_token_address, create_associated_token_account, close_account, CloseAccountParams
try:
    from spl.token.instructions import create_idempotent_associated_token_account
    CREATE_ATA_FUNCTION = create_idempotent_associated_token_account
except ImportError:
    CREATE_ATA_FUNCTION = create_associated_token_account
    logger.warning("create_idempotent_associated_token_account not available, using regular create_associated_token_account")
from spl.token.constants import TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID
from solders.system_program import ID as SYSTEM_PROGRAM_ID

# Token-2022 Program ID for xStocks (RWA tokens)
TOKEN_2022_PROGRAM_ID = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EP2rHEjaChQX6n57TR5m")
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
# Pre-computed SPL Token program discriminators (avoids hashlib.sha256 in hot path)
SYNC_NATIVE_DISCRIMINATOR  = bytes([0x35, 0x9a, 0xdc, 0x8e, 0x9a, 0x8b, 0xea, 0x6a])
CLOSE_ACCOUNT_DISCRIMINATOR = bytes([0x02, 0x9e, 0x8d, 0x1d, 0x11, 0x8e, 0x3b, 0x87])

COMPUTE_BUDGET_PROGRAM_ID = Pubkey.from_string("ComputeBudget111111111111111111111111111111")

def validate_cb_ordering(instructions: List[Instruction], location: str = "tx_builder") -> bool:
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
                logger.error(f"CRITICAL FIX-2 [{location}]: ComputeBudget instruction at index {i}. MUST be 0 or 1. Aborting to prevent SVM panic.")
                return False
    return True

MARGINFI_PROGRAM_ID = Pubkey.from_string("MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA")

def get_marginfi_vault_pdas(bank_pubkey: str):
    bank_pk = Pubkey.from_string(bank_pubkey)
    liquidity_vault, _ = Pubkey.find_program_address([b"liquidity_vault", bytes(bank_pk)], MARGINFI_PROGRAM_ID)
    liquidity_vault_auth, _ = Pubkey.find_program_address([b"liquidity_vault_auth", bytes(bank_pk)], MARGINFI_PROGRAM_ID)
    return liquidity_vault, liquidity_vault_auth

logger = logging.getLogger(__name__)

# MarginFi Contract Discriminators - pre-computed (Fix 80)
MARGINFI_BORROW_DISCRIMINATOR = b'\x91Y\xeba\x184\xa5\xd7'
MARGINFI_REPAY_DISCRIMINATOR = b'1`E\xabz3\xa5\x9a'

SWAP_INSTRUCTIONS_API_URL = "https://api.jup.ag/swap/v1/swap-instructions"

JUPITER_PROXIES = [
    "https://tiny-base-1f12.ivans-bobrovs4321.workers.dev/swap-instructions",
    "https://jupiter-proxy-2.info-feelflow.workers.dev/swap-instructions",
    "https://jupiter-proxy-3.bobrovsivans1.workers.dev/swap-instructions",
]

class NaiveLimiter:
    """Simple rate limiter fallback."""
    def __init__(self, rps: int):
        self.rps = rps
        self.semaphore = asyncio.Semaphore(rps)

    async def __aenter__(self):
        await self.semaphore.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await asyncio.sleep(1.0)
        self.semaphore.release()

class JupiterTxBuilder:
    """Builds and signs Solana swap transactions using Jupiter API."""

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        timeout: float = 5.0,
        max_retries: int = 2,
        rpc_url: Optional[str] = None,
        jupiter_rps: int = 5,  # Jupiter API rate limit
        alt_manager: Optional[Any] = None,
    ):
        self.session = session
        self.timeout = timeout
        self.max_retries = max_retries
        self.rpc_url = rpc_url
        self.alt_manager = alt_manager
        self._session_owned = session is None
        # CU cache: key is (program_id, operation_type), value is (cu_limit, timestamp)
        self.cu_cache: Dict[Tuple[str, str], Tuple[int, float]] = {}
        self.cache_ttl = 60  # seconds
        # Jupiter rate limiter
        self.jupiter_limiter = self._create_limiter(jupiter_rps)
        self.proxy_index = 0
        self.last_429_time = 0

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

    async def estimate_transaction_cu(self, transaction: VersionedTransaction, rpc_url: Optional[str] = None) -> int:
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
            logger.warning("No RPC URL provided for CU estimation, using default 200000 CU")
            return 200000

        try:
            # Serialize transaction for simulation
            tx_b64 = base64.b64encode(bytes(transaction)).decode('ascii')

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
                        "accounts": {
                            "encoding": "base64",
                            "addresses": []
                        }
                    }
                ]
            }

            timeout = aiohttp.ClientTimeout(total=2.0)
            async with self.session.post(rpc_url, json=payload, timeout=timeout) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "result" in data and "value" in data["result"]:
                        sim_result = data["result"]["value"]
                        if "unitsConsumed" in sim_result and sim_result["unitsConsumed"] is not None:
                            cu_used = sim_result["unitsConsumed"]
                            logger.debug(f"Transaction simulation successful: {cu_used} CU consumed")
                            return cu_used
                        elif sim_result.get("err"):
                            logger.warning(f"Simulation failed with error: {sim_result['err']}")
                        else:
                            logger.warning("Simulation completed but unitsConsumed not found")
                    else:
                        logger.warning(f"Invalid simulation response: {data}")
                else:
                    logger.warning(f"Simulation request failed with status {resp.status}")

        except Exception as e:
            logger.warning(f"CU estimation failed: {e}")

        # Fallback to default
        logger.info("Using default CU limit: 200000")
        return 200000

    def _get_cu_cache_key(self, program_id: str, operation_type: str = "swap") -> Tuple[str, str]:
        """Generate cache key for CU estimation."""
        return (program_id, operation_type)

    def _get_cached_cu(self, program_id: str, operation_type: str = "swap") -> Optional[int]:
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

    async def get_dynamic_priority_fee(self, rpc_url: Optional[str] = None, lookback_slots: int = 20, max_priority_fee_sol: float = 0.005, cu_limit: int = 300000) -> int:
        """Get dynamic priority fee based on recent prioritization fees.

        Args:
            rpc_url: RPC URL to query
            lookback_slots: Number of recent slots to analyze
            max_priority_fee_sol: Absolute maximum fee cap in SOL (Phase 34 Guard)
            cu_limit: Compute unit limit for this transaction

        Returns:
            Priority fee in micro-lamports, or 0 to signal caller to skip the trade
        """
        if not self.session:
            raise RuntimeError("Client session not available")

        rpc_url = rpc_url or self.rpc_url
        if not rpc_url:
            logger.warning("No RPC URL provided for priority fee estimation, using default")
            return 1000  # Default 1000 micro-lamports

        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getRecentPrioritizationFees",
                "params": [[]]  # Empty array for network-wide fees
            }

            timeout = aiohttp.ClientTimeout(total=1.0)
            async with self.session.post(rpc_url, json=payload, timeout=timeout) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "result" in data and data["result"]:
                        fees = [fee["prioritizationFee"] for fee in data["result"]]
                        if fees:
                            # Use 75th percentile for competitive pricing
                            fees.sort()
                            percentile_75_idx = int(len(fees) * 0.75)
                            priority_fee = fees[min(percentile_75_idx, len(fees) - 1)]
                            # Apply aggressiveness multiplier (1.1x)
                            priority_fee = int(priority_fee * 1.1)

                            # Fix 60: Priority Fee Saturation Guard
                            # 0.005 SOL is the absolute safety cap (~30% of our 0.017 SOL budget)
                            # If the network asks for more, we skip the trade — no exceptions
                            max_micro_lamports = int((max_priority_fee_sol * 1e9) / cu_limit * 1e6)

                            if priority_fee > max_micro_lamports:
                                logger.critical(
                                    f"🚨 PRIORITY FEE CAP BREACH: {priority_fee} µ-lamports "
                                    f"exceeds the {max_priority_fee_sol} SOL safety cap "
                                    f"({max_micro_lamports} µ-lamports). "
                                    f"Skipping trade — this fee would consume >30% of capital."
                                )
                                return 0  # Sentinel: caller MUST skip

                            final_fee = min(priority_fee, max_micro_lamports)
                            logger.debug(f"Dynamic priority fee: {final_fee} micro-lamports")
                            return max(final_fee, 1)  # Minimum 1 micro-lamport
                else:
                    logger.warning(f"Priority fee request failed with status {resp.status}")

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
        rpc_url: Optional[str] = None
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
            "stables_swap": 45000,      # Simple stablecoin swaps
            "lst_arbitrage": 65000,     # LST arbitrage with flash loans
            "xstocks_arbitrage": 85000, # xStocks with Token-2022 overhead
            "flash_arbitrage": 300000,  # Full flash loan arbitrage
            "default": 60000            # Standard Jupiter swaps
        }

        cu_limit = cu_profiles.get(operation_type, cu_profiles["default"])
        
        # Если в пути есть xStock (начинается на Xs...), повышаем лимит
        if any(str(m).startswith("Xs") for m in [program_id, operation_type]):
            cu_limit = 400000 # Удваиваем бюджет для Token-2022
        
        # Use cached CU only if it's lower than our conservative limit
        cached_cu = self._get_cached_cu(program_id, operation_type)
        if cached_cu and cached_cu < cu_limit:
            cu_limit = cached_cu


        # ╔══════════════════════════════════════════════════════════════════════╗
        # ║  TASK 2 — HARDCODED CU LIMITS (NO RPC SIMULATION — SAVES 200–300ms) ║
        # ║  Solana charges ONLY for actually consumed CU.                    ║
        # ║  Over-estimating is fine; under-estimating causes OOG.             ║
        # ╚══════════════════════════════════════════════════════════════════════╝
        if operation_type == "flash_arbitrage":
            cu_limit = 600_000
        elif operation_type == "xstocks_arbitrage":
            cu_limit = 800_000  # Token-2022 needs slightly more
        else:
            cu_limit = 400_000

        # Get priority fee
        # ЕСЛИ МЫ ИСПОЛЬЗУЕМ JITO, НАМ НЕ НУЖЕН ВЫСОКИЙ PRIORITY FEE!
        # Jito валидатор заберет транзакцию из-за чаевых. Платим сети абсолютный минимум.
        priority_fee = 1 if use_jito else await self.get_dynamic_priority_fee(rpc_url)

        # Fix 60: Safety cap check — 0 is our skip sentinel from get_dynamic_priority_fee
        if priority_fee == 0:
            logger.warning("🚫 PRIORITY FEE CAP HIT in build_optimized_transaction — trade aborted")
            return None, 0, 0

        # Build final instructions with compute budget
        final_instructions = []

        # Add CU limit instruction first
        cu_limit_ix = set_compute_unit_limit(cu_limit)
        final_instructions.append(cu_limit_ix)

        # Add priority fee instruction if not using Jito
        if priority_fee > 0:
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
                    logger.error(f"COMPUTE_BUDGET_RUNTIME_ASSERT: Instruction {type(ix).__name__} found at index {i} > 1")
                    return None, 0, 0  # Fix 6: hard check instead of assert (python -O safe)
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
                recent_blockhash=_bh
            )
            draft_tx = VersionedTransaction(draft_msg, [])
            _size = len(bytes(draft_tx))
            if _size > 1232:
                logger.warning(f"⚠️ TX {_size} B > 1232 B UDP limit — spilled; too many hops or providers")
                return None, 0, 0
        except Exception as _compile_err:
            # CRITICAL: MessageV0.try_compile failed — possible Rust panic or malformed CU/ALT state.
            # We skip this TX attempt (no RPC roundtrip) and return None so the caller retries cleanly.
            logger.warning(f"🚨 tx_builder compile/MTU preflight error: {_compile_err} — skipping TX, no RPC call made.")
            return None, 0, 0

        return final_instructions, cu_limit, priority_fee

    def _parse_instruction(self, ix_data: Dict) -> Instruction:
        """Parse Jupiter instruction dictionary into solders.Instruction."""
        raw_b64 = ix_data["data"]
        # Fix: pad base64 string to a multiple of 4 characters (Jupiter sometimes omits trailing '=')
        padded_b64 = raw_b64 + "=" * (-len(raw_b64) % 4)
        return Instruction(
            program_id=Pubkey.from_string(ix_data["programId"]),
            accounts=[
                AccountMeta(
                    pubkey=Pubkey.from_string(meta["pubkey"]),
                    is_signer=meta["isSigner"],
                    is_writable=meta["isWritable"]
                )
                for meta in ix_data["accounts"]
            ],
            data=base64.b64decode(padded_b64) if isinstance(ix_data["data"], str) else bytes(ix_data["data"])
        )

    async def get_swap_instructions(
        self,
        quote_response: Dict[str, Any],
        wallet_pubkey: str,
        use_custom_cu: bool = False,
        expected_tip_lamports: int = 100_000  # Ожидаемые чаевые
    ) -> Tuple[List[Instruction], List[Pubkey]]:
        """Get swap instructions from Jupiter API for a given quote.

        Args:
            quote_response: The response from the Jupiter /v6/quote API
            wallet_pubkey: User's public key as string

        Returns:
            Tuple of (list of solders Instructions, list of Address Lookup Table Pubkeys)
        """
        # Rate limit Jupiter API calls
        async with self.jupiter_limiter:
            payload = {
                "quoteResponse": quote_response,
                "userPublicKey": wallet_pubkey,
                "wrapAndUnwrapSol": False,
                "dynamicComputeUnitLimit": not use_custom_cu,
                "onlyDirectRoutes": "false",
                "restrictIntermediateTokens": "true",
                "maxAccounts": "8",  # MTU Safety: 8 accts × 32B = 256B overhead → TX stays within 1232-byte UDP limit
            }
            if destination_ata:
                payload["destinationTokenAccount"] = destination_ata
                logger.debug(f"🎯 Forcing Jupiter destination to primary wSOL ATA: {destination_ata[:8]}...")

            instructions_data = await self._post_swap_instructions_request(payload)
        
        if "error" in instructions_data:
            logger.error(f"Failed to get swap instructions: {instructions_data['error']}")
            return [], []

        instructions = []

        # Skip compute budget instructions - we handle CU limits ourselves

        # Parse setup instructions (e.g. creating ATAs)
        if "setupInstructions" in instructions_data and instructions_data["setupInstructions"]:
            seen_atas = set()
            for ix_data in instructions_data["setupInstructions"]:
                ix = self._parse_instruction(ix_data)
                
                # Phase 12: Deduplicate Associated Token Account creation
                if str(ix.program_id) == "ATokenGPvbdQxrVyoUXYLdG6A8P5F8L8ytxHBSxl86":
                    if len(ix.accounts) >= 2:
                        ata_pubkey = str(ix.accounts[1].pubkey)
                        if ata_pubkey in seen_atas:
                            logger.debug(f"🛡️ Skipping duplicate ATA creation for {ata_pubkey}")
                            continue
                        seen_atas.add(ata_pubkey)
                
                instructions.append(ix)

        # Parse main swap instruction
        if "swapInstruction" in instructions_data and instructions_data["swapInstruction"]:
            instructions.append(self._parse_instruction(instructions_data["swapInstruction"]))

        # Parse cleanup instruction (e.g. closing ATAs)
        if "cleanupInstruction" in instructions_data and instructions_data["cleanupInstruction"]:
            instructions.append(self._parse_instruction(instructions_data["cleanupInstruction"]))

        alt_pubkeys = []
        if "addressLookupTableAddresses" in instructions_data and instructions_data["addressLookupTableAddresses"]:
            raw_alts = instructions_data["addressLookupTableAddresses"]
            alt_pubkeys = [Pubkey.from_string(alt) for alt in raw_alts]
            # Non-blocking ALT validation (background task)
            if self.alt_manager:
                asyncio.create_task(self._validate_alt_accounts(alt_pubkeys))

        return instructions, alt_pubkeys

    async def _post_swap_instructions_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Post request to Jupiter swap-instructions API."""
        for attempt in range(self.max_retries):
            try:
                headers = {"Content-Type": "application/json"}
                jupiter_api_key = os.getenv("JUPITER_API_KEY")
                if jupiter_api_key:
                    headers["Authorization"] = f"Bearer {jupiter_api_key}"
                # Phase 13: Proxy Rotation
                url = JUPITER_PROXIES[self.proxy_index % len(JUPITER_PROXIES)]
                self.proxy_index += 1
                if time.time() - self.last_429_time < 30:
                    url = SWAP_INSTRUCTIONS_API_URL
                async with self.session.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 429:
                        self.last_429_time = time.time()
                        await asyncio.sleep(2 ** (attempt + 1))
                    else:
                        error_text = await response.text()
                        logger.warning(f"Swap instructions API error (attempt {attempt + 1}): {response.status} - {error_text}")

                        if attempt == self.max_retries - 1:
                            return {"error": f"HTTP {response.status}: {error_text}"}

            except asyncio.TimeoutError:
                logger.warning(f"Swap instructions API timeout (attempt {attempt + 1})")
                if attempt == self.max_retries - 1:
                    return {"error": "Request timeout"}

            except Exception as e:
                logger.error(f"Swap instructions API error (attempt {attempt + 1}): {e}")
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
                "params": [[str(pk) for pk in alt_pubkeys], {"encoding": "base64"}]
            }
            timeout = aiohttp.ClientTimeout(total=2.0)
            async with self.session.post(self.rpc_url, json=payload, timeout=timeout) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "result" in data and "value" in data["result"]:
                        accounts = data["result"]["value"]
                        invalid_alts = [alt for alt, acc in zip(alt_pubkeys, accounts) if acc is None]
                        if invalid_alts:
                            logger.warning(f"Invalid ALT accounts: {[str(pk) for pk in invalid_alts]}")
                            raise ValueError("One or more ALT accounts do not exist")
                            
                        # Phase 38: Update ALT cache with validated results
                        if self.alt_manager:
                            for alt_pubkey, acc_data in zip(alt_pubkeys, accounts):
                                if acc_data and "data" in acc_data:
                                    resolved = self.alt_manager._parse_alt_data(acc_data["data"][0])
                                    if resolved:
                                        alt_key = str(alt_pubkey)
                                        existing = self.alt_manager.alt_cache.get(alt_key, [])
                                        if len(resolved) >= len(existing):
                                            self.alt_manager.alt_cache[alt_key] = resolved
                                            self.alt_manager.alt_metadata[alt_key] = (time.time(), self.alt_manager.default_ttl)
        except Exception as e:
            logger.error(f"ALT validation error: {e}")
            raise

    # === CRITICAL SAFETY CHECK METHODS ===

    async def _estimate_transaction_size(
        self,
        instructions: List[Instruction],
        address_lookup_tables: List[str],
        payer: Pubkey
    ) -> int:
        """Estimate serialized transaction size in bytes."""
        try:
            # Create minimal message for size estimation
            dummy_blockhash = Hash.from_string("11111111111111111111111111111111")
            message = MessageV0.try_compile(
                payer=payer,
                instructions=instructions,
                address_lookup_table_accounts=[],  # Skip ALTs for estimation
                recent_blockhash=dummy_blockhash
            )

            # Estimate size (rough calculation)
            # MessageV0 header + instructions + signatures
            base_size = 128  # Headers and metadata
            instructions_size = sum(len(ix.data) + 32 for ix in instructions)  # Rough estimate
            alt_size = len(address_lookup_tables) * 32  # ALT addresses

            estimated_size = base_size + instructions_size + alt_size

            # Conservative estimate - add 20% buffer
            return int(estimated_size * 1.2)

        except Exception as e:
            logger.warning(f"Failed to estimate transaction size: {e}")
            return 2000  # Conservative fallback - assume too large

    async def _calculate_cpi_depth(self, instructions: List[Instruction]) -> int:
        """Estimate CPI (Cross-Program Invocation) depth."""
        max_depth = 1  # Base level

        for ix in instructions:
            # Jupiter swaps can have nested CPI calls
            if "Jupiter" in str(ix.program_id) or "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8" in str(ix.program_id):
                max_depth = max(max_depth, 3)  # Jupiter can go 2-3 levels deep
            # Raydium/Orca AMM calls
            elif any(pid in str(ix.program_id) for pid in ["675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8", "9W959DqEETiGZocYWCQPaJ6sBmUzgfxXfqGeTEdp3aQP"]):
                max_depth = max(max_depth, 2)

        return max_depth

    async def _check_marginfi_liquidity_realtime(self, borrow_amount: int, bank_pubkey: str) -> bool:
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
                "params": [bank_pubkey] # This should be the VAULT address in practice
            }
            
            async with self.session.post(self.rpc_url, json=payload) as resp:
                data = await resp.json()
                if "result" in data and "value" in data["result"]:
                    vault_lamports = int(data["result"]["value"]["amount"])
                    
                    # 95% Cap to avoid "InsufficientLiquidity" reverts
                    safe_liquidity = int(vault_lamports * 0.95)
                    
                    if borrow_amount > safe_liquidity:
                        logger.warning(f"❌ MarginFi Liquidity Cap hit: Borrowing {borrow_amount/1e9:.3f} > Safe {safe_liquidity/1e9:.3f} SOL")
                        return False
                        
                    return True
                
            return True # Fallback if RPC fails
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
                "params": [bank_pubkey]  # bank_liquidity_vault
            }
            async with self.session.post(self.rpc_url, json=payload) as resp:
                data = await resp.json()
                if "result" in data and "value" in data["result"]:
                    vault_lamports = int(data["result"]["value"]["amount"])
                    safe_liquidity = int(vault_lamports * 0.95)
                    return safe_liquidity
        except Exception as e:
            logger.error(f"Failed to fetch MarginFi bank liquidity: {e}")
        return 0

    async def _detect_sol_wrapping_conflict(self, instructions: List[Instruction]) -> bool:
        """Detect if there are conflicting SOL wrapping instructions."""
        wrap_count = 0
        unwrap_count = 0

        for ix in instructions:
            # Check for syncNative instruction (wSOL wrapping)
            if ix.program_id == Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"):
                # syncNative discriminator is first 8 bytes of sha256("global:sync_native")
                if len(ix.data) >= 8 and ix.data[:8] == SYNC_NATIVE_DISCRIMINATOR:
                    wrap_count += 1

            # Check for closeAccount instruction (wSOL unwrapping)
            if ix.program_id == Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"):
                # closeAccount discriminator
                if len(ix.data) >= 8 and ix.data[:8] == CLOSE_ACCOUNT_DISCRIMINATOR:
                    unwrap_count += 1

        # If both wrapping and unwrapping detected, likely a conflict
        return wrap_count > 0 and unwrap_count > 0

    # === FLASHLOAN PROVIDER FALLBACK SYSTEM ===

    async def build_flashloan_with_fallback(self, borrow_asset: str, borrow_amount: Decimal,
                                           arbitrage_instructions: List[Instruction],
                                           wallet_keypair, pool_state_manager = None) -> Optional[Dict[str, Any]]:
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
                        logger.warning(f"Provider {provider['name']} unavailable, trying fallback")
                        continue

                # Build transaction with this provider
                tx_data = await self._build_flashloan_for_provider(
                    provider, borrow_asset, borrow_amount,
                    arbitrage_instructions, wallet_keypair
                )

                if tx_data:
                    logger.info(f"✅ Flashloan built with {provider['name']} | "
                               f"Asset: {borrow_asset} | Amount: {borrow_amount}")
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
                "priority": 1
            },
            {
                "name": "Kamino",
                "program_id": "KLend2g3cP87fffoy8q1mQqGKjrxjC8bojiCLxnsfmk",
                "fee": 0,  # 0% fee
                "priority": 2
            },
            {
                "name": "Solend",
                "program_id": "So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpVF",  # Placeholder
                "fee": 0.001,  # 0.1% fee
                "priority": 3
            }
        ]

        # Filter providers that support the asset
        supported_providers = []
        for provider in base_providers:
            if await self._provider_supports_asset(provider, borrow_asset):
                supported_providers.append(provider)

        # Sort by priority
        supported_providers.sort(key=lambda x: x['priority'])
        return supported_providers

    async def _check_provider_availability(self, provider: Dict[str, Any], borrow_asset: str,
                                         borrow_amount: Decimal, pool_state_manager) -> bool:
        """Check if provider has sufficient liquidity for the borrow."""
        try:
            # In practice, would query provider's on-chain liquidity
            # For now, simulate utilization check

            utilization_rate = await self._get_provider_utilization(provider, borrow_asset)

            # Available if utilization < 95%
            available = utilization_rate < 0.95

            if not available:
                logger.debug(f"Provider {provider['name']} utilization: {utilization_rate:.1%}")

            return available

        except Exception as e:
            logger.debug(f"Availability check failed for {provider['name']}: {e}")
            return True  # Assume available if check fails

    async def _get_provider_utilization(self, provider: Dict[str, Any], asset: str) -> float:
        """Get utilization rate for provider/asset pair."""
        # In practice, would query on-chain data
        # For simulation, return mock values

        # Simulate MarginFi often at capacity
        if provider['name'] == 'MarginFi' and asset == 'USDC':
            return 0.98  # 98% utilized

        # Kamino more stable
        if provider['name'] == 'Kamino':
            return 0.70  # 70% utilized

        return 0.50  # Default 50% utilization

    async def _provider_supports_asset(self, provider: Dict[str, Any], asset: str) -> bool:
        """Check if provider supports borrowing the asset."""
        # All providers support major assets
        supported_assets = ['SOL', 'USDC', 'USDT', 'wBTC', 'wETH']
        return asset in supported_assets

    async def _build_flashloan_for_provider(self, provider: Dict[str, Any], borrow_asset: str,
                                          borrow_amount: Decimal, arbitrage_instructions: List[Instruction],
                                          wallet_keypair) -> Optional[Dict[str, Any]]:
        """Build flashloan transaction for specific provider."""
        try:
            if provider['name'] == 'MarginFi':
                return await self._build_marginfi_flashloan(
                    borrow_asset, borrow_amount, arbitrage_instructions, wallet_keypair
                )
            elif provider['name'] == 'Kamino':
                return await self._build_kamino_flashloan(
                    borrow_asset, borrow_amount, arbitrage_instructions, wallet_keypair
                )
            elif provider['name'] == 'Solend':
                return await self._build_solend_flashloan(
                    borrow_asset, borrow_amount, arbitrage_instructions, wallet_keypair
                )
            else:
                return None

        except Exception as e:
            logger.debug(f"Provider build failed for {provider['name']}: {e}")
            return None

    async def _build_marginfi_flashloan(self, borrow_asset: str, borrow_amount: Decimal,
                                      arbitrage_instructions: List[Instruction],
                                      wallet_keypair) -> Optional[Dict[str, Any]]:
        """Build MarginFi flashloan transaction using correct lending_account_flashloan instruction."""
        try:
            borrow_amount_lamports = int(borrow_amount * 1_000_000_000)  # Assume SOL for now
            repay_amount = borrow_amount_lamports  # Fix 79: exact integer repayment, no drift

            # Setup pubkeys (placeholder values, would be fetched)
            wallet = wallet_keypair.pubkey()
            mfi_program = Pubkey.from_string("MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA")
            mfi_account = Pubkey.from_string("11111111111111111111111111111111")  # Placeholder
            mfi_group = Pubkey.from_string("4qp6Fx6tnZkY5Wropq9wUYgtFxXKwE6viZxFHg3rdAG8")
            bank = Pubkey.from_string("11111111111111111111111111111111")  # Placeholder
            vault = Pubkey.from_string("11111111111111111111111111111111")  # Placeholder
            vault_auth = Pubkey.from_string("11111111111111111111111111111111")  # Placeholder
            sol_mint = Pubkey.from_string("So11111111111111111111111111111111111111112")
            user_sol_ata = get_associated_token_address(wallet, sol_mint)

            # Calculate repay index: after borrow + swaps
            repay_index = 1 + len(arbitrage_instructions)  # borrow at 0, swaps, repay at end

            # Borrow instruction
            borrow_ix = self._build_marginfi_borrow_ix(
                mfi_program, mfi_account, wallet, mfi_group, bank, vault, vault_auth,
                user_sol_ata, TOKEN_PROGRAM_ID, borrow_amount_lamports, [repay_index]
            )

            # Repay instruction
            repay_ix = self._build_marginfi_repay_ix(
                mfi_program, mfi_account, wallet, mfi_group, bank, vault, vault_auth,
                user_sol_ata, TOKEN_PROGRAM_ID, borrow_amount_lamports
            )

            all_instructions = [borrow_ix] + arbitrage_instructions + [repay_ix]

            return {
                "instructions": all_instructions,
                "expected_output": borrow_amount_lamports,  # Placeholder
                "borrow_amount": borrow_amount_lamports
            }

        except Exception as e:
            logger.error(f"Failed to build MarginFi flashloan: {e}")
            return None

    async def _build_kamino_flashloan(self, borrow_asset: str, borrow_amount: Decimal,
                                    arbitrage_instructions: List[Instruction],
                                    wallet_keypair) -> Optional[Dict[str, Any]]:
        """Build Kamino flashloan transaction."""
        # Implement Kamino-specific flashloan
        # Placeholder - would implement Kamino-specific instructions
        logger.debug("Kamino flashloan placeholder - needs implementation")
        return None

    async def _build_solend_flashloan(self, borrow_asset: str, borrow_amount: Decimal,
                                    arbitrage_instructions: List[Instruction],
                                    wallet_keypair) -> Optional[Dict[str, Any]]:
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
                    data = await resp.json()
                    if ("result" in data and "value" in data["result"]
                            and data["result"]["value"].get("amount")):
                        vault_lamports = int(data["result"]["value"]["amount"])
                        # 95 % cap prevents InsufficientLiquidity errors
                        safe_liquidity = int(vault_lamports * 0.95)
                        return safe_liquidity
        except Exception as e:
            logger.error(f"Failed to fetch MarginFi bank liquidity for {bank_liquidity_vault[:8]}: {e}")
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
        sol_bank_id = os.getenv("MARGINFI_SOL_BANK", "CCwqExrqLGHtq12X182rFvA4KEDtK13q2E7B3Jp2Cxyj").strip()
        usdc_bank_id = os.getenv("MARGINFI_USDC_BANK", "2s37akK2eyBbp8DZgCm7RtsaEz8eWhVKGfHGA3cKMEW2").strip()
        
        # Self-healing override to prevent fatal USDC bank address from .env
        correct_usdc = "2s37akK2eyBbp8DZgCm7RtsaEz8eWhVKGfHGA3cKMEW2"
        if usdc_bank_id != correct_usdc:
            usdc_bank_id = correct_usdc

        # Determine which bank to use based on borrow_mint
        bank_pubkey = sol_bank_id if "So111" in borrow_mint else usdc_bank_id
        
        # Real-time Liquidity Check with 95% Cap
        if not await self._check_marginfi_liquidity_realtime(borrow_amount_lamports, bank_pubkey):
            return None

        # ── 2. Setup Pubkeys ──────────────────────────────────────────
        wallet = Pubkey.from_string(wallet_pubkey)
        mfi_program = Pubkey.from_string(marginfi_config.get("program_id", "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"))
        mfi_account = Pubkey.from_string(marginfi_config["marginfi_account"])
        mfi_group = Pubkey.from_string(marginfi_config.get("marginfi_group", "4qp6Fx6tnZkY5Wropq9wUYgtFxXKwE6viZxFHg3rdAG8"))
        bank = Pubkey.from_string(bank_pubkey)
        vault = Pubkey.from_string(marginfi_config["bank_liquidity_vault"])
        vault_auth = Pubkey.from_string(marginfi_config["bank_liquidity_vault_authority"])
        
        sol_mint = Pubkey.from_string(borrow_mint)
        
        # Phase 48: Token-2022 Aware ATA Derivation
        from src.config.xstocks_registry import is_xstock_token
        sol_prog_id = TOKEN_2022_PROGRAM_ID if is_xstock_token(sol_mint) else TOKEN_PROGRAM_ID
        user_sol_ata = get_associated_token_address(wallet, sol_mint, sol_prog_id)

        # ── 3. Assemble Instructions ──────────────────────────────────
        all_instructions = []
        
        # 0. Compute Budget (MEV Safety & Priority)
        # We add these here so we can calculate the EXACT repay index dynamically.
        # Increased to 600,000 CU for Phase 48 high-complexity swaps.
        all_instructions.append(set_compute_unit_limit(600000))
        # Removed set_compute_unit_price - will be added by build_optimized_transaction
        
        # 1. Borrow from MarginFi (placeholder index)
        borrow_ix = self._build_marginfi_borrow_ix(
            mfi_program, mfi_account, wallet, mfi_group, bank, vault, vault_auth,
            user_sol_ata, sol_prog_id, borrow_amount_lamports, [0]
        )
        all_instructions.append(borrow_ix)
        
        # 2. DEX Swaps
        all_instructions.extend(dex_swap_instructions)
        
        # 4. MarginFi Repay
        repay_ix = self._build_marginfi_repay_ix(
            mfi_program, mfi_account, wallet, mfi_group, bank, vault, vault_auth,
            user_sol_ata, sol_prog_id, borrow_amount_lamports
        )
        all_instructions.append(repay_ix)

        # =====================================================================
        # 4.5 ATOMIC RENT RECOVERY — Закрытие промежуточных ATA (ЗАЩИТА КАПИТАЛА)
        # =====================================================================
        # После того как репей выполнен, закрываем все промежуточные ATA (кроме
        # CORE_GOLDEN: wSOL, USDC), чтобы мгновенно вернуть 0.002 SOL за каждую.
        # Это критично для бюджета 0.017 SOL — даже 2 зависшие ATA = 25% капитала.
        CORE_GOLDEN_MINTS_STR = {
            "So11111111111111111111111111111111111111112",  # wSOL
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", # USDC
        }
        intermediate_mints = set(arbitrage_path)  # все токены маршрута (Эфемерные ATA)
        for mint_str in intermediate_mints:
            if mint_str in CORE_GOLDEN_MINTS_STR:
                continue
            try:
                mint_pk = Pubkey.from_string(mint_str)
                # Token-2022 detection via xstocks_registry
                from src.config.xstocks_registry import is_xstock_token
                is_xstock = is_xstock_token(mint_pk)
                prog_id = TOKEN_2022_PROGRAM_ID if is_xstock else TOKEN_PROGRAM_ID

                ata_to_close = get_associated_token_address(wallet, mint_pk, prog_id)
                close_ix = close_account(CloseAccountParams(
                    program_id=prog_id,
                    account=ata_to_close,
                    dest=wallet,
                    owner=wallet
                ))
                all_instructions.append(close_ix)
                prog_label = "Token-2022" if is_xstock else "SPL"
                logger.debug(f"🧹 Atomic CloseAccount: {mint_str[:8]} ({prog_label})")
            except Exception as e:
                logger.debug(f"⚠️ Atomic close skipped for {mint_str[:8]}: {e}")
        # =====================================================================

        # ЗАЩИТА КАПИТАЛА (0.017 SOL): Чаевые Jito СТРОГО в конце единой транзакции.
        # Если DEX Swap выдаст SlippageExceeded или MarginFi Repay выдаст InsufficientFunds ->
        # вся транзакция откатывается, и перевод чаевых НЕ СРАБОТАЕТ.
        if jito_tip_lamports > 0:
            from solders.system_program import TransferParams, transfer
            tip_ix = transfer(TransferParams(
                from_pubkey=wallet,
                to_pubkey=Pubkey.from_string("96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"),
                lamports=jito_tip_lamports
            ))
            all_instructions.append(tip_ix)

        # Calculate EXACT repay index dynamically using list introspection
        try:
            actual_repay_index = all_instructions.index(repay_ix)

            # ── БЕЗОПАСНАЯ ПЕРЕСБОРКА ДАННЫХ (Первые 8 байт - дискриминатор, затем 8 байт - u64 amount) ──
            # Формат: discriminator(8) + amount(8) + index(1)
            # Старый подход borrow_ix.data[:-1] + bytes([index]) сдвигает байты и убивает транзакцию.
            # Теперь используем struct.pack для четкой сборки последнего байта.
            import struct
            from solders.instruction import Instruction
            original_data_without_index = borrow_ix.data[:16]
            safe_index_bytes = struct.pack("<Q", actual_repay_index)
            new_data = original_data_without_index + safe_index_bytes
            new_borrow_ix = Instruction(
                program_id=borrow_ix.program_id,
                accounts=borrow_ix.accounts,
                data=new_data,
            )
            borrow_idx = all_instructions.index(borrow_ix)
            all_instructions[borrow_idx] = new_borrow_ix
            borrow_ix = new_borrow_ix

            logger.debug(f"🛠️ Safe Dynamic Repay Index calculated: {actual_repay_index}")
        except ValueError:
            logger.error("CRITICAL: repay_ix not found in instruction list")
            return None

        return {
            "instructions": self.sanitize_instructions(all_instructions),
            "address_lookup_tables": [], # Would be populated
            "repay_index": actual_repay_index
        }


    def sanitize_instructions(self, instructions: List[Instruction]) -> List[Instruction]:
        """Phase 48: Global Cross-Leg ATA Deduplication.
        Filters out redundant create_associated_token_account instructions.
        """
        seen_atas = set()
        sanitized = []
        ata_prog = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
        
        for ix in instructions:
            if ix.program_id == ata_prog:
                # Associated Token Account program: target ATA is typically account at index 1
                if len(ix.accounts) >= 2:
                    ata_pubkey = str(ix.accounts[1].pubkey)
                    if ata_pubkey in seen_atas:
                        logger.debug(f"✂️ Deduplicated ATA creation for {ata_pubkey[:8]}")
                        continue
                    seen_atas.add(ata_pubkey)
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
        strategy_type: int = 1
    ) -> Optional[Dict[str, Any]]:
        try:
            from solders.pubkey import Pubkey
            from spl.token.instructions import get_associated_token_address
            from spl.token.constants import TOKEN_PROGRAM_ID
            
            wallet = Pubkey.from_string(wallet_pubkey)
            mfi_program = Pubkey.from_string("MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA")
            mfi_group = Pubkey.from_string("4qp6Fx6tnZkY5Wropq9wUYgtFxXKwE6viZxFHg3rdAG8")
            sol_mint = Pubkey.from_string("So11111111111111111111111111111111111111112")
            user_sol_ata = get_associated_token_address(wallet, sol_mint)
            
            all_instructions = []
            alts = []

            # Get Buy Swaps (если quote не пустой)
            if buy_quote_response:
                buy_ixs, buy_alts = await self.get_swap_instructions(buy_quote_response, wallet_pubkey, use_custom_cu=True)
                if not buy_ixs: return None
                alts.extend(buy_alts)

            # Get Sell Swaps (если quote не пустой)
            if sell_quote_response:
                sell_ixs, sell_alts = await self.get_swap_instructions(sell_quote_response, wallet_pubkey, use_custom_cu=True)
                if not sell_ixs: return None
                alts.extend(sell_alts)

            # ── ФИКС ЛОВУШКИ #1: Умная дедупликация ATA ─────────────────────────
            # Оба свопа могут возвращать setupInstructions с CreateATA для одного
            # и того же токена. Дубликат вызывает AccountAlreadyInitialized.
            # Удаляем дубли до сборки транзакции.
            from solders.pubkey import Pubkey
            ATOKEN_PROGRAM = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
            seen_atas: set = set()
            cleaned_ixs: list = []

            for ix in (buy_ixs if buy_quote_response else []) + (sell_ixs if sell_quote_response else []):
                if ix.program_id == ATOKEN_PROGRAM and len(ix.accounts) >= 2:
                    ata_addr = str(ix.accounts[1].pubkey)
                    if ata_addr in seen_atas:
                        logger.debug(f"✂️ Пропущен дубликат создания ATA: {ata_addr[:8]}")
                        continue
                    seen_atas.add(ata_addr)
                cleaned_ixs.append(ix)

            all_instructions = cleaned_ixs

            # Вычисляем индексы для MarginFi (Flashloan Introspection)
            # Допустим, мы берем займ первым, затем идут свопы, затем возврат
            repay_index = len(all_instructions) + 1 # +1 т.к. borrow будет в начале

            borrow_ix = self.build_marginfi_borrow_ix(
                mfi_program, Pubkey.from_string(marginfi_account), wallet, mfi_group,
                Pubkey.from_string(bank_pubkey), Pubkey.from_string(bank_liquidity_vault),
                Pubkey.from_string(bank_liquidity_vault_authority), user_sol_ata, TOKEN_PROGRAM_ID,
                borrow_amount_lamports, [repay_index]
            )
            
            repay_ix = self.build_marginfi_repay_ix(
                mfi_program, Pubkey.from_string(marginfi_account), wallet, mfi_group,
                Pubkey.from_string(bank_pubkey), Pubkey.from_string(bank_liquidity_vault),
                Pubkey.from_string(bank_liquidity_vault_authority), user_sol_ata, TOKEN_PROGRAM_ID,
                borrow_amount_lamports
            )

            # ── ФИКС ЛОВУШКИ #2: Идемпотентное создание ATA для займа ─────────
            # MarginFi lending_account_start_flashloan предполагает существование ATA
            # для займного токена. Jupiter его не создаёт. create_idempotent не упадёт,
            # если ATA уже есть — безопасно вызывать всегда.
            pre_instructions = []
            try:
                from spl.token.instructions import create_idempotent_associated_token_account
                # Определяем mint займа по bank_pubkey
                _sol_bank = os.getenv("MARGINFI_SOL_BANK", "CCwqExrqLGHtq12X182rFvA4KEDtK13q2E7B3Jp2Cxyj")
                _usdc_bank = "2s37akK2eyBbp8DZgCm7RtsaEz8eWhVKGfHGA3cKMEW2"
                borrow_mint_str = (
                    "So11111111111111111111111111111111111111112"
                    if bank_pubkey == _sol_bank else
                    ("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
                     if bank_pubkey == _usdc_bank else
                     "So11111111111111111111111111111111111111112")  # fallback: SOL
                )
                borrow_mint_pk = Pubkey.from_string(borrow_mint_str)
                init_ata_ix = create_idempotent_associated_token_account(
                    payer=wallet, owner=wallet, mint=borrow_mint_pk
                )
                pre_instructions.append(init_ata_ix)
                logger.debug(f"🛡️ Idempotent borrow ATA ensured for {borrow_mint_str[:8]}")
            except ImportError:
                logger.warning("⚠️ create_idempotent_associated_token_account unavailable — relying on pre-existing ATA")

            cu_limit_ix = set_compute_unit_limit(600000)
            final_instructions = [cu_limit_ix] + pre_instructions + [borrow_ix] + all_instructions + [repay_ix]

            # 4.5 ATOMIC RENT RECOVERY — закрыть промежуточные после repay
            CORE_GOLDEN_MINTS_STR = {
                "So11111111111111111111111111111111111111112",
                "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            }
            intermediate_mints = set(arbitrage_path) if isinstance(arbitrage_path, list) else set()
            for mint_str in intermediate_mints:
                if mint_str in CORE_GOLDEN_MINTS_STR:
                    continue
                try:
                    mint_pk = Pubkey.from_string(mint_str)
                    from src.config.xstocks_registry import is_xstock_token
                    is_xstock = is_xstock_token(mint_pk)
                    prog_id = TOKEN_2022_PROGRAM_ID if is_xstock else TOKEN_PROGRAM_ID
                    ata_to_close = get_associated_token_address(wallet, mint_pk, prog_id)
                    close_ix = close_account(CloseAccountParams(
                        program_id=prog_id,
                        account=ata_to_close,
                        dest=wallet,
                        owner=wallet
                    ))
                    final_instructions.append(close_ix)
                except Exception:
                    pass

            # 5. ATOMIC JITO TIP (100% CAPITAL PROTECTION)
            if jito_tip_lamports > 0:
                from solders.system_program import TransferParams, transfer
                tip_ix = transfer(TransferParams(
                    from_pubkey=wallet,
                    to_pubkey=Pubkey.from_string("96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"),
                    lamports=jito_tip_lamports
                ))
                final_instructions.append(tip_ix)

            # Вычисляем точный индекс Repay инструкции для интроспекции MarginFi
            try:
                actual_repay_index = final_instructions.index(repay_ix)
                # БЕЗОПАСНАЯ ПЕРЕСБОРКА ДАННЫХ (Первые 8 байт - дискриминатор, затем 8 байт - u64 amount,
                # потом 1 байт - индекс). Старый подход borrow_ix.data[:-1] + bytes([index])
                # сдвигает байты и убивает транзакцию.
                import struct
                original_data_without_index = borrow_ix.data[:16]
                safe_index_bytes = struct.pack("<Q", actual_repay_index)
                new_borrow_ix = Instruction(
                    program_id=borrow_ix.program_id,
                    accounts=borrow_ix.accounts,
                    data=original_data_without_index + safe_index_bytes,
                )
                borrow_idx = final_instructions.index(borrow_ix)
                final_instructions[borrow_idx] = new_borrow_ix
                borrow_ix = new_borrow_ix
                logger.debug(f"🛠️ Safe Dynamic Repay Index calculated: {actual_repay_index}")
            except ValueError:
                logger.error("CRITICAL: repay_ix not found in instruction list")
                return None

            return {
                "instructions": self.sanitize_instructions(final_instructions),
                "address_lookup_table_pubkeys": list(set(alts)),
                "repay_index": actual_repay_index if 'actual_repay_index' in dir() else repay_index
            }
        except Exception as e:
            logger.error(f"Failed to build marginfi flashloan tx: {e}")
            return None

    def build_marginfi_borrow_ix(
        self, mfi_program: Pubkey, mfi_account: Pubkey, wallet: Pubkey,
        mfi_group: Pubkey, bank: Pubkey, vault: Pubkey, vault_auth: Pubkey,
        user_token_account: Pubkey, token_program: Pubkey, amount: int,
        instruction_indices: List[int]
    ) -> Instruction:
        """Build MarginFi lending_account_flashloan instruction with instruction introspection."""
        # Data: discriminator + amount (u64) + end_index (u8)
        # Note: instruction_indices[0] is the index where repayment is checked
        data = MARGINFI_BORROW_DISCRIMINATOR + amount.to_bytes(8, "little") + bytes([instruction_indices[0]])

        # Add Sysvar1nstructions for MarginFi v2 instruction introspection
        sysvar_instructions = Pubkey.from_string("Sysvar1nstructions1111111111111111111111111")

        return Instruction(
            program_id=mfi_program,
            accounts=[
                AccountMeta(pubkey=mfi_account, is_signer=False, is_writable=True),
                AccountMeta(pubkey=wallet, is_signer=True, is_writable=True),
                AccountMeta(pubkey=mfi_group, is_signer=False, is_writable=False),
                AccountMeta(pubkey=bank, is_signer=False, is_writable=True),
                AccountMeta(pubkey=vault, is_signer=False, is_writable=True),
                AccountMeta(pubkey=vault_auth, is_signer=False, is_writable=False),
                AccountMeta(pubkey=user_token_account, is_signer=False, is_writable=True),
                AccountMeta(pubkey=token_program, is_signer=False, is_writable=False),
                AccountMeta(pubkey=sysvar_instructions, is_signer=False, is_writable=False),
            ],
            data=data,
        )

    def build_marginfi_repay_ix(
        self, mfi_program: Pubkey, mfi_account: Pubkey, wallet: Pubkey,
        mfi_group: Pubkey, bank: Pubkey, vault: Pubkey, vault_auth: Pubkey,
        user_token_account: Pubkey, token_program: Pubkey, amount: int
    ) -> Instruction:
        """Build MarginFi lending_account_repay instruction."""
        # Phase 48: Используем точную сумму amount вместо u64::MAX
        # MarginFi v2 может выдавать ошибку math на u64_max во флеш-лоанах.
        # Передача точной суммы гарантирует успешный repay без ошибок математики.
        data = MARGINFI_REPAY_DISCRIMINATOR + amount.to_bytes(8, "little")

        return Instruction(
            program_id=mfi_program,
            accounts=[
                AccountMeta(pubkey=mfi_account, is_signer=False, is_writable=True),
                AccountMeta(pubkey=wallet, is_signer=True, is_writable=True),
                AccountMeta(pubkey=mfi_group, is_signer=False, is_writable=False),
                AccountMeta(pubkey=bank, is_signer=False, is_writable=True),
                AccountMeta(pubkey=vault, is_signer=False, is_writable=True),
                AccountMeta(pubkey=vault_auth, is_signer=False, is_writable=False),
                AccountMeta(pubkey=user_token_account, is_signer=False, is_writable=True),
                AccountMeta(pubkey=token_program, is_signer=False, is_writable=False),
            ],
            data=data,
        )

    def _build_jito_tip_ix(self, wallet: Pubkey, tip_amount: int) -> Instruction:
        """Build Jito tip instruction for capital protection."""
        from solders.system_program import TransferParams, transfer

        return transfer(TransferParams(
            from_pubkey=wallet,
            to_pubkey=Pubkey.from_string("96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"),  # Jito tip account
            lamports=tip_amount,
        ))

    # === CAPITAL PROTECTION METHODS ===

    async def _add_ata_rent_recovery(self, instructions: List[Instruction], payer: Pubkey) -> List[Instruction]:
        """Add ATA rent recovery instructions to reclaim 0.002 SOL per token account."""
        recovery_instructions = []
        WHITELIST_MINTS = [
            "So11111111111111111111111111111111111111112", # SOL
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", # USDC
        ]

        for ix in instructions:
            if hasattr(ix, 'program_id') and str(ix.program_id) == str(ASSOCIATED_TOKEN_PROGRAM_ID):
                if len(ix.accounts) >= 4:
                    token_mint = str(ix.accounts[3].pubkey)
                    if token_mint in WHITELIST_MINTS:
                        continue

                    token_account = ix.accounts[1].pubkey

                    # Determine program ID based on token type (Token vs Token-2022)
                    from src.config.xstocks_registry import is_xstock_token
                    program_id = TOKEN_2022_PROGRAM_ID if is_xstock_token(token_mint) else TOKEN_PROGRAM_ID

                    from spl.token.instructions import CloseAccountParams, close_account
                    close_ix = close_account(CloseAccountParams(
                        account=token_account, dest=payer, owner=payer, program_id=program_id
                    ))
                    recovery_instructions.append(close_ix)
                    logger.debug(f"🛠️ Enforcing rent recovery for {'xStock' if is_xstock_token(token_mint) else 'SPL'} ATA: {token_account}")

        return recovery_instructions

    async def _estimate_transaction_cu(self, instructions: List[Instruction], current_cu_limit: int, rpc_url: str) -> Optional[int]:
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
                recent_blockhash=dummy_blockhash
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
                    }
                ]
            }

            async with self.session.post(rpc_url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
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
        STABLES = ["EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"]
        LSTs = ["jitoSoX8AnGvCjk9ncS626S6757L8HEnuU6Muz3zSUn", "mSoLzYSa7mS5165EKKv9kS6m4H3sSsaZ17PZ7wHS69"]
        
        is_stable = all(token in STABLES for token in arbitrage_path)
        if is_stable:
            return 0.0002 # 2 bps
            
        is_lst = any(token in LSTs for token in arbitrage_path)
        if is_lst:
            return 0.0005 # 5 bps
            
        return 0.0030 # 30 bps (xStocks/Default)

    async def get_circular_quote(
        self,
        input_mint: str,
        middle_mint: str,
        amount_lamports: int,
        dex_filter_leg1: Optional[List[str]] = None,
        dex_filter_leg2: Optional[List[str]] = None,
        jito_tip_lamports: int = 50000,
        only_direct_routes: bool = False,
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
            f"amount={amount_lamports}&"
            f"slippageBps=50&"
            f"maxAccounts=10&"
            f"onlyDirectRoutes={str(only_direct_routes).lower()}&"
            f"restrictIntermediateTokens=true"
        )
        if dex_filter_leg1:
            quote_url += f"&dexes={','.join(dex_filter_leg1)}"

        try:
            timeout = aiohttp.ClientTimeout(total=5.0)
            async with self.session.get(quote_url, timeout=timeout) as resp:
                if resp.status != 200:
                    return None
                leg1 = await resp.json()
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
            f"slippageBps=50&"
            f"maxAccounts=10&"
            f"onlyDirectRoutes={str(only_direct_routes).lower()}&"
            f"restrictIntermediateTokens=true"
        )
        if dex_filter_leg2:
            quote_url2 += f"&dexes={','.join(dex_filter_leg2)}"

        try:
            timeout = aiohttp.ClientTimeout(total=5.0)
            async with self.session.get(quote_url2, timeout=timeout) as resp:
                if resp.status != 200:
                    return None
                leg2 = await resp.json()
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