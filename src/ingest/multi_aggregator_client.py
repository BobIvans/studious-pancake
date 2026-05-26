"""
Multi-Aggregator Routing Client for MEV Arbitrage
Balances load across multiple DEX aggregators to avoid rate limits and RPC bans.
Provides unified interface for quotes, swaps, and instruction extraction.
"""

import asyncio
import aiohttp
import orjson
import logging
import random
import time
import os
from typing import Dict, List, Optional, Tuple, Any
from decimal import Decimal

logger = logging.getLogger(__name__)


class AggregatorClient:
    """Individual DEX aggregator client with unified interface."""

    def __init__(
        self,
        name: str,
        quote_url: str,
        swap_url: Optional[str] = None,
        headers: Optional[Dict] = None,
    ):
        self.name = name
        self.quote_url = quote_url
        self.swap_url = swap_url or quote_url.replace("/quote", "/swap")
        self.headers = headers or {}
        self.last_request = 0
        self.request_count = 0

    async def get_quote(
        self, session: aiohttp.ClientSession, params: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Get quote from this aggregator."""
        try:
            # Rate limiting: 1 request per second per aggregator
            elapsed = time.time() - self.last_request
            if elapsed < 1.0:
                await asyncio.sleep(1.0 - elapsed)

            url = self.quote_url

            async with session.get(url, params=params, headers=self.headers) as resp:
                if resp.status == 200:
                    raw_bytes = await resp.read()
                    data = orjson.loads(raw_bytes)
                    self.last_request = time.time()
                    self.request_count += 1
                    return {
                        "aggregator": self.name,
                        "data": data,
                        "timestamp": time.time(),
                    }
                else:
                    logger.debug(f"{self.name} quote failed: {resp.status}")
                    return None

        except Exception as e:
            logger.debug(f"{self.name} quote error: {e}")
            return None

    async def get_swap_instructions(
        self, session: aiohttp.ClientSession, params: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Get swap instructions from this aggregator."""
        try:
            # Rate limiting
            elapsed = time.time() - self.last_request
            if elapsed < 1.0:
                await asyncio.sleep(1.0 - elapsed)

            url = self.swap_url

            async with session.post(url, json=params, headers=self.headers) as resp:
                if resp.status == 200:
                    raw_bytes = await resp.read()
                    data = orjson.loads(raw_bytes)
                    self.last_request = time.time()
                    self.request_count += 1

                    # Extract instructions and ALT addresses
                    instructions = []
                    alt_addresses = []

                    # Parse aggregator-specific response format
                    if self.name == "jupiter":
                        if "swapTransaction" in data:
                            instructions = data.get("instructions", [])
                            alt_addresses = data.get("addressLookupTableAddresses", [])
                    elif self.name == "openocean":
                        # Parse OpenOcean format
                        if "data" in data and "tx" in data["data"]:
                            tx_data = data["data"]["tx"]
                            instructions = tx_data.get("instructions", [])
                            alt_addresses = tx_data.get(
                                "addressLookupTableAddresses", []
                            )
                    # Add other aggregators as needed

                    return {
                        "aggregator": self.name,
                        "instructions": instructions,
                        "addressLookupTableAddresses": alt_addresses,
                        "raw_response": data,
                        "timestamp": time.time(),
                    }
                else:
                    logger.debug(f"{self.name} swap instructions failed: {resp.status}")
                    return None

        except Exception as e:
            logger.debug(f"{self.name} swap instructions error: {e}")
            return None


class MultiAggregatorClient:
    """Load-balanced multi-aggregator client for DEX arbitrage."""

    def __init__(self):
        # Jupiter (primary, most reliable)
        _jupiter_api_key = os.getenv("JUPITER_API_KEY", "")
        _jupiter_headers = (
            {"Authorization": f"Bearer {_jupiter_api_key}"} if _jupiter_api_key else {}
        )
        self.jupiter = AggregatorClient(
            "jupiter",
            "https://quote-api.jup.ag/v6/quote",
            "https://quote-api.jup.ag/v6/swap",
            headers=_jupiter_headers,
        )

        # OpenOcean
        self.openocean = AggregatorClient(
            "openocean",
            "https://open-api.openocean.finance/v4/solana/quote",
            "https://open-api.openocean.finance/v4/solana/swap",
        )

        # OKX DEX
        self.okx = AggregatorClient(
            "okx",
            "https://web3.okx.com/api/v6/dex/aggregator/quote",
            "https://web3.okx.com/api/v6/dex/aggregator/swap",
        )

        # NEW: Odos Aggregator (strict RPS limiting for micro-balance safety)
        self.odos = AggregatorClient(
            "odos",
            os.getenv("ODOS_QUOTE_URL", "https://api.odos.xyz/sor/cat"),
            os.getenv("ODOS_SWAP_URL", "https://api.odos.xyz/sor/assemble"),
        )

        # Phase 26: Use proper time-based rate limiters instead of Semaphores
        self.jupiter_limiter = self._create_limiter(
            int(os.getenv("JUPITER_QUOTE_RPS", 5))
        )
        self.openocean_limiter = self._create_limiter(
            int(os.getenv("OPENOCEAN_RPS", 2))
        )
        self.okx_limiter = self._create_limiter(int(os.getenv("OKX_RPS", 5)))
        self.odos_limiter = self._create_limiter(
            int(os.getenv("ODOS_RPS", 1))
        )  # Strict 1 RPS

        self.aggregators = [self.jupiter, self.openocean, self.okx, self.odos]
        self.current_index = 0
        self.session = None

    def _create_limiter(self, rps: int):
        """Create async limiter for API calls (Phase 26)."""
        try:
            from aiolimiter import AsyncLimiter

            return AsyncLimiter(max(1, rps), 1.0)
        except ImportError:
            logger.warning("aiolimiter not installed, using naive limiter")

            # Fallback to a simple Semaphore-based limiter that adds a delay
            class NaiveLimiter:
                def __init__(self, rps):
                    self.semaphore = asyncio.Semaphore(1)
                    self.delay = 1.0 / rps

                async def __aenter__(self):
                    await self.semaphore.acquire()
                    return self

                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    # Don't block the worker! Schedule release in background
                    asyncio.get_running_loop().call_later(
                        self.delay, self.semaphore.release
                    )

            return NaiveLimiter(rps)

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def _get_next_aggregator(self) -> AggregatorClient:
        """Round-robin aggregator selection."""
        aggregator = self.aggregators[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.aggregators)
        return aggregator

    async def get_quote(
        self, input_mint: str, output_mint: str, amount: int, slippage_bps: int = 50
    ) -> Optional[Dict[str, Any]]:
        """Get quote from next aggregator in rotation with RPS limiting."""
        if not self.session:
            raise RuntimeError(
                "MultiAggregatorClient must be used as async context manager"
            )

        # Fix 1: Safe cast to str so Pubkey objects never reach HTTP params or Pubkey.from_string()
        input_mint = str(input_mint) if not isinstance(input_mint, str) else input_mint
        output_mint = (
            str(output_mint) if not isinstance(output_mint, str) else output_mint
        )

        # Try up to 4 aggregators (now includes Odos)
        for _ in range(4):
            aggregator = self._get_next_aggregator()

            # Apply independent limiter to prevent starvation (Jupiter 5 RPS won't block Gecko 0.5 RPS)
            limiter = getattr(self, f"{aggregator.name}_limiter", self.jupiter_limiter)
            async with limiter:

                anti_sandwich_bps = max(5, int(slippage_bps))
                params = {
                    "inputMint": str(input_mint),
                    "outputMint": str(output_mint),
                    "amount": str(int(amount)),  # Task 16: strict int→string to avoid HTTP 400
                    "slippageBps": str(anti_sandwich_bps),
                    "onlyDirectRoutes": "true",  # Task 14: force direct routes to block ATA creation on intermediate tokens
                    "restrictIntermediateTokens": "true",
                    "maxAccounts": "28",  # FIX 8: Increased from 8 to 28 — LST routing via Sanctum requires deep account graphs. ALTs keep TX within 1232-byte MTU.
                }

                # Adjust params for different aggregators
                if aggregator.name == "openocean":
                    params = {
                        "chain": "solana",
                        "inTokenAddress": str(input_mint),
                        "outTokenAddress": str(output_mint),
                        "amount": str(amount),
                        "gasPrice": "5",
                    }
                elif aggregator.name == "okx":
                    params = {
                        "chainId": "501",
                        "fromTokenAddress": str(input_mint),
                        "toTokenAddress": str(output_mint),
                        "amount": str(amount),
                        "slippage": str(slippage_bps / 100),
                    }
                elif aggregator.name == "odos":
                    # Odos specific format (strict RPS=1 enforced by limiter)
                    params = {
                        "chainId": 501,
                        "inputTokens": [
                            {"tokenAddress": str(input_mint), "amount": str(amount)}
                        ],
                        "outputTokens": [
                            {"tokenAddress": str(output_mint), "proportion": 1}
                        ],
                        "slippageLimitPercent": slippage_bps / 100,
                        "userAddr": "11111111111111111111111111111112",
                    }

            quote = await aggregator.get_quote(self.session, params)
            if quote:
                return quote

        logger.warning(f"All aggregators failed for {input_mint} -> {output_mint}")
        return None

    async def get_swap_instructions(
        self, quote_response: Dict[str, Any], user_public_key: str
    ) -> Optional[Tuple[List[Dict], List[str]]]:
        """Get swap instructions from aggregator that provided the quote."""
        if not self.session:
            raise RuntimeError(
                "MultiAggregatorClient must be used as async context manager"
            )

        aggregator_name = quote_response.get("aggregator")
        aggregator = None

        # Find the aggregator that provided the quote
        for agg in self.aggregators:
            if agg.name == aggregator_name:
                aggregator = agg
                break

        if not aggregator:
            logger.error(f"Unknown aggregator: {aggregator_name}")
            return None

        # Prepare swap request params
        if aggregator.name == "jupiter":
            params = {
                "quoteResponse": quote_response["data"],
                "userPublicKey": user_public_key,
                "wrapAndUnwrapSol": False,  # Critical: Don't auto-wrap SOL for flash loans
                "dynamicComputeUnitLimit": False,  # ФИКС: Исключает конфликт с нашим кастомным CU-билдером
            }
        elif aggregator.name == "openocean":
            # OpenOcean swap params
            params = quote_response["data"]
            params["userWallet"] = user_public_key
        elif aggregator.name == "okx":
            params = {
                "chainId": "501",
                "fromTokenAddress": quote_response["data"].get("fromTokenAddress"),
                "toTokenAddress": quote_response["data"].get("toTokenAddress"),
                "amount": quote_response["data"].get("fromTokenAmount"),
                "slippage": str(50 / 100),  # 0.5%
                "userWalletAddress": user_public_key,
            }
        elif aggregator.name == "odos":
            params = {
                "userAddr": user_public_key,
                "pathId": quote_response["data"].get("pathId"),
                "simulate": False,
            }

        result = await aggregator.get_swap_instructions(self.session, params)
        if result:
            instructions = result.get("instructions", [])
            alt_addresses = result.get("addressLookupTableAddresses", [])
            return instructions, alt_addresses

        return None

    def get_stats(self) -> Dict[str, Any]:
        """Get usage statistics for monitoring."""
        return {
            "jupiter_requests": self.jupiter.request_count,
        }
