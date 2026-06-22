"""Jupiter API client for Solana swaps and quotes."""

import asyncio
import base64
import logging
import os
import time
from typing import Any, Dict, Optional
import aiohttp
import orjson
from solders.transaction import VersionedTransaction

logger = logging.getLogger(__name__)

_GLOBAL_JUPITER_LIMITER = None
_limiter_available = False

def get_jupiter_limiter():
    global _GLOBAL_JUPITER_LIMITER, _limiter_available
    if _GLOBAL_JUPITER_LIMITER is None:
        try:
            from aiolimiter import AsyncLimiter
            _GLOBAL_JUPITER_LIMITER = AsyncLimiter(4, 1.0)
            _limiter_available = True
        except ImportError:
            _GLOBAL_JUPITER_LIMITER = None
            _limiter_available = False
    return _GLOBAL_JUPITER_LIMITER

# Jupiter API endpoints — динамически из .env
QUOTE_API_URL = os.getenv("JUPITER_QUOTE_API", "https://api.jup.ag/swap/v1/quote")
SWAP_API_URL = os.getenv("JUPITER_SWAP_URL", "https://api.jup.ag/swap/v1/swap")
SWAP_INSTRUCTIONS_API_URL = os.getenv("SWAP_INSTRUCTIONS_API_URL", "https://api.jup.ag/swap/v1/swap-instructions")

class JupiterClient:
    """Async client for Jupiter API operations."""

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
    ):
        self.session = session
        self.timeout = timeout
        self.max_retries = max_retries
        self._session_owned = session is None

    async def __aenter__(self):
        if self._session_owned and self.session is None:
            connector = aiohttp.TCPConnector(
                limit=150,
                limit_per_host=30,
                ttl_dns_cache=300,
                use_dns_cache=True,
                keepalive_timeout=60
            )
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=12, sock_connect=8, sock_read=10),
                headers={"User-Agent": "Mozilla/5.0"}
            )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session_owned and self.session:
            await self.session.close()

    async def get_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int = 50,
        *,
        fee_bps: Optional[int] = None,
        only_direct_routes: bool = False,
        as_legacy_transaction: bool = False,
        swap_mode: str = "ExactIn", # Task 16: ExactOut support
        wallet_balance_sol: float = 0.015, # Task 1: Dynamic Routing
    ) -> Dict[str, Any]:
        """Get quote from Jupiter API.

        Args:
            input_mint: Input token mint address
            output_mint: Output token mint address
            amount: Amount in smallest units (e.g., lamports for SOL)
            slippage_bps: Slippage tolerance in basis points (default: 50 = 0.5%)
            fee_bps: Platform fee in basis points (optional)
            only_direct_routes: Explicit override for direct routes
            as_legacy_transaction: Whether to return legacy transaction format
            swap_mode: "ExactIn" or "ExactOut"
            wallet_balance_sol: Current wallet balance to determine routing complexity

        Returns:
            Quote response from Jupiter API
        """
        if not self.session:
            raise RuntimeError("Client session not available")

        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(int(amount)),  # Task 16: strict int→string to avoid HTTP 400
            "slippageBps": slippage_bps,
            "swapMode": swap_mode, # Task 16
            "onlyDirectRoutes": str(only_direct_routes).lower(),
            "restrictIntermediateTokens": "false", # Let Jupiter find triangular arbs
            "cache_buster": str(time.time_ns()),  # Task 1: Anti-cache bomb for HFT
        }

        if fee_bps is not None:
            params["feeBps"] = str(fee_bps)

        # Task 14: ATA Routing Drain mitigation (maxAccounts=8)
        params["maxAccounts"] = "8"  # FIX 8: Lowered to 8 for micro-balance safety (prevent ATA drain)

        if as_legacy_transaction:
            params["asLegacyTransaction"] = "true"

        for attempt in range(self.max_retries):
            try:
                limiter = get_jupiter_limiter()
                if limiter is not None:
                    async with limiter:
                        async with self.session.get(
                            QUOTE_API_URL,
                            params=params,
                            timeout=self.timeout,
                        ) as response:
                            if response.status == 200:
                                result = orjson.loads(await response.read())
                                result["fetched_at"] = time.time()  # Task 13: Stale Quote Guard
                                logger.debug(f"Successfully got quote for {input_mint} -> {output_mint}")
                                return result
                            elif response.status == 429:
                                # FIX 13: 429 Too Many Requests — mandatory 2.0s backoff
                                logger.warning(f"Jupiter 429 rate limit hit — backoff 2.0s (attempt {attempt + 1})")
                                await asyncio.sleep(2.0)
                                continue
                            else:
                                error_text = await response.text()
                                logger.warning(f"Quote API error (attempt {attempt + 1}): {response.status} - {error_text}")

                                if attempt == self.max_retries - 1:
                                    return {
                                        "error": f"HTTP {response.status}: {error_text}",
                                        "inputMint": input_mint,
                                        "outputMint": output_mint,
                                        "amount": str(amount),
                                    }
                else:
                    async with self.session.get(
                        QUOTE_API_URL,
                        params=params,
                        timeout=self.timeout,
                    ) as response:
                        if response.status == 200:
                            result = orjson.loads(await response.read())
                            logger.debug(f"Successfully got quote for {input_mint} -> {output_mint}")
                            return result
                        elif response.status == 429:
                            logger.warning(f"Jupiter 429 rate limit hit — backoff 2.0s (attempt {attempt + 1})")
                            await asyncio.sleep(2.0)
                            continue
                        else:
                            error_text = await response.text()
                            logger.warning(f"Quote API error (attempt {attempt + 1}): {response.status} - {error_text}")

                            if attempt == self.max_retries - 1:
                                return {
                                    "error": f"HTTP {response.status}: {error_text}",
                                    "inputMint": input_mint,
                                    "outputMint": output_mint,
                                    "amount": str(amount),
                                }

            except asyncio.TimeoutError:
                logger.warning(f"Quote API timeout (attempt {attempt + 1})")
                if attempt == self.max_retries - 1:
                    return {
                        "error": "Request timeout",
                        "inputMint": input_mint,
                        "outputMint": output_mint,
                        "amount": str(amount),
                    }

            except Exception as e:
                logger.error(f"Quote API error (attempt {attempt + 1}): {e}")
                if attempt == self.max_retries - 1:
                    return {
                        "error": str(e),
                        "inputMint": input_mint,
                        "outputMint": output_mint,
                        "amount": str(amount),
                    }

            # Wait before retry
            await asyncio.sleep(0.5 * (2 ** attempt))

        return {
            "error": "Max retries exceeded",
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
        }

    async def get_swap_transaction(
        self,
        quote_response: Dict[str, Any],
        user_public_key: str,
        *,
        wrap_unwrap_sol: bool = False,
        fee_account: Optional[str] = None,
        tracking_account: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get swap transaction from Jupiter API.

        Args:
            quote_response: Quote response from get_quote()
            user_public_key: User's public key as string
            wrap_unwrap_sol: Whether to auto-wrap/unwrap SOL (default: False)
            fee_account: Fee account for platform fees (optional)
            tracking_account: Tracking account for analytics (optional)

        Returns:
            Swap transaction response with base64 encoded transaction
        """
        if not self.session:
            raise RuntimeError("Client session not available")

        if "error" in quote_response:
            return {
                "error": f"Invalid quote: {quote_response.get('error')}",
                "quote_response": quote_response,
            }

        # Strip injected keys that Jupiter's Rust backend rejects
        clean_quote = {k: v for k, v in quote_response.items() if k != "fetched_at"}

        payload = {
            "quoteResponse": clean_quote,
            "userPublicKey": user_public_key,
            "wrapAndUnwrapSol": wrap_unwrap_sol,
            "dynamicComputeUnitLimit": False,  # ФИКС: Исключает конфликт с нашим кастомным CU-билдером
            "asVersionedTransaction": True,    # As specified in requirements
            "prioritizationFeeLamports": "auto",  # ФИКС: Priority fee для избежания зависания в мемпуле
        }

        if fee_account:
            payload["feeAccount"] = fee_account

        if tracking_account:
            payload["trackingAccount"] = tracking_account

        for attempt in range(self.max_retries):
            try:
                limiter = get_jupiter_limiter()
                if limiter is not None:
                    async with limiter:
                        async with self.session.post(
                            SWAP_API_URL,
                            json=payload,
                            headers={"Content-Type": "application/json"},
                            timeout=self.timeout,
                        ) as response:
                            if response.status == 200:
                                result = orjson.loads(await response.read())
                                logger.debug(f"Successfully got swap transaction for user {user_public_key}")
                                return result
                            elif response.status == 429:
                                logger.warning(f"Jupiter swap 429 rate limit hit — backoff 2.0s (attempt {attempt + 1})")
                                await asyncio.sleep(2.0)
                                continue
                            else:
                                error_text = await response.text()
                                logger.warning(f"Swap API error (attempt {attempt + 1}): {response.status} - {error_text}")
                                if attempt == self.max_retries - 1:
                                    return {
                                        "error": f"HTTP {response.status}: {error_text}",
                                        "quote_response": quote_response,
                                        "user_public_key": user_public_key,
                                    }
                else:
                    async with self.session.post(
                        SWAP_API_URL,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                        timeout=self.timeout,
                    ) as response:
                        if response.status == 200:
                            result = orjson.loads(await response.read())
                            logger.debug(f"Successfully got swap transaction for user {user_public_key}")
                            return result
                        elif response.status == 429:
                            logger.warning(f"Jupiter swap 429 rate limit hit — backoff 2.0s (attempt {attempt + 1})")
                            await asyncio.sleep(2.0)
                            continue
                        else:
                            error_text = await response.text()
                            logger.warning(f"Swap API error (attempt {attempt + 1}): {response.status} - {error_text}")
                            if attempt == self.max_retries - 1:
                                return {
                                    "error": f"HTTP {response.status}: {error_text}",
                                    "quote_response": quote_response,
                                    "user_public_key": user_public_key,
                                }

            except asyncio.TimeoutError:
                logger.warning(f"Swap API timeout (attempt {attempt + 1})")
                if attempt == self.max_retries - 1:
                    return {
                        "error": "Request timeout",
                        "quote_response": quote_response,
                        "user_public_key": user_public_key,
                    }

            except Exception as e:
                logger.error(f"Swap API error (attempt {attempt + 1}): {e}")
                if attempt == self.max_retries - 1:
                    return {
                        "error": str(e),
                        "quote_response": quote_response,
                        "user_public_key": user_public_key,
                    }

            # Wait before retry
            await asyncio.sleep(0.5 * (2 ** attempt))

        return {
            "error": "Max retries exceeded",
            "quote_response": quote_response,
            "user_public_key": user_public_key,
        }

    @staticmethod
    def decode_swap_transaction(swap_response: Dict[str, Any]) -> Optional[VersionedTransaction]:
        """Decode base64 swap transaction to VersionedTransaction object.

        Args:
            swap_response: Response from get_swap_transaction()

        Returns:
            VersionedTransaction object or None if decoding fails
        """
        if "error" in swap_response:
            logger.error(f"Cannot decode transaction with error: {swap_response['error']}")
            return None

        swap_transaction_data = swap_response.get("swapTransaction")
        if not swap_transaction_data:
            logger.error("No swapTransaction field in response")
            return None

        try:
            # Jupiter returns the transaction as base64 string
            if isinstance(swap_transaction_data, str):
                # Decode base64 to bytes — with padding guard for Helius/QuickNode.
                # Some RPC providers strip trailing '='; dynamic padding always matches b64decode.
                padded_tx = swap_transaction_data + "=" * (-len(swap_transaction_data) % 4)
                transaction_bytes = base64.b64decode(padded_tx)
            else:
                logger.error(f"Unexpected swapTransaction format: {type(swap_transaction_data)}")
                return None

            # Parse bytes into VersionedTransaction
            transaction = VersionedTransaction.from_bytes(transaction_bytes)
            logger.debug("Successfully decoded swap transaction")
            return transaction

        except Exception as e:
            logger.error(f"Failed to decode swap transaction: {e}")
            return None

    async def get_quote_and_transaction(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        user_public_key: str,
        slippage_bps: int = 50,
        *,
        wrap_unwrap_sol: bool = False,
        fee_account: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Convenience method to get both quote and transaction in one call.

        Args:
            input_mint: Input token mint address
            output_mint: Output token mint address
            amount: Amount in smallest units
            user_public_key: User's public key as string
            slippage_bps: Slippage tolerance in basis points
            wrap_unwrap_sol: Whether to auto-wrap/unwrap SOL
            fee_account: Fee account for platform fees

        Returns:
            Dict containing quote, transaction data, and decoded VersionedTransaction
        """
        # Get quote first
        quote = await self.get_quote(input_mint, output_mint, amount, slippage_bps)
        if "error" in quote:
            return {
                "success": False,
                "error": quote["error"],
                "quote": quote,
            }

        # Get swap transaction
        swap_tx = await self.get_swap_transaction(
            quote, user_public_key, wrap_unwrap_sol=wrap_unwrap_sol, fee_account=fee_account
        )
        if "error" in swap_tx:
            return {
                "success": False,
                "error": swap_tx["error"],
                "quote": quote,
                "swap_transaction": swap_tx,
            }

        # Decode transaction
        decoded_tx = self.decode_swap_transaction(swap_tx)

        return {
            "success": True,
            "quote": quote,
            "swap_transaction": swap_tx,
            "decoded_transaction": decoded_tx,
            "input_mint": input_mint,
            "output_mint": output_mint,
            "amount": amount,
            "user_public_key": user_public_key,
            "slippage_bps": slippage_bps,
        }