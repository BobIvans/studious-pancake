"""
DexScreener Trend Scanner
Background task that discovers new "Blue Ocean" tokens on Solana.
Filters for liquidity and volume to avoid rugs.
Injects fresh mints into the scanning queue (with 30min TTL cache).
"""

import asyncio
import aiohttp
import logging
import os
from typing import List, Dict, Set
from datetime import datetime, timedelta
import orjson

logger = logging.getLogger(__name__)

class DexScreenerClient:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.base_url = os.getenv("DEXSCREENER_BASE_URL", "https://api.dexscreener.com")
        self.rps = int(os.getenv("DEXSCREENER_RPS", 4))
        self.semaphore = asyncio.Semaphore(self.rps)
        
        # TTL cache for dynamically discovered tokens (Phase 4: Memory Leak Prevention)
        self.discovered_tokens: Dict[str, datetime] = {}
        self.ttl_minutes = 30

    async def _fetch_trending(self) -> List[Dict]:
        """Fetch latest trending tokens on Solana."""
        async with self.semaphore:
            url = f"{self.base_url}/tokens/v1/solana"
            try:
                async with self.session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        data = orjson.loads(await resp.read())
                        return data if isinstance(data, list) else []
            except Exception as e:
                logger.warning(f"DexScreener fetch failed: {e}")
            await asyncio.sleep(1.0 / self.rps)
        return []

    def _filter_quality_tokens(self, tokens: List[Dict]) -> List[Dict]:
        """Filter tokens with liquidity > $50k and 1h volume > $10k."""
        quality = []
        for t in tokens:
            try:
                liq = float(t.get("liquidity", {}).get("usd", 0))
                vol = float(t.get("volume", {}).get("h1", 0))
                if liq > 50000 and vol > 10000:
                    quality.append(t)
            except (ValueError, TypeError):
                continue
        return quality

    async def dexscreener_scanner_loop(self, queue: asyncio.Queue):
        """Background task: continuously discover and inject new tokens."""
        while True:
            try:
                raw_tokens = await self._fetch_trending()
                quality_tokens = self._filter_quality_tokens(raw_tokens)

                new_injections = 0
                now = datetime.now()

                for token in quality_tokens[:10]:  # Limit per cycle
                    mint = token.get("baseToken", {}).get("address")
                    if not mint or mint in self.discovered_tokens:
                        continue

                    # TTL check
                    if mint in self.discovered_tokens:
                        if (now - self.discovered_tokens[mint]) > timedelta(minutes=self.ttl_minutes):
                            del self.discovered_tokens[mint]
                        else:
                            continue

                    # Inject into queue (paired with SOL and USDC)
                    opportunity = {
                        "type": "fresh_listing",
                        "mint": mint,
                        "symbol": token.get("baseToken", {}).get("symbol", "???"),
                        "liquidity_usd": token.get("liquidity", {}).get("usd"),
                        "volume_1h": token.get("volume", {}).get("h1"),
                        "timestamp": now.isoformat()
                    }
                    # Fix 1: queue must be (priority, path_tuple) to match arb_bot worker
                    SOL_MINT = "So11111111111111111111111111111111111111112"
                    try:
                        queue.put_nowait((2, (SOL_MINT, mint)))
                    except asyncio.QueueFull:
                        pass  # HFT: stale data is trash — drop it, don't deadlock
                    self.discovered_tokens[mint] = now
                    new_injections += 1

                if new_injections > 0:
                    logger.info(f"🔍 DexScreener injected {new_injections} new tokens into queue")

                # Clean expired TTL entries
                expired = [k for k, v in self.discovered_tokens.items() 
                          if (now - v) > timedelta(minutes=self.ttl_minutes)]
                for k in expired:
                    del self.discovered_tokens[k]

            except Exception as e:
                logger.error(f"DexScreener scanner error: {e}")

            await asyncio.sleep(60)  # Scan every minute (respecting RPS)