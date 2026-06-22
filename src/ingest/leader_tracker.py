"""Leader Schedule Tracker for Hybrid Execution Engine."""

import asyncio
import logging
import os
from typing import List, Dict, Any, Optional
import aiohttp
import src.ingest.shared_state as shared_state

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
        self._task: Optional[asyncio.Task] = None

    async def start(self, session: aiohttp.ClientSession):
        self.session = session
        self.running = True
        self._task = asyncio.create_task(self._fetch_loop())
        shared_state.active_tasks.add(self._task)
        self._task.add_done_callback(shared_state.active_tasks.discard)

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

            self.last_fetch = asyncio.get_running_loop().time()
            logger.info(f"✅ Updated leader schedule for {len(leaders)} slots starting from {current_slot}")

        except Exception as e:
            logger.error(f"Failed to fetch leader schedule: {e}")

    def get_leader_for_slot(self, slot: int) -> Optional[str]:
        """Get the validator pubkey for a given slot."""
        return self.leader_schedule.get(slot)

    def get_current_slot_leader(self, current_slot: int) -> Optional[str]:
        """Get the leader for the current slot."""
        return self.get_leader_for_slot(current_slot)

    def is_jito_imminent(self, current_slot: int, jito_leaders: Optional[set] = None,
                         max_slots_ahead: int = 10) -> Dict[str, Any]:
        """
        Task 4 — Jito Leader Trap Guard.

        Checks whether a Jito block-engine leader is scheduled within the next
        ``max_slots_ahead`` slots.

        If the next Jito leader is MORE than ``max_slots_ahead`` slots away, the
        caller should either raise the Jito tip by +10% or skip the trade entirely
        to avoid "Blockhash Expired" while waiting for the Jito validator's slot.

        Args:
            current_slot: The latest known slot number.
            jito_leaders:  Set of Jito block-engine validator pubkeys.
                           If None, an empty set is used (returns ``not_imminent``).
            max_slots_ahead: The threshold slots distance beyond which the Jito
                             leader is considered "too far" (default: 10 slots ≈ 4 s).

        Returns:
            Dict with:
              ``imminent``    — True if a Jito leader is within max_slots_ahead.
              ``slots_ahead`` — Exact slot distance to the next Jito leader.
              ``reason``      — Human-readable explanation.
        """
        jito_leaders = jito_leaders or set()

        if not self.leader_schedule or not jito_leaders:
            return {
                "imminent": False,
                "slots_ahead": float("inf"),
                "reason": "No leader schedule or Jito leader list available — assume not imminent",
            }

        # Scan forward from current_slot in the cached schedule
        for offset in range(1, max_slots_ahead + 1):
            slot = current_slot + offset
            validator = self.leader_schedule.get(slot)
            if validator and validator in jito_leaders:
                return {
                    "imminent": True,
                    "slots_ahead": offset,
                    "reason": f"Jito leader '{validator[:8]}…' found at slot {slot} ({offset} slots ahead)",
                }

        # No Jito leader within max_slots_ahead slots
        return {
            "imminent": False,
            "slots_ahead": max_slots_ahead + 1,
            "reason": (
                f"No Jito leader within {max_slots_ahead} slots "
                f"(slots {current_slot + 1}–{current_slot + max_slots_ahead}). "
                "Consider increasing tip by +10% or skipping trade."
            ),
        }

    async def calculate_aggressive_priority_fee(self, session: aiohttp.ClientSession, rpc_url: str, max_fee_sol: float, account_keys: Optional[List[str]] = None) -> float:
        """Calculate aggressive priority fee for non-Jito slots."""
        try:
            # Get recent prioritization fees - use localized fee market if accounts provided
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getRecentPrioritizationFees",
                "params": [account_keys if account_keys else []],  # Localized fee market support
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
