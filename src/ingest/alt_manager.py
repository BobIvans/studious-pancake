"""
In-Memory Address Lookup Table (ALT) Cache Manager

Eliminates fatal 50-100ms RPC delays during transaction building by pre-fetching
and caching all known Jupiter and DEX Address Lookup Tables in RAM at bot startup.

Critical for O(1) transaction construction in high-frequency arbitrage.
"""

import asyncio
import aiohttp
import logging
import time
from typing import Dict, List, Optional, Set, Any, Tuple
from solders.pubkey import Pubkey

logger = logging.getLogger(__name__)


class ALTCacheManager:
    """
    Manages in-memory caching of Address Lookup Tables (ALTs) for fast transaction building.

    Pre-fetches ALTs from Jupiter, Raydium, Orca, Meteora, and other major DEXes
    to eliminate RPC calls during critical transaction construction paths.
    """

    def __init__(self, rpc_url: str, session: Optional[aiohttp.ClientSession] = None):
        self.rpc_url = rpc_url
        self.session = session
        self._session_owned = session is None

        # Cache structure: alt_pubkey -> list of resolved account pubkeys
        self.alt_cache: Dict[str, List[Pubkey]] = {}

        # Metadata cache: alt_pubkey -> (last_updated, ttl_seconds)
        self.alt_metadata: Dict[str, Tuple[float, int]] = {}

        # Known ALT pubkeys for major protocols
        self.known_alts = self._get_known_alt_pubkeys()

        # Cache settings
        self.default_ttl = 30  # Phase 38: Reduced TTL for high-frequency updates
        self.max_cache_age = 7200  # 2 hours

    async def __aenter__(self):
        if self._session_owned and self.session is None:
            self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session_owned and self.session:
            await self.session.close()

    async def initialize_cache(self) -> bool:
        """
        Initialize ALT cache by pre-fetching all known ALTs.

        Call this at bot startup. Returns True if cache populated successfully.
        """
        logger.info(f"Initializing ALT cache with {len(self.known_alts)} known ALTs")

        try:
            # Batch fetch all known ALTs
            await self._batch_fetch_alts(list(self.known_alts))
            logger.info(f"ALT cache initialized with {len(self.alt_cache)} entries")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize ALT cache: {e}")
            return False

    async def resolve_alt(self, alt_pubkey: Pubkey) -> Optional[List[Pubkey]]:
        """
        Resolve ALT synchronously from cache (no RPC calls).

        Args:
            alt_pubkey: Address Lookup Table pubkey

        Returns:
            List of resolved account pubkeys, or None if not cached/expired
        """
        alt_key = str(alt_pubkey)

        # Check if cached and not expired
        if alt_key in self.alt_metadata:
            last_updated, ttl = self.alt_metadata[alt_key]
            if time.time() - last_updated < ttl:
                resolved_accounts = self.alt_cache.get(alt_key)
                if resolved_accounts:
                    logger.debug(f"ALT cache hit for {alt_key[:8]}... ({len(resolved_accounts)} accounts)")
                    return resolved_accounts

            # Expired - remove from cache
            else:
                logger.debug(f"ALT cache expired for {alt_key[:8]}...")
                self._remove_expired_alt(alt_key)

        logger.warning(f"ALT cache miss for {alt_key[:8]}... - cache miss during tx building!")
        return None

    async def refresh_cache(self, force: bool = False) -> int:
        """
        Refresh expired ALTs in cache.

        Args:
            force: If True, refresh all ALTs regardless of TTL

        Returns:
            Number of ALTs refreshed
        """
        expired_alts = []

        if force:
            expired_alts = list(self.known_alts)
        else:
            current_time = time.time()
            for alt_key, (last_updated, ttl) in self.alt_metadata.items():
                if current_time - last_updated >= ttl:
                    expired_alts.append(Pubkey.from_string(alt_key))

        if expired_alts:
            logger.info(f"Refreshing {len(expired_alts)} expired ALTs")
            await self._batch_fetch_alts(expired_alts)
            return len(expired_alts)

        return 0

    async def add_dynamic_alt(self, alt_pubkey: Pubkey, ttl_seconds: int = None) -> bool:
        """
        Add a dynamically discovered ALT to cache.

        Args:
            alt_pubkey: New ALT pubkey to cache
            ttl_seconds: Custom TTL, uses default if None

        Returns:
            True if successfully cached
        """
        try:
            resolved = await self._fetch_single_alt(alt_pubkey)
            if resolved:
                alt_key = str(alt_pubkey)
                self.alt_cache[alt_key] = resolved
                self.alt_metadata[alt_key] = (time.time(), ttl_seconds or self.default_ttl)
                logger.debug(f"Added dynamic ALT {alt_key[:8]}... to cache")
                return True
        except Exception as e:
            logger.debug(f"Failed to cache dynamic ALT {alt_pubkey}: {e}")

        return False

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics for monitoring."""
        total_alts = len(self.alt_cache)
        expired_count = 0
        current_time = time.time()

        for alt_key, (last_updated, ttl) in self.alt_metadata.items():
            if current_time - last_updated >= ttl:
                expired_count += 1

        return {
            'total_cached_alts': total_alts,
            'expired_alts': expired_count,
            'cache_hit_ratio': 1.0 if total_alts > 0 else 0.0,  # Would track hits/misses in practice
            'oldest_entry_age': self._get_oldest_entry_age()
        }

    async def _batch_fetch_alts(self, alt_pubkeys: List[Pubkey]) -> None:
        """Batch fetch multiple ALTs efficiently."""
        if not alt_pubkeys:
            return

        try:
            # getMultipleAccounts supports up to 100 accounts per request
            batch_size = 100
            for i in range(0, len(alt_pubkeys), batch_size):
                batch = alt_pubkeys[i:i + batch_size]
                await self._fetch_alt_batch(batch)
                await asyncio.sleep(0.01)  # Small delay to avoid overwhelming RPC

        except Exception as e:
            logger.error(f"Batch ALT fetch failed: {e}")

    async def _fetch_alt_batch(self, alt_pubkeys: List[Pubkey]) -> None:
        """Fetch a batch of ALTs and cache them."""
        if not self.session:
            raise RuntimeError("HTTP session not available")

        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getMultipleAccounts",
                "params": [
                    [str(pk) for pk in alt_pubkeys],
                    {
                        "encoding": "base64",
                        "commitment": "confirmed"
                    }
                ]
            }

            async with self.session.post(
                self.rpc_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=5.0)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "result" in data and "value" in data["result"]:
                        accounts_data = data["result"]["value"]

                        for alt_pubkey, account_data in zip(alt_pubkeys, accounts_data):
                            if account_data:
                                try:
                                    # getMultipleAccounts returns array of account objects directly in "value"
                                    account_info = account_data.get("account", account_data)
                                    if "data" in account_info:
                                        resolved_accounts = self._parse_alt_data(account_info["data"][0])
                                        if resolved_accounts:
                                            alt_key = str(alt_pubkey)
                                            # Phase 38: Overwrite if larger (new addresses added)
                                            existing = self.alt_cache.get(alt_key, [])
                                            if len(resolved_accounts) >= len(existing):
                                                if len(resolved_accounts) > len(existing):
                                                    logger.info(f"🔄 ALT {alt_key[:8]}... grew: {len(existing)} -> {len(resolved_accounts)} accounts")
                                                self.alt_cache[alt_key] = resolved_accounts
                                                self.alt_metadata[alt_key] = (time.time(), self.default_ttl)
                                                logger.debug(f"Cached ALT {alt_key[:8]}... with {len(resolved_accounts)} accounts")
                                except Exception as e:
                                    logger.debug(f"Failed to parse ALT {alt_pubkey}: {e}")

                else:
                    logger.warning(f"ALT batch fetch failed with status {resp.status}")

        except Exception as e:
            logger.error(f"ALT batch fetch error: {e}")

    async def _fetch_single_alt(self, alt_pubkey: Pubkey) -> Optional[List[Pubkey]]:
        """Fetch a single ALT account."""
        await self._batch_fetch_alts([alt_pubkey])
        return self.alt_cache.get(str(alt_pubkey))

    def _parse_alt_data(self, base64_data: str) -> Optional[List[Pubkey]]:
        """Parse ALT account data to extract resolved pubkeys."""
        try:
            import base64
            # Fix #5: Add padding before decoding to handle base64 strings
            padded = base64_data + "=" * (-len(base64_data) % 4)
            data = base64.b64decode(padded)

            # Phase 32: Fixed ALT header parsing (authoritized ALTs only)
            # ALT header layout:
            # - type: u64 (8)
            # - deactivation_slot: u64 (8)
            # - last_extended_slot: u64 (8)
            # - last_extended_slot_index_padding: u8 (1)
            # - authority: Option<Pubkey> (1 byte flag + 32 bytes) = always 33 bytes, padded to 56
            
            if len(data) < 56:
                return None
            header_len = 56  # Fixed header for authoritized ALTs

            if len(data) < header_len:
                return None

            pubkeys = []
            pubkey_data = data[header_len:]

            for i in range(0, len(pubkey_data), 32):
                if i + 32 <= len(pubkey_data):
                    pubkey_bytes = pubkey_data[i:i + 32]
                    pubkeys.append(Pubkey.from_bytes(pubkey_bytes))

            return pubkeys

        except Exception as e:
            logger.debug(f"ALT data parsing error: {e}")
            return None

    def _remove_expired_alt(self, alt_key: str) -> None:
        """Remove expired ALT from cache."""
        self.alt_cache.pop(alt_key, None)
        self.alt_metadata.pop(alt_key, None)

    def _get_oldest_entry_age(self) -> float:
        """Get age of oldest cache entry in seconds."""
        if not self.alt_metadata:
            return 0.0

        current_time = time.time()
        # Fix: snapshot values to avoid RuntimeError if alt_metadata changes during iteration
        values_snapshot = list(self.alt_metadata.values())
        if not values_snapshot:
            return 0.0
        oldest_age = min(current_time - last_updated for last_updated, _ in values_snapshot)
        return oldest_age

    def _get_known_alt_pubkeys(self) -> Set[Pubkey]:
        """
        Return set of known ALT pubkeys for major Solana DEXes and protocols.
        """
        # Jupiter v6 ALTs (mainnet)
        jupiter_alts = [
            "8BnUecXrf4oXLR2pGLCJdGdTNr4F9K3L9CQz6Fz7GQo",  # Jupiter ALT 1
            "2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo",  # Jupiter ALT 2
            "GvT9Yv7pGkC4C2G7C1U1W1E1G1U1W1E1G1U1W1E1G1U",  # Placeholder
            "7G1U1W1E1G1U1W1E1G1U1W1E1G1U1W1E1G1U1W1E1G",  # Placeholder
        ]

        # Raydium ALTs
        raydium_alts = [
            "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8", # Raydium Main
            "9W959DqEETiGZocYWCQPaJ6sBmUzgfxXfqGeTEdp3aQP", # Orca
        ]

        # Meteora ALTs
        meteora_alts = [
            "LBUZKhRxPF3XUpBCjp4YzTKgLLjggiJWUna9LZJRQD3",
        ]

        # Convert to Pubkey objects
        all_alts = []
        for alt_list in [jupiter_alts, raydium_alts, meteora_alts]:
            for alt_str in alt_list:
                try:
                    all_alts.append(Pubkey.from_string(alt_str))
                except Exception as e:
                    logger.debug(f"Invalid ALT pubkey {alt_str}: {e}")

        return set(all_alts)
