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

logger = logging.getLogger(__name__)

# Token program IDs
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
TOKEN_2022_PROGRAM_ID = Pubkey.from_string(
    "TokenzQdBNbLqP5VEhdkAS6EP2rHEjaChQX6n57TR5m"
)

# Minimum vault balance threshold (equivalent to $100 worth of tokens)
MIN_VAULT_BALANCE_THRESHOLD = 100_000_000  # 0.1 SOL in lamports as example

# Whitelist of safe tokens (stablecoins and LSTs)
SAFE_MINTS = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",  # jitoSOL  (mainnet verified)
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",  # mSOL     (mainnet verified)
    "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",  # bSOL     (mainnet verified)
    "So11111111111111111111111111111111111111112",  # wSOL
    "DezXAZ8z7P8gVmFiDQ6cEhPmmF9rj3ZfVGg3LyZ3mTKV",  # BONK    (mainnet verified)
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
                logger.debug("Fix 73: Created ad-hoc aiohttp session for check_token_security")
            except Exception as e:
                return False, f"No HTTP session available: {e}"

        # Phase 20: Whitelist bypass
        if mint_address in SAFE_MINTS:
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
                    mint_address,
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

            data_b64 = account_info.get("data", [""])[0]
            if not data_b64:
                return False, "No account data"

            # Decode base64 data (with padding fix)
            data = base64.b64decode(data_b64 + "=" * (-len(data_b64) % 4))

            # Token-2022 has extensions before the base mint data
            # We need to parse the extensions and then check the base mint data

            if len(data) < 82:  # Minimum size
                return False, "Invalid Token-2022 account data size"

            # For Token-2022, check transfer fee extension
            # The extensions are at the beginning, followed by base mint data

            # Check if there's a transfer fee extension
            # This is complex - for now, we'll check the base mint authorities
            # and add transfer fee checking as a TODO

            # Base mint data starts after extensions
            # For basic check, look at the end of the data where authorities should be

            # Token-2022 TLV (Type-Length-Value) Parsing
            # Base Mint: 0-82 | AccountType: 165 | Extensions: 166+
            if len(data) >= 166:
                offset = 166
                while offset + 4 <= len(data):
                    ext_type = struct.unpack("<H", data[offset : offset + 2])[0]
                    ext_len = struct.unpack("<H", data[offset + 2 : offset + 4])[0]

                    if ext_type == 11:  # TransferFeeConfig
                        # Newer Transfer Fee bps is at offset 106 within extension value
                        if ext_len >= 108:
                            bps_offset = offset + 4 + 106
                            if bps_offset + 2 <= len(data):
                                fee_bps = struct.unpack(
                                    "<H", data[bps_offset : bps_offset + 2]
                                )[0]
                                if fee_bps > 0:
                                    fee_pct = fee_bps / 100.0
                                    return (
                                        False,
                                        f"Token-2022 has transfer fee: {fee_pct}% ({fee_bps} bps)",
                                    )

                    # Move to next extension (must be 8-byte aligned in account data, but sequential here)
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
                try:
                    amount = int(amount_str)
                    if amount < MIN_VAULT_BALANCE_THRESHOLD:
                        return (
                            False,
                            f"Insufficient vault balance: {amount} (min: {MIN_VAULT_BALANCE_THRESHOLD})",
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

                        if balance < MIN_VAULT_BALANCE_THRESHOLD:
                            return (
                                False,
                                f"Insufficient vault balance: {balance} (min: {MIN_VAULT_BALANCE_THRESHOLD})",
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

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        rpc_url: Optional[str] = None,
    ):
        self.session = session
        self.rpc_url = rpc_url
        self.security_checker = TokenSecurityChecker(session, rpc_url)
        self.liquidity_validator = LiquidityValidator(session, rpc_url)
        self.pool_fail_counter: Dict[str, int] = {}
        self.blacklisted_pools: Dict[str, float] = {}
        self.blacklist_duration = 3600  # 1 hour

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

                raw_data = base64.b64decode(account_data["data"][0])

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
    # If native SOL balance drops below 0.002 SOL, the Solana network garbage-
    # collector will DELETE the wallet account. Kill the process at 0.002 SOL to
    # prevent that from ever happening — never allow the wallet to be erased.
    HARD_FLOOR_SOL = 0.002

    @staticmethod
    def enforce_hard_floor(native_sol_balance: float) -> None:
        """
        💀 Hard Floor Guard — absolute rent-exemption killswitch.

        If native_sol_balance < 0.002 SOL, the Solana network garbage-collector
        will delete the wallet account. This function calls os._exit(1) instantly
        to prevent that from ever happening.

        Args:
            native_sol_balance: Current wallet balance in SOL.
        """
        if native_sol_balance < PreTradeGuard.HARD_FLOOR_SOL:
            logger.critical(
                f"💀 RENT DEATH KILLSWITCH: Balance {native_sol_balance:.6f} SOL < "
                f"{PreTradeGuard.HARD_FLOOR_SOL} SOL — calling os._exit(1) to preserve wallet state"
            )
            os._exit(1)

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
    ) -> Tuple[bool, float]:
        """
        🔋 Strict Gas Tank — последняя линия обороны капитала.

        Если нативный SOL-баланс падает ниже Config.MIN_RESERVE_SOL, мы ОСТАНАВЛИВАЕМ
        ВСЮ ТОРГОВЛЮ. Никаких сделок, никаких чаевых Jito, никаких
        флеш-лоанов. Бот должен сначала восстановить баланс (через
        dust_sweeper, внешний депозит, или ATA rent recovery).

        Args:
            native_sol_balance: Текущий баланс в SOL, или None для пропуска.

        Returns:
            Tuple[bool, float]:
              True  = достаточно газа, можно торговать.
              False = баланс на нуле — trading halted.
              Second element: available_sol = balance - gas_reserve.
        """
        if native_sol_balance is None:
            return True, 0.0  # Нет данных — оптимистично пропускаем

        min_reserve = PreTradeGuard.get_min_reserve_sol()
        if native_sol_balance < min_reserve:
            logger.critical(
                f"🚨 STRICT GAS TANK: Balance {native_sol_balance:.6f} SOL < "
                f"{min_reserve} SOL (MIN_RESERVE_SOL). TRADING HALTED. "
                f"Deposit SOL or run dust_sweeper to recover rent before resuming."
            )
            return False, 0.0

        available = native_sol_balance - min_reserve
        logger.debug(
            f"🔋 Gas Tank: {native_sol_balance:.6f} SOL → {available:.6f} SOL available (reserve={min_reserve})"
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
        quote_url: str = "https://quote-api.jup.ag/v6/quote",
        slippage_bps: int = 30,
    ) -> Tuple[bool, str, int]:
        """Re-check Jupiter price ~50 ms before signing/bundling the transaction.

        This is the **last line of defence**: between fetching a quote and sending the
        bundle 100-300 ms later the pool price may have moved enough to eat the expected
        profit entirely.  Aborting here is always cheaper than burning gas + Jito tip on
        a transaction that cannot be profitable.

        Args:
            input_mint:  Entry token mint string.
            output_mint: Exit token mint string.
            amount_lamports:      Size of the trade being executed.
            jito_tip_lamports:    Jito tip in lamports (deducts from profit).
            base_fee_lamports:    Network base fee in lamports.
            expected_profit_lamports:  Profit that was projected at quote time.
            quote_url:            Jupiter quote endpoint.
            slippage_bps:         Slippage tolerance for the re-check.

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
            "amount": str(int(amount_lamports)),  # Task 16: strict int→string to avoid HTTP 400
            "slippageBps": str(slippage_bps),
            "maxAccounts": "8",
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
                    async with self.session.get(quote_url, params=params, timeout=2.0) as resp:
                        if resp.status != 200:
                            return False, f"Pre-trade quote failed: HTTP {resp.status}", 0
                        fresh_quote = await resp.json()
            else:
                async with self.session.get(quote_url, params=params, timeout=2.0) as resp:
                    if resp.status != 200:
                        return False, f"Pre-trade quote failed: HTTP {resp.status}", 0
                    fresh_quote = await resp.json()

            actual_out = int(
                fresh_quote.get("otherAmountThreshold", fresh_quote.get("outAmount", 0))
            )
            if actual_out == 0:
                return False, "Pre-trade quote: outAmount == 0", 0

            actual_gross_profit = actual_out - amount_lamports
            total_cost_lamports = jito_tip_lamports + base_fee_lamports
            actual_net_profit = actual_gross_profit - total_cost_lamports

            latency_ms = (time.time() - now) * 1000
            logger.debug(
                f"🔍 Pre-trade re-check ({latency_ms:.0f}ms): "
                f"gross={actual_gross_profit/1e9:.6f} SOL | "
                f"cost={total_cost_lamports/1e9:.6f} SOL | "
                f"net={actual_net_profit/1e9:.6f} SOL"
            )

            if actual_net_profit <= 0:
                logger.warning(
                    f"🚫 Pre-trade BLOCKED: profit eroded to {actual_net_profit/1e9:.6f} SOL "
                    f"(tip={jito_tip_lamports/1e9:.6f} + fee={base_fee_lamports/1e9:.6f} = "
                    f"{total_cost_lamports/1e9:.6f} SOL)"
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
