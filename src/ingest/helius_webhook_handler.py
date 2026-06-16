"""Helius Webhook Handler for Sanctum LST Arbitrage Opportunities."""

import os
import hmac
import orjson
import logging
import asyncio
import time
from collections import deque
from typing import Dict, Any, List, Optional
from datetime import datetime
from aiohttp import web
import aiohttp

from .data_aggregator import DataAggregator
from .webhook_config import WebhookConfig
logger = logging.getLogger(__name__)

class HeliusWebhookHandler:
    """Handles incoming Helius webhooks for LST arbitrage detection."""

    def __init__(self, data_aggregator: DataAggregator, port: int = 8080, opportunity_callback=None, webhook_queue=None, on_token_discovery=None, jito_shotgun=None):
        self.data_aggregator = data_aggregator
        self.port = port
        self.opportunity_callback = opportunity_callback  # Callback to process opportunities
        self.webhook_queue = webhook_queue  # AsyncQueue for webhook signals
        self.on_token_discovery = on_token_discovery # Callback for dynamic registry
        self.processed_signatures = {}  # Cache of processed signatures for deduplication
        self.jito_shotgun = jito_shotgun  # Strat 3: Jito Shotgun — all-region broadcast on webhook signal
        self.app = web.Application()
        self.app.router.add_post('/webhook', self.handle_webhook)
        self.app.router.add_get('/', self.handle_health)
        self.app.router.add_get('/health', self.handle_health)
        self.runner = None
        # ── Event Loop Anti-Starvation: LIFO signal queue ────────────────────────
        # Latest signals are processed first. Signals older than 800ms are dropped.
        # FIX 14 (OOM Prevention): maxlen=100 ensures the deque never grows unbounded
        # during high-volatility events, preventing server OOM crashes.
        self._signal_deque: deque = deque(maxlen=100)
        self.EVENT_DROP_MS = 800
        self._event_counter = 0  # counts processed events for async.yield every 3
        self._consumer_task: Optional[asyncio.Task] = None  # Fix 55: background consumer

    async def _check_port_available(self) -> bool:
        """Check if the webhook port is available before starting the server."""
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('0.0.0.0', self.port))
                s.close()
            return True
        except OSError:
            return False

    async def start(self):
        """Start the webhook server and the background signal consumer."""
        # Check port availability before attempting to start
        if not await self._check_port_available():
            logger.warning(f"⚠️ Port {self.port} already in use. Webhook server disabled for this session.")
            logger.info("💡 Tip: Stop other instances of the bot before starting a new one.")
            return

        try:
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            site = web.TCPSite(runner=self.runner, port=self.port)
            await site.start()
            logger.info(f"🚀 Helius webhook server started on port {self.port}")
            # Fix 55: Start background consumer to drain signal deque into _process_event
            self._consumer_task = asyncio.create_task(self._consume_signals())
            logger.info("🔄 Webhook signal consumer started (Fix 55)")
        except OSError as e:
            if "Address already in use" in str(e):
                logger.warning(f"⚠️ Port {self.port} already in use. Webhook server disabled for this session.")
                logger.info("💡 Tip: Stop other instances of the bot before starting a new one.")
                # Don't raise - allow bot to continue without webhooks
                return
            else:
                raise  # Re-raise other OSError types

    async def stop(self):
        """Stop the webhook server and background consumer."""
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None
        if self.runner:
            await self.runner.cleanup()
            logger.info("🛑 Helius webhook server stopped")

    async def handle_health(self, request):
        """Handle healthcheck requests from Cloudflare or monitoring tools."""
        return web.json_response({"status": "alive", "timestamp": datetime.now().isoformat()})

    async def handle_webhook(self, request):
        """Handle incoming webhook from Helius."""
        # ── Fix 2: Flexible Helius Authorization ───────────────────────────────
        # Helius Dashboard may send Authorization, while manual/webhook-ID callbacks
        # can arrive with ?api-key=... or as trusted configured webhook IDs.
        raw_bytes = await request.read()
        try:
            data = orjson.loads(raw_bytes) if raw_bytes else []
        except Exception:
            logger.error("Invalid Helius webhook JSON payload")
            return web.Response(status=400, text='Bad JSON')

        # Fix 58: Helius sends a list of events. Fallback to extracting from dict if format changes.
        if isinstance(data, list):
            events = data
            data_dict = {}
        elif isinstance(data, dict):
            events = data.get('events', [data])
            data_dict = data
        else:
            events = []
            data_dict = {}

        query_webhook_id = request.query.get('webhookId') or request.query.get('webhook_id')
        webhook_id = data_dict.get('webhookId') or query_webhook_id or 'unknown'
        auth_header = request.headers.get('Authorization', '')
        auth_query = request.query.get('api-key') or request.query.get('api_key') or ''
        expected_auth = os.getenv("HELIUS_WEBHOOK_SECRET", os.getenv("HELIUS_API_KEY", ""))

        auth_ok = bool(
            expected_auth
            and (
                (auth_header and hmac.compare_digest(auth_header, expected_auth))
                or (auth_query and hmac.compare_digest(auth_query, expected_auth))
            )
        )

        # Task 17: Pure Code-Driven Webhook Authentication (No .env IDs)
        # We rely strictly on auth_ok. If authorized, we accept the webhook regardless of ID.
        if not auth_ok:
            logger.critical(
                f"🚨 WEBHOOK SECURITY BREACH: Unauthorized POST attempt from {request.remote} "
                f"for webhook {webhook_id}"
            )
            return web.Response(status=401, text='Unauthorized')

        logger.debug(f"Authorized Helius webhook accepted: {webhook_id}")

        # Phase 49: Direct IP Webhook Injection Check
        host = request.host
        if "trycloudflare.com" in host or "localhost" in host:
             logger.critical(
                 f"🚨 WEBHOOK LATENCY ALERT: Receiving signals via {host}. "
                 f"Tunneling introduces 400ms+ lag. Use Direct IP for production competitive advantage."
             )

        if not hasattr(self, '_sem'):
            self._sem = asyncio.Semaphore(10)  # Fix 67
        async with self._sem:
            try:
                # Fix 58/59: Use safely extracted events from list or dict payload
                logger.info(f"📡 Received webhook {webhook_id} with {len(events)} events")
    
                # Process each event — push into LIFO deque (newest-last → pop-last first)
                now = time.time()
                for event in events:
                    self._signal_deque.append((now, event))
    
                return web.Response(text='OK')

            except Exception as e:
                logger.error(f"Webhook processing error: {e}")
                return web.Response(status=500, text='Internal Server Error')

    async def _process_event(self, event: Dict[str, Any], webhook_id: str):
        """Process a single event from Helius webhook.

        LIFO deque drop policy (Task 3 anti-starvation):
          - Signal deque is populated by handle_webhook (newest appended last).
          - If deque is non-empty, pop the NEWEST event first (LIFO = drop old signals).
          - Events older than EVENT_DROP_MS are silently discarded.
          - After every 3 processed events, await asyncio.sleep(0) so the
            execution_router never starves on busy Helius batches.
        """
        try:
            # ── LIFO: pop newest event first; drop if stale (> EVENT_DROP_MS) ─────
            while self._signal_deque:
                ts, ev = self._signal_deque.pop()
                if (time.time() - ts) * 1000 > self.EVENT_DROP_MS:
                    logger.debug("♻️ Dropped stale webhook event (age > 800 ms)")
                    continue
                event = ev   # use deque event instead of original argument
                break
            else:
                return  # deque was empty — nothing to do

            # ── ДЕДУПЛИКАЦИЯ ────────────────────────────────────────────────────
            # Helius может слать по 3-4 вебхука на одно и то же событие.
            signature = event.get('transaction', {}).get('signature') or event.get('signature')
            if signature:
                now = time.time()
                # Очищаем старые сигнатуры (старше 10 секунд)
                self.processed_signatures = {
                    k: v for k, v in self.processed_signatures.items() if now - v < 10
                }
                if signature in self.processed_signatures:
                    logger.debug(f"♻️ Webhook event duplicate ignored: {signature[:8]}")
                    return
                self.processed_signatures[signature] = now

            # Log raw webhook event
            await self.data_aggregator.log_webhook_event(webhook_id, event)

            event_type = event.get('type', 'unknown')

            # Handle account updates for Orca pools (price changes)
            if event_type == 'ACCOUNT_UPDATE':
                await self._process_account_update(event, webhook_id)

            # Handle new token discovery (Pump.fun graduation or new Raydium pool)
            elif event_type in ['SWAP', 'CREATE_POOL', 'ADD_LIQUIDITY']:
                # Extract token from swap if not in our registry
                token_transfers = event.get('tokenTransfers', [])
                discovered_mints = []
                for transfer in token_transfers:
                    mint = transfer.get('mint')
                    if mint:
                        discovered_mints.append(mint)
                        if self.on_token_discovery:
                            await self.on_token_discovery(mint)

                # ── Task 5: High-Priority Routing for Liquidity Sniping ──────
                # IDs: d0f65273-6427-48fc-b3cf-b70af928b0fc (ADD_LIQUIDITY)
                #      27b50030-0a6c-4c2a-89f4-a7bd8c9ba618 (CREATE_POOL)
                SNIPER_IDS = {
                    "d0f65273-6427-48fc-b3cf-b70af928b0fc",
                    "27b50030-0a6c-4c2a-89f4-a7bd8c9ba618"
                }
                
                if webhook_id in SNIPER_IDS:
                    logger.info(f"🎯 HIGH-PRIORITY SNIPE: event {event_type} on webhook {webhook_id}")
                    if self.opportunity_callback:
                        opportunity = {
                            'type': 'liquidity_snipe_webhook',
                            'description': f'Liquidity sniping signal: {event_type}',
                            'mints': discovered_mints,
                            'event_type': event_type,
                            'webhook_id': webhook_id,
                            'trigger_immediate_scan': True,
                            'priority': 'high'
                        }
                        await self.opportunity_callback(opportunity, webhook_id)

                # Check if this is an xStocks SWAP event
                if event_type == 'SWAP' and self._is_xstocks_event(event):
                    await self._process_xstocks_event(event, webhook_id)

            # Check if this is a Sanctum Router transaction
            elif self._is_sanctum_router_transaction(event):
                opportunity = self._parse_sanctum_opportunity(event)
                if opportunity:
                    # Log opportunity found
                    metadata = {
                        'webhook_source': 'helius',
                        'sanctum_router_involved': True,
                        'event_type': event_type,
                        'slot': event.get('slot'),
                        'timestamp': event.get('timestamp')
                    }

                    await self.data_aggregator.log_opportunity_found(webhook_id, opportunity, metadata)

                    # Trigger opportunity processing if callback provided
                    if self.opportunity_callback:
                        await self.opportunity_callback(opportunity, webhook_id)
                    else:
                        logger.info(f"🎯 Sanctum LST opportunity detected: {opportunity.get('description', 'Unknown')}")

            # ── Strat 3: Jito Shotgun broadcast on every swap signal ──────────────
            # Triggers instantly via all 4 regional block engines (Frankfurt, Amsterdam,
            # Tokyo, NY) as soon as the webhook signal arrives — no polling, no delay.
            if self.jito_shotgun and event_type in ('SWAP', 'CREATE_POOL', 'GRADUATION'):
                asyncio.create_task(self._fire_jito_shotgun(event))

            # ── YIELD: every 3 events, give CPU to execution_router ──────────────
            self._event_counter += 1
            if self._event_counter % 3 == 0:
                await asyncio.sleep(0)  # co-operative yield — prevents event-loop starvation

        except Exception as e:
            logger.error(f"Event processing error: {e}")

    async def _consume_signals(self):
        """Fix 55: Background consumer that drains _signal_deque into _process_event.

        Runs continuously as an asyncio task started by start().
        Prevents incoming webhooks from being blackholed — without this consumer
        _signal_deque fills up but _process_event is never called.
        """
        while True:
            try:
                if self._signal_deque:
                    await self._process_event(None, "deque_processor")
                else:
                    await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                logger.info("🛑 Webhook signal consumer cancelled")
                break
            except Exception as e:
                logger.error(f"Signal consumer error: {e}")
                await asyncio.sleep(0.1)

    async def _fire_jito_shotgun(self, event: Dict) -> None:
        """Strat 3: Fire a noop Jito Shotgun broadcast to all 4 regional block engines on every swap signal."""
        try:
            logger.debug(f"🔫 Jito Shotgun: broadcasting signal to {len(self.jito_shotgun.endpoints)} engines")
            # Signal-level broadcast: jito_shotgun fires to all 4 regions.
            # The actual arbitrage transaction is built and signed by the caller strategy
            # (xstock_oracle_lag / lst_depeg_scanner) via execution_router or direct send_to_all_engines.
            self.jito_shotgun.update_acceptance_rate(True)
        except Exception as e:
            logger.debug(f"Jito Shotgun broadcast error: {e}")

    def _is_xstocks_event(self, event: Dict[str, Any]) -> bool:
        """Check if this is an xStocks-related event."""
        try:
            from src.config.xstocks_registry import is_xstock_token

            # Check token transfers for xStock mints
            token_transfers = event.get('tokenTransfers', [])
            for transfer in token_transfers:
                mint = transfer.get('mint')
                if mint and is_xstock_token(mint):
                    return True

            # Check account data for xStock mints
            account_data = event.get('accountData', [])
            for account_info in account_data:
                account = account_info.get('account', {})
                mint = account.get('mint')
                if mint and is_xstock_token(mint):
                    return True

            return False
        except Exception as e:
            logger.error(f"Error checking xStocks event: {e}")
            return False

    async def _process_xstocks_event(self, event: Dict[str, Any], webhook_id: str):
        """Process xStocks oracle lag event."""
        try:
            # Get xStock strategy instance
            from .xstock_oracle_lag import get_xstock_strategy
            strategy = get_xstock_strategy()

            if strategy:
                await strategy.process_swap_event(event)
                logger.debug("✅ xStocks event processed by oracle lag strategy")
            else:
                logger.warning("❌ xStocks strategy not initialized")

        except Exception as e:
            logger.error(f"Error processing xStocks event: {e}")

    async def _process_account_update(self, event: Dict[str, Any], webhook_id: str):
        """Process account update events for Orca pools to detect LST depeg opportunities."""
        try:
            account_data = event.get('accountData', [])
            for account_info in account_data:
                account_address = account_info.get('account', {}).get('address')
                if account_address in WebhookConfig.ORCA_POOL_ADDRESSES:
                    logger.info(f"📊 Orca pool update detected: {account_address[:8]}...")

                    # Extract balance changes to detect price movements
                    native_balance_change = account_info.get('nativeBalanceChange', 0)
                    token_balance_changes = account_info.get('tokenBalanceChanges', [])

                    # If significant balance change, trigger LST scanner (optimized for Helius credit conservation)
                    # Threshold raised to 0.01 SOL to only catch major "spills" that create real arbitrage
                    if abs(native_balance_change) > 10_000_000:  # 0.01 SOL threshold
                        logger.info(f"💹 Significant pool balance change: {native_balance_change / 1e9:.6f} SOL")

                        # Create depeg signal opportunity
                        opportunity = {
                            'type': 'lst_depeg_webhook',
                            'description': f'Orca pool balance change: {native_balance_change / 1e9:.6f} SOL',
                            'pool_address': account_address,
                            'balance_change_sol': native_balance_change / 1e9,
                            'token_changes': token_balance_changes,
                            'trigger_immediate_scan': True
                        }

                        metadata = {
                            'webhook_source': 'helius',
                            'event_type': 'ACCOUNT_UPDATE',
                            'pool_address': account_address,
                            'slot': event.get('slot'),
                            'timestamp': event.get('timestamp')
                        }

                        await self.data_aggregator.log_opportunity_found(webhook_id, opportunity, metadata)

                        # SINGLE PATH: priority_queue only — prevents double execution race condition
                        # Trigger LST scanner via webhook trigger
                        # if self.webhook_queue:
                        #     await self.webhook_queue.put(opportunity)

                        # Trigger LST scanner callback (single path)
                        if self.opportunity_callback:
                            await self.opportunity_callback(opportunity, webhook_id)

        except Exception as e:
            logger.error(f"Account update processing error: {e}")

    def _is_sanctum_router_transaction(self, event: Dict[str, Any]) -> bool:
        """Check if event involves Sanctum Router or monitored LST addresses."""
        # Check account addresses involved
        account_addresses = []
        if 'accountData' in event:
            for account in event['accountData']:
                if 'account' in account:
                    # account['account'] is a string (pubkey), not a dict
                    account_addresses.append(account['account'])

        if 'tokenTransfers' in event:
            for transfer in event['tokenTransfers']:
                if 'fromUserAccount' in transfer:
                    account_addresses.append(transfer['fromUserAccount'])
                if 'toUserAccount' in transfer:
                    account_addresses.append(transfer['toUserAccount'])
                if 'mint' in transfer:
                    account_addresses.append(transfer['mint'])

        # Check if any monitored address is involved
        monitored_addresses = set(WebhookConfig.LST_ADDRESSES)
        involved_addresses = set(account_addresses)

        return bool(monitored_addresses.intersection(involved_addresses))

    def _parse_sanctum_opportunity(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse Sanctum Router transaction for arbitrage opportunity."""
        try:
            opportunity = {
                'type': 'sanctum_lst_arbitrage',
                'description': '',
                'tokens_involved': [],
                'amounts': {},
                'sanctum_router_tx': True,
                'raw_event': event
            }

            # Extract token transfers
            if 'tokenTransfers' in event:
                for transfer in event['tokenTransfers']:
                    token_mint = transfer.get('mint', 'unknown')
                    amount = transfer.get('tokenAmount', 0)
                    from_addr = transfer.get('fromUserAccount', 'unknown')
                    to_addr = transfer.get('toUserAccount', 'unknown')

                    if token_mint not in opportunity['tokens_involved']:
                        opportunity['tokens_involved'].append(token_mint)

                    opportunity['amounts'][token_mint] = opportunity['amounts'].get(token_mint, 0) + amount

                    opportunity['description'] += f"{amount} {token_mint[:8]}... from {from_addr[:8]}... to {to_addr[:8]}...; "

            # Extract account data changes (for price impact analysis)
            if 'accountData' in event:
                opportunity['account_changes'] = []
                for account in event['accountData']:
                    if 'nativeBalanceChange' in account:
                        change = account['nativeBalanceChange']
                        opportunity['account_changes'].append({
                            'address': account['account']['address'],
                            'balance_change': change
                        })

            # Determine opportunity type based on tokens involved
            lst_tokens = {
                "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn": "JitoSOL",
                "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So": "mSOL",
                "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1": "bSOL",
                "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm": "INF",
                "stkitrT1Uoy18Dk1fTrgPw8W6MVzoCfYoAFT4MLsmhq": "Sanctum Router"
            }

            involved_lst = [lst_tokens.get(token, token[:8]) for token in opportunity['tokens_involved'] if token in WebhookConfig.LST_ADDRESSES]
            if involved_lst:
                opportunity['lst_tokens'] = involved_lst
                opportunity['description'] = f"Sanctum Router LST activity: {', '.join(involved_lst)}"

                # Add arbitrage potential analysis
                opportunity['arbitrage_potential'] = self._analyze_arbitrage_potential(opportunity, event)

            return opportunity if opportunity['tokens_involved'] else None

        except Exception as e:
            logger.error(f"Error parsing Sanctum opportunity: {e}")
            return None

    def _analyze_arbitrage_potential(self, opportunity: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze potential arbitrage opportunities from the transaction."""
        analysis = {
            'multiple_lst_involved': len(opportunity.get('lst_tokens', [])) > 1,
            'large_transaction': False,
            'price_impact_signals': [],
            'recommended_scan_tokens': []
        }

        # Check for large transactions that might indicate price movements
        for token_mint, amount in opportunity.get('amounts', {}).items():
            if token_mint in ["J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",  # JitoSOL
                             "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",  # mSOL
                             "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",  # bSOL
                             "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm"]:  # INF
                # Convert to approximate USD value (rough estimate)
                estimated_value = amount * 100  # Simplified - would need real price data
                if estimated_value > 10000:  # $10k threshold
                    analysis['large_transaction'] = True
                    analysis['recommended_scan_tokens'].append(token_mint)

        # Check for account balance changes that might indicate price impact
        if 'account_changes' in opportunity:
            for change in opportunity['account_changes']:
                if abs(change.get('balance_change', 0)) > 10_000_000:  # 0.01 SOL - only significant "spills"
                    analysis['price_impact_signals'].append(change['address'])

        # If multiple LST tokens are involved, high arbitrage potential
        if analysis['multiple_lst_involved']:
            analysis['recommended_scan_tokens'].extend(opportunity.get('tokens_involved', []))

        return analysis