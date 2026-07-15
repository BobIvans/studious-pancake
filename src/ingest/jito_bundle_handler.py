"""Jito Bundle Handler for Atomic Backrunning & MEV Execution."""

import src.ingest.shared_state as shared_state
from solders.instruction import AccountMeta
from solders.address_lookup_table_account import AddressLookupTableAccount
from solders.system_program import transfer, TransferParams
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.hash import Hash
from solders.message import MessageV0
from solders.transaction import VersionedTransaction
import asyncio
import orjson
import base58
import logging
import time
import random
import os
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


def _normalize_tip_sol(
        expected_profit_sol: float,
        target_mint_str: str) -> float:
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


logger = logging.getLogger(__name__)


class JitoLeaderChecker:
    """Check upcoming Jito leaders for bundle optimization."""

    def __init__(self, session: Optional[aiohttp.ClientSession] = None):
        self.session = session
        self.jito_endpoints = [
            "https://amsterdam.mainnet.block-engine.jito.wtf/api/v1/bundles",
            "https://frankfurt.mainnet.block-engine.jito.wtf/api/v1/bundles",
            "https://ny.mainnet.block-engine.jito.wtf/api/v1/bundles",
            "https://tokyo.mainnet.block-engine.jito.wtf/api/v1/bundles",
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
                logger.debug(
                    "Fix 75: Created ad-hoc aiohttp session for JitoLeaderChecker"
                )
            except Exception:
                return self.jito_endpoints  # Fallback to all

        current_time = time.time()
        # Check cache
        ttl = self.leader_cache.get(
            "ttl_override",
            self.cache_ttl) if self.leader_cache else self.cache_ttl
        if (
            self.leader_cache
            and current_time - self.leader_cache.get("timestamp", 0) < ttl
        ):
            leaders = self.leader_cache.get("leaders", self.jito_endpoints)
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
                    "method": "getSlotLeaders",
                    "params": [current_slot, 100]
                }
                # Запрос отправляется на self.rpc_url основной ноды, а не на
                # Jito Block Engine URL

                timeout = aiohttp.ClientTimeout(total=0.5)
                async with _session.post(
                    endpoint, json=payload, timeout=timeout
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if "result" in data and data["result"]:
                            active_endpoints.append(endpoint)

            except Exception as e:
                logger.debug(f"Leader check failed for {endpoint}: {e}")

        # Cache results (FIX 169: Use short TTL on failure to recover
        # instantly)
        self.leader_cache = {
            "leaders": active_endpoints if active_endpoints else self.jito_endpoints,
            "timestamp": current_time,
            "ttl_override": 0.1 if not active_endpoints else self.cache_ttl}

        if _session_owned:
            await _session.close()
        return self.leader_cache["leaders"]


class BundleTemplate:
    """Pre-signed transaction template for instant bundle creation."""

    def __init__(self,
                 keypair: Keypair,
                 jito_tip_accounts: Optional[List[str]] = None,
                 tx_builder: Optional[Any] = None):
        self.keypair = keypair
        self.templates: Dict[str, Dict] = {}
        self.jito_tip_accounts = jito_tip_accounts or []
        self.tx_builder = tx_builder

    def create_arbitrage_template(
        self, base_mint: str, quote_mint: str, amount_sol: float
    ) -> str:
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

    def create_tip_template(
        self, tip_amount_lamports: int, jito_account: str
    ) -> VersionedTransaction:
        """Create pre-signed tip transaction."""
        tip_ix = transfer(
            TransferParams(
                from_pubkey=self.keypair.pubkey(),
                to_pubkey=Pubkey.from_string(jito_account),
                lamports=tip_amount_lamports,
            )
        )

        # Create minimal message for tip
        from solders.message import MessageV0
        from solders.hash import Hash

        msg = MessageV0.try_compile(
            payer=self.keypair.pubkey(),
            instructions=[tip_ix],
            address_lookup_table_accounts=[],
            recent_blockhash=Hash.default(),  # Placeholder, will be updated
        )

        return VersionedTransaction(msg, [self.keypair])

    def _select_tip_account_sync(self) -> str:
        """Synchronous tip account selection for instantiate_template (thread-safe copy-on-read)."""
        accounts_snapshot = list(self.jito_tip_accounts)
        if accounts_snapshot:
            index = int(time.time() * 1000) % len(accounts_snapshot)
            return accounts_snapshot[index]
        logger.warning(
            "JITO TIP ACCOUNTS: using local test fallback account after dynamic fetch failed.")
        return str(self.keypair.pubkey())

    async def instantiate_template(
        self,
        template_key: str,
        recent_blockhash: str,
        arbitrage_path: List[str],
        borrow_amount_lamports: int,
        expected_min_profit_lamports: int,
        dex_swap_instructions: List[Any],
        marginfi_config: Dict[str, Any],
    ) -> Optional[VersionedTransaction]:
        """Compile and sign a transaction template into a ready-to-send VersionedTransaction."""
        if not self.tx_builder:
            return None

        try:
            tx_data = await self.tx_builder.build_native_flashloan_tx(
                wallet_pubkey=str(self.keypair.pubkey()),
                arbitrage_path=arbitrage_path,
                borrow_amount_lamports=borrow_amount_lamports,
                expected_min_profit_lamports=expected_min_profit_lamports,
                dex_swap_instructions=dex_swap_instructions,
                marginfi_config=marginfi_config,
                jito_tip_lamports=0,
                wsol_manager=None,
                pool_state_manager=None,
                use_jito=True,
            )

            if not tx_data:
                return None

            instructions = tx_data["instructions"]
            alt_keys = tx_data.get("address_lookup_table_pubkeys", [])

            alts = []
            if shared_state.alt_manager:
                for alt_str in alt_keys:
                    resolved = await shared_state.alt_manager.resolve_alt(Pubkey.from_string(alt_str))
                    if resolved:
                        alts.append(
                            AddressLookupTableAccount(
                                key=Pubkey.from_string(alt_str),
                                addresses=resolved))

            msg = MessageV0.try_compile(
                payer=self.keypair.pubkey(),
                instructions=instructions,
                address_lookup_table_accounts=alts,
                recent_blockhash=Hash.from_string(recent_blockhash),
            )

            return VersionedTransaction(msg, [self.keypair])
        except Exception as e:
            logger.error(f"Template instantiation failed: {e}")
            return None


class JitoBundleHandler:
    """Atomic backrunning with Jito bundles for MEV execution."""

    def __init__(
        self,
        keypair: Keypair,
        session: Optional[aiohttp.ClientSession] = None,
        jito_endpoints: Optional[List[str]] = None,
        auth_key: Optional[str] = None,
        tip_percent: float = 0.6,
        tx_builder: Optional[Any] = None,
    ):
        self.keypair = keypair
        self.session = session
        self.auth_key = auth_key
        self.tip_percent = tip_percent
        self.tx_builder = tx_builder
        self.jito_tip_accounts = []
        self.bundle_template = BundleTemplate(
            keypair,
            jito_tip_accounts=self.jito_tip_accounts,
            tx_builder=tx_builder)
        self.leader_checker = JitoLeaderChecker(session)

        # Default Jito endpoints if not provided
        self.jito_endpoints = jito_endpoints or [
            "https://amsterdam.mainnet.block-engine.jito.wtf/api/v1/bundles",
            "https://frankfurt.mainnet.block-engine.jito.wtf/api/v1/bundles",
            "https://ny.mainnet.block-engine.jito.wtf/api/v1/bundles",
            "https://tokyo.mainnet.block-engine.jito.wtf/api/v1/bundles",
        ]

    async def _get_jupiter_quote(
        self, input_mint: str, output_mint: str, amount: int
    ) -> Optional[Dict]:
        url = os.getenv(
            "JUPITER_QUOTE_API", "https://api.jup.ag/swap/v2/quote"
        )
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(int(amount)),
            "slippageBps": "5",
            "onlyDirectRoutes": "false",
            "restrictIntermediateTokens": "false",
        }
        try:
            timeout = aiohttp.ClientTimeout(total=5.0)
            if self.session and not self.session.closed:
                async with self.session.get(
                    url, params=params, timeout=timeout
                ) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.json()
            else:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url, params=params, timeout=timeout
                    ) as resp:
                        if resp.status != 200:
                            return None
                        return await resp.json()
        except Exception as e:
            logger.debug(f"Jupiter quote failed: {e}")
            return None

    async def execute_backrun_bundle(
        self,
        trigger_signature: str,
        base_mint: str,
        quote_mint: str,
        amount_sol: float,
        expected_profit_sol: float,
        recent_blockhash: str,
        # Fix: Cross-currency tip normalization
        profit_mint_str: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute atomic backrun bundle triggered by signature."""

        start_time = time.time()
        logger.info(
            f"🔥 Executing backrun bundle for signature: {trigger_signature[:8]}..."
        )

        try:
            # ── Fix: Cross-Currency Tip Translation ──────────────────────────
            # Normalize expected_profit_sol to true SOL value before calculating tip.
            # If profit_mint_str is not given, default to assuming SOL.
            tip_target_mint = (
                profit_mint_str or "So11111111111111111111111111111111111111112")
            true_profit_sol = _normalize_tip_sol(
                expected_profit_sol, tip_target_mint)

            # Calculate dynamic tip based on expected profit (now in true SOL)
            tip_lamports = int(
                true_profit_sol * self.tip_percent * 1_000_000_000
            )  # Convert SOL to lamports
            tip_lamports = max(tip_lamports, 10000)  # Minimum 0.00001 SOL

            # ── Task 15: Micro-Jitter (The Tie-Breaker) ──────────────────────
            # FIXED: Расширен диапазон до +500..1500 для защиты от перебивания
            # ботами-конкурентами
            tip_lamports += random.randint(500, 1500)

            logger.info(
                f"💰 Using dynamic tip: {
                    tip_lamports /
                    1e9:.6f} SOL ({
                    self.tip_percent:.1%} of expected profit, normalized from {
                    expected_profit_sol:.6f} {
                    tip_target_mint[
                        :8]} SOL-equiv)")

            # Get active Jito leaders for optimal Block Engine targeting
            active_endpoints = await self.leader_checker.get_next_scheduled_leaders()
            logger.info(
                f"🎯 Targeting {
                    len(active_endpoints)} active Jito Block Engines for shotgun execution")

            # Build Jupiter swap instructions for the arbitrage path
            swap_ixs = []
            if self.tx_builder and self.session:
                amount_lamports = int(amount_sol * 1e9)
                leg1_quote = await self._get_jupiter_quote(
                    base_mint, quote_mint, amount_lamports
                )
                if leg1_quote:
                    leg1_out = int(leg1_quote.get("outAmount", 0))
                    if leg1_out > 0:
                        leg2_quote = await self._get_jupiter_quote(
                            quote_mint, base_mint, leg1_out
                        )
                        if leg2_quote:
                            for leg_quote in [leg1_quote, leg2_quote]:
                                ixs, _ = await self.tx_builder.get_swap_instructions(
                                    leg_quote, str(self.keypair.pubkey()), use_custom_cu=True
                                )
                                swap_ixs.extend(ixs)

            # Create arbitrage transaction
            arb_template_key = self.bundle_template.create_arbitrage_template(
                base_mint, quote_mint, amount_sol
            )
            # Resolve real MarginFi bank accounts for the base mint.
            # This avoids the stale "..." authority placeholder that crashes
            # MessageV0.try_compile with an invalid public key.
            _marginfi_bank_cfg = None
            try:
                if base_mint in shared_state.MARGINFI_BANKS:
                    _raw_bank_cfg = shared_state.MARGINFI_BANKS[base_mint]
                    if isinstance(_raw_bank_cfg, dict) and _raw_bank_cfg.get(
                            "liquidity_vault_authority"):
                        _marginfi_bank_cfg = _raw_bank_cfg
            except Exception as _bank_err:
                logger.debug(
                    f"Marginfi bank account lookup failed (non-fatal): {_bank_err}")

            if _marginfi_bank_cfg:
                _mfi_program_id = "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"
                _mfi_account = os.getenv("MARGINFI_ACCOUNT")
                if not _mfi_account:
                    logger.error(
                        "MARGINFI_ACCOUNT env var missing, cannot build backrun bundle.")
                    return {
                        "success": False,
                        "error": "Missing MarginFi Account"}
                _mfi_vault = str(
                    _marginfi_bank_cfg.get(
                        "liquidity_vault",
                        Pubkey.from_string("CCwqExrqLGHtq12X182rFvA4KEDtK13q2E7B3Jp2Cxyj")))
                _mfi_vault_auth = str(
                    _marginfi_bank_cfg["liquidity_vault_authority"])
                _marginfi_config = {
                    "program_id": _mfi_program_id,
                    "marginfi_account": _mfi_account,
                    "bank_liquidity_vault": _mfi_vault,
                    "bank_liquidity_vault_authority": _mfi_vault_auth,
                }
            else:
                _marginfi_config = {
                    "program_id": "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA",
                    "marginfi_account": "Fk4G5NB5e1NyULQCCpTNLWCmChCW2UbDwpkEofqAiHk2",
                    "bank_liquidity_vault": "2s37akK2eyBbp8DZgCm7RtsaEz8eWhVKGfHGA3cKMEW2",
                    "bank_liquidity_vault_authority": "",
                }

            arbitrage_tx = await self.bundle_template.instantiate_template(
                arb_template_key,
                recent_blockhash,
                arbitrage_path=[base_mint, quote_mint, base_mint],
                borrow_amount_lamports=int(amount_sol * 1_000_000_000),
                expected_min_profit_lamports=int(expected_profit_sol * 1_000_000_000),
                dex_swap_instructions=swap_ixs,
                marginfi_config=_marginfi_config,
            )

            if not arbitrage_tx:
                return {
                    "success": False,
                    "error": "Failed to create arbitrage transaction",
                }

            # ── Uncle Bandit Protection: Merge tip INTO arbitrage tx ─────────
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
                        accounts=[
                            AccountMeta(all_keys[i], True, True) for i in ci.accounts
                        ],
                        data=bytes(ci.data),
                    )
                )

            # Append tip transfer as the last instruction (inside the same tx)
            all_ixs = decompiled + [
                transfer(
                    TransferParams(
                        from_pubkey=self.keypair.pubkey(),
                        to_pubkey=Pubkey.from_string(tip_account),
                        lamports=tip_lamports,
                    )
                )
            ]

            # Fix 69: Safe ALT extraction — MessageV0 may not expose
            # address_lookup_table_accounts as a top-level attribute on all solders versions.
            # Use getattr with empty fallback to prevent AttributeError
            # crashes.
            _alts = getattr(msg, "address_lookup_table_accounts", [])
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

            # Single atomic transaction — tip cannot be extracted without the
            # arb
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
                "bundle_size": len(bundle),
            }

        except Exception as e:
            logger.error(f"Bundle execution failed: {e}")
            return {"success": False, "error": str(e)}

    async def _shotgun_bundle(
        self, bundle: List[VersionedTransaction], endpoints: List[str]
    ) -> List[Dict]:
        """Send bundle to all 4 regional Block Engines simultaneously with Jito Shotgun strategy."""
        results = []

        # Get active endpoints with upcoming Jito leaders (optimization for
        # success rate)
        active_endpoints = await self.leader_checker.get_next_scheduled_leaders()
        if not active_endpoints:
            active_endpoints = endpoints  # Fallback to all if leader check fails

        logger.debug(
            f"🎯 Jito Shotgun: targeting {
                len(active_endpoints)} active Block Engines")

        # Phase 1: Aggressive initial burst - send to ALL 4 endpoints
        # simultaneously (max parallelism)
        logger.debug("🚀 Phase 1: Initial shotgun burst to all Block Engines")
        burst_results = await self._send_bundle_to_endpoints(bundle, active_endpoints)
        results.extend(burst_results)

        # Phase 2: Sustained spam for 3 seconds with 100ms intervals (more aggressive than 200ms)
        # This maximizes coverage of leader schedule windows
        end_time = time.time() + 3.0  # Extended from 2.0 to 3.0 seconds
        spam_count = 1

        while time.time() < end_time:
            # Faster 100ms intervals for better coverage
            await asyncio.sleep(0.1)
            spam_results = await self._send_bundle_to_endpoints(
                bundle, active_endpoints
            )
            results.extend(spam_results)
            spam_count += 1

            # Log progress every 10 sends (more frequent logging)
            if spam_count % 10 == 0:
                success_count = sum(1 for r in results if r.get("success"))
                total_sends = len(results)
                success_rate = (
                    (success_count / total_sends * 100) if total_sends > 0 else 0)
                logger.debug(
                    f"📡 Shotgun spam {spam_count}: {success_count}/{total_sends} successful ({success_rate:.1f}%)"
                )

        # Final stats
        final_success_count = sum(1 for r in results if r.get("success"))
        final_total = len(results)
        final_success_rate = (
            (final_success_count / final_total * 100) if final_total > 0 else 0
        )
        logger.info(
            f"🎯 Jito Shotgun complete: {final_success_count}/{final_total} bundles accepted ({
                final_success_rate:.1f}% success rate)")

        return results

    async def _send_bundle_to_endpoints(
        self, bundle: List[VersionedTransaction], endpoints: List[str]
    ) -> List[Dict]:
        """Send bundle to multiple endpoints in parallel."""
        if not self.session:
            return [{"success": False, "error": "No HTTP session"}]

        # Serialize bundle
        serialized_bundle = [
            base58.b58encode(bytes(tx)).decode("ascii") for tx in bundle
        ]

        async def send_to_endpoint(endpoint: str) -> Dict:
            try:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "sendBundle",
                    "params": [serialized_bundle],
                }

                headers = {"Content-Type": "application/json"}
                if self.auth_key:
                    headers["x-jito-auth"] = self.auth_key

                timeout = aiohttp.ClientTimeout(total=0.5)  # Fast timeout
                async with self.session.post(
                    endpoint, json=payload, headers=headers, timeout=timeout
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if "result" in data:
                            bundle_id = data["result"]
                            logger.debug(
                                f"✅ Bundle sent to {endpoint[-20:]}: {bundle_id[:8]}..."
                            )
                            return {
                                "success": True,
                                "bundle_id": bundle_id,
                                "endpoint": endpoint,
                            }
                        else:
                            return {
                                "success": False,
                                "error": data.get("error", "Unknown error"),
                                "endpoint": endpoint,
                            }
                    else:
                        error_text = await resp.text()
                        return {
                            "success": False,
                            "error": f"HTTP {resp.status}: {error_text}",
                            "endpoint": endpoint,
                        }

            except asyncio.TimeoutError:
                return {
                    "success": False,
                    "error": "Timeout",
                    "endpoint": endpoint}
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "endpoint": endpoint}

        # Send to all endpoints in parallel
        tasks = [send_to_endpoint(endpoint) for endpoint in endpoints]
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def _select_tip_account(self) -> str:
        """Select optimal Jito tip account (rotate for distribution) with live fetch and thread-safe copy-on-read."""
        # Сначала проверяем кэш; если пуст — запрашиваем актуальные адреса у
        # Block Engine
        if not self.jito_tip_accounts:
            try:
                import aiohttp

                async with aiohttp.ClientSession() as session:
                    url = "https://mainnet.block-engine.jito.wtf/api/v1/bundles/tip_accounts"
                    async with session.get(url, timeout=3.0) as resp:
                        if resp.status == 200:
                            accounts_data = await resp.json()
                            accounts = []
                            if isinstance(accounts_data, list):
                                accounts = accounts_data
                            elif isinstance(accounts_data, dict):
                                if "value" in accounts_data:
                                    accounts = accounts_data["value"]
                                elif "result" in accounts_data:
                                    accounts = accounts_data["result"]
                                    if isinstance(
                                            accounts, dict) and "value" in accounts:
                                        accounts = accounts["value"]

                            if accounts and isinstance(accounts, list):
                                self.jito_tip_accounts = accounts
                                logger.info(
                                    f"🔄 {
                                        self.__class__.__name__}: Fetched {
                                        len(accounts)} live tip accounts")
            except Exception as e:
                logger.warning(f"Live tip account fetch failed: {e}")

        # Обновляем снимок коллекции ПОСЛЕ возможного сетевого запроса
        accounts_snapshot = list(self.jito_tip_accounts)
        if accounts_snapshot:
            index = int(time.time() * 1000) % len(accounts_snapshot)
            return accounts_snapshot[index]

        logger.warning(
            "JITO TIP ACCOUNTS: using local test fallback account after dynamic fetch failed.")
        return str(self.keypair.pubkey())

    # simulate_bundle_locally REMOVED: was a stub returning {"simulated": True} after asyncio.sleep(0.1).
    # Real simulation requires full SVM execution which is not implemented
    # here.


class BackrunTrigger:
    """Signature-based trigger for backrunning opportunities."""

    def __init__(self, bundle_handler: JitoBundleHandler):
        self.bundle_handler = bundle_handler
        self.active_backruns: Dict[str, float] = {}  # signature -> timestamp

    async def on_migration_event(
        self,
        signature: str,
        base_mint: str,
        quote_mint: str,
        recent_blockhash: str,
        expected_profit_sol: float = 0.001,
    ):
        """Handle migration/pool creation event for backrunning."""
        # Avoid duplicate processing
        if signature in self.active_backruns:
            if time.time() - \
                    self.active_backruns[signature] < 5.0:  # 5 second cooldown
                return
        self.active_backruns[signature] = time.time()

        logger.info(
            f"🎯 Migration detected: {signature[:8]}... ({base_mint[:8]} -> {quote_mint[:8]})"
        )

        # Execute backrun bundle
        result = await self.bundle_handler.execute_backrun_bundle(
            trigger_signature=signature,
            base_mint=base_mint,
            quote_mint=quote_mint,
            amount_sol=1.0,  # Default amount, would be calculated optimally
            expected_profit_sol=expected_profit_sol,
            recent_blockhash=recent_blockhash,
        )

        if result["success"]:
            logger.info("🎉 Backrun bundle executed successfully!")
            bundle_id = (
                result["results"][0].get("bundle_id", "unknown")
                if result["results"]
                else "unknown"
            )
            logger.info(f"Bundle ID: {bundle_id}")
        else:
            logger.warning("❌ Backrun bundle failed")
        # Cleanup old entries
        current_time = time.time()
        self.active_backruns = {
            sig: ts
            for sig, ts in self.active_backruns.items()
            if current_time - ts < 30.0  # Keep for 30 seconds
        }

    # === DISABLED: create_secure_jito_bundle ===
    # Jito tip is inlined in tx_builder.build_native_flashloan_tx. Calling this would add a
    # SECOND tip instruction and double-spend the Jito fee from the capital reserve.
    # Kept as dead-code reference only — DO NOT CALL.
    #
    # def create_secure_jito_bundle(self, arbitrage_tx: VersionedTransaction,
    #                               jito_tip_lamports: int,
    # address_lookup_table_accounts=None) -> List[VersionedTransaction]:
