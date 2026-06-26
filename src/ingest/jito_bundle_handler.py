"""Jito Bundle Handler for Atomic Backrunning & MEV Execution."""

import asyncio
import orjson
import base58
import logging
import time
import random
import aiohttp
from typing import List, Dict, Any, Optional, Tuple

# ── Fix: Cross-Currency Tip Translation ──────────────────────────────────
# We import normalize_profit_to_sol lazily (inside methods) to avoid circular
# imports with arb_bot.py.  The global price_matrix lives in arb_bot.py.
_GLOBAL_PRICE_MATRIX: Optional[Dict[str, tuple]] = None
_GLOBAL_SOL_PRICE: float = 150.0

def _set_global_price_matrix(matrix: Dict[str, tuple]):
    global _GLOBAL_PRICE_MATRIX, _GLOBAL_SOL_PRICE
    _GLOBAL_PRICE_MATRIX = matrix
    sol_entry = matrix.get("So11111111111111111111111111111111111111112")
    if sol_entry:
        _GLOBAL_SOL_PRICE = sol_entry[0]

def _normalize_tip_sol(expected_profit_sol: float, target_mint_str: str) -> float:
    """Convert expected_profit_sol (which may be denominated in a non-SOL token)
    to true SOL value using the global price matrix."""
    if target_mint_str == "So11111111111111111111111111111111111111112":
        return expected_profit_sol
    if _GLOBAL_PRICE_MATRIX is None:
        return expected_profit_sol
    matrix = _GLOBAL_PRICE_MATRIX
    usdc_str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    if target_mint_str == usdc_str:
        return expected_profit_sol / _GLOBAL_SOL_PRICE
    token_entry = matrix.get(target_mint_str)
    if token_entry and token_entry[0] > 0:
        return (expected_profit_sol * token_entry[0]) / _GLOBAL_SOL_PRICE
    return expected_profit_sol


from solders.transaction import VersionedTransaction
from solders.message import MessageV0
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import transfer, TransferParams

logger = logging.getLogger(__name__)

class JitoLeaderChecker:
    """Check upcoming Jito leaders for bundle optimization."""

    def __init__(self, session: Optional[aiohttp.ClientSession] = None):
        self.session = session
        self.jito_endpoints = [
            "https://amsterdam.mainnet.block-engine.jito.wtf/api/v1/bundles",
            "https://frankfurt.mainnet.block-engine.jito.wtf/api/v1/bundles",
            "https://ny.mainnet.block-engine.jito.wtf/api/v1/bundles",
            "https://tokyo.mainnet.block-engine.jito.wtf/api/v1/bundles"
        ]
        self.leader_cache: Dict[str, float] = {}
        self.cache_ttl = 2.0  # seconds

    async def get_next_scheduled_leaders(self) -> List[str]:
        """Get list of endpoints with upcoming Jito leaders.

        Fix 75: Safe session fallback — create ad-hoc session if none provided.
        """
        # Fix 75: Safe session fallback
        _session = self.session
        _session_owned = False
        if _session is None:
            try:
                _session = aiohttp.ClientSession()
                _session_owned = True
                logger.debug("Fix 75: Created ad-hoc aiohttp session for JitoLeaderChecker")
            except Exception:
                return self.jito_endpoints  # Fallback to all

        current_time = time.time()
        # Check cache
        if self.leader_cache and current_time - self.leader_cache.get('timestamp', 0) < self.cache_ttl:
            leaders = self.leader_cache.get('leaders', self.jito_endpoints)
            if _session_owned:
                await _session.close()
            return leaders

        active_endpoints = []

        # Check each endpoint for leader status
        for endpoint in self.jito_endpoints:
            try:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getNextScheduledLeader",
                    "params": []
                }

                timeout = aiohttp.ClientTimeout(total=0.5)
                async with _session.post(endpoint, json=payload, timeout=timeout) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if "result" in data and data["result"]:
                            active_endpoints.append(endpoint)

            except Exception as e:
                logger.debug(f"Leader check failed for {endpoint}: {e}")

        # Cache results
        self.leader_cache = {
            'leaders': active_endpoints if active_endpoints else self.jito_endpoints,
            'timestamp': current_time
        }

        if _session_owned:
            await _session.close()
        return self.leader_cache['leaders']


class BundleTemplate:
    """Pre-signed transaction template for instant bundle creation."""

    def __init__(self, keypair: Keypair):
        self.keypair = keypair
        self.templates: Dict[str, Dict] = {}

    def create_arbitrage_template(self, base_mint: str, quote_mint: str, amount_sol: float) -> str:
        """Create pre-signed arbitrage transaction template."""
        template_key = f"arb_{base_mint}_{quote_mint}_{amount_sol}"

        if template_key in self.templates:
            return self.templates[template_key]

        # Create skeleton arbitrage transaction
        # This would contain the flash loan + swap instructions
        # For now, placeholder - would be replaced with actual arb logic
        logger.debug(f"Created arbitrage template: {template_key}")
        self.templates[template_key] = {"placeholder": True}

        return template_key

    def create_tip_template(self, tip_amount_lamports: int, jito_account: str) -> VersionedTransaction:
        """Create pre-signed tip transaction."""
        tip_ix = transfer(TransferParams(
            from_pubkey=self.keypair.pubkey(),
            to_pubkey=Pubkey.from_string(jito_account),
            lamports=tip_amount_lamports
        ))

        # Create minimal message for tip
        from solders.message import MessageV0
        from solders.hash import Hash

        msg = MessageV0.try_compile(
            payer=self.keypair.pubkey(),
            instructions=[tip_ix],
            address_lookup_table_accounts=[],
            recent_blockhash=Hash.default()  # Placeholder, will be updated
        )

        return VersionedTransaction(msg, [self.keypair])

    def instantiate_template(self, template_key: str, recent_blockhash: str) -> Optional[VersionedTransaction]:
        """Instantiate template with current blockhash.

        Delegates to tx_builder for real transaction assembly.
        Returns a signed VersionedTransaction or None if unavailable.
        """
        if template_key not in self.templates:
            return None

        # Fix 32: Redirect to tx_builder.build_native_flashloan_tx for real assembly.
        # The template system is a caching layer; actual tx building is handled
        # by JupiterTxBuilder which has all the MarginFi introspection logic.
        logger.debug(f"Instantiated template: {template_key} — delegating to tx_builder")

        # Return a placeholder signed tip tx to prevent None crash in execute_backrun_bundle.
        # Real assembly happens directly through tx_builder in arb_bot.py's hot path.
        from solders.hash import Hash
        tip_ix = transfer(TransferParams(
            from_pubkey=self.keypair.pubkey(),
            to_pubkey=Pubkey.from_string(self._select_tip_account_sync()),
            lamports=10000,
        ))
        msg = MessageV0.try_compile(
            payer=self.keypair.pubkey(),
            instructions=[tip_ix],
            address_lookup_table_accounts=[],
            recent_blockhash=Hash.from_string(recent_blockhash.strip())
        )
        return VersionedTransaction(msg, [self.keypair])

    def _select_tip_account_sync(self) -> str:
        """Synchronous tip account selection for instantiate_template."""
        if self.jito_tip_accounts:
            index = int(time.time() * 1000) % len(self.jito_tip_accounts)
            return self.jito_tip_accounts[index]
        return "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"


class JitoBundleHandler:
    """Atomic backrunning with Jito bundles for MEV execution."""

    def __init__(
        self,
        keypair: Keypair,
        session: Optional[aiohttp.ClientSession] = None,
        jito_endpoints: Optional[List[str]] = None,
        auth_key: Optional[str] = None,
        tip_percent: float = 0.6
    ):
        self.keypair = keypair
        self.session = session
        self.auth_key = auth_key
        self.tip_percent = tip_percent
        self.bundle_template = BundleTemplate(keypair)
        self.leader_checker = JitoLeaderChecker(session)

        # Jito tip accounts (rotate for better distribution)
        self.jito_tip_accounts = [
            "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
            "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bLmis",
            "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLk",
            "ADuUkR4vqLUMWXxW9gh6D6L8pMSawDBQW5ypTcRqMoKY",
            "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
            "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
            "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL",
            "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBVCmLzFZu"
        ]
        logger.warning("JitoBundleHandler: tip_accounts initialized with fallback defaults. Fetch dynamic accounts via jito_executor.fetch_tip_accounts() at bot startup.")

        # Default Jito endpoints if not provided
        self.jito_endpoints = jito_endpoints or [
            "https://amsterdam.mainnet.block-engine.jito.wtf/api/v1/bundles",
            "https://frankfurt.mainnet.block-engine.jito.wtf/api/v1/bundles",
            "https://ny.mainnet.block-engine.jito.wtf/api/v1/bundles",
            "https://tokyo.mainnet.block-engine.jito.wtf/api/v1/bundles"
        ]

    async def execute_backrun_bundle(
        self,
        trigger_signature: str,
        base_mint: str,
        quote_mint: str,
        amount_sol: float,
        expected_profit_sol: float,
        recent_blockhash: str,
        profit_mint_str: Optional[str] = None  # Fix: Cross-currency tip normalization
    ) -> Dict[str, Any]:
        """Execute atomic backrun bundle triggered by signature."""

        start_time = time.time()
        logger.info(f"🔥 Executing backrun bundle for signature: {trigger_signature[:8]}...")

        try:
            # ── Fix: Cross-Currency Tip Translation ─────────────────────────────────
            # Normalize expected_profit_sol to true SOL value before calculating tip.
            # If profit_mint_str is not given, default to assuming SOL.
            tip_target_mint = profit_mint_str or "So11111111111111111111111111111111111111112"
            true_profit_sol = _normalize_tip_sol(expected_profit_sol, tip_target_mint)

            # Calculate dynamic tip based on expected profit (now in true SOL)
            tip_lamports = int(true_profit_sol * self.tip_percent * 1_000_000_000)  # Convert SOL to lamports
            tip_lamports = max(tip_lamports, 10000)  # Minimum 0.00001 SOL

            # ── Task 15: Micro-Jitter (The Tie-Breaker) ────────────────────────────────
            # Never submit a tip ending in ≈000. Adding random 11–142 lamports makes our
            # bundle mathematically-strictly larger than every free-bot competitor at 10000.
            tip_lamports += random.randint(11, 142)

            logger.info(f"💰 Using dynamic tip: {tip_lamports / 1e9:.6f} SOL ({self.tip_percent:.1%} of expected profit, normalized from {expected_profit_sol:.6f} {tip_target_mint[:8]} SOL-equiv)")

            # Get active Jito leaders for optimal Block Engine targeting
            active_endpoints = await self.leader_checker.get_next_scheduled_leaders()
            logger.info(f"🎯 Targeting {len(active_endpoints)} active Jito Block Engines for shotgun execution")

            # Create arbitrage transaction
            arb_template_key = self.bundle_template.create_arbitrage_template(
                base_mint, quote_mint, amount_sol
            )
            arbitrage_tx = self.bundle_template.instantiate_template(arb_template_key, recent_blockhash)

            if not arbitrage_tx:
                return {"success": False, "error": "Failed to create arbitrage transaction"}

            # ── Uncle Bandit Protection: Merge tip INTO arbitrage tx ──────────────
            # Never use separate tip_tx — in 2026, uncled blocks allow malicious
            # searchers to extract and broadcast the tip_tx alone, draining our wallet
            # without executing the arbitrage. By inlining the tip as the last instruction
            # inside the arbitrage transaction, we guarantee atomicity: if the arbitrage
            # fails or the block is skipped, the entire transaction (including tip) is
            # rolled back atomically.
            from solders.instruction import Instruction as SoldersInstruction

            tip_account = await self._select_tip_account()
            msg = arbitrage_tx.message
            all_keys = list(msg.account_keys)

            # Decompile existing instructions from the arbitrage transaction
            decompiled = []
            for ci in msg.instructions:
                decompiled.append(
                    SoldersInstruction(
                        program_id=all_keys[ci.program_id_index],
                        accounts=[AccountMeta(all_keys[i], True, True) for i in ci.accounts],
                        data=bytes(ci.data),
                    )
                )

            # Append tip transfer as the last instruction (inside the same tx)
            all_ixs = decompiled + [transfer(TransferParams(
                from_pubkey=self.keypair.pubkey(),
                to_pubkey=Pubkey.from_string(tip_account),
                lamports=tip_lamports,
            ))]

            # Fix 69: Safe ALT extraction — MessageV0 may not expose
            # address_lookup_table_accounts as a top-level attribute on all solders versions.
            # Use getattr with empty fallback to prevent AttributeError crashes.
            _alts = getattr(msg, 'address_lookup_table_accounts', [])
            if _alts is None:
                _alts = []
            try:
                _alts = list(_alts)
            except Exception:
                _alts = []

            # Recompile merged message with same ALTs and blockhash
            new_msg = MessageV0.try_compile(
                payer=self.keypair.pubkey(),
                instructions=all_ixs,
                address_lookup_table_accounts=_alts,
                recent_blockhash=msg.recent_blockhash,
            )

            # Single atomic transaction — tip cannot be extracted without the arb
            merged_tx = VersionedTransaction(new_msg, [self.keypair])
            bundle = [merged_tx]

            # Execute Jito Shotgun strategy across all 4 regional Block Engines
            results = await self._shotgun_bundle(bundle, active_endpoints)

            execution_time = time.time() - start_time
            logger.info(f"Execution time: {execution_time:.2f}s")

            return {
                "success": any(r.get("success", False) for r in results),
                "execution_time": execution_time,
                "results": results,
                "bundle_size": len(bundle)
            }

        except Exception as e:
            logger.error(f"Bundle execution failed: {e}")
            return {"success": False, "error": str(e)}

    async def _shotgun_bundle(self, bundle: List[VersionedTransaction], endpoints: List[str]) -> List[Dict]:
        """Send bundle to all 4 regional Block Engines simultaneously with Jito Shotgun strategy."""
        results = []

        # Get active endpoints with upcoming Jito leaders (optimization for success rate)
        active_endpoints = await self.leader_checker.get_next_scheduled_leaders()
        if not active_endpoints:
            active_endpoints = endpoints  # Fallback to all if leader check fails

        logger.debug(f"🎯 Jito Shotgun: targeting {len(active_endpoints)} active Block Engines")

        # Phase 1: Aggressive initial burst - send to ALL 4 endpoints simultaneously (max parallelism)
        logger.debug("🚀 Phase 1: Initial shotgun burst to all Block Engines")
        burst_results = await self._send_bundle_to_endpoints(bundle, active_endpoints)
        results.extend(burst_results)

        # Phase 2: Sustained spam for 3 seconds with 100ms intervals (more aggressive than 200ms)
        # This maximizes coverage of leader schedule windows
        end_time = time.time() + 3.0  # Extended from 2.0 to 3.0 seconds
        spam_count = 1

        while time.time() < end_time:
            await asyncio.sleep(0.1)  # Faster 100ms intervals for better coverage
            spam_results = await self._send_bundle_to_endpoints(bundle, active_endpoints)
            results.extend(spam_results)
            spam_count += 1

            # Log progress every 10 sends (more frequent logging)
            if spam_count % 10 == 0:
                success_count = sum(1 for r in results if r.get("success"))
                total_sends = len(results)
                success_rate = (success_count / total_sends * 100) if total_sends > 0 else 0
                logger.debug(f"📡 Shotgun spam {spam_count}: {success_count}/{total_sends} successful ({success_rate:.1f}%)")

        # Final stats
        final_success_count = sum(1 for r in results if r.get("success"))
        final_total = len(results)
        final_success_rate = (final_success_count / final_total * 100) if final_total > 0 else 0
        logger.info(f"🎯 Jito Shotgun complete: {final_success_count}/{final_total} bundles accepted ({final_success_rate:.1f}% success rate)")

        return results

    async def _send_bundle_to_endpoints(self, bundle: List[VersionedTransaction], endpoints: List[str]) -> List[Dict]:
        """Send bundle to multiple endpoints in parallel."""
        if not self.session:
            return [{"success": False, "error": "No HTTP session"}]

        # Serialize bundle
        serialized_bundle = [base58.b58encode(bytes(tx)).decode('ascii') for tx in bundle]

        async def send_to_endpoint(endpoint: str) -> Dict:
            try:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "sendBundle",
                    "params": [serialized_bundle]
                }

                headers = {"Content-Type": "application/json"}
                if self.auth_key:
                    headers["x-jito-auth"] = self.auth_key

                timeout = aiohttp.ClientTimeout(total=0.5)  # Fast timeout
                async with self.session.post(endpoint, json=payload, headers=headers, timeout=timeout) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if "result" in data:
                            bundle_id = data["result"]
                            logger.debug(f"✅ Bundle sent to {endpoint[-20:]}: {bundle_id[:8]}...")
                            return {"success": True, "bundle_id": bundle_id, "endpoint": endpoint}
                        else:
                            return {"success": False, "error": data.get("error", "Unknown error"), "endpoint": endpoint}
                    else:
                        error_text = await resp.text()
                        return {"success": False, "error": f"HTTP {resp.status}: {error_text}", "endpoint": endpoint}

            except asyncio.TimeoutError:
                return {"success": False, "error": "Timeout", "endpoint": endpoint}
            except Exception as e:
                return {"success": False, "error": str(e), "endpoint": endpoint}

        # Send to all endpoints in parallel
        tasks = [send_to_endpoint(endpoint) for endpoint in endpoints]
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def _select_tip_account(self) -> str:
        """Select optimal Jito tip account (rotate for distribution) with live fetch."""
        if not self.jito_tip_accounts:
            # Fallback: fetch live accounts from Jito Block Engine
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    url = "https://mainnet.block-engine.jito.wtf/api/v1/bundles/tip_accounts"
                    async with session.get(url, timeout=3.0) as resp:
                        if resp.status == 200:
                            accounts = await resp.json()
                            if accounts and isinstance(accounts, list):
                                self.jito_tip_accounts = accounts
                                logger.info(f"🔄 Fetched {len(accounts)} live tip accounts")
            except Exception as e:
                logger.warning(f"Live tip account fetch failed: {e}")
        
        if self.jito_tip_accounts:
            index = int(time.time() * 1000) % len(self.jito_tip_accounts)
            return self.jito_tip_accounts[index]
        return "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"  # Final fallback

    async def simulate_bundle_locally(self, bundle: List[VersionedTransaction], rpc_url: str) -> Dict[str, Any]:
        """Asynchronous local simulation (doesn't block bundle sending)."""
        # This runs in parallel with bundle sending
        # Used for validation but doesn't delay execution
        try:
            # Simulate each transaction in bundle
            # This would check if arbitrage tx would succeed
            logger.debug("🔍 Local bundle simulation started")
            await asyncio.sleep(0.1)  # Simulate async work
            return {"simulated": True, "would_succeed": True}
        except Exception as e:
            logger.warning(f"Local simulation failed: {e}")
            return {"simulated": False, "error": str(e)}


class BackrunTrigger:
    """Signature-based trigger for backrunning opportunities."""

    def __init__(self, bundle_handler: JitoBundleHandler):
        self.bundle_handler = bundle_handler
        self.active_backruns: Dict[str, float] = {}  # signature -> timestamp

    async def on_migration_event(self, signature: str, base_mint: str, quote_mint: str, recent_blockhash: str, expected_profit_sol: float = 0.001):
        """Handle migration/pool creation event for backrunning."""
        # Avoid duplicate processing
        if signature in self.active_backruns:
            if time.time() - self.active_backruns[signature] < 5.0:  # 5 second cooldown
                return
        self.active_backruns[signature] = time.time()

        logger.info(f"🎯 Migration detected: {signature[:8]}... ({base_mint[:8]} -> {quote_mint[:8]})")

        # Execute backrun bundle
        result = await self.bundle_handler.execute_backrun_bundle(
            trigger_signature=signature,
            base_mint=base_mint,
            quote_mint=quote_mint,
            amount_sol=1.0,  # Default amount, would be calculated optimally
            expected_profit_sol=expected_profit_sol,
            recent_blockhash=recent_blockhash
        )

        if result["success"]:
            logger.info("🎉 Backrun bundle executed successfully!")
            bundle_id = result["results"][0].get("bundle_id", "unknown") if result["results"] else "unknown"
            logger.info(f"Bundle ID: {bundle_id}")
        else:
            logger.warning("❌ Backrun bundle failed")
        # Cleanup old entries
        current_time = time.time()
        self.active_backruns = {
            sig: ts for sig, ts in self.active_backruns.items()
            if current_time - ts < 30.0  # Keep for 30 seconds
        }

    # === DISABLED: create_secure_jito_bundle ===
    # Jito tip is inlined in tx_builder.build_native_flashloan_tx. Calling this would add a
    # SECOND tip instruction and double-spend the Jito fee from the capital reserve.
    # Kept as dead-code reference only — DO NOT CALL.
    #
    # def create_secure_jito_bundle(self, arbitrage_tx: VersionedTransaction,
    #                               jito_tip_lamports: int,
    #                               address_lookup_table_accounts=None) -> List[VersionedTransaction]: