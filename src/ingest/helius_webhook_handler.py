"""Helius Webhook Handler for Sanctum LST Arbitrage Opportunities."""

import os
import re
import hmac
import hashlib
import orjson
import logging
import asyncio
import time
from collections import defaultdict
from aiohttp import web
import aiohttp
from typing import Dict, Any, Optional, List
from datetime import datetime
import src.ingest.shared_state as shared_state

from .data_aggregator import DataAggregator
from .webhook_config import WebhookConfig
logger = logging.getLogger(__name__)


class HeliusWebhookHandler:
    """Handles incoming Helius webhooks for LST arbitrage detection."""

    def __init__(
            self,
            data_aggregator: DataAggregator,
            port: int = 3000,
            opportunity_callback=None,
            webhook_queue=None,
            on_token_discovery=None,
            jito_shotgun=None):
        self.data_aggregator = data_aggregator
        self.port = port
        # Callback to process opportunities
        self.opportunity_callback = opportunity_callback
        self.webhook_queue = webhook_queue  # AsyncQueue for webhook signals
        self.on_token_discovery = on_token_discovery  # Callback for dynamic registry
        self.processed_signatures = {}  # Cache of processed signatures for deduplication
        # Strat 3: Jito Shotgun — all-region broadcast on webhook signal
        self.jito_shotgun = jito_shotgun
        self.app = web.Application()
        self.app.router.add_post('/webhook', self.handle_webhook)
        self.app.router.add_get('/', self.handle_health)
        self.app.router.add_get('/health', self.handle_health)
        self.runner = None
        # Rate limiter for DoS protection
        self.ip_limits = defaultdict(list)
        self.MAX_REQ_PER_SEC = 5
        # ── ИСПРАВЛЕНИЕ: asyncio.Queue вместо deque — без потери событий ─────
        self._signal_queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self.WORKER_COUNT = int(os.getenv("WEBHOOK_WORKERS", "10"))  # FIX 142
        self._worker_pool: List[asyncio.Task] = []
        self._last_scan_trigger: Dict[str, float] = {}
        self._dedup_lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(10)

    async def _load_signatures_from_db(self):
        """FIX 140: Load processed signatures from SQLite on startup to prevent duplicates after crash"""
        try:
            import aiosqlite
            db_path = self.data_aggregator.db_path
            if not os.path.exists(db_path):
                return
            async with aiosqlite.connect(db_path, timeout=10) as db:
                cutoff = time.time() - 7200  # last 2 hours
                async with db.execute(
                    "SELECT transaction_signature FROM events WHERE timestamp > ? AND transaction_signature IS NOT NULL",
                    (cutoff,)
                ) as cursor:
                    rows = await cursor.fetchall()
                    now = time.time()
                    for row in rows:
                        sig = row[0]
                        if sig:
                            self.processed_signatures[sig] = now
            logger.info(
                f"💾 Persistent dedup: loaded {
                    len(
                        self.processed_signatures)} signatures from database on startup.")
        except Exception as e:
            logger.warning(f"Failed to load signatures: {e}")

    async def start(self):
        """Start the webhook server and the worker pool."""
        await self._load_signatures_from_db()  # FIX 140: Restore persistent dedup
        # Safety check: HELIUS_WEBHOOK_SECRET must be configured in production
        webhook_secret = os.getenv("HELIUS_WEBHOOK_SECRET")
        if not webhook_secret:
            raise RuntimeError(
                "HELIUS_WEBHOOK_SECRET environment variable is required for production. "
                "Set it in your .env file or use 'openssl rand -hex 32' to generate one.")
        try:
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            import ssl  # FIX 137
            # FIX 138: Bind to all interfaces
            host = os.getenv("WEBHOOK_HOST", "0.0.0.0")

            # FIX 137: SSL context for HTTPS support
            ssl_context = None
            cert_file = os.getenv("SSL_CERT_FILE")
            key_file = os.getenv("SSL_KEY_FILE")
            if cert_file and key_file and os.path.exists(
                    cert_file) and os.path.exists(key_file):
                try:
                    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                    ssl_context.load_cert_chain(
                        certfile=cert_file, keyfile=key_file)
                    logger.info(
                        "🔒 HTTPS/TLS successfully initialized for Helius Webhook server")
                except Exception as ssl_err:
                    logger.error(
                        f"Failed to load SSL chain: {ssl_err}. Falling back to plain HTTP.")

            site = web.TCPSite(
                runner=self.runner,
                host=host,
                port=self.port,
                ssl_context=ssl_context)
            await site.start()
            logger.warning(
                f"🚀 WEBHOOK SERVER ACTIVE: Listening on port {
                    self.port} ({host}). Endpoint: http://{host}:{
                    self.port}/webhook")
        except OSError as e:
            if "Address already in use" in str(e):
                logger.warning(
                    f"⚠️ Port {
                        self.port} already in use. Webhook server disabled for this session.")
                logger.info(
                    "💡 Tip: Stop other instances of the bot before starting a new one.")
            else:
                raise

        for i in range(self.WORKER_COUNT):
            worker = asyncio.create_task(self._worker(i))
            self._worker_pool.append(worker)
        logger.info(
            f"🔄 Webhook worker pool started with {
                self.WORKER_COUNT} workers")

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
        # FIX 143: Secure health check from public scanners leaking
        # virtual_balance
        health_token = request.headers.get("X-Health-Token")
        expected_token = os.getenv("HEALTH_TOKEN")
        if not expected_token or health_token != expected_token:
            return web.json_response({
                "status": "alive",
                "timestamp": datetime.now().isoformat()
            })

        last_opp_ts = shared_state.stats.get("last_opportunity_ts", 0.0)
        consecutive_failures = shared_state.stats.get(
            "consecutive_failures", 0)
        virtual_balance = shared_state.stats.get("virtual_balance", 1.0)
        now = time.time()

        status = "alive"
        http_status = 200

        reasons = []
        if now - last_opp_ts > 300:  # 5 min without opportunities
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
        # FIX 158: Prune and completely delete empty IP keys to avoid memory
        # leaks
        pruned_limits = [
            t for t in self.ip_limits.get(
                client_ip, []) if now - t < 1.0]
        if not pruned_limits:
            self.ip_limits.pop(client_ip, None)
        else:
            self.ip_limits[client_ip] = pruned_limits

        if len(self.ip_limits[client_ip]) >= self.MAX_REQ_PER_SEC:
            logger.warning(
                f"🚨 Webhook Rate Limit hit for IP: {client_ip} ({len(self.ip_limits[client_ip])} req/sec)")
            return web.Response(status=429, text='Too Many Requests')

        self.ip_limits[client_ip].append(now)

        # 0. STRICT PAYLOAD SIZE LIMITER (1 MB max)
        if request.content_length and request.content_length > 1024 * 1024:
            logger.critical(
                f"🚨 DoS PROTECT: Payload too large from {client_ip} ({
                    request.content_length} bytes)")
            return web.Response(status=413, text='Payload Too Large')

        # 2. IP WHITELISTING (Optional)
        allowed_ips_raw = os.getenv("ALLOWED_WEBHOOK_IPS", "")
        if allowed_ips_raw:
            allowed_ips = [ip.strip()
                           for ip in allowed_ips_raw.split(",") if ip.strip()]
            if client_ip not in allowed_ips:
                logger.critical(
                    f"🚨 WEBHOOK BLOCKED: Request from unauthorized IP: {client_ip}")
                return web.Response(status=403, text='Forbidden')

        # Read raw body for HMAC computation
        raw_bytes = await request.read()

        # 3. CRYPTOGRAPHIC SIGNATURE VERIFICATION (HMAC-SHA256)
        helius_signature = request.headers.get("X-Helius-Signature")
        webhook_secret = os.getenv("HELIUS_WEBHOOK_SECRET")

        if webhook_secret:
            if not helius_signature:
                logger.critical(
                    f"🚨 SEC-BREACH: Request from {client_ip} missing X-Helius-Signature header!")
                return web.Response(
                    status=401, text='Unauthorized: Missing Signature')

            expected_signature = hmac.new(
                webhook_secret.encode('utf-8'),
                raw_bytes,
                hashlib.sha256
            ).hexdigest()

            if not hmac.compare_digest(expected_signature, helius_signature):
                # FIX 239: Do not leak signature prefix in logs to protect HMAC
                # from brute force
                logger.critical(
                    f"🚨 SEC-BREACH: Invalid signature from IP {client_ip}!")
                return web.Response(
                    status=401, text='Unauthorized: Invalid Signature')
        else:
            # Безопасность: Не использовать небезопасный fallback. Если webhook_secret не задан,
            # отвечаем 401 Unauthorized. Production требует
            # HELIUS_WEBHOOK_SECRET.
            logger.critical(
                f"🚨 SEC-BREACH: HELIUS_WEBHOOK_SECRET not configured! Request from {client_ip} rejected.")
            return web.Response(
                status=401,
                text='Unauthorized: Webhook secret not configured')

        # 4. PARSE PAYLOAD (after successful authorization)
        try:
            data = orjson.loads(raw_bytes) if raw_bytes else []
        except Exception:
            logger.error(f"Invalid JSON payload from {client_ip}")
            return web.Response(status=400, text='Bad JSON')

        # Parse webhook data
        if isinstance(data, list):
            events = data
        elif isinstance(data, dict):
            events = data.get('events', [data])
        else:
            events = []

        # FIX 108: Извлекаем ID вебхука из заголовка Helius или JSON тела
        webhook_id = (
            request.headers.get("X-Helius-Webhook-Id")
            or request.query.get('webhook_id')
            or (data.get('webhookId') if isinstance(data, dict) else None)
            or 'unknown'
        )

        # Sanitize to prevent Log Injection / SQLi
        webhook_id = re.sub(r'[^a-zA-Z0-9_-]', '', str(webhook_id))[:64]

        # TASK 4.2 (SEC-003): Webhook ID Whitelisting
        if WebhookConfig.WEBHOOK_IDS and webhook_id not in WebhookConfig.WEBHOOK_IDS:
            logger.critical(
                f"🚨 SEC-BREACH: Unrecognized Webhook ID {webhook_id} from {client_ip}")
            return web.Response(
                status=403, text='Forbidden: Unknown Webhook ID')

        logger.info(
            f"📡 Authorized Helius webhook accepted: {webhook_id} from {client_ip} ({
                len(events)} events)")

        # FIX 178: Removed useless semaphore to prevent Helius delivery timeout on bursts
        # FIX #43: Atomic buffer — pre-check free space BEFORE enqueuing any
        # event
        try:
            free_space = self._signal_queue.maxsize - self._signal_queue.qsize()
            if free_space < len(events):
                logger.warning(
                    f"Webhook queue near full ({free_space} slots left), rejecting batch of {
                        len(events)} for Helius retry.")
                return web.Response(status=503, text='Queue Full')

            for event in events:
                self._signal_queue.put_nowait((time.time(), event, webhook_id))
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
                    logger.debug(
                        f"Worker {worker_id}: dropped stale event (age {
                            age:.1f}s)")
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

    async def _process_event(
            self, event: Optional[Dict[str, Any]] = None, webhook_id: str = "unknown"):
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

            # TASK 4.1 (SEC-002): Webhook Replay Attack Protection
            event_timestamp = event.get('timestamp')
            if event_timestamp:
                age = time.time() - event_timestamp
                if age > 30.0:
                    logger.warning(
                        f"🚨 REPLAY ATTACK BLOCKED: Event is {
                            age:.1f}s old. Ignored.")
                    return

            # ── ДЕДУПЛИКАЦИЯ (CONC-001 & CONC-012) ───────────────────────────
            async with self._dedup_lock:
                # FIX 107: Извлекаем сигнатуру напрямую из корня события Helius
                signature = event.get('signature') or (
                    event.get('transaction') or {}).get('signature')
                if signature:
                    now = time.time()
                    # Prune old signatures only if cache size grows too large (optimizes CPU cycles)
                    # FIX 141: Increase dedup TTL to 600 seconds (10 min) to
                    # cover Helius retries
                    if len(self.processed_signatures) > 5000:
                        self.processed_signatures = {
                            k: v for k, v in self.processed_signatures.items() if now - v < 600}
                    if signature in self.processed_signatures:
                        logger.debug(
                            f"♻️ Webhook event duplicate ignored: {signature[:8]}")
                        return
                    self.processed_signatures[signature] = now

            # Log raw webhook event
            await self.data_aggregator.log_webhook_event(webhook_id, event)

            event_type = event.get('type', 'unknown')

            if event_type == 'ACCOUNT_UPDATE':
                await self._process_account_update(event, webhook_id)
            # FIX 106: Ставим проверку Sanctum ПЕРВОЙ, чтобы SWAP-события не
            # перехватывали ее
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
                        logger.info(
                            f"🎯 Sanctum LST opportunity detected: {
                                opportunity.get(
                                    'description', 'Unknown')}")
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
                    logger.info(
                        f"🎯 HIGH-PRIORITY SNIPE: event {event_type} on webhook {webhook_id}")
                    if self.opportunity_callback:
                        opportunity = {
                            'type': 'liquidity_snipe_webhook',
                            'description': f'Liquidity sniping signal: {event_type}',
                            'mints': discovered_mints,
                            'event_type': event_type,
                            'webhook_id': webhook_id,
                            'trigger_immediate_scan': True,
                            'priority': 'high'}
                        await self.opportunity_callback(opportunity, webhook_id)

            # FIX 129: Handle GRADUATION events
            elif event_type == 'GRADUATION':
                opportunity = self._parse_graduation_event(event)
                if opportunity:
                    metadata = {
                        'webhook_source': 'helius',
                        'event_type': 'GRADUATION',
                        'slot': event.get('slot'),
                        'timestamp': event.get('timestamp')
                    }
                    await self.data_aggregator.log_opportunity_found(webhook_id, opportunity, metadata)
                    if self.opportunity_callback:
                        await self.opportunity_callback(opportunity, webhook_id)

            # FIX 129: Handle TRANSFER events
            elif event_type == 'TRANSFER':
                opportunity = self._parse_transfer_event(event)
                if opportunity:
                    metadata = {
                        'webhook_source': 'helius',
                        'event_type': 'TRANSFER',
                        'slot': event.get('slot'),
                        'timestamp': event.get('timestamp')
                    }
                    await self.data_aggregator.log_opportunity_found(webhook_id, opportunity, metadata)
                    if self.opportunity_callback:
                        await self.opportunity_callback(opportunity, webhook_id)
                    if self.webhook_queue:
                        try:
                            await self.webhook_queue.put(opportunity)
                        except asyncio.QueueFull:
                            pass

        except Exception as e:
            logger.error(f"Event processing error: {e}")

    async def _process_account_update(
            self, event: Dict[str, Any], webhook_id: str):
        """Process account update events for Orca pools."""
        try:
            account_data = event.get('accountData', [])
            for account_info in account_data:
                account_address = account_info.get('account')
                if account_address in WebhookConfig.ORCA_POOL_ADDRESSES:
                    # FIX 247: Atomic check-and-set to prevent TOCTOU duplicate
                    # trades
                    async with self._dedup_lock:
                        now = time.time()
                        last_trigger = self._last_scan_trigger.get(
                            account_address, 0)
                        if now - last_trigger < 2.0:
                            continue
                        self._last_scan_trigger[account_address] = now
                    native_balance_change = account_info.get(
                        'nativeBalanceChange', 0)
                    token_balance_changes = event.get(
                        'tokenBalanceChanges', [])
                    if abs(native_balance_change) > 10_000_000:
                        logger.info(
                            f"💹 Significant pool balance change: {
                                native_balance_change / 1e9:.6f} SOL")
                        opportunity = {
                            'type': 'lst_depeg_webhook',
                            'description': f'Orca pool balance change: {
                                native_balance_change / 1e9:.6f} SOL',
                            'pool_address': account_address,
                            'balance_change_sol': native_balance_change / 1e9,
                            'token_changes': token_balance_changes,
                            'trigger_immediate_scan': True}
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
                        # Send to webhook_queue for immediate LST scanner
                        # trigger
                        if self.webhook_queue:
                            try:
                                await self.webhook_queue.put(opportunity)
                            except asyncio.QueueFull:
                                logger.warning(
                                    "Webhook queue full, dropping opportunity")
        except Exception as e:
            logger.error(f"Account update processing error: {e}")

    def _is_sanctum_router_transaction(self, event: Dict[str, Any]) -> bool:
        """Check if event involves the Sanctum Router program ID.

        Uses LST_PROGRAMS (program IDs) rather than LST_ADDRESSES (token mints),
        because this check is detecting program-level invocation, not token transfers.
        """
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
        monitored_addresses = set(WebhookConfig.LST_PROGRAMS)
        involved_addresses = set(account_addresses)
        return bool(monitored_addresses.intersection(involved_addresses))

    def _parse_sanctum_opportunity(
            self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse Sanctum Router transaction for arbitrage opportunity."""
        try:
            import uuid
            correlation_id = str(uuid.uuid4())
            logger.debug(
                f"🆔 Generated correlation_id={correlation_id[:12]} for webhook event")
            opportunity = {
                'type': 'sanctum_lst_arbitrage',
                'correlation_id': correlation_id,
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
                    opportunity['amounts'][token_mint] = opportunity['amounts'].get(
                        token_mint, 0) + amount
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
            involved_lst = [lst_tokens.get(
                token, token[:8]) for token in opportunity['tokens_involved'] if token in WebhookConfig.LST_ADDRESSES]
            if involved_lst:
                opportunity['lst_tokens'] = involved_lst
                opportunity['description'] = f"Sanctum Router LST activity: {
                    ', '.join(involved_lst)}"
                opportunity['arbitrage_potential'] = self._analyze_arbitrage_potential(
                    opportunity, event)
            return opportunity if opportunity['tokens_involved'] else None
        except Exception as e:
            logger.error(f"Error parsing Sanctum opportunity: {e}")
            return None

    def _analyze_arbitrage_potential(
            self, opportunity: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze potential arbitrage opportunities from the transaction."""
        analysis = {
            'multiple_lst_involved': len(
                opportunity.get(
                    'lst_tokens',
                    [])) > 1,
            'large_transaction': False,
            'price_impact_signals': [],
            'recommended_scan_tokens': []}
        for token_mint, amount in opportunity.get('amounts', {}).items():
            if token_mint in ["J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
                              "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",
                              "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",
                              "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm"]:
                # FIX 134: Account for LST native decimals (9) to prevent
                # false-positives
                normalized_amount = amount / 1e9
                if normalized_amount >= 50.0:  # Threshold set to 50 LST
                    analysis['large_transaction'] = True
                    analysis['recommended_scan_tokens'].append(token_mint)
        if 'account_changes' in opportunity:
            for change in opportunity['account_changes']:
                if abs(change.get('balance_change', 0)) > 10_000_000:
                    analysis['price_impact_signals'].append(change['address'])
        if analysis['multiple_lst_involved']:
            analysis['recommended_scan_tokens'].extend(
                opportunity.get('tokens_involved', []))
        return analysis

    # FIX 129: Helper method for parsing Graduation events
    def _parse_graduation_event(
            self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            token_transfers = event.get('tokenTransfers', [])
            token_mint = token_transfers[0].get(
                'mint') if token_transfers else None
            account_data = event.get('accountData', [])
            raydium_pool = account_data[0].get(
                'account') if account_data else None

            if not token_mint:
                return None

            return {
                'strategy': 'graduation',
                'type': 'token_graduation',
                'token_pair': ('SOL', token_mint),
                'token_mint': token_mint,
                'raydium_pool': raydium_pool,
                'trigger_data': {
                    'platform': 'pump_fun' if '39azUYFW' in str(event) else 'moonshot',
                    'token_mint': token_mint,
                    'raydium_pool': raydium_pool,
                    'timestamp': event.get('timestamp', time.time())
                },
                'expected_profit_sol': 0.005,
                'description': f"Token graduation detected: {token_mint[:8]}"
            }
        except Exception as e:
            logger.error(f"Error parsing graduation event: {e}")
            return None

    # FIX 129: Helper method for parsing TRANSFER events (detect depeg signals)
    def _parse_transfer_event(
            self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            token_transfers = event.get('tokenTransfers', [])
            if not token_transfers:
                return None

            transfer_data = token_transfers[0]
            mint = transfer_data.get('mint')
            amount = float(transfer_data.get('tokenAmount', 0))

            if mint in WebhookConfig.LST_ADDRESSES and amount > 10000:
                return {
                    'strategy': 'lst_depeg',
                    'type': 'large_transfer_signal',
                    'token_mint': mint,
                    'amount': amount,
                    'trigger_immediate_scan': True,
                    'description': f"Large transfer: {amount:.2f} of {mint[:8]}... (triggering scan)"
                }
        except Exception as e:
            logger.error(f"Error parsing transfer event: {e}")
        return None
