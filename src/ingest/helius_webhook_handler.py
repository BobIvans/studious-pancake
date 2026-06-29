"""Helius Webhook Handler for Sanctum LST Arbitrage Opportunities."""

import os
import hmac
import hashlib
import orjson
import logging
import asyncio
import time
from collections import defaultdict
from aiohttp import web
import aiohttp
from typing import Dict, Any, Optional
from datetime import datetime
import src.ingest.shared_state as shared_state

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
        # Rate limiter for DoS protection
        self.ip_limits = defaultdict(list)
        self.MAX_REQ_PER_SEC = 5  # Max 5 requests per second per IP
        # ── ИСПРАВЛЕНИЕ: asyncio.Queue вместо deque — без потери событий ────────
        self._signal_queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self.WORKER_COUNT = 3
        self._worker_pool: List[asyncio.Task] = []

    async def start(self):
        """Start the webhook server and the worker pool."""
        try:
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            site = web.TCPSite(runner=self.runner, host='0.0.0.0', port=self.port)
            await site.start()
            logger.warning(f"🚀 WEBHOOK SERVER ACTIVE: Listening on port {self.port}. Endpoint: http://0.0.0.0:{self.port}/webhook")
            # ИСПРАВЛЕНИЕ: Worker Pool — 3 фиксированных воркера
            for i in range(self.WORKER_COUNT):
                worker = asyncio.create_task(self._worker(i))
                self._worker_pool.append(worker)
            logger.info(f"🔄 Webhook worker pool started with {self.WORKER_COUNT} workers")
        except OSError as e:
            if "Address already in use" in str(e):
                logger.warning(f"⚠️ Port {self.port} already in use. Webhook server disabled for this session.")
                logger.info("💡 Tip: Stop other instances of the bot before starting a new one.")
                return
            else:
                raise

    async def stop(self):
        """Stop the webhook server and worker pool."""
        for task in self._worker_pool:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._worker_pool.clear()
        if self.runner:
            await self.runner.cleanup()
            logger.info("🛑 Helius webhook server stopped")

    async def handle_health(self, request):
        """Handle healthcheck requests with strict production checks."""
        last_opp_ts = shared_state.stats.get("last_opportunity_ts", 0.0)
        consecutive_failures = shared_state.stats.get("consecutive_failures", 0)
        virtual_balance = shared_state.stats.get("virtual_balance", 1.0)
        now = time.time()

        status = "alive"
        http_status = 200

        reasons = []
        if now - last_opp_ts > 300:  # 5 минут без возможностей (проблема с сетью/вебхуком)
            reasons.append("no_opportunities_5min")
        if consecutive_failures >= 3:
            reasons.append("high_failure_rate")
        if virtual_balance < 0.005:
            reasons.append("low_balance")
        if shared_state.GLOBAL_STOP_EVENT and shared_state.GLOBAL_STOP_EVENT.is_set():
            reasons.append("global_stop_event_set")

        if reasons:
            status = "degraded"
            http_status = 503  # Service Unavailable

        return web.json_response({
            "status": status,
            "reasons": reasons,
            "timestamp": datetime.now().isoformat(),
            "virtual_balance": virtual_balance
        }, status=http_status)

    async def handle_webhook(self, request):
        """Handle incoming webhook from Helius with HMAC signature verification and rate limiting."""
        # 1. STRICT RATE LIMITER BY IP
        client_ip = request.headers.get("X-Forwarded-For", request.remote)
        if "," in client_ip:
            client_ip = client_ip.split(",")[0].strip()
        
        now = time.time()
        self.ip_limits[client_ip] = [t for t in self.ip_limits[client_ip] if now - t < 1.0]
        
        if len(self.ip_limits[client_ip]) >= self.MAX_REQ_PER_SEC:
            logger.warning(f"🚨 Webhook Rate Limit hit for IP: {client_ip} ({len(self.ip_limits[client_ip])} req/sec)")
            return web.Response(status=429, text='Too Many Requests')
        
        self.ip_limits[client_ip].append(now)

        # 2. IP WHITELISTING (Optional)
        allowed_ips_raw = os.getenv("ALLOWED_WEBHOOK_IPS", "")
        if allowed_ips_raw:
            allowed_ips = [ip.strip() for ip in allowed_ips_raw.split(",") if ip.strip()]
            if client_ip not in allowed_ips:
                logger.critical(f"🚨 WEBHOOK BLOCKED: Request from unauthorized IP: {client_ip}")
                return web.Response(status=403, text='Forbidden')

        # Read raw body for HMAC computation
        raw_bytes = await request.read()
        
        # 3. CRYPTOGRAPHIC SIGNATURE VERIFICATION (HMAC-SHA256)
        helius_signature = request.headers.get("X-Helius-Signature")
        webhook_secret = os.getenv("HELIUS_WEBHOOK_SECRET")

        if webhook_secret:
            if not helius_signature:
                logger.critical(f"🚨 SEC-BREACH: Request from {client_ip} missing X-Helius-Signature header!")
                return web.Response(status=401, text='Unauthorized: Missing Signature')
            
            expected_signature = hmac.new(
                webhook_secret.encode('utf-8'),
                raw_bytes,
                hashlib.sha256
            ).hexdigest()
            
            if not hmac.compare_digest(expected_signature, helius_signature):
                logger.critical(f"🚨 SEC-BREACH: Invalid signature from IP {client_ip}! Computed={expected_signature[:8]}..., Got={helius_signature[:8]}...")
                return web.Response(status=401, text='Unauthorized: Invalid Signature')
        else:
            # Fallback insecure method (if secret not configured in .env)
            logger.warning("⚠️ HELIUS_WEBHOOK_SECRET is not configured! Falling back to weak token verification...")
            auth_header = request.headers.get('Authorization', '')
            expected_auth = os.getenv("HELIUS_API_KEY", "")
            
            if not expected_auth or not hmac.compare_digest(auth_header, expected_auth):
                logger.critical(f"🚨 SEC-BREACH: Unauthorized fallback webhook attempt from {client_ip}")
                return web.Response(status=401, text='Unauthorized')

        # 4. PARSE PAYLOAD (after successful authorization)
        try:
            data = orjson.loads(raw_bytes) if raw_bytes else []
        except Exception:
            logger.error(f"Invalid JSON payload from {client_ip}")
            return web.Response(status=400, text='Bad JSON')

        # Parse webhook data
        if isinstance(data, list):
            events = data
            webhook_id = request.query.get('webhook_id', 'unknown')
        elif isinstance(data, dict):
            events = data.get('events', [data])
            webhook_id = data.get('webhookId') or request.query.get('webhook_id', 'unknown')
        else:
            events = []
            webhook_id = 'unknown'

        logger.info(f"📡 Authorized Helius webhook accepted: {webhook_id} from {client_ip} ({len(events)} events)")

        if not hasattr(self, '_sem'):
            self._sem = asyncio.Semaphore(10)
        
        async with self._sem:
            try:
                for event in events:
                    try:
                        self._signal_queue.put_nowait((time.time(), event, webhook_id))
                    except asyncio.QueueFull:
                        logger.warning(f"Webhook queue full, dropping event from {webhook_id}")
                return web.Response(text='OK')
            except Exception as e:
                logger.error(f"Webhook processing error: {e}")
                return web.Response(status=500, text='Internal Server Error')

    async def _worker(self, worker_id: int) -> None:
        """Worker pool task: consumes events from _signal_queue and processes them."""
        while True:
            try:
                ts, event, webhook_id = await self._signal_queue.get()
                # Staleness check: drop events older than 5 seconds
                age = time.time() - ts
                if age > 5.0:
                    logger.debug(f"Worker {worker_id}: dropped stale event (age {age:.1f}s)")
                    self._signal_queue.task_done()
                    continue
                await self._process_event(event, webhook_id)
                self._signal_queue.task_done()
            except asyncio.CancelledError:
                logger.info(f"Worker {worker_id} cancelled")
                break
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")
                await asyncio.sleep(0.1)

    async def _process_event(self, event: Optional[Dict[str, Any]] = None, webhook_id: str = "unknown"):
        """Process a single event from Helius webhook.

        Called by _worker pool tasks with the event already provided.
        If event is None, falls back to pulling from _signal_queue (direct call case).
        """
        try:
            if event is None:
                try:
                    ts, ev, w_id = self._signal_queue.get_nowait()
                    event = ev
                    webhook_id = w_id
                except asyncio.QueueEmpty:
                    return

            # ── ДЕДУПЛИКАЦИЯ ────────────────────────────────────────────────────
            tx_data = event.get('transaction') or {}
            signature = tx_data.get('signature') if isinstance(tx_data, dict) else event.get('signature')
            if signature:
                now = time.time()
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

            if event_type == 'ACCOUNT_UPDATE':
                await self._process_account_update(event, webhook_id)
            elif event_type in ['SWAP', 'CREATE_POOL', 'ADD_LIQUIDITY']:
                token_transfers = event.get('tokenTransfers', [])
                discovered_mints = []
                for transfer in token_transfers:
                    mint = transfer.get('mint')
                    if mint:
                        discovered_mints.append(mint)
                        if self.on_token_discovery:
                            await self.on_token_discovery(mint)

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

            elif self._is_sanctum_router_transaction(event):
                opportunity = self._parse_sanctum_opportunity(event)
                if opportunity:
                    metadata = {
                        'webhook_source': 'helius',
                        'sanctum_router_involved': True,
                        'event_type': event_type,
                        'slot': event.get('slot'),
                        'timestamp': event.get('timestamp')
                    }
                    await self.data_aggregator.log_opportunity_found(webhook_id, opportunity, metadata)
                    if self.opportunity_callback:
                        await self.opportunity_callback(opportunity, webhook_id)
                    else:
                        logger.info(f"🎯 Sanctum LST opportunity detected: {opportunity.get('description', 'Unknown')}")

        except Exception as e:
            logger.error(f"Event processing error: {e}")

    async def _process_account_update(self, event: Dict[str, Any], webhook_id: str):
        """Process account update events for Orca pools."""
        try:
            account_data = event.get('accountData', [])
            for account_info in account_data:
                account_address = account_info.get('account')
                if account_address in WebhookConfig.ORCA_POOL_ADDRESSES:
                    native_balance_change = account_info.get('nativeBalanceChange', 0)
                    token_balance_changes = account_info.get('tokenBalanceChanges', [])
                    if abs(native_balance_change) > 10_000_000:
                        logger.info(f"💹 Significant pool balance change: {native_balance_change / 1e9:.6f} SOL")
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
                        if self.opportunity_callback:
                            await self.opportunity_callback(opportunity, webhook_id)
                        # Send to webhook_queue for immediate LST scanner trigger
                        if self.webhook_queue:
                            try:
                                await self.webhook_queue.put(opportunity)
                            except asyncio.QueueFull:
                                logger.warning("Webhook queue full, dropping opportunity")
        except Exception as e:
            logger.error(f"Account update processing error: {e}")

    def _is_sanctum_router_transaction(self, event: Dict[str, Any]) -> bool:
        """Check if event involves Sanctum Router or monitored LST addresses."""
        account_addresses = []
        if 'accountData' in event:
            for account in event['accountData']:
                if 'account' in account:
                    account_addresses.append(account['account'])
        if 'tokenTransfers' in event:
            for transfer in event['tokenTransfers']:
                if 'fromUserAccount' in transfer:
                    account_addresses.append(transfer['fromUserAccount'])
                if 'toUserAccount' in transfer:
                    account_addresses.append(transfer['toUserAccount'])
                if 'mint' in transfer:
                    account_addresses.append(transfer['mint'])
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
            if 'accountData' in event:
                opportunity['account_changes'] = []
                for account in event['accountData']:
                    if 'nativeBalanceChange' in account:
                        change = account['nativeBalanceChange']
                        opportunity['account_changes'].append({
                            'address': account.get('account'),
                            'balance_change': change
                        })
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
        for token_mint, amount in opportunity.get('amounts', {}).items():
            if token_mint in ["J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
                             "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",
                             "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",
                             "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm"]:
                estimated_value = amount * 100
                if estimated_value > 10000:
                    analysis['large_transaction'] = True
                    analysis['recommended_scan_tokens'].append(token_mint)
        if 'account_changes' in opportunity:
            for change in opportunity['account_changes']:
                if abs(change.get('balance_change', 0)) > 10_000_000:
                    analysis['price_impact_signals'].append(change['address'])
        if analysis['multiple_lst_involved']:
            analysis['recommended_scan_tokens'].extend(opportunity.get('tokens_involved', []))
        return analysis
