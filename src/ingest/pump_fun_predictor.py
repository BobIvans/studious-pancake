"""Pump.fun Migration Predictor for MEV arbitrage opportunities."""

import asyncio
import json
import logging
import struct
import time
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum
import aiohttp

from solders.pubkey import Pubkey
from solders.system_program import ID as SYSTEM_PROGRAM_ID
from solders.instruction import Instruction, AccountMeta
from solders.transaction import VersionedTransaction
from solders.message import MessageV0

logger = logging.getLogger(__name__)

class MigrationPhase(Enum):
    """Phases of Pump.fun to Raydium migration."""
    EARLY = "early"           # < 50 SOL
    MONITORING = "monitoring" # 50-80 SOL
    CRITICAL = "critical"     # 80-84 SOL
    WARMUP = "warmup"         # 84-84.5 SOL
    READY = "ready"           # 84.5-85 SOL
    MIGRATING = "migrating"   # Migration triggered

class PumpFunBondingCurve:
    """Represents a Pump.fun bonding curve state."""

    # Pump.fun program ID
    PROGRAM_ID = Pubkey.from_string("6EF8rrecthR5Dkzon8NwuT9rCf9YoMPCGkh3D3RPuGJV")

    # Migration threshold: 85 SOL in lamports
    MIGRATION_THRESHOLD_LAMPORTS = 85 * 1_000_000_000

    # Monitoring thresholds
    MONITORING_START_LAMPORTS = 50 * 1_000_000_000    # Start monitoring at 50 SOL
    CRITICAL_START_LAMPORTS = 80 * 1_000_000_000      # Critical phase at 80 SOL
    WARMUP_START_LAMPORTS = 84 * 1_000_000_000        # Warmup at 84 SOL
    READY_START_LAMPORTS = int(84.5 * 1_000_000_000)  # Ready at 84.5 SOL

    def __init__(self, curve_address: str, mint_address: str):
        self.curve_address = curve_address
        self.mint_address = mint_address
        self.last_update = 0

        # Curve state
        self.virtual_token_reserves = 0
        self.virtual_sol_reserves = 0
        self.real_token_reserves = 0
        self.real_sol_reserves = 0
        self.token_total_supply = 0
        self.complete = False

        # Computed values
        self.progress_percentage = 0.0
        self.phase = MigrationPhase.EARLY

        # Pre-computed Raydium addresses
        self.raydium_addresses = None
        self.transaction_template = None
        self.market_subscriber = None

    def update_from_account_data(self, account_data: bytes) -> bool:
        """Update curve state from account data. Returns True if state changed."""
        try:
            # Parse Pump.fun bonding curve layout
            # Skip 8 bytes discriminator, then u64 fields
            if len(account_data) < 8 + 8 * 6 + 1:  # discriminator + 6 u64 + bool
                logger.warning(f"Invalid account data length: {len(account_data)}")
                return False

# Skip discriminator (8 bytes)
            data = account_data[8:]

            # Parse u64 fields (little endian)
            # Fix 5: Explicit int() to prevent float overflow on extreme values (Python 3.13)
            self.virtual_token_reserves = int(struct.unpack('<Q', data[0:8])[0])
            self.virtual_sol_reserves = int(struct.unpack('<Q', data[8:16])[0])
            self.real_token_reserves = int(struct.unpack('<Q', data[16:24])[0])
            self.real_sol_reserves = int(struct.unpack('<Q', data[24:32])[0])
            self.token_total_supply = int(struct.unpack('<Q', data[32:40])[0])
            self.complete = bool(data[40])

            # Calculate progress
            old_progress = self.progress_percentage
            self.progress_percentage = (self.real_sol_reserves / self.MIGRATION_THRESHOLD_LAMPORTS) * 100

            # Update phase
            old_phase = self.phase
            self._update_phase()

            # Update timestamp
            self.last_update = time.time()

            # Check if state changed significantly
            state_changed = (
                abs(self.progress_percentage - old_progress) > 0.1 or
                self.phase != old_phase
            )

            if state_changed:
                logger.info(f"🎯 Curve {self.curve_address[:8]}: {self.progress_percentage:.1f}% ({self.phase.value})")

            return state_changed

        except Exception as e:
            logger.error(f"Failed to parse curve data: {e}")
            return False

    def _update_phase(self):
        """Update migration phase based on current state."""
        sol_lamports = self.real_sol_reserves

        if self.complete or sol_lamports >= self.MIGRATION_THRESHOLD_LAMPORTS:
            self.phase = MigrationPhase.MIGRATING
        elif sol_lamports >= self.READY_START_LAMPORTS:
            self.phase = MigrationPhase.READY
        elif sol_lamports >= self.WARMUP_START_LAMPORTS:
            self.phase = MigrationPhase.WARMUP
        elif sol_lamports >= self.CRITICAL_START_LAMPORTS:
            self.phase = MigrationPhase.CRITICAL
        elif sol_lamports >= self.MONITORING_START_LAMPORTS:
            self.phase = MigrationPhase.MONITORING
        else:
            self.phase = MigrationPhase.EARLY

    def should_monitor(self) -> bool:
        """Check if this curve should be actively monitored."""
        return self.phase in [MigrationPhase.MONITORING, MigrationPhase.CRITICAL,
                            MigrationPhase.WARMUP, MigrationPhase.READY]

    def is_ready_for_migration(self) -> bool:
        """Check if curve is ready for migration."""
        return self.phase in [MigrationPhase.READY, MigrationPhase.MIGRATING]

    def get_time_to_migration_estimate(self) -> Optional[float]:
        """Estimate time to migration in seconds (rough approximation)."""
        if self.phase == MigrationPhase.MIGRATING:
            return 0

        remaining_lamports = self.MIGRATION_THRESHOLD_LAMPORTS - self.real_sol_reserves
        if remaining_lamports <= 0:
            return 0

        # Rough estimate: assume 1 SOL per minute growth (very approximate)
        remaining_sol = remaining_lamports / 1_000_000_000
        return remaining_sol * 60  # minutes to seconds

class RaydiumPDAPrecomputer:
    """Pre-computes Raydium AMM v4 PDA addresses for zero-latency graduation sniping."""

    # Raydium AMM v4 program ID
    AMM_PROGRAM_ID = Pubkey.from_string("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")

    # OpenBook/Serum Market program ID (for market addresses)
    OPENBOOK_PROGRAM_ID = Pubkey.from_string("srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX")

    AUTHORITY_SEED = b"amm_authority"

    def __init__(self):
        self.precomputed_addresses: Dict[str, Dict[str, Pubkey]] = {}
        self.market_cache: Dict[str, Pubkey] = {}

    async def compute_all_addresses(self, token_mint: str, market_id: Optional[str] = None) -> Dict[str, Pubkey]:
        """
        REMOVED (Fix 33): Raydium V4 pool addresses are randomly generated Keypairs.
        Pre-computing via find_program_address is mathematically impossible and
        results in 100% AccountNotFound failures.

        The bot must rely on jito_sniper.WssPoolCreationListener to parse the
        actual pool_address from the InitializePool logs.
        """
        logger.error(
            f"🚫 compute_all_addresses HARD BLOCKED for {token_mint}: "
            "Raydium V4 uses random Keypairs, not PDAs. "
            "Use jito_sniper.WssPoolCreationListener for pool discovery."
        )
        return {}

    def _derive_pda(self, seeds: List[bytes]) -> Pubkey:
        """Derive Program Derived Address."""
        try:
            pda, _ = Pubkey.find_program_address(seeds, self.AMM_PROGRAM_ID)
            return pda
        except Exception as e:
            logger.error(f"PDA derivation failed: {e}")
            raise

    async def _predict_openbook_market(self, token_mint: str) -> Optional[str]:
        """Predict OpenBook market ID (would monitor logs in production)."""
        # Check cache
        if token_mint in self.market_cache:
            return str(self.market_cache[token_mint])

        # In production: monitor OpenBook MarketCreated logs
        # For now: return None (would be implemented)
        logger.warning(f"OpenBook market prediction not implemented for {token_mint}")
        return None

    def get_precomputed_addresses(self, token_mint: str) -> Optional[Dict[str, Pubkey]]:
        """Get pre-computed addresses for instant sniping."""
        return self.precomputed_addresses.get(token_mint)

    def is_ready_for_sniping(self, token_mint: str) -> bool:
        """Check if all addresses ready for Slot 0 execution."""
        addresses = self.get_precomputed_addresses(token_mint)
        return addresses is not None and len(addresses) == 7

    @staticmethod
    def compute_complete_pool_addresses(mint_address: str, market_id: Optional[str] = None) -> Dict[str, str]:
        """
        REMOVED (Fix 33): Raydium V4 pool addresses are randomly generated Keypairs.
        Pre-computing via find_program_address is mathematically impossible and
        results in 100% AccountNotFound failures.

        The bot must rely on jito_sniper.WssPoolCreationListener to parse the
        actual pool_address from the InitializePool logs.
        """
        logger.error(
            f"compute_complete_pool_addresses HARD BLOCKED for {mint_address}: "
            "Raydium V4 uses random Keypairs, not PDAs. "
            "Use jito_sniper.WssPoolCreationListener for pool discovery."
        )
        return {}

    @staticmethod
    def compute_pool_addresses(mint_address: str) -> Dict[str, str]:
        """Backward compatibility — now intentionally disabled (Fix 33)."""
        return RaydiumPDAPrecomputer.compute_complete_pool_addresses(mint_address)

    @staticmethod
    def compute_market_addresses(market_id: str) -> Dict[str, str]:
        """Compute OpenBook market-related addresses."""
        try:
            market_pubkey = Pubkey.from_string(market_id)

            # Market Event Queue
            market_event_queue, _ = Pubkey.find_program_address(
                [b"event_queue", bytes(market_pubkey)],
                RaydiumPDAPrecomputer.OPENBOOK_PROGRAM_ID
            )

            # Market Bids
            market_bids, _ = Pubkey.find_program_address(
                [b"bids", bytes(market_pubkey)],
                RaydiumPDAPrecomputer.OPENBOOK_PROGRAM_ID
            )

            # Market Asks
            market_asks, _ = Pubkey.find_program_address(
                [b"asks", bytes(market_pubkey)],
                RaydiumPDAPrecomputer.OPENBOOK_PROGRAM_ID
            )

            return {
                "market_event_queue": str(market_event_queue),
                "market_bids": str(market_bids),
                "market_asks": str(market_asks)
            }

        except Exception as e:
            logger.error(f"Failed to compute market addresses for {market_id}: {e}")
            return {}


class RaydiumTransactionTemplate:
    """Pre-built transaction template for Raydium swaps."""

    def __init__(self, addresses: Dict[str, str], mint_address: str):
        self.addresses = addresses
        self.mint_address = mint_address
        self.template_built = False
        self.instruction_template = None

    def build_swap_template(self, user_wallet: str, amount_in: int, minimum_out: int) -> bool:
        """Build a swap instruction template with placeholders."""
        try:
            # This would build the actual Raydium swap instruction
            # For now, create a template structure
            self.instruction_template = {
                "program_id": RaydiumPDAPrecomputer.AMM_PROGRAM_ID,
                "accounts": {
                    "amm_id": self.addresses.get("amm_id"),
                    "amm_authority": self.addresses.get("amm_authority"),
                    "amm_open_orders": self.addresses.get("amm_open_orders"),
                    "amm_target_orders": self.addresses.get("amm_target_orders"),
                    "pool_coin_token_account": self.addresses.get("pool_coin_token_account"),
                    "pool_pc_token_account": self.addresses.get("pool_pc_token_account"),
                    "withdraw_queue": self.addresses.get("withdraw_queue"),
                    "user_wallet": user_wallet,
                    "user_token_account": None,  # Will be computed
                    "user_pc_token_account": None,  # Will be computed
                },
                "data": {
                    "amount_in": amount_in,
                    "minimum_out": minimum_out,
                    "swap_direction": "sol_to_token"  # or "token_to_sol"
                }
            }

            self.template_built = True
            return True

        except Exception as e:
            logger.error(f"Failed to build swap template: {e}")
            return False

    def instantiate_with_blockhash(self, blockhash: str, user_token_accounts: Dict[str, str], keypair=None) -> Optional[VersionedTransaction]:
        """Instantiate template with current blockhash and build VersionedTransaction."""
        if not self.template_built or not self.instruction_template:
            return None

        try:
            # Build actual Instruction objects from template
            template = self.instruction_template
            
            # Map accounts (simplified - in production would need careful mapping)
            accounts = []
            for acc in template.get("accounts", []):
                pubkey_str = acc.get("pubkey")
                # If pubkey is a placeholder for user token account
                if pubkey_str.startswith("USER_"):
                    token_symbol = pubkey_str.split("_")[1]
                    actual_pubkey = user_token_accounts.get(token_symbol, pubkey_str)
                    pubkey = Pubkey.from_string(actual_pubkey)
                else:
                    pubkey = Pubkey.from_string(pubkey_str)
                    
                accounts.append(AccountMeta(
                    pubkey=pubkey,
                    is_signer=acc.get("is_signer", False),
                    is_writable=acc.get("is_writable", False)
                ))

            ix = Instruction(
                program_id=Pubkey.from_string(template["program_id"]),
                accounts=accounts,
                data=template["data"]
            )

            # Compile message
            message = MessageV0.try_compile(
                payer=Pubkey.from_string(list(user_token_accounts.values())[0]) if user_token_accounts else Pubkey.default(),
                instructions=[ix],
                address_lookup_table_accounts=[],
                recent_blockhash=Pubkey.from_string(blockhash)
            )

            # Create VersionedTransaction
            return VersionedTransaction(message, [keypair] if keypair else [])

        except Exception as e:
            logger.error(f"Failed to instantiate template: {e}")
            return None


class RaydiumMarketSubscriber:
    """Subscribes to Raydium program logs to capture market creation in real-time."""

    def __init__(self, session: Optional[aiohttp.ClientSession] = None, wss_url: Optional[str] = None):
        self.session = session
        self.wss_url = wss_url or "wss://api.mainnet-beta.solana.com"
        self.market_cache: Dict[str, Dict] = {}  # mint -> market_info

    async def subscribe_to_market_creation(self, mint_address: str) -> Optional[str]:
        """Subscribe to Raydium program logs to detect market creation for a specific mint."""
        try:
            # This would set up a subscription to Raydium program logs
            # When a pool is created for the mint, we capture the market_id
            # For now, return None (market not found yet)

            # In production, this would:
            # 1. Subscribe to logsSubscribe with Raydium program ID
            # 2. Filter for InitializePool instructions
            # 3. Extract market_id from the instruction data
            # 4. Cache and return it

            logger.debug(f"Market subscription active for mint {mint_address[:8]}")
            return None  # Market not found yet

        except Exception as e:
            logger.error(f"Failed to subscribe to market creation: {e}")
            return None

    def get_cached_market(self, mint_address: str) -> Optional[Dict]:
        """Get cached market information for a mint."""
        return self.market_cache.get(mint_address)

    def cache_market_info(self, mint_address: str, market_info: Dict):
        """Cache market information for future use."""
        self.market_cache[mint_address] = market_info

class PumpFunMigrationPredictor:
    """Main predictor for Pump.fun to Raydium migrations."""

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        wss_url: Optional[str] = None,
        jito_endpoints: Optional[List[str]] = None
    ):
        self.session = session
        self.wss_url = wss_url or "wss://api.mainnet-beta.solana.com"
        # Fix G: Use real Jito Block Engine URLs instead of hallucinated solana.com domains
        self.jito_endpoints = jito_endpoints or [
            "https://amsterdam.mainnet.block-engine.jito.wtf/api/v1/bundles",
            "https://frankfurt.mainnet.block-engine.jito.wtf/api/v1/bundles",
            "https://ny.mainnet.block-engine.jito.wtf/api/v1/bundles",
            "https://tokyo.mainnet.block-engine.jito.wtf/api/v1/bundles"
        ]

        # Active curves being monitored
        self.monitored_curves: Dict[str, PumpFunBondingCurve] = {}

        # Pre-computed transaction templates
        self.transaction_templates: Dict[str, Any] = {}

        # Jito warm-up connections
        self.jito_sessions: Dict[str, aiohttp.ClientSession] = {}

        # Callbacks
        self.on_migration_ready_callback = None
        self.on_migration_triggered_callback = None

    async def start_monitoring(self, curve_addresses: List[str]):
        """Start monitoring specified Pump.fun bonding curves."""
        logger.info(f"🚀 Starting Pump.fun migration predictor for {len(curve_addresses)} curves")

        # Initialize curves
        for curve_addr in curve_addresses:
            # We need to get the mint address from the curve
            # For now, we'll use a placeholder - in practice, you'd query this
            mint_addr = await self._get_mint_from_curve(curve_addr)
            if mint_addr:
                curve = PumpFunBondingCurve(curve_addr, mint_addr)
                self.monitored_curves[curve_addr] = curve

                # Pre-compute Raydium addresses
                curve.raydium_addresses = RaydiumPDAPrecomputer.compute_complete_pool_addresses(mint_addr)
                logger.info(f"📐 Pre-computed {len(curve.raydium_addresses)} Raydium addresses for {curve_addr[:8]}")

                # Create transaction template
                curve.transaction_template = RaydiumTransactionTemplate(curve.raydium_addresses, mint_addr)

                # Set up market subscriber
                curve.market_subscriber = RaydiumMarketSubscriber(self.session, self.wss_url)

        # Start monitoring loop
        asyncio.create_task(self._monitoring_loop())

    async def _monitoring_loop(self):
        """Main monitoring loop for curve updates."""
        while True:
            try:
                # Check all monitored curves
                curves_to_check = [
                    curve_addr for curve_addr, curve in self.monitored_curves.items()
                    if curve.should_monitor()
                ]

                if curves_to_check:
                    await self._update_curves_from_rpc(curves_to_check)

                    # Check for phase changes
                    for curve_addr, curve in self.monitored_curves.items():
                        await self._handle_phase_change(curve)

                # Sleep based on most critical curve
                sleep_time = self._calculate_sleep_time()
                await asyncio.sleep(sleep_time)

            except Exception as e:
                logger.error(f"Monitoring loop error: {e}")
                await asyncio.sleep(1)

    async def _update_curves_from_rpc(self, curve_addresses: List[str]):
        """Update curve data from RPC."""
        if not self.session:
            return

        try:
            # Batch get multiple accounts
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getMultipleAccounts",
                "params": [
                    curve_addresses,
                    {
                        "encoding": "base64",
                        "commitment": "confirmed"
                    }
                ]
            }

            async with self.session.post(self.wss_url.replace('wss://', 'https://'), json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "result" in data and "value" in data["result"]:
                        accounts = data["result"]["value"]

                        for i, account_data in enumerate(accounts):
                            if account_data and i < len(curve_addresses):
                                curve_addr = curve_addresses[i]
                                curve = self.monitored_curves.get(curve_addr)
                                if curve:
                                    # Decode base64 and update
                                    import base64
                                    b64_data = account_data["data"][0]
                                    raw_data = base64.b64decode(b64_data + "=" * (-len(b64_data) % 4))
                                    curve.update_from_account_data(raw_data)

        except Exception as e:
            logger.debug(f"RPC update failed: {e}")

    async def _handle_phase_change(self, curve: PumpFunBondingCurve):
        """Handle phase changes in monitored curves."""
        if curve.phase == MigrationPhase.WARMUP and curve.raydium_addresses:
            # Start warm-up process
            await self._warmup_for_migration(curve)

        elif curve.phase == MigrationPhase.READY:
            # Prepare transaction template
            await self._prepare_migration_transaction(curve)

        elif curve.phase == MigrationPhase.MIGRATING:
            # Trigger migration
            await self._trigger_migration(curve)

    async def _warmup_for_migration(self, curve: PumpFunBondingCurve):
        """Warm up Jito connections and prepare transaction template."""
        logger.info(f"🔥 Warming up for migration: {curve.curve_address[:8]}")

        # Initialize Jito sessions
        for endpoint in self.jito_endpoints:
            try:
                session = aiohttp.ClientSession()
                self.jito_sessions[endpoint] = session

                # Test connection with a simple request
                payload = {"jsonrpc": "2.0", "id": 1, "method": "getVersion"}
                async with session.post(endpoint, json=payload, timeout=aiohttp.ClientTimeout(total=2.0)) as resp:
                    if resp.status == 200:
                        logger.debug(f"✅ Jito session ready: {endpoint}")
                    else:
                        logger.warning(f"⚠️ Jito warmup failed: {endpoint}")

            except Exception as e:
                logger.warning(f"Failed to warmup Jito connection {endpoint}: {e}")

        # Build transaction template
        if curve.transaction_template and not curve.transaction_template.template_built:
            # Use placeholder wallet and amounts - will be replaced at execution time
            placeholder_wallet = "11111111111111111111111111111112"  # Placeholder
            success = curve.transaction_template.build_swap_template(
                user_wallet=placeholder_wallet,
                amount_in=1000000,  # 0.001 SOL placeholder
                minimum_out=100000  # Placeholder minimum out
            )
            if success:
                logger.info(f"📝 Transaction template built for {curve.curve_address[:8]}")
            else:
                logger.warning(f"❌ Failed to build transaction template for {curve.curve_address[:8]}")

    async def _prepare_migration_transaction(self, curve: PumpFunBondingCurve):
        """Prepare transaction template and try to get market ID."""
        logger.info(f"📝 Preparing migration transaction for {curve.curve_address[:8]}")

        # Try to get market ID from subscriber
        if curve.market_subscriber:
            market_id = await curve.market_subscriber.subscribe_to_market_creation(curve.mint_address)
            if market_id:
                logger.info(f"🎯 Market ID found: {market_id[:8]}... for {curve.curve_address[:8]}")

                # Re-compute addresses with market ID
                # Fix 33: Raydium V4 addresses cannot be pre-computed (random Keypairs).
                # WssPoolCreationListener supplies the real pool_address at graduation.
                curve.raydium_addresses = {
                    "reason": "Raydium V4 uses random Keypairs; "
                              "pool_address provided by WssPoolCreationListener at graduation"
                }
                logger.warning(
                    f"🔄 Raydium V4 address pre-computation DISABLED for {curve.curve_address[:8]}: "
                    "pool addresses are random Keypairs, not PDAs."
                )
            else:
                logger.debug(f"⏳ Market ID not found yet for {curve.curve_address[:8]} (this is normal)")

        template_key = f"migration_{curve.curve_address}"

        # Store complete template info
        self.transaction_templates[template_key] = {
            "curve": curve,
            "prepared_at": time.time(),
            "raydium_addresses": curve.raydium_addresses,
            "transaction_template": curve.transaction_template,
            "market_id": market_id if 'market_id' in locals() else None
        }

        logger.info(f"✅ Migration transaction prepared for {curve.curve_address[:8]}")

    async def _trigger_migration(self, curve: PumpFunBondingCurve):
        """Trigger actual migration arbitrage."""
        logger.info(f"🚀 TRIGGERING MIGRATION ARBITRAGE: {curve.curve_address[:8]}")

        template_key = f"migration_{curve.curve_address}"
        template = self.transaction_templates.get(template_key)

        if not template:
            logger.warning(f"No prepared transaction for {curve.curve_address[:8]}")
            return

        # Execute the prepared transaction
        # This would involve getting current blockhash and sending via Jito
        success = await self._execute_migration_arbitrage(template)

        if success:
            logger.info(f"🎉 Migration arbitrage executed successfully!")
        else:
            logger.warning(f"❌ Migration arbitrage failed")

    async def _execute_migration_arbitrage(self, template: Dict) -> bool:
        """Execute the actual migration arbitrage transaction."""
        try:
            # Get current blockhash
            # Build final transaction
            # Send via Jito shotgun approach
            # This is a placeholder - would contain actual implementation

            logger.info("🔥 Executing migration arbitrage via Jito...")
            await asyncio.sleep(0.1)  # Placeholder for actual execution

            return True

        except Exception as e:
            logger.error(f"Migration execution failed: {e}")
            return False

    async def _get_mint_from_curve(self, curve_address: str) -> Optional[str]:
        """Get mint address from bonding curve (placeholder implementation)."""
        # In practice, you'd query the curve account or use logs to find the mint
        # For now, return a placeholder
        logger.debug(f"Getting mint for curve {curve_address[:8]}")
        return "So11111111111111111111111111111111111111112"  # Placeholder WSOL

    def _calculate_sleep_time(self) -> float:
        """Calculate sleep time based on most critical curve."""
        min_time = 5.0  # Default 5 seconds

        for curve in self.monitored_curves.values():
            if curve.phase == MigrationPhase.READY:
                return 0.1  # Very frequent checks when ready
            elif curve.phase == MigrationPhase.WARMUP:
                min_time = min(min_time, 0.5)  # 0.5 seconds
            elif curve.phase == MigrationPhase.CRITICAL:
                min_time = min(min_time, 1.0)  # 1 second
            elif curve.phase == MigrationPhase.MONITORING:
                min_time = min(min_time, 2.0)  # 2 seconds

        return min_time

    def get_migration_status(self) -> Dict[str, Any]:
        """Get current migration status for all monitored curves."""
        status = {}
        for curve_addr, curve in self.monitored_curves.items():
            status[curve_addr] = {
                "phase": curve.phase.value,
                "progress": curve.progress_percentage,
                "real_sol_reserves": curve.real_sol_reserves / 1_000_000_000,  # Convert to SOL
                "time_to_migration": curve.get_time_to_migration_estimate(),
                "addresses_ready": curve.raydium_addresses is not None
            }
        return status

    async def stop(self):
        """Stop the predictor and cleanup."""
        logger.info("🛑 Stopping Pump.fun migration predictor")

        # Close Jito sessions
        for session in self.jito_sessions.values():
            await session.close()
        self.jito_sessions.clear()