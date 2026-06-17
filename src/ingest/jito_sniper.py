"""
Jito Sniper - WebSocket-Based Pool Creation Sniping

Ultra-fast pool creation detection via WSS logsSubscribe and instant Jito bundle execution
for free-tier Solana arbitrage opportunities.
"""

import asyncio
import orjson
import logging
import random
import time
import os
import urllib.request
from typing import Dict, List, Optional, Set, Tuple, Any, Callable
import aiohttp
import websockets
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import VersionedTransaction
from solders.message import MessageV0
from solders.hash import Hash
from .tx_builder import JupiterTxBuilder

logger = logging.getLogger("JitoSniper")


class PoolCreationEvent:
    """Represents a detected pool creation event."""

    def __init__(
        self,
        program_id: str,
        pool_address: str,
        base_mint: str,
        quote_mint: str,
        timestamp: float,
        slot: int,
        signature: str,
    ):
        self.program_id = program_id
        self.pool_address = pool_address
        self.base_mint = base_mint
        self.quote_mint = quote_mint
        self.timestamp = timestamp
        self.slot = slot
        self.signature = signature

    def __repr__(self):
        return f"PoolCreationEvent(pool={self.pool_address[:8]}..., base={self.base_mint[:8]}..., quote={self.quote_mint[:8]}..., slot={self.slot})"


class JitoTipManager:
    """Manages real-time Jito tip tracking and optimization."""

    DEFAULT_TIP_ACCOUNTS = ["96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"]

    JITO_TIP_STREAM_URL = "ws://bundles.jito.wtf/api/v1/bundles/tip_stream"
    JITO_TIP_ACCOUNTS_URL = "https://mainnet.block-engine.jito.wtf/api/v1/bundles/tip_accounts"

    def __init__(self, percentile: float = 75.0, min_tip_lamports: int = 10000, tip_multiplier: float = 1.1):
        self.percentile = percentile
        self.min_tip_lamports = min_tip_lamports
        self.tip_multiplier = tip_multiplier
        self.tip_accounts = []
        self.websocket: Optional[websockets.WebSocketServerProtocol] = None
        self.running = False
        self.current_percentiles: Dict[str, int] = {}
        self.last_update = 0.0
        self.cache_timeout = 30.0  # 30 seconds
        self.ema_75th: Optional[float] = None
        self.ema_alpha = 2 / (10 + 1)  # EMA period 10
        # Phase 40: WebSocket Watchdog
        self.last_msg_time = 0.0
        self.watchdog_task = None

    async def start(self):
        """Start tip tracking."""
        self.running = True
        # Task 14: Dynamically fetch tip accounts on startup
        await self._refresh_tip_accounts()
        asyncio.create_task(self._maintain_connection())

    async def _refresh_tip_accounts(self):
        """Fetch Jito tip accounts from API."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.JITO_TIP_ACCOUNTS_URL) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.tip_accounts = data if isinstance(data, list) else []
                        if self.tip_accounts:
                            logger.info(f"✅ Dynamically fetched {len(self.tip_accounts)} Jito tip accounts")
                            return
        except Exception as e:
            logger.warning(f"Failed to fetch Jito tip accounts: {e}")
        
        # Absolute fallback if API is down
        self.tip_accounts = ["96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"]

    async def stop(self):
        """Stop tip tracking."""
        self.running = False
        if self.watchdog_task:
            self.watchdog_task.cancel()
        if self.websocket:
            await self.websocket.close()

    async def _maintain_connection(self):
        """Maintain WebSocket connection to Jito tip stream."""
        while self.running:
            try:
                logger.info("🔌 Connecting to Jito tip stream...")
                async with websockets.connect(self.JITO_TIP_STREAM_URL) as websocket:
                    self.websocket = websocket
                    logger.info("✅ Connected to Jito tip stream")
                    self.last_msg_time = time.time()
                    if not self.watchdog_task or self.watchdog_task.done():
                        self.watchdog_task = asyncio.create_task(self._watchdog())

                    async for message in websocket:
                        self.last_msg_time = time.time()
                        try:
                            data = orjson.loads(message)
                            await self._process_tip_data(data)
                        except Exception:
                            logger.warning(
                                f"Invalid JSON from tip stream: {message[:100]}..."
                            )
                        except Exception as e:
                            logger.error(f"Error processing tip data: {e}")

            except Exception as e:
                logger.warning(f"Tip stream connection error: {e}")
                if self.running:
                    await asyncio.sleep(5.0)  # Reconnect delay

    async def _watchdog(self):
        """Monitor Jito stream health (Phase 40)."""
        while self.running:
            try:
                if self.websocket and self.last_msg_time > 0:
                    if time.time() - self.last_msg_time > 5.0:
                        logger.warning("🚨 Jito stream watchdog: No messages for 5s! Force reconnecting...")
                        await self.websocket.close()
                await asyncio.sleep(1.0)
            except Exception as e:
                logger.error(f"Jito watchdog error: {e}")
                await asyncio.sleep(1.0)

    async def _process_tip_data(self, data: Dict[str, Any]):
        """Process incoming tip data from Jito stream."""
        try:
            # Handle percentile data format
            if "percentiles" in data:
                percentiles = data["percentiles"]
                self.current_percentiles = {
                    key: int(value) for key, value in percentiles.items()
                }
                self.last_update = time.time()

                # Update EMA for 75th percentile
                if "75th" in self.current_percentiles:
                    p75 = self.current_percentiles["75th"]
                    if self.ema_75th is None:
                        self.ema_75th = p75
                    else:
                        self.ema_75th = self.ema_alpha * p75 + (1 - self.ema_alpha) * self.ema_75th

                    logger.debug(
                        f"📊 Updated percentiles: {self.current_percentiles}, EMA 75th: {self.ema_75th:.0f} lamports"
                    )
            # Fallback to old format if needed
            elif "lands" in data:
                # Extract tip amounts from lands data
                tips = []
                for land_data in data["lands"]:
                    if "time" in land_data and "mevTip" in land_data:
                        tip_amount = int(land_data["mevTip"])
                        tips.append(tip_amount)

                if tips:
                    self.current_tips = sorted(tips)
                    self.last_update = time.time()
                    logger.debug(
                        f"📊 Updated tip data: {len(tips)} tips, range: {min(tips)}-{max(tips)} lamports"
                    )

        except Exception as e:
            logger.error(f"Error parsing tip data: {e}")

    def get_optimal_tip(self, is_jito_leader: bool = False, competition_low: bool = True, max_tip_lamports: int = 500000) -> int:
        """
        Get optimal tip amount with Game Theory optimizations.
        
        Logic:
        - If Jito is leader and competition is low -> Min Tip (10k)
        - If competition is high -> Check if optimal tip exceeds MAX_TIP_SOL
        - Otherwise -> EMA 75th percentile * multiplier
        """
        if is_jito_leader and competition_low:
            logger.info("🎮 Jito Leader + Low Competition: Using MIN TIP (10k)")
            return self.min_tip_lamports

        if not self._is_cache_valid():
            logger.warning("⚠️ Tip data stale, using minimum tip")
            return self.min_tip_lamports

        if self.ema_75th is None:
            return self.min_tip_lamports

        try:
            optimal_tip = int(self.ema_75th * self.tip_multiplier)
            
            # Competition Skip Logic
            if not competition_low and optimal_tip > max_tip_lamports:
                logger.warning(f"🚫 Competition too high: Optimal tip {optimal_tip} > Max tip {max_tip_lamports}. Skipping.")
                return -1 # Signal to skip

            optimal_tip = max(optimal_tip, self.min_tip_lamports)
            optimal_tip = min(optimal_tip, max_tip_lamports)

            return optimal_tip

        except Exception as e:
            logger.error(f"Error calculating optimal tip: {e}")
            return self.min_tip_lamports

    def _is_cache_valid(self) -> bool:
        """Check if cached tip data is still valid."""
        return time.time() - self.last_update < self.cache_timeout

    async def fetch_tip_accounts(self) -> bool:
        """Fetch live Jito tip accounts from Block Engine (Phase 35)."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(self.JITO_TIP_ACCOUNTS_URL, timeout=5.0) as resp:
                    if resp.status == 200:
                        accounts = await resp.json()
                        parsed_accounts = self._parse_tip_accounts(accounts)
                        if parsed_accounts:
                            self.tip_accounts = parsed_accounts
                            logger.info(f"🔄 Jito tip accounts updated: {len(self.tip_accounts)} active accounts")
                            return True
        except Exception as e:
            logger.warning(f"Failed to fetch dynamic Jito tip accounts: {e}. Using defaults.")
            
        return False

    def _parse_tip_accounts(self, accounts: Any) -> List[str]:
        if isinstance(accounts, dict):
            accounts = accounts.get("value") or accounts.get("accounts") or accounts.get("tip_accounts") or []
        if not isinstance(accounts, list):
            return []
        parsed_accounts: List[str] = []
        for account in accounts:
            account_str = str(account).strip()
            if account_str:
                parsed_accounts.append(account_str)
        return parsed_accounts

    def _fetch_tip_accounts_sync(self, timeout: float = 1.5) -> bool:
        try:
            with urllib.request.urlopen(self.JITO_TIP_ACCOUNTS_URL, timeout=timeout) as resp:
                if resp.status == 200:
                    accounts = orjson.loads(resp.read().decode("utf-8"))
                    parsed_accounts = self._parse_tip_accounts(accounts)
                    if parsed_accounts:
                        self.tip_accounts = parsed_accounts
                        logger.info(f"🔄 Jito tip accounts updated: {len(self.tip_accounts)} active accounts")
                        return True
        except Exception as e:
            logger.debug(f"Synchronous Jito tip account fetch failed: {e}")
        return False

    def _load_tip_accounts_from_env(self) -> List[str]:
        raw_accounts = os.getenv("JITO_TIP_ACCOUNTS", "")
        if not raw_accounts:
            return []
        return [
            account.strip()
            for account in raw_accounts.replace(";", ",").split(",")
            if account.strip()
        ]

    def get_random_tip_account(self) -> str:
        """Get random Jito tip account for load balancing with fallback fetch."""
        if not self.tip_accounts:
            if self._fetch_tip_accounts_sync():
                return random.choice(self.tip_accounts)

            env_accounts = self._load_tip_accounts_from_env()
            if env_accounts:
                self.tip_accounts = env_accounts
                logger.warning("Using JITO_TIP_ACCOUNTS fallback tip accounts")
                return random.choice(self.tip_accounts)

            logger.warning("Jito tip accounts unavailable; using emergency fallback tip account")
            self.tip_accounts = list(self.DEFAULT_TIP_ACCOUNTS)

        return random.choice(self.tip_accounts)


class WssPoolCreationListener:
    """WebSocket listener for pool creation events."""

    # Program IDs to monitor for pool creation - UPDATED FOR BLUE OCEAN
    TARGET_PROGRAMS = {
        "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "raydium_amm_v4",
        "6EF8rrecthR5Dkzon8NQtmB3MtyyRSKCMWNgBtygzRh": "raydium_clmm",
        "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C": "raydium_cpmm_v4",  # New Raydium CPMM
        "LBUZKhRxPF3XUpBCjp4YzTKgLLjggiJWUna9LZJRQD3": "meteora_dlmm",      # Blue Ocean - Meteora DLMM
        "MoonCVVNZFSYkqNXP6bxHL13nk21VGGf25sUnyP6HjU": "moonshot",           # Blue Ocean - Moonshot
        "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg": "pump_migration",     # Pump.fun Migration
        # Add more Blue Ocean programs as they emerge
    }

    def __init__(
        self,
        rpc_ws_url: str = "wss://api.mainnet-beta.solana.com",
        rpc_http_url: str = "https://api.mainnet-beta.solana.com",
        event_callback: Optional[Callable[[PoolCreationEvent], None]] = None,
        session: Optional[aiohttp.ClientSession] = None,
    ):
        self.rpc_ws_url = rpc_ws_url
        self.rpc_http_url = rpc_http_url
        self.event_callback = event_callback
        self.session = session
        self._session_owned = session is None  # Will be created in __aenter__
        self.websocket = None
        self.running = False
        self.subscriptions: Dict[str, int] = {}
        self.subscription_counter = 1

        # Phase 40: WebSocket Watchdog
        self.last_msg_time = 0.0
        self.watchdog_task = None
        
        # Target DEX programs to listen to for pool creation

    async def __aenter__(self):
        if self._session_owned and self.session is None:
            self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session_owned and self.session:
            await self.session.close()

    async def start(self):
        """Start listening for pool creation events."""
        self.running = True
        logger.info("🎯 Starting pool creation listener...")
        await self._maintain_connection()

    async def stop(self):
        """Stop listening."""
        self.running = False
        if self.watchdog_task:
            self.watchdog_task.cancel()
        if self.websocket:
            await self.websocket.close()

    async def _maintain_connection(self):
        """Maintain WebSocket connection."""
        while self.running:
            # Phase 25: Clear subscription tracking to prevent memory leaks on reconnect
            self.subscriptions.clear()
            self.subscription_counter = 1
            
            try:
                logger.info(f"🔌 Connecting to {self.rpc_ws_url}...")
                async with websockets.connect(self.rpc_ws_url) as websocket:
                    self.websocket = websocket
                    logger.info("✅ Connected to RPC WebSocket")
                    self.last_msg_time = time.time()
                    if not self.watchdog_task or self.watchdog_task.done():
                        self.watchdog_task = asyncio.create_task(self._watchdog())

                    # Subscribe to all target programs
                    await self._subscribe_to_programs()
                    # Phase 40: Subscribe to slots for heartbeat
                    await self._subscribe_to_slots()

                    # Listen for messages
                    async for message in websocket:
                        self.last_msg_time = time.time()
                        try:
                            await self._handle_message(message)
                        except Exception as e:
                            logger.error(f"Error handling message: {e}")

            except Exception as e:
                logger.warning(f"WebSocket connection error: {e}")
                if self.running:
                    await asyncio.sleep(5.0)

    async def _watchdog(self):
        """Monitor RPC WebSocket health (Phase 40)."""
        while self.running:
            try:
                if self.websocket and self.last_msg_time > 0:
                    if time.time() - self.last_msg_time > 5.0:
                        logger.warning("🚨 RPC WebSocket watchdog: No messages for 5s! Force reconnecting...")
                        await self.websocket.close()
                await asyncio.sleep(1.0)
            except Exception as e:
                logger.error(f"RPC watchdog error: {e}")
                await asyncio.sleep(1.0)

    async def _subscribe_to_slots(self):
        """Subscribe to slot updates for heartbeat (Phase 40)."""
        if not self.websocket:
            return
        try:
            msg = {
                "jsonrpc": "2.0",
                "id": 999,
                "method": "slotSubscribe",
                "params": []
            }
            await self.websocket.send(orjson.dumps(msg))
            logger.info("📡 Subscribed to slots for heartbeat watchdog")
        except Exception as e:
            logger.error(f"Failed to subscribe to slots: {e}")

    async def _subscribe_to_programs(self):
        """Subscribe to logs for all target programs."""
        for program_id in self.TARGET_PROGRAMS.keys():
            await self._subscribe_to_program(program_id)

    async def _subscribe_to_program(self, program_id: str):
        """Subscribe to logs for a specific program."""
        if not self.websocket:
            return

        subscription_id = self.subscription_counter
        self.subscription_counter += 1

        # Use programSubscribe with dataSize filter instead of logsSubscribe
        # This prevents flooding from all program interactions
        subscribe_request = {
            "jsonrpc": "2.0",
            "id": subscription_id,
            "method": "programSubscribe",
            "params": [
                program_id,
                {
                    "commitment": "processed",
                    "filters": [
                        # Phase 21: Raydium AMM v4 pool state is 752 bytes, standard SPL is 165
                        {"dataSize": 752 if program_id == "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8" else 165},
                    ]
                }
            ],
        }

        try:
            await self.websocket.send(orjson.dumps(subscribe_request))
            self.subscriptions[program_id] = subscription_id
            logger.info(
                f"📡 Subscribed to logs for {self.TARGET_PROGRAMS.get(program_id, program_id)[:8]}..."
            )

        except Exception as e:
            logger.error(f"Failed to subscribe to {program_id}: {e}")

    async def _handle_message(self, message: str):
        """Handle incoming WebSocket message."""
        try:
            data = orjson.loads(message)

            # Handle subscription confirmations
            if "id" in data and data.get("result"):
                logger.debug(f"Subscription confirmed: {data['id']}")
                return

            # Handle log notifications
            if data.get("method") == "logsNotification":
                await self._handle_logs_notification(data["params"])

        except Exception:
            logger.error(f"Invalid JSON message: {message[:100]}...")
        except Exception as e:
            logger.error(f"Error processing WebSocket message: {e}")

    async def _handle_logs_notification(self, params: Dict[str, Any]):
        """Handle logs notification for pool creation detection."""
        try:
            result = params["result"]
            logs = result["value"]["logs"]
            signature = result.get("value", {}).get("signature", "")
            slot = params.get("result", {}).get("context", {}).get("slot", 0)

            # Quick check for pool creation indicators in logs
            if not self._quick_log_check(logs):
                return

            # Fetch full transaction to parse properly
            pool_event = await self._fetch_and_parse_transaction(signature, slot)
            if pool_event:
                logger.info(f"🎯 Pool creation detected: {pool_event}")
                if self.event_callback:
                    await self.event_callback(pool_event)

        except Exception as e:
            logger.error(f"Error handling logs notification: {e}")

    def _quick_log_check(self, logs: List[str]) -> bool:
        """Quick check if logs indicate pool creation."""
        for log in logs:
            log_lower = log.lower()
            if (
                ("initialize" in log_lower and "pool" in log_lower)
                or ("create" in log_lower and "pool" in log_lower)
                or ("amm" in log_lower and "initialize" in log_lower)
            ):
                return True
        return False

    async def _fetch_and_parse_transaction(
        self, signature: str, slot: int
    ) -> Optional[PoolCreationEvent]:
        """Fetch transaction and parse pool creation details."""
        try:
            if not self.session:
                return None

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTransaction",
                "params": [
                    signature,
                    {
                        "encoding": "jsonParsed",
                        "commitment": "confirmed",
                        "maxSupportedTransactionVersion": 0,
                    },
                ],
            }

            async with self.session.post(
                self.rpc_http_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=1.0),
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        f"Failed to fetch transaction {signature}: {resp.status}"
                    )
                    return None

                data = await resp.json()
                if "result" not in data or not data["result"]:
                    return None

                return self._parse_transaction_data(data["result"], signature, slot)

        except Exception as e:
            logger.error(f"Error fetching/parsing transaction {signature}: {e}")
            return None

    def _parse_transaction_data(
        self, tx_data: Dict[str, Any], signature: str, slot: int
    ) -> Optional[PoolCreationEvent]:
        """Parse transaction data to extract pool creation details."""
        try:
            transaction = tx_data.get("transaction", {})
            meta = tx_data.get("meta", {})
            if not transaction or not meta:
                return None

            instructions = transaction.get("message", {}).get("instructions", [])
            if not instructions:
                return None

            # Find the program that triggered the log
            for instruction in instructions:
                program_id = instruction.get("programId")
                if program_id in self.TARGET_PROGRAMS:
                    # Parse accounts based on program
                    if (
                        program_id == "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
                    ):  # Raydium AMM v4
                        return self._parse_raydium_amm_v4(instruction, signature, slot)
                    # Add other programs here

            return None

        except Exception as e:
            logger.error(f"Error parsing transaction data: {e}")
            return None

    def _parse_raydium_amm_v4(
        self, instruction: Dict[str, Any], signature: str, slot: int
    ) -> Optional[PoolCreationEvent]:
        """Parse Raydium AMM v4 initialize instruction."""
        try:
            accounts = instruction.get("accounts", [])
            if len(accounts) < 11:  # Raydium initialize has many accounts
                return None

            # Raydium AMM v4 initialize instruction accounts:
            # 0: amm_authority
            # 1: amm_open_orders
            # 2: amm_target_orders
            # 3: amm_coin_vault
            # 4: amm_pc_vault
            # 5: amm_withdraw_queue
            # 6: amm_temp_lp_vault
            # 7: serum_program
            # 8: serum_market
            # 9: coin_mint
            # 10: pc_mint
            # etc.

            if len(accounts) >= 11:
                base_mint = accounts[9]  # coin_mint
                quote_mint = accounts[10]  # pc_mint
                pool_address = accounts[
                    0
                ]  # amm_authority or first account as identifier

                return PoolCreationEvent(
                    program_id="675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
                    pool_address=pool_address,
                    base_mint=base_mint,
                    quote_mint=quote_mint,
                    timestamp=time.time(),
                    slot=slot,
                    signature=signature,
                )

        except Exception as e:
            logger.error(f"Error parsing Raydium AMM v4 instruction: {e}")

        return None

    def _parse_pool_creation_logs(
        self, logs: List[str], signature: str, slot: int
    ) -> Optional[PoolCreationEvent]:
        """
        Parse transaction logs to detect pool creation events.

        This is a simplified parser - in production, would need to:
        - Parse actual instruction data
        - Handle different program layouts
        - Extract exact addresses from instruction data
        """
        try:
            # Look for initialization instructions in logs
            for log in logs:
                log_lower = log.lower()

                # Raydium AMM v4 pool creation indicators
                if (
                    ("initialize" in log_lower and "pool" in log_lower)
                    or ("create" in log_lower and "pool" in log_lower)
                    or ("amm" in log_lower and "initialize" in log_lower)
                    or ("pool" in log_lower and "initialize" in log_lower)
                ):

                    # Extract program ID from the subscription that triggered this
                    program_id = None
                    for prog_id, sub_id in self.subscriptions.items():
                        # This is simplified - in practice would track which subscription triggered
                        program_id = prog_id
                        break

                    if not program_id:
                        continue

                    # Placeholder addresses - in production would parse from instruction data
                    # This requires decoding the actual transaction instructions
                    pool_address = "11111111111111111111111111111112"
                    base_mint = "So11111111111111111111111111111112"  # SOL placeholder
                    quote_mint = "11111111111111111111111111111112"

                    return PoolCreationEvent(
                        program_id=program_id,
                        pool_address=pool_address,
                        base_mint=base_mint,
                        quote_mint=quote_mint,
                        timestamp=time.time(),
                        slot=slot,
                        signature=signature,
                    )

        except Exception as e:
            logger.error(f"Error parsing pool creation logs: {e}")

        return None


class JitoBundleSender:
    """Sends transactions as Jito bundles using shotgun approach."""

    # Jito regional endpoint — single NY endpoint for Helius (US-based RPC)
    # to avoid blockhash geo-delay (BlockhashNotFound from cross-continent ping).
    # cfg.JITO_ENDPOINTS (from arb_bot.py) is passed at construction time and used instead.
    JITO_DEFAULT_ENDPOINT = "https://ny.mainnet.block-engine.jito.wtf/api/v1/bundles"
    JITO_ENDPOINTS = [JITO_DEFAULT_ENDPOINT]

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        jito_endpoints: Optional[List[str]] = None,
        auth_key: Optional[str] = None,
    ):
        self.session = session
        self._session_owned = session is None  # Will be created in __aenter__
        self.jito_endpoints = jito_endpoints or self.JITO_ENDPOINTS
        self.auth_key = auth_key

    async def __aenter__(self):
        if self._session_owned and self.session is None:
            self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session_owned and self.session:
            await self.session.close()

    async def send_bundle(
        self, transaction: VersionedTransaction, bundle_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send transaction as Jito bundle to multiple endpoints simultaneously.

        Args:
            transaction: Signed VersionedTransaction to bundle
            bundle_id: Optional bundle identifier

        Returns:
            Dict with results from all endpoints
        """
        # Convert transaction to bundle format (Jito requires base58)
        import base58
        tx_base58 = base58.b58encode(bytes(transaction)).decode('ascii')
        bundle_data = [[tx_base58]]

        # Send to the single configured endpoint (geo-single mode to prevent blockhash drift)
        tasks = []
        for endpoint in self.jito_endpoints:
            tasks.append(self._send_to_endpoint(endpoint, bundle_data))

        # Wait for first completion or all failures
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        success_count = 0
        first_bundle_id = None
        errors = []

        for i, result in enumerate(results):
            endpoint = self.jito_endpoints[i]

            if isinstance(result, Exception):
                errors.append(f"{endpoint}: {str(result)}")
                continue

            if result.get("success"):
                success_count += 1
                if not first_bundle_id:
                    first_bundle_id = result.get("bundle_id")
                logger.info(
                    f"✅ Bundle sent to {endpoint.split('.')[0]}: {result.get('bundle_id')}"
                )
            else:
                errors.append(f"{endpoint}: {result.get('error', 'Unknown error')}")

        response = {
            "success": success_count > 0,
            "success_count": success_count,
            "total_endpoints": len(self.jito_endpoints),
            "first_bundle_id": first_bundle_id,
            "errors": errors,
        }

        if success_count > 0:
            logger.info(
                f"✅ Bundle delivered: {success_count}/1 endpoint"
            )
        else:
            logger.error(f"❌ Bundle send failed on the sole endpoint: {errors}")

        return response

    async def _send_to_endpoint(
        self, endpoint: str, bundle_data: List
    ) -> Dict[str, Any]:
        """Send bundle to a specific Jito endpoint."""
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendBundle",
                "params": bundle_data,
            }

            async with self.session.post(
                endpoint,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=1.0),  # 1 second timeout
            ) as response:

                result = await response.json()

                if response.status == 200 and "result" in result:
                    bundle_id = result["result"]
                    return {
                        "success": True,
                        "bundle_id": bundle_id,
                        "endpoint": endpoint,
                    }
                else:
                    error_msg = result.get("error", {}).get("message", "Unknown error")
                    return {"success": False, "error": error_msg, "endpoint": endpoint}

        except asyncio.TimeoutError:
            return {"success": False, "error": "Timeout", "endpoint": endpoint}
        except Exception as e:
            return {"success": False, "error": str(e), "endpoint": endpoint}


class TransactionTipBuilder:
    """Builds transactions with Jito tips for sniping."""

    def __init__(
        self,
        tip_manager: JitoTipManager,
        jupiter_builder: Optional["JupiterTxBuilder"] = None,
    ):
        self.tip_manager = tip_manager
        self.jupiter_builder = jupiter_builder

    async def build_sniping_transaction(
        self,
        pool_event: PoolCreationEvent,
        buyer_keypair: Keypair,
        buy_amount_lamports: int = 1_000_000_000,  # 1 SOL
        recent_blockhash: Optional[Hash] = None,
    ) -> Optional[VersionedTransaction]:
        """
        Build a sniping transaction with swap + tip instructions.

        Args:
            pool_event: Pool creation event with addresses
            buyer_keypair: Keypair for signing
            buy_amount_lamports: Amount to spend on buy (in lamports)
            recent_blockhash: Recent blockhash for transaction

        Returns:
            Signed VersionedTransaction ready for bundling
        """
        try:
            # For now, create a placeholder transaction with tip
            # In production, would include actual swap instructions for Raydium/Pump.fun

            # Get optimal tip amount
            tip_amount = self.tip_manager.get_optimal_tip()
            tip_account = self.tip_manager.get_random_tip_account()

            logger.info(
                f"💰 Building sniping tx: {buy_amount_lamports/1e9:.3f} SOL buy + {tip_amount} lamports tip"
            )

            # Create tip instruction
            tip_ix = transfer(
                TransferParams(
                    from_pubkey=buyer_keypair.pubkey(),
                    to_pubkey=Pubkey.from_string(tip_account),
                    lamports=tip_amount,
                )
            )

            # Placeholder: In production, add swap instruction here
            # swap_ix = create_raydium_swap_instruction(...)

            all_instructions = [tip_ix]  # Add swap_ix when implemented

            # Phase 30: Inject fresh blockhash from racing manager at the last second
            if recent_blockhash is None:
                from ingest.blockhash_racing import get_blockhash_manager
                bh_mgr = get_blockhash_manager()
                if bh_mgr:
                    recent_blockhash = await bh_mgr.get_fresh_blockhash()
                
                if recent_blockhash is None:
                    logger.error("❌ Failed to get fresh blockhash for sniping transaction")
                    return None

            # Build message
            message = MessageV0.try_compile(
                payer=buyer_keypair.pubkey(),
                instructions=all_instructions,
                address_lookup_table_accounts=[],  # Add LUTs if needed
                recent_blockhash=recent_blockhash,
            )

            # Create and sign transaction
            transaction = VersionedTransaction(message, [buyer_keypair])

            logger.info("✅ Sniping transaction built and signed")
            return transaction

        except Exception as e:
            logger.error(f"Error building sniping transaction: {e}")
            return None
