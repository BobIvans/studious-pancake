"""
Multi-Aggregator Routing Client for MEV Arbitrage
Balances load across multiple DEX aggregators to avoid rate limits and RPC bans.
Provides unified interface for quotes, swaps, and instruction extraction.
"""

import asyncio
import socket
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
        """Get quote from this aggregator.

        Fix 51: Manual rate-limit sleep removed — parent MultiAggregatorClient
        already enforces RPS via independent AsyncLimiter per aggregator.
        """
        try:

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
            {"x-api-key": _jupiter_api_key} if _jupiter_api_key else {}
        )
        self.jupiter = AggregatorClient(
            "jupiter",
            os.getenv("JUPITER_QUOTE_API", "https://api.jup.ag/swap/v1/quote"),
            os.getenv("JUPITER_SWAP_URL", "https://api.jup.ag/swap/v1/swap"),
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
        connector = aiohttp.TCPConnector(limit=150, ttl_dns_cache=300, family=socket.AF_INET)
        self.session = aiohttp.ClientSession(connector=connector)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def _get_next_aggregator(self) -> AggregatorClient:
        """Round-robin aggregator selection."""
        aggregator = self.aggregators[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.aggregators)
        return aggregator

    async def _race_single_aggregator(
        self,
        aggregator: AggregatorClient,
        limiter,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Task 12: Fire a quote request to a single aggregator through its rate limiter.
        This is wrapped in an asyncio task for the concurrent race pattern.
        """
        async with limiter:
            anti_sandwich_bps = max(5, int(slippage_bps))

            if aggregator.name == "jupiter":
                params = {
                    "inputMint": str(input_mint),
                    "outputMint": str(output_mint),
                    "amount": str(int(amount)),
                    "slippageBps": str(anti_sandwich_bps),
                    "onlyDirectRoutes": "true",
                    "restrictIntermediateTokens": "true",
                    "maxAccounts": "28",
                }
            elif aggregator.name == "openocean":
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
            else:
                params = {
                    "inputMint": str(input_mint),
                    "outputMint": str(output_mint),
                    "amount": str(int(amount)),
                    "slippageBps": str(anti_sandwich_bps),
                }

            return await aggregator.get_quote(self.session, params)

    async def get_quote(
        self, input_mint: str, output_mint: str, amount: int, slippage_bps: int = 50
    ) -> Optional[Dict[str, Any]]:
        """
        Task 12: Concurrent Aggregator Racing (Promise.any pattern).
        Fires HTTP requests to ALL healthy aggregators simultaneously using
        asyncio.wait(FIRST_COMPLETED). Takes the fastest profitable quote,
        immediately cancels remaining pending tasks.

        This replaces the old sequential loop (for _ in range(4):) which
        waited 300-400ms per aggregator before trying the next one.
        """
        if not self.session:
            raise RuntimeError(
                "MultiAggregatorClient must be used as async context manager"
            )

        # Fix 1: Safe cast to str so Pubkey objects never reach HTTP params
        input_mint = str(input_mint) if not isinstance(input_mint, str) else input_mint
        output_mint = (
            str(output_mint) if not isinstance(output_mint, str) else output_mint
        )

        # ── Task 12: Fire ALL aggregators concurrently ───────────────────────
        # Create one task per aggregator. Each task acquires its own rate limiter
        # (Jupiter 5 RPS, OpenOcean 2 RPS, OKX 5 RPS, Odos 1 RPS) autonomously.
        tasks = []
        aggregator_map: Dict[int, str] = {}  # task_id -> aggregator_name

        for aggregator in self.aggregators:
            limiter = getattr(self, f"{aggregator.name}_limiter", self.jupiter_limiter)
            task = asyncio.create_task(
                self._race_single_aggregator(
                    aggregator,
                    limiter,
                    input_mint,
                    output_mint,
                    amount,
                    slippage_bps,
                )
            )
            tasks.append(task)
            aggregator_map[id(task)] = aggregator.name

        # ── Race: wait for FIRST_COMPLETED ───────────────────────────────────
        pending = set(tasks)
        start_race = time.time()
        timeout = 4.0  # Hard timeout — if no aggregator responds in 4s, fail

        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=timeout,
                )

                for task in done:
                    try:
                        result = task.result()
                        if result is not None and result.get("data") is not None:
                            # First profitable/valid quote received!
                            race_ms = (time.time() - start_race) * 1000
                            winner = aggregator_map.get(id(task), "unknown")
                            logger.debug(
                                f"🏁 Aggregator race won by {winner} "
                                f"in {race_ms:.0f}ms for {input_mint[:8]}->{output_mint[:8]}"
                            )

                            # Cancel all pending tasks immediately
                            for t in pending:
                                t.cancel()

                            return result
                    except Exception as task_err:
                        logger.debug(f"Aggregator race task failed: {task_err}")

                # All completed tasks failed — continue waiting on the rest
                if not pending:
                    break

                # Shrink timeout to remaining time
                elapsed = time.time() - start_race
                if elapsed >= 4.0:
                    break
                timeout = max(0.1, 4.0 - elapsed)

        finally:
            # Ensure all tasks are properly cleaned up
            # Note: asyncio.wait() with timeout does NOT raise TimeoutError —
            # it simply returns whatever tasks completed. The while-loop above
            # handles the timeout naturally by reducing the remaining timeout.
            for t in pending:
                t.cancel()
            # Fire-and-forget: do NOT await cancelled tasks in the hot path.
            # A stuck task (bad socket / library swallowing CancelledError) would
            # deadlock get_quote forever. Let them die in the background.

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
