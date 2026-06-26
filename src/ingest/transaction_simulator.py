"""
Transaction Simulator - Optimistic State Simulation Module

Lightweight service that simulates transactions through Helius RPC to verify profit
before execution. Handles simulation response parsing and profit calculation.
"""

import asyncio
import orjson
import logging
from typing import Dict, Optional, Tuple
import aiohttp
import base64
from solders.transaction import VersionedTransaction

logger = logging.getLogger("TransactionSimulator")


class TransactionSimulator:
    """Simulates transactions to verify profit before execution."""

    def __init__(self, helius_rpc_url: str, session: Optional[aiohttp.ClientSession] = None):
        self.helius_rpc_url = helius_rpc_url
        self.session = session
        self._session_owned = session is None

    async def __aenter__(self):
        if self._session_owned and self.session is None:
            self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session_owned and self.session:
            await self.session.close()

    async def simulate(self, transaction: VersionedTransaction) -> Tuple[bool, float]:
        """
        Simulate transaction using Helius RPC.

        Args:
            transaction: VersionedTransaction to simulate

        Returns:
            Tuple of (success: bool, net_profit_sol: float)
            success=False if simulation fails or net profit <= 0
        """
        try:
            # Serialize transaction to base64
            tx_b64 = base64.b64encode(bytes(transaction)).decode('ascii')

            # Build simulation request
            sim_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "simulateTransaction",
                "params": [
                    tx_b64,
                    {
                        "encoding": "base64",
                        "commitment": "confirmed",
                        "sigVerify": False
                    }
                ]
            }

            logger.debug("🎭 Simulating transaction")

            # Send request with timeout
            timeout = aiohttp.ClientTimeout(total=0.5)  # 500ms timeout for speed
            async with self.session.post(
                self.helius_rpc_url,
                json=sim_payload,
                timeout=timeout
            ) as response:
                result = await response.json()

            # Parse simulation response
            return self._parse_simulation_response(result)

        except asyncio.TimeoutError:
            logger.warning("⚠️ Simulation timeout - skipping for speed")
            return False, 0.0
        except Exception as e:
            logger.error(f"Simulation error: {e}")
            return False, 0.0

    def _parse_simulation_response(self, response: Dict) -> Tuple[bool, float]:
        """
        Parse simulation response to extract net profit.

        Args:
            response: Raw JSON response from simulateTransaction

        Returns:
            Tuple of (success: bool, net_profit_sol: float)
        """
        try:
            # Check for RPC errors
            if "error" in response:
                logger.warning(f"❌ Simulation RPC error: {response['error']}")
                return False, 0.0

            result = response.get("result", {})
            value = result.get("value", {})

            # Check for transaction execution errors
            if value.get("err"):
                err_msg = str(value['err'])
                logger.warning(f"❌ Simulation transaction error: {err_msg}")
                # Log specific failure reasons for debugging
                if "SlippageToleranceExceeded" in err_msg:
                    logger.info("   Reason: Slippage tolerance exceeded")
                elif "InsufficientFunds" in err_msg:
                    logger.info("   Reason: Insufficient funds")
                else:
                    logger.info(f"   Reason: {err_msg}")
                return False, 0.0

            # Parse accounts for balance changes
            accounts = value.get("accounts", [])
            if not accounts:
                logger.warning("No account data in simulation response")
                return False, 0.0

            # Extract SOL balance changes
            # In a flash loan arbitrage, we expect:
            # - Initial SOL balance (before flash loan)
            # - SOL after flash loan + fees
            # - SOL after swap back to SOL

            # Try to parse actual balance changes from preBalances/postBalances arrays
            net_profit_sol = 0.0
            try:
                pre_balances = value.get("preBalances", [])
                post_balances = value.get("postBalances", [])
                if pre_balances and post_balances and len(pre_balances) > 0 and len(post_balances) > 0:
                    delta_lamports = post_balances[0] - pre_balances[0]
                    if delta_lamports > 0:
                        net_profit_sol = delta_lamports / 1e9
            except (ValueError, TypeError, IndexError, AttributeError):
                net_profit_sol = 0.0

            if net_profit_sol <= 0:
                logger.info(f"📉 No real profit detected from simulation balances: {net_profit_sol:.6f} SOL")
                return False, 0.0

            logger.info(f"Profit from simulation: {net_profit_sol:.6f} SOL")
            return True, net_profit_sol

        except Exception as e:
            logger.error(f"Error parsing simulation response: {e}")
            return False, 0.0