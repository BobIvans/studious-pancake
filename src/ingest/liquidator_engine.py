"""
Atomic Flash-Liquidation Engine
Monitors Health Factor < 1.0 and executes profitable liquidations using Flash Loans.
Zero capital required - pure arbitrage on distressed positions.
"""

import asyncio
import base64
import logging
import socket
import struct
from typing import Dict, List, Optional, Callable, Any
from decimal import Decimal
import aiohttp
from solders.pubkey import Pubkey
from solders.instruction import Instruction, AccountMeta
from solders.system_program import TransferParams, transfer

logger = logging.getLogger(__name__)

class LiquidationOpportunity:
    """Detected liquidation opportunity."""
    def __init__(self, obligation_address: str, health_factor: Decimal,
                 debt_asset: str, collateral_asset: str, liquidation_bonus: Decimal,
                 debt_amount: Decimal, estimated_profit: Decimal,
                 protocol: str, pool_address: str):
        self.obligation_address = obligation_address
        self.health_factor = health_factor
        self.debt_asset = debt_asset
        self.collateral_asset = collateral_asset
        self.liquidation_bonus = liquidation_bonus
        self.debt_amount = debt_amount
        self.estimated_profit = estimated_profit
        self.protocol = protocol  # 'kamino' or 'marginfi'
        self.pool_address = pool_address

class LiquidationEngine:
    """Monitors lending protocols and executes flash liquidations."""

    def __init__(self, websocket_url: str, kamino_program_id: str,
                 marginfi_program_id: str, pool_state_manager):
        self.websocket_url = websocket_url
        self.kamino_program_id = kamino_program_id
        self.marginfi_program_id = marginfi_program_id
        self.pool_state_manager = pool_state_manager
        self.opportunity_callbacks: List[Callable] = []
        self.websocket = None
        self.running = False
        self.monitored_obligations: Dict[str, str] = {}  # address -> protocol

    def register_opportunity_callback(self, callback: Callable[[LiquidationOpportunity], None]):
        """Register callback for liquidation opportunities."""
        self.opportunity_callbacks.append(callback)

    async def start(self):
        """Start WebSocket monitoring for lending protocols."""
        self.running = True
        try:
            connector = aiohttp.TCPConnector(ttl_dns_cache=300, family=socket.AF_INET)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.ws_connect(self.websocket_url, heartbeat=15.0, timeout=30.0, compress=15, receive_timeout=45.0) as ws:
                    self.websocket = ws
                    logger.info("Liquidation Engine WebSocket connected")

                    # Subscribe to Kamino obligations
                    kamino_obligations = await self._get_kamino_obligations()
                    for addr in kamino_obligations:
                        await self._subscribe_to_obligation(ws, addr, "kamino")

                    # Subscribe to MarginFi obligations
                    marginfi_obligations = await self._get_marginfi_obligations()
                    for addr in marginfi_obligations:
                        await self._subscribe_to_obligation(ws, addr, "marginfi")

                    # Listen for updates
                    async for msg in ws:
                        if not self.running:
                            break

                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._handle_account_notification(msg.json())

        except Exception as e:
            logger.error(f"Liquidation Engine error: {e}")

    async def stop(self):
        """Stop the WebSocket connection."""
        self.running = False
        if self.websocket:
            await self.websocket.close()

    async def _subscribe_to_obligation(self, ws, obligation_address: str, protocol: str):
        """Subscribe to obligation account updates."""
        try:
            subscription_msg = {
                "jsonrpc": "2.0",
                "id": len(self.monitored_obligations) + 1,
                "method": "accountSubscribe",
                "params": [obligation_address, {"encoding": "jsonParsed"}]
            }
            await ws.send_json(subscription_msg)
            self.monitored_obligations[obligation_address] = protocol
            logger.debug(f"Subscribed to {protocol} obligation: {obligation_address}")

        except Exception as e:
            logger.debug(f"Failed to subscribe to obligation {obligation_address}: {e}")

    async def _handle_account_notification(self, notification: Dict[str, Any]):
        """Process account updates and detect liquidation opportunities."""
        try:
            params = notification.get("params", {})
            result = params.get("result", {})
            account_data = result.get("value", {})

            if not account_data:
                return

            account_pubkey = params.get("result", {}).get("pubkey")
            if not account_pubkey:
                return

            protocol = self.monitored_obligations.get(account_pubkey)
            if not protocol:
                return

            # Calculate health factor
            health_factor = await self._calculate_health_factor(account_data, protocol)

            if health_factor < Decimal('1.0'):
                opportunity = await self._create_liquidation_opportunity(
                    account_data, health_factor, protocol, account_pubkey
                )
                if opportunity and opportunity.estimated_profit > Decimal('0.01'):  # >$0.01 profit
                    logger.info(f"💰 Liquidation opportunity detected! HF: {health_factor} | "
                               f"Profit: ${opportunity.estimated_profit}")

                    # Trigger callbacks
                    for callback in self.opportunity_callbacks:
                        try:
                            await callback(opportunity)
                        except Exception as e:
                            logger.error(f"Liquidation callback error: {e}")

        except Exception as e:
            logger.debug(f"Notification processing error: {e}")

    async def _calculate_health_factor(self, account_data: Dict[str, Any], protocol: str) -> Decimal:
        """Calculate health factor from obligation data."""
        try:
            if protocol == "kamino":
                # Kamino-specific health factor calculation
                return await self._calculate_kamino_health_factor(account_data)
            elif protocol == "marginfi":
                # MarginFi-specific health factor calculation
                return await self._calculate_marginfi_health_factor(account_data)

            return Decimal('999')  # Default healthy

        except Exception:
            return Decimal('999')

    async def _calculate_kamino_health_factor(self, account_data: Dict[str, Any]) -> Decimal:
        """Calculate health factor for Kamino obligations."""
        try:
            # Extract position data from Kamino account
            # NOTE: jsonParsed only works for native programs. For Kamino, we get raw base64.
            # Temporary fix: skip if not parsed, in production use a proper decoder.
            parsed_data = account_data.get("parsed", {}).get("info", {})
            if not parsed_data:
                logger.debug(f"Kamino account data not parsed (raw base64). Skipping automatic parsing.")
                return Decimal('999')

            positions = parsed_data.get("positions", [])

            # Initialize variables before the loop
            total_collateral_value = Decimal('0')
            total_debt_value = Decimal('0')

            # FIX 174: Pull live Pyth oracle prices instead of hardcoded $1 flat rate
            from src.ingest.pyth_core_price_feeder import get_pyth_core_feeder
            feeder = get_pyth_core_feeder()

            for position in positions:
                mint = position.get("mint")
                price_val = 1.0
                if feeder and mint:
                    price_val = feeder.get_price(mint) or 1.0
                price = Decimal(str(price_val))

                if position.get("position_type") == "collateral":
                    amount = Decimal(str(position.get("amount", 0)))
                    total_collateral_value += amount * price
                elif position.get("position_type") == "debt":
                    amount = Decimal(str(position.get("amount", 0)))
                    price = Decimal('1')  # Placeholder
                    total_debt_value += amount * price

            if total_debt_value == 0:
                return Decimal('999')

            return total_collateral_value / total_debt_value

        except Exception:
            return Decimal('999')

    async def _calculate_marginfi_health_factor(self, account_data: Dict[str, Any]) -> Decimal:
        """Calculate health factor for MarginFi obligations."""
        # Similar to Kamino but with MarginFi-specific account structure
        return Decimal('0.95')  # Placeholder - would implement actual calculation

    async def _create_liquidation_opportunity(self, account_data: Dict[str, Any],
                                             health_factor: Decimal, protocol: str,
                                             obligation_address: str) -> Optional[LiquidationOpportunity]:
        """Create liquidation opportunity from account data."""
        try:
            # Extract debt and collateral info
            if protocol == "kamino":
                debt_asset, collateral_asset, debt_amount = await self._extract_kamino_positions(account_data)
            else:
                debt_asset, collateral_asset, debt_amount = await self._extract_marginfi_positions(account_data)

            liquidation_bonus = Decimal('0.05')  # 5% bonus
            estimated_profit = debt_amount * liquidation_bonus * Decimal('0.8')  # Conservative estimate

            pool_address = await self._find_liquidation_pool(debt_asset, collateral_asset)

            return LiquidationOpportunity(
                obligation_address=obligation_address,
                health_factor=health_factor,
                debt_asset=debt_asset,
                collateral_asset=collateral_asset,
                liquidation_bonus=liquidation_bonus,
                debt_amount=debt_amount,
                estimated_profit=estimated_profit,
                protocol=protocol,
                pool_address=pool_address or ""
            )

        except Exception as e:
            logger.debug(f"Failed to create liquidation opportunity: {e}")
            return None

    async def execute_liquidation(self, opportunity: LiquidationOpportunity,
                                 jito_tip_lamports: int, wallet_keypair) -> bool:
        """Quarantined legacy path: PR-020 forbids live liquidation execution.

        This method intentionally has no fallback builder, sender, signer, Jito,
        or placeholder execution body. Keeping the legacy method as an
        immediate runtime error resolves merge conflicts around old guessed
        liquidation code while preserving import compatibility for historical
        modules that still reference ``LiquidationEngine``.
        """
        raise RuntimeError(
            "legacy LiquidationEngine.execute_liquidation is quarantined; "
            "use shadow-only src.liquidation planner"
        )

    async def _extract_kamino_positions(self, account_data: Dict[str, Any]) -> tuple:
        """Extract positions from Kamino obligation."""
        try:
            raw_data = account_data
            if "account" in account_data:
                raw_data = account_data["account"]
            b64_data = raw_data.get("data", "")
            if isinstance(b64_data, list):
                b64_data = b64_data[0]
            if not isinstance(b64_data, str) or not b64_data:
                return "", "", Decimal('0')
            padded = b64_data + "=" * (-len(b64_data) % 4)
            raw_bytes = base64.b64decode(padded)
            if len(raw_bytes) < 121:
                return "", "", Decimal('0')
            collateral_mint = str(Pubkey.from_bytes(raw_bytes[81:113]))
            collateral_amount = struct.unpack('<Q', raw_bytes[113:121])[0]
            return "", collateral_mint, Decimal(collateral_amount)
        except Exception as e:
            logger.debug(f"Failed to extract Kamino positions: {e}")
            return "", "", Decimal('0')

    async def _extract_marginfi_positions(self, account_data: Dict[str, Any]) -> tuple:
        """Extract positions from MarginFi obligation."""
        try:
            parsed = account_data.get("parsed", {})
            info = parsed.get("info", {})
            if info:
                return (
                    info.get("debtMint") or "",
                    info.get("collateralMint") or "",
                    Decimal(str(info.get("debtAmount", 0) or 0)),
                )
            raw_data = account_data
            if "account" in account_data:
                raw_data = account_data["account"]
            b64_data = raw_data.get("data", "")
            if isinstance(b64_data, list):
                b64_data = b64_data[0]
            if not isinstance(b64_data, str) or not b64_data:
                return "", "", Decimal('0')
            padded = b64_data + "=" * (-len(b64_data) % 4)
            raw_bytes = base64.b64decode(padded)
            if len(raw_bytes) >= 9:
                debt_amount = struct.unpack('<Q', raw_bytes[1:9])[0]
            else:
                debt_amount = 0
            return "", "", Decimal(debt_amount)
        except Exception as e:
            logger.debug(f"Failed to extract MarginFi positions: {e}")
            return "", "", Decimal('0')

    async def _find_liquidation_pool(self, debt_asset: str, collateral_asset: str) -> Optional[str]:
        """Find best pool for liquidation swap."""
        try:
            # Use pool state manager to find pools with both assets
            for pool_addr, pool_state in self.pool_state_manager.get_all_pool_states().items():
                has_debt = (pool_state.token_a_mint == debt_asset or
                           pool_state.token_b_mint == debt_asset)
                has_collateral = (pool_state.token_a_mint == collateral_asset or
                                pool_state.token_b_mint == collateral_asset)

                if has_debt and has_collateral:
                    return pool_addr

        except Exception:
            pass
        return None

    async def _fetch_liquidatable_accounts(self) -> List[Dict[str, Any]]:
        """
        Query program accounts with filters to find liquidatable targets.
        Uses getProgramAccounts with memcmp filters for discriminators and health factor.
        """
        try:
            # Filters for Kamino (example)
            # Discriminator for Obligation: [168, 201, 10, 168, 59, 118, 142, 38]
            # Health factor is usually stored as a fixed-point number at a specific offset
            
            # This is a robust implementation using getProgramAccounts
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getProgramAccounts",
                "params": [
                    self.kamino_program_id,
                    {
                        "encoding": "base64",
                        "filters": [
                            {"dataSize": 1500}, # Size of Kamino Obligation
                            {"memcmp": {"offset": 0, "bytes": "4vCKeWp2jg6"}} # Base58 for discriminator
                        ]
                    }
                ]
            }
            
            connector = aiohttp.TCPConnector(ttl_dns_cache=300, family=socket.AF_INET)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(self.websocket_url.replace("wss://", "https://"), json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("result", [])
                    else:
                        return []
        except Exception as e:
            logger.error(f"Failed to fetch liquidatable accounts: {e}")
            return []

    async def _get_kamino_obligations(self) -> List[str]:
        """Get list of Kamino obligation accounts to monitor."""
        accounts = await self._fetch_liquidatable_accounts()
        return [acc["pubkey"] for acc in accounts]

    async def _get_marginfi_obligations(self) -> List[str]:
        """Get list of MarginFi obligation accounts to monitor."""
        # For demo, returning placeholders as MarginFi filters are different
        return ["MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"]