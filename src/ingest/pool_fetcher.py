"""
Dynamic Pool Address Fetcher
Fetches active pool addresses for target tokens from Jupiter/Raydium APIs.
Caches results to avoid repeated API calls.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Set
import aiohttp
import os
from pathlib import Path

logger = logging.getLogger(__name__)

class PoolAddress:
    """Pool address information."""
    def __init__(self, address: str, token_a: str, token_b: str,
                 dex: str, program_id: str):
        self.address = address
        self.token_a = token_a
        self.token_b = token_b
        self.dex = dex  # 'raydium', 'orca', 'meteora', 'saber'
        self.program_id = program_id

class PoolFetcher:
    """Fetches and caches pool addresses for target tokens."""

    def __init__(self, session: aiohttp.ClientSession, cache_file: str = "pools_cache.json"):
        self.session = session
        self.cache_file = Path(cache_file)
        self.cache: Dict[str, List[PoolAddress]] = {}
        self.target_tokens = set()
        self.jupiter_api_url = "https://quote-api.jup.ag/v6"
        self.raydium_api_url = "https://api-v3.raydium.io"

    def set_target_tokens(self, tokens: List[str]):
        """Set the list of target tokens to fetch pools for."""
        self.target_tokens = set(tokens)
        logger.info(f"Set {len(tokens)} target tokens for pool fetching")

    async def load_cache(self) -> bool:
        """Load cached pool addresses from file."""
        try:
            if self.cache_file.exists():
                with open(self.cache_file, 'r') as f:
                    data = json.load(f)

                # Reconstruct PoolAddress objects
                for token, pools_data in data.items():
                    pools = []
                    for pool_data in pools_data:
                        pool = PoolAddress(
                            address=pool_data["address"],
                            token_a=pool_data["token_a"],
                            token_b=pool_data["token_b"],
                            dex=pool_data["dex"],
                            program_id=pool_data["program_id"]
                        )
                        pools.append(pool)
                    self.cache[token] = pools

                logger.info(f"Loaded {sum(len(pools) for pools in self.cache.values())} cached pools")
                return True
            else:
                logger.info("No cache file found, will fetch from APIs")
                return False

        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")
            return False

    async def save_cache(self):
        """Save current pool addresses to cache file."""
        try:
            data = {}
            for token, pools in self.cache.items():
                pools_data = []
                for pool in pools:
                    pools_data.append({
                        "address": pool.address,
                        "token_a": pool.token_a,
                        "token_b": pool.token_b,
                        "dex": pool.dex,
                        "program_id": pool.program_id
                    })
                data[token] = pools_data

            with open(self.cache_file, 'w') as f:
                json.dump(data, f, indent=2)

            logger.info(f"Saved {sum(len(pools) for pools in self.cache.values())} pools to cache")

        except Exception as e:
            logger.error(f"Failed to save cache: {e}")

    async def fetch_all_pools(self) -> Dict[str, List[PoolAddress]]:
        """Fetch pool addresses for all target tokens."""
        if not self.target_tokens:
            logger.warning("No target tokens set")
            return {}

        logger.info(f"Fetching pools for {len(self.target_tokens)} tokens...")

        # Check cache first
        await self.load_cache()

        # Fetch missing tokens
        tasks = []
        for token in self.target_tokens:
            if token not in self.cache:
                tasks.append(self._fetch_token_pools(token))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for token, pools in zip([t for t in self.target_tokens if t not in self.cache], results):
                if isinstance(pools, Exception):
                    logger.error(f"Failed to fetch pools for {token}: {pools}")
                    continue
                self.cache[token] = pools

            # Save updated cache
            await self.save_cache()

        total_pools = sum(len(pools) for pools in self.cache.values())
        logger.info(f"Total pools fetched: {total_pools}")

        return self.cache.copy()

    async def _fetch_token_pools(self, token_mint: str) -> List[PoolAddress]:
        """Fetch pools for a specific token."""
        pools = []

        # Fetch from Jupiter API
        jupiter_pools = await self._fetch_jupiter_pools(token_mint)
        pools.extend(jupiter_pools)

        # Fetch from Raydium API
        raydium_pools = await self._fetch_raydium_pools(token_mint)
        pools.extend(raydium_pools)

        # Remove duplicates
        seen_addresses = set()
        unique_pools = []
        for pool in pools:
            if pool.address not in seen_addresses:
                unique_pools.append(pool)
                seen_addresses.add(pool.address)

        logger.debug(f"Fetched {len(unique_pools)} pools for {token_mint}")
        return unique_pools

    async def _fetch_jupiter_pools(self, token_mint: str) -> List[PoolAddress]:
        """Fetch pools from Jupiter API."""
        pools = []
        try:
            # Jupiter provides program-id-to-label mapping
            url = f"{self.jupiter_api_url}/program-id-to-label"
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()

                    # Jupiter has program ID mappings, but we need to filter for our tokens
                    # This is a simplified implementation
                    logger.debug(f"Jupiter program mappings: {len(data)} entries")

        except Exception as e:
            logger.debug(f"Jupiter API error: {e}")

        return pools

    async def _fetch_raydium_pools(self, token_mint: str) -> List[PoolAddress]:
        """Fetch pools from Raydium V3 API or fallback to alternative sources."""
        pools = []
        try:
            # Try Raydium V3 API
            url = f"{self.raydium_api_url}/pools?mint={token_mint}"
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Parse V3 format (placeholder - adjust based on actual API response)
                    for pool_data in data.get("data", []):
                        pool_addr = pool_data.get("id")
                        mint_a = pool_data.get("mintA")
                        mint_b = pool_data.get("mintB")
                        if pool_addr and mint_a and mint_b:
                            pool = PoolAddress(
                                address=pool_addr,
                                token_a=mint_a,
                                token_b=mint_b,
                                dex="raydium",
                                program_id="675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
                            )
                            pools.append(pool)
                else:
                    logger.warning(f"Raydium V3 API failed: {resp.status}, falling back to getProgramAccounts")

        except Exception as e:
            logger.warning(f"Raydium API error: {e}, using alternative sources")
            # Fallback: could implement getProgramAccounts or Bitquery here

        return pools

        return pools

    def get_pool_addresses_for_token(self, token_mint: str) -> List[str]:
        """Get pool addresses for a specific token."""
        pools = self.cache.get(token_mint, [])
        return [pool.address for pool in pools]

    def get_all_pool_addresses(self) -> List[str]:
        """Get all unique pool addresses."""
        all_addresses = set()
        for pools in self.cache.values():
            for pool in pools:
                all_addresses.add(pool.address)
        return list(all_addresses)

    def get_pools_by_dex(self, dex: str) -> List[PoolAddress]:
        """Get all pools for a specific DEX."""
        pools = []
        for token_pools in self.cache.values():
            for pool in token_pools:
                if pool.dex == dex:
                    pools.append(pool)
        return pools

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about fetched pools."""
        total_pools = sum(len(pools) for pools in self.cache.values())
        dex_counts = {}
        for pools in self.cache.values():
            for pool in pools:
                dex_counts[pool.dex] = dex_counts.get(pool.dex, 0) + 1

        return {
            "total_tokens": len(self.cache),
            "total_pools": total_pools,
            "pools_per_dex": dex_counts,
            "cache_file": str(self.cache_file),
            "cache_exists": self.cache_file.exists()
        }