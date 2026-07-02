"""Security and Liquidity Guard for pre-trade validation."""

import asyncio
import logging
import os
import struct
import time
from typing import Optional, Dict, Any, Tuple
import aiohttp
from solders.pubkey import Pubkey
from solders.system_program import ID as SYSTEM_PROGRAM_ID
from src.ingest.flywheel_scaler import DynamicThresholds

logger = logging.getLogger(__name__)

# Token program IDs
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
TOKEN_2022_PROGRAM_ID = Pubkey.from_string(
    "TokenzQdBNbLqP5VEhdkAS6EP2rHEjaChQX6n57TR5m"
)


def get_vault_threshold(decimals: int = 6) -> int:
    """Calculate vault liquidity threshold for a given token decimals.

    Threshold = 100 * (10 ** decimals) — equivalent to ~$100 worth at $1/token.
    For 6-decimals (USDC): threshold = 100 * 10^6 = 100_000_000 ($100)
    For 5-decimals (BONK): threshold = 100 * 10^5 = 10_000_000 (~$1.80 at BONK prices)
    For 9-decimals (SOL): threshold = 100 * 10^9 = 100_000_000_000 (100 SOL — too high; SOL paths bypass this check via OptimalTradeSizer)
    """
    return 100 * (10 ** max(decimals, 0))


RENT_EXEMPT_LAMPORT = 2_039_280

# Whitelist of safe tokens (stablecoins and LSTs)
SAFE_MINTS = {
    "So11111111111111111111111111111111111111112",  # wSOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",  # jitoSOL (mainnet verified)
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",  # mSOL    (mainnet verified)
    "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",  # bSOL    (mainnet verified)
}


class TokenSecurityChecker:
    """Analyzes token mint accounts for security flags and scam indicators."""

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        rpc_url: Optional[str] = None,
    ):
        self.session = session
        self.rpc_url = rpc_url

    async def check_token_security(
        self, mint_address: str, rpc_url: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Check if a token mint account is safe for trading.

        Args:
            mint_address: Token mint address as string
            rpc_url: Optional RPC URL override

        Returns:
            Tuple of (is_safe: bool, reason: str)
        """
        # Fix 73: Safe session fallback — create ad-hoc session if none provided
        _session = self.session
        _session_owned = False
        if _session is None:
            try:
                _session = aiohttp.ClientSession()
                _session_owned = True
                logger.debug(
                    "Fix 73: Created ad-hoc aiohttp session for check_token_security"
                )
            except Exception as e:
                return False, f"No HTTP session available: {e}"

        # Phase 20: Whitelist bypass
        mint_str = (
            str(mint_address) if isinstance(mint_address, Pubkey) else str(mint_address)
        )
        if mint_str in SAFE_MINTS:
            logger.debug(
                f"🛡️ Token {mint_address} is in SAFE_MINTS whitelist. Bypassing security checks."
            )
            if _session_owned:
                await _session.close()
            return True, "Whitelisted safe token"

        rpc_url = rpc_url or self.rpc_url
        if not rpc_url:
            if _session_owned:
                await _session.close()
            return False, "No RPC URL provided"

        try:
            # Get account info for the mint
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [
                    str(mint_address),  # Phase 18: str() cast prevents JSON serialization crash for Pubkey objects
                    {"encoding": "base64", "commitment": "confirmed"},
                ],
            }

            async with _session.post(rpc_url, json=payload) as resp:
                if resp.status != 200:
                    return False, f"RPC error: HTTP {resp.status}"

                data = await resp.json()
                if "error" in data:
                    return False, f"RPC error: {data['error']}"

                account_info = data.get("result", {}).get("value")
                if not account_info:
                    return False, "Mint account not found"

                return await self._analyze_mint_account(account_info, mint_address)

        except Exception as e:
            logger.warning(f"Security check failed for {mint_address}: {e}")
            return False, f"Check failed: {str(e)}"
        finally:
            if _session_owned:
                await _session.close()

    async def _analyze_mint_account(
        self, account_info: Dict[str, Any], mint_address: str
    ) -> Tuple[bool, str]:
        """Analyze the raw mint account data for security flags."""
        try:
            owner = account_info.get("owner")
            if not owner:
                return False, "Account has no owner"

            # Check which token program owns this account
            owner_pubkey = Pubkey.from_string(owner)

            if owner_pubkey == TOKEN_PROGRAM_ID:
                return self._check_token_program_mint(account_info, mint_address)
            elif owner_pubkey == TOKEN_2022_PROGRAM_ID:
                return self._check_token_2022_mint(account_info, mint_address)
            else:
                return False, f"Unknown token program: {owner}"

        except Exception as e:
            return False, f"Analysis failed: {str(e)}"

    def _check_token_program_mint(
        self, account_info: Dict[str, Any], mint_address: str
    ) -> Tuple[bool, str]:
        """Check security flags for standard Token Program mint."""
        try:
            import base64

            data_b64 = account_info.get("data", [""])[0]
            if not data_b64:
                return False, "No account data"

            # Decode base64 data (with padding fix)
            data = base64.b64decode(data_b64 + "=" * (-len(data_b64) % 4))

            # Mint account structure for Token Program:
            # - mintAuthority: 36 bytes (pubkey option, starts at byte 0)
            # - supply: 8 bytes (byte 36)
            # - decimals: 1 byte (byte 44)
            # - isInitialized: 1 byte (byte 45)
            # - freezeAuthority: 36 bytes (pubkey option, starts at byte 46)

            if len(data) < 82:  # Minimum size for mint account
                return False, "Invalid mint account data size"

            # Check mintAuthority (first 36 bytes: 1 byte option + 32 byte pubkey)
            mint_auth_option = data[0]
            if mint_auth_option != 0:  # 0 = None, 1 = Some
                return False, "Mint authority is set (token can be minted)"

            # Check freezeAuthority (starts at byte 46: 1 byte option + 32 byte pubkey)
            freeze_auth_option = data[46]
            if freeze_auth_option != 0:  # 0 = None, 1 = Some
                return False, "Freeze authority is set (tokens can be frozen)"

            return True, "Token appears safe"

        except Exception as e:
            return False, f"Token program analysis failed: {str(e)}"

    def _check_token_2022_mint(
        self, account_info: Dict[str, Any], mint_address: str
    ) -> Tuple[bool, str]:
        """Check security flags for Token-2022 mint."""
        try:
            import base64

            DANGEROUS_EXTENSIONS = {3, 7, 16}

            data_b64 = account_info.get("data", [""])[0]
            if not data_b64:
                return False, "No account data"

            data = base64.b64decode(data_b64 + "=" * (-len(data_b64) % 4))

            if len(data) < 82:
                return False, "Invalid Token-2022 account data size"

            if len(data) >= 166:
                offset = 166
                while offset + 4 <= len(data):
                    ext_type = struct.unpack("<H", data[offset : offset + 2])[0]
                    ext_len = struct.unpack("<H", data[offset + 2 : offset + 4])[0]

                    if ext_type in DANGEROUS_EXTENSIONS:
                        logger.critical(
                            f"🚨 HONEYPOT DETECTED: Token-2022 has dangerous extension {ext_type} on {mint_address}"
                        )
                        return False, f"Dangerous Token-2022 extension {ext_type} (Potential Honeypot)"

                    # ─── БЛОК 13: PermanentDelegate Honeypot Detection ─────────────────────
                    if ext_type == 13:  # PermanentDelegate
                        logger.critical(
                            f"🚨 HONEYPOT DETECTED: Token-2022 has PermanentDelegate (type 13) on {mint_address}"
                        )
                        return False, "Honeypot: PermanentDelegate active (creator can seize tokens at any time)"

                    # ─── БЛОК 13: TransferHook Honeypot Detection ──────────────────────────
                    if ext_type == 14:  # TransferHook
                        logger.critical(
                            f"🚨 HONEYPOT DETECTED: Token-2022 has TransferHook (type 14) on {mint_address}"
                        )
                        return False, "Honeypot: Unknown TransferHook (can freeze/fail transfers)"

                    if ext_type == 11:
                        if ext_len >= 108:
                            bps_offset = offset + 4 + 106
                            if bps_offset + 2 <= len(data):
                                fee_bps = struct.unpack(
                                    "<H", data[bps_offset : bps_offset + 2]
                                )[0]
                                if fee_bps > 500:
                                    fee_pct = fee_bps / 100.0
                                    logger.critical(
                                        f"🚨 HONEYPOT DETECTED: Token-2022 transfer fee {fee_pct}% > 5% on {mint_address}"
                                    )
                                    return (
                                        False,
                                        f"Token-2022 transfer fee {fee_pct}% exceeds 5% (Potential Honeypot)",
                                    )
                                elif fee_bps > 0:
                                    fee_pct = fee_bps / 100.0
                                    return (
                                        False,
                                        f"Token-2022 has transfer fee: {fee_pct}% ({fee_bps} bps)",
                                    )

                    offset += 4 + ext_len

            return True, "Token-2022 appears safe (fee check passed)"

        except Exception as e:
            return False, f"Token-2022 analysis failed: {str(e)}"


class LiquidityValidator:
    """Validates real liquidity in pool vaults."""

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        rpc_url: Optional[str] = None,
    ):
        self.session = session
        self.rpc_url = rpc_url

    async def validate_vault_balance(
        self, vault_address: str, rpc_url: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Check if a token vault has sufficient real liquidity.

        Args:
            vault_address: Token vault address as string
            rpc_url: Optional RPC URL override

        Returns:
            Tuple of (has_liquidity: bool, reason: str)
        """
        # Fix 73: Safe session fallback
        _session = self.session
        _session_owned = False
        if _session is None:
            try:
                _session = aiohttp.ClientSession()
                _session_owned = True
            except Exception as e:
                return False, f"No HTTP session available: {e}"

        rpc_url = rpc_url or self.rpc_url
        if not rpc_url:
            if _session_owned:
                await _session.close()
            return False, "No RPC URL provided"

        try:
            # Get token account balance
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountBalance",
                "params": [vault_address],
            }

            async with _session.post(rpc_url, json=payload) as resp:
                if resp.status != 200:
                    return False, f"RPC error: HTTP {resp.status}"

                data = await resp.json()
                if "error" in data:
                    return False, f"RPC error: {data['error']}"

                balance_info = data.get("result", {})
                if not balance_info:
                    return False, "Vault account not found or not a token account"

                amount_str = balance_info.get("amount", "0")
                decimals = balance_info.get("decimals", 6)
                try:
                    amount = int(amount_str)
                    threshold = get_vault_threshold(decimals)
                    if amount < threshold:
                        return (
                            False,
                            f"Insufficient vault balance: {amount} (min: {threshold} for {decimals} decimals)",
                        )

                    return True, f"Vault has sufficient balance: {amount}"

                except ValueError:
                    return False, f"Invalid balance format: {amount_str}"

        except Exception as e:
            logger.warning(f"Vault validation failed for {vault_address}: {e}")
            return False, f"Validation failed: {str(e)}"
        finally:
            if _session_owned:
                await _session.close()

    async def batch_validate_security_and_liquidity(
        self, mint_address: str, vault_address: str, rpc_url: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Validate both security and liquidity in a single batch RPC call.

        Args:
            mint_address: Token mint address
            vault_address: Token vault address
            rpc_url: Optional RPC URL override

        Returns:
            Tuple of (is_valid: bool, reason: str)
        """
        # Fix 73: Safe session fallback
        _session = self.session
        _session_owned = False
        if _session is None:
            try:
                _session = aiohttp.ClientSession()
                _session_owned = True
            except Exception as e:
                return False, f"No HTTP session available: {e}"

        rpc_url = rpc_url or self.rpc_url
        if not rpc_url:
            if _session_owned:
                await _session.close()
            return False, "No RPC URL provided"

        try:
            # Use getMultipleAccounts to fetch both accounts in one request
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getMultipleAccounts",
                "params": [
                    [mint_address, vault_address],
                    {"encoding": "base64", "commitment": "confirmed"},
                ],
            }

            async with _session.post(rpc_url, json=payload) as resp:
                if resp.status != 200:
                    return False, f"RPC error: HTTP {resp.status}"

                data = await resp.json()
                if "error" in data:
                    return False, f"RPC error: {data['error']}"

                accounts = data.get("result", {}).get("value", [])
                if len(accounts) != 2:
                    return False, "Failed to fetch both accounts"

                mint_account, vault_account = accounts

                # Check security first (cheaper analysis)
                if not mint_account:
                    return False, "Mint account not found"

                security_checker = TokenSecurityChecker()
                is_secure, security_reason = (
                    await security_checker._analyze_mint_account(
                        mint_account, mint_address
                    )
                )
                if not is_secure:
                    return False, f"Security check failed: {security_reason}"

                # Check liquidity
                if not vault_account:
                    return False, "Vault account not found"

                # Parse vault balance from account data
                import base64

                vault_data_b64 = vault_account.get("data", [""])[0]
                if vault_data_b64:
                    vault_data = base64.b64decode(
                        vault_data_b64 + "=" * (-len(vault_data_b64) % 4)
                    )
                    # Token account balance is at offset 64-72 (8 bytes, little endian)
                    if len(vault_data) >= 72:
                        balance_bytes = vault_data[64:72]
                        balance = struct.unpack("<Q", balance_bytes)[
                            0
                        ]  # little endian uint64

                        if balance < get_vault_threshold(6):
                            return (
                                False,
                                f"Insufficient vault balance: {balance} (min: {get_vault_threshold(6)})",
                            )

                        return True, f"Token is secure and vault has balance: {balance}"
                    else:
                        return False, "Invalid vault account data"
                else:
                    return False, "No vault account data"

        except Exception as e:
            logger.warning(
                f"Batch validation failed for mint={mint_address}, vault={vault_address}: {e}"
            )
            return False, f"Batch validation failed: {str(e)}"
        finally:
            if _session_owned:
                await _session.close()


class PreTradeGuard:
    """Orchestrates pre-trade security and liquidity checks."""

    _shared_pool_fail_counter: Dict[str, int] = {}
    _shared_blacklisted_pools: Dict[str, float] = {}
    _shared_blacklist_duration: int = 3600

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        rpc_url: Optional[str] = None,
    ):
        self.session = session
        self.rpc_url = rpc_url
        self.security_checker = TokenSecurityChecker(session, rpc_url)
        self.liquidity_validator = LiquidityValidator(session, rpc_url)

    @property
    def pool_fail_counter(self) -> Dict[str, int]:
        return self.__class__._shared_pool_fail_counter

    @property
    def blacklisted_pools(self) -> Dict[str, float]:
        return self.__class__._shared_blacklisted_pools

    @property
    def blacklist_duration(self) -> int:
        return self.__class__._shared_blacklist_duration

    def record_failure(self, pool_id: str):
        """Record a trade failure for a pool."""
        self.pool_fail_counter[pool_id] = self.pool_fail_counter.get(pool_id, 0) + 1
        if self.pool_fail_counter[pool_id] >= 3:
            self.blacklisted_pools[pool_id] = time.time()
            logger.warning(
                f"🚫 Pool {pool_id} blacklisted for 1 hour after 3 failures."
            )

    def is_blacklisted(self, pool_id: str) -> bool:
        """Check if a pool is blacklisted."""
        if pool_id not in self.blacklisted_pools:
            return False

        if time.time() - self.blacklisted_pools[pool_id] > self.blacklist_duration:
            del self.blacklisted_pools[pool_id]
            self.pool_fail_counter[pool_id] = 0
            return False

        return True

    async def check_token_2022_transfer_fee(
        self, mint_address: Pubkey, rpc_url: Optional[str] = None
    ) -> Tuple[bool, float, str]:
        """
        Check Token-2022 TransferFeeConfig for hidden transfer taxes.

        Args:
            mint_address: Token mint Pubkey object
            rpc_url: Optional RPC URL override

        Returns:
            Tuple of (has_fee: bool, fee_bps: float, reason: str)
        """
        # Fix 73: Safe session fallback
        _session = self.session
        _session_owned = False
        if _session is None:
            try:
                _session = aiohttp.ClientSession()
                _session_owned = True
            except Exception as e:
                return False, 0.0, f"No HTTP session available: {e}"

        rpc_url = rpc_url or self.rpc_url
        if not rpc_url:
            if _session_owned:
                await _session.close()
            return False, 0.0, "No RPC URL provided"

        try:
            # Get mint account info
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [
                    str(mint_address),
                    {"encoding": "base64", "commitment": "confirmed"},
                ],
            }

            async with _session.post(rpc_url, json=payload) as resp:
                if resp.status != 200:
                    return False, 0.0, f"RPC error: HTTP {resp.status}"

                data = await resp.json()
                if "error" in data:
                    return False, 0.0, f"RPC error: {data['error']}"

                account_data = data.get("result", {}).get("value")
                if not account_data:
                    return False, 0.0, "Mint account not found"

                # Check if this is a Token-2022 mint
                owner = account_data.get("owner")
                if owner != str(TOKEN_2022_PROGRAM_ID):
                    return False, 0.0, "Not a Token-2022 mint"

                # Decode base64 data
                import base64

                data_b64 = account_data["data"][0]
                raw_data = base64.b64decode(data_b64 + "=" * (-len(data_b64) % 4))

                # Token-2022 TLV (Type-Length-Value) Parsing
                # Base Mint: 0-82 | Padding: 82-165 | AccountType: 165 | Extensions: 166+
                if len(raw_data) < 166:
                    return False, 0.0, "No extensions found in Token-2022 mint"

                # Iterate through extensions
                offset = 166
                while offset + 4 <= len(raw_data):
                    ext_type = struct.unpack("<H", raw_data[offset : offset + 2])[0]
                    ext_len = struct.unpack("<H", raw_data[offset + 2 : offset + 4])[0]

                    if ext_type == 11:  # TransferFeeConfig
                        # TransferFeeConfig layout (simplified):
                        # - Authorities: 64 bytes (2 * 32)
                        # - Withheld Amount: 8 bytes
                        # - Older Transfer Fee: 18 bytes (8 epoch + 8 max + 2 bps)
                        # - Newer Transfer Fee: 18 bytes (8 epoch + 8 max + 2 bps)
                        # Total extension length is typically 108 bytes.

                        # We care about the 'newer_transfer_fee' basis points.
                        # Offset within extension value: 32 + 32 + 8 + 18 + 16 = 106
                        if ext_len >= 108:
                            bps_offset = offset + 4 + 106
                            fee_bps = struct.unpack(
                                "<H", raw_data[bps_offset : bps_offset + 2]
                            )[0]

                            if fee_bps > 0:
                                fee_pct = fee_bps / 100.0
                                logger.info(
                                    f"🛡️ Token-2022 Transfer Fee detected: {fee_pct}% ({fee_bps} bps)"
                                )
                                return True, fee_pct, f"Transfer fee: {fee_pct}%"

                    # Move to next extension (must be 8-byte aligned)
                    offset += 4 + ext_len
                    # Note: SPL Token-2022 extensions are usually padded to 8 bytes,
                    # but the 'length' field doesn't include the padding.
                    # For simple sequential parsing, we just follow the length.

                return False, 0.0, "No transfer fee extension found"

        except Exception as e:
            logger.error(
                f"Error checking Token-2022 transfer fee for {mint_address}: {e}"
            )
            return False, 0.0, f"Check failed: {str(e)}"
        finally:
            if _session_owned:
                await _session.close()

    async def get_adjusted_profit_threshold(
        self,
        mint_address: Pubkey,
        base_profit_threshold: float,
        rpc_url: Optional[str] = None,
    ) -> float:
        """
        Get profit threshold adjusted for Token-2022 transfer fees.

        Args:
            mint_address: Token mint Pubkey
            base_profit_threshold: Base profit threshold in SOL
            rpc_url: Optional RPC URL

        Returns:
            Adjusted profit threshold accounting for transfer fees
        """
        has_fee, fee_pct, reason = await self.check_token_2022_transfer_fee(
            mint_address, rpc_url
        )

        if has_fee and fee_pct > 0:
            # Add transfer fee to required profit (assume fee applies to output amount)
            # Conservative estimate: add 2x the fee to account for round-trip
            adjustment_factor = 1 + (fee_pct / 100) * 2
            adjusted_threshold = base_profit_threshold * adjustment_factor

            logger.info(
                f"💰 Transfer fee adjustment for {mint_address}: {fee_pct:.2f}% "
                f"-> threshold {base_profit_threshold:.6f} -> {adjusted_threshold:.6f} SOL"
            )
            return adjusted_threshold
        else:
            return base_profit_threshold

    async def validate_trade_opportunity(
        self,
        mint_address: str,
        pool_id: Optional[str] = None,
        vault_address: Optional[str] = None,
        rpc_url: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Run complete pre-trade validation pipeline.

        Args:
            mint_address: Token mint address
            pool_id: Optional pool ID to check blacklist
            vault_address: Pool vault address
            rpc_url: Optional RPC URL override

        Returns:
            Tuple of (can_trade: bool, reason: str)
        """
        if pool_id and self.is_blacklisted(pool_id):
            return False, f"Pool {pool_id} is blacklisted"

        logger.debug(
            f"Running pre-trade validation for mint={mint_address}, vault={vault_address}"
        )

        # Step 1: Security check (fastest - analyze local data)
        logger.debug("Step 1: Security Shield check")
        is_secure, security_reason = await self.security_checker.check_token_security(
            mint_address, rpc_url
        )
        if not is_secure:
            logger.info(f"🚫 Trade aborted - Security check failed: {security_reason}")
            return False, security_reason

        # Step 2: Liquidity check (requires RPC call) - skip if no vault address
        if vault_address:
            logger.debug("Step 2: Ghost Liquidity Filter check")
            has_liquidity, liquidity_reason = (
                await self.liquidity_validator.validate_vault_balance(
                    vault_address, rpc_url
                )
            )
            if not has_liquidity:
                logger.info(
                    f"🚫 Trade aborted - Liquidity check failed: {liquidity_reason}"
                )
                return False, liquidity_reason
        else:
            logger.debug(
                "Step 2: Skipping vault validation (no vault address provided)"
            )

        logger.info(f"✅ Pre-trade validation passed for {mint_address}")
        return True, "All checks passed"

    async def validate_token_security(
        self, mint_address: str, rpc_url: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Validate only token security (for existing pools/arbitrage)."""
        logger.debug(f"Running security validation for mint={mint_address}")

        is_secure, security_reason = await self.security_checker.check_token_security(
            mint_address, rpc_url
        )
        if not is_secure:
            logger.info(f"🚫 Token security check failed: {security_reason}")
            return False, security_reason

        logger.debug(f"✅ Token security check passed for {mint_address}")
        return True, "Security check passed"

    # ─── Strict Gas Tank (Survival Floor) ───────────────────────────
    # Never let the wallet drop below Config.MIN_RESERVE_SOL. If we hit this level,
    # stop ALL trading immediately. At 0 SOL we can't even close ATAs to recover rent.
    @staticmethod
    def get_min_reserve_sol() -> float:
        """Get minimum reserve SOL from environment or default."""
        import os

        return float(os.getenv("MIN_RESERVE_SOL", "0.010"))

    # ─── Hard Floor Guard (Rent-Exemption Killswitch) ───────────────────────────
    # If native SOL balance drops below dynamic floor, we trigger emergency shutdown:
    # 1. Set GLOBAL_STOP_EVENT to stop all trading
    # 2. DustSweeper runs to close ATAs and recover rent
    # At 0.002 SOL the Solana network garbage-collector will DELETE the wallet account.

    @staticmethod
    def enforce_hard_floor(
        native_sol_balance: float, keypair=None, rpc_url=None, session=None
    ) -> None:
        """
        💀 Hard Floor Guard — absolute rent-exemption killswitch.

        If native_sol_balance < DynamicThresholds(native_sol_balance).hard_floor_sol,
        trigger graceful shutdown via GLOBAL_STOP_EVENT so DustSweeper can close ATAs
        and recover rent before the process dies.

        Args:
            native_sol_balance: Current wallet balance in SOL.
            keypair: Wallet keypair for emergency dust sweep.
            rpc_url: RPC URL for emergency dust sweep.
            session: aiohttp session for emergency dust sweep.
        """
        from src.ingest.flywheel_scaler import DynamicThresholds

        floor = DynamicThresholds(native_sol_balance).hard_floor_sol
        if native_sol_balance < floor:
            logger.critical(
                f"💀 RENT DEATH KILLSWITCH: Balance {native_sol_balance:.6f} SOL < "
                f"{floor:.6f} SOL — triggering emergency shutdown via GLOBAL_STOP_EVENT"
            )
            try:
                import src.ingest.shared_state as _ss

                _ss.GLOBAL_STOP_EVENT.set()
            except Exception:
                pass
            if keypair and rpc_url and session:
                try:
                    from src.ingest.dust_sweeper import DustSweeper

                    sweeper = DustSweeper(keypair, rpc_url, session)
                    asyncio.create_task(sweeper.sweep_on_shutdown())
                except Exception as sweep_err:
                    logger.warning(f"Emergency dust sweep failed: {sweep_err}")

    # ─── Main Wallet Rent-Exemption Killswitch ──────────────────────────────────
    # Urgent RPC-balance check: call this after every successful Jito bundle
    # confirmation and before any balance-tracking logic. Triggers killed process
    # on native_sol_balance < 0.0015 SOL to guarantee wallet is never garbage-
    # collected by the Solana network.

    MARGINFI_BASE_ACCOUNT = Pubkey.from_string(
        "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"
    )

    @staticmethod
    async def check_gas_tank(
        native_sol_balance: Optional[float] = None,
        num_new_atas: int = 0,
    ) -> Tuple[bool, float]:
        """
        🔋 Strict Gas Tank — последняя линия обороны капитала.

        Если нативный SOL-баланс падает ниже Config.MIN_RESERVE_SOL, мы ОСТАНАВЛИВАЕМ
        ВСЮ ТОРГОВЛЮ. Никаких сделок, никаких чаевых Jito, никаких
        флеш-лоанов. Бот должен сначала восстановить баланс (через
        dust_sweeper, внешний депозит, или ATA rent recovery).

        Args:
            native_sol_balance: Текущий баланс в SOL, или None для пропуска.
            num_new_atas: Количество новых ATA, которые будут созданы в сделке.
              Каждый требует ~0.00204 SOL rent, вычитаемого из available.

        Returns:
            Tuple[bool, float]:
              True  = достаточно газа, можно торговать.
              False = баланс на нуле — trading halted.
              Second element: available_sol = balance - gas_reserve - ata_rent.
        """
        if native_sol_balance is None:
            logger.warning(
                "🚫 check_gas_tank: native_sol_balance is None — fail-closed, blocking trade"
            )
            return False, 0.0  # Нет данных — fail-closed

        min_reserve = PreTradeGuard.get_min_reserve_sol()
        ata_rent = num_new_atas * 0.00204
        if native_sol_balance < min_reserve + ata_rent:
            logger.critical(
                f"🚨 STRICT GAS TANK: Balance {native_sol_balance:.6f} SOL < "
                f"{min_reserve + ata_rent:.6f} SOL (reserve {min_reserve} + "
                f"{num_new_atas} ATA rent {ata_rent:.6f}). TRADING HALTED. "
                f"Deposit SOL or run dust_sweeper to recover rent before resuming."
            )
            return False, 0.0

        available = native_sol_balance - min_reserve - ata_rent
        logger.debug(
            f"🔋 Gas Tank: {native_sol_balance:.6f} SOL → {available:.6f} SOL available "
            f"(reserve={min_reserve}, ata_rent={ata_rent:.6f} for {num_new_atas} new ATAs)"
        )
        return True, available

    # ─── Pre-Trade Profit Re-Check ─────────────────────────────────────────────

    async def check_profit_before_execution(
        self,
        input_mint: str,
        output_mint: str,
        amount_lamports: int,
        jito_tip_lamports: int,
        base_fee_lamports: int,
        expected_profit_lamports: int,
        quote_url: str = os.getenv(
            "JUPITER_QUOTE_API", "https://api.jup.ag/swap/v1/quote"
        ),
        slippage_bps: int = 30,
        is_circular: bool = False,
        priority_fee_lamports: int = 0,
        flashloan_fee_lamports: int = 0,
        ata_rent_lamports: int = 0,
        min_profit_lamports: int = 0,
    ) -> Tuple[bool, str, int]:
        """Re-check Jupiter price ~50 ms before signing/bundling the transaction.

        This is the **last line of defence**: between fetching a quote and sending the
        bundle 100-300 ms later the pool price may have moved enough to eat the expected
        profit entirely.  Aborting here is always cheaper than burning gas + Jito tip on
        a transaction that cannot be profitable.

        When `is_circular=True`, the route is cross-asset (e.g., USDC → xStock → USDC).
        A single-leg Jupiter quote cannot compute profit in this case — the full route
        simulation handles it. The check passes optimistically and delegates to the
        pre-trade simulator for the actual profitability verification.

        Full Cost Stack includes:
        - jito_tip_lamports: Jito searcher tip
        - base_fee_lamports: Network base fee
        - priority_fee_lamports: Compute unit priority fee
        - flashloan_fee_lamports: Flash loan provider fee (0 for MarginFi, else up to 0.1%)
        - ata_rent_lamports: ATA rent exemption for new accounts (2_039_280 lamports each)

        Args:
            input_mint:  Entry token mint string.
            output_mint: Exit token mint string.
            amount_lamports:      Size of the trade being executed.
            jito_tip_lamports:    Jito tip in lamports (deducts from profit).
            base_fee_lamports:    Network base fee in lamports.
            expected_profit_lamports:  Profit that was projected at quote time.
            quote_url:            Jupiter quote endpoint.
            slippage_bps:         Slippage tolerance for the re-check.
            is_circular:          True if route is cross-asset (USDC→xStock→USDC).
                                  Skips single-leg profit math — simulator handles it.
            priority_fee_lamports: Compute unit priority fee (SetComputeUnitPrice * CU limit).
            flashloan_fee_lamports: Flash loan provider fee (0 for MarginFi).
            ata_rent_lamports:    ATA rent for new accounts (2_039_280 per new ATA).

        Returns:
            Tuple[bool, str, int]:
              True  = still profitable, safe to go.
              False = profit eroded — abort.
              Third element: actual_profit_lamports (for caller audit/logging).
        """
        # Fix 70: Lazy session creation — if no session was provided at init,
        # create one on-the-fly to prevent AttributeError during pre-trade checks.
        if not self.session:
            try:
                self.session = aiohttp.ClientSession()
                logger.debug("Fix 70: Created ad-hoc aiohttp session for PreTradeGuard")
            except Exception as session_err:
                return False, f"No session available: {session_err}", 0

        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(
                int(amount_lamports)
            ),  # Task 16: strict int→string to avoid HTTP 400
            "slippageBps": str(slippage_bps),
            "maxAccounts": "28",
            "onlyDirectRoutes": "false",  # Fix B: allow multi-hop routes for triangular arbitrage
            "restrictIntermediateTokens": "false",  # Fix B: allow intermediate tokens for complex routes
        }

        try:
            now = time.time()
            # ИСПРАВЛЕНИЕ: Используем глобальный Jupiter лимитер для избежания HTTP 429
            from src.ingest.jupiter_api_client import get_jupiter_limiter

            limiter = get_jupiter_limiter()
            if limiter is not None:
                async with limiter:
                    async with self.session.get(
                        quote_url, params=params, timeout=2.0
                    ) as resp:
                        if resp.status != 200:
                            return (
                                False,
                                f"Pre-trade quote failed: HTTP {resp.status}",
                                0,
                            )
                        fresh_quote = await resp.json()
            else:
                async with self.session.get(
                    quote_url, params=params, timeout=2.0
                ) as resp:
                    if resp.status != 200:
                        return False, f"Pre-trade quote failed: HTTP {resp.status}", 0
                    fresh_quote = await resp.json()

            actual_out = int(
                fresh_quote.get("otherAmountThreshold", fresh_quote.get("outAmount", 0))
            )
            if actual_out == 0:
                return False, "Pre-trade quote: outAmount == 0", 0

            # Phase 12: Cross-Currency Accounting — convert actual_out to SOL lamports
            # before subtracting fees (which are denominated in SOL).
            # actual_out is in output_mint native units (e.g. USDC micro-units),
            # while all cost params are in SOL lamports. Subtracting directly
            # corrupts profit for non-SOL routes ("Apples to Oranges" bug).
            is_sol_route = output_mint == "So11111111111111111111111111111111111111112"
            _sol_price_usd = 150.0
            _output_price_usd = 1.0  # default: assume 1:1 with SOL

            # Phase 12: fetch prices via Pyth for cross-currency conversion.
            # If price fetch fails for a non-SOL route, delegate to simulator
            # by returning True (the simulator handles profitability verification).
            if not is_sol_route:
                try:
                    from src.ingest.pyth_core_price_feeder import get_pyth_core_feeder
                    feeder = get_pyth_core_feeder()
                    if feeder is not None:
                        _output_price_usd = feeder.get_price(output_mint) or 1.0
                        _sol_price_usd = feeder.get_price("So11111111111111111111111111111111111111112") or 150.0
                except Exception:
                    # Price feed unavailable — delegate to simulator for accuracy
                    logger.debug("Phase 12: Price feed unavailable for non-SOL route — delegating to simulator")
                    return True, "Price unavailable — delegate to simulator", 0

            # Convert actual_out from output_mint units to SOL lamports
            if is_sol_route:
                gross_profit_sol_lamports = actual_out - amount_lamports
            else:
                # Phase 12: expanded decimals mapping covering all active token types
                _decimals = {
                    # Stables (6 decimals)
                    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 6,  # USDC
                    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": 6,  # USDT
                    "2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo": 6,  # PYUSD
                    # SOL and LSTs (9 decimals)
                    "So11111111111111111111111111111111111111112": 9,  # wSOL
                    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn": 9,  # jitoSOL
                    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So": 9,  # mSOL
                    "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1": 9,  # bSOL
                    "jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v": 9,  # JupSOL
                    "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm": 9,  # INF
                    # Memes (variable decimals)
                    "DezXAZ8z7P8gVmFiDQ6cEhPmmF9rj3ZfVGg3LyZ3mTKV": 5,  # BONK
                    "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm": 6,  # WIF
                }.get(output_mint, 6)  # default 6 for unknown tokens
                amount_ui = amount_lamports / (10 ** _decimals)
                actual_out_ui = actual_out / (10 ** _decimals)
                # Step 2: convert gross profit to SOL via price bridge
                gross_profit_ui = actual_out_ui - amount_ui
                gross_profit_sol_lamports = int((gross_profit_ui * _output_price_usd / _sol_price_usd) * 1e9)

            # ── Define threshold BEFORE is_circular branch ─────────────────────
            threshold = min_profit_lamports if min_profit_lamports > 0 else 0

            # FIX is_circular: for cross-asset routes (USDC→xStock), single-leg
            # profit math is meaningless across asset boundaries, BUT we must still
            # mathematically verify that the fresh quote covers the trade size + total
            # cost. Previously this returned True unconditionally — a hole that let
            # unprofitable circular routes through to execution.
            if is_circular:
                total_cost_lamports = (
                    jito_tip_lamports
                    + base_fee_lamports
                    + priority_fee_lamports
                    + flashloan_fee_lamports
                    + ata_rent_lamports
                )
                # For circular routes, the gross profit is already in SOL lamports
                actual_net_profit = gross_profit_sol_lamports - total_cost_lamports
                if actual_net_profit < threshold:
                    logger.warning(
                        f"🚫 Circular route BLOCKED: net {actual_net_profit/1e9:.6f} SOL "
                        f"< threshold (cost {total_cost_lamports/1e9:.6f} SOL)"
                    )
                    return (
                        False,
                        f"Circular route unprofitable: net {actual_net_profit/1e9:.6f} SOL",
                        actual_net_profit,
                    )
                logger.debug(
                    f"🔄 Circular route OK: net≈{actual_net_profit/1e9:.6f} SOL "
                    f"(cost={total_cost_lamports/1e9:.6f} SOL)"
                )
                return (
                    True,
                    f"Circular route verified (net≈{actual_net_profit/1e9:.6f} SOL)",
                    actual_net_profit,
                )

            # Non-circular: gross_profit_sol_lamports already in SOL denomination
            total_cost_lamports = (
                jito_tip_lamports
                + base_fee_lamports
                + priority_fee_lamports
                + flashloan_fee_lamports
                + ata_rent_lamports
            )
            actual_net_profit = gross_profit_sol_lamports - total_cost_lamports

            latency_ms = (time.time() - now) * 1000
            logger.debug(
                f"🔍 Pre-trade re-check ({latency_ms:.0f}ms): "
                f"gross={gross_profit_sol_lamports/1e9:.6f} SOL | "
                f"cost={total_cost_lamports/1e9:.6f} SOL | "
                f"net={actual_net_profit/1e9:.6f} SOL"
            )

            if actual_net_profit < threshold:
                logger.warning(
                    f"🚫 Pre-trade BLOCKED: profit eroded to {actual_net_profit/1e9:.6f} SOL "
                    f"(tip={jito_tip_lamports/1e9:.6f} + fee={base_fee_lamports/1e9:.6f} = "
                    f"{total_cost_lamports/1e9:.6f} SOL, threshold={threshold/1e9:.6f} SOL)"
                )
                return (
                    False,
                    f"Profit eroded to {actual_net_profit/1e9:.6f} SOL (cost = {total_cost_lamports/1e9:.6f} SOL)",
                    actual_net_profit,
                )

            # Optional: compare with original expected profit
            profit_slipped_pct = (
                (expected_profit_lamports - actual_net_profit)
                / expected_profit_lamports
                if expected_profit_lamports > 0
                else 0.0
            )
            if profit_slipped_pct > 0.30:
                logger.warning(
                    f"⚠️ Pre-trade: profit slipped {profit_slipped_pct:.0%} "
                    f"({expected_profit_lamports/1e9:.6f} → {actual_net_profit/1e9:.6f} SOL)"
                )

            return (
                True,
                f"Pre-trade OK (net={actual_net_profit/1e9:.6f} SOL)",
                actual_net_profit,
            )

        except asyncio.TimeoutError:
            return False, "Pre-trade quote timed out", 0
        except Exception as e:
            logger.warning(f"Pre-trade re-check error: {e}")
            return False, f"Pre-trade check error: {e}", 0
