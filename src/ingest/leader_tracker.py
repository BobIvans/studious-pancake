"""Leader Schedule Tracker for Hybrid Execution Engine."""

import asyncio
import logging
from typing import Dict, Optional
import aiohttp
from solders.pubkey import Pubkey

logger = logging.getLogger(__name__)

class LeaderTracker:
    """Tracks slot leader schedule for hybrid execution."""

    # Removed: hardcoded JITO_VALIDATOR_VOTES was always stale (~100% outdated).
    # Jito Block Engine auto-inserts bundles into the next Jito slot within 5 slots —
    # no local leader check required. See: https://jito-labs.gitbook.io/mev/searcher-resources/bundles

    def __init__(self, rpc_url: str, fetch_interval_ms: int = 600000):
        self.rpc_url = rpc_url
        self.fetch_interval_ms = fetch_interval_ms
        self.leader_schedule: Dict[int, str] = {}  # slot -> validator pubkey
        self.last_fetch = 0
        self.running = False
        self.session: Optional[aiohttp.ClientSession] = None

    async def start(self, session: aiohttp.ClientSession):
        """Start the leader tracker."""
        self.session = session
        self.running = True
        asyncio.create_task(self._fetch_loop())

    async def stop(self):
        """Stop the leader tracker."""
        self.running = False

    async def _fetch_loop(self):
        """Fetch leader schedule periodically."""
        while self.running:
            try:
                await self._fetch_leader_schedule()
                await asyncio.sleep(self.fetch_interval_ms / 1000)
            except Exception as e:
                logger.error(f"Error in leader fetch loop: {e}")
                await asyncio.sleep(60)  # Retry after 1 minute on error

    async def _fetch_leader_schedule(self):
        """Fetch upcoming slot leaders."""
        try:
            # Get current slot
            current_slot_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSlot",
                "params": []
            }
            async with self.session.post(self.rpc_url, json=current_slot_payload) as resp:
                if resp.status != 200:
                    raise Exception(f"Failed to get current slot: {resp.status}")
                data = await resp.json()
                current_slot = data["result"]

            # Fetch leaders for next 5000 slots
            leaders_payload = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "getSlotLeaders",
                "params": [current_slot, 5000]
            }
            async with self.session.post(self.rpc_url, json=leaders_payload) as resp:
                if resp.status != 200:
                    raise Exception(f"Failed to get slot leaders: {resp.status}")
                data = await resp.json()
                leaders = data["result"]

            # Update cache
            self.leader_schedule = {}
            for i, leader_pubkey in enumerate(leaders):
                slot = current_slot + i
                self.leader_schedule[slot] = leader_pubkey

            self.last_fetch = asyncio.get_event_loop().time()
            logger.info(f"✅ Updated leader schedule for {len(leaders)} slots starting from {current_slot}")

        except Exception as e:
            logger.error(f"Failed to fetch leader schedule: {e}")

    def get_leader_for_slot(self, slot: int) -> Optional[str]:
        """Get the validator pubkey for a given slot."""
        return self.leader_schedule.get(slot)

    def get_current_slot_leader(self, current_slot: int) -> Optional[str]:
        """Get the leader for the current slot."""
        return self.get_leader_for_slot(current_slot)

    async def calculate_aggressive_priority_fee(self, session: aiohttp.ClientSession, rpc_url: str, max_fee_sol: float) -> float:
        """Calculate aggressive priority fee for non-Jito slots."""
        try:
            # Get recent prioritization fees
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getRecentPrioritizationFees",
                "params": [["11111111111111111111111111111112"]]  # System program
            }
            async with session.post(rpc_url, json=payload) as resp:
                if resp.status != 200:
                    raise Exception(f"Failed to get prioritization fees: {resp.status}")
                data = await resp.json()

            fees = data["result"]
            if not fees:
                return 0.0

            # Get 90th percentile of last 5 blocks
            recent_fees = [fee["prioritizationFee"] for fee in fees[:5]]  # Last 5
            if not recent_fees:
                return 0.0

            sorted_fees = sorted(recent_fees)
            index = int(len(sorted_fees) * 0.9)  # 90th percentile
            base_fee = sorted_fees[min(index, len(sorted_fees) - 1)]

            # Add 20% buffer
            aggressive_fee = base_fee * 1.2

            # Convert lamports to SOL
            aggressive_fee_sol = aggressive_fee / 1_000_000_000

            # Cap at max_fee_sol
            return min(aggressive_fee_sol, max_fee_sol)

        except Exception as e:
            logger.error(f"Failed to calculate priority fee: {e}")
            return 0.0
