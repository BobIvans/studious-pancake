from __future__ import annotations
from dotenv import load_dotenv

load_dotenv(override=False)  # FIX 128: Allow Docker env overrides
import orjson
import asyncio
import aiohttp
import time
import logging

logger = logging.getLogger(__name__)
import random
import os
import stat
import pathlib
import base64
import itertools
import struct
import hashlib
import re
import socket
import sys
import urllib.parse
from decimal import Decimal
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any, Callable, Set
import resource
from solders.pubkey import Pubkey
from spl.token.instructions import get_associated_token_address
from spl.token.constants import TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID

# ── Этап 3: Prometheus Metrics ─────────────────────────────────────────
from prometheus_client import Counter, Gauge, start_http_server

PROMETHEUS_VIRTUAL_BALANCE = Gauge("marginfy_virtual_balance_sol", "Bot virtual balance in SOL")
PROMETHEUS_TRADES = Counter("marginfy_trades_executed_total", "Total executed trades")
PROMETHEUS_SIM_FAILS = Counter("marginfy_sim_fails_total", "Total simulation failures")


try:
    # Увеличиваем лимит открытых файлов до максимума (65535)
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    target_limit = min(65535, hard) if hard != resource.RLIM_INFINITY else 65535
    resource.setrlimit(resource.RLIMIT_NOFILE, (target_limit, hard))
    logging.info(f"🚀 Системные лимиты подняты: {soft} -> {target_limit}")
except Exception as e:
    logging.warning(
        f"⚠️ Не удалось поднять лимиты (попробуй запустить 'ulimit -n 65535' в терминале): {e}"
    )
import glob
import gc
import shutil
import psutil  # FIX 161: Make dead dependency useful
import tracemalloc  # FIX 161: Enable built-in memory tracker
tracemalloc.start(25)  # Stack depth for allocation tracking — 25 frames

gc.set_threshold(7000, 10, 10)  # Less frequent GC to avoid freezing hot loops


# ============================================================================
# GLOBAL NORMALIZATION HELPER: Convert profit of any token to SOL equivalent
# before calculating Jito tips.  This prevents the "Cross-Currency Tip Suicide"
# where a profit of 5 USDC is interpreted as 5 SOL and the bot overpays tips.
# ============================================================================
def guaranteed_quote_out_amount(quote: Dict[str, Any]) -> int:
    """Return the guaranteed output amount from a quote payload."""
    if not quote:
        return 0

    if "otherAmountThreshold" in quote:
        return int(quote["otherAmountThreshold"])
    if "outAmount" in quote:
        return int(quote["outAmount"])
    if "out_amount" in quote:
        return int(quote["out_amount"])
    return 0


def normalize_profit_to_sol(
    profit_raw: float,
    target_mint_str: str,
    price_matrix: Dict[str, tuple],
    sol_price_usd: float = None,
) -> float:
    """
    Convert profit denominated in any token to SOL equivalent.

    Args:
        profit_raw: Raw profit in the target token's native units (not lamports).
                    E.g. for USDC this would be USDC amount (not micro-USDC).
        target_mint_str: String Pubkey of the profit token mint.
        price_matrix: Global price dict mapping mint_str -> (price_usd, timestamp).
        sol_price_usd: Fallback SOL price if not in price_matrix.

    Returns:
        Profit expressed in SOL (native units, not lamports).
    """
    sol_mint_str = "So11111111111111111111111111111111111111112"
    usdc_mint_str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

    # Get SOL price from matrix
    sol_entry = price_matrix.get(sol_mint_str)
    if sol_entry:
        sol_price_usd = sol_entry[0]

    # If profit is already in SOL, return as-is
    if target_mint_str == sol_mint_str:
        return profit_raw

    # If profit is in USDC (6 decimals), convert via USD
    # Fail-Closed: require SOL price for conversion
    if target_mint_str == usdc_mint_str:
        if sol_price_usd is None:
            logger.warning(
                f"🚫 normalize_profit_to_sol: no SOL price for USDC route — cannot verify profitability"
            )
            return None
        return profit_raw / sol_price_usd

    # For any other token: get its USD price and convert
    token_entry = price_matrix.get(target_mint_str)
    if token_entry and token_entry[0] > 0:
        token_price_usd = token_entry[0]
        if sol_price_usd is None:
            logger.warning(
                f"🚫 normalize_profit_to_sol: no SOL price for {target_mint_str[:8]} route — cannot verify profitability"
            )
            return None
        return (profit_raw * token_price_usd) / sol_price_usd

    # Fallback: Fail-Closed - cannot convert cross-currency without price feed
    # Log a warning and return None to signal failure
    logger.warning(
        f"🚫 normalize_profit_to_sol: no price for {target_mint_str[:8]} — cannot verify profitability"
    )
    return None  # Fail-Closed: abort trade when conversion impossible


# ULTRA ARB MASTER - Unified Shared State (Imported from src.ingest.shared_state)
KEYPAIR = None  # Fix 81: memory-mapped wallet - never read disk during arb
_QUOTE_TASKS: Dict[str, asyncio.Task] = {}  # Fix 84: RPS shield - task-based dedup Jupiter requests
_QUOTE_TASKS_LOCK = asyncio.Lock()
# FIX 293: RAM quote cache with 800ms TTL (2 Solana slots) to eliminate duplicate HTTP requests
_QUOTE_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_QUOTE_CACHE_LOCK = asyncio.Lock()
LAST_SIGNAL_TIME: Dict[str, float] = {}  # Fix 88: per-pair 400ms cooldown (1 slot)
STRATEGY_FAILURES: Dict[str, int] = {}  # Fix 90: reputation circuit breaker
STRATEGY_DISABLED_UNTIL: Dict[str, float] = {}

# ── Fix 2 (Reputation Guard): Pair-level consecutive failure tracking ──────
# Если конкретная пара (напр. SOL/jitoSOL) выдает 3 ошибки Slippage подряд,
# отправляем пару в бан (cooldown) на 600 секунд. Это сохраняет репутацию
# кошелька перед Jito и предотвращает сжигание газа на «высушенных» пулах.
PAIR_COOLDOWN_SECONDS: int = 600
# ────────────────────────────────────────────────────────────────────────────


# Fix 1 (wSOL Death Spiral): Timestamp of last atomic wSOL CloseAccount.
# When build_native_flashloan_tx closes wSOL + recreates ATA before the Jito tip,
# this is set to time.time(). The wallet_balance_listener skips its own standalone
# wSOL close for WSOL_CLOSE_COOLDOWN seconds after an atomic close.
WSOL_JUST_CLOSED_ATOMICALLY: float = 0.0
WSOL_CLOSE_COOLDOWN: float = 60.0  # seconds — any recent atomic close is authoritative

# Phase 19 T2: Deferred refund queue for timed-out bundles
# Place bundle here instead of instantly refunding virtual_balance.
# The balance_reconciler (runs every 30s) catches late landings.
RECENTLY_TIMED_OUT_BUNDLES: Dict[str, dict] = {}

# Import Jito client
try:
    from src.ingest.jito_bundle_client import JitoBundleClient
    from src.ingest.jito_bundle_handler import _set_global_price_matrix
    from src.ingest.jito_manager import JitoBiddingManager
    from src.ingest.jito_executor import JitoExecutor
    from src.ingest.jito_shotgun import JitoShotgun  # FIX 131

    JITO_AVAILABLE = True
except ImportError:
    class JitoShotgun:
        def __init__(self, session):
            pass

        async def send_to_all_engines(self, *args, **kwargs):
            return {"error": "JitoShotgun unavailable"}

    JITO_AVAILABLE = False
    logger.warning("Jito client not available, falling back to RPC execution")

    class JitoBiddingManager:
        async def update_tip_accounts(self, session):
            return False

        async def poll_tip_floor(self, session):
            pass

        def get_50th_percentile_lamports(self):
            return 10000

        def calculate_blue_ocean_tip(self, *args, **kwargs):
            return 0

        def calculate_optimal_tip(self, *args, **kwargs):
            return 0

        def record_bundle_result(self, *args, **kwargs):
            pass

        def record_trade_result(self, *args, **kwargs):
            pass




from src.ingest.tx_builder import JupiterTxBuilder
from src.ingest.multi_aggregator_client import MultiAggregatorClient
from src.ingest.transaction_prebuilder import TransactionPrebuilder
from src.ingest.multi_rpc_manager import MultiRpcManager, RpcEndpoint
from src.ingest.leader_tracker import LeaderTracker
from src.ingest.execution_router import ExecutionRouter
from src.ingest.blockhash_racing import init_blockhash_racing, get_blockhash_manager
from src.ingest.pre_trade_guard import PreTradeGuard
from src.ingest.arbitrage_scorer import (
    ArbitrageScorer,
    PriorityArbitrageQueue,
    ArbitrageOpportunity,
)

# AI data collection classes - TODO: Implement when needed
from src.ingest.data_aggregator import DataAggregator
from src.ingest.data_collector import DataCollector
from src.ingest.helius_webhook_handler import HeliusWebhookHandler
from src.ingest.optimal_trade_sizer import (
    OptimalTradeSizer,
)
from src.ingest.pyth_core_price_feeder import init_pyth_core_feeder
from src.ingest.helius_sender import HeliusSender, TransactionSender

# ULTRA ARB MASTER - New In-Memory State Modules
from src.ingest.pool_state_manager import PoolStateManager
from src.ingest.event_triggers import EventTriggerEngine, VolatilityWatcher
from src.ingest.liquidator_engine import LiquidationEngine
from src.ingest.dust_sweeper import DustSweeper
from src.ingest.alt_manager import ALTCacheManager
from src.ingest.circuit_breaker import CapitalProtection
import src.ingest.shared_state as shared_state
from src.ingest.shared_state import (
    initialize_shared_state,
    send_telegram_alert,
)

# LST Depeg Flash-Arb modules
from src.ingest.lst_fair_price_monitor import LstFairPriceMonitor, DepegSignal
from src.ingest.lst_route_aggregator import LstRouteAggregator, RouteResult
from src.ingest.flash_simulator import FlashSimulator
from src.ingest.flywheel_scaler import FlywheelScaler
from src.ingest.wrapper_arb import WrapperPegArb

# Dynamic ATA rent: 0.00204 SOL for standard SPL Token, 0.0035 SOL for Token-2022
RENT_SPL_ATA_SOL = 0.00204
RENT_TOKEN2022_SOL = 0.0035
MIN_RESERVE_SOL = 0.005

# ── Phase 49: Async Trade Logger ─────────────────────────────────────────────
# HFT-safe: trade records go into an in-memory queue and are flushed to
# trades.jsonl asynchronously every FLUSH_INTERVAL seconds or on idle.
# No write() call ever blocks the hot loop.

import orjson, time, pathlib

TRADE_LOG_QUEUE: asyncio.Queue | None = None  # Set by start_async_trade_logger()
_async_log_task: asyncio.Task | None = None
FLUSH_INTERVAL = 30  # seconds


class AsyncTradeLogger:
    """Batched async writer for trades.jsonl."""

    def __init__(self, path: str = "trades.jsonl", interval: int = FLUSH_INTERVAL):
        self.path = pathlib.Path(path)
        self.interval = interval
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=10_000)
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None  # captured once in start()

    def start(self) -> None:
        self._task = asyncio.create_task(self._flush_loop())

    async def enqueue(self, record: dict) -> None:
        await self.queue.put(orjson.dumps(record).decode())

    async def _flush_loop(self) -> None:
        self._loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
                break
            except asyncio.TimeoutError:
                pass  # interval elapsed — flush below
            await self._flush_batch()

    async def _flush_batch(self) -> None:
        """Drain everything currently queued and write it in one syscall."""
        lines: list[str] = []
        while not self.queue.empty():
            try:
                lines.append(self.queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if not lines:
            return
        try:

            def _write_logs():
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")

            await self._loop.run_in_executor(None, _write_logs)
        except Exception as exc:
            logger.warning(f"[async-log] flush error: {exc}")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._flush_batch()


async def start_async_trade_logger(path: str = "trades.jsonl") -> AsyncTradeLogger:
    global TRADE_LOG_QUEUE
    logger_obj = AsyncTradeLogger(path=path)
    logger_obj.start()
    TRADE_LOG_QUEUE = logger_obj.queue
    logger.info(f"📝 Async trade logger started → {path}")
    return logger_obj


CORE_GOLDEN_MINTS = {
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
}
EXTENDED_GOLDEN_MINTS = {
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
}
ALL_GOLDEN_MINTS = CORE_GOLDEN_MINTS | EXTENDED_GOLDEN_MINTS

# New MarginFi-compatible arbitrage modules
# TASK 5 — hard-guarded imports: Kamino & Orderbook are DISABLED at import time
# so that changing .env doesn't silently resurrect Red-Ocean scanners

# Webhook trigger for LST scanner

# Create instances
transaction_prebuilder = TransactionPrebuilder()

# Advanced trading components
trade_sizer = OptimalTradeSizer()

# ULTRA ARB MASTER - Initialize In-Memory State Components (commented for minimal startup)
# arbitrage_graph = ArbitrageGraph(max_tokens=25)  # 25 Blue Ocean tokens
# pool_state_manager = PoolStateManager(
#     websocket_url=cfg.WSS_ENDPOINTS[0],
#     pool_addresses=[]
# )
# cex_dex_oracle = CexDexOracle(pool_state_manager=pool_state_manager)

# ULTRA ARB - Initialize Advanced Strategy Engines (commented for minimal startup)
# liquidation_engine = LiquidationEngine(
#     websocket_url=cfg.WSS_ENDPOINTS[0],
#     kamino_program_id="KLend2g3cP87fffoy8q1mQqGKjrxjC8bojiCLxnsfmk",
#     marginfi_program_id="MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA",
#     pool_state_manager=pool_state_manager
# )
# cex_dex_oracle = CexDexOracle(pool_state_manager=pool_state_manager)
# epoch_tracker = EpochTracker(
#     rpc_url=rpc.get_rpc(),
#     session=session
# )

# ULTRA ARB - Market Expansion Engines (commented for minimal startup)
# volatility_watcher = VolatilityWatcher(pool_state_manager)

# ULTRA ARB - Stable×Stable & Lending Rate Engines (commented for minimal startup)

# k_hop_stitcher = KHopStitcher(wallet_keypair=keypair)

# DISABLED for Free Tier: Yellowstone gRPC connects to premium Helius relay
# and will timeout/hang on free tier accounts.
# Global ATA Cache (Phase 48) — синхронизирован с shared_state для DustSweeper
ATA_CACHE = shared_state.ATA_CACHE

# AI-powered trading components (moved to main() function)
# arbitrage_scorer = ArbitrageScorer(session=session, rpc_url=rpc.get_rpc())
# priority_queue = PriorityArbitrageQueue(max_size=50)
data_collector = DataCollector(use_sqlite=True, db_path="bot_history.db")

# Multi-RPC racing configuration
MULTI_RPC_ENABLED = str(os.getenv("MULTI_RPC_ENABLED", "false")).lower() == "true"

# Configure RPC endpoints for racing — built from .env, NEVER fallback to public RPC
# Use MULTI_RPC_WS_1, MULTI_RPC_HTTP_1, etc. or HELIUS_API_KEY to build Helius URLs
multi_rpc_endpoints: List[RpcEndpoint] = []
_rpc_ws_endpoints = [
    os.getenv("MULTI_RPC_WS_1", "").strip(),
    os.getenv("MULTI_RPC_WS_2", "").strip(),
    os.getenv("MULTI_RPC_WS_3", "").strip(),
]
_rpc_http_endpoints = [
    os.getenv("MULTI_RPC_HTTP_1", "").strip(),
    os.getenv("MULTI_RPC_HTTP_2", "").strip(),
    os.getenv("MULTI_RPC_HTTP_3", "").strip(),
]
for i in range(3):
    ws = _rpc_ws_endpoints[i] if i < len(_rpc_ws_endpoints) else ""
    http = _rpc_http_endpoints[i] if i < len(_rpc_http_endpoints) else ""
    if ws and http:
        multi_rpc_endpoints.append(
            RpcEndpoint(f"rpc_node_{i+1}", ws, http, priority=i + 1)
        )
if not multi_rpc_endpoints and MULTI_RPC_ENABLED:
    logger.warning(
        "⚠️ MULTI_RPC endpoints не настроены — укажите MULTI_RPC_WS_1 и MULTI_RPC_HTTP_1 в .env"
    )

# Helius Sender initialization
# helius_sender = HeliusSender(session, cfg.HELIUS_SENDER_URLS, cfg.HELIUS_TIP_ACCOUNTS)
# transaction_sender = TransactionSender(helius_sender)

# Jito sniper components will be initialized later after cfg

from solders.instruction import Instruction, AccountMeta
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import VersionedTransaction
from solders.message import MessageV0
from solders.hash import Hash
from solders.keypair import Keypair
from solders.address_lookup_table_account import AddressLookupTableAccount


# Helper function for safe Pubkey creation
def ensure_pubkey(val) -> Pubkey:
    """Safely convert value to Pubkey, handling both strings and existing Pubkey objects."""
    if isinstance(val, str):
        return Pubkey.from_string(val)
    elif isinstance(val, Pubkey):
        return val
    else:
        raise ValueError(f"Cannot convert {type(val)} to Pubkey")


# Helper function for thread-safe stats updates
async def update_stats(key: str, value: Any = 1):
    """Thread-safe stats update."""
    async with shared_state.stats_lock:
        if (
            isinstance(value, int)
            and key in shared_state.stats
            and isinstance(shared_state.stats[key], int)
        ):
            shared_state.stats[key] += value
        else:
            shared_state.stats[key] = value


from solders.system_program import transfer, TransferParams


import logging
from logging.handlers import RotatingFileHandler
import orjson

# FIX 163: Safe integer parsing for environment configuration
def get_env_int(key: str, default: int) -> int:
    val = os.getenv(key)
    if not val:
        return default
    try:
        return int(val.strip().strip("'\""))
    except ValueError:
        logger.critical(f"❌ CONFIG ERROR: Env variable {key} must be an integer, but got '{val}'. Falling back to default {default}.")
        return default


# FIX 175: Jito Bundle Error classifier for adaptive retries/pauses

def classify_jito_error(error_str: str) -> str:
    err_lower = str(error_str).lower()
    if "blockhash" in err_lower or "expired" in err_lower:
        return "BLOCKHASH_EXPIRED"
    if "account in use" in err_lower or "lock" in err_lower:
        return "ACCOUNT_IN_USE"
    if "simulation failed" in err_lower:
        return "SIMULATION_FAILED"
    if "too large" in err_lower:
        return "BUNDLE_TOO_LARGE"
    return "UNKNOWN"


class JsonFormatter(logging.Formatter):
    """Сериализатор логов в структурированный JSON для Grafana Loki/ELK."""
    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage()
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return orjson.dumps(log_data).decode("utf-8")

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

stdout_handler = logging.StreamHandler()
stdout_handler.setFormatter(JsonFormatter())
root_logger.addHandler(stdout_handler)

try:
    os.makedirs("logs", exist_ok=True)
    file_handler = RotatingFileHandler(
        "logs/bot-start.log",
        maxBytes=50 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8"
    )
    file_handler.setFormatter(JsonFormatter())
    root_logger.addHandler(file_handler)
except Exception as log_file_err:
    print(f"Failed to initialize rotating file handler: {log_file_err}")

logger = logging.getLogger("ArbBot")

# FIXED: Подключение автоматического Telegram-обработчика для всех CRITICAL ошибок системы
try:
    from src.ingest.shared_state import TelegramAlertHandler
    tg_handler = TelegramAlertHandler()
    tg_handler.setLevel(logging.CRITICAL)
    logging.getLogger().addHandler(tg_handler)
    logger.info("📡 Automated Telegram Alert Handler successfully attached to root logger")
except Exception as tg_init_err:
    logger.warning(f"Failed to attach Telegram Alert Handler: {tg_init_err}")


def redact_url(url: str) -> str:
    """P0-4.2a: Redact API keys from URLs for safe logging.
    Replaces api-key, apikey, token query params with [REDACTED].
    """
    if not url:
        return url
    try:
        parsed = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        redacted = False
        for sensitive_key in {"api-key", "apikey", "api_key", "token", "key"}:
            if sensitive_key in query_params:
                query_params[sensitive_key] = ["[REDACTED]"]
                redacted = True
        if redacted:
            new_query = urllib.parse.urlencode(query_params, doseq=True)
            return urllib.parse.urlunparse(
                (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment)
            )
        return url
    except Exception:
        return url


def clean_rpc_urls(env_string: str, is_helius: bool = False) -> List[str]:
    """Железобетонная очистка ссылок и ключей от любого мусора"""
    if not env_string:
        return []

    # Заменяем возможные переносы строк и другие разделители на запятые
    env_string = env_string.replace("\n", ",").replace("\r", ",").replace(";", ",")

    valid_urls = []
    for part in env_string.split(","):
        # Очищаем от пробелов, табов, кавычек одинарных и двойных
        clean_part = part.strip(" \t\n\r\"'")

        if not clean_part:
            continue

        if is_helius:
            # Если это уже готовая ссылка
            if clean_part.startswith("http"):
                valid_urls.append(clean_part)
            # Если это просто ключ (набор букв и цифр)
            else:
                valid_urls.append(
                    f"https://mainnet.helius-rpc.com/?api-key={clean_part}"
                )
        else:
            if clean_part.startswith("http"):
                valid_urls.append(clean_part)

    return valid_urls


async def check_time_sync(session, rpc_url):
    """
    Check time sync between local machine and RPC node.
    Critical for Jito bundles to avoid BlockhashNotFound/Transaction too old.
    """
    import time
    from email.utils import parsedate_to_datetime

    start = time.time()
    try:
        # Use getHealth or a simple getSlot to check server time in headers
        import src.ingest.shared_state as shared_state
        async with shared_state.rpc_limiter:
            async with session.post(
                rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": "getSlot"}, timeout=2.0
            ) as resp:
                pass
            latency = (time.time() - start) / 2
            server_date_str = resp.headers.get("Date")
            if server_date_str:
                server_time = parsedate_to_datetime(server_date_str).timestamp()
                # Subtract latency to get estimated server time at the moment of request
                local_time = time.time() - latency
                diff = abs(local_time - server_time)

                if diff > 2.0:
                    logger.critical(
                        f"🚨 CRITICAL: Time desync detected! Difference: {diff*1000:.0f}ms. Jito will reject bundles (BlockhashNotFound/AUTH_TIMESTAMP_EXPIRED)."
                    )
                    logger.warning(
                        "👉 Install chrony for HFT-grade time sync: sudo apt-get install chrony && sudo nano /etc/chrony/chrony.conf"
                    )
                else:
                    logger.info(
                        f"⏱️ Time sync OK: network latency {latency*1000:.1f}ms, drift {diff*1000:.1f}ms (<200ms HFT threshold). Ready for Jito bundles."
                    )
            else:
                logger.info(
                    f"⏱️ Сетевая задержка: {latency*1000:.2f}ms. (Сервер не прислал заголовок Date)"
                )
    except Exception as e:
        logger.warning(f"⚠️ Не удалось проверить синхронизацию времени: {e}")


# =============================================================================
# ATA Warm-Up (ATA Ghosting trap — TASK 1)
# =============================================================================
# Maps each golden mint to the correct token program (SPL vs Token-2022).
_GOLDEN_ATA_MINTS: Dict[str, str] = {
    "So11111111111111111111111111111111111111112": str(TOKEN_PROGRAM_ID),  # wSOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": str(TOKEN_PROGRAM_ID),  # USDC
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn": str(TOKEN_PROGRAM_ID),  # jitoSOL
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So": str(TOKEN_PROGRAM_ID),  # mSOL
    "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm": str(TOKEN_PROGRAM_ID),  # INF
}


async def warmup_golden_atas(
    session: aiohttp.ClientSession, rpc_url: str, wallet_pubkey: Pubkey
) -> None:
    """Pre-create (or confirm existence of) all golden ATA accounts at bot startup.

    This is the ATA Ghosting fix: creating an ATA during an arbitrage trade costs
    15 000–30 000 CU and ~50 ms of latency.  By pre-warming them once at startup
    we remove that cost from the hot-path entirely.

    The function is idempotent — calling it repeatedly is safe because
    ``create_associated_token_account`` is a no-op when the ATA already exists.
    """
    from spl.token.instructions import create_associated_token_account as _create_ata

    if not rpc_url:
        logger.warning("warmup_golden_atas: no RPC URL — skipping")
        return

    for mint_str, program_id_str in _GOLDEN_ATA_MINTS.items():
        mint_pk = Pubkey.from_string(mint_str)
        program_id = Pubkey.from_string(program_id_str)
        ata = get_associated_token_address(wallet_pubkey, mint_pk, token_program_id=program_id)
        ata_str = str(ata)

        # Check on-chain existence via getAccountInfo
        exists = False
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [ata_str, {"encoding": "base64"}],
            }
            timeout = aiohttp.ClientTimeout(total=3.0)
            async with session.post(rpc_url, json=payload, timeout=timeout) as resp:
                if resp.status == 200:
                    data = orjson.loads(await resp.read())
                    result = data.get("result", {})
                    value = result.get("value")
                    exists = value is not None and value != {"data": None}
        except Exception as exc:
            logger.debug(
                f"warmup_golden_atas: getAccountInfo failed for {mint_str[:8]} — assuming missing: {exc}"
            )

        if not exists:
            try:
                create_ix = _create_ata(
                    payer=wallet_pubkey,
                    owner=wallet_pubkey,
                    mint=mint_pk,
                    token_program_id=program_id,
                )
                # Send as a simple standalone transaction (no Jito needed — low urgency)
                _bh_payload = {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "getLatestBlockhash",
                    "params": [{"commitment": "confirmed"}],
                }
                import src.ingest.shared_state as shared_state
                async with shared_state.rpc_limiter:
                    async with session.post(
                        rpc_url, json=_bh_payload, timeout=aiohttp.ClientTimeout(total=3.0)
                    ) as bh_resp:
                        pass
                    bh_data = await bh_resp.json()
                    recent_bh = Hash.from_string(
                        bh_data["result"]["value"]["blockhash"]
                    )

                from solders.message import MessageV0
                from solders.transaction import VersionedTransaction

                msg = MessageV0.try_compile(
                    payer=wallet_pubkey,
                    instructions=[create_ix],
                    address_lookup_table_accounts=[],
                    recent_blockhash=recent_bh,
                )
                warmup_tx = VersionedTransaction(msg, [KEYPAIR])
                warmup_b64 = base64.b64encode(bytes(warmup_tx)).decode("ascii")
                import src.ingest.shared_state as shared_state
                async with shared_state.rpc_limiter:
                    async with session.post(
                        rpc_url,
                        json={
                            "jsonrpc": "2.0",
                            "id": 3,
                            "method": "sendTransaction",
                            "params": [warmup_b64, {"encoding": "base64"}],
                        },
                        timeout=aiohttp.ClientTimeout(total=10.0),
                    ) as send_resp:
                        pass
                    if send_resp.status == 200:
                        sig = (await send_resp.json()).get("result", "?")
                        logger.info(
                            f"🔥 ATA warmup CREATED: {mint_str[:8]} → {ata_str[:8]}  sig={str(sig)[:12]}"
                        )
                        # Cache the newly created ATA so the hot-path doesn't deduct phantom rent.
                        import src.ingest.shared_state as shared_state
                        await shared_state.add_to_ata_cache(ata_str)
                    else:
                        txt = await send_resp.text()
                        logger.warning(
                            f"ATA warmup create send failed ({send_resp.status}): {txt}"
                        )
            except Exception as exc:
                logger.warning(f"ATA warmup create failed for {mint_str[:8]}: {exc}")
        else:
            logger.debug(
                f"✅ ATA warmup: {mint_str[:8]} already exists → {ata_str[:8]}"
            )
            # Cache the existing ATA so the hot-path doesn't deduct phantom rent.
            import src.ingest.shared_state as shared_state
            await shared_state.add_to_ata_cache(ata_str)


def validate_marginfi_account(cfg: Config) -> bool:
    """Fix 46: .env MARGINFI_ACCOUNT sanitization (must be a valid 32-44 char Base58 Pubkey)."""
    acct = cfg.MARGINFI_ACCOUNT_PUBKEY.strip() if cfg.MARGINFI_ACCOUNT_PUBKEY else ""
    if not acct:
        logger.critical(
            "CRITICAL: MarginFi Account not found. Run MarginFi deposit first."
        )
        return False
    if not re.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", acct):
        logger.critical(
            f"CRITICAL: MARGINFI_ACCOUNT has invalid format ({len(acct)} chars). "
            "Must be a valid Base58 Solana pubkey (32-44 alphanumeric chars, no 0/O/I/l). "
            "Run MarginFi deposit first."
        )
        return False
    return True


async def check_marginfi_health_factor(
    session, rpc_url, marginfi_account_pubkey: str
) -> Optional[float]:
    """БЛОК 14: Fetch and parse MarginFi account health factor via on-chain data.

    Parses the Anchor-serialized MarginfiAccount data layout to verify:
    - Account exists on-chain
    - Account owner is the MarginFi program
    - Account is initialized (is_initialized == 1)

    Returns:
        1.0 if account is structurally valid and ready for flash loans.
        0.0 if account is missing, wrong owner, or uninitialized -> triggers sys.exit(1).
        None if RPC request itself failed (transient error, caller may retry).
    """
    MARGINFI_PROGRAM_ID = "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"
    try:
        health_check_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getAccountInfo",
            "params": [marginfi_account_pubkey, {"encoding": "base64"}],
        }
        import src.ingest.shared_state as shared_state
        async with shared_state.rpc_limiter:
            async with session.post(
                rpc_url, json=health_check_payload, timeout=aiohttp.ClientTimeout(total=5.0)
            ) as resp:
                pass
            if resp.status != 200:
                logger.warning(f"Health-factor RPC error: HTTP {resp.status}")
                return None

            data = orjson.loads(await resp.read())
            result = data.get("result", {})
            value = result.get("value")

            if not value:
                logger.critical(
                    f"🛑 БЛОК 14: MarginFi account {marginfi_account_pubkey[:8]}... NOT FOUND on-chain. "
                    "Account may be uninitialized or closed. Run MarginFi deposit first."
                )
                return 0.0

            # ── Check 1: Owner must be MarginFi program ────────────────────────────
            owner = value.get("owner", "")
            if owner != MARGINFI_PROGRAM_ID:
                logger.critical(
                    f"🛑 БЛОК 14: Account owner is {owner[:16]}..., not MarginFi program. "
                    "Invalid MarginFi account address provided in .env MARGINFI_ACCOUNT."
                )
                return 0.0

            # ── Check 2: Account data must be present and parseable ────────────────
            account_data_b64 = value.get("data", [""])[0]
            if not account_data_b64:
                logger.critical(
                    "🛑 БЛОК 14: MarginFi account has no data (uninitialized/empty)."
                )
                return 0.0

            import base64
            raw = base64.b64decode(account_data_b64)

            # ── Check 3: Minimum data length (8 discriminator + 3*32 pubkeys + 1 flag) ──
            if len(raw) < 105:
                logger.critical(
                    f"🛑 БЛОК 14: MarginFi account data too short ({len(raw)} bytes). "
                    "Expected at least 105 bytes for a valid MarginfiAccount."
                )
                return 0.0

            # ── Check 4: Anchor discriminator validation ───────────────────────────
            # MarginfiAccount discriminator = sha256("account:MarginfiAccount")[:8]
            _expected_disc = hashlib.sha256(b"account:MarginfiAccount").digest()[:8]
            if raw[:8] != _expected_disc:
                # Also try LendingAccount (alternative naming in older versions)
                _alt_disc = hashlib.sha256(b"account:LendingAccount").digest()[:8]
                if raw[:8] != _alt_disc:
                    logger.warning(
                        f"⚠️ БЛОК 14: MarginFi account discriminator mismatch. "
                        f"Got {raw[:8].hex()}, expected MarginfiAccount. Proceeding with caution."
                    )
                else:
                    logger.debug("✅ БЛОК 14: Account discriminator matches LendingAccount (legacy naming)")
            else:
                logger.debug("✅ БЛОК 14: Account discriminator matches MarginfiAccount")

            # ── Check 5: is_initialized flag ────────────────────────────────────────
            is_initialized = raw[104]
            if is_initialized != 1:
                logger.critical(
                    f"🛑 БЛОК 14: MarginFi account is NOT initialized (flag={is_initialized}). "
                    "Deposit funds via app.marginfi.vi first."
                )
                return 0.0

            # FIX 183: Financial safety check (Reject starting with active MarginFi debts)
            if len(raw) >= 116:
                balance_count = struct.unpack("<I", raw[112:116])[0]
                if balance_count > 0:
                    logger.critical(
                        f"🛑 БЛОК 14 (КРИТИЧЕСКИЙ ФИНАНСОВЫЙ РИСК): MarginFi account has {balance_count} active debts! "
                        "Trading blocked to prevent forced account liquidation during flashloans."
                    )
                    return 0.0

            logger.info(
                f"✅ БЛОК 14: MarginFi account validated — initialized, correct owner, valid structure. "
                "Ready for flash loan trading."
            )
            return 1.0

    except Exception as e:
        logger.warning(f"БЛОК 14: Health-factor fetch failed: {e}")
    return None


@dataclass
class Config:
    WALLET_PATH: str = os.getenv("WALLET_PATH", "./wallet.json")

    HELIUS_GATEKEEPER_URL: str = os.getenv("HELIUS_GATEKEEPER_URL", "")
    HELIUS_API_KEY: str = os.getenv("HELIUS_API_KEY", "")
    WEBHOOK_PORT: int = get_env_int("WEBHOOK_PORT", 3000)
    HELIUS_WEBHOOK_ENABLED: bool = (
        str(os.getenv("HELIUS_WEBHOOK_ENABLED", "true")).lower() == "true"
    )

    # Helius Sender Configuration
    HELIUS_SENDER_URLS: List[str] = field(
        default_factory=lambda: [
            os.getenv(
                "HELIUS_SENDER_URL", "https://mainnet.helius-rpc.com/?api-key=YOUR_KEY"
            ),
        ]
    )
    HELIUS_TIP_ACCOUNTS: List[str] = field(
        default_factory=lambda: []
    )
    # ⚠️ FALLBACK: Jito rotates tip accounts regularly. Always use dynamic fetch_tip_accounts().
    # See: https://mainnet.block-engine.jito.wtf/api/v1/bundles/tip_accounts

    # Multi-RPC Racing Configuration
    MULTI_RPC_ENABLED: bool = (
        str(os.getenv("MULTI_RPC_ENABLED", "true")).lower() == "true"
    )
    MULTI_RPC_ENDPOINTS: List[str] = field(
        default_factory=lambda: [
            u
            for u in [
                os.getenv("MULTI_RPC_1", ""),
                os.getenv("MULTI_RPC_2", ""),
                os.getenv("MULTI_RPC_3", ""),
            ]
            if u
        ]
    )

    # Jito Sniper Configuration
    JITO_SNIPER_ENABLED: bool = (
        str(os.getenv("JITO_SNIPER_ENABLED", "false")).lower() == "true"
    )
    JITO_TIP_PERCENTILE: float = float(os.getenv("JITO_TIP_PERCENTILE", "75.0"))
    JITO_MIN_TIP_LAMPORTS: int = get_env_int("JITO_MIN_TIP_LAMPORTS", 10000)
    TIP_MULTIPLIER: float = float(os.getenv("TIP_MULTIPLIER", "1.1"))
    MAX_PRIORITY_FEE_SOL: float = float(os.getenv("MAX_PRIORITY_FEE_SOL", "0.00005"))
    LEADER_FETCH_INTERVAL: int = get_env_int("LEADER_FETCH_INTERVAL", 600000)
    STRICT_JITO_MODE: bool = (
        str(os.getenv("STRICT_JITO_MODE", "true")).lower() == "true"
    )  # Enforce Jito execution for capital protection

    # RPC Multiplexing Configuration
    WSS_ENDPOINTS: List[str] = field(
        default_factory=lambda: [
            u
            for u in [
                os.getenv("WSS_ENDPOINT_1", ""),
                os.getenv("WSS_ENDPOINT_2", ""),
                os.getenv("WSS_ENDPOINT_3", ""),
                os.getenv("WSS_ENDPOINT_4", ""),
            ]
            if u
        ]
    )

    # Jito Bundle Configuration
    # Phase 49: All 4 regions in shotgun approach for maximum bundle propagation
    JITO_ENDPOINTS: List[str] = field(
        default_factory=lambda: [
            u
            for u in (
                [os.getenv("JITO_BLOCK_ENGINE_URL", "").strip()]
                if os.getenv("JITO_BLOCK_ENGINE_URL", "").strip()
                else [
                    "https://frankfurt.mainnet.block-engine.jito.wtf/api/v1/bundles",
                    "https://amsterdam.mainnet.block-engine.jito.wtf/api/v1/bundles",
                    "https://ny.mainnet.block-engine.jito.wtf/api/v1/bundles",
                    "https://tokyo.mainnet.block-engine.jito.wtf/api/v1/bundles",
                ]
            )
            if u  # filter out empty strings
        ]
    )
    JITO_AUTH_KEY: str = os.getenv("JITO_AUTH_KEY", "")
    JITO_TIP_PERCENT: float = float(
        os.getenv("JITO_TIP_PERCENT", "0.6")
    )  # 60% of profit
    # Global Production Settings
    JITO_TIP_STRATEGY: str = os.getenv(
        "JITO_TIP_STRATEGY", "40%_OF_NET"
    )  # Always relative to net profit

    # MEV Execution Thresholds
    MIN_PROFIT_SOL: float = float(
        os.getenv("MIN_PROFIT_SOL", "0.0001")
    )  # Minimum 0.0001 SOL profit
    MAX_TIP_SOL: float = float(os.getenv("MAX_TIP_SOL", "0.0005"))

    HELIUS_URLS: List[str] = field(
        default_factory=lambda: [
            u
            for u in [
                os.getenv("HELIUS_GATEKEEPER_URL", "").strip().strip("'\\\""),
                os.getenv("RPC_URL_1", "").strip().strip("'\\\""),
                os.getenv("RPC_URL", "").strip().strip("'\\\""),
            ]
            if u
        ]
    )

    QUICKNODE_URLS: List[str] = field(
        default_factory=lambda: [
            u
            for u in [
                *(os.getenv(f"QUICKNODE_URL_{i}") for i in range(1, 10)),
                os.getenv("RPC_URL_1", "").strip().strip("'\\\""),
                os.getenv("RPC_URL", "").strip().strip("'\\\""),
            ]
            if u and u.strip()
        ]
    )

    JUPITER_API_KEY: str = os.getenv("JUPITER_API_KEY", "")

    WORKER_COUNT: int = get_env_int("WEBHOOK_WORKER_COUNT", 1)  # FIX 163: Use safe env parser
    BATCH_SIZE: int = get_env_int("BATCH_SIZE", 20)
    BG_FETCH_INTERVAL: float = float(os.getenv("BG_FETCH_INTERVAL", "2.0"))
    SIMULATE_BEFORE_EXECUTE: bool = (
        str(os.getenv("SIMULATE_BEFORE_EXECUTE", "True")).lower() == "true"
    )
    DEXSCREENER_URL: str = os.getenv(
        "DEXSCREENER_URL", "https://api.dexscreener.com/token-profiles/latest/v1"
    )
    DEXSCREENER_RPS: int = get_env_int("DEXSCREENER_RPS", 1)
    VELORA_QUOTE_URL: str = os.getenv(
        "VELORA_QUOTE_URL", "https://api.paraswap.io/prices"
    )
    SCAN_INTERVAL: float = float(os.getenv("SCAN_INTERVAL", "3.0"))

    TRADE_SIZE_PCT: float = float(os.getenv("TRADE_SIZE_PCT", 1.0))
    MIN_RESERVE_SOL: float = 0.005  # Phase 49: minimum gas reserve (confirmed by spec)
    MIN_NET_PROFIT_PCT: float = float(os.getenv("MIN_NET_PROFIT_PCT", 0.005))
    MAX_DRAWDOWN_SOL: float = float(os.getenv("MAX_DRAWDOWN_SOL", 0.005))  # Phase 10: 33% of 0.015 SOL survival balance

    JUP_RPS: int = get_env_int("JUPITER_QUOTE_RPS", 1)

    JUPITER_PRICE_URL: str = os.getenv(
        "JUPITER_PRICE_URL", "https://api.jup.ag/price/v2"
    )
    JUPITER_QUOTE_URL: str = os.getenv(
        "JUPITER_QUOTE_API", "https://api.jup.ag/swap/v1/quote"
    )
    BASE_TIP_LAMPORTS: int = get_env_int("BASE_TIP_LAMPORTS", 10000)
    FLASH_FEE_PCT: float = float(os.getenv("FLASH_FEE_PCT", "0.0"))

    MARGINFI_ACCOUNT_PUBKEY: str = os.getenv("MARGINFI_ACCOUNT", "")

    # Arbitrage Engine Settings
    MIN_PROFIT_THRESHOLD_SOL: float = float(
        os.getenv("MIN_PROFIT_THRESHOLD_SOL", "0.0005")  # 500 micro-SOL for micro-balance
    )
    MIN_PROFIT_THRESHOLD_USDC: float = float(
        os.getenv("MIN_PROFIT_THRESHOLD_USDC", "0.01")
    )
    ARBITRAGE_TIMEOUT_SECONDS: int = get_env_int("ARBITRAGE_TIMEOUT_SECONDS", 30)
    MAX_CONCURRENT_ARBITRAGES: int = get_env_int("MAX_CONCURRENT_ARBITRAGES", 3)

    SLIPPAGE_BPS: int = get_env_int("SLIPPAGE_BPS", 15)
    BASE_FEE: float = 0.000005
    PRIORITY_FEE: float = 0.00005
    # ATA_FEE removed: rent_fee_sol is already computed dynamically from ATA_CACHE
    # in build_native_flashloan_tx. Adding a static ATA_FEE here caused a phantom
    # ~27% capital drain on paper (double-counting rent on every trade).

    # Arbitrage Filters
    ARBITRAGE_FILTER_MIN_PROFIT_SOL: float = float(
        os.getenv("ARBITRAGE_FILTER_MIN_PROFIT_SOL", "0.0001")
    )  # Broad: allow low profit trades
    ARBITRAGE_FILTER_MAX_SLIPPAGE_BPS: int = int(
        os.getenv("ARBITRAGE_FILTER_MAX_SLIPPAGE_BPS", "50")
    )  # Broad: up to 50 BPS slippage
    ARBITRAGE_FILTER_MIN_LIQUIDITY_LAMPORTS: int = int(
        os.getenv("ARBITRAGE_FILTER_MIN_LIQUIDITY_LAMPORTS", "1000000")
    )  # 0.01 SOL liquidity

    # === LST Depeg Flash-Arb Strategy ===
    # ⚠️ PLACEHOLDER STRATEGIES DISABLED FOR SAFETY - Need full implementation before enabling
    LST_DEPEG_ENABLED: bool = (
        str(os.getenv("LST_DEPEG_ENABLED", "true")).lower() == "true"
    )  # BLUE OCEAN: LST depeg (0.017 SOL start)

    # FIX 202: Повышаем порог депега по умолчанию до 30 BPS для гарантированной окупаемости после вычета всех комиссий
    LST_DEPEG_THRESHOLD_BPS: int = get_env_int("LST_DEPEG_THRESHOLD_BPS", 30)
    FLASH_LOAN_SIZE_SOL: float = float(
        os.getenv("FLASH_LOAN_SIZE_SOL", "0.05")
    )  # Initial: 0.05 SOL (5x leverage is max safe for 0.015 SOL)
    MIN_NET_PROFIT_BUFFER_SOL: float = float(
        os.getenv("MIN_NET_PROFIT_BUFFER_SOL", "0.00005")
    )
    LST_SCAN_INTERVAL: float = float(os.getenv("LST_SCAN_INTERVAL", "3.0"))
    SANCTUM_ROUTER_ENABLED: bool = (
        str(os.getenv("SANCTUM_ROUTER_ENABLED", "true")).lower() == "true"
    )  # BLUE OCEAN: Sanctum for LST instant unstake

    # === New MarginFi-Compatible Arbitrage Strategies ===
    KAMINO_LIQUIDATION_ENABLED: bool = (
        str(os.getenv("KAMINO_LIQUIDATION_ENABLED", "false")).lower() == "true"
    )  # DISABLED: placeholder
    KAMINO_SCAN_INTERVAL: float = float(os.getenv("KAMINO_SCAN_INTERVAL", "5.0"))
    KAMINO_MIN_PROFIT_SOL: float = float(os.getenv("KAMINO_MIN_PROFIT_SOL", "0.001"))

    LST_UNSTAKE_ARB_ENABLED: bool = (
        str(os.getenv("LST_UNSTAKE_ARB_ENABLED", "true")).lower() == "true"
    )  # BLUE OCEAN: LST unstake arb
    LST_UNSTAKE_MIN_DEVIATION_PCT: float = float(
        os.getenv("LST_UNSTAKE_MIN_DEVIATION_PCT", "0.5")
    )
    LST_UNSTAKE_SCAN_INTERVAL: float = float(
        os.getenv("LST_UNSTAKE_SCAN_INTERVAL", "3.0")
    )

    # Fix 35: Hardcode to False to prevent accidental gas leakage from unfinished modules.
    # These .env values are intentionally IGNORED so the bot never boots frozen Red Ocean strategies.
    KAMINO_LIQUIDATION_ENABLED: bool = (
        False  # HARDCODED: unfinished module, .env ignored
    )
    ORDERBOOK_AMM_ENABLED: bool = False  # HARDCODED: unfinished module, .env ignored
    ORDERBOOK_AMM_SCAN_INTERVAL: float = float(
        os.getenv("ORDERBOOK_AMM_SCAN_INTERVAL", "1.0")
    )
    PHOENIX_MARKET_ADDRESS: str = os.getenv("PHOENIX_MARKET_ADDRESS", "")
    RAYDIUM_POOL_ADDRESS: str = os.getenv("RAYDIUM_POOL_ADDRESS", "")

    # Paper Trading Mode — if true, simulates trades without sending real transactions
    PAPER_TRADING_ONLY: bool = (
        str(os.getenv("PAPER_TRADING_ONLY", "false")).lower() == "true"
    )

    # CFG-006: Range validation for critical numeric parameters
    def __post_init__(self):
        assert 0.0 < self.JITO_TIP_PERCENTILE <= 100.0, f"JITO_TIP_PERCENTILE must be strictly greater than 0, got {self.JITO_TIP_PERCENTILE}"
        assert 0.0 < self.TIP_MULTIPLIER <= 5.0, f"TIP_MULTIPLIER must be between 0 and 5, got {self.TIP_MULTIPLIER}"
        assert 0.0 < self.TRADE_SIZE_PCT <= 1.0, f"TRADE_SIZE_PCT must be between 0 and 1, got {self.TRADE_SIZE_PCT}"
        assert 0.0 < self.MAX_PRIORITY_FEE_SOL <= 0.1, f"MAX_PRIORITY_FEE_SOL must be reasonable (< 0.1 SOL), got {self.MAX_PRIORITY_FEE_SOL}"
        assert self.MIN_PROFIT_SOL >= 0.0, f"MIN_PROFIT_SOL must be non-negative, got {self.MIN_PROFIT_SOL}"
        assert self.MAX_TIP_SOL >= 0.0, f"MAX_TIP_SOL must be non-negative, got {self.MAX_TIP_SOL}"
        assert self.SLIPPAGE_BPS > 0, f"SLIPPAGE_BPS must be strictly positive, got {self.SLIPPAGE_BPS}"
        assert self.BASE_TIP_LAMPORTS > 0, f"BASE_TIP_LAMPORTS must be strictly positive, got {self.BASE_TIP_LAMPORTS}"
        assert self.JITO_MIN_TIP_LAMPORTS > 0, f"JITO_MIN_TIP_LAMPORTS must be strictly positive, got {self.JITO_MIN_TIP_LAMPORTS}"


TOKENS = {
    # === GOLDEN FUND: Stables & Yield ===
    "SOL": "So11111111111111111111111111111111111111112",
    "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "PYUSD": "2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo",
    "USDS": "USDSwr9ApdHk5bvJKMjzff41FfhJbZkp9bHqzZdduoP",
    "USDY": "A1KLoBrKBde8Ty9qtNQUtq3C2ortoC3u7twggz7sEto6",
    "USDe": "DEkqHyPN7GMRJ5cArtQFAWefqbZb33Hyf6s5iCwjEonT",
    "sUSDe": "Eh6XEPhSwoLv5wFApukmnaVSHQ6sAnoD9BmgmwQoN2sN",
    "sUSDS": "SKYTAiJRkgexqQqFoqhXdCANyfziwrVrzjhBaCzdbKW",
    "JupUSD": "JuprjznTrTSp2UFa3ZBUFgwdAmtZCq4MQCwysN55USD",
    # === GOLDEN FUND: LSTs ===
    "jitoSOL": "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
    "mSOL": "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",
    "bSOL": "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",
    "INF": "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm",
    "JupSOL": "jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v",
    "hubSOL": "HUBsveNpjo5pWqNkH57QzxjQASdTVXcSK7bVKTSZtcSX",
    "fwdSOL": "cPQPBN7WubB3zyQDpzTK2ormx1BMdAym9xkrYUJsctm",
    "dSOL": "Dso1bDeDjCQxTrWHqUUi63oBvV7Mdm6WaobLbQ7gnPQ",
    "dzSOL": "Gekfj7SL2fVpTDxJZmeC46cTYxinjB6gkAnb6EGT6mnn",
    "psol": "pSo1f9nQXWgXibFtKf7NWYxb5enAM4qfP6UJSiXRQfL",
    "bonkSOL": "BonK1YhkXEGLZzwtcvRTip3gAL9nCeQD7ppZBLXhtTs",
    "cgntSOL": "CgnTSoL3DgY9SFHxcLj6CgCgKKoTBr6tp4CPAEWy25DE",
    "vSOL": "vSoLxydx6akxyMD9XEcPvGYNGq6Nn66oqVb3UkGkei7",
    "compassSOL": "Comp4ssDzXcLeu2MnLuGNNFC4cmLPMng8qWHPvzAMU1h",
    "hSOL": "he1iusmfkpAdwvxLNGV8Y1iSbj4rUy6yMhEA3fotn9A",
    # === BTC Wrappers (Step 5) ===
    "cbBTC": "cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij",
    "wBTC": "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh",
    "tBTC": "6DNSN2BJsaPFdFFc1zP37kkeNe4Usc1Sqkzr9C9vPWcU",
    # === Other Ecosystem Tokens ===
    "BELIEVE": "BLVxek8YMXUQhcKmMvrFTrzh5FXg8ec88Crp6otEaCMf",
    "JUP": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "BONK": "DezXAZ8z7P8gVmFiDQ6cEhPmmF9rj3ZfVGg3LyZ3mTKV",
    "POPCAT": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr",
}

# ============================================================================
# ONE-DIRECTION HELPER: safe bytes works with both str and Pubkey input
# ============================================================================


def _to_pubkey(val):
    """Safely return a Pubkey from either a string or an existing Pubkey."""
    return val if isinstance(val, Pubkey) else Pubkey.from_string(str(val))


def _to_pubkey_bytes(val) -> bytes:
    """Safely convert a Pubkey or address string to 32 raw bytes."""
    return (
        bytes(val) if isinstance(val, Pubkey) else bytes(Pubkey.from_string(str(val)))
    )


# ZERO-STRING HOT LOOP: Pre-cache all token addresses as Pubkey objects
# ============================================================================


# Convert all string addresses to Pubkey objects for HFT performance
def _convert_tokens_to_pubkeys():
    """Convert all string token addresses to Pubkey objects at startup."""
    from solders.pubkey import Pubkey

    global TOKENS

    converted_tokens = {}
    for symbol, address in TOKENS.items():
        if isinstance(address, str):
            try:
                converted_tokens[symbol] = Pubkey.from_string(address)
            except Exception as e:
                logger.warning(f"Invalid token address for {symbol}: {address} - {e}")
                converted_tokens[symbol] = Pubkey.default()
        else:
            converted_tokens[symbol] = address

    TOKENS = converted_tokens
    logger.info(f"✅ Pre-cached {len(TOKENS)} token Pubkey objects for HFT performance")


# ============================================================================
# SELF-HEALING STATE: Emergency balance recovery
# ============================================================================

# Token decimals mapping
TOKEN_DECIMALS = {
    # Golden Fund: Stables
    "So11111111111111111111111111111111111111112": 9,  # SOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 6,  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": 6,  # USDT
    "2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo": 6,  # PYUSD
    "USDSwr9ApdHk5bvJKMjzff41FfhJbZkp9bHqzZdduoP": 6,  # USDS
    "A1KLoBrKBde8Ty9qtNQUtq3C2ortoC3u7twggz7sEto6": 6,  # USDY
    "DEkqHyPN7GMRJ5cArtQFAWefqbZb33Hyf6s5iCwjEonT": 6,  # USDe
    "Eh6XEPhSwoLv5wFApukmnaVSHQ6sAnoD9BmgmwQoN2sN": 18,  # FIX 113: sUSDe 18 decimals
    "SKYTAiJRkgexqQqFoqhXdCANyfziwrVrzjhBaCzdbKW": 6,  # sUSDS
    # Yield Stables (new — 6 decimals)
    "JuprjznTrTSp2UFa3ZBUFgwdAmtZCq4MQCwysN55USD": 6,  # JupUSD
    # Golden Fund: LSTs (9 decimals)
    "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm": 9,  # INF
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn": 9,  # jitoSOL
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So": 9,  # mSOL
    "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1": 9,  # bSOL
    "jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v": 9,  # JupSOL
    "HUBsveNpjo5pWqNkH57QzxjQASdTVXcSK7bVKTSZtcSX": 9,  # hubSOL
    "BonK1YhkXEGLZzwtcvRTip3gAL9nCeQD7ppZBLXhtTs": 9,  # bonkSOL
    "CgnTSoL3DgY9SFHxcLj6CgCgKKoTBr6tp4CPAEWy25DE": 9,  # cgntSOL
    "Gekfj7SL2fVpTDxJZmeC46cTYxinjB6gkAnb6EGT6mnn": 9,  # dzSOL
    "pSo1f9nQXWgXibFtKf7NWYxb5enAM4qfP6UJSiXRQfL": 9,  # psol
    "cPQPBN7WubB3zyQDpzTK2ormx1BMdAym9xkrYUJsctm": 9,  # fwdSOL
    "Dso1bDeDjCQxTrWHqUUi63oBvV7Mdm6WaobLbQ7gnPQ": 9,  # dSOL
    "vSoLxydx6akxyMD9XEcPvGYNGq6Nn66oqVb3UkGkei7": 9,  # vSOL
    "Comp4ssDzXcLeu2MnLuGNNFC4cmLPMng8qWHPvzAMU1h": 9,  # compassSOL
    "he1iusmfkpAdwvxLNGV8Y1iSbj4rUy6yMhEA3fotn9A": 9,  # hSOL
    # BTC Wrappers (8 decimals)
    "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh": 8,  # wBTC (Wormhole)
    "cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij": 8,  # cbBTC (Coinbase)
    "6DNSN2BJsaPFdFFc1zP37kkeNe4Usc1Sqkzr9C9vPWcU": 8,  # tBTC
    # Tier B: Memes
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN": 6,  # JUP
    "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm": 6,  # WIF
    "DezXAZ8z7P8gVmFiDQ6cEhPmmF9rj3ZfVGg3LyZ3mTKV": 5,  # BONK
    "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr": 9,  # POPCAT
}

# Arbitrage Registry for Data Collection Phase
ARBITRAGE_REGISTRY = {
    "stablecoins": [
        {
            "base": "USDC",
            "target": "USDT",
            "description": "USDC/USDT DEX-to-DEX arbitrage",
        },
        {
            "base": "USDC",
            "target": "PYUSD",
            "description": "USDC/PYUSD rate differential on MarginFi/Save pools",
        },
    ],
    "lst_tokens": [
        {
            "base": "SOL",
            "target": "jitoSOL",
            "description": "SOL/jitoSOL MEV rewards distribution arbitrage",
        },
        {
            "base": "SOL",
            "target": "mSOL",
            "description": "SOL/mSOL instant unstake arbitrage on Marinade",
        },
        {
            "base": "SOL",
            "target": "bSOL",
            "description": "SOL/bSOL discount buys on DEX, siphon via aggregators",
        },
        {
            "base": "SOL",
            "target": "JupSOL",
            "description": "SOL/JupSOL Jupiter DAO votes cause price divergence",
        },
        {
            "base": "SOL",
            "target": "compassSOL",
            "description": "SOL/compassSOL APY campaigns arbitrage",
        },
        {
            "base": "SOL",
            "target": "hSOL",
            "description": "SOL/hSOL Helius promotions arbitrage",
        },
        {
            "base": "SOL",
            "target": "fwdSOL",
            "description": "SOL/fwdSOL Forward staking arbitrage",
        },
        {
            "base": "SOL",
            "target": "dSOL",
            "description": "SOL/dSOL Drift staking arbitrage",
        },
        {
            "base": "SOL",
            "target": "hubSOL",
            "description": "SOL/hubSOL SolanaHub staking arbitrage",
        },
        {
            "base": "SOL",
            "target": "dzSOL",
            "description": "SOL/dzSOL DoubleZero staking arbitrage",
        },
        {
            "base": "SOL",
            "target": "vSOL",
            "description": "SOL/vSOL Vector staking arbitrage",
        },
    ],
    "ultra_arb_yield_stables": [
        {
            "base": "sUSDS",
            "target": "USDC",
            "description": "Stable-Yield Accrual Drift: sUSDS vs USDC yield differential",
        },
        {
            "base": "USDY",
            "target": "USDC",
            "description": "Stable-Yield Accrual Drift: USDY vs USDC yield differential",
        },
        {
            "base": "JupUSD",
            "target": "USDC",
            "description": "Stable-Yield Accrual Drift: JupUSD vs USDC yield differential",
        },
    ],
    "ultra_arb_graduation": [
        {
            "base": "SOL",
            "target": "MOONSHOT",
            "description": "Moonshot graduation arbitrage (pre-computed PDA)",
        },
        {
            "base": "SOL",
            "target": "BELIEVE",
            "description": "BelieveApp graduation arbitrage (pre-computed PDA)",
        },
    ],
    "kamino_receipts": [
        {
            "base": "USDC",
            "target": "kUSDC",
            "description": "USDC/kUSDC rate differential between MarginFi and Kamino",
        },
        {
            "base": "USDC",
            "target": "kJLP",
            "description": "USDC/kJLP Jupiter Perps LP value revaluation",
        },
    ],
    "ultra_arb_wrappers": [
        {
            "base": "cbBTC",
            "target": "wBTC",
            "description": "1:1 BTC wrapper peg enforcement",
        },
        {
            "base": "wBTC",
            "target": "tBTC",
            "description": "1:1 BTC wrapper peg enforcement",
        },
        {
            "base": "cbBTC",
            "target": "tBTC",
            "description": "1:1 BTC wrapper peg enforcement",
        },
        {"base": "wETH", "target": "SOL", "description": "ETH wrapper vs native token"},
    ],
    "ultra_arb_depin": [
        {"base": "HNT", "target": "USDC", "description": "DePIN volatility arbitrage"},
        {
            "base": "GRASS",
            "target": "USDC",
            "description": "AI DePIN volatility arbitrage",
        },
        {
            "base": "RENDER",
            "target": "USDC",
            "description": "GPU DePIN volatility arbitrage",
        },
        {
            "base": "MOBILE",
            "target": "USDC",
            "description": "Mobile DePIN volatility arbitrage",
        },
        {
            "base": "HONEY",
            "target": "USDC",
            "description": "Yield DePIN volatility arbitrage",
        },
    ],
    "volatile_governance": [
        {
            "base": "USDC",
            "target": "wBTC",
            "description": "USDC/wBTC BTC movement synch issues between Raydium/Orca",
        },
        {
            "base": "USDC",
            "target": "JUP",
            "description": "USDC/JUP Jupiter monthly unlocks cause dumps on DEX",
        },
        {
            "base": "USDC",
            "target": "BONK",
            "description": "USDC/BONK viral events, price lag between AMM Phoenix CLOB",
        },
        {
            "base": "USDC",
            "target": "ORCA",
            "description": "USDC/ORCA Orca commission changes cause governance volatility",
        },
    ],
}

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

# Marginfi Config - loaded from environment with defaults
MARGINFI_PROGRAM_ID = Pubkey.from_string(
    os.getenv("MARGINFI_PROGRAM_ID", "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA")
)
MARGINFI_GROUP = Pubkey.from_string(
    os.getenv("MARGINFI_GROUP", "4qp6Fx6tnZkY5Wropq9wUYgtFxXKwE6viZxFHg3rdAG8")
)

# ── Task 11: Hardcoded MarginFi Liquidity Vaults (Mainnet) ─────────────────
# In MarginFi v2 liquidity_vault is a standard Token Account, NOT a PDA.
# Using find_program_address("liquidity_vault") generates a FAKE address that the
# smart-contract rejects with ConstraintTokenAccount / AccountNotInitialized.
# These are the real on-chain vault addresses for the two active Mainnet banks.
MARGINFI_LIQUIDITY_VAULTS: Dict[str, str] = {
    # SOL Bank (CCwqExrqLGHtq12X182rFvA4KEDtK13q2E7B3Jp2Cxyj)  →  SOL Liquidity Vault
    "CCwqExrqLGHtq12X182rFvA4KEDtK13q2E7B3Jp2Cxyj": "7uttpzxsHAcX97X5ZwaX8xMpsJc9aKx2V8t4Gf6A43XJ",
    # USDC Bank (2s37akK2eyBbp8DZgCm7RtsaEz8eWhVKGfHGA3cKMEW2)  →  USDC Liquidity Vault
    "2s37akK2eyBbp8DZgCm7RtsaEz8eWhVKGfHGA3cKMEW2": "73zNEAXx8vWeCReEwZgPZteXhH3RTo8gC1vC51g8x7j2",
}


# Helper to derive marginfi PDAs
def get_marginfi_bank_accounts(bank_pubkey: Pubkey):
    def find_pda(seed_str):
        pda, _ = Pubkey.find_program_address(
            [seed_str.encode(), bytes(bank_pubkey)], MARGINFI_PROGRAM_ID
        )
        return pda

    bank_str = str(bank_pubkey)
    # logger.debug(f"DEBUG BANK LOOKUP: '{bank_str}' (len={len(bank_str)})")
    liquidity_vault_str = MARGINFI_LIQUIDITY_VAULTS.get(bank_str)
    if not liquidity_vault_str:
        logger.critical(
            f"🛑 UNKNOWN MARGINFI BANK: {bank_str}\n"
            "liquidity_vault not in MARGINFI_LIQUIDITY_VAULTS map — flash loan cannot proceed."
        )

    return {
        "bank": bank_pubkey,
        # Task 11: liquidity_vault is a real Token Account, NOT derived via PDA
        "liquidity_vault": (
            Pubkey.from_string(liquidity_vault_str) if liquidity_vault_str else None
        ),
        # liquidity_vault_authority IS a PDA — keep find_program_address
        "liquidity_vault_authority": find_pda("liquidity_vault_auth"),
        "insurance_vault": find_pda("insurance_vault"),
        "insurance_vault_authority": find_pda("insurance_vault_auth"),
        "fee_vault": find_pda("fee_vault"),
        "fee_vault_authority": find_pda("fee_vault_auth"),
    }


# MarginFi banks - lazy initialization to avoid import issues
def is_strategy_allowed(strategy: str) -> bool:
    """Fix 90: Jito Reputation Guard - disable after 3 consecutive FlashSimulator fails."""
    if STRATEGY_DISABLED_UNTIL.get(strategy, 0) > time.time():
        return False
    return True


def record_sim_failure(strategy: str):
    STRATEGY_FAILURES[strategy] = STRATEGY_FAILURES.get(strategy, 0) + 1
    if STRATEGY_FAILURES[strategy] >= 3:
        STRATEGY_DISABLED_UNTIL[strategy] = time.time() + 300  # 5 min
        logger.critical(
            f"🚨 REPUTATION BREAKER: {strategy} disabled 5min after 3 sim fails"
        )


def get_marginfi_banks():
    """Get MarginFi bank configurations with lazy initialization."""
    try:
        sol_bank = os.getenv(
            "MARGINFI_SOL_BANK", "CCwqExrqLGHtq12X182rFvA4KEDtK13q2E7B3Jp2Cxyj"
        ).strip()
        # Phase 45: Correct MarginFi USDC bank address (NOT the USDC mint!)
        usdc_bank = os.getenv(
            "MARGINFI_USDC_BANK", "2s37akK2eyBbp8DZgCm7RtsaEz8eWhVKGfHGA3cKMEW2"
        ).strip()
        correct_usdc = "2s37akK2eyBbp8DZgCm7RtsaEz8eWhVKGfHGA3cKMEW2"
        if usdc_bank != correct_usdc:
            logger.warning(
                f"⚠️ Self-healing .env: wrong MARGINFI_USDC_BANK {usdc_bank} -> {correct_usdc}"
            )
            usdc_bank = correct_usdc  # Fix 87: auto-correct in memory

        return {
            "So11111111111111111111111111111111111111112": get_marginfi_bank_accounts(
                Pubkey.from_string(sol_bank)
            ),
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": get_marginfi_bank_accounts(
                Pubkey.from_string(usdc_bank)
            ),
        }
    except Exception as e:
        logger.warning(f"Failed to initialize MarginFi banks: {e}. Using empty dict.")
        return {}


# MARGINFI_BANKS is now defined in shared_state.py to avoid circular imports
from src.ingest.circuit_breaker import CapitalProtection
import src.ingest.shared_state as shared_state

MARGINFI_BANKS = shared_state.MARGINFI_BANKS
shared_state.init_marginfi_banks()

# Discriminators for our flash loan contract
EXECUTE_ARBITRAGE_DISCRIMINATOR = bytes(
    [63, 57, 76, 143, 41, 52, 112, 208]
)  # sha256("global:execute_arbitrage")[:8]

HIGH_TIER_PAIRS = {
    ("SOL", "USDC"),
    ("jitoSOL", "SOL"),
    ("USDC", "SOL"),
    ("SOL", "jitoSOL"),
}
TIER_A_TOKENS = {
    "INF",
    "jitoSOL",
    "mSOL",
    "bSOL",
    "JupSOL",
    "fwdSOL",
    "dSOL",
    "hubSOL",
    "dzSOL",
}
TIER_A_MINTS = {TOKENS[name] for name in TIER_A_TOKENS if name in TOKENS}

price_matrix: Dict[str, tuple] = {}  # (price, timestamp) for freshness TTL
cached_blockhash: Optional[str] = None
cache_time = 0
openocean_banned_until = 0
openocean_ban_time = 60

# Global production settings
MAX_CONCURRENT_TASKS = 1  # Sequential mode to prevent MarginFi account lock


# Fix 3: Silent Exception Swallower - Background task callback for exception logging
def background_task_callback(t: asyncio.Task):
    """Log hidden exceptions in background tasks and prevent silent failures."""
    shared_state.active_tasks.discard(t)
    try:
        t.result()  # Raises exception if task failed
    except asyncio.CancelledError:
        pass  # Task was cancelled, not an error
    except Exception as e:
        logger.error(
            f"💥 Hidden failure in background task ({t.get_name()}): {e}", exc_info=True
        )


TOTAL_FAILED_BUNDLES_IN_A_ROW = 0  # Fix 64: Slippage loop breaker

# Fix 2: MarginFi Flash-Loan Asset Pivot — when StaleOracle is detected,
# flip borrow asset between SOL and USDC for the next trade attempt.
_oracle_stale_hit: bool = False
_oracle_stale_asset_hint: str = "USDC"  # Which asset triggered the stale error

# Fix 6 + 67: Balance Lock Guard — lives in shared_state.py to eliminate
# circular imports with wsol_manager.py. Reference via shared_state module.
# Local aliases are removed; use shared_state._balance_lock_paused directly.


# =============================================================================
# Fix 96: Token-2022 Remaining-Account Error Parser
# =============================================================================
STRATEGY_EXTRA_ACCOUNTS: Dict[str, Set[str]] = (
    {}
)  # auto-discovered extra accounts per strategy/pair


def _extract_pubkey_from_error(error_text: str) -> Optional[str]:
    """Extract a Pubkey from a Solana instruction error string."""
    import re

    # Pattern: "Missing required account X...", "AccountNotFound: X...", "remaining account X"
    patterns = [
        r"Missing required account\s+([1-9A-HJ-NP-Za-km-z]{32,44})",
        r"AccountNotFound:\s*([1-9A-HJ-NP-Za-km-z]{32,44})",
        r"remaining account\s+([1-9A-HJ-NP-Za-km-z]{32,44})",
        r"([1-9A-HJ-NP-Za-km-z]{32,44})",  # bare pubkey fallback
    ]
    for pat in patterns:
        match = re.search(pat, error_text)
        if match:
            return match.group(1)
    return None


EXTRA_ACCOUNTS_FILE = "extra_accounts.json"


def _load_extra_accounts() -> dict:
    """Load extra accounts from JSON file, keyed by strategy_key."""
    try:
        with open(EXTRA_ACCOUNTS_FILE, "r") as f:
            return orjson.loads(f.read())
    except (FileNotFoundError, orjson.JSONDecodeError):
        return {}


def _save_extra_accounts(data: dict) -> None:
    """Save extra accounts to JSON file."""
    with open(EXTRA_ACCOUNTS_FILE, "wb") as f:
        f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2))


def discover_ri_extra_account(error_text: str, strategy_key: str = "default") -> None:
    """Parse a Remaining Account / Missing signature error and cache the pubkey for future injections."""
    pk = _extract_pubkey_from_error(str(error_text) if error_text else "")
    if pk:
        # FIX 179: Prune extra accounts cache if it grows past 200 entries to prevent memory bloat
        existing_set = STRATEGY_EXTRA_ACCOUNTS.setdefault(strategy_key, set())
        if len(existing_set) > 200:
            existing_set.pop()
        existing_set.add(pk)
        # Persist to JSON file for bot restart recovery
        try:
            disk = _load_extra_accounts()
            existing = set(disk.get(strategy_key, []))
            existing.add(pk)
            disk[strategy_key] = list(existing)
            disk["_updated_at"] = time.time()
            _save_extra_accounts(disk)
        except Exception as _fs_err:
            logger.debug(f"extra_accounts.json write failed: {_fs_err}")
        logger.warning(
            f"🔧 Fix 96: Discovered extra account {pk[:8]}… for strategy={strategy_key}"
        )


# =============================================================================
# Virtual Balance Reconciler — Fix "Ghost Balance Drift"
# =============================================================================
async def balance_reconciler(
    http_session, rpc_url: str, keypair_ref, jito_exec_ref
) -> None:
    wallet_pk = str(keypair_ref.pubkey())

    while True:
        try:
            await asyncio.sleep(30)  # Hard 30 s background loop per spec

            # 1. Fetch actual balance from RPC
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBalance",
                "params": [wallet_pk],
            }
            import src.ingest.shared_state as shared_state
            async with shared_state.rpc_limiter:
                async with http_session.post(
                    rpc_url, json=payload, timeout=aiohttp.ClientTimeout(total=5.0)
                ) as resp:
                    pass
                if resp.status != 200:
                    continue
                result_data = orjson.loads(await resp.read())
                if "result" not in result_data or "value" not in result_data["result"]:
                    continue
                actual_lamports = result_data["result"]["value"]
            actual_sol = actual_lamports / 1e9

            # 2. Atomic recalculation of virtual_balance UNDER LOCK (FIX 245)
            async with shared_state.stats_lock:
                pending_lamports = 0
                if jito_exec_ref and hasattr(jito_exec_ref, 'pending_bundles'):
                    for meta in list(jito_exec_ref.pending_bundles.values()):
                        # Only count unrefunded bundles
                        if not meta.get("refunded", False):
                            pending_lamports += int(meta.get("deducted", 0.0) * 1e9)

                reconciled_sol = max((actual_lamports - pending_lamports) / 1e9, 0.0)
                prev = shared_state.stats.get("virtual_balance", 0.0)
                drift = abs(reconciled_sol - prev)

                shared_state.stats["virtual_balance"] = reconciled_sol
                shared_state.stats["last_balance"] = actual_sol

                if drift > 0.003:
                    shared_state.set_balance_lock_paused(True, 0.4)
                    logger.critical(
                        f"🚨 BALANCE DRIFT DETECTED: prev={prev:.6f} -> reconciled={reconciled_sol:.6f} SOL "
                        f"(actual={actual_sol:.6f}, pending={pending_lamports/1e9:.6f}). Pausing trades for 400ms."
                    )

        except Exception as e:
            logger.debug(f"Balance reconciler cycle error: {e}")


# Track failed attempts per pair to switch resources


# ── Fix 2: Pair-level reputation guard functions ────────────────────────────


# =============================================================================
# Phase 19 T2: Deferred Timeout Refund — Grace Period for Late Bundle Landings
# =============================================================================
async def _monitor_timed_out_bundles(grace_period: float = 15.0) -> None:
    """
    Background task that waits for the grace period, then refunds virtual_balance
    for bundles that truly expired.  The balance_reconciler (every 30s) catches
    late landings during this window, so we don't need Jito polling here.
    """
    global RECENTLY_TIMED_OUT_BUNDLES
    if not RECENTLY_TIMED_OUT_BUNDLES:
        return

    await asyncio.sleep(grace_period)

    for bundle_id, meta in list(RECENTLY_TIMED_OUT_BUNDLES.items()):
        vid = meta["virtual_balance_to_deduct"]
        async with shared_state.stats_lock:
            shared_state.stats["virtual_balance"] += vid

        jito_exec = meta.get("jito_executor_ref")
        if jito_exec:
            try:
                jito_exec._cancel_pending(bundle_id)
            except Exception:
                pass

        if shared_state.capital_protection and vid > 0:
            shared_state.capital_protection.record_trade(-vid)

        # Phase 22 T3: Reset WSOL atomic close flag on bundle failure
        # If the bundle that timed out contained a wSOL close instruction,
        # the wallet_balance_listener was blocked from unwrapping for 60s.
        # Reset now so it can recover gas immediately.
        if shared_state.WSOL_JUST_CLOSED_ATOMICALLY > 0:
            shared_state.WSOL_JUST_CLOSED_ATOMICALLY = 0.0
            logger.debug(f"♻️ Phase 22: Reset WSOL_JUST_CLOSED_ATOMICALLY after bundle timeout")

        logger.info(
            f"♻️ Deferred Reconciler: Refunded {vid:.6f} SOL for expired bundle {bundle_id}. "
            f"Bundle did not land within {grace_period}s grace period."
        )

        RECENTLY_TIMED_OUT_BUNDLES.pop(bundle_id, None)
def is_pair_allowed(pair_key: str) -> bool:
    """Check if a pair is allowed to trade."""
    return not shared_state.pair_reputation.is_banned(pair_key)


def record_pair_failure(pair_key: str, error_type: str = "unknown"):
    """Record a pair failure via shared pair reputation."""
    shared_state.pair_reputation.record_failure(pair_key, error_type)


def record_pair_success(pair_key: str):
    """Reset pair failure counter via shared pair reputation."""
    shared_state.pair_reputation.record_success(pair_key)


# ────────────────────────────────────────────────────────────────────────────

try:
    from aiolimiter import AsyncLimiter

    class TokenBucket:
        def __init__(self, rps):
            self.limiter = AsyncLimiter(max(1, rps), 1.0)

        async def wait(self):
            await self.limiter.acquire()

except ImportError:
    logger.warning(
        "aiolimiter not installed, falling back to naive TokenBucket. Run: pip install aiolimiter"
    )

    class TokenBucket:
        def __init__(self, rps):
            self.rps = rps
            self.semaphore = asyncio.Semaphore(rps)

        async def wait(self):
            await self.semaphore.acquire()
            asyncio.get_running_loop().call_later(1.0, self.semaphore.release)


limiters = {}


def init_limiters(cfg: Config):
    limiters["jupiter"] = TokenBucket(cfg.JUP_RPS)
    limiters["dexscreener"] = TokenBucket(cfg.DEXSCREENER_RPS)


class RPCManager:
    def __init__(self, cfg: Config):
        # Fix: respect MULTI_RPC_ENABLED to save credits on Free Tier
        all_potential_nodes = [
            node for node in cfg.HELIUS_URLS + cfg.QUICKNODE_URLS if node
        ]
        if not MULTI_RPC_ENABLED and all_potential_nodes:
            self.all_nodes = [all_potential_nodes[0]]
            logger.info(
                f"ℹ️ Multi-RPC disabled: using single node {self.all_nodes[0][:40]}..."
            )
        else:
            self.all_nodes = all_potential_nodes
            if self.all_nodes:
                logger.info(f"✅ Пул RPC готов: {len(self.all_nodes)} узлов в работе")

        self.latencies: Dict[str, float] = {n: 999.0 for n in self.all_nodes}
        self.latest_slot = 0
        self.degraded_nodes: Set[str] = set()
        self.session: Optional[aiohttp.ClientSession] = None

        if not self.all_nodes:
            logger.error("!!! КРИТИЧЕСКАЯ ОШИБКА: RPC ссылки не найдены в .env !!!")
            logger.critical(
                "🛑 Укажите RPC_URL_1 (или HELIUS_API_KEY) в .env файле. Бот остановлен."
            )
            sys.exit(1)
        else:
            # Task 8: Keep strong reference to background task
            self.latency_task = asyncio.create_task(self._latency_ranker())
            shared_state.active_tasks.add(self.latency_task)
            self.latency_task.add_done_callback(background_task_callback)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            import os

            proxy_url = os.getenv("PROXY_URL")
            if proxy_url and (
                proxy_url.startswith("socks5") or proxy_url.startswith("socks4")
            ):
                try:
                    from aiohttp_socks import ProxyConnector

                    connector = ProxyConnector.from_url(proxy_url, limit=100)
                except ImportError:
                    connector = aiohttp.TCPConnector(
                        family=socket.AF_INET, ttl_dns_cache=300
                    )
            elif proxy_url and proxy_url.startswith("http"):
                os.environ["HTTPS_PROXY"] = proxy_url
                os.environ["HTTP_PROXY"] = proxy_url
                connector = aiohttp.TCPConnector(
                    family=socket.AF_INET, ttl_dns_cache=300, trust_env=True
                )
            else:
                connector = aiohttp.TCPConnector(
                    family=socket.AF_INET, ttl_dns_cache=300
                )
            self.session = aiohttp.ClientSession(connector=connector, trust_env=True)
        return self.session

    async def _latency_ranker(self):
        """Fix 63: Background latency ranking every 30s"""
        while True:
            for node in list(self.all_nodes):
                try:
                    t0 = time.time()
                    s = await self._get_session()
                    async with s.post(
                        node,
                        json={"jsonrpc": "2.0", "id": 1, "method": "getSlot"},
                        timeout=2,
                    ) as r:
                        if r.status == 200:
                            raw_bytes = await r.read()
                            data = orjson.loads(raw_bytes)
                            slot = int(data.get("result", 0))
                            if slot > self.latest_slot:
                                self.latest_slot = slot
                            if slot < self.latest_slot - 2:
                                self.degraded_nodes.add(node)
                                logger.warning(
                                    f"🐌 Slot Lag Alert: Node {node[:40]}... lagged by {self.latest_slot - slot} slots. Temporarily degraded."
                                )
                            else:
                                self.degraded_nodes.discard(node)
                            self.latencies[node] = (time.time() - t0) * 1000
                except Exception:
                    self.latencies[node] = 999.0
            await asyncio.sleep(30)

    def get_rpc(self):
        if not self.all_nodes:
            logger.critical(
                "!!! КРИТИЧЕСКАЯ ОШИХА: Все RPC узлы заблокированы (401) или отсутствуют !!!"
            )
            raise Exception("No available RPC nodes. Pool is empty.")

        active_nodes = [n for n in self.all_nodes if n not in self.degraded_nodes]
        # Если все ноды просели, откатываемся на полный список для выживания
        nodes_to_query = active_nodes if active_nodes else self.all_nodes

        # Return fastest (lowest latency)
        return min(nodes_to_query, key=lambda n: self.latencies.get(n, 999.0))

    async def get_token_account_balance(
        self, account_address: str
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch SPL token account balance via RPC.
        Delegates to the active RPC session.
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTokenAccountBalance",
                    "params": [account_address],
                }
                rpc_url = self.get_rpc()
                session = await self._get_session()
                # P0-4.2b: Removed ssl=False — using default TLS verification
                import src.ingest.shared_state as shared_state
                async with shared_state.rpc_limiter:
                    async with session.post(
                        rpc_url, json=payload, timeout=3.0
                    ) as resp:
                        pass
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("result", {}).get("value")
                    elif resp.status == 429:
                        backoff = 2.0 * (2**attempt)
                        logger.warning(
                            f"RPC 429 rate limit hit — backoff {backoff}s (attempt {attempt + 1}/{max_retries})"
                        )
                        await asyncio.sleep(backoff)
                        continue
                    elif resp.status in (403, 401):
                        logger.error(
                            f"RPC {resp.status} forbidden/unauthorized - check API key for {account_address[:8]}"
                        )
                        return None
                    else:
                        logger.debug(f"RPC Error {resp.status}: {await resp.text()}")
                        return None
            except asyncio.TimeoutError:
                logger.debug(
                    f"get_token_account_balance timeout (attempt {attempt + 1}/{max_retries})"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.5 * (2**attempt))
            except Exception as e:
                logger.debug(
                    f"get_token_account_balance failed for {account_address[:8]}: {e}"
                )
                if attempt == max_retries - 1:
                    return None
        return None

    def blacklist(self, rpc_url):
        if rpc_url in self.all_nodes:
            self.all_nodes.remove(rpc_url)
            # Mask the key for logging
            if "helius-rpc.com" in rpc_url:
                # Extract api-key and mask
                parsed = urllib.parse.urlparse(rpc_url)
                query = urllib.parse.parse_qs(parsed.query)
                if "api-key" in query:
                    key = query["api-key"][0]
                    masked_key = (
                        key[:4] + "*" * (len(key) - 8) + key[-4:]
                        if len(key) > 8
                        else key
                    )
                    logger.warning(
                        f"🚫 RPC заблокирован (401 Unauthorized): Helius key {masked_key}"
                    )
                else:
                    logger.warning(
                        f"🚫 RPC заблокирован (401 Unauthorized): {rpc_url[:60]}..."
                    )
            else:
                logger.warning(
                    f"🚫 RPC заблокирован (401 Unauthorized): {rpc_url[:60]}..."
                )
            if not self.all_nodes:
                logger.critical(
                    "Все RPC ключи в .env невалидны или заблокированы сервером. Пожалуйста, обновите HELIUS_KEYS"
                )
                sys.exit(1)


def update_global_price_matrix(matrix: Dict[str, tuple]) -> None:
    """Fix 62: Unified callback that updates both arb_bot.price_matrix and the global Jito/RPC multiplexing matrix.

    Called by PythCorePriceFeeder on every Hermes price update (~400ms).
    Prevents stale price drift between arb_bot.price_matrix and
    _set_global_price_matrix() — both are updated atomically.
    """
    price_matrix.update(matrix)
    _set_global_price_matrix(matrix)


async def update_prices(session, cfg):
    global price_matrix
    mint_map = {name: mint for name, mint in TOKENS.items()}
    while True:
        try:
            # Phase 44: Convert Pubkey objects to strings for the join() call
            ids = ",".join([str(mint) for mint in mint_map.values()])
            async with session.get(f"{cfg.JUPITER_PRICE_URL}?ids={ids}") as resp:
                data = orjson.loads(await resp.read())
                if "data" in data:
                    new_matrix = {}
                    now = time.time()
                    for mint, info in data["data"].items():
                        if info and info.get("price"):
                            new_matrix[mint] = (float(info["price"]), now)
                    price_matrix = new_matrix
                    _set_global_price_matrix(new_matrix)
        except Exception as e:
            logger.debug(f"Price error: {e}")
        await asyncio.sleep(cfg.BG_FETCH_INTERVAL)


async def dexscreener_scanner(queue, session, cfg):
    """Trend Scanner: Fetch trending Solana pairs from DexScreener."""
    while True:
        try:
            await limiters["dexscreener"].wait()
            timeout = aiohttp.ClientTimeout(total=2.0)
            async with session.get(cfg.DEXSCREENER_URL, timeout=timeout) as resp:
                if resp.status == 200:
                    data = orjson.loads(await resp.read())
                    profiles = data if isinstance(data, list) else data.get("pairs", [])
                    for profile in profiles[:20]:
                        mint = profile.get("tokenAddress") or profile.get(
                            "baseToken", {}
                        ).get("address")
                        if mint and mint not in [str(m) for m in TOKENS.values()]:
                            # Dynamically inject new mint into worker queue
                            try:
                                queue.put_nowait(
                                    (2, time.time_ns(), (str(TOKENS["SOL"]), mint))
                                )
                            except asyncio.QueueFull:
                                pass  # HFT: stale data is trash — drop it, don't deadlock
                            if mint in [str(m) for m in MARGINFI_BANKS.keys()]:
                                try:
                                    queue.put_nowait(
                                        (2, time.time_ns(), (mint, str(TOKENS["SOL"])))
                                    )
                                except asyncio.QueueFull:
                                    pass  # HFT: stale data is trash — drop it, don't deadlock
        except Exception as e:
            logger.debug(f"DexScreener error: {e}")
        await asyncio.sleep(60)


# Dynamic Token Registry for Webhook-discovered tokens
temporary_tokens: Dict[str, float] = {}  # Mint -> Expiry Timestamp
# P0-2.1a: Initialized as None — set inside async def run() to bind to correct event loop
temporary_tokens_lock = None


async def register_temporary_token(mint: str, duration: int = 1800):
    """Register a token discovered via webhooks for high-frequency scanning (default 30 min)."""
    async with temporary_tokens_lock:
        expiry = time.time() + duration
        temporary_tokens[mint] = expiry
        logger.info(
            f"✨ Dynamically registered {str(mint)[:8]} for high-frequency scanning until {time.strftime('%H:%M:%S', time.localtime(expiry))}"
        )


async def cleanup_temporary_tokens():
    """Remove expired tokens from the dynamic registry."""
    while True:
        try:
            await asyncio.sleep(300)  # Every 5 minutes
            now = time.time()
            async with temporary_tokens_lock:
                to_remove = [
                    m for m, expiry in temporary_tokens.items() if now > expiry
                ]
                for m in to_remove:
                    del temporary_tokens[m]
                    logger.info(
                        f"🧹 Removed temporary token {str(m)[:8]} from registry (expired)"
                    )
        except Exception as e:
            logger.error(f"Cleanup error: {e}")


# ============================================================================
# SCAN TARGETS — consumed by stable_scanner, lst_scanner, rwa_rest_scanner
# ============================================================================

SCAN_TARGETS = {
    "stables": {
        "description": "Stablecoin Pairs",
        "scan_interval": 1.5,
        "pair_delay": 0.1,
        "pairs": [
            ("USDC", "USDT"),
            ("USDC", "PYUSD"),
            ("USDC", "USDS"),
            ("USDC", "USDY"),
            ("USDC", "USDe"),
            ("USDC", "sUSDe"),
            ("USDC", "sUSDS"),
            ("USDC", "JupUSD"),
        ],
    },  # Step 5: yield stables
    "lst": {
        "description": "LST Pairs",
        "scan_interval": 2.0,
        "pair_delay": 0.1,
        "pairs": [
            ("SOL", "jitoSOL"),
            ("SOL", "mSOL"),
            ("SOL", "bSOL"),
            ("SOL", "INF"),
            ("SOL", "JupSOL"),
            ("SOL", "fwdSOL"),
            ("SOL", "dSOL"),
            ("SOL", "hubSOL"),
            ("SOL", "dzSOL"),
            ("SOL", "bonkSOL"),
            ("SOL", "vSOL"),
            ("SOL", "compassSOL"),
            ("SOL", "hSOL"),
        ],
    },  # Step 5: new LSTs
    "rwa_rest": {
        "description": "Other RWA/DePIN",
        "scan_interval": 15.0,
        "pair_delay": 0.5,
        "pairs": [("USDC", "JUP"), ("USDC", "WIF")],
    },
}


async def stable_scanner(queue, cfg):
    """Loop A (Fast Stables): Check 5+ stablecoin pairs every 1.5 seconds."""
    scan_config = SCAN_TARGETS["stables"]
    logger.debug(f"🚀 Stable Scanner: {scan_config['description']}")

    cycle_count = 0
    while True:
        # Self-healing: Check balance every 10 cycles (~15 seconds)
        cycle_count += 1
        if cycle_count % 10 == 0:
            # Balance guard handled globally in the main event loop – no per-scanner recovery needed
            pass

        for base, target in scan_config["pairs"]:
            if base in TOKENS and target in TOKENS:
                try:
                    queue.put_nowait(
                        (1, time.time_ns(), (TOKENS[base], TOKENS[target]))
                    )
                except asyncio.QueueFull:
                    pass  # HFT: stale data is trash — drop it, don't deadlock
                await asyncio.sleep(scan_config["pair_delay"])
        await asyncio.sleep(scan_config["scan_interval"])
        await asyncio.sleep(0.1)  # Safe 100ms yield to the OS event loop


async def lst_scanner(queue, cfg):
    """Loop B (LST Priority): Arbitrage between SOL and derivatives."""
    scan_config = SCAN_TARGETS["lst"]
    logger.debug(f"🌊 LST Scanner: {scan_config['description']}")

    while True:
        for base, target in scan_config["pairs"]:
            if base in TOKENS and target in TOKENS:
                try:
                    queue.put_nowait(
                        (1, time.time_ns(), (TOKENS[base], TOKENS[target]))
                    )
                except asyncio.QueueFull:
                    pass  # HFT: stale data is trash — drop it, don't deadlock
                await asyncio.sleep(scan_config["pair_delay"])
        await asyncio.sleep(scan_config["scan_interval"])
        await asyncio.sleep(0.1)  # Safe 100ms yield to the OS event loop


def is_nyse_trading_hours() -> bool:
    """Check if current UTC time is within NYSE trading hours (13:30-20:00 UTC)."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    hour = now.hour
    minute = now.minute

    # NYSE trading hours: 13:30 - 20:00 UTC (9:30 AM - 4:00 PM ET)
    current_minutes = hour * 60 + minute
    start_minutes = 13 * 60 + 30  # 13:30 UTC
    end_minutes = 20 * 60  # 20:00 UTC

    return start_minutes <= current_minutes <= end_minutes


def get_market_aware_scan_interval(base_interval: float) -> float:
    """Adjust scan interval based on market hours. Reduce frequency outside trading hours."""
    if is_nyse_trading_hours():
        return base_interval  # Full speed during trading hours
    else:
        return (
            base_interval * 10
        )  # 10x slower outside trading hours to save RPC credits


async def rwa_rest_scanner(queue, cfg):
    """Loop D (RWA Rest): Slow scan of remaining RWA assets every 15 seconds."""
    scan_config = SCAN_TARGETS["rwa_rest"]
    logger.debug(f"🏛️ RWA Rest Scanner: {scan_config['description']}")

    while True:
        for base, target in scan_config["pairs"]:
            if base in TOKENS and target in TOKENS:
                try:
                    queue.put_nowait(
                        (2, time.time_ns(), (TOKENS[base], TOKENS[target]))
                    )  # Lower priority
                except asyncio.QueueFull:
                    pass  # HFT: stale data is trash — drop it, don't deadlock
                await asyncio.sleep(scan_config["pair_delay"])
        await asyncio.sleep(scan_config["scan_interval"])


async def _fetch_quote_internal(
    session,
    input_mint,
    output_mint,
    amount_lamports,
    cfg,
    slippage_bps=None,
    restrict_intermediate: bool = True,
    swap_mode: Optional[str] = None,
    wallet_balance_sol: float = 0.0,  # Task 14: micro-balance ATA routing guard
    exact_out_amount: Optional[int] = None,  # Fix: ExactOut desired output (debt)
):
    """Internal quote fetcher — all original HTTP logic lives here."""
    from src.ingest.jupiter_api_client import get_quote_limiter

    limiter = get_quote_limiter()
    if slippage_bps is None:
        slippage_bps = cfg.SLIPPAGE_BPS
    # ── ExactOut Mode: amount param must be desired OUTPUT (borrow debt), not input ──
    # Jupiter API v6: when swapMode=ExactOut, the `amount` field represents
    # the exact number of OUTPUT tokens you want to receive, not what you input.
    # The fake `exactOutAmount` param does NOT exist in Jupiter API v6.
    if swap_mode == "ExactOut" and exact_out_amount is not None:
        use_amount = str(int(exact_out_amount))
    else:
        use_amount = str(int(amount_lamports))
    params = {
        "inputMint": str(input_mint),
        "outputMint": str(output_mint),
        "amount": use_amount,
        "slippageBps": str(slippage_bps),
        "onlyDirectRoutes": "false",
        "restrictIntermediateTokens": "false",
        "cache_buster": str(time.time_ns()),
    }
    # ── ExactOut Mode (The ExactIn vs ExactOut Fix) ──────────────────────────────
    # For the final closing leg, Jupiter ExactOut guarantees the swap yields exactly
    # the required repayment amount for MarginFi, fully eliminating InsufficientFunds.
    if swap_mode:
        params["swapMode"] = swap_mode
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    if cfg.JUPITER_API_KEY:
        headers["x-api-key"] = cfg.JUPITER_API_KEY

    max_retries = 3
    async with limiter:
        for attempt in range(max_retries):
            try:
                async with session.get(
                    cfg.JUPITER_QUOTE_URL, params=params, headers=headers
                ) as resp:
                    if resp.status == 200:
                        data = orjson.loads(await resp.read())
                        data["fetched_at"] = time.time()  # FIX 104: Добавляем метку времени во внутренний ответ
                        return {
                            "source": "Jupiter",
                            "out_amount": int(data["outAmount"]),
                            "full_quote_response": data,
                        }
                    elif resp.status == 429:
                        backoff = min(2.0, 1.5 * (attempt + 1))
                        logger.warning(
                            f"Jupiter 429 on {cfg.JUPITER_QUOTE_URL} — backoff {backoff}s (attempt {attempt + 1}/{max_retries})"
                        )
                        await asyncio.sleep(backoff)
                        continue
                    else:
                        error_text = await resp.text()
                        logger.warning(
                            f"Jupiter API Error {resp.status}: {error_text}"
                        )
                        return None
            except asyncio.TimeoutError:
                logger.warning(
                    f"Jupiter quote timeout (attempt {attempt + 1}/{max_retries})"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.5 * (2**attempt))
            except Exception as e:
                logger.warning(f"Jupiter Exception: {repr(e)}")
                return None
    return None


async def get_jupiter_quote(
    session,
    input_mint,
    output_mint,
    amount_lamports,
    cfg,
    slippage_bps=None,
    restrict_intermediate: bool = True,
    swap_mode: Optional[str] = None,
    wallet_balance_sol: float = 0.0,  # Task 14: micro-balance ATA routing guard
    exact_out_amount: Optional[int] = None,  # Fix: ExactOut desired output (debt)
):
    """Deduplicated quote fetcher — if a request for the same key is in-flight,
    subsequent callers await the same task instead of making a duplicate RPC call."""
    cache_key = f"{input_mint}:{output_mint}:{amount_lamports}:{swap_mode}:{exact_out_amount}"
    now = time.time()

    # FIX 293: RAM cache with 800ms TTL (2 Solana slots) — return instantly without HTTP
    async with _QUOTE_CACHE_LOCK:
        if cache_key in _QUOTE_CACHE:
            fetched_at, cached_data = _QUOTE_CACHE[cache_key]
            if now - fetched_at < 0.8:
                logger.debug(f"⚡ Quote cache HIT for {input_mint[:8]}->{output_mint[:8]} (Age: {(now - fetched_at)*1000:.0f}ms)")
                return cached_data
            else:
                _QUOTE_CACHE.pop(cache_key, None)

    pair_key = cache_key

    async with _QUOTE_TASKS_LOCK:
        if pair_key in _QUOTE_TASKS:
            # Если кто-то уже делает этот запрос, ждем его результата (shield защищает от отмены)
            try:
                return await asyncio.shield(_QUOTE_TASKS[pair_key])
            except Exception as e:
                logger.debug(f"Shielded quote task failed: {e}")
                return None

        # Создаем новую задачу
        coro = _fetch_quote_internal(
            session, input_mint, output_mint, amount_lamports, cfg,
            slippage_bps, restrict_intermediate, swap_mode, wallet_balance_sol, exact_out_amount
        )
        task = asyncio.create_task(coro)
        _QUOTE_TASKS[pair_key] = task

    try:
        result = await task
        
        # FIX 293: Store successful quote in RAM cache with 800ms TTL
        if result and "out_amount" in result:
            async with _QUOTE_CACHE_LOCK:
                _QUOTE_CACHE[cache_key] = (time.time(), result)
                
        return result
    finally:
        async with _QUOTE_TASKS_LOCK:
            _QUOTE_TASKS.pop(pair_key, None)


def get_token_decimals(mint) -> int:
    """Return token decimals safe for str and Pubkey inputs."""
    return TOKEN_DECIMALS.get(str(mint), 6)  # 6 - стандарт для новых токенов на Solana


async def get_token_decimals_dynamic(session: aiohttp.ClientSession, rpc_url: str, mint_address: str) -> int:
    """Dynamically fetch token decimals via jsonParsed RPC with caching (P2-024).

    Resolution order:
    1. Check hardcoded TOKEN_DECIMALS dict
    2. Check shared_state.DYNAMIC_DECIMALS_CACHE
    3. Query RPC getAccountInfo with jsonParsed encoding
    4. Fallback to 6 (safe conservative default)
    """
    mint_str = str(mint_address)

    # 1. Check hardcoded dictionary first
    if mint_str in TOKEN_DECIMALS:
        return TOKEN_DECIMALS[mint_str]

    # 2. Check in-memory dynamic cache
    import src.ingest.shared_state as _ss
    if mint_str in _ss.DYNAMIC_DECIMALS_CACHE:
        return _ss.DYNAMIC_DECIMALS_CACHE[mint_str]

    # 3. Query RPC with jsonParsed encoding
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": [mint_str, {"encoding": "jsonParsed", "commitment": "confirmed"}],
    }
    try:
        import src.ingest.shared_state as shared_state
        async with shared_state.rpc_limiter:
            async with session.post(rpc_url, json=payload, timeout=3.0) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    value = data.get("result", {}).get("value")
                    if value and "data" in value:
                        parsed_info = value["data"].get("parsed", {}).get("info", {})
                        decimals = parsed_info.get("decimals")
                        if decimals is not None:
                            decimals_val = int(decimals)
                        # FIX 159: Limit dynamic decimals cache to 2000 items to avoid slow memory leak
                        if len(_ss.DYNAMIC_DECIMALS_CACHE) > 2000:
                            _ss.DYNAMIC_DECIMALS_CACHE.clear()
                        _ss.DYNAMIC_DECIMALS_CACHE[mint_str] = decimals_val
                        logger.info(f"✨ Dynamically resolved decimals for {mint_str[:8]}...: {decimals_val}")
                        return decimals_val
    except Exception as e:
        logger.debug(f"Dynamic decimals fetch failed for {mint_str[:8]}: {e}")

    return 6  # Safe conservative fallback


async def get_best_quote_multi(
    session,
    in_mint,
    out_mint,
    amount,
    cfg,
    expected_profit_bps: float = 0.0,
    restrict_intermediate: bool = True,
    slippage_bps=None,
    swap_mode: Optional[str] = None,
    exact_out_amount: Optional[int] = None,  # Fix: ExactOut desired output (debt)
):
    """Get best quote with anti-sandwich slippage guard (Fix 34).

    Args:
        expected_profit_bps: Expected arbitrage profit in basis points.
                             Required for profit-aware dynamic slippage.
                             If 0, falls back to cfg.SLIPPAGE_BPS.
        restrict_intermediate: If False, Jupiter finds multi-hop routes through intermediate tokens.
                               Use for triangular/3+hop arbitrage to reduce sequential API calls.
        slippage_bps: Explicit slippage override. If set, bypasses profit-aware auto-calculation.
        swap_mode: Optional Jupiter swapMode (e.g. "ExactOut") for the final closing leg.
        exact_out_amount: When swap_mode="ExactOut", the exact output amount desired
                          (typically the borrow debt to repay).  Passed as `amount` param
                          instead of the input amount_lamports.
    """
    try:
        if slippage_bps is None:
            if expected_profit_bps > 0:
                # Fix 34: Profit-Aware Dynamic Slippage (Anti-Sandwich Guard)
                # Slippage must never exceed 40% of expected profit.
                # This mathematically prevents sandwich bot extraction of our capital:
                #   worst case: 40% slippage eaten by sandwich, leaving 60% gross profit → still net profit.
                # Fix 4 (SlippageBps Floor): min 5 BPS — Jupiter часто отклоняет маршруты при slippage < 5 BPS
                slippage_bps = max(5, int(expected_profit_bps * 0.4))
                logger.debug(
                    f"🛡️ Profit-aware slippage: {slippage_bps} BPS "
                    f"(profit={expected_profit_bps:.1f} BPS, cap=40%, floor=5)"
                )
            else:
                slippage_bps = cfg.SLIPPAGE_BPS

        quote = await asyncio.wait_for(
            get_jupiter_quote(
                session,
                in_mint,
                out_mint,
                amount,
                cfg,
                slippage_bps,
                restrict_intermediate=restrict_intermediate,
                swap_mode=swap_mode,
                exact_out_amount=exact_out_amount,
            ),
            timeout=15.0,
        )
        return quote
    except Exception as e:
        logger.warning(f"Jupiter quote failed: {repr(e)}")
        return None


async def create_flashloan_arbitrage_tx(
    session,
    base_mint,
    target_mint,
    base_amount_lamports,
    quotes,
    cfg,
    keypair,
    rpc_getter,
    use_jito=False,
    tip_lamports=0,
    alt_manager=None,
    strategy_type=1,
    tip_accounts=None,
    blockhash_mgr=None,
    opportunity=None,
    expected_profit_sol: float = 0.0,
):
    wallet_pubkey = str(keypair.pubkey())

    # Fix 1: Safe cast base_mint / target_mint to strings up front
    base_mint_str = str(base_mint) if isinstance(base_mint, Pubkey) else str(base_mint)
    target_mint_str = (
        str(target_mint) if isinstance(target_mint, Pubkey) else str(target_mint)
    )
    base_mint = _to_pubkey(base_mint_str)
    target_mint = _to_pubkey(target_mint_str)

    # Динамически берем аккаунт из пула для этой конкретной транзакции
    pool_acct_str = cfg.MARGINFI_ACCOUNT_PUBKEY
    try:
        from src.ingest.shared_state import stats

        current_slot = stats.get("current_slot", 0)
        # Если роутер передан, просим у пула свободный аккаунт
        if hasattr(opportunity, "metadata") and opportunity.metadata.get(
            "execution_router"
        ):
            router = opportunity.metadata["execution_router"]
            if hasattr(router, "marginfi_pool"):
                pool_acct_str, _ = await router.marginfi_pool.checkout(current_slot)
    except Exception as e:
        logger.debug(f"Pool checkout fallback to env: {e}")

    marginfi_account = Pubkey.from_string(pool_acct_str)

    flashloan_mint_str = base_mint_str
    effective_base_amount = base_amount_lamports

    if flashloan_mint_str not in MARGINFI_BANKS:
        logger.warning(f"Marginfi bank not configured for mint: {flashloan_mint_str}")
        return None
    bank_cfg = MARGINFI_BANKS[flashloan_mint_str]

    tx_builder = JupiterTxBuilder(
        session=session, rpc_getter=lambda: rpc_getter(), alt_manager=alt_manager
    )

    # FIX 254: Parallel swap-instructions fetch to reduce hot-path latency
    instructions = []
    if not quotes:
        return None
    wallet_pubkey_str = str(wallet_pubkey)
    swap_tasks = []
    for i, quote in enumerate(quotes):
        if "full_quote_response" not in quote:
            return None
        swap_tasks.append(
            tx_builder.get_swap_instructions(
                quote["full_quote_response"],
                wallet_pubkey_str,
                use_custom_cu=True,
                expected_profit_sol=expected_profit_sol,
            )
        )
    swap_results = await asyncio.gather(*swap_tasks, return_exceptions=True)
    for i, res in enumerate(swap_results):
        if isinstance(res, Exception) or not res or not res[0]:
            logger.warning(f"❌ [Parallel Swap] Leg {i} swap-instructions fetch failed: {res}")
            return None
        ixs, alts = res
        instructions.append((ixs, alts))

    if len(instructions) < 2:
        logger.warning("Not enough instructions")
        return None

    # Apply dynamic slippage (Slippage Sniper)
    dynamic_slippage = tx_builder.get_dynamic_slippage([base_mint_str, target_mint_str])
    logger.debug(
        f"Using dynamic slippage: {dynamic_slippage*100:.2f}% for {base_mint_str[:8]}/{target_mint_str[:8]}"
    )

    # Filter by profit — generalized for any number of legs (Fix 39)
    # profit comes from the LAST leg: input -> ... -> output
    # Use last quote output as the final result
    last_quote = quotes[-1]
    first_quote = quotes[0]
    profit_lamports = int(last_quote["out_amount"]) - base_amount_lamports

    # Convert SOL fees to base_mint equivalents if base_mint is not SOL
    is_sol_base = base_mint_str == "So11111111111111111111111111111111111111112"
    sol_entry = price_matrix.get("So11111111111111111111111111111111111111112")
    sol_price_in_usd = sol_entry[0] if isinstance(sol_entry, (tuple, list)) else 150.0

    base_fee_sol = cfg.BASE_FEE + (tip_lamports / 1e9)
    if is_sol_base:
        fee_in_base_token_lamports = int(base_fee_sol * 1e9)
    else:
        # Assuming base_mint is a stablecoin
        # FIX 195: Dynamically resolve decimals instead of hardcoded 1e6 (6 decimals)
        decimals = get_token_decimals(base_mint_str) or 6
        fee_in_base_token_lamports = int(base_fee_sol * sol_price_in_usd * (10 ** decimals))

    # DEX-003: Subtract Jupiter platform fee (totalFee from final quote)
    jupiter_fee_lamports = int(
        last_quote.get("full_quote_response", {})
        .get("fees", {})
        .get("totalFee", 0)
    )
    # DEX-006: Asset-specific flashloan fee (0.05% for USDC/USDT, 0% for SOL)
    _usdc_mint_str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    _usdt_mint_str = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
    if str(base_mint_str) in [_usdc_mint_str, _usdt_mint_str]:
        _flashloan_fee_pct = 0.0005  # 0.05% for stablecoins
    else:
        _flashloan_fee_pct = 0.0     # 0% for SOL
    flashloan_fee_lamports = int(base_amount_lamports * _flashloan_fee_pct)
    total_fees_in_base = fee_in_base_token_lamports + flashloan_fee_lamports + jupiter_fee_lamports

    if profit_lamports < total_fees_in_base:
        return None

    from spl.token.instructions import (
        get_associated_token_address,
        close_account,
        CloseAccountParams,
    )
    from spl.token.instructions import create_idempotent_associated_token_account

    CREATE_ATA_FUNCTION = create_idempotent_associated_token_account

    # Phase 48: Resolve the borrow mint for wSOL unwrapping (Bug 20)
    borrow_mint_str = flashloan_mint_str  # The asset we flashloan
    borrow_mint = _to_pubkey(borrow_mint_str)
    sol_wrapped_mint = Pubkey.from_string("So11111111111111111111111111111111111111112")

    wallet = keypair.pubkey()
    user_sol_ata = get_associated_token_address(wallet, sol_wrapped_mint)
    user_token_account = get_associated_token_address(wallet, borrow_mint)

    # Prepare arbitrage instructions — dynamic sweep of ALL legs (Fix 39)
    swap_instructions = []
    all_alts = []
    for ixs, alts in instructions:
        swap_instructions.extend(ixs)
        all_alts.extend(alts)

    # Phase 47: Instruction Introspection Refactor
    # Instead of packing instructions into a single Anchor call (CPI),
    # we build a sequential transaction: [Borrow, *Swaps, VerifyProfit, Repay].
    # This avoids CPI depth limits and allows the Anchor contract to be lightweight.

    # 2. Build MarginFi Borrow/Repay instructions
    from src.ingest.tx_builder import JupiterTxBuilder

    builder = JupiterTxBuilder(session=session)

    mfi_program = Pubkey.from_string("MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA")
    mfi_group = shared_state.MARGINFI_GROUP
    sol_mint = Pubkey.from_string("So11111111111111111111111111111111111111112")

    # Calculate indices for Instruction Introspection
    # [Borrow, Withdraw, ...Swaps, Repay, End]
    repay_index = (
        2 + len(swap_instructions) + 1
    )  # borrow(0) + withdraw(1) + len(Swaps) + repay = end_ix

    borrow_ix = builder.build_marginfi_start_flashloan_ix(
            marginfi_group=mfi_group,
            marginfi_account=marginfi_account,
            bank=bank_cfg["bank"],
            liquidity_vault=bank_cfg["liquidity_vault"],
            bank_liquidity_vault_authority=bank_cfg["liquidity_vault_authority"],
            token_program=TOKEN_PROGRAM_ID,
            instructions_sysvar=Pubkey.from_string("Sysvar1nstructions1111111111111111111111111"),
            signer=keypair.pubkey(),
            fee_payer=keypair.pubkey(),
            bank_index=0,
            amount=int(effective_base_amount),
            repay_index=repay_index,
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # SAFE FLASHLOAN START DATA RECONSTRUCTION (discriminator 8 + bank_index 2 + amount 8 + repay_index 2)
    # MarginFi v2 flashloan start layout: discriminator(8) | bank_index(2 u16 LE) | amount(8 u64 LE) | repay_index(2 u16 LE)
    # Total: 20 bytes. Rebuild from scratch to ensure correct indexing after sanitization.
    # ═══════════════════════════════════════════════════════════════════════════
    try:
        from src.ingest.tx_builder import MARGINFI_FLASHLOAN_START
    except ImportError:
        from src.ingest.tx_builder import MARGINFI_FLASHLOAN_START

    try:
        # Exact re-serialization: 20 bytes total
        _new_data = (
            MARGINFI_FLASHLOAN_START
            + struct.pack("<H", 0)  # bank_index
            + struct.pack("<Q", int(effective_base_amount))  # amount
            + struct.pack("<H", repay_index)  # repay_index
        )
        if len(_new_data) == 20:
            borrow_ix = Instruction(
                program_id=borrow_ix.program_id,
                accounts=borrow_ix.accounts,
                data=_new_data,
            )
        else:
            logger.warning(
                f"Borrow data re-serialized to {len(_new_data)} bytes — using original"
            )
    except Exception as _rebuild_err:
        logger.debug(f"Borrow safe-rebuild skipped ({_rebuild_err}), using original")

    # ── MarginFi v2: withdraw borrowed tokens from vault ──
    withdraw_ix = builder.build_marginfi_withdraw_ix(
        mfi_program=borrow_ix.program_id,
        mfi_group=shared_state.MARGINFI_GROUP,
        mfi_account=marginfi_account,
        wallet=keypair.pubkey(),
        bank=bank_cfg["bank"],
        user_token_account=user_token_account,
        vault=bank_cfg["liquidity_vault"],
        vault_auth=bank_cfg["liquidity_vault_authority"],
        token_program=TOKEN_PROGRAM_ID,
        amount=int(effective_base_amount),
    )

    # ── MarginFi v2: repay flashloan (lending_account_repay) ──
    repay_ix = builder.build_marginfi_repay_ix(
        mfi_program=borrow_ix.program_id,
        mfi_group=shared_state.MARGINFI_GROUP,
        mfi_account=marginfi_account,
        wallet=keypair.pubkey(),
        bank=bank_cfg["bank"],
        user_token_account=user_token_account,
        vault=bank_cfg["liquidity_vault"],
        vault_auth=bank_cfg["liquidity_vault_authority"],
        token_program=TOKEN_PROGRAM_ID,
        amount=int(effective_base_amount),
    )

    # ── MarginFi v2: end flashloan introspection (8 accounts) ──
    end_ix = builder.build_marginfi_end_flashloan_ix(
        marginfi_group=mfi_group,
        marginfi_account=marginfi_account,
        bank=bank_cfg["bank"],
        liquidity_vault=bank_cfg["liquidity_vault"],
        bank_liquidity_vault_authority=bank_cfg["liquidity_vault_authority"],
        token_program=TOKEN_PROGRAM_ID,
        instructions_sysvar=Pubkey.from_string("Sysvar1nstructions1111111111111111111111111"),
        signer=keypair.pubkey(),
        repay_index=repay_index,
    )

    # Final instruction sequence for build_optimized_transaction
    # Order: [borrow, withdraw, ...swaps, repay, end]
    arbitrage_instructions = (
        [borrow_ix, withdraw_ix] + swap_instructions + [repay_ix, end_ix]
    )

    # ─── ALT CACHE: Resolve all ALTs in-MEMORY — Zero-Latency Lookup ──────────
    # Deduplicate and batch-resolve via cache. Only a single RPC call for any ALTs
    # not yet in cache. Cache miss on the first trade → 1 RPC fetch; all subsequent
    # trades using the same ALTs → 0 ms (pure RAM lookup).
    address_lookup_tables = []
    ALT_CACHE_TTL = 7200  # 2-hour hard TTL for cached ALT entries
    if alt_manager:
        seen_alt_strs = set()
        unique_alts = []
        for alt in all_alts:
            alt_str = str(alt)
            if alt_str not in seen_alt_strs:
                seen_alt_strs.add(alt_str)
                unique_alts.append(alt)

        from solders.address_lookup_table_account import AddressLookupTableAccount

        # ── Pass 1: Resolve from in-memory cache ───────────────────────────────
        still_needed = []
        for pk in unique_alts:
            resolved = alt_manager.resolve_alt(pk)
            if resolved:
                address_lookup_tables.append(
                    AddressLookupTableAccount(key=pk, addresses=resolved)
                )
            else:
                still_needed.append(pk)

        # ── Pass 2: Single RPC fetch for ALL uncached ALTs, then cache them ────
        if still_needed:
            try:
                alt_payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getMultipleAccounts",
                    "params": [[str(p) for p in still_needed], {"encoding": "base64"}],
                }
                async with session.post(rpc_getter(), json=alt_payload) as resp:
                    if resp.status == 200:
                        data = orjson.loads(await resp.read())
                        for i, acc_data in enumerate(
                            data.get("result", {}).get("value", [])
                        ):
                            if acc_data:
                                b64 = acc_data["data"][0]
                                padded_b64 = b64 + "=" * (-len(b64) % 4)
                                raw = base64.b64decode(padded_b64)
                                header_len = 56 if raw[21] == 1 else 24
                                keys = [
                                    Pubkey.from_bytes(raw[j : j + 32])
                                    for j in range(header_len, len(raw), 32)
                                ]
                                _pk = still_needed[i]
                                address_lookup_tables.append(
                                    AddressLookupTableAccount(key=_pk, addresses=keys)
                                )
                                # Cache permanently (2-hour TTL) — avoids RPC on every future tx
                                alt_manager.alt_cache[str(_pk)] = keys
                                alt_manager.alt_metadata[str(_pk)] = (
                                    time.time(),
                                    ALT_CACHE_TTL,
                                )
            except Exception as _alt_err:
                logger.debug(f"ALT RPC fallback fetch error: {_alt_err}")

    if all_alts and not address_lookup_tables:
        logger.warning(
            f"⚠️ ALT RESOLUTION FAILURE: Could not resolve {len(all_alts)} ALTs. "
            "Aborting transaction to prevent MTU packet overflow."
        )
        return None

    # Task 5: Slot Drift Compensator — force-refresh blockhash if local clock
    # has drifted > 200 ms from the RPC-reported slot time. Prevents Jito from
    # rejecting our bundles as "too old" on machines with skewed clocks.
    if blockhash_mgr:
        _drift_refreshed = await blockhash_mgr.check_and_recover_drift()
        if _drift_refreshed:
            logger.warning(
                "🔄 Slot Drift Compensator: blockhash force-refreshed before TX compile"
            )

    recent_blockhash = None
    if blockhash_mgr:
        bh_obj = await blockhash_mgr.get_fresh_blockhash()
        if bh_obj:
            recent_blockhash = str(bh_obj)
    if not recent_blockhash:
        try:
            timeout = aiohttp.ClientTimeout(total=1.0)
            async with session.post(
                rpc_getter(),
                json={"jsonrpc": "2.0", "id": 1, "method": "getLatestBlockhash"},
                timeout=timeout,
            ) as resp:
                bh_data = orjson.loads(await resp.read())
                if "result" in bh_data:
                    recent_blockhash = Hash.from_string(
                        bh_data["result"]["value"]["blockhash"]
                    )
        except Exception:
            pass

    if not recent_blockhash:
        logger.error(
            "❌ CRITICAL: Failed to fetch valid blockhash. Aborting transaction build to prevent silent bundle drop."
        )
        return None

    try:
        # Use optimized transaction building with custom CU and priority fees
        optimized_instructions, cu_limit, priority_fee = (
            await tx_builder.build_optimized_transaction(
                instructions=arbitrage_instructions,
                address_lookup_tables=address_lookup_tables,
                payer=keypair.pubkey(),
                recent_blockhash=str(recent_blockhash),
                program_id="MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA",  # MarginFi program as caching key
                operation_type="flash_arbitrage",
                use_jito=use_jito,
                rpc_url=rpc_getter(),
                expected_profit_sol=(
                    opportunity.expected_profit_sol if opportunity else 0.0
                ),
            )
        )
        # ── ИСПРАВЛЕНИЕ: Защита от краша при превышении MTU лимита (Task 11) ──
        if optimized_instructions is None or optimized_instructions == "MTU_SIZE_LIMIT":
            logger.warning(
                f"⚠️ Сделка отменена: транзакция превышает лимит MTU (1180 байт) "
                f"или компиляция завершилась с ошибкой. Пропуск сборки."
            )
            return None

        # cu_limit is already the dynamic profile value from build_optimized_transaction()
        # Calculate EXACT repay index dynamically using list introspection in optimized_instructions
        try:
            actual_repay_index = next(
                (
                    i
                    for i, ix in enumerate(optimized_instructions)
                    if ix.program_id == end_ix.program_id
                    and ix.data[:8] == end_ix.data[:8]
                ),
                None,
            )
            from src.ingest.tx_builder import MARGINFI_FLASHLOAN_START

            bank_index_val = struct.unpack("<H", borrow_ix.data[8:10])[0] if len(borrow_ix.data) >= 10 else 0
            _safe_data = (
                MARGINFI_FLASHLOAN_START
                + struct.pack("<H", bank_index_val)
                + int(effective_base_amount).to_bytes(8, "little")
                + struct.pack("<H", actual_repay_index)
            )
            # Find and replace the borrow instruction inside optimized_instructions
            # ИСПРАВЛЕНИЕ Python 3.13 StopIteration: Добавлен None как дефолтное значение
            borrow_idx = next(
                (
                    i
                    for i, ix in enumerate(optimized_instructions)
                    if ix.program_id == borrow_ix.program_id
                    and ix.data[:8] == MARGINFI_FLASHLOAN_START
                ),
                None,
            )
            if borrow_idx is not None:
                optimized_instructions[borrow_idx] = Instruction(
                    program_id=borrow_ix.program_id,
                    accounts=borrow_ix.accounts,
                    data=_safe_data,
                )
                logger.debug(
                    f"🛠️ Safe Flashloan Start Data Re-serialized and Replaced at index {borrow_idx}: repay_index={actual_repay_index}"
                )
        except (ValueError, StopIteration) as e:
            logger.error(
                f"CRITICAL: Failed to locate and update borrow/repay instruction: {e}"
            )
            return None

        logger.debug(
            f"Optimized transaction: CU={cu_limit}, PriorityFee={priority_fee} microlamports, Jito={use_jito}"
        )

        # Phase 48: Native SOL Tip Starvation Fix (Bug 20)
        # If the flashloan asset is SOL, profit accrues as wSOL in the ATA.
        # Close the wSOL ATA first to unwrap into native SOL, then pay the Jito tip.
        if borrow_mint == Pubkey.from_string(
            "So11111111111111111111111111111111111111112"
        ):
            optimized_instructions.append(
                close_account(
                    CloseAccountParams(
                        program_id=TOKEN_PROGRAM_ID,
                        account=user_sol_ata,
                        dest=wallet,
                        owner=wallet,
                        signers=[],
                    )
                )
            )
            optimized_instructions.append(
                CREATE_ATA_FUNCTION(payer=wallet, owner=wallet, mint=sol_wrapped_mint)
            )
            logger.debug(
                "🔓 wSOL unwrapping injected: CloseATA + CreateIdempotentATA before Jito tip"
            )

        # Add Jito tip instruction if specified (must be last for security)
        if tip_lamports > 0:
            from solders.system_program import TransferParams, transfer

            # Use dynamic tip accounts from jito_executor (never hardcoded)
            _tip_accounts_list = tip_accounts or []
            if not _tip_accounts_list:
                logger.critical("🚨 JITO TIP ACCOUNTS: tip_accounts is empty! Aborting to prevent hardcoded fallback.")
                return None
            selected_tip_account = random.choice(_tip_accounts_list)
            tip_ix = transfer(
                TransferParams(
                    from_pubkey=keypair.pubkey(),
                    to_pubkey=Pubkey.from_string(selected_tip_account),
                    lamports=tip_lamports,
                )
            )
            optimized_instructions.append(tip_ix)

        msg = MessageV0.try_compile(
            payer=keypair.pubkey(),
            instructions=optimized_instructions,
            address_lookup_table_accounts=address_lookup_tables,
            recent_blockhash=recent_blockhash,
        )
        tx = VersionedTransaction(msg, [keypair])

        # ─── TASK 5: MTU PADDING ────────────────────────────────────────────────
        # If the compiled transaction is below 500 B, expand to ~600 B so the
        # Solana QUIC scheduler does not deprioritise our packet.
        tx = _ensure_mtu_size(tx, cu_limit=cu_limit)

        # ─── TASK 6: ATOMIC SEQUENCE GUARD ─────────────────────────────────────
        # Strictly enforce instruction order:
        #   [0]  ComputeBudget Limit
        #   [1]  ComputeBudget Price   (may be absent for Jito; forward-search)
        #   [2]  MarginFi Borrow
        #   [3..N] Jupiter Swaps
        #   [N+1] wSOL Close (Unwrap)
        #   [N+2] MarginFi Repay
        #   [N+3] Jito Tip
        from src.ingest.tx_builder import (
            MARGINFI_FLASHLOAN_START,
            MARGINFI_FLASHLOAN_END,
            CLOSE_ACCOUNT_DISCRIMINATOR,
        )

        _CB_PROG = Pubkey.from_string("ComputeBudget111111111111111111111111111111")
        _cb_idx = next(
            (
                i
                for i, ix in enumerate(optimized_instructions)
                if ix.program_id == _CB_PROG
            ),
            -1,
        )
        _price_idx = (
            _cb_idx + 1
            if _cb_idx >= 0 and _cb_idx + 1 < len(optimized_instructions)
            else -1
        )
        try:
            _second_cb_idx = _cb_idx + 1  # next position after limit
            _extra_cb = next(
                (
                    i
                    for i, ix in enumerate(optimized_instructions)
                    if ix.program_id == _CB_PROG and i != _cb_idx
                ),
                -1,
            )
            if _extra_cb >= 0:
                _price_idx = _extra_cb
            elif _cb_idx >= 0 and _cb_idx + 1 < len(optimized_instructions):
                _price_idx = _cb_idx + 1
        except Exception:
            pass

        # Find borrow/repay by program_id discrimination
        _borrow_idx = next(
            (
                i
                for i, ix in enumerate(optimized_instructions)
                if ix.program_id == shared_state.MARGINFI_PROGRAM_ID
                and ix.data[:8] == MARGINFI_FLASHLOAN_START
            ),
            -1,
        )
        _repay_idx = next(
            (
                i
                for i, ix in enumerate(optimized_instructions)
                if ix.program_id == shared_state.MARGINFI_PROGRAM_ID
                and ix.data[:8] == MARGINFI_FLASHLOAN_END
            ),
            -1,
        )

        # Find wSOL close (SPL CloseAccount discriminator)
        _SPL_TK = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
        _wsol_close_idx = next(
            (
                i
                for i, ix in enumerate(optimized_instructions)
                if ix.program_id == _SPL_TK
                and len(ix.data) >= 8
                and ix.data[:8] == CLOSE_ACCOUNT_DISCRIMINATOR
            ),
            -1,
        )

        _violation = None
        if _borrow_idx >= 0 and _cb_idx > 0 and _cb_idx > _borrow_idx:
            _violation = (
                f"ComputeBudget (idx={_cb_idx}) found AFTER Borrow (idx={_borrow_idx})"
            )
        if _borrow_idx >= 0 and _repay_idx >= 0 and _repay_idx <= _borrow_idx:
            _violation = (
                f"Repay (idx={_repay_idx}) not AFTER Borrow (idx={_borrow_idx})"
            )
        if _borrow_idx >= 0 and _wsol_close_idx >= 0 and _wsol_close_idx < _repay_idx:
            _violation = (
                f"wSOL close (idx={_wsol_close_idx}) before Repay (idx={_repay_idx})"
            )
        if (
            _repay_idx >= 0
            and _borrow_idx >= 0
            and _wsol_close_idx >= 0
            and _wsol_close_idx < _borrow_idx
        ):
            _violation = (
                f"wSOL close (idx={_wsol_close_idx}) before Borrow (idx={_borrow_idx})"
            )

        if _violation:
            logger.error(
                f"🚨 ATOMIC SEQUENCE VIOLATION: {_violation} — refusing to compile"
            )
            return None

        # Task 4: Transaction Size Hard-Cap — 1180 bytes (well below 1232-byte MTU)
        # Provides headroom for unexpected Token-2022 transfer hook account metas.
        tx_size = len(bytes(tx))
        if tx_size > 1180:
            logger.warning(
                f"⚠️ TX rejected: size {tx_size} > 1180 bytes (MTU safety cap). Dropping to avoid silent network drop."
            )
            return None

        return base64.b64encode(bytes(tx)).decode("ascii")
    except (ValueError, TypeError, SystemError) as key_err:
        # FIX 198: Catch fatal signature/keypair errors and halt the bot
        logger.critical(f"🚨 CRITICAL WALLET ERROR: Private key is corrupted or invalid! {key_err}. Stopping bot.")
        try:
            import src.ingest.shared_state as _ss
            _ss.GLOBAL_STOP_EVENT.set()
        except Exception:
            pass
        return None
    except Exception as e:
        logger.debug(f"Tx construction error: {e}")
        return None


async def reconcile_inflight_bundles(session: aiohttp.ClientSession, rpc_url: str):
    """Reconcile inflight bundles on startup: check status and refund if failed."""
    try:
        import aiosqlite
        db_path = "bot_history.db"
        async with aiosqlite.connect(db_path, timeout=10) as db:
            cursor = await db.execute(
                "SELECT bundle_id, tx_sigs_json, deducted_sol, sent_at FROM inflight_bundles WHERE status = 'sent'"
            )
            rows = await cursor.fetchall()

        if not rows:
            logger.info("No inflight bundles to reconcile")
            return

        logger.info(f"🔄 Reconciling {len(rows)} inflight bundles...")
        for bundle_id, tx_sigs_json, deducted_sol, sent_at in rows:
            try:
                sigs = orjson.loads(tx_sigs_json)
                if not sigs:
                    continue

                # Check transaction status via RPC
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getSignatureStatuses",
                    "params": [sigs],
                }
                import src.ingest.shared_state as shared_state
                async with shared_state.rpc_limiter:
                    async with session.post(rpc_getter(), json=payload, timeout=timeout) as resp:
                        if resp.status == 200:
                            data = orjson.loads(await resp.read())
                            statuses = data.get("result", {}).get("value", [])

                        for sig_status in statuses:
                            if sig_status is None:
                                # Transaction not found by immediate status check — check if older than 60 seconds
                                if time.time() - sent_at > 60:
                                    # FIXED: Защита от фантомного баланса. Перед возвратом проверяем историю транзакций
                                    # на случай, если бандл подтвердился с опозданием.
                                    try:
                                        payload_history = {
                                            "jsonrpc": "2.0",
                                            "id": 1,
                                            "method": "getSignatureStatuses",
                                            "params": [sigs, {"searchTransactionHistory": True}]
                                        }
                                        async with session.post(rpc_url, json=payload_history, timeout=5.0) as hist_resp:
                                            if hist_resp.status == 200:
                                                hist_data = orjson.loads(await hist_resp.read())
                                                hist_statuses = hist_data.get("result", {}).get("value", [])
                                                
                                                # Если в истории транзакция найдена и подтверждена, отменяем возврат
                                                if hist_statuses and hist_statuses[0] is not None:
                                                    h_status = hist_statuses[0].get("confirmation_status")
                                                    if h_status in ("confirmed", "finalized") and hist_statuses[0].get("err") is None:
                                                        logger.info(f"Double-Credit Prevented: bundle {bundle_id[:12]} confirmed late. No refund applied.")
                                                        continue
                                                    # FIX 208: Network Reorg/Revert handling
                                                    elif hist_statuses[0].get("err") is not None:
                                                        logger.warning(f"🚨 Network Reorg/Revert detected for {bundle_id[:12]}: applying refund.")
                                                        # Let it fall through to the refund logic below
                                    except Exception as history_err:
                                        logger.debug(f"History cross-validation failed: {history_err}")

                                    async with shared_state.stats_lock:
                                        shared_state.stats["virtual_balance"] += deducted_sol
                                    async with aiosqlite.connect(db_path, timeout=10) as db:
                                        await db.execute(
                                            "UPDATE inflight_bundles SET status = 'refunded', finalized_at = ? WHERE bundle_id = ?",
                                            (time.time(), bundle_id),
                                        )
                                        await db.commit()
                                    logger.warning(
                                        f"Recovery: refunded {deducted_sol:.6f} SOL for stale bundle {bundle_id[:12]} (not found on-chain)"
                                    )
                                continue
                            err = sig_status.get("err")

                            if err is not None:
                                # Transaction failed — refund virtual balance
                                async with shared_state.stats_lock:
                                    shared_state.stats["virtual_balance"] += deducted_sol
                                async with aiosqlite.connect(db_path, timeout=10) as db:
                                    await db.execute(
                                        "UPDATE inflight_bundles SET status = 'refunded', finalized_at = ? WHERE bundle_id = ?",
                                        (time.time(), bundle_id),
                                    )
                                    await db.commit()
                                logger.warning(
                                    f"Recovery: refunded {deducted_sol:.6f} SOL for failed bundle {bundle_id[:12]}"
                                )
                            elif sig_status.get("confirmation_status") in ("confirmed", "finalized"):
                                # FIX 173: Detect Late Landing anomalies
                                landed_slot = sig_status.get("slot", 0)
                                sent_slot = shared_state.stats.get("current_slot", 0)
                                if landed_slot > 0 and sent_slot > 0 and (landed_slot - sent_slot) > 2:
                                    logger.warning(
                                        f"⚠️ LATE LANDING DETECTED: Bundle {bundle_id[:12]} landed {landed_slot - sent_slot} slots late! "
                                        f"Sent: {sent_slot}, Landed: {landed_slot}. Actual profit may have degraded due to pool state shift."
                                    )
                                async with aiosqlite.connect(db_path, timeout=10) as db:
                                    await db.execute(
                                        "UPDATE inflight_bundles SET status = 'confirmed', finalized_at = ? WHERE bundle_id = ?",
                                        (time.time(), bundle_id),
                                    )
                                    await db.commit()
                                logger.info(
                                    f"Recovery: bundle {bundle_id[:12]} confirmed already on-chain"
                                )
            except Exception as e:
                logger.warning(f"Recovery error for bundle {bundle_id[:12]}: {e}")
    except Exception as e:
        logger.warning(f"Reconciliation error: {e}")

async def lst_depeg_scanner(
    session,
    cfg,
    rpc_manager,
    keypair,
    jito_executor,
    webhook_trigger=None,
    blockhash_mgr=None,
):
    """Main LST Depeg Flash-Arb scanner loop.

    Continuously monitors fair price vs market price for LST tokens
    (jitoSOL, mSOL, bSOL). When a depeg exceeds the threshold:

    """
    global _oracle_stale_hit, _oracle_stale_asset_hint
    tx_builder = JupiterTxBuilder(
        session=session,
        rpc_getter=lambda: rpc_manager.get_rpc(),
    )
    rpc_url = rpc_manager.get_rpc()

    # Initialize components
    fair_price_monitor = LstFairPriceMonitor(
        session=session,
        rpc_url=rpc_url,
        poll_interval=cfg.LST_SCAN_INTERVAL,
        optimal_trade_sizer=trade_sizer,
    )
    route_aggregator = LstRouteAggregator(
        session=session,
        jupiter_api_key=cfg.JUPITER_API_KEY,
        slippage_bps=cfg.SLIPPAGE_BPS,
        sanctum_enabled=cfg.SANCTUM_ROUTER_ENABLED,
    )
    flash_sim = FlashSimulator(
        session=session,
        rpc_url=rpc_url,
    )

    # Pre-Trade Guard: prevent sending unprofitable bundles (right before jito_executor.send_bundle)
    pre_trade_guard = PreTradeGuard(session=session, rpc_url=rpc_url)

    # ── Fix 5 (Strict Gas Tank): never trade if balance < 0.005 SOL ──────────
    sol_mint_str = str(TOKENS["SOL"])
    if sol_mint_str not in MARGINFI_BANKS:
        logger.error("MarginFi SOL bank not configured — LST scanner disabled")
        return
    bank_cfg = MARGINFI_BANKS[sol_mint_str]

    min_profit_lamports = int(cfg.MIN_NET_PROFIT_BUFFER_SOL * 1_000_000_000)
    # Phase 21: Adjust min profit for Token-2022 transfer fees (silent capital loss)
    try:
        _ptg = PreTradeGuard(session=session, rpc_url=rpc_url)
        _adjusted = await _ptg.get_adjusted_profit_threshold(
            lst_mint, min_profit_lamports / 1e9, rpc_url,
            trade_volume_sol=cfg.FLASH_LOAN_SIZE_SOL,
        )
        if abs(_adjusted - min_profit_lamports / 1e9) > 1e-12:
            min_profit_lamports_orig = min_profit_lamports
            min_profit_lamports = int(_adjusted * 1e9)
            logger.info(f"💰 Phase 21: min profit adjusted for Token-2022 fee: "
                        f"{min_profit_lamports_orig/1e9:.6f} → {min_profit_lamports/1e9:.6f} SOL")
    except Exception as _e21:
        logger.debug(f"Phase 21 fee adjustment skipped: {_e21}")
    cycle_count = 0

    logger.debug(
        f"🚀 LST Depeg Scanner started | "
        f"threshold={cfg.LST_DEPEG_THRESHOLD_BPS} BPS | "
        f"flash_loan={cfg.FLASH_LOAN_SIZE_SOL} SOL | "
        f"profit_buffer={cfg.MIN_NET_PROFIT_BUFFER_SOL} SOL | "
        f"sanctum={'ON' if cfg.SANCTUM_ROUTER_ENABLED else 'OFF'}"
    )

    # Warm-up: initial price fetch
    await fair_price_monitor.update_fair_prices()
    await fair_price_monitor.update_market_prices()
    status = fair_price_monitor.get_status()
    logger.debug(f"📊 Initial fair prices: {status['fair_prices']}")
    logger.debug(f"📊 Initial market prices: {status['market_prices']}")

    while not shared_state.GLOBAL_STOP_EVENT.is_set():
        cycle_count += 1

        # Fix 6 + 67: Balance Lock Guard — pause if lock is active
        if (
            shared_state._balance_lock_paused
            and time.time() < shared_state._balance_lock_pause_until
        ):
            _lock_wait_ms = (
                shared_state._balance_lock_pause_until - time.time()
            ) * 1000
            logger.debug(
                f"🔒 Balance Lock active — waiting {_lock_wait_ms:.0f}ms (lst_depeg_scanner)"
            )
            await asyncio.sleep(
                max(0, shared_state._balance_lock_pause_until - time.time())
            )

            # ── Step 1: Update prices and detect depeg ────────────────────
            # FIX 294: Parallelize MarginFi liquidity + price updates to save ~150-200ms
            liq_task = asyncio.create_task(
                tx_builder.get_max_marginfi_borrow(str(bank_cfg["liquidity_vault"]))
            )
            fair_task = asyncio.create_task(fair_price_monitor.update_fair_prices())
            market_task = asyncio.create_task(
                fair_price_monitor.update_market_prices(price_matrix)
            )

            price_results = await asyncio.gather(liq_task, fair_task, market_task, return_exceptions=True)

            if isinstance(price_results[0], Exception):
                logger.debug(f"⚠️ MarginFi liquidity fetch failed: {price_results[0]}")
                borrow_lamports = int(cfg.FLASH_LOAN_SIZE_SOL * 1_000_000_000)
            else:
                borrow_lamports = price_results[0] or 1_000_000_000

            if isinstance(price_results[1], Exception) or isinstance(price_results[2], Exception):
                logger.debug("⚠️ Fair/Market price update failed during parallel gather. Skipping tick.")
                await asyncio.sleep(cfg.LST_SCAN_INTERVAL)
                continue

            # DYNAMIC SIZING: Feed 95% vault into OptimalTradeSizer to find peak of AMM curve
            optimal = trade_sizer.find_optimal_trade_size(
                routes=[],
                amount_in=borrow_lamports,
                decimals_in=9,
                decimals_out=9,
                jito_tip_sol=0.0001,
            )
            if (
                optimal and int(optimal) > 1_000_000
            ):
                borrow_lamports = int(optimal)
                logger.debug(
                    f"📈 LST optimal size: {borrow_lamports/1e9:.4f} SOL (AMM curve peak)"
                )

            current_native_balance = shared_state.stats.get(
                "last_balance", shared_state.stats.get("virtual_balance", 0.017)
            )
            _estimated_slippage_pct = max(0.001, cfg.SLIPPAGE_BPS / 10000.0)
            slippage_pegged_lamports = (
                trade_sizer.get_slippage_pegged_borrow_lamports(
                    wallet_native_balance_sol=current_native_balance,
                    pool_slippage_pct=_estimated_slippage_pct,
                    bank_liquidity_lamports=borrow_lamports,
                )
            )
            if borrow_lamports > slippage_pegged_lamports:
                logger.debug(
                    f"📉 Slippage-Pegged cap: {borrow_lamports/1e9:.4f} -> {slippage_pegged_lamports/1e9:.4f} SOL"
                )
                borrow_lamports = slippage_pegged_lamports

            if borrow_lamports < 1_000_000:
                logger.warning(f"📉 MarginFi SOL Bank is low ({borrow_lamports/1e9:.4f} SOL). Waiting...")
                await asyncio.sleep(10)
                continue

            # Check for webhook trigger
            force_scan = False
            try:
                while not webhook_trigger.empty():
                    opportunity = webhook_trigger.get_nowait()
                    if opportunity.get("trigger_immediate_scan"):
                        logger.debug("🚨 Webhook triggered immediate LST scan")
                        force_scan = True
                        break  # Process one trigger per cycle
            except asyncio.QueueEmpty:
                pass

            signals = fair_price_monitor.get_depeg_signals(
                threshold_bps=cfg.LST_DEPEG_THRESHOLD_BPS
            )

            if not signals and not force_scan:
                if cycle_count % 120 == 0:  # Log status every ~60 sec
                    status = fair_price_monitor.get_status()
                    sim_stats = flash_sim.get_stats()
                    logger.debug(
                        f"📡 LST Scanner heartbeat #{cycle_count} | "
                        f"fair={status['fair_prices']} | "
                        f"sims={sim_stats['total_simulations']} "
                        f"(ok={sim_stats['profitable']}, blocked={sim_stats['unprofitable']}, "
                        f"saved={sim_stats['gas_saved_sol']:.6f} SOL)"
                    )
                await asyncio.sleep(cfg.LST_SCAN_INTERVAL)
                continue

            # ── Step 2: Process each depeg signal ─────────────────────────
            for signal in signals:
                logger.debug(
                    f"🔔 DEPEG detected: {signal.token_symbol} | "
                    f"fair={signal.fair_price:.6f} market={signal.market_price:.6f} | "
                    f"dev={signal.deviation_bps:+.1f} BPS → {signal.direction}"
                )

                # FIX #1: Gas Tank Check moved INSIDE signal loop (signal.token_mint must exist)
                try:
                    from src.ingest.shared_state import get_ata_rent_for_mint
                    estimated_rent = get_ata_rent_for_mint(str(signal.token_mint)) if str(signal.token_mint) not in shared_state.ATA_CACHE else 0.0
                    _gas_ok, _gas_avail = await PreTradeGuard.check_gas_tank(
                        shared_state.stats.get("virtual_balance", 0.0), estimated_rent
                    )
                    if not _gas_ok:
                        continue
                except Exception:
                    pass

                # ── Step 3: Find best route ───────────────────────────────
                if borrow_lamports <= 0:  # Микро-баланс: убран жёсткий порог 1 SOL
                    logger.warning("MarginFi SOL bank is dry. Waiting...")
                    await asyncio.sleep(5)
                    continue

                current_wallet_balance = shared_state.stats.get(
                    "last_balance", 0.017
                )  # Task 14: wallet balance for direct-route guard
                route = await route_aggregator.find_best_route(
                    borrow_amount_lamports=borrow_lamports,
                    lst_mint=signal.token_mint,
                    direction=signal.direction,
                    base_fee_sol=cfg.BASE_FEE,
                    priority_fee_sol=cfg.PRIORITY_FEE,
                    jito_tip_sol=0.0,  # Placeholder — tip optimized below after route is confirmed
                    min_profit_buffer_sol=cfg.MIN_NET_PROFIT_BUFFER_SOL,
                    wallet_balance_sol=current_wallet_balance,  # Task 14: pass balance to enforce direct routes under 0.5 SOL
                    active_slippage_bps=cfg.SLIPPAGE_BPS,
                )

                if route is None:
                    continue

                # ── ExactIn Safety: Validate debt coverage via otherAmountThreshold ─────
                # Ensures worst-case swap output covers MarginFi repayment
                sell_quote_resp = route.sell_quote.full_quote_response
                worst_case_out = int(
                    sell_quote_resp.get(
                        "otherAmountThreshold", sell_quote_resp.get("outAmount", 0)
                    )
                )
                if worst_case_out < borrow_lamports:
                    logger.warning(
                        f"🚫 Trade cancelled: worst-case out {worst_case_out} < debt {borrow_lamports} "
                        f"(slippage risk) for {signal.token_symbol}"
                    )
                    continue

                if not route.is_profitable:
                    continue

                # God-mode tip via bidding manager (tip_floor + step-up/down + capital guard)
                # Fix 2 (Unfunded Jito Tip): pass native SOL balance to cap tip
                current_native_for_tip = shared_state.stats.get("last_balance", 0.017)
                god_tip_lamports = jito_bidding_manager.calculate_blue_ocean_tip(
                    expected_profit_sol=route.profit_sol,
                    strategy="lst_depeg",
                    current_native_sol_balance=current_native_for_tip,
                )
                calculated_tip_lamports = god_tip_lamports
                if god_tip_lamports <= 0:
                    continue

                # Build tip lamports for trade execution (already optimized by bidding manager)
                jito_tip_lamports = god_tip_lamports

                # ── Task 13: InsufficientFunds Protection ─────────────────────────
                # Hard cap: tip must never exceed (native_balance - 0.0025) SOL.
                # 0.0025 SOL is the gas/rent safety reserve; exceeding it causes
                # InsufficientFundsForFee pre-flight failure on a 0.015 SOL wallet.
                current_native_for_tip = shared_state.stats.get("last_balance", 0.015)
                available_for_tip = (current_native_for_tip - 0.0025) * 1e9
                if available_for_tip <= 0:
                    logger.warning(
                        f"🚫 Native balance {current_native_for_tip:.6f} SOL < 0.0025 gas reserve "
                        f"— skipping {signal.token_symbol}"
                    )
                    continue
                capped_tip = min(jito_tip_lamports, int(available_for_tip))
                if capped_tip < 10000:
                    logger.warning(
                        f"⏭️ Tip {capped_tip} lamports below 10k minimum after balance cap "
                        f"(native={current_native_for_tip:.6f} SOL) — skipping {signal.token_symbol}"
                    )
                    continue
                jito_tip_lamports = capped_tip

                # ── Step 4: Build MarginFi flash loan TX ──────────────────
                if not cfg.MARGINFI_ACCOUNT_PUBKEY:
                    logger.error("MARGINFI_ACCOUNT not set — cannot execute flash loan")
                    continue

                # Fix 2: Oracle Pivot consumption — flip borrow asset if prior StaleOracle hit
                _pivot_borrow_mint = None
                if _oracle_stale_hit:
                    _pivot_borrow_mint = (
                        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
                        if "SOL" in _oracle_stale_asset_hint
                        else "So11111111111111111111111111111111111111112"
                    )
                    _oracle_stale_hit = False

                fl_result = await tx_builder.build_marginfi_flashloan_tx(
                    wallet_pubkey=str(keypair.pubkey()),
                    borrow_amount_lamports=borrow_lamports,
                    buy_quote_response=route.buy_quote.full_quote_response,
                    sell_quote_response=route.sell_quote.full_quote_response,
                    marginfi_account=cfg.MARGINFI_ACCOUNT_PUBKEY,
                    bank_pubkey=str(bank_cfg["bank"]),
                    bank_liquidity_vault=str(bank_cfg["liquidity_vault"]),
                    bank_liquidity_vault_authority=str(
                        bank_cfg["liquidity_vault_authority"]
                    ),
                     use_jito=True,
                     strategy_type=2,
                     tip_accounts=(
                         jito_executor.tip_accounts if jito_executor else None
                     ),  # Fix 2: dynamic tip accounts
                     expected_profit_sol=route.profit_sol,  # Dynamic Rent Guard
                     jito_tip_lamports=jito_tip_lamports,  # FIX #2: pass calculated tip
                     borrow_mint=_pivot_borrow_mint,  # FIX: Использование разворота (Pivot) при старом оракуле
                 )

                if not fl_result:
                    logger.warning(
                        f"Failed to build flash loan TX for {signal.token_symbol}"
                    )
                    continue

                # ── Step 5: Resolve ALTs and build final transaction ──────
                instructions = fl_result["instructions"]
                alt_pubkeys = fl_result["address_lookup_table_pubkeys"]

                # Fetch ALT account data
                address_lookup_tables = []
                if alt_pubkeys:
                    try:
                        alt_payload = {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "getMultipleAccounts",
                            "params": [
                                [str(pk) for pk in alt_pubkeys],
                                {"encoding": "base64"},
                            ],
                        }
                        timeout = aiohttp.ClientTimeout(total=2.0)
                        import src.ingest.shared_state as shared_state
                        async with shared_state.rpc_limiter:
                            async with session.post(
                                rpc_manager.get_rpc(), json=alt_payload, timeout=timeout
                            ) as resp:
                                if resp.status == 200:
                                    alt_data = orjson.loads(await resp.read())
                                if (
                                    "result" in alt_data
                                    and "value" in alt_data["result"]
                                ):
                                    for acct in alt_data["result"]["value"]:
                                        if acct:
                                            try:
                                                b64_data = acct["data"][0]
                                                padded = b64_data + "=" * (
                                                    -len(b64_data) % 4
                                                )
                                                raw_data = base64.b64decode(padded)
                                                keys = []
                                                # Phase 32: Dynamic ALT header parsing
                                                header_len = (
                                                    56 if raw_data[21] == 1 else 24
                                                )
                                                for i in range(
                                                    header_len, len(raw_data), 32
                                                ):
                                                    keys.append(
                                                        Pubkey.from_bytes(
                                                            raw_data[i : i + 32]
                                                        )
                                                    )
                                                # Use the pubkey from alt_pubkeys
                                                index = alt_data["result"][
                                                    "value"
                                                ].index(acct)
                                                alt_acct = AddressLookupTableAccount(
                                                    key=alt_pubkeys[index],
                                                    addresses=keys,
                                                )
                                                address_lookup_tables.append(alt_acct)
                                            except Exception:
                                                pass
                    except Exception as e:
                        logger.debug(f"ALT fetch error: {e}")

                if alt_pubkeys and not address_lookup_tables:
                    logger.warning(
                        f"⚠️ ALT RESOLUTION FAILURE: Could not resolve {len(alt_pubkeys)} ALTs via RPC. "
                        f"Aborting transaction to prevent MTU (1232 bytes) packet overflow."
                    )
                    continue  # Пропускаем эту попытку до следующего слота

                # FIX 187: Deduplicate blockhash fetch and correctly update global cache variables
                global cached_blockhash, cache_time
                blockhash = cached_blockhash
                if not blockhash or time.time() - cache_time > 2:
                    blockhash = await get_current_blockhash(
                        session, rpc_manager.get_rpc()
                    )
                    if blockhash:
                        cached_blockhash = blockhash
                        cache_time = time.time()
                if not blockhash:
                    logger.warning("Cannot get blockhash — skipping")
                    continue

                try:
                    msg = MessageV0.try_compile(
                        payer=keypair.pubkey(),
                        instructions=instructions,
                        address_lookup_table_accounts=address_lookup_tables,
                        recent_blockhash=Hash.from_string(blockhash),
                    )
                    tx = VersionedTransaction(msg, [keypair])
                    tx_b64 = base64.b64encode(bytes(tx)).decode("ascii")
                except Exception as e:
                    logger.warning(f"TX compile error: {e}")
                    continue

                # ── Step 6: Pre-flight simulation ─────────────────────────
                strategy = "lst_depeg"
                if not is_strategy_allowed(strategy):
                    continue
                is_profitable, reason, sim_result = (
                    await flash_sim.validate_profitability(
                        tx_b64=tx_b64,
                        tx_signer_pubkey=str(keypair.pubkey()),
                        min_profit_lamports=min_profit_lamports,
                        tip_lamports=jito_tip_lamports,
                        priority_fee_lamports=int(cfg.PRIORITY_FEE * 1e9),
                    )
                )

                if not is_profitable:
                    # FIXED: Инкремент счетчика неудачных симуляций
                    PROMETHEUS_SIM_FAILS.inc()
                    # Fix 2: MarginFi Flash-Loan Asset Pivot
                    if "StaleOracle" in reason or "stale" in reason.lower():
                        # global _oracle_stale_hit, _oracle_stale_asset_hint  # (moved to function top)
                        _oracle_stale_hit = True
                        _oracle_stale_asset_hint = "USDC" if "USDC" in reason else "SOL"

                    if "sim" in reason.lower() or "fail" in reason.lower():
                        record_sim_failure(strategy)
                    continue  # Skip this opportunity — do NOT send unprofitable tx to Jito

                else:
                    # ── Async: record profitable candidate before execution ──────────
                    if TRADE_LOG_QUEUE:
                        await TRADE_LOG_QUEUE.put(
                            orjson.dumps(
                                {
                                    "ts": time.time(),
                                    "event": "sim_ok",
                                    "strategy": "lst_depeg",
                                    "token": signal.token_symbol,
                                }
                            ).decode()
                        )

                    # ── Step 7: Send via Jito bundle ──────────────────────────
                    if JITO_AVAILABLE:
                        tx_with_tip = tx  # Placeholder - tip will be added by JitoBundleHandler/JitoExecutor

                        # ── Pre-Trade Guard: Re-check profit right before send_bundle (Fix Slippage Re-check)
                        # Between fetching the quote and sending, 100-300ms may have passed.
                        # If the price slipped and eats the profit — abort. Better to skip than burn gas.
                        base_fee_lamports = int(cfg.PRIORITY_FEE * 1e9)
                        import src.ingest.shared_state as shared_state
                        _cu_limit = shared_state.DYNAMIC_CU_CACHE.get("flash_arbitrage_MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA", 600_000)
                        _priority_fee_micro = 1 if JITO_AVAILABLE else int(cfg.PRIORITY_FEE * 1e6)
                        est_gas_lamports = 5000 + (_priority_fee_micro * _cu_limit // 1_000_000)
                        expected_profit_lamports = int(route.profit_sol * 1e9)
                        from src.ingest.shared_state import get_ata_rent_for_mint
                        _rent_lamports = 0 if str(signal.token_mint) in shared_state.ATA_CACHE else int(get_ata_rent_for_mint(str(signal.token_mint)) * 1e9)
                        _priority_fee_lamports = int(cfg.PRIORITY_FEE * 1e9)

                        trade_ok, trade_reason, _ = (
                            await pre_trade_guard.check_profit_before_execution(
                                input_mint=str(
                                    route.buy_quote.input_mint
                                ),  # entry token (SOL for buy-LST)
                                output_mint=str(
                                    route.buy_quote.output_mint
                                ),  # exit token (LST for buy-LST)
                                amount_lamports=route.borrow_amount_lamports,
                                jito_tip_lamports=jito_tip_lamports,
                                base_fee_lamports=base_fee_lamports + est_gas_lamports,
                                expected_profit_lamports=expected_profit_lamports,
                                priority_fee_lamports=_priority_fee_lamports,
                                ata_rent_lamports=_rent_lamports,
                                quote_url=cfg.JUPITER_QUOTE_URL,
                                slippage_bps=cfg.SLIPPAGE_BPS,
                                is_circular=True,  # FIX: Требуем двухстороннюю проверку профита для Flash-loan
                            )
                        )
                        if not trade_ok:
                            logger.warning(
                                f"🚫 Pre-Trade Guard BLOCKED: {trade_reason} | {signal.token_symbol}"
                            )
                            continue

                        await shared_state.increment_stat("bundle_send_attempts")

                        # ── Fix "Blocking Discovery": Fire-and-Forget Execution ──────────
                        # send_bundle itself is ~200ms, wait_for_confirmation wall-clock is up to 30 s.
                        # Both are wrapped in a background task so the worker loop never blocks
                        # and continues scanning new pairs while this bundle is pending.
                        async def _post_send_processing(
                            b_result,
                            b_route,
                            b_tip_lamports,
                            b_token_symbol,
                            b_borrow_lamports,
                        ):
                            if not b_result.get("success"):
                                return

                            await shared_state.increment_stat("bundle_successes")
                            await shared_state.increment_stat("trades")
                            bundle_id = b_result.get("bundle_id", "")

                            # ── Async trade record (no blocking write) ─────────────────
                            if TRADE_LOG_QUEUE:
                                await TRADE_LOG_QUEUE.put(
                                    orjson.dumps(
                                        {
                                            "ts": time.time(),
                                            "event": "bundle_sent",
                                            "strategy": "lst_depeg",
                                            "token": b_token_symbol,
                                            "borrow_sol": round(
                                                b_borrow_lamports / 1e9, 6
                                            ),
                                            "tip_sol": round(b_tip_lamports / 1e9, 6),
                                            "bundle_id": bundle_id,
                                        }
                                    ).decode()
                                )

                            # Wait for confirmation in background (non-blocking)
                            confirmation = await jito_executor.wait_for_confirmation(
                                bundle_id, max_wait_time=5.0
                            )
                            jito_bidding_manager.record_bundle_result(
                                "lst_depeg",
                                confirmation.get("status")
                                in ["confirmed", "finalized"],
                                jito_tip_lamports  # FIX 205
                            )
                            if confirmation.get("status") in ["confirmed", "finalized"]:
                                if TRADE_LOG_QUEUE:
                                    await TRADE_LOG_QUEUE.put(
                                        orjson.dumps(
                                            {
                                                "ts": time.time(),
                                                "event": "confirmed",
                                                "strategy": "lst_depeg",
                                                "bundle_id": bundle_id,
                                                "status": confirmation.get("status"),
                                            }
                                        ).decode()
                                    )
                                # Task 6 — Zero-Delay Post-Trade Dust Sweep
                                try:
                                    from src.ingest.dust_sweeper import DustSweeper

                                    _sweeper = DustSweeper(keypair, rpc_url, session)
                                    _recovered = (
                                        await _sweeper.sweep_after_successful_tx()
                                    )
                                except Exception:
                                    pass
                            else:
                                logger.warning(
                                    f"❌ LST bundle status: {confirmation.get('status', 'unknown')} "
                                    f"| {signal.token_symbol}"
                                )
                                jito_bidding_manager.record_trade_result(
                                    "lst_depeg", False
                                )

                            tx_with_tip = tx  # Placeholder — tip will be added by JitoBundleHandler/JitoExecutor
                            bundle_result = await jito_executor.send_bundle(
                                [tx_with_tip],
                                tip_amount_lamports=jito_tip_lamports,
                                deducted_amount=jito_tip_lamports / 1e9,
                            )
                            # Сохраняем сильную ссылку в глобальный набор shared_state.active_tasks (Fix GC Trap)
                            task = asyncio.create_task(
                                _post_send_processing(
                                    bundle_result,
                                    route,
                                    jito_tip_lamports,
                                    str(signal.token_symbol),
                                    route.borrow_amount_lamports,
                                )
                            )
                            shared_state.active_tasks.add(task)
                            task.add_done_callback(background_task_callback)

                    else:
                        logger.warning(
                            "❌ Simulation failed or Jito unavailable. Skipping trade for capital protection."
                        )

        await asyncio.sleep(cfg.LST_SCAN_INTERVAL)


# ═══════════════════════════════════════════════════════════════════════════
#  KAMINO FLASH-LIQUIDATION SCANNER
# ═══════════════════════════════════════════════════════════════════════════


async def lst_unstake_arbitrage_scanner(
    session,
    cfg,
    rpc_manager,
    keypair,
    jito_executor,
    jito_bidding_manager=None,
    data_aggregator=None,
):
    """Main LST instant unstake arbitrage scanner for MarginFi flash loans.

    Monitors Raydium LST/SOL pools vs protocol unstake rates, executes
    arbitrage when market price < protocol price.
    """
    rpc_url = rpc_manager.get_rpc()

    # Initialize components
    tx_builder = JupiterTxBuilder(
        session=session,
        rpc_getter=lambda: rpc_manager.get_rpc(),
    )
    unstake_arb = LstInstantUnstakeArbitrage(
        session=session,
        rpc_url=rpc_url,
        marginfi_account=cfg.MARGINFI_ACCOUNT_PUBKEY,
        lst_mints=[str(TOKENS["jitoSOL"]), str(TOKENS["mSOL"]), str(TOKENS["bSOL"]), str(TOKENS["INF"]), str(TOKENS["JupSOL"])],  # FIX 111
        min_deviation_pct=cfg.LST_UNSTAKE_MIN_DEVIATION_PCT,
        tx_builder=tx_builder,
        optimal_trade_sizer=trade_sizer,
        rpc_getter=lambda: rpc_manager.get_rpc(),
        cfg=cfg,
        data_aggregator=data_aggregator,
        data_collector=data_collector,
        stats=shared_state.stats,
        stats_lock=shared_state.stats_lock,
        jito_bidding_manager=jito_bidding_manager,
    )

    cycle_count = 0

    logger.info(
        f"🚀 LST Unstake Arbitrage Scanner started | "
        f"min_deviation={cfg.LST_UNSTAKE_MIN_DEVIATION_PCT}% | "
        f"scan_interval={cfg.LST_UNSTAKE_SCAN_INTERVAL}s"
    )

    while not shared_state.GLOBAL_STOP_EVENT.is_set():
        cycle_count += 1
        try:
            # Fix 5: Strict Gas Tank — stop if balance < 0.005 SOL
            _gas_ok, _gas_avail = await PreTradeGuard.check_gas_tank(
                shared_state.stats.get(
                    "virtual_balance", shared_state.stats.get("last_balance", 0.0)
                ),
                0.0,  # Task 41: estimated_rent_sol (LST unstake — rent already handled at route level)
            )
            if not _gas_ok:
                logger.critical(
                    f"🚨 STRICT GAS TANK: LST Unstake scanner halted — balance below 0.005 SOL"
                )
                await asyncio.sleep(30)
                continue

            # ── Step 1: Scan for unstake arbitrage opportunities ───────────
            opportunities = await unstake_arb.scan_unstake_opportunities()

            if not opportunities:
                if cycle_count % 120 == 0:  # Log status every ~4 min
                    logger.debug(f"📡 LST Unstake Scanner heartbeat #{cycle_count}")
                await asyncio.sleep(cfg.LST_UNSTAKE_SCAN_INTERVAL)
                continue

            logger.debug(f"🎯 Found {len(opportunities)} LST unstake opportunities")

            # ── Step 2: Execute arbitrage opportunities ─────────────────────
            for opportunity in opportunities:
                # opportunity is a dict with keys: lst_mint, expected_profit_lamports, borrow_amount, quote
                lst_mint_str = opportunity.get("lst_mint", "")
                expected_profit_sol = (
                    opportunity.get("expected_profit_lamports", 0) / 1e9
                )
                borrow_amount_sol = opportunity.get("borrow_amount", 0) / 1e9

                logger.info(
                    f"💰 LST Unstake opportunity: {str(lst_mint_str)[:8]}... | "
                    f"borrow={borrow_amount_sol:.6f} SOL | "
                    f"profit={expected_profit_sol:.6f} SOL"
                )

                # Execute the arbitrage
                success = await unstake_arb.execute_unstake_arbitrage(
                    opportunity,
                    tx_builder,
                    keypair,
                    jito_executor,
                    jito_bidding_manager,
                )

                if success:
                    await shared_state.increment_stat("trades")
                    logger.info(
                        f"✅ LST unstake arbitrage successful | profit={expected_profit_sol:.6f} SOL"
                    )
                else:
                    await shared_state.increment_stat("sim_fails")
                    record_sim_failure("lst_unstake")
                    logger.warning("❌ LST unstake arbitrage failed")

                # Small delay between executions
                await asyncio.sleep(0.1)

        except Exception as e:
            logger.error(f"LST unstake scanner error: {e}")

        await asyncio.sleep(cfg.LST_UNSTAKE_SCAN_INTERVAL)


# ═══════════════════════════════════════════════════════════════════════════
#  BTC WRAPPER PEG ARBITRAGE SCANNER
# ═══════════════════════════════════════════════════════════════════════════


async def wrapper_peg_scanner(
    session,
    cfg,
    rpc_manager,
    keypair,
    jito_executor,
    execution_router=None,
):
    """BTC Wrapper Peg Arbitrage scanner (cbBTC/wBTC/tBTC).

    Monitors peg deviations between BTC wrapper tokens and executes
    a 3-leg flash loan arbitrage via execution_router.
    """
    rpc_url = rpc_manager.get_rpc()

    tx_builder = JupiterTxBuilder(
        session=session,
        rpc_getter=lambda: rpc_manager.get_rpc(),
    )

    borrow_env_sol = float(os.getenv("FLASH_LOAN_SIZE_SOL", "1.0"))

    wrapper_arb = WrapperPegArb(
        session=session,
        tx_builder=tx_builder,
        execution_router=execution_router,
        min_profit_sol=getattr(cfg, "MIN_PROFIT_THRESHOLD_SOL", 0.0005),
        price_matrix=price_matrix,
    )

    cycle_count = 0

    logger.info(
        f"🚀 Wrapper Peg Scanner started | "
        f"scan_interval={getattr(cfg, 'LST_UNSTAKE_SCAN_INTERVAL', 3.0)}s"
    )

    while not shared_state.GLOBAL_STOP_EVENT.is_set():
        cycle_count += 1
        try:
            _gas_ok, _ = await PreTradeGuard.check_gas_tank(
                shared_state.stats.get(
                    "virtual_balance", shared_state.stats.get("last_balance", 0.0)
                ),
                0.0,  # Task 41: estimated_rent_sol (wrapper peg — rent already handled at route level)
            )
            if not _gas_ok:
                logger.critical(
                    "🚨 STRICT GAS TANK: Wrapper Peg scanner halted — balance below 0.005 SOL"
                )
                await asyncio.sleep(30)
                continue

            sol_mint_str = "So11111111111111111111111111111111111111112"
            sol_price = 150.0
            sol_entry = price_matrix.get(sol_mint_str)
            if sol_entry:
                sol_price = sol_entry[0]
            borrow_usdc_lamports = int(borrow_env_sol * sol_price * 1_000_000)

            result = await wrapper_arb.scan_and_execute(borrow_usdc_lamports)
            trades = result.get("trades", [])
            if trades:
                await shared_state.increment_stat("trades", len(trades))
                logger.info(f"💰 Wrapper Peg: {len(trades)} trade(s) executed")

        except Exception as e:
            logger.error(f"Wrapper Peg scanner error: {e}")

        await asyncio.sleep(getattr(cfg, "LST_UNSTAKE_SCAN_INTERVAL", 3.0))


# ═══════════════════════════════════════════════════════════════════════════
#  ORDERBOOK-AMM BIPARTITE SOLVER SCANNER
# ═══════════════════════════════════════════════════════════════════════════


async def fetch_phoenix_orderbook(session, market_address: str):
    """Fetch Phoenix orderbook data."""
    # TODO: Implement Phoenix orderbook fetching
    return None


async def fetch_raydium_reserves(session, pool_address: str):
    """Fetch Raydium pool reserves."""
    # TODO: Implement Raydium reserves fetching
    return None


async def create_simple_dummy_tx(session, keypair, rpc_getter):
    """Create a simple dummy transaction for priority fee estimation"""
    try:
        # Create a minimal transfer transaction for fee estimation
        dummy_recipient = Pubkey.from_string(
            "11111111111111111111111111111112"
        )  # Dummy recipient
        transfer_ix = transfer(
            TransferParams(
                from_pubkey=keypair.pubkey(),
                to_pubkey=dummy_recipient,
                lamports=1,  # Minimal amount
            )
        )

        # Get recent blockhash
        payload = {"jsonrpc": "2.0", "id": 1, "method": "getLatestBlockhash"}
        timeout = aiohttp.ClientTimeout(total=1.0)
        import src.ingest.shared_state as shared_state
        async with shared_state.rpc_limiter:
            async with session.post(rpc_getter(), json=payload, timeout=timeout) as resp:
                if resp.status == 200:
                    data = orjson.loads(await resp.read())
                if "result" in data:
                    recent_blockhash = Hash.from_string(
                        data["result"]["value"]["blockhash"]
                    )

                    msg = MessageV0.try_compile(
                        payer=keypair.pubkey(),
                        instructions=[transfer_ix],
                        address_lookup_table_accounts=[],
                        recent_blockhash=recent_blockhash,
                    )
                    tx = VersionedTransaction(msg, [keypair])
                    return base64.b64encode(bytes(tx)).decode("ascii")
    except Exception as e:
        logger.debug(f"Dummy tx creation error: {e}")
    return None


async def get_dynamic_priority_fee(
    session, rpc_getter, serialized_tx, cfg, priority_level="Medium"
):
    """Get dynamic priority fee from Helius API"""
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "getPriorityFeeEstimate",
            "params": [
                {
                    "transaction": serialized_tx,
                    "options": {"priorityLevel": priority_level, "recommended": True},
                }
            ],
        }
        timeout = aiohttp.ClientTimeout(total=1.0)
        import src.ingest.shared_state as shared_state
        async with shared_state.rpc_limiter:
            async with session.post(rpc_getter(), json=payload, timeout=timeout) as resp:
                if resp.status == 200:
                    data = orjson.loads(await resp.read())
                if "result" in data and "priorityFeeEstimate" in data["result"]:
                    # Return as microlamports (int)
                    fee_microlamports = int(data["result"]["priorityFeeEstimate"])
                    return fee_microlamports
    except Exception as e:
        logger.debug(f"Priority fee API error: {e}")
    # Fallback to hardcoded value (convert SOL → micro-lamports/CU)
    default_cu = 200_000
    fallback_lamports = int(cfg.PRIORITY_FEE * 1e9)
    fallback_micro_lamports = int(fallback_lamports * 1e6 / default_cu)
    return max(50_000, fallback_micro_lamports)


async def _daily_cleanup(data_aggregator: DataAggregator):
    """Run daily cleanup of old data."""
    while True:
        # Wait until next day (simplified - runs every 24 hours)
        await asyncio.sleep(24 * 60 * 60)
        try:
            await data_aggregator.cleanup_old_data(keep_hours=336)
            logger.info("✅ Daily data cleanup completed")
        except Exception as e:
            logger.error(f"Daily cleanup failed: {e}")



async def get_current_blockhash(session, rpc_url):
    """Get current blockhash for transaction."""
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getLatestBlockhash",
            "params": [
                {"commitment": "confirmed"}
            ],  # Phase 48: Use confirmed for Jito bundle reliability
        }
        async with session.post(
            rpc_url, json=payload, timeout=aiohttp.ClientTimeout(total=1.0)
        ) as resp:
            if resp.status == 200:
                data = orjson.loads(await resp.read())
                if "result" in data:
                    return data["result"]["value"]["blockhash"]
    except Exception as e:
        logger.debug(f"Blockhash fetch failed: {e}")
    return None


def create_placeholder_arbitrage_tx(keypair, blockhash):
    """Create placeholder arbitrage transaction for testing."""
    # This would be replaced with actual transaction from template
    dummy_ix = transfer(
        TransferParams(
            from_pubkey=keypair.pubkey(),
            to_pubkey=Pubkey.from_string("11111111111111111111111111111112"),
            lamports=1000,
        )
    )

    msg = MessageV0.try_compile(
        payer=keypair.pubkey(),
        instructions=[dummy_ix],
        address_lookup_table_accounts=[],
        recent_blockhash=blockhash,
    )

    return VersionedTransaction(msg, [keypair])


async def mark_wsol_atomically_closed():
    """Fix 1 (wSOL Death Spiral): Mark that the atomic arb path just closed wSOL.

    build_native_flashloan_tx injects CloseAccount+CreateIdempotentATA for wSOL
    inside the arb transaction before the Jito tip.  The wallet_balance_listener
    must NOT run its own standalone CloseAccount transaction for the same ATA —
    that would race with the arb's close and waste gas.  Call this right after
    the arb bundle is sent (not confirmed — a failed bundle reverts atomically).
    """
    # Fix F: WSOL_JUST_CLOSED_ATOMICALLY read from shared_state
    shared_state.WSOL_JUST_CLOSED_ATOMICALLY = time.time()


async def check_bundle_confirmation(
    bundle_id,
    jito_executor,
    data_aggregator,
    tx_b64,
    tx_id,
    execution_time,
    session=None,
    keypair=None,
    rpc_getter=None,
    target_mint_ata=None,
    virtual_balance_to_deduct=0.0,
    new_atas_to_create=None,  # ФИКС 3: ATA кэшируем только после подтверждения
    real_profit_sol: float = 0.0,  # Task 43: фактический чистый профит сделки
):
    """Check bundle confirmation asynchronously without blocking."""
    try:
        confirmation = await jito_executor.wait_for_confirmation(
            bundle_id, max_wait_time=4.0
        )
        if confirmation.get("status") == "failed":
            logger.error(f"❌ ТРЕЙД УПАЛ (Bundle Failed): {confirmation}")
            await data_aggregator.log_tx_failed(bundle_id, confirmation, {"tx": tx_b64})

            # FIXED: Инкремент счетчика сбоев в Prometheus
            PROMETHEUS_SIM_FAILS.inc()

            error_msg = str(confirmation.get("error", "")).lower()
            err_class = classify_jito_error(error_msg)

            # ВЕТВЛЕНИЕ 1: Сбой из-за устаревшего блокхеша -> принудительный апдейт racing-менеджера
            if err_class == "BLOCKHASH_EXPIRED":
                logger.warning("⏰ Jito reported BlockhashNotFound/Expired! Force-refreshing blockhash immediately.")
                from src.ingest.blockhash_racing import get_blockhash_manager
                bh_mgr = get_blockhash_manager()
                if bh_mgr:
                    asyncio.create_task(bh_mgr.fetch_fresh_blockhash())

            # ВЕТВЛЕНИЕ 1.2: Account in use (Lock) -> Sleep 400ms (1 slot)
            elif err_class == "ACCOUNT_IN_USE":
                logger.warning("🔒 MarginFi Account locked/in use! Sleeping 1 slot (400ms) to allow lock release.")
                await asyncio.sleep(0.4)

            # ВЕТВЛЕНИЕ 2: Проскальзывание в пуле -> отправляем конкретную пару на 10-минутный cooldown
            elif "slippage" in error_msg or "custom program error: 0x1" in error_msg:
                logger.warning(f"🚫 Slippage Exceeded on-chain! Activating 10-minute cooldown for pair: {tx_id}")
                from src.ingest.shared_state import pair_reputation
                if pair_reputation:
                    pair_reputation.record_failure(tx_id, "slippage")

            # ♻️ 0ms Reconciler: Instantly refund virtual balance on failure
            if virtual_balance_to_deduct > 0:
                # FIX 103: Check if already refunded by jito_executor
                if bundle_id in jito_executor.pending_bundles and jito_executor.pending_bundles[bundle_id].get('refunded'):
                    pass
                else:
                    # Phase 19 T2: Deferred refund — don't instantly refund.
                    # Queue the bundle for 15s grace period. The balance_reconciler
                    # (runs every 30s) will catch late landings and adjust accordingly.
                    RECENTLY_TIMED_OUT_BUNDLES[bundle_id] = {
                        "virtual_balance_to_deduct": virtual_balance_to_deduct,
                        "timed_out_at": time.time(),
                        "jito_executor_ref": jito_executor,
                    }
                    logger.info(
                        f"♻️ Deferred Reconciler: {bundle_id} queued for 15s grace. "
                        f"Virtual balance NOT refunded yet ({virtual_balance_to_deduct:.6f} SOL at risk)."
                    )
                    # Spawn background task to process the deferred refund
                    task = asyncio.create_task(_monitor_timed_out_bundles())
                    shared_state.retain_background_task(task)

            # ── Этап 2: Record loss in CapitalProtection ──────────────────────
            if shared_state.capital_protection and virtual_balance_to_deduct > 0:
                shared_state.capital_protection.record_trade(-virtual_balance_to_deduct)

            # MEV: Losing an auction is normal. Only trigger circuit breaker for critical errors.
            error_msg = str(confirmation.get("error", "")).lower()
            critical_errors = [
                "insufficient funds",
                "account not found",
                "unauthorized",
                "invalid signer",
            ]
            if any(err in error_msg for err in critical_errors):
                shared_state.GLOBAL_STOP_EVENT.set()
                logger.critical(
                    f"🛑 CIRCUIT BREAKER ACTIVATED: {error_msg.upper()}. Скрипт остановлен для анализа."
                )

                # FIX 3 (Zero-Delay Post-Trade Sweep): Even on failure, close intermediate ATA.
                # Prevents ATA rent trap accumulation — every failed trade that created a new ATA
                # costs 0.002 SOL if we don't close it. Fire-and-forget is safe here.
                if target_mint_ata and session and keypair and rpc_getter:
                    task = asyncio.create_task(
                        close_ata_after_arbitrage(
                            session, keypair, rpc_getter, target_mint_ata
                        )
                    )
                    shared_state.retain_background_task(task)
            else:
                logger.debug(
                    "ℹ️ Auction lost or bundle dropped - normal operation continues"
                )
        elif confirmation.get("status") == "timeout":
            logger.warning(
                f"⏰ BUNDLE TIMEOUT: {bundle_id} - normal in competitive Jito auctions"
            )

            # ── Этап 2: Record loss in CapitalProtection on timeout ──────────
            if shared_state.capital_protection and virtual_balance_to_deduct > 0:
                shared_state.capital_protection.record_trade(-virtual_balance_to_deduct)

            await data_aggregator.log_tx_failed(
                bundle_id, confirmation, {"tx": tx_b64, "reason": "timeout"}
            )
        else:
            # ФИКС 3: Добавляем ATA в глобальный кэш ТОЛЬКО после подтверждения
            if new_atas_to_create:
                for _ata_addr in new_atas_to_create:
                    await shared_state.add_to_ata_cache(_ata_addr)
                logger.debug(
                    f"✅ ATA_CACHE updated with {len(new_atas_to_create)} new ATAs after successful confirmation"
                )

            # Log successful confirmation + TASK 1: zero-delay ATA close for any outcome
            await data_aggregator.log_tx_confirmed(
                tx_id,
                {"real_profit_sol": real_profit_sol, "status": "confirmed"},  # FIXED: Использование реального профита
                {"execution_time_ms": execution_time},
            )

            # FIXED: Инкремент счетчика успешных сделок в Prometheus
            PROMETHEUS_TRADES.inc()

            # ── Этап 2: Record PnL in CapitalProtection (используем реальный профит) ─
            if shared_state.capital_protection:
                shared_state.capital_protection.record_trade(real_profit_sol)

            # FIX 3 (Zero-Delay Post-Trade Sweep): Fire-and-forget targeted ATA close + dust sweep.
            # After Jito bundle is Confirmed, immediately sweep the intermediate token ATA
            # used in this trade. Burn-before-close prevents dust from blocking CloseAccount.
            # We use close_ata_after_arbitrage for the specific intermediate token,
            # and dust_sweeper._sweep_dust() for the general sweep.
            # Both run asyncio.create_task so they NEVER block the main event loop.
            if target_mint_ata and session and keypair and rpc_getter:
                logger.info(
                    f"♻️ Zero-Delay Post-Trade Sweep: closing intermediate ATA {target_mint_ata[:8]}..."
                )
                task = asyncio.create_task(
                    close_ata_after_arbitrage(
                        session, keypair, rpc_getter, target_mint_ata
                    )
                )
                shared_state.retain_background_task(task)
            # General dust sweep for any other stranded accounts
            if dust_sweeper:
                task = asyncio.create_task(dust_sweeper.sweep_after_successful_tx())
                shared_state.retain_background_task(task)
    except Exception as e:
        logger.error(f"Confirmation check failed: {e}")


async def execute_priority_opportunity(
    opportunity,
    session,
    cfg,
    rpc_manager,
    keypair,
    jito_executor,
    data_collector,
    flywheel_scaler,
    data_aggregator,
    alt_manager=None,
    execution_router=None,
    blockhash_mgr=None,
):
    """Execute a high-priority arbitrage opportunity."""
    start_time = time.time()

    # Get current balance and flywheel params
    current_balance_sol = shared_state.stats.get("last_balance", 0.017)
    params = flywheel_scaler.get_trading_params(current_balance_sol)

    # FIX 274: Фиксация слепка цен для консистентности расчетов во всей транзакции
    try:
        local_price_snapshot = dict(price_matrix)
    except Exception:
        local_price_snapshot = {}  # Fail open if price_matrix not available
    if local_price_snapshot:
        logger.debug(f"Price snapshot stored: {len(local_price_snapshot)} entries")

    # ── wSOL Death Spiral — реактивное разворачивание wSOL в hot path ──
    if current_balance_sol < 0.015:
        try:
            from src.ingest.wsol_manager import WSOLManager

            wsol_mgr = WSOLManager(keypair.pubkey(), keypair=keypair, session=session)
            unwrapped = await wsol_mgr.check_and_unwrap_wsol(
                rpc_url=rpc_manager.get_rpc(),
                native_balance_sol=current_balance_sol,
                unwrap_threshold_sol=0.015,
            )
            if unwrapped:
                logger.info("🔓 Hot path wSOL unwrap — native balance replenished")
        except Exception as wsol_err:
            logger.debug(f"Hot path wSOL unwrap skipped: {wsol_err}")

    # Check circuit breaker
    if shared_state.GLOBAL_STOP_EVENT.is_set():
        logger.critical("Бот остановлен для анализа. Ожидание ручного рестарта.")
        return

    # Check if pair has too many failures, switch to other pairs
    if not is_pair_allowed(opportunity.pair):
        logger.debug(
            f"🚫 Skipping {opportunity.pair} due to reputation ban — switching resources"
        )
        return

    # Phase 42: Upfront Liquidity Guard (REWRITTEN Phase 48)
    # Formula: Current_Balance - (ACTUAL_NEW_ATAs_NEEDED * 0.00204) - Jito_Tip < 0.01
    tip_amount_lamports = opportunity.metadata.get(
        "tip_lamports", getattr(cfg, "BASE_TIP_LAMPORTS", 10000)
    )

    actual_new_atas_needed = 0
    mints_involved = set()
    for leg in [opportunity.metadata.get("quote1"), opportunity.metadata.get("quote2")]:
        if leg:
            mints_involved.add(leg.get("inputMint"))
            mints_involved.add(leg.get("outputMint"))

    # Check which ATAs actually need creation (not in cache)
    for mint in mints_involved:
        if not mint:
            continue
        from spl.token.instructions import get_associated_token_address

        ata_addr = str(
            get_associated_token_address(keypair.pubkey(), Pubkey.from_string(mint))
        )
        if ata_addr not in ATA_CACHE:
            actual_new_atas_needed += 1
            # Note: We don't add to cache here, only after successful creation/check

    rent_per_ata = 0.00204
    # Fix 44: Use virtual_balance for affordability check (doesn't rely on last_WS_update)
    current_sol = shared_state.stats.get(
        "virtual_balance", shared_state.stats.get("last_balance", 0.0)
    )
    tip_sol = tip_amount_lamports / 1e9

    # Integrate the preventative check (TASK 4)
    max_allowed = flywheel_scaler.pre_calculate_ata_budget(
        current_sol, tip_sol, cfg.PRIORITY_FEE
    )
    if actual_new_atas_needed > max_allowed:
        logger.warning(
            f"🚫 [Pre-emptive ATA Guard] Required new ATAs ({actual_new_atas_needed}) exceed safe budget limit ({max_allowed}). Dropping trade."
        )
        return None

    mints_involved = set()
    for leg in [opportunity.metadata.get("quote1"), opportunity.metadata.get("quote2")]:
        if leg:
            mints_involved.add(leg.get("inputMint"))
            mints_involved.add(leg.get("outputMint"))

    actual_new_atas_needed = 0
    _rent_cost = 0.0

    # Добавляем в проверку заемный токен (borrow_mint)
    # Находим его из метаданных или параметров сделки
    borrow_mint_str = opportunity.metadata.get("in_mint", "So11111111111111111111111111111111111111112")
    check_mints = set(mints_involved)
    check_mints.add(borrow_mint_str)

    for mint_str in check_mints:
        if not mint_str or mint_str in CORE_GOLDEN_MINTS:
            continue

        mint_pubkey = Pubkey.from_string(mint_str)
        # Определяем программу токена
        from src.ingest.shared_state import TOKEN_2022_MINTS, get_ata_rent_for_mint
        program_id = TOKEN_2022_PROGRAM_ID if mint_str in TOKEN_2022_MINTS else TOKEN_PROGRAM_ID
        
        ata_addr = str(
            get_associated_token_address(keypair.pubkey(), mint_pubkey, token_program_id=program_id)
        )

        async with shared_state.ata_cache_lock:
            if ata_addr not in ATA_CACHE:
                exists = await check_ata_exists(
                    session, rpc_manager.get_rpc, keypair.pubkey(), mint_str
                )
                if not exists:
                    actual_new_atas_needed += 1
                    _rent_cost += get_ata_rent_for_mint(mint_str)
                else:
                    # Напрямую модифицируем кэш во избежание дедлока (Задача 1)
                    ATA_CACHE.add(ata_addr)

    current_sol = shared_state.stats.get(
        "virtual_balance", shared_state.stats.get("last_balance", 0.0)
    )
    tip_sol = tip_amount_lamports / 1e9
    rent_cost_sol = _rent_cost

    projected_balance_during_tx = (
        current_sol - rent_cost_sol - tip_sol - cfg.PRIORITY_FEE
    )

    if projected_balance_during_tx < MIN_RESERVE_SOL:
        logger.warning(
            f"🚫 [Dynamic Rent Guard] Слишком дорого! "
            f"Нужно {actual_new_atas_needed} новых ATA. "
            f"Баланс в процессе: {projected_balance_during_tx:.5f} < Резерв {MIN_RESERVE_SOL}. Скипаем."
        )
        return

    logger.debug(
        f"🚀 Executing priority opportunity: {opportunity.pair} (score: {opportunity.score:.1f})"
    )

    # FIX 132: Run Stale Quote Guard BEFORE early return for webhooks
    q1 = opportunity.metadata.get("quote1") or opportunity.metadata.get("raw_data", {}).get("leg1_quote")
    if q1 and "fetched_at" in q1:
        quote_age = time.time() - q1["fetched_at"]
        if quote_age > 1.5:
            reason = f"Stale Quote: {quote_age:.2f}s > 1.5s TTL limit"
            logger.warning(f"skip: {reason}")
            if data_aggregator:
                asyncio.create_task(data_aggregator.log_opportunity_skipped(
                    webhook_id="internal",
                    parsed_opportunity={"pair": opportunity.pair, "expected_profit_sol": opportunity.expected_profit_sol},
                    reason=reason
                ))
            return

    # ── ИСПРАВЛЕНИЕ: Сквозная маршрутизация для Webhook ──
    if opportunity.metadata.get("is_webhook"):
        logger.info(
            f"🔄 Routing Webhook Signal directly to Execution Router: {opportunity.pair}"
        )
        raw_data = opportunity.metadata.get("raw_data", {})
        if execution_router:
            result = await execution_router.execute_arbitrage_opportunity(raw_data)
            logger.debug(f"Webhook execution result: {result}")
        return

    # Extract saved quotes from metadata instead of re-fetching (saves API calls)
    quote1 = opportunity.metadata.get("quote1")
    quote2 = opportunity.metadata.get("quote2")
    chosen_route = opportunity.metadata.get("chosen_route")

    if not chosen_route and quote1 and quote2:
        chosen_route = [quote1, quote2]

    amount_lamports = opportunity.metadata.get(
        "amount_lamports", int(0.1 * 1_000_000_000)
    )
    in_mint_str = opportunity.metadata.get("in_mint")
    out_mint_str = opportunity.metadata.get("out_mint")
    tip_amount_lamports = opportunity.metadata.get(
        "tip_lamports", getattr(cfg, "BASE_TIP_LAMPORTS", 10000)
    )

    if not quote1 or not quote2 or not chosen_route:
        logger.warning(
            f"No quotes or chosen_route in metadata for {opportunity.pair}, skipping"
        )
        return

    # Convert mint strings back to Pubkeys
    from solders.pubkey import Pubkey

    try:
        in_mint = Pubkey.from_string(in_mint_str) if in_mint_str else TOKENS["SOL"]
        out_mint = Pubkey.from_string(out_mint_str) if out_mint_str else TOKENS["SOL"]
    except Exception as e:
        logger.debug(f"Pubkey parse fallback to SOL: {e}")
        in_mint = TOKENS["SOL"]
        out_mint = TOKENS["SOL"]

    # Get flywheel params
    current_balance_sol = shared_state.stats.get("last_balance", 0.017)
    params = flywheel_scaler.get_trading_params(current_balance_sol)
    cfg.ARBITRAGE_FILTER_MIN_PROFIT_SOL = params["min_net_profit_sol"]

    # ┌─ KERNEL TASK 1: MarginFi Account Lock (Per-Account Locks for Parallel Trades) ──
    # BUG #36: Use per-account locks so different MarginFi accounts can trade concurrently.
    # Lock is held ONLY during transaction BUILDING (including simulation),
    # then RELEASED immediately after successful bundle SEND.
    # Jito auctions operate on slot-level millisecond intervals — MarginFi account is free
    # for the next slot regardless of this bundle's confirmation outcome.
    pool_acct_str = cfg.MARGINFI_ACCOUNT_PUBKEY
    if execution_router and hasattr(execution_router, "marginfi_pool"):
        current_slot = shared_state.stats.get("current_slot", 0)
        pool_acct_str, _ = await execution_router.marginfi_pool.checkout(current_slot)
    async with shared_state.marginfi_account_locks[pool_acct_str]:
        # ───────────────────────────────────────────────────────────────────────────────────────

        # --- ATA RENT GUARD (per-trade profit check) ---
        # Deduct 0.002 SOL from expected profit if a new ATA must be created for the target token.
        # Prevents Death-by-Success: don't let 5 simultaneous wins drain 0.01 SOL in rent deposits.
        from spl.token.instructions import get_associated_token_address

        _dst_mint_str = str(out_mint)
        _dst_prog_id = TOKEN_PROGRAM_ID
        _dst_ata = str(
            get_associated_token_address(
                keypair.pubkey(), Pubkey.from_string(_dst_mint_str), _dst_prog_id
            )
        )
        _rent_sol = 0.0
        async with shared_state.ata_cache_lock:
            if _dst_ata not in ATA_CACHE:
                _ata_already = await check_ata_exists(
                    session, rpc_manager.get_rpc, keypair.pubkey(), _dst_mint_str
                )
                if _ata_already:
                    await shared_state.add_to_ata_cache(_dst_ata)
                else:
                    _rent_sol = RENT_SPL_ATA_SOL
                    logger.info(
                        f"⚠️ New ATA required for {_dst_mint_str[:8]} — deducting {_rent_sol:.5f} SOL from expected profit ({opportunity.expected_profit_sol:.6f} SOL)"
                    )
        # FIX 2 (Dynamic Rent Guard): Deduct 0.00204 SOL rent if NEW ATA must be created.
        # If ATA already exists (cached), skip deduction — rent was already paid.
        # This prevents capital drain from creating unnecessary ATAs for tiny profits.
        if _rent_sol > 0:
            _profit_after_rent = opportunity.expected_profit_sol - _rent_sol
            from src.ingest.flywheel_scaler import DynamicThresholds
            dynamic_min_profit = DynamicThresholds(current_balance_sol).min_profit_sol
            if _profit_after_rent < dynamic_min_profit:
                logger.warning(
                    f"⏭️ Dynamic Rent Guard: Profit {_profit_after_rent:.6f} SOL after ATA rent ({_rent_sol} SOL) < min profit {dynamic_min_profit:.6f} SOL — ABORTING trade {opportunity.pair}"
                )
                return None  # Correctly abort execution to protect capital
        else:
            _profit_after_rent = opportunity.expected_profit_sol
        # ------------------------------------------------

        # — TASK 2 — Upfront Dynamic Capital Check (before we waste time building a tx) —
        # Count how many NEW ATAs the chosen_route actually needs, not what's already cached.
        # Then verify the remaining virtual_balance can cover ATA rent + Jito tip + gas fees
        # while keeping MIN_RESERVE_SOL as an untouched floor.
        try:
            leg_mints: Set[str] = set()
            if chosen_route:
                for leg in chosen_route:
                    leg_mints.add(str(leg.get("inputMint", "")))
                    leg_mints.add(str(leg.get("outputMint", "")))
            leg_mints.discard("")

            _new_ata_count = 0
            _rent_cost = 0.0
            _new_atas_to_create = set()  # ФИКС 3: локальный сет — не в глобальный кэш!
            for mint_str in leg_mints:
                mint_pk = Pubkey.from_string(mint_str)
                _prog_id = TOKEN_PROGRAM_ID
                _ata = str(
                    get_associated_token_address(keypair.pubkey(), mint_pk, _prog_id)
                )
                async with shared_state.ata_cache_lock:
                    if _ata not in ATA_CACHE:
                        _new_ata_count += 1
                        _new_atas_to_create.add(
                            _ata
                        )  # локально — только после подтверждения tx
                        _rent_cost += RENT_SPL_ATA_SOL

            _tip_sol = int(tip_amount_lamports) / 1e9
            _gas_sol = cfg.PRIORITY_FEE + 0.000005
            _total_cost = _tip_sol + _gas_sol + _rent_cost
            _virt_bal = shared_state.stats.get("virtual_balance", current_balance_sol)

            if _virt_bal - _total_cost < cfg.MIN_RESERVE_SOL:
                logger.warning(
                    f"🚫 [Dynamic Capital Guard] Insufficient capital: "
                    f"virtual_balance={_virt_bal:.5f} | cost(ATAs+tip+gas)={_total_cost:.5f} | "
                    f"floor={cfg.MIN_RESERVE_SOL} | Skipping {opportunity.pair}"
                )
                return

            logger.debug(
                f"💰 Capital check OK: new_atas={_new_ata_count} rent={_rent_cost:.5f} "
                f"tip={_tip_sol:.5f} gas={_gas_sol:.5f} | post-deduction bal={_virt_bal - _total_cost:.5f} SOL"
            )
        except Exception as _e:
            logger.debug(f"Capital check skipped (non-critical): {_e}")
        # ──────────────────────────────────────────────────────────────────────────

        # 1. Build transaction
        strat_type = 1
        if opportunity.metadata.get("strategy") == "lst_depeg":
            strat_type = 2
        elif opportunity.metadata.get("strategy") == "orderbook":
            strat_type = 4

        # Fix 39: Pass the ACTUAL dynamic chosen_route (not hardcoded [quote1, quote2])
        # Fix 81: Pre-calculate net profit to prevent USDC math divide-by-1e9 bug
        tip_amount_sol = tip_amount_lamports / 1e9 if tip_amount_lamports else 0.0
        borrow_amount_sol = opportunity.metadata.get("borrow_amount_sol", 0.0)
        # DEX-006: Asset-specific flashloan fee (0.05% for USDC/USDT, 0% for SOL)
        _usdc_mint_str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        _usdt_mint_str = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
        _in_mint_str = str(in_mint) if not isinstance(in_mint, str) else in_mint
        if _in_mint_str in [_usdc_mint_str, _usdt_mint_str]:
            _flashloan_pct = 0.0005  # 0.05%
        else:
            _flashloan_pct = 0.0     # 0% for SOL
        flashloan_fee_sol = borrow_amount_sol * _flashloan_pct

        est_net_profit_sol = max(
            0.0,
            float(opportunity.expected_profit_sol)
            - tip_amount_sol
            - flashloan_fee_sol
            - (cfg.PRIORITY_FEE + cfg.BASE_FEE),
        )
        # For triangular, this carries all 3 legs; for direct, 2 legs.
        tx_b64 = await create_flashloan_arbitrage_tx(
            session,
            in_mint,
            out_mint,
            amount_lamports,
            chosen_route,
            cfg,
            keypair,
            lambda: rpc_manager.get_rpc(),
            use_jito=True,
            tip_lamports=tip_amount_lamports,
            alt_manager=alt_manager,
            strategy_type=strat_type,
            tip_accounts=(
                jito_executor.tip_accounts if jito_executor else None
            ),  # Fix 3: dynamic tip accounts
            blockhash_mgr=blockhash_mgr,  # Task 5: Slot Drift Compensator
            opportunity=opportunity,
            expected_profit_sol=est_net_profit_sol,
        )
        if not tx_b64:
            logger.warning("Failed to create priority arbitrage tx")
            return

        # 2. Simulate First (Capital Protection)
        from src.ingest.flash_simulator import FlashSimulator

        flash_sim = FlashSimulator(session, rpc_manager.get_rpc())

        # Local Simulation Integrity: Use region-matching RPC
        # FIX 186: Select a random Jito endpoint for simulation to prevent single region point of failure
        import random
        jito_endpoint = random.choice(cfg.JITO_ENDPOINTS) if cfg.JITO_ENDPOINTS else "https://frankfurt.mainnet.block-engine.jito.wtf/api/v1/bundles"
        # FIX 249: Check GLOBAL_STOP_EVENT before simulation (capital guard)
        if shared_state.GLOBAL_STOP_EVENT.is_set():
            logger.critical("🛑 [Capital Guard] GLOBAL_STOP_EVENT set mid-trade (pre-simulation) — aborting transaction build.")
            return {"status": "aborted", "message": "Global stop triggered mid-trade"}
        is_profitable, reason, sim_result = await flash_sim.validate_profitability(
            tx_b64=tx_b64,
            tx_signer_pubkey=str(keypair.pubkey()),
            min_profit_lamports=int(params["min_net_profit_sol"] * 1e9),
            tip_lamports=tip_amount_lamports,
            jito_endpoint=jito_endpoint,
        )
        # TASK 10: Update dynamic CU cache on successful simulation
        if sim_result and sim_result.success and sim_result.units_consumed > 0:
            import src.ingest.shared_state as shared_state
            strategy_key = "flash_arbitrage_MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"
            shared_state.DYNAMIC_CU_CACHE[strategy_key] = int(sim_result.units_consumed * 1.1)
        # ---> ИСПРАВЛЕНИЕ: PAPER_TRADING_ONLY после симуляции <---
        if getattr(cfg, "PAPER_TRADING_ONLY", False):
            simulated_profit = (
                sim_result.balance_delta_sol
                if sim_result
                else opportunity.expected_profit_sol
            )
            logger.info(
                f"🧪 [SIMULATION] Профит подтвержден: {opportunity.pair} | "
                f"Симуляция: {simulated_profit:.6f} SOL. "
                f"Статус: {is_profitable} ({reason}). Real execution skipped."
            )
            if data_aggregator:
                try:
                    await data_aggregator.log_event(
                        event_type="SimulatedOpportunity",
                        parsed_opportunity={
                            "pair": opportunity.pair,
                            "score": getattr(opportunity, "score", 0),
                            "expected_profit_sol": simulated_profit,
                            "is_profitable": is_profitable,
                            "reason": reason,
                        },
                        metadata=opportunity.metadata,
                    )
                except Exception as e:
                    logger.warning(f"Failed to log simulated opportunity: {e}")

            # Data Collection: record simulated trade for post-factum analysis
            if data_aggregator:
                try:
                    jito_tip_sol = tip_amount_lamports / 1e9
                    est_gas_sol = cfg.BASE_FEE + cfg.PRIORITY_FEE
                    total_cost_sol = jito_tip_sol + est_gas_sol + _rent_cost

                    gross_profit_sol = simulated_profit
                    net_profit_sol = gross_profit_sol - total_cost_sol

                    base_fee_lamports = int(cfg.BASE_FEE * 1e9)
                    priority_fee_lamports = int(cfg.PRIORITY_FEE * 1e9)
                    jito_tip_lamports = int(jito_tip_sol * 1e9)
                    flashloan_fee_lamports = int(amount_lamports * __flashloan_pct)
                    ata_rent_lamports = int(_rent_cost * 1e9)
                    total_cost_lamports = int(total_cost_sol * 1e9)
                    net_profit_lamports = int(net_profit_sol * 1e9)
                    gross_revenue_lamports = int(gross_profit_sol * 1e9)
                    decision = "EXECUTE" if net_profit_sol > 0 else "SKIP_LOW_MARGIN"
                    roi_pct = (
                        (net_profit_sol / (gross_profit_sol + 1e-12)) * 100
                    )

                    await data_aggregator.log_paper_trade(
                        {
                            "slot": shared_state.stats.get("current_slot", 0),
                            "blockhash": cached_blockhash,
                            "route": opportunity.metadata.get("route")
                            if opportunity.metadata
                            else opportunity.pair,
                            "token_in": opportunity.metadata.get("input_mint", "")
                            if opportunity.metadata
                            else "",
                            "token_out": opportunity.metadata.get("output_mint", "")
                            if opportunity.metadata
                            else "",
                            "amount_lamports": int(
                                opportunity.metadata.get("amount_lamports", 0)
                                if opportunity.metadata
                                else 0
                            ),
                            "expected_profit_lamports": int(
                                opportunity.expected_profit_sol * 1e9
                            )
                            if hasattr(opportunity, "expected_profit_sol")
                            else 0,
                            "gross_revenue_lamports": gross_revenue_lamports,
                            "flashloan_fee_lamports": flashloan_fee_lamports,
                            "dex_fee_lamports": int(gross_profit_sol * 0.003 * 1e9)
                            if gross_profit_sol > 0
                            else 0,
                            "slippage_bps": opportunity.slippage_pct or 15,
                            "compute_cost_lamports": 0,
                            "network_fee_lamports": base_fee_lamports,
                            "priority_fee_lamports": priority_fee_lamports,
                            "jito_tip_lamports": jito_tip_lamports,
                            "ata_rent_lamports": ata_rent_lamports,
                            "total_cost_lamports": total_cost_lamports,
                            "net_profit_lamports": net_profit_lamports,
                            "roi_pct": roi_pct,
                            "decision": decision,
                            "executed": 1 if decision == "EXECUTE" else 0,
                            "sim_success": 1 if sim_result and sim_result.success else 0,
                            "sim_error": reason if not is_profitable else None,
                            "price_impact_pct": getattr(opportunity, "slippage_pct", 0.0),
                            "sol_usd_price": price_matrix.get(
                                "So11111111111111111111111111111111111111112", (150.0, 0)
                            )[0] if isinstance(
                                price_matrix.get("So11111111111111111111111111111111111111112"), tuple
                            ) else 150.0,
                        }
                    )
                except Exception as e:
                    logger.warning(f"Data recording failed: {e}")

            # Paper compounding / loss: update virtual_balance with NET profit
            if sim_result and net_profit_sol > 0:
                async with shared_state.stats_lock:
                    shared_state.stats["virtual_balance"] += net_profit_sol
                logger.info(
                    f"🧪 Paper compounding: +{net_profit_sol:.6f} SOL (Net) credited to virtual balance"
                )
            elif sim_result and net_profit_sol <= 0 and total_cost_sol > 0:
                async with shared_state.stats_lock:
                    shared_state.stats["virtual_balance"] = max(
                        0.0,
                        shared_state.stats["virtual_balance"] - total_cost_sol,
                    )
                logger.warning(
                    f"💸 Paper loss: Deducted cost -{total_cost_sol:.6f} SOL from virtual balance"
                )
            return

        # Логируем попытку для ИИ
        if data_aggregator:
            try:
                await data_aggregator.log_event(
                    event_type="AITrainingData",
                    parsed_opportunity={
                        "pair": opportunity.pair,
                        "score": opportunity.score,
                        "expected_profit_sol": opportunity.expected_profit_sol,
                    },
                    simulation_result={
                        "is_profitable": is_profitable,
                        "reason": reason,
                        "simulated_profit": (
                            sim_result.balance_delta_sol if sim_result else 0.0
                        ),
                    },
                    metadata=opportunity.metadata,
                )
            except Exception as e:
                logger.warning(f"Failed to log AI training data: {e}")

        if not is_profitable:
            logger.warning(f"Sim failed: {reason}. Attempting Smart Retry...")
            from src.ingest.smart_retry_engine import SmartRetryEngine
            
            # Определяем функцию пере-котирования для ретрая
            async def refetch_quotes(old_quote, new_amount, only_direct_routes=True):
                return await get_best_quote_multi(
                    session,
                    in_mint_str,
                    target_mint_str,
                    new_amount,
                    cfg,
                    slippage_bps=0,
                    restrict_intermediate=not only_direct_routes
                )
            
            # FIX 301: Fix lambda closure (use local 'opp' param) and profit variable (est_net_profit_sol)
            retry_result = await SmartRetryEngine.execute_retry(
                opportunity=opportunity.metadata,
                refetch_func=refetch_quotes,
                execute_func=lambda opp: execute_priority_opportunity(
                    opp, session, cfg, rpc_manager, keypair, jito_executor,
                    data_collector, flywheel_scaler, data_aggregator, alt_manager, execution_router
                ),
                jito_bidding_manager=jito_bidding_manager,
                original_amount=amount_lamports,
                original_profit=est_net_profit_sol,
                reason=reason
            )
            logger.info(f"🔄 Smart Retry execution status: {retry_result.get('status')}")
            return

        # 3. Hybrid Execution (Jito/Standard)
        tx_bytes = base64.b64decode(tx_b64)
        arbitrage_tx = VersionedTransaction.from_bytes(tx_bytes)
        # FIX 249: Check GLOBAL_STOP_EVENT before Jito submission (capital guard)
        if shared_state.GLOBAL_STOP_EVENT.is_set():
            logger.critical("🛑 [Capital Guard] GLOBAL_STOP_EVENT set mid-trade (pre-execution) — aborting submission.")
            return {"status": "aborted", "message": "Global stop triggered before Jito send"}
        result = await execution_router.execute_opportunity(
            session, cfg, rpc_manager.get_rpc(), arbitrage_tx, tip_amount_lamports
        )

        # FIX 184: Hot path blockhash-expiry retry (prevent useless dropping of verified profitable opportunities)
        if result.get("error") and ("blockhash" in str(result.get("error")).lower() or "expired" in str(result.get("error")).lower()):
            logger.warning("⏰ [HOT PATH RETRY] Jito rejected bundle due to stale blockhash. Fetching fresh blockhash and rebuilding transaction...")
            if blockhash_mgr:
                await blockhash_mgr.fetch_fresh_blockhash()
                # Rebuild with fresh blockhash and retry
                tx_b64 = await create_flashloan_arbitrage_tx(
                    session, in_mint, out_mint, amount_lamports, chosen_route, cfg, keypair,
                    lambda: rpc_manager.get_rpc(), use_jito=True, tip_lamports=tip_amount_lamports,
                    alt_manager=alt_manager, strategy_type=strat_type,
                    tip_accounts=(jito_executor.tip_accounts if jito_executor else None),
                    blockhash_mgr=blockhash_mgr, opportunity=opportunity, expected_profit_sol=est_net_profit_sol
                )
                if tx_b64:
                    arbitrage_tx = VersionedTransaction.from_bytes(base64.b64decode(tx_b64))
                    result = await execution_router.execute_opportunity(
                        session, cfg, rpc_manager.get_rpc(), arbitrage_tx, tip_amount_lamports
                    )

        # Virtual Balance Guard — deduct cost as soon as the bundle is sent
        tip_lamports = int(
            tip_amount_lamports
            if tip_amount_lamports
            else getattr(cfg, "BASE_TIP_LAMPORTS", 10000)
        )
        est_gas_lamports = int((cfg.PRIORITY_FEE + 0.000005) * 1e9)
        virtual_balance_to_deduct = (tip_lamports + est_gas_lamports) / 1e9

        async with shared_state.stats_lock:
            shared_state.stats["virtual_balance"] = max(
                0.0, shared_state.stats["virtual_balance"] - virtual_balance_to_deduct
            )
        logger.debug(
            f"💸 VirtualBalance deducted: -{virtual_balance_to_deduct:.6f} SOL | virtual_balance={shared_state.stats['virtual_balance']:.6f}"
        )

    # --- OUTSIDE LOCK: Confirmation and Post-Execution ------------------------
    execution_time = (time.time() - start_time) * 1000

    if result.get("success"):
        record_pair_success(opportunity.pair)
        tx_id_str = str(in_mint_str)[:8] + str(out_mint_str)[:8] + str(int(time.time()))
        logger.debug("🔥 Priority transaction sent successfully!")

        if "bundle_id" in result:
            out_ata = (
                str(get_associated_token_address(keypair.pubkey(), out_mint))
                if out_mint_str != str(TOKENS["SOL"])
                else None
            )
            task = asyncio.create_task(
                check_bundle_confirmation(
                    result["bundle_id"],
                    jito_executor,
                    data_aggregator,
                    base64.b64encode(bytes(arbitrage_tx)).decode(),
                    tx_id_str,
                    execution_time,
                    session=session,
                    keypair=keypair,
                    rpc_getter=lambda: rpc_manager.get_rpc(),
                    target_mint_ata=out_ata,
                    virtual_balance_to_deduct=virtual_balance_to_deduct,
                    new_atas_to_create=_new_atas_to_create,  # ФИКС 3
                    real_profit_sol=est_net_profit_sol,  # FIXED: Передача фактического расчетного чистого профита
                )
            )
            shared_state.active_tasks.add(task)
            task.add_done_callback(background_task_callback)
    else:
        err_msg = result.get("error", "")
        logger.warning(f"❌ Priority transaction failed to send: {err_msg}")

        # Refund virtual balance if submission failed
        async with shared_state.stats_lock:
            shared_state.stats["virtual_balance"] = max(
                0.0, shared_state.stats["virtual_balance"] + virtual_balance_to_deduct
            )
        logger.info(
            f"♻️ Capital Guard: Refunded {virtual_balance_to_deduct:.6f} SOL to virtual_balance due to send failure."
        )

        if err_msg and (
            "remaining account" in err_msg.lower()
            or "missing required signature" in err_msg.lower()
        ):
            discover_ri_extra_account(
                err_msg, getattr(opportunity, "metadata", {}).get("strategy", "default")
            )
        record_pair_failure(opportunity.pair, error_type=err_msg or "unknown")


async def check_ata_exists(session, rpc_getter, wallet_pubkey, mint_address):
    """Check if Associated Token Account exists for the given mint"""
    try:
        # Query token accounts for the wallet
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                str(wallet_pubkey),
                {"mint": mint_address},
                {"encoding": "jsonParsed"},
            ],
        }
        timeout = aiohttp.ClientTimeout(total=1.0)
        async with session.post(rpc_getter(), json=payload, timeout=timeout) as resp:
            if resp.status == 200:
                data = orjson.loads(await resp.read())
                if "result" in data and "value" in data["result"]:
                    return len(data["result"]["value"]) > 0
    except Exception as e:
        logger.debug(f"ATA check error: {e}")
    return False


async def worker(
    queue,
    session,
    cfg,
    rpc_manager,
    keypair,
    limiters,
    jito_executor,
    arbitrage_scorer=None,
    priority_queue=None,
    alt_manager=None,
    execution_router=None,
):
    # Stagger startup to prevent MacOS DNS gaierror(8)
    await asyncio.sleep(random.uniform(0.5, 5.0))
    pairs_checked = 0
    while True:
        priority, _tie_breaker, path = await queue.get()
        logger.info(
            f"🔎 [1 RPS Queue]: Scanning route {str(path[0])[:8]} ➔ {str(path[1])[:8]}"
        )
        try:
            pairs_checked += 1
            if len(path) == 2:
                in_mint, target_mint = path
                in_mint_str = str(in_mint)
                target_mint_str = str(target_mint)  # str for HTTP/JSON safety
            elif len(path) == 3:
                # Triangular: t1 -> t2 -> t3 -> t1
                t1, t2, t3 = path
                in_mint, target_mint = t1, t3  # Use t3 as target for simplicity
                in_mint_str = str(in_mint)
                target_mint_str = str(target_mint)
            else:
                logger.warning(f"Unsupported path length: {len(path)}")
                continue

            # Fix 62: Price Freshness TTL — never trade stale or missing data (Fail-Closed)
            now = time.time()
            is_stale = False
            for mint in (in_mint_str, target_mint_str):
                entry = price_matrix.get(mint)
                if not entry:
                    logger.warning(f"🚫 Price missing for {mint[:8]} — Fail-Closed.")
                    is_stale = True
                    break
                if (now - entry[1]) > 0.8:  # FIX 293: TTL reduced to 800ms (2 slots)
                    logger.warning(f"⏰ Stale price for {mint[:8]} ({now - entry[1]:.1f}s old) — Fail-Closed.")
                    is_stale = True
                    break

            if is_stale:
                continue  # skip this opportunity

            # Fix 44: Virtual Balance Guard — use virtual_balance so we never double-
            # commit capital while previous bundles are still in-flight.
            balance = shared_state.stats.get(
                "virtual_balance", shared_state.stats.get("last_balance", 0.0)
            )

            # Task 24/25: Expand rent check to include borrow_mint and SOL_MINT ATAs
            _SOL_MINT_STR = "So11111111111111111111111111111111111111112"
            try:
                from src.ingest.shared_state import get_ata_rent_for_mint
                _estimated_rent = 0.0
                for _check_mint in {target_mint_str, str(in_mint_str), _SOL_MINT_STR}:
                    if _check_mint not in shared_state.ATA_CACHE:
                        _estimated_rent += get_ata_rent_for_mint(_check_mint)
                _gas_ok, _gas_avail = await PreTradeGuard.check_gas_tank(balance, _estimated_rent)
                if not _gas_ok:
                    logger.critical(
                        f"🚨 STRICT GAS TANK: Balance {balance:.6f} SOL < 0.005 SOL. Worker halting."
                    )
                    await asyncio.sleep(30)
                    continue
            except Exception as _ge:
                logger.debug(f"Worker gas tank check skipped: {_ge}")

            # Fix 6 + 67: Balance Lock Guard — pause if lock is active
            if (
                shared_state._balance_lock_paused
                and time.time() < shared_state._balance_lock_pause_until
            ):
                _lock_wait_ms = (
                    shared_state._balance_lock_pause_until - time.time()
                ) * 1000
                logger.debug(
                    f"🔒 Balance Lock active — waiting {_lock_wait_ms:.0f}ms (worker)"
                )
                await asyncio.sleep(
                    max(0, shared_state._balance_lock_pause_until - time.time())
                )

            # Task 29: Dynamic params from FlywheelScaler (balance-dependent scaling)
            current_balance_sol = shared_state.stats.get("last_balance", 0.017)
            params = flywheel_scaler.get_trading_params(current_balance_sol)
            active_slippage_bps = params["max_slippage_bps"]
            active_borrow_sol = params["flash_loan_size"]

            # Fix 2: If base token is USDC (6 decimals), convert SOL amount to USDC equivalent
            # Otherwise 1.0 SOL * 10^6 = 1 USDC () — too small to cover fees
            usdc_mint_str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            borrow_amount_sol = active_borrow_sol
            if str(in_mint_str) == usdc_mint_str:
                sol_entry = price_matrix.get(
                    "So11111111111111111111111111111111111111112"
                )
                sol_price = sol_entry[0] if sol_entry else 150.0
                borrow_amount_sol = active_borrow_sol * sol_price
                logger.debug(
                    f"Fix 2: USDC borrow — scaling {active_borrow_sol} SOL * ${sol_price:.0f}/SOL = {borrow_amount_sol:.2f} USDC"
                )

            # --- RESTORED MISSING QUOTE FETCHING LOGIC ---
            decimals_in = await get_token_decimals_dynamic(session, rpc_manager.get_rpc(), in_mint_str)
            amount_lamports = int(borrow_amount_sol * (10**decimals_in))

            # ── wSOL Death Spiral — проверка перед котированием ──
            if balance is not None and balance < 0.015:
                try:
                    from src.ingest.wsol_manager import WSOLManager

                    wsol_mgr = WSOLManager(
                        keypair.pubkey(), keypair=keypair, session=session
                    )
                    unwrapped = await wsol_mgr.check_and_unwrap_wsol(
                        rpc_url=rpc_manager.get_rpc(),
                        native_balance_sol=balance,
                        unwrap_threshold_sol=0.015,
                    )
                    if unwrapped:
                        logger.info(
                            "🔓 Worker hot path wSOL unwrap — native balance replenished"
                        )
                except Exception as wsol_err:
                    logger.debug(f"Worker wSOL unwrap skipped: {wsol_err}")

            routes = []
            route_types = []

            # Variables for re-fetch later
            quote1 = None
            quote_sol_usdc = None

            logger.info(
                f"🔎 Очередь [1 RPS]: Ищу маршрут {in_mint_str[:4]} ➔ {target_mint_str[:4]}"
            )
            if len(path) == 2:
                # 2-hop Direct
                quote1 = await get_best_quote_multi(
                    session,
                    in_mint_str,
                    target_mint_str,
                    amount_lamports,
                    cfg,
                    slippage_bps=active_slippage_bps,
                )
                if quote1 and "out_amount" in quote1:
                    q2 = await get_best_quote_multi(
                        session, target_mint_str, in_mint_str, quote1["out_amount"], cfg,
                        slippage_bps=active_slippage_bps,
                    )
                    if q2 and "out_amount" in q2:
                        routes.append([quote1, q2])
                        route_types.append("direct")

                # Triangular: Jupiter multi-hop via restrictIntermediateTokens=false (2 calls instead of 3 sequential)
                quote1_multi = await get_best_quote_multi(
                    session,
                    in_mint_str,
                    target_mint_str,
                    amount_lamports,
                    cfg,
                    restrict_intermediate=False,
                    slippage_bps=active_slippage_bps,
                )
                if quote1_multi and "out_amount" in quote1_multi:
                    q2_multi = await get_best_quote_multi(
                        session,
                        target_mint_str,
                        in_mint_str,
                        quote1_multi["out_amount"],
                        cfg,
                        restrict_intermediate=False,
                        slippage_bps=active_slippage_bps,
                    )
                    if q2_multi and "out_amount" in q2_multi:
                        routes.append([quote1_multi, q2_multi])
                        route_types.append("triangular")

            elif len(path) == 3:
                # Multi-hop: Jupiter finds optimal route via intermediates with restrictIntermediateTokens=false
                q1 = await get_best_quote_multi(
                    session,
                    in_mint_str,
                    target_mint_str,
                    amount_lamports,
                    cfg,
                    restrict_intermediate=False,
                    slippage_bps=active_slippage_bps,
                )
                if q1 and "out_amount" in q1:
                    q2 = await get_best_quote_multi(
                        session,
                        target_mint_str,
                        in_mint_str,
                        q1["out_amount"],
                        cfg,
                        restrict_intermediate=False,
                        slippage_bps=active_slippage_bps,
                    )
                    if q2 and "out_amount" in q2:
                        routes.append([q1, q2])
                        route_types.append("triangular")

            if not routes:
                continue
            # ---------------------------------------------

            # --- RESTORED MISSING QUOTE FETCHING LOGIC ---
            # ... fetches quotes into `routes` ... (Already done)

            # --- Fix 36: Cross-Currency Profit Illusion (Drain Bug) ---
            # Normalize cross-currency profit to SOL via price_matrix
            SOL_MINT = "So11111111111111111111111111111111111111112"
            sol_price_in_usd = (
                price_matrix.get(SOL_MINT, (150.0, 0))[0]
                if isinstance(price_matrix.get(SOL_MINT), (list, tuple))
                else price_matrix.get(SOL_MINT, 150.0)
            )

            best_out_lamports = max([r[-1]["out_amount"] for r in routes])
            raw_profit_lamports = best_out_lamports - amount_lamports

            if raw_profit_lamports <= 0:
                continue  # No profit at all

            # Normalize cross-currency profit to Native SOL equivalents for tip calculation
            # Uses price oracle for all tokens (stables, LSTs, jitoSOL) - no more is_stable_trade illusion
            # Get USD price of input token
            in_mint_str_clean = str(in_mint) if hasattr(in_mint, "__str__") else in_mint
            if in_mint_str_clean not in price_matrix:
                in_mint_str_clean = target_mint_str  # fallback to other leg
            token_in_price_usd = (
                price_matrix.get(in_mint_str_clean, (sol_price_in_usd, 0))[0]
                if isinstance(price_matrix.get(in_mint_str_clean), (list, tuple))
                else price_matrix.get(in_mint_str_clean, sol_price_in_usd)
            )

            profit_in_tokens = raw_profit_lamports / (10**decimals_in)
            profit_in_usd = profit_in_tokens * token_in_price_usd
            raw_profit_sol = profit_in_usd / sol_price_in_usd
            current_expected_profit = raw_profit_sol

            # Max tip should never exceed 90% of equivalent USD profit gained (converted to SOL)
            max_safe_tip_sol = raw_profit_sol * 0.9

            # Jito Game Theory: Dynamic Tips
            tip_lamports = getattr(cfg, "BASE_TIP_LAMPORTS", 10000)
            try:
                # 2. Determine competition level (Success Rate)
                attempts = shared_state.stats.get("bundle_send_attempts", 0)
                successes = shared_state.stats.get("bundle_successes", 0)
                competition_low = True
                if attempts > 5:
                    success_rate = successes / attempts
                    if success_rate < 0.2:
                        competition_low = False

                # 3. God-mode tip via JitoBiddingManager (tip_floor poller + step-up/down + capital guard)
                #       replaces inline dynamic tip logic.
                # Capital Guard is inside calculate_optimal_tip: returns -1 if 50th > 80% profit.
                strategy_label = "arbitrage"
                calculated_tip = jito_bidding_manager.calculate_optimal_tip(
                    expected_profit_sol=current_expected_profit,
                    strategy=strategy_label,
                )
                if calculated_tip <= 0:
                    logger.warning(
                        f"🚫 Capital Guard: Jito 50th > 80% of expected profit — skipping whale market for {path}"
                    )
                    continue

                # Apply the mathematical Cross-Currency safety cap
                safe_tip_lamports = min(calculated_tip, int(max_safe_tip_sol * 1e9))
                # Fix 2 (Unfunded Jito Tip): cap further by actual native SOL balance
                current_native_sol = shared_state.stats.get("last_balance", 0.017)
                available_for_tip = (
                    current_native_sol - 0.005
                ) * 1e9  # leave 0.005 SOL for gas
                if available_for_tip <= 0:
                    logger.warning(
                        f"🚫 Native balance {current_native_sol:.6f} SOL < 0.005 gas reserve — skipping {path}"
                    )
                    continue
                native_capped = min(safe_tip_lamports, int(available_for_tip))
                if native_capped < 10000:
                    logger.warning(
                        f"⏭️ Tip {native_capped} lamports below 10k minimum after native cap "
                        f"(native={current_native_sol:.6f} SOL) — skipping {path}"
                    )
                    continue
                safe_tip_lamports = native_capped
                if safe_tip_lamports < 10000:
                    safe_tip_lamports = 10000  # Minimum floor

                tip_lamports = safe_tip_lamports
                jito_tip_sol = tip_lamports / 1e9
            except Exception as e:
                logger.debug(f"Tip calculation error: {e}")
                tip_lamports = min(
                    getattr(cfg, "BASE_TIP_LAMPORTS", 10000),
                    int(max_safe_tip_sol * 1e9),
                )
                # The Tie-Breaker Fix: Micro-Jitter
                import random
                tip_lamports += random.randint(11, 142)
                jito_tip_sol = tip_lamports / 1e9

            # Find optimal size comparing routes
            result = trade_sizer.find_optimal_trade_size_multi_route(
                routes=routes,
                amount_in=amount_lamports,
                decimals_in=decimals_in,
                decimals_out=await get_token_decimals_dynamic(session, rpc_manager.get_rpc(), target_mint),
                jito_tip_sol=jito_tip_sol,
            )

            if result is None or result[0] is None:
                continue

            optimal_amount, best_route_idx = result

            # Apply min() safeguard: env limit + available liquidity (Issue 5)
            # ATA rent is computed dynamically from ATA_CACHE elsewhere; reserve a flat 0.001 SOL buffer here.
            required_fee_reserve_lamports = int(
                (cfg.BASE_FEE + cfg.PRIORITY_FEE + 0.001) * 1e9
            )
            available_liquidity_lamports = max(
                0, int(balance * 1e9) - required_fee_reserve_lamports
            )
            # FIX 300: Dynamic borrow cap from flywheel_scaler (fixes NameError: borrow_env_sol undefined in worker())
            current_native_sol = shared_state.stats.get("last_balance", 0.015)
            _fs = flywheel_scaler
            if _fs is not None:
                scaler_params = _fs.get_trading_params(current_native_sol)
                dynamic_borrow_cap_sol = scaler_params.get("flash_loan_size", 0.01)
            else:
                dynamic_borrow_cap_sol = 0.01
            borrow_cap_lamports = int(dynamic_borrow_cap_sol * 1e9)
            capped_amount = min(int(optimal_amount), borrow_cap_lamports)
            if capped_amount < 1_000_000:
                logger.debug(
                    f"Cap too small ({capped_amount} lamports), skipping {path}"
                )
                continue
            optimal_amount = capped_amount

            # ── ФИКС 1: Перерасчет котировки при изменении объема ────────────────
            if optimal_amount != amount_lamports:
                logger.debug(
                    f"🔄 Size optimized ({amount_lamports/1e9:.4f} -> {optimal_amount/1e9:.4f} SOL). "
                    f"Re-fetching quotes to prevent InsufficientFunds..."
                )
                new_quote1 = await get_best_quote_multi(
                    session,
                    in_mint_str,
                    target_mint_str,
                    optimal_amount,
                    cfg,
                    slippage_bps=0,
                )
                if not new_quote1 or "out_amount" not in new_quote1:
                    logger.debug(
                        "Re-fetch failed (leg 1) for optimized amount — skipping"
                    )
                    continue

                new_quote2 = await get_best_quote_multi(
                    session,
                    target_mint_str,
                    in_mint_str,
                    new_quote1["out_amount"],
                    cfg,
                    slippage_bps=0,
                )
                if not new_quote2 or "out_amount" not in new_quote2:
                    logger.debug(
                        "Re-fetch failed (leg 2) for optimized amount — skipping"
                    )
                    continue

                chosen_route = [new_quote1, new_quote2]
                quote1 = new_quote1
                quote2 = new_quote2
                amount_lamports = optimal_amount
                logger.debug(
                    f"✅ Re-fetched both legs with optimal amount {optimal_amount/1e9:.4f} SOL. "
                    f"Route rebuilt: {len(chosen_route)} legs."
                )

            else:
                # Calculate profit for chosen route (non-optimized path)
                chosen_route = routes[best_route_idx]
                route_type = route_types[best_route_idx]

            # --- ЗАЩИТА АРЕНДЫ ATA (ATA Rent Guard) ---
            from spl.token.instructions import get_associated_token_address

            prog_id = TOKEN_PROGRAM_ID
            target_ata = str(
                get_associated_token_address(keypair.pubkey(), target_mint, prog_id)
            )
            rent_fee_sol = 0.0
            async with shared_state.ata_cache_lock:
                if target_ata not in ATA_CACHE:
                    ata_exists = await check_ata_exists(
                        session, rpc_manager.get_rpc, keypair.pubkey(), str(target_mint)
                    )
                    if ata_exists:
                        await shared_state.add_to_ata_cache(target_ata)
                    else:
                        rent_fee_sol = 0.00204
                        logger.debug(
                            f"⚠️ New ATA required for {str(target_mint)[:8]}. Deducting 0.002 SOL from expected profit."
                        )

            # Task 10: Исправление расчета прибыли для режима ExactOut
            quote_leg1 = chosen_route[0]
            quote_leg2 = chosen_route[-1]

            is_exact_out_route = (
                quote_leg2.get("full_quote_response", {}).get("swapMode") == "ExactOut"
            )

            if is_exact_out_route:
                # 1. Полученный объем промежуточного токена на первом шаге
                bought_lst_lamports = int(quote_leg1["out_amount"])

                # 2. Потраченный объем промежуточного токена для выкупа SOL долга на втором шаге
                spent_lst_lamports = int(
                    quote_leg2.get("full_quote_response", {}).get("inAmount", bought_lst_lamports)
                )

                # 3. Чистый неизрасходованный остаток LST на балансе
                leftover_lst_lamports = max(0, bought_lst_lamports - spent_lst_lamports)

                # 4. Переводим остаток LST в SOL-эквивалент по обменному курсу второй ноги
                sol_out_leg2 = int(quote_leg2["out_amount"])
                if spent_lst_lamports > 0:
                    lst_to_sol_rate = sol_out_leg2 / spent_lst_lamports
                    profit_lamports = int(leftover_lst_lamports * lst_to_sol_rate)
                else:
                    profit_lamports = 0
            else:
                # Классический расчет для ExactIn (SOL -> LST -> SOL)
                expected_out_lamports = chosen_route[-1][
                    "out_amount"
                ]  # Output in in_mint lamports
                profit_lamports = expected_out_lamports - amount_lamports

            # Получаем реальный минимум, который выдаст Jupiter при максимальном slippage
            worst_case_out = int(
                chosen_route[-1]
                .get("full_quote_response", {})
                .get("otherAmountThreshold", expected_out_lamports)
            )

            if worst_case_out < amount_lamports:
                logger.debug(
                    f"🚫 Пропуск маршрута: worst_case_out ({worst_case_out}) < долга ({amount_lamports}). Риск невыплаты Flashloan!"
                )
                continue

            is_sol_base = str(in_mint) == "So11111111111111111111111111111111111111112"
            sol_entry = price_matrix.get("So11111111111111111111111111111111111111112")
            sol_price_in_usd = (
                sol_entry[0] if isinstance(sol_entry, (tuple, list)) else 150.0
            )

            base_fee_sol = (
                cfg.BASE_FEE
                + cfg.PRIORITY_FEE
                + rent_fee_sol
                + jito_tip_sol
            )
            if is_sol_base:
                fee_in_base_token_lamports = int(base_fee_sol * 1e9)
            else:
                # Assuming in_mint is a stablecoin
                # FIX 195: Dynamically resolve decimals instead of hardcoded 1e6 (6 decimals)
                decimals = get_token_decimals(in_mint_str) or 6
                fee_in_base_token_lamports = int(base_fee_sol * sol_price_in_usd * (10 ** decimals))

            # DEX-003: Jupiter platform fee from final quote
            jupiter_fee_lamports = int(
                chosen_route[-1]
                .get("full_quote_response", {})
                .get("fees", {})
                .get("totalFee", 0)
            )
            # DEX-006: MarginFi flashloan fee (asset-specific)
            _usdc_mint_str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            _usdt_mint_str = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
            _in_mint_str = str(in_mint) if not isinstance(in_mint, str) else in_mint
            if _in_mint_str in [_usdc_mint_str, _usdt_mint_str]:
                _flashloan_pct = 0.0005
            else:
                _flashloan_pct = 0.0
            flashloan_fee_lamports = int(amount_lamports * _flashloan_pct)
            total_fees_in_base = fee_in_base_token_lamports + flashloan_fee_lamports + jupiter_fee_lamports
            if profit_lamports < total_fees_in_base:
                logger.debug(
                    f"Skipping: Profit {profit_lamports} lamports doesn't cover total fees ({total_fees_in_base} lamports)"
                )
                continue

            # Calculate net_profit in SOL for logging and metadata
            if is_sol_base:
                net_profit = (profit_lamports - total_fees_in_base) / 1e9
            else:
                net_profit = (
                    (profit_lamports - total_fees_in_base) / 1e6
                ) / sol_price_in_usd
            current_expected_profit = net_profit

            from src.ingest.flywheel_scaler import DynamicThresholds
            dynamic_min_profit = DynamicThresholds(current_native_sol).min_profit_sol
            if net_profit < dynamic_min_profit:
                logger.debug(
                    f"Skipping: Net profit {net_profit:.6f} SOL < dynamic min profit {dynamic_min_profit:.6f} SOL"
                )
                continue

            # ── Fix 34: Anti-Sandwich Profit-Aware BPS ───────────────────────────
            # Convert expected profit to basis points (profit per input lamport * 10 000).
            # This is the "slippage budget": sandwich bots can extract at most 40% of it.
            if optimal_amount > 0:
                profit_per_unit = (
                    expected_out_lamports - float(optimal_amount)
                ) / float(optimal_amount)
                expected_profit_bps = profit_per_unit * 10_000.0
            else:
                expected_profit_bps = 0.0
            anti_sandwich_bps = max(5, int(expected_profit_bps * 0.4))
            logger.debug(
                f"🛡️ Anti-sandwich: expected_profit={expected_profit_bps:.1f} BPS, "
                f"max_slippage={anti_sandwich_bps} BPS (40% cap)"
            )
            # ──────────────────────────────────────────────────────────────────

            # ── Fix 34 + Fix 39: Re-fetch chosen-route legs with anti-sandwich slippage ────
            # We re-request the exact same legs but with the tightened slip limit.
            # Fix 39: Rebuild chosen_route from re-fetched legs instead of stale in-memory values.
            chosen_route = None
            quote3 = None  # Triangular leg 3

            if route_type == "direct" and quote1:
                # Direct route re-fetch: update quote2 with ExactOut to guarantee repayment
                quote2 = await get_best_quote_multi(
                    session,
                    target_mint_str,
                    in_mint_str,
                    amount_lamports,
                    cfg,
                    slippage_bps=0,
                    swap_mode="ExactOut",
                    exact_out_amount=amount_lamports,
                )
                if not quote2:
                    logger.debug("Anti-sandwich re-fetch of leg 2 failed; skipping")
                    continue
                # Fix 39: Direct route — rebuild chain from anti-sandwich value
                chosen_route = [quote1, quote2]

            elif route_type == "triangular":
                # Triangular route re-fetch: use restrictIntermediateTokens=false (2 calls instead of 3)
                quote1_multi = await get_best_quote_multi(
                    session,
                    in_mint_str,
                    target_mint_str,
                    amount_lamports,
                    cfg,
                    expected_profit_bps=expected_profit_bps,
                    restrict_intermediate=False,
                )
                if not quote1_multi:
                    logger.debug(
                        "Anti-sandwich re-fetch of multi-hop leg 1 failed; skipping"
                    )
                    continue
                # out_amount already populated by get_jupiter_quote
                q2_multi = await get_best_quote_multi(
                    session,
                    target_mint_str,
                    in_mint_str,
                    amount_lamports,
                    cfg,
                    slippage_bps=0,
                    swap_mode="ExactOut",
                    exact_out_amount=amount_lamports,
                    restrict_intermediate=False,
                )
                if not q2_multi:
                    logger.debug(
                        "Anti-sandwich re-fetch of multi-hop leg 2 failed; skipping"
                    )
                    continue
                q2_multi["out_amount"] = int(q2_multi["outAmount"])
                chosen_route = [quote1_multi, q2_multi]
            # ─────────────────────────────────────────────────────────────────────────────

            # Fix 39: chosen_route must be populated before this point
            if not chosen_route:
                logger.error("chosen_route not built — skipping")
                continue

            # Update metadata with anti-sandwich-validated legs for executor
            # Fix 39: store anti-sandwich feetched chosen_route for triangular
            quote1 = chosen_route[0]
            quote2 = chosen_route[-1]  # Last leg: target->in (good enough for executor)

            # Log route comparison
            if len(routes) > 1:
                # Simplified profit calculations for route comparison
                direct_out_sol = routes[0][-1]["out_amount"] / (10**decimals_in)
                direct_in_sol = float(optimal_amount) / (10**decimals_in)
                direct_profit = direct_out_sol - direct_in_sol

                tri_out_sol = routes[1][-1]["out_amount"] / (10**decimals_in)
                tri_in_sol = float(optimal_amount) / (10**decimals_in)
                tri_profit = tri_out_sol - tri_in_sol

                logger.debug(
                    f"Route comparison: Direct +{direct_profit:.6f} SOL | Triangular +{tri_profit:.6f} SOL | Chosen: {route_type}"
                )
            else:
                logger.debug(f"Direct route profit: +{net_profit:.6f} SOL")

            # Pre-trade security validation (skip vault check for existing arbitrage pairs)
            guard = PreTradeGuard(session=session, rpc_url=rpc_manager.get_rpc())
            can_trade, reason = await guard.validate_token_security(
                mint_address=target_mint, rpc_url=rpc_manager.get_rpc()
            )
            if not can_trade:
                logger.debug(
                    f"🚫 Arbitrage aborted for {str(target_mint)[:8]}: {reason}"
                )
                # Log skipped opportunity
                parsed_opportunity = {
                    "pair": f"{str(in_mint)[:8]}/{str(target_mint)[:8]}",
                    "amount_lamports": int(amount_lamports),
                    "reason": reason,
                }
                if shared_state.data_aggregator:
                    await shared_state.data_aggregator.log_opportunity_skipped(
                        "internal", parsed_opportunity, reason
                    )
                continue

            # Log opportunity found
            parsed_opportunity = {
                "pair": f"{str(in_mint)[:8]}/{str(target_mint)[:8]}",
                "amount_lamports": int(optimal_amount),
                "expected_profit_sol": float(net_profit),
                "route": "triangular" if route_type == "triangular" else "direct",
                # FIX 259: Save raw Jupiter quote responses for reproducibility
                "quote1_raw": quote1,
                "quote2_raw": quote2,
            }
            metadata = {"borrow_amount_sol": borrow_amount_sol, "decimals": decimals_in}
            # FIX 258: Propagate correlation_id for end-to-end event tracing (from webhook or fresh)
            import uuid
            metadata["correlation_id"] = opportunity.metadata.get("correlation_id") if hasattr(opportunity, "metadata") and isinstance(opportunity.metadata, dict) else str(uuid.uuid4())
            if shared_state.data_aggregator:
                await shared_state.data_aggregator.log_opportunity_found(
                    "internal", parsed_opportunity, metadata
                )
            shared_state.stats["last_opportunity_ts"] = time.time()

            # Calculate working capital locally (current balance for liquidity estimate)
            working_cap = (
                shared_state.stats.get("last_balance", 0.0) * 1e6
            )  # Convert to USD approximation

            # Create arbitrage opportunity with quotes saved in metadata for executor
            opportunity = ArbitrageOpportunity(
                pair=f"{str(in_mint)[:8]}/{str(target_mint)[:8]}",
                expected_profit_sol=float(net_profit),
                slippage_pct=cfg.SLIPPAGE_BPS / 100.0,
                liquidity_depth_usd=working_cap * 10,  # Rough estimate
                network_congestion=50.0,  # Will be updated by scorer
                gas_cost_sol=0.0,  # Fix 41: MarginFi flashloans have 0% fee
                execution_time_ms=0,  # Will be measured
                timestamp=time.time(),
                metadata={
                    "quote1": quote1,
                    "quote2": quote2,
                    "amount_lamports": optimal_amount,
                    "in_mint": in_mint_str,
                    "out_mint": target_mint_str,
                    "tip_lamports": tip_lamports,
                    "chosen_route": chosen_route,
                    "strategy": strategy_label,
                    "expected_profit_sol": current_expected_profit,
                    "execution_router": execution_router,
                },
            )

            # Calculate AI score
            current_balance = shared_state.stats.get("last_balance", 0.0)
            score = await arbitrage_scorer.score_opportunity(
                opportunity, wallet_balance=current_balance
            )
            opportunity.score = score

            logger.debug(f"🎯 Opportunity scored: {opportunity.pair} = {score:.1f}")

            # Add to priority queue instead of immediate execution
            priority_queue.add_opportunity(opportunity)

            continue  # Move to next pair, let priority queue handle execution

        except Exception as e:
            logger.debug(f"Worker error: {e}")
        finally:
            pairs_checked += 1
            if pairs_checked % 50 == 0:
                logger.debug(
                    f"Worker {asyncio.current_task().get_name()} heartbeat: {pairs_checked} pairs processed."
                )
            queue.task_done()


async def blockhash_updater(session, rpc_getter):
    global cached_blockhash, cache_time
    while True:
        rpc = rpc_getter()
        try:
            # Batch request for efficiency
            payload = [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getLatestBlockhash",
                    "params": [{"commitment": "confirmed"}],
                },
                {"jsonrpc": "2.0", "id": 2, "method": "getSlot"},
            ]
            timeout = aiohttp.ClientTimeout(total=1.0)
            async with session.post(rpc, json=payload, timeout=timeout) as resp:
                if resp.status == 200:
                    data = orjson.loads(await resp.read())
                    for item in data:
                        if item["id"] == 1:
                            cached_blockhash = item["result"]["value"]["blockhash"]
                            cache_time = time.time()
                        elif item["id"] == 2:
                            shared_state.stats["current_slot"] = item["result"]
                            # StaleStreamGuard: record timestamp of last slot update
                            shared_state.stats["_sg_last_slot"] = item["result"]
                            shared_state.stats["_sg_last_slot_ts"] = time.time()
        except Exception as e:
            logger.debug(f"blockhash_updater warning: {e}")
        await asyncio.sleep(
            4.0
        )  # 4s cache — confirmed blockhash for Jito geo-propagation


async def hard_floor_guard():
    """
    Phase 49: Hard Floor Guard (Capital Suicide).
    If native SOL balance < 0.003 SOL, block the wallet to prevent
    the network from deleting the account (Rent Death).
    """
    while True:
        try:
            async with shared_state.stats_lock:
                # FIX 307: Default to 0.0 (block trading on state loss), not 1.0 (skip guard)
                balance = shared_state.stats.get("virtual_balance", 0.0)

            if balance < 0.003:
                logger.critical(
                    f"💀 RENT DEATH SHUTDOWN: Баланс {balance:.6f} SOL упал ниже критического лимита 0.003 SOL. "
                    f"Запуск экстренного завершения работы во избежание удаления аккаунта кошелька сетью!"
                )

                # Устанавливаем маркер блокировки перезапуска
                with open(".hard_floor_triggered", "w") as f_marker:
                    f_marker.write(f"blocked_at_{time.time()}")

                # Сигнализируем всем системам на экстренную остановку
                shared_state.GLOBAL_STOP_EVENT.set()

                # Экстренный сбор пыли и возврат аренды со всех ATA перед смертью процесса
                try:
                    _kp = globals().get("KEYPAIR")
                    if _kp is not None:
                        from src.ingest.dust_sweeper import DustSweeper
                        _rpc_url = rpc_manager.get_rpc() if 'rpc_manager' in globals() else None
                        if _rpc_url:
                            _http_session = aiohttp.ClientSession()
                            sweeper = DustSweeper(_kp, _rpc_url, _http_session)
                            await sweeper.sweep_on_shutdown()
                            await _http_session.close()
                except Exception as e_panic:
                    logger.error(f"Panic sweep failed: {e_panic}")

                break
        except Exception:
            pass
        await asyncio.sleep(1.0)


async def tcp_heartbeat(session: aiohttp.ClientSession):
    """
    HFT: Keep TCP congestion window warm by firing micro-pings to Jito/Jupiter.
    Prevents 5-15ms cold-start latency on trade execution.
    """
    ENDPOINTS = [
        "https://frankfurt.mainnet.block-engine.jito.wtf/api/v1/bundles",
        "https://amsterdam.mainnet.block-engine.jito.wtf/api/v1/bundles",
        "https://ny.mainnet.block-engine.jito.wtf/api/v1/bundles",
        "https://tokyo.mainnet.block-engine.jito.wtf/api/v1/bundles",
        os.getenv("JUPITER_QUOTE_API", "https://api.jup.ag/swap/v1/quote"),
    ]
    payload = {"jsonrpc": "2.0", "id": 1, "method": "getVersion"}

    while True:
        try:
            tasks = [session.post(ep, json=payload, timeout=0.3) for ep in ENDPOINTS]
            # Fire-and-forget: parallel post with no await on body
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            for r in responses:
                if isinstance(r, aiohttp.ClientResponse):
                    await r.release()
        except Exception:
            pass
        await asyncio.sleep(3.0)  # 3.0 seconds sufficient to keep TCP keep-alive connection open


async def run():
    import gc
    import signal
    import fcntl
    import sys
    
    # FIX 126: PID Lock (Prevent double instances from draining MarginFi account)
    pid_file = open('arb_bot.pid', 'w')
    try:
        fcntl.lockf(pid_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        print("🚨 CRITICAL: Another instance of arb_bot is already running! Exiting to prevent MarginFi collision.")
        sys.exit(1)

    logger.info("=== RUN() STARTED ===")

    # Phase 6B LOG-009: Silence noisy default library loggers
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logger.info("🔕 Noisy internal library loggers muted (aiohttp/asyncio set to WARNING)")

    # HFT optimization: Disable automatic GC to prevent Stop-the-World pauses
    gc.disable()

    # Fix 1: Initialize asyncio locks inside the running event loop
    initialize_shared_state()

    # P0-2.3b: Check if hard floor was triggered on previous run
    if os.path.exists(".hard_floor_triggered"):
        logger.critical("🚫 .hard_floor_triggered file found — previous run hit hard floor. Refusing to start.")
        sys.exit(1)
    if os.path.exists(".capital_protection_triggered"):
        with open(".capital_protection_triggered", "r", encoding="utf-8") as f_cp:
            cp_reason = f_cp.read().strip()
        logger.critical(f"🚫 .capital_protection_triggered file found — previous run hit Capital Protection: {cp_reason}. Refusing to start.")
        sys.exit(1)

    # FIX 162: SIGUSR1 diagnostic dump handler (Unix only)
    def dump_diagnostics(sig, frame):
        logger.critical(f"🚨 DIAGNOSTIC SIGNAL RECEIVED (SIG={sig})")
        import traceback, sys, threading
        for thread_id, stack in sys._current_frames().items():
            logger.critical(f"Thread {thread_id} ({threading.current_thread().name}):")
            logger.critical("".join(traceback.format_stack(stack)))
        if tracemalloc.is_tracing():
            snapshot = tracemalloc.take_snapshot()
            top_stats = snapshot.statistics('lineno')
            logger.critical("Top 10 memory allocations:")
            for index, stat in enumerate(top_stats[:10], 1):
                logger.critical(f" #{index}: {stat}")

    try:
        import signal
        _loop.add_signal_handler(signal.SIGUSR1, lambda: dump_diagnostics(signal.SIGUSR1, None))
        logger.info("📡 Diagnostic SIGUSR1 handler registered (kill -USR1 <pid> to dump traces/memory)")
    except (NotImplementedError, AttributeError):
        pass

    # FIX 155: Wrap signal handlers in try/except for Windows platform support
    _loop = asyncio.get_running_loop()
    for _sig in (signal.SIGTERM, signal.SIGINT):
        try:
            _loop.add_signal_handler(_sig, shared_state.GLOBAL_STOP_EVENT.set)
        except NotImplementedError:
            logger.warning(f"⚠️ Signal {_sig} handler not supported on this platform")
    logger.info("🔔 SIGTERM/SIGINT handlers registered for graceful shutdown")

    # OPS-001: SIGHUP/SIGPIPE shield — prevent SSH disconnects and broken pipes from killing the bot
    try:
        _loop.add_signal_handler(
            signal.SIGHUP,
            lambda: logger.warning("Received SIGHUP, ignoring to keep bot alive during terminal disconnect."),
        )
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)
        logger.info("🛡️ SIGHUP/SIGPIPE shield active — bot survives SSH disconnects and broken pipe failures")
    except (ValueError, AttributeError, NotImplementedError):
        logger.warning("⚠️ SIGHUP/SIGPIPE shield not available on this platform")

    import src.config.events as events_config

    events_config.lst_webhook_trigger = asyncio.Queue()

    # Делаем сборку мусора реже, но эффективнее, чтобы не мешать горячим циклам
    gc.set_threshold(7000, 10, 10)
    # gc.disable()  # Moved to top of run()

    # Fix 58: macOS/Linux Insomnia Guard — prevent system sleep / CPU throttling on startup
    import subprocess
    import platform

    if platform.system() == "Darwin":
        try:
            # FIX 164: Save process handle to prevent zombie/orphan on exit
            proc = subprocess.Popen(
                ["caffeinate", "-i", "-p", str(os.getpid())],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            shared_state.caffeinate_proc = proc
            logger.info(
                "🛡️ Insomnia guard active: caffeinate preventing macOS sleep (PID %s)"
                % os.getpid()
            )
        except Exception as e:
            logger.warning(f"⚠️ Could not start caffeinate: {e}")
    elif platform.system() == "Linux":
        logger.warning(
            "⚡ For Linux insomnia: run 'sudo cpupower frequency-set -g performance' manually for lowest-latency operation"
        )

    # Fix 57: GC idle-watchdog — collect only when priority_queue is empty for >5 s
    # Task 3: Disables auto-GC and calls gc.collect() only during confirmed idle periods.
    async def _gc_idle_collector():
        """Manual GC trigger — fires only when work queue has been empty for 5 s."""
        idle_seconds = 0.0
        while True:
            await asyncio.sleep(1.0)
            if priority_queue.size() == 0:
                idle_seconds += 1.0
                if idle_seconds >= 5.0:
                    gc.collect()
                    idle_seconds = 0.0
            else:
                idle_seconds = 0.0  # Reset on every enqueue — no GC mid-arb

    cfg = Config()
    init_limiters(cfg)

    # FIX 277: Oracle Lag Report — логирование задержки данных Pyth в главный поток
    try:
        from src.ingest.pyth_oracle_client import get_pyth_client
        client = get_pyth_client()
        report = client.get_lag_report()
        sol_lag = report.get("SOL", {}).get("average_lag_seconds", 0.0)
        logger.info(f"📊 [ORACLE LAG REPORT] SOL lag: {sol_lag:.2f}s")
    except Exception:
        pass

    # FIX 275: Запуск фонового мониторинга здоровья MarginFi
    if cfg.MARGINFI_ACCOUNT_PUBKEY:
        health_task = asyncio.create_task(
            marginfi_health_monitor_loop(session, rpc_manager.get_rpc(), cfg.MARGINFI_ACCOUNT_PUBKEY)
        )
        shared_state.retain_background_task(health_task)

    # Phase 6B CFG-001: Block placeholder Helius API keys
    if any("YOUR_KEY" in url for url in cfg.HELIUS_SENDER_URLS):
        raise ValueError(
            "CRITICAL CONFIG ERROR: You are using the default HELIUS_SENDER_URL placeholder. "
            "Please configure your actual Helius API key in the .env file."
        )

    # ── Phase 49: Start async trade logger BEFORE any worker is scheduled ─────
    # This must fire before workers enqueue so TRADE_LOG_QUEUE is set.
    # Global so substasks (workers, executors) can access TRADE_LOG_QUEUE.
    logger_obj = await start_async_trade_logger("trades.jsonl")  # type: ignore[misc]

    if not os.path.exists(cfg.WALLET_PATH):
        logger.error(f"Wallet not found: {cfg.WALLET_PATH}")
        return

    global KEYPAIR
    # Fix 81 / Memory Hardening: load keypair once at startup with context manager.
    # No disk I/O during the hot trade loop — KEYPAIR stays resident in RAM.
    # P0-4.1b: Set restrictive permissions before reading wallet
    wallet_path = cfg.WALLET_PATH
    try:
        st = os.stat(wallet_path)
        if st.st_mode & (stat.S_IRGRP | stat.S_IROTH | stat.S_IWGRP | stat.S_IWOTH):
            logger.warning(f"⚠️ {wallet_path} has insecure permissions. Fixing to 0o600...")
            os.chmod(wallet_path, 0o600)
    except Exception as e:
        logger.error(f"Failed to verify/fix wallet permissions: {e}")
    
    # 2. Безопасное считывание и зануление сырых байт в памяти
    with open(wallet_path, "rb") as _f:
        raw_data = _f.read()
    
    try:
        key_ints = orjson.loads(raw_data)
        key_bytes = bytes(key_ints)
        
        KEYPAIR = Keypair.from_bytes(key_bytes)
        keypair = KEYPAIR
        
        # Стираем приватные байты из памяти сразу после инициализации
        # Превращаем массивы чисел в нули, чтобы они не утекли из Heap
        if isinstance(key_ints, list):
            for i in range(len(key_ints)):
                key_ints[i] = 0
        del key_bytes
        del raw_data
    except Exception as e:
        logger.critical(f"Failed to load wallet securely: {e}")
        sys.exit(1)

    keypair = KEYPAIR

    # ── Jito executor init (must be before health-factor uses RPC) ──────────────
    rpc = RPCManager(cfg)

    # Initialize priority queue and trade sizer
    priority_queue = PriorityArbitrageQueue(max_size=50)
    trade_sizer = OptimalTradeSizer()

    proxy_url = os.getenv("PROXY_URL")
    if proxy_url:
        if proxy_url.startswith("socks5") or proxy_url.startswith("socks4"):
            try:
                from aiohttp_socks import ProxyConnector

                connector = ProxyConnector.from_url(proxy_url, limit=100)
                logger.info(f"🌐 SOCKS Proxy Enabled: {proxy_url}")
            except ImportError:
                logger.warning("aiohttp_socks not installed. Using default resolver.")
                connector = aiohttp.TCPConnector(
                    limit=100,
                    ttl_dns_cache=300,
                    use_dns_cache=True,
                    family=socket.AF_INET,
                    force_close=True,
                    enable_cleanup_closed=True,
                )
        elif proxy_url.startswith("http"):
            os.environ["HTTPS_PROXY"] = proxy_url
            os.environ["HTTP_PROXY"] = proxy_url
            connector = aiohttp.TCPConnector(
                limit=100,
                ttl_dns_cache=300,
                use_dns_cache=True,
                trust_env=True,
                family=socket.AF_INET,
                force_close=True,
                enable_cleanup_closed=True,
            )
            logger.info(f"🌐 HTTP Proxy Enabled: {proxy_url}")
        else:
            connector = aiohttp.TCPConnector(
                limit=100,
                ttl_dns_cache=300,
                use_dns_cache=True,
                family=socket.AF_INET,
                force_close=True,
                enable_cleanup_closed=True,
            )
    else:
        connector = aiohttp.TCPConnector(
            limit=100,
            ttl_dns_cache=300,
            use_dns_cache=True,
            family=socket.AF_INET,
            force_close=True,
            enable_cleanup_closed=True,
        )

    session = aiohttp.ClientSession(
        connector=connector,
        headers={
            "Accept-Encoding": "br, gzip"
        },  # Fix 53 + 92: Brotli compression cuts quote payload size
    )

    # Phase 6B CFG-009: Startup Handshake Sentinel — validate all RPC nodes before entering hot loops
    logger.info("⏱️ Initiating startup handshake to validate all RPC nodes...")
    verified_nodes = []
    for node_url in list(rpc.all_nodes):
        try:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getSlot"}
            timeout = aiohttp.ClientTimeout(total=2.0)
            async with session.post(node_url, json=payload, timeout=timeout) as resp:
                if resp.status == 200:
                    verified_nodes.append(node_url)
                    logger.info(f"  ✓ RPC Node validated: {redact_url(node_url)[:45]}...")
                elif resp.status in (401, 403):
                    logger.warning(f"  ✗ RPC Node REJECTED (HTTP {resp.status} - Invalid key): {redact_url(node_url)[:45]}...")
                    rpc.blacklist(node_url)
                else:
                    logger.warning(f"  ✗ RPC Node degraded (HTTP {resp.status}): {redact_url(node_url)[:45]}...")
                    rpc.blacklist(node_url)
        except Exception as e:
            logger.warning(f"  ✗ RPC Node connection failed: {redact_url(node_url)[:45]}... Error: {e}")
            rpc.blacklist(node_url)

    if not rpc.all_nodes:
        raise RuntimeError("CRITICAL: All RPC endpoints in your pool failed the startup handshake. Check your API keys and internet connection.")

    rpc_url = rpc.get_rpc()
    balance_lamports = await StateManager.get_balance_lamports(
        session, rpc, keypair.pubkey()
    )
    balance_sol = None if balance_lamports is None else balance_lamports / 1e9
    logger.info("==================================================")
    logger.info("Post-authorization diagnostics")
    logger.info(f"Loaded Keypair file path: {cfg.WALLET_PATH}")
    logger.info(f"Resolved public key address: {keypair.pubkey()}")
    logger.info(f"Active RPC endpoint URL being queried: {redact_url(rpc_url)}")
    if balance_lamports is not None:
        logger.info(
            f"Fetched SOL balance: {balance_lamports} lamports / {balance_sol:.9f} SOL"
        )
    else:
        logger.info("Fetched SOL balance: unavailable")
    logger.info("==================================================")

    # ── Этап 2: Initialize Capital Protection ──────────────────────────────
    initial_balance = balance_sol if balance_sol is not None else 0.017
    shared_state.capital_protection = CapitalProtection(initial_balance)
    logger.info(f"🛡️ Capital Protection initialized (start_balance={initial_balance:.6f} SOL)")

    # ── Этап 3: Start Prometheus metrics server ─────────────────────────────
    try:
        # FIX 234: Строго привязываем сокет к localhost для исключения публичной утечки баланса
        start_http_server(9100, addr="127.0.0.1")
        logger.info("📊 Prometheus metrics server started securely on 127.0.0.1:9100")
    except Exception as e:
        logger.warning(f"Failed to start Prometheus server: {e}")

    # ── Fix 46: MARGINFI_ACCOUNT .env sanitization ─────────────────────────────
    if not validate_marginfi_account(cfg):
        logger.critical("Bot cannot start — MarginFi account validation failed.")
        await session.close()
        sys.exit(1)

    # Phase 49: Hardware & Performance Heartbeat
    task = asyncio.create_task(tcp_heartbeat(session))
    shared_state.retain_background_task(task)
    # ── Fix 53: Warm-up requests (3 dummy calls to prime DNS + TCP connections) ──────
    jup_quote_url = os.getenv("JUPITER_QUOTE_API", "https://api.jup.ag/swap/v1/quote")
    jup_key = os.getenv("JUPITER_API_KEY", "")
    jup_headers = {"x-api-key": jup_key} if jup_key else {}
    for _ in range(3):
        try:
            await session.get(
                f"{jup_quote_url}?inputMint=So11111111111111111111111111111111111112&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=1000000",
                headers=jup_headers,
                timeout=2,
            )
        except Exception as e:
            logger.debug(f"Jupiter warm-up GET failed: {e}")
        try:
            await session.post(
                rpc.get_rpc(),
                json={"jsonrpc": "2.0", "id": 1, "method": "getSlot"},
                timeout=2,
            )
        except Exception as e:
            logger.debug(f"RPC warm-up POST failed: {e}")

    # Fix 70: Log rotation + DB vacuum background task
    async def _maintenance():
        last_backup_time = time.time()
        while True:
            await asyncio.sleep(6 * 3600)
            # delete old .jsonl
            for f in glob.glob("*.jsonl"):
                if os.path.getmtime(f) < time.time() - 48 * 3600:
                    os.remove(f)
            
            # FIXED: Создание резервной копии базы данных каждые 12 часов + Генерация ИИ-отчета
            if time.time() - last_backup_time >= 12 * 3600:
                if shared_state.data_aggregator:
                    try:
                        await shared_state.data_aggregator.backup_database()

                        # Автоматическая генерация аналитического отчета на диске
                        from src.ingest.offline_stats_reporter import OfflineStatsReporter
                        from src.ingest.data_collector import DataCollector
                        collector = DataCollector(use_sqlite=True, db_path="bot_history.db")
                        await collector.start()
                        reporter = OfflineStatsReporter(collector)
                        await reporter.run_full_analysis(days_back=1)
                        reporter.generate_report(save_path="analysis_report.md")
                        await collector.stop()
                        logger.info("📝 OfflineStatsReporter: analysis_report.md refreshed successfully")

                        last_backup_time = time.time()
                    except Exception as backup_err:
                        logger.debug(f"Periodic maintenance analysis failed: {backup_err}")

            # FIX 154: Run DB vacuum in background thread pool to prevent Event Loop freeze
            try:
                def _db_vacuum():
                    import sqlite3
                    conn = sqlite3.connect("bot_history.db")
                    conn.execute("VACUUM;")
                    conn.close()
                await asyncio.get_running_loop().run_in_executor(None, _db_vacuum)
                logger.info("🧹 Database VACUUM completed in background thread")
            except Exception as e:
                logger.debug(f"DB vacuum failed: {e}")
            # disk check
            if shutil.disk_usage(".").free < 500 * 1024 * 1024:
                logger.critical("CRITICAL: Low disk space (<500MB)! Muting non-critical logs to prevent DB corruption.")
                logging.getLogger().setLevel(logging.ERROR)

            # FIX 160: Periodically check time sync to prevent Jito timestamp drift (every ~6h)
            try:
                await check_time_sync(session, rpc.get_rpc())
            except Exception as ntp_err:
                logger.debug(f"NTP periodic drift check failed: {ntp_err}")

    task = asyncio.create_task(_maintenance())
    shared_state.retain_background_task(task)
    _gc_task = asyncio.create_task(
        _gc_idle_collector()
    )  # Fix 57: manual GC on idle queue
    shared_state.active_tasks.add(_gc_task)
    _gc_task.add_done_callback(background_task_callback)
    # Задача 50: Защита от Slot Drift (Time Sync Guard)
    await check_time_sync(session, rpc.get_rpc())

    # ── Fix 50: Health-Factor guard before any trade is attempted ───────────────
    hf_raw = await check_marginfi_health_factor(
        session, rpc.get_rpc(), cfg.MARGINFI_ACCOUNT_PUBKEY
    )
    # ── БЛОК 14: Health Factor Guard ───────────────────────────────────────
    # 0.0  = account not found / uninitialized (critical)
    # 0<HF<1.0 = liquidation risk (critical)
    # 1.0  = healthy (parsed OK)
    # None = RPC error (transient — proceed with caution)
    if hf_raw is not None and hf_raw < 1.0:
        if hf_raw == 0.0:
            logger.critical(
                f"🛑 БЛОК 14: MarginFi account {cfg.MARGINFI_ACCOUNT_PUBKEY[:8]}... NOT FOUND or UNINITIALIZED. "
                "Bot cannot trade without a valid MarginFi account. Run MarginFi deposit first."
            )
        else:
            logger.critical(
                f"🛑 БЛОК 14: MarginFi account Health Factor {hf_raw:.4f} < 1.0. "
                "Clear your MarginFi debt before starting the bot."
            )
        sys.exit(1)
    if hf_raw is not None and hf_raw == 1.0:
        logger.info(
            "✅ БЛОК 14: MarginFi account validated — ready for flash loan trading."
        )

    # 1. Core Data & Scaling Components
    data_aggregator = DataAggregator()
    shared_state.data_aggregator = data_aggregator
    await data_aggregator.start_batch_writer()

    # ── Этап 1: Backup DB and reconcile inflight bundles ────────────────────
    await data_aggregator.backup_database()
    await reconcile_inflight_bundles(session, rpc_url)

    # ── Этап 3: Prometheus metric update ────────────────────────────────────
    PROMETHEUS_VIRTUAL_BALANCE.set(shared_state.stats.get("virtual_balance", balance_sol if balance_sol else 0.0))

    flywheel_scaler = FlywheelScaler(initial_balance=0.017)
    arbitrage_scorer = ArbitrageScorer(session=session, rpc_url=rpc.get_rpc())

    # 2. State Management
    pool_state_manager = PoolStateManager(
        websocket_url=cfg.WSS_ENDPOINTS[0], pool_addresses=[]
    )

    alt_manager = ALTCacheManager(rpc_url=rpc.get_rpc(), session=session)
    shared_state.alt_manager = alt_manager
    await alt_manager.initialize_cache()

    # Task 5: Slot Drift Compensator — initialize blockhash racing manager
    _all_rpc_endpoints = (
        rpc.all_nodes
        if hasattr(rpc, "all_nodes") and rpc.all_nodes
        else [rpc.get_rpc()]
    )
    _bh_mgr = init_blockhash_racing(_all_rpc_endpoints)
    await _bh_mgr.start(session)
    global blockhash_mgr
    blockhash_mgr = _bh_mgr
    logger.info(
        f"⏱️ Slot Drift Compensator initialized with {len(_all_rpc_endpoints)} RPC endpoint(s)"
    )

    # Task 3b: Load persisted extra accounts from disk (survives bot restarts)
    try:
        _extra_on_disk = _load_extra_accounts()
        for _strat_key, _extra_pks in _extra_on_disk.items():
            if _strat_key.startswith("_"):
                continue
            STRATEGY_EXTRA_ACCOUNTS.setdefault(_strat_key, set()).update(
                set(_extra_pks)
            )
        _extra_total = sum(
            len(v) for k, v in _extra_on_disk.items() if not k.startswith("_")
        )
        if _extra_total:
            logger.info(
                f"📂 Loaded {_extra_total} persisted extra accounts from {EXTRA_ACCOUNTS_FILE}"
            )
    except Exception as _load_err:
        logger.debug(f"extra_accounts.json loading failed: {_load_err}")

    global leader_tracker
    leader_tracker = LeaderTracker(
        rpc_url=rpc.get_rpc(), fetch_interval_ms=cfg.LEADER_FETCH_INTERVAL
    )
    await leader_tracker.start(session)

    # Fix 37: jito_leader_tracker removed (RNG-based, replaced by real leader_tracker above)

    jito_executor = None
    if JITO_AVAILABLE:
        jito_executor = JitoExecutor(
            session=session,
            bundle_endpoint=cfg.JITO_ENDPOINTS[0] if cfg.JITO_ENDPOINTS else None,
            keypair=keypair,
        )
        await jito_executor.start()

    # God-mode Jito Bidding Manager — tip_floor poller + step-up/down + capital guard
    global jito_bidding_manager
    jito_bidding_manager = JitoBiddingManager()
    if JITO_AVAILABLE:
        # Phase 35: Dynamic Jito Tip Accounts pre-fetch
        await jito_bidding_manager.update_tip_accounts(session)

        _poll_task = asyncio.create_task(jito_bidding_manager.poll_tip_floor(session))
        # noinspection PyTypeChecker
        # _poll_task is intentionally fire-and-forget; it exits when run() exits
        shared_state.active_tasks.add(_poll_task)
        _poll_task.add_done_callback(background_task_callback)
        logger.info("🎯 Jito bidding manager started (polling tip_floor every 10s)")
        shared_state.jito_bidding_manager = jito_bidding_manager

    execution_router = ExecutionRouter(
        leader_tracker=leader_tracker,
        jito_executor=jito_executor,
        session=session,
        rpc_url=rpc.get_rpc(),
        keypair=keypair,
        alt_manager=alt_manager,
        rpc_getter=lambda: rpc.get_rpc(),
        cfg=cfg,
        data_aggregator=data_aggregator,
        data_collector=data_collector,
        stats=shared_state.stats,
        stats_lock=shared_state.stats_lock,
        blockhash_mgr=blockhash_mgr,
        jito_bidding_manager=jito_bidding_manager,
    )
    execution_router.start_processor()

    # Сохраняем пул глобально для всех модулей
    shared_state.marginfi_pool = execution_router.marginfi_pool

    # 4. Webhook & Strategy Routing
    async def handle_webhook_opportunity(opportunity, webhook_id):
        logger.debug(f"🚨 Webhook Triggered: {opportunity.get('strategy', 'unknown')}")
        # FIX 135: On-chain enrichment instead of fake 0.01 SOL constants
        expected_profit_sol = 0.0001
        if opportunity.get('type') == 'sanctum_lst_arbitrage' and opportunity.get('tokens_involved'):
            try:
                from src.ingest.lst_route_aggregator import LstRouteAggregator
                route_aggregator = LstRouteAggregator(
                    session=session,
                    jupiter_api_key=cfg.JUPITER_API_KEY,
                    slippage_bps=cfg.SLIPPAGE_BPS,
                    sanctum_enabled=cfg.SANCTUM_ROUTER_ENABLED,
                )
                lst_mints = [t for t in opportunity['tokens_involved'] if t != "So11111111111111111111111111111111111111112"]
                if lst_mints:
                    lst_mint = lst_mints[0]
                    route = await route_aggregator.find_best_route(
                        borrow_amount_lamports=int(cfg.FLASH_LOAN_SIZE_SOL * 1e9),
                        lst_mint=lst_mint,
                        direction="BUY_LST",
                        base_fee_sol=cfg.BASE_FEE,
                        priority_fee_sol=cfg.PRIORITY_FEE,
                        jito_tip_sol=0.0001
                    )
                    if route and route.is_profitable:
                        expected_profit_sol = route.profit_sol
                        opportunity['expected_profit_sol'] = expected_profit_sol
                        opportunity['leg1_quote'] = route.buy_quote.full_quote_response
                        opportunity['leg2_quote'] = route.sell_quote.full_quote_response
                        logger.info(f"Webhook Enriched: Real on-chain profit for {lst_mint[:8]} is {expected_profit_sol:.6f} SOL")
            except Exception as e:
                logger.warning(f"Failed to enrich webhook opportunity: {e}")

        arb_opp = ArbitrageOpportunity(
            pair=opportunity.get("description", "Webhook/Arb"),
            expected_profit_sol=opportunity.get("expected_profit_sol", expected_profit_sol),
            slippage_pct=0.01,
            liquidity_depth_usd=50000,
            network_congestion=50.0,
            gas_cost_sol=0.0001,
            execution_time_ms=0,
            timestamp=time.time(),
            metadata={"is_webhook": True, "raw_data": opportunity},
        )
        arb_opp.score = 95.0
        priority_queue.add_opportunity(arb_opp)
        shared_state.stats["last_opportunity_ts"] = time.time()

    # Strat 3: Helius webhook handler
    jito_shotgun = JitoShotgun(session)  # FIX 131
    helius_webhook_handler = HeliusWebhookHandler(
        data_aggregator,
        cfg.WEBHOOK_PORT,
        opportunity_callback=handle_webhook_opportunity,
        webhook_queue=events_config.lst_webhook_trigger,
        on_token_discovery=register_temporary_token,  # FIX 130
        jito_shotgun=jito_shotgun,  # FIX 131
    )

    if cfg.HELIUS_WEBHOOK_ENABLED:
        webhook_task = asyncio.create_task(helius_webhook_handler.start())
        shared_state.active_tasks.add(webhook_task)
        webhook_task.add_done_callback(background_task_callback)
    else:
        logger.info("ℹ️ Helius webhook handler disabled")

    global dust_sweeper
    dust_sweeper = DustSweeper(keypair, rpc.get_rpc(), session)
    task = asyncio.create_task(dust_sweeper.sweep_on_startup())
    shared_state.retain_background_task(task)

    # [TASK 49] Periodic Dust Sweep (15-min fallback, primary sweep is post-trade)
    async def periodic_dust_sweep():
        while True:
            await asyncio.sleep(900)  # 15 minutes fallback
            try:
                await dust_sweeper._sweep_dust()
            except Exception as e:
                logger.error(f"Periodic dust sweep failed: {e}")

    task = asyncio.create_task(periodic_dust_sweep())
    shared_state.retain_background_task(task)

    # 7. Balance & Health Monitoring
    async def wallet_balance_listener():
        from spl.token.instructions import close_account, CloseAccountParams
        from spl.token.instructions import get_associated_token_address
        from solders.compute_budget import (
            set_compute_unit_limit,
            set_compute_unit_price,
        )

        wsol_mint = Pubkey.from_string("So11111111111111111111111111111111111111112")
        wsol_ata = get_associated_token_address(keypair.pubkey(), wsol_mint)

        # FIX 157: Check GLOBAL_STOP_EVENT to terminate instantly on emergency stop
        while not shared_state.GLOBAL_STOP_EVENT.is_set():
            try:
                # 1. Проверяем нативный баланс
                # PAPER TRADING GUARD: skip real wallet maintenance in paper mode
                if cfg.PAPER_TRADING_ONLY:
                    await asyncio.sleep(2.0)
                    continue
                current_balance = await StateManager.get_balance(
                    session, rpc, keypair.pubkey()
                )
                if current_balance is not None:
                    shared_state.stats["last_balance"] = current_balance

                    # 2. Если нативный SOL падает ниже 0.01 SOL (опасно!)
                    if current_balance < 0.01:
                        logger.warning(
                            f"⚠️ Native SOL critically low ({current_balance} SOL). Checking wSOL for unwrap..."
                        )

                        # Fix 1 (wSOL Death Spiral): If the atomic arb path just closed wSOL
                        # inside the transaction, skip the standalone close to avoid races + gas waste.
                        if (
                            time.time() - shared_state.WSOL_JUST_CLOSED_ATOMICALLY
                            < WSOL_CLOSE_COOLDOWN
                        ):
                            logger.debug(
                                f"🔓 wSOL was atomically closed {time.time() - shared_state.WSOL_JUST_CLOSED_ATOMICALLY:.0f}s ago — "
                                f"skipping standalone unwrap to prevent duplicate close"
                            )
                            continue  # keep sleeping; the atomic path already replenished native SOL

                        # Проверяем баланс wSOL ATA
                        payload = {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "getTokenAccountBalance",
                            "params": [str(wsol_ata)],
                        }
                        async with session.post(rpc.get_rpc(), json=payload) as resp:
                            data = orjson.loads(await resp.read())
                            if "result" in data and "value" in data["result"]:
                                wsol_amount = int(data["result"]["value"]["amount"])

                                # Если скопили хотя бы 0.005 wSOL профита - конвертируем в нативный
                                if wsol_amount > 1_000_000:
                                    logger.info(
                                        f"🔄 Unwrapping {wsol_amount / 1e9} wSOL to Native SOL to replenish gas!"
                                    )

                                    # Закрытие wSOL ATA автоматически переводит все средства в Native SOL
                                    close_ix = close_account(
                                        CloseAccountParams(
                                            program_id=TOKEN_PROGRAM_ID,
                                            account=wsol_ata,
                                            dest=keypair.pubkey(),
                                            owner=keypair.pubkey(),
                                            signers=[],
                                        )
                                    )

                                    # Fix 4: Add Priority Fee so TX doesn't hang in mempool for hours
                                    cu_limit_ix = set_compute_unit_limit(50_000)
                                    cu_price_ix = set_compute_unit_price(
                                        100_000
                                    )  # ~0.000005 SOL priority fee
                                    blockhash = await get_current_blockhash(
                                        session, rpc.get_rpc()
                                    )
                                    msg = MessageV0.try_compile(
                                        keypair.pubkey(),
                                        [cu_limit_ix, cu_price_ix, close_ix],
                                        [],
                                        Hash.from_string(blockhash),
                                    )
                                    tx = VersionedTransaction(msg, [keypair])
                                    if str(os.getenv("PAPER_TRADING_ONLY", "false")).lower() == "true":
                                        continue
                                    tx_b64 = base64.b64encode(bytes(tx)).decode("ascii")
                                    await session.post(
                                        rpc.get_rpc(),
                                        json={
                                            "jsonrpc": "2.0",
                                            "id": 1,
                                            "method": "sendTransaction",
                                            "params": [tx_b64],
                                        },
                                    )
                                    logger.info(
                                        f"✅ wSOL successfully unwrapped to native SOL"
                                    )

                                    # ATA будет пересоздана автоматически при следующем арбитраже через CREATE_ATA_FUNCTION

                        # 🔴 THREAT #1 FIX: Auto-swap USDC → Native SOL when gas runs low
                        # After wSOL unwrap, re-check native balance before USDC swap
                        native_after_unwrap = await StateManager.get_balance(
                            session, rpc, keypair.pubkey()
                        )
                        if (
                            native_after_unwrap is not None
                            and native_after_unwrap < 0.005
                        ):
                            USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
                            usdc_ata = get_associated_token_address(
                                keypair.pubkey(), Pubkey.from_string(USDC_MINT)
                            )
                            usdc_payload = {
                                "jsonrpc": "2.0",
                                "id": 1,
                                "method": "getTokenAccountBalance",
                                "params": [str(usdc_ata)],
                            }
                            async with session.post(
                                rpc.get_rpc(), json=usdc_payload
                            ) as usdc_resp:
                                usdc_data = await usdc_resp.json()
                                if (
                                    "result" in usdc_data
                                    and "value" in usdc_data["result"]
                                ):
                                    usdc_amount = int(
                                        usdc_data["result"]["value"]["amount"]
                                    )
                                    # Need at least $2 in USDC to cover aggregated coins
                                    if usdc_amount > 2_000_000:
                                        logger.info(
                                            f"🔄 GAS REPLENISHMENT: Swapping exactly 2 USDC ({2_000_000} micro-USDC) to Native SOL "
                                            f"(USDC balance: {usdc_amount / 1_000_000:.2f})"
                                        )
                                        try:
                                            from src.ingest.jupiter_api_client import (
                                                JupiterClient,
                                                QUOTE_API_URL,
                                                SWAP_API_URL,
                                            )

                                            async with JupiterClient(
                                                session=session
                                            ) as jup:
                                                # Step 1: Get quote for USDC → SOL swap (exactly 2 USDC)
                                                quote = await jup.get_quote(
                                                    input_mint=USDC_MINT,
                                                    output_mint="So11111111111111111111111111111111111111112",
                                                    amount=2_000_000,  # Exactly 2 USDC
                                                    slippage_bps=100,  # 1% slippage tolerance
                                                )
                                                if "error" in quote:
                                                    logger.error(
                                                        f"❌ Jupiter quote failed for USDC→SOL swap: {quote['error']}"
                                                    )
                                                    continue

                                                # Step 2: Build signed swap transaction
                                                swap_tx = (
                                                    await jup.get_swap_transaction(
                                                        quote,
                                                        str(keypair.pubkey()),
                                                        wrap_unwrap_sol=False,
                                                    )
                                                )
                                                if "error" in swap_tx:
                                                    logger.error(
                                                        f"❌ Jupiter swap tx failed for USDC→SOL swap: {swap_tx['error']}"
                                                    )
                                                    continue

                                                # Step 3: Decode the versioned transaction
                                                signed_tx = JupiterClient.decode_swap_transaction(
                                                    swap_tx
                                                )
                                                if signed_tx is None:
                                                    logger.error(
                                                        "❌ Failed to decode Jupiter swap transaction"
                                                    )
                                                    continue

                                                # Step 4: Resign with our keypair (Jupiter tx is not yet signed)
                                                try:
                                                    signed_tx = VersionedTransaction(
                                                        signed_tx.message,
                                                        [keypair],
                                                    )
                                                except Exception as resign_err:
                                                    logger.error(
                                                        f"❌ Failed to re-sign Jupiter tx: {resign_err}"
                                                    )
                                                    continue

                                                # Step 5: Broadcast via direct RPC (NOT Jito — avoid front-run)
                                                tx_b64_swap = base64.b64encode(
                                                    bytes(signed_tx)
                                                ).decode("ascii")
                                                if str(os.getenv("PAPER_TRADING_ONLY", "false")).lower() == "true":
                                                    continue
                                                send_response = await session.post(
                                                    rpc.get_rpc(),
                                                    json={
                                                        "jsonrpc": "2.0",
                                                        "id": 1,
                                                        "method": "sendTransaction",
                                                        "params": [
                                                            tx_b64_swap,
                                                            {
                                                                "skipPreflight": False,
                                                                "maxRetries": 3,
                                                            },
                                                        ],
                                                    },
                                                )
                                                if send_response.status == 200:
                                                    swap_result = (
                                                        await send_response.json()
                                                    )
                                                    logger.info(
                                                        f"✅ GAS REFILL: USDC→SOL swap relayed: "
                                                        f"{swap_result}"
                                                    )
                                                else:
                                                    logger.error(
                                                        f"❌ Swap broadcast returned "
                                                        f"HTTP {send_response.status}: "
                                                        f"{await send_response.text()}"
                                                    )
                                        except Exception as jup_err:
                                            logger.error(
                                                f"❌ USDC→SOL swap failed: {jup_err}"
                                            )
            except Exception as e:
                logger.debug(f"Balance listener/unwrap error: {e}")

            # FIX 157: Wait on GLOBAL_STOP_EVENT to terminate instantly on stop
            try:
                await asyncio.wait_for(shared_state.GLOBAL_STOP_EVENT.wait(), timeout=120.0)
                break
            except asyncio.TimeoutError:
                pass

    _wallet_task = asyncio.create_task(wallet_balance_listener())
    shared_state.active_tasks.add(_wallet_task)
    _wallet_task.add_done_callback(background_task_callback)


    # 8. Warm-up
    initial_balance = None
    while initial_balance is None:
        initial_balance = await StateManager.get_balance(session, rpc, keypair.pubkey())
        if initial_balance is None:
            logger.warning("⏳ Ожидание готовности RPC... Повтор через 5 секунд")
            await asyncio.sleep(5)

    shared_state.stats["last_balance"] = initial_balance
    try:
        with open("bot_health.json", "r") as f:
            health_data = orjson.loads(f.read())
            shared_state.stats["virtual_balance"] = health_data.get(
                "balance", initial_balance
            )
            logger.info(
                f"⚖️ Loaded persisted virtual balance: {shared_state.stats['virtual_balance']:.6f} SOL"
            )
    except Exception:
        shared_state.stats["virtual_balance"] = initial_balance
    shared_state.stats["initial_balance"] = initial_balance
    import src.ingest.shared_state as _ss
    _ss.init_global_scaler(initial_balance)

    # Seed Hard Floor Guard (Task 47)
    task = asyncio.create_task(hard_floor_guard())
    shared_state.retain_background_task(task)

    # Jupiter Warm-up (Paper Trading Bypass: no route restriction)
    try:
        url = os.getenv("JUPITER_QUOTE_API", "https://api.jup.ag/swap/v1/quote")
        jup_key = os.getenv("JUPITER_API_KEY", "")
        headers = {"x-api-key": jup_key} if jup_key else {}
        params = {
            "inputMint": "So11111111111111111111111111111111111112",
            "outputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "amount": "100000000",
            "slippageBps": "50",
        }
        async with session.get(url, params=params, headers=headers) as resp:
            if resp.status == 200:
                logger.debug("✅ Jupiter warm-up successful")
    except Exception as e:
        logger.debug(f"Jupiter warm-up failed: {e}")

    # ── TASK 1: ATA Ghosting Pre-Warm ─────────────────────────────────────────
    # DISABLED for micro-capital (0.017 SOL): creating 5 ATAs costs ~0.01 SOL
    # in rent and hits STRICT_GAS_TANK immediately, freezing the bot before
    # the first trade. Jupiter swap-instructions (setupInstructions) already
    # create ATAs atomic-ally and recover the rent when the TX finalizes.
    # Pre-warm ATA cache to avoid slow RPC calls in hot path
    await warmup_golden_atas(session, rpc.get_rpc(), keypair.pubkey())

    # ── TASK 3: WebSocket Liveness Guard (StaleStreamGuard) ───────────────────
    # Monitors shared_state.stats["current_slot"] (updated by blockhash_updater every 2 s).
    # If no slot update arrives within STALE_SLOT_TIMEOUT, force-reconnects
    # HeliusWebhookHandler and PoolStateManager so the bot recovers from a
    # ghosted / frozen WebSocket within milliseconds, not system timeout seconds.
    STALE_SLOT_TIMEOUT = 5.0  # seconds
    shared_state.stats["_sg_last_slot"] = shared_state.stats.get("current_slot", 0)
    shared_state.stats["_sg_last_slot_ts"] = time.time()

    async def _stale_stream_guard():
        while True:
            try:
                await asyncio.sleep(0.25)
                now_slot = shared_state.stats.get("current_slot", 0)
                last_tracked = shared_state.stats.get("_sg_last_slot", 0)
                last_ts = shared_state.stats.get("_sg_last_slot_ts", time.time())

                if now_slot == last_tracked and last_tracked != 0:
                    stale_secs = time.time() - last_ts
                    if stale_secs > STALE_SLOT_TIMEOUT:
                        logger.critical(
                            f"🚨 STALE STREAM GUARD: slot={now_slot} unchanged for {stale_secs:.1f}s — "
                            "clearing blockhash cache and restarting handlers due to validator slot-skip."
                        )
                        # Принудительно сбрасываем кэш блокхеша, чтобы исключить BlockhashExpired
                        global cached_blockhash
                        cached_blockhash = None
                        # Reconnect HeliusWebhookHandler
                        if helius_webhook_handler:
                            try:
                                await helius_webhook_handler.stop()
                                await asyncio.sleep(0.5)
                                task = asyncio.create_task(helius_webhook_handler.start())
                                shared_state.retain_background_task(task)
                            except Exception:
                                pass
                        # Reset tracker so we don't loop-spam restarts
                        shared_state.stats["_sg_last_slot_ts"] = time.time()
                else:
                    shared_state.stats["_sg_last_slot"] = now_slot
                    shared_state.stats["_sg_last_slot_ts"] = time.time()
            except Exception as _sg_err:
                logger.debug(f"StaleStreamGuard tick error: {_sg_err}")
                await asyncio.sleep(0.25)

    task = asyncio.create_task(_stale_stream_guard())
    shared_state.retain_background_task(task)

    # Priority queue processor for AI-scored opportunities
    async def priority_queue_processor():
        """Реактивный обработчик очереди: 0 мс задержки на запуск транзакции."""
        logger.info("🧠 Реактивный процессор очереди запущен (0ms polling penalty)")
        sem = asyncio.Semaphore(cfg.MAX_CONCURRENT_ARBITRAGES)
        
        async def _execute_with_sem(opp):
            async with sem:
                await execute_priority_opportunity(
                    opp,
                    session,
                    cfg,
                    rpc,
                    keypair,
                    jito_executor,
                    data_collector,
                    flywheel_scaler,
                    data_aggregator,
                    alt_manager=alt_manager,
                    execution_router=execution_router,
                    blockhash_mgr=blockhash_mgr,
                )
        
        while True:
            try:
                opportunity = await priority_queue.get_next_opportunity_async()
                task = asyncio.create_task(_execute_with_sem(opportunity))
                shared_state.retain_background_task(task)
            except Exception as e:
                logger.error(f"Priority queue processor error: {e}")
                await asyncio.sleep(1)

    # Fix 62: Start Pyth Core Price Feeder for real-time SOL/USDC/USDT prices
    # Updates both arb_bot.price_matrix and _set_global_price_matrix atomically
    try:
        pyth_feeder = init_pyth_core_feeder()
        task = asyncio.create_task(
            pyth_feeder.start(on_price_update=update_global_price_matrix)
        )
        shared_state.retain_background_task(task)
        logger.info(
            "📡 PythCorePriceFeeder started with unified price matrix callback (Fix 62)"
        )
    except Exception as pyth_err:
        logger.warning(f"PythCorePriceFeeder startup failed (non-fatal): {pyth_err}")

    # 9. Main Processing Loops
    queue = asyncio.PriorityQueue(maxsize=5000)

    tasks = [
        asyncio.create_task(update_prices(session, cfg)),
        asyncio.create_task(blockhash_updater(session, lambda: rpc.get_rpc())),
        # DISABLED: stable_scanner — RPS-heavy polling (Helius 429 prevention)
        # asyncio.create_task(stable_scanner(queue, cfg)),        # Fast stables (1.5s)
        asyncio.create_task(lst_scanner(queue, cfg)),  # Loop B: LST arbitrage (2.0s)
        # DISABLED: rwa_rest_scanner — RPS-heavy polling (15.0s interval)
        # asyncio.create_task(rwa_rest_scanner(queue, cfg)),
        # DISABLED: dexscreener_scanner — RPS-heavy external API polling
        # asyncio.create_task(dexscreener_scanner(queue, session, cfg))
        asyncio.create_task(
            priority_queue_processor()
        ),  # ENABLED: AI-powered priority processor
        *[
            asyncio.create_task(
                worker(
                    queue,
                    session,
                    cfg,
                    rpc,
                    keypair,
                    limiters,
                    jito_executor,
                    arbitrage_scorer,
                    priority_queue,
                    alt_manager=alt_manager,
                    execution_router=execution_router,
                )
            )
            for _ in range(cfg.WORKER_COUNT)
        ],
        # ULTRA ARB MASTER — background tasks commented out (components disabled)
        # ULTRA ARB - Production-Ready Tasks
        asyncio.create_task(dust_sweep_background()),
        asyncio.create_task(cleanup_temporary_tokens()),
        # FIXED: Запуск ежедневного обслуживания и ротации БД
        asyncio.create_task(_daily_cleanup(data_aggregator)),
        # Virtual Balance Reconciler — re-anchors virtual_balance every 30 s
        asyncio.create_task(
            balance_reconciler(session, rpc.get_rpc(), keypair, jito_executor)
        ),
    ]

    # FIX 122: Add all loops to active_tasks for graceful shutdown
    shared_state.active_tasks.update(tasks)
    def make_cb(task_to_remove):
        return lambda _: shared_state.active_tasks.discard(task_to_remove)
    for t in list(shared_state.active_tasks):
        t.add_done_callback(make_cb(t))

    # Yellowstone gRPC removed.
    # LST Depeg Flash-Arb Scanner (primary strategy)
    if cfg.LST_DEPEG_ENABLED:
        lst_task = asyncio.create_task(
            lst_depeg_scanner(
                session,
                cfg,
                rpc,
                keypair,
                jito_executor,
                events_config.lst_webhook_trigger,  # ИСПРАВЛЕНИЕ ССЫЛКИ
                blockhash_mgr=blockhash_mgr,
            )
        )
        tasks.append(lst_task)
        logger.debug("🌊 LST Depeg Flash-Arb Scanner ENABLED (Blue Ocean)")
    else:
        logger.debug("ℹ️ LST Depeg Flash-Arb Scanner DISABLED")


    # LST Instant Unstake Arbitrage Scanner
    if cfg.LST_UNSTAKE_ARB_ENABLED:
        unstake_task = asyncio.create_task(
            lst_unstake_arbitrage_scanner(
                session,
                cfg,
                rpc,
                keypair,
                jito_executor,
                jito_bidding_manager=jito_bidding_manager,
                data_aggregator=data_aggregator,
            )
        )
        tasks.append(unstake_task)
        logger.info("🔄 LST Instant Unstake Arbitrage Scanner ENABLED")
    else:
        logger.info("ℹ️ LST Instant Unstake Arbitrage Scanner DISABLED")


    # Wrapper Peg Arbitrage Scanner
    wrapper_peg_task = asyncio.create_task(
        wrapper_peg_scanner(
            session,
            cfg,
            rpc,
            keypair,
            jito_executor,
            execution_router=execution_router,
        )
    )
    tasks.append(wrapper_peg_task)
    logger.info("🔄 BTC Wrapper Peg Arbitrage Scanner ENABLED")

    logger.debug(f"🚀 Matrix Scanner launched! Initial Balance: {initial_balance} SOL")

    try:
        while not shared_state.GLOBAL_STOP_EVENT.is_set():
            try:
                await asyncio.wait_for(shared_state.GLOBAL_STOP_EVENT.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                pass
            current_balance = await StateManager.get_balance(
                session, rpc, keypair.pubkey()
            )
            if current_balance is None:
                continue

            shared_state.stats["last_balance"] = current_balance

            # Задача 52: Локальный мониторинг (Health Check File)
            try:
                with open("bot_health.json", "wb") as f:
                    f.write(
                        orjson.dumps(
                            {
                                "last_ping": time.time(),
                                "balance": shared_state.stats.get("virtual_balance", shared_state.stats.get("last_balance")),
                                "trades": shared_state.stats.get("trades"),
                                "last_opportunity_ts": shared_state.stats.get("last_opportunity_ts", 0.0),
                                "consecutive_failures": shared_state.stats.get("consecutive_failures", 0),
                            }
                        )
                    )
            except Exception as e:
                logger.debug(f"Heartbeat write error: {e}")

            # Update metrics & Log Stats
            working_cap = (current_balance - cfg.MIN_RESERVE_SOL) * cfg.TRADE_SIZE_PCT
            bir = (
                (
                    shared_state.stats["bundle_successes"]
                    / shared_state.stats["bundle_send_attempts"]
                )
                * 100
                if shared_state.stats["bundle_send_attempts"] > 0
                else 0
            )
            avg_sel = (
                sum(shared_state.stats["state_to_execution_latencies"])
                / len(shared_state.stats["state_to_execution_latencies"])
                if shared_state.stats["state_to_execution_latencies"]
                else 0
            )
            flash_miss_rate = (
                (
                    shared_state.stats["flash_loan_miss_count"]
                    / shared_state.stats["flash_loan_attempt_count"]
                )
                * 100
                if shared_state.stats["flash_loan_attempt_count"] > 0
                else 0
            )

            # FIX 161: Log actual process memory utilization via psutil
            try:
                p_mem = psutil.Process(os.getpid()).memory_info()
                rss_mb = p_mem.rss / (1024 * 1024)
                logger.info(f"📊 [RESOURCE ENGINE] Memory allocation: RSS={rss_mb:.2f}MB")
            except Exception:
                pass
            logger.debug(
                f"📊 [STATS] Balance: {current_balance:.8f} | WC: {working_cap:.8f} | Trades: {shared_state.stats['trades']} | BIR: {bir:.1f}% | SEL: {avg_sel:.1f}ms"
            )

            # ── Этап 2: Capital Protection circuit breaker check ─────────────────
            if shared_state.capital_protection:
                shared_state.capital_protection.reset_if_needed()
                stop, reason = shared_state.capital_protection.should_stop()
                if stop:
                    logger.critical(f"🚨 CAPITAL PROTECTION TRIGGERED: {reason}")
                    with open(".capital_protection_triggered", "w") as f:
                        f.write(reason)
                    await send_telegram_alert(f"<b>CAPITAL PROTECTION TRIGGERED</b>\n{reason}")
                    shared_state.GLOBAL_STOP_EVENT.set()
                    break

            # ── Этап 3: Update Prometheus metrics ──────────────────────────────
            PROMETHEUS_VIRTUAL_BALANCE.set(shared_state.stats.get("virtual_balance", current_balance))

            # Balance Guard + Fix 68: Dust Reserve
            if current_balance < 0.005:
                logger.critical(
                    "🚨 DEBT CEILING REACHED: 0.005 SOL native. Starting emergency recovery before shutdown..."
                )
                # ── ИСПРАВЛЕНИЕ: Реализация экстренной паники (Task 12) ──
                try:
                    # 1. Запускаем экстренное закрытие пустых ATA для возврата SOL
                    if "dust_sweeper" in locals() and dust_sweeper:
                        logger.info("🧹 Emergency recovery: sweeping empty ATAs...")
                        await dust_sweeper._sweep_dust()
                    # 2. Пытаемся конвертировать остатки USDC обратно в SOL для заправки бака
                    from src.ingest.gas_manager import check_and_refill_gas

                    await check_and_refill_gas(session, rpc, keypair)
                except Exception as panic_err:
                    logger.critical(f"Emergency recovery failed: {panic_err}")
                shared_state.GLOBAL_STOP_EVENT.set()
                break
            if current_balance < initial_balance * 0.3:
                logger.critical(
                    f"🚨 BALANCE GUARD ACTIVATED: Balance {current_balance:.8f} SOL dropped below 30%"
                )
                await send_telegram_alert(f"<b>BALANCE GUARD ACTIVATED</b>\nBalance dropped to {current_balance:.6f} SOL")
                # FIX #25: Trigger global stop to halt ALL background tasks
                if shared_state.GLOBAL_STOP_EVENT is not None:
                    shared_state.GLOBAL_STOP_EVENT.set()
                break
    finally:
        logger.debug("🛑 Shutting down arbitrage engine components...")

        try:
            if "leader_tracker" in locals() and leader_tracker:
                await leader_tracker.stop()
                logger.info("⚙️ Leader tracker components stopped cleanly.")
        except Exception as e:
            logger.debug(f"Failed to cleanly stop leader_tracker: {e}")

        # 1. Принудительно отменяем все фоновые задачи ДО закрытия сессии
        for task in list(shared_state.active_tasks):
            if not task.done():
                task.cancel()

        # 2. Ждем их корректного завершения
        if shared_state.active_tasks:
            await asyncio.gather(*shared_state.active_tasks, return_exceptions=True)

        # 3. AsyncLogger: flush
        try:
            if "logger_obj" in locals() and logger_obj:
                await logger_obj.stop()
        except Exception:
            pass

        # 4. Только теперь безопасно закрываем HTTP сессию
        if "session" in locals() and session and not session.closed:
            await session.close()

        # Phase 20 Task 5: Close RPCManager to release ClientSession sockets
        if "rpc" in locals() and rpc is not None:
            try:
                await rpc.close()
            except Exception as _rpc_close_err:
                logger.warning(f"RPCManager close failed: {_rpc_close_err}")

        # FIX 164: Terminate macOS insomnia guard child process
        if getattr(shared_state, "caffeinate_proc", None):
            try:
                shared_state.caffeinate_proc.terminate()
                shared_state.caffeinate_proc.wait(timeout=2.0)
                logger.info("🔌 Insomnia guard (caffeinate) successfully closed.")
            except Exception:
                pass
        # FIX 123: Stop Pyth Feeder to prevent WSS leak
        try:
            if "pyth_feeder" in locals() and pyth_feeder:
                await pyth_feeder.stop()
        except Exception:
            pass
        if "jito_executor" in locals() and jito_executor:
            try:
                await jito_executor.stop()
            except Exception:
                pass
        if "helius_webhook_handler" in locals() and helius_webhook_handler:
            try:
                await helius_webhook_handler.stop()
            except Exception:
                pass
        if "data_aggregator" in locals() and data_aggregator:
            try:
                await data_aggregator.stop_batch_writer()
            except Exception:
                pass


class StateManager:
    @staticmethod
    async def get_balance_lamports(session, rpc_manager, pubkey):
        # Fix 72: Force confirmed commitment (never use processed)
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [str(pubkey), {"commitment": "confirmed"}],
        }
        timeout = aiohttp.ClientTimeout(total=3.0)
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        }

        for attempt in range(3):
            try:
                rpc_url = rpc_manager.get_rpc()
            except Exception as e:
                logger.error(f"No available RPCs: {e}")
                return None

            logger.debug(
                f"🔍 Попытка {attempt+1}: проверяем RPC {repr(rpc_url)[:60]}..."
            )

            try:
                import src.ingest.shared_state as shared_state
                async with shared_state.rpc_limiter:
                    async with session.post(
                        rpc_url, json=payload, headers=headers, timeout=timeout
                    ) as resp:
                        if resp.status == 200:
                            data = orjson.loads(await resp.read())
                        if "result" in data:
                            logger.debug("✅ Баланс успешно получен")
                            return data["result"]["value"]
                        else:
                            error_text = await resp.text()
                        logger.warning(
                            f"Ошибка {resp.status} на RPC. Ответ: {error_text}"
                        )
                        if (
                            resp.status == 401
                            or "invalid api key" in error_text.lower()
                        ):
                            rpc_manager.blacklist(rpc_url)
            except Exception as e:
                logger.warning(f"Исключение на RPC: {e}")

        logger.error("Все 3 попытки RPC провалились, возвращаем None")
        return None

    @staticmethod
    async def get_balance(session, rpc_manager, pubkey):
        balance_lamports = await StateManager.get_balance_lamports(
            session, rpc_manager, pubkey
        )
        return None if balance_lamports is None else balance_lamports / 1e9


async def handle_graduation_event(opportunity, session, cfg, rpc, keypair):
    """Handle token graduation event."""
    try:
        logger.debug(
            f"🎓 Graduation Event: {opportunity.token_pair} | "
            f"Platform: {opportunity.trigger_data.get('platform')}"
        )

        # Execute pre-computed graduation arbitrage
        # This would integrate with Jito sniper for instant execution

    except Exception as e:
        logger.error(f"Graduation event handling error: {e}")


# ULTRA ARB - Advanced Strategy Event Handlers
async def handle_liquidation_opportunity(opportunity, liquidation_engine, keypair):
    """Quarantined legacy liquidation callback.

    PR-020 liquidation planning is shadow-only and must not route through the
    legacy executor, sender, signer, Jito, or keypair path. The old direct executor call is intentionally removed from the reachable
    callback so `src/ingest/liquidator_engine.py` can remain
    an unmodified legacy artifact while active runtime stays isolated.
    """
    logger.warning("legacy liquidation opportunity ignored: PR-020 is shadow-only")
    return False


async def handle_epoch_opportunity(opportunity, epoch_tracker, keypair, jito_executor):
    """Handle LST epoch rebalance opportunity."""
    try:
        logger.debug(
            f"🕐 Epoch Opportunity: {opportunity.lst_token} | "
            f"Rate Change: {opportunity.rate_change_pct:.2%} | "
            f"Seconds until epoch: {opportunity.seconds_until_epoch}"
        )

        # Execute epoch arbitrage
        success = await epoch_tracker.execute_epoch_arbitrage(
            opportunity, keypair, jito_executor
        )

        if success:
            logger.debug("✅ Epoch arbitrage successfully executed")
        else:
            logger.warning("❌ Epoch arbitrage execution failed")

    except Exception as e:
        logger.error(f"Epoch opportunity handling error: {e}")


# ULTRA ARB - Market Expansion Event Handlers
async def handle_wrapper_opportunity(opportunity):
    """Handle wrapper peg arbitrage opportunity."""
    pass


async def handle_volatility_signal(signal):
    """Handle volatility-triggered arbitrage signal."""
    pass


async def handle_receipt_opportunity(opportunity):
    """Handle receipt token arbitrage opportunity."""
    pass


async def execute_ultra_arbitrage(cycle: ArbitrageCycle, session, rpc, keypair):
    """Execute arbitrage with full Ultra Arb protection and correct math."""
    pass


# ULTRA ARB - Background Scanning Functions
async def volatility_monitor_background():
    """Background monitor for token volatility."""
    pass


async def dust_sweep_background():
    """Background dust sweeping every 30 minutes."""
    while True:
        try:
            await asyncio.sleep(1800)  # 30 minutes
            recovered = await dust_sweeper.sweep_on_startup()
            if recovered > 0:
                logger.info(
                    f"🧹 Background dust sweep recovered {recovered / 1e9:.6f} SOL"
                )
        except Exception as e:
            logger.error(f"Background dust sweep error: {e}")
            await asyncio.sleep(300)  # Retry in 5 minutes


async def _build_burn_instruction_atlanta(
    token_account: str, mint: str, amount_lamports: int, keypair
):
    """Build TokenProgram.Burn instruction for SPL token (Task 52 — Phase 41).
    Uses SPL Token program."""
    try:
        from spl.token.instructions import BurnParams, burn

        program_id = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")

        burn_params = BurnParams(
            program_id=program_id,
            account=Pubkey.from_string(token_account),
            mint=Pubkey.from_string(mint),
            owner=keypair.pubkey(),
            amount=amount_lamports,
        )
        return burn(burn_params)
    except Exception as e:
        logger.debug(f"Burn instruction build failed: {e}")
        return None


# =============================================================================
# MTU Size Padding (Kernel Task 5)
# =============================================================================
# Thin QUIC packets (< 500 B) are deprioritised by Solana network providers.
# This helper decompiles a VersionedTransaction, checks its serialised size,
# and — if it falls below the threshold — appends a harmless duplicate
# SetComputeUnitLimit as a no-op padding instruction so the frame expands to
# ~600 B.  The entire operation is local-only (no RPC round-trip).
_MTU_PAD_MIN_BYTES = 500  # pad if below this
_MTU_PAD_TARGET_BYTES = 600  # target size after padding


def _ensure_mtu_size(
    tx: VersionedTransaction, cu_limit: int = 0
) -> VersionedTransaction:
    # FIX 117: Do not append instructions after the transaction is signed,
    # otherwise SignatureVerificationFailed occurs. Return as is.
    return tx


async def close_ata_after_arbitrage(session, keypair, rpc_getter, ata_address: str):
    """Task 52 — Burn-before-close ATA."""
    try:
        # Check ATA balance
        balance_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountBalance",
            "params": [ata_address],
        }
        timeout = aiohttp.ClientTimeout(total=2.0)
        import src.ingest.shared_state as shared_state
        async with shared_state.rpc_limiter:
            async with session.post(
                rpc_getter(), json=balance_payload, timeout=timeout
            ) as resp:
                if resp.status != 200:
                    logger.debug(f"Failed to check ATA balance: {resp.status}")
                    return
                data = orjson.loads(await resp.read())
                if "result" not in data or "value" not in data["result"]:
                    logger.debug(f"No balance data for ATA {str(ata_address)[:8]}")
                    return
    
                value = data["result"]["value"]
            raw_amount_str = value.get("amount", "0")  # integer lamports (base units)
            ui_amount = float(value.get("uiAmountString") or "0")
            decimals = int(value.get("decimals", 6))

            # Phase 48: Golden ATA Protection — never close wSOL or USDC
            SOL_MINT = "So11111111111111111111111111111111111111112"
            USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            from spl.token.instructions import get_associated_token_address

            wsol_ata = str(
                get_associated_token_address(
                    keypair.pubkey(), Pubkey.from_string(SOL_MINT)
                )
            )
            usdc_ata = str(
                get_associated_token_address(
                    keypair.pubkey(), Pubkey.from_string(USDC_MINT)
                )
            )
            if str(ata_address) in [wsol_ata, usdc_ata]:
                logger.debug(f"Preserving golden ATA: {ata_address}")
                return

            if ui_amount == 0 and int(raw_amount_str or 0) == 0:
                logger.debug(
                    f"ATA {str(ata_address)[:8]} is already empty — nothing to burn or close"
                )
                return

            # Determine mint address for this ATA (needed for burn instruction)
            mint = value.get("mint")

            close_instructions = []

            # Task 52: Burn-before-close — flush non-zero residue to prevent TokenAccountNotEmpty
            # ФИКС 2: raw_amount_str уже в базовых единицах, умножение на децимали НЕ ТРЕБУЕТСЯ
            # Phase 21: Remove from ATA_CACHE optimistically BEFORE async close
            # Prevents race: if next trade starts and checks ATA_CACHE, it sees
            # stale entry and skips ATA creation — then the close lands and swap fails.
            try:
                import src.ingest.shared_state as _ss_t2
                ata_str = str(ata_address) if not isinstance(ata_address, str) else ata_address
                if ata_str in _ss_t2.ATA_CACHE:
                    await _ss_t2.discard_from_ata_cache(ata_str)
                    logger.debug(f"🧹 Phase 21: Removed {ata_str[:8]} from ATA_CACHE before close")
            except Exception:
                pass

            raw_amount = int(raw_amount_str or 0)
            if raw_amount > 0:
                burn_ix = await _build_burn_instruction_atlanta(
                    str(ata_address), mint, raw_amount, keypair
                )
                if burn_ix:
                    close_instructions.append(burn_ix)
                    logger.debug(
                        f"🔥 Burning {raw_amount} lamports ({ui_amount} tokens) from {str(ata_address)[:8]}…"
                    )

            # Build CloseAccount instruction (runs regardless — handles zero-leftover path)
            from spl.token.instructions import CloseAccountParams, close_account

            close_program_id = Pubkey.from_string(
                "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
            )

            close_params = CloseAccountParams(
                account=Pubkey.from_string(ata_address),
                dest=keypair.pubkey(),
                owner=keypair.pubkey(),
                program_id=close_program_id,
                signers=[],
            )
            close_instructions.append(close_account(close_params))

            # === Build transaction ===
            from solders.message import MessageV0
            from solders.transaction import VersionedTransaction
            from solders.compute_budget import set_compute_unit_limit

            cu_limit_ix = set_compute_unit_limit(50_000)

            # Get blockhash
            blockhash_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getLatestBlockhash",
            }
            import src.ingest.shared_state as shared_state
            async with shared_state.rpc_limiter:
                async with session.post(
                    rpc_getter(), json=blockhash_payload, timeout=timeout
                ) as resp:
                    if resp.status != 200:
                        logger.debug("Failed to get blockhash for ATA close")
                        return
                    bh_data = orjson.loads(await resp.read())
                    blockhash = bh_data["result"]["value"]["blockhash"]

            message = MessageV0.try_compile(
                payer=keypair.pubkey(),
                instructions=[cu_limit_ix] + close_instructions,
                address_lookup_table_accounts=[],
                recent_blockhash=Pubkey.from_string(blockhash),
            )
            tx = VersionedTransaction(message, [keypair])

            # Send transaction
            tx_b64 = base64.b64encode(bytes(tx)).decode()
            send_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendTransaction",
                "params": [tx_b64, {"encoding": "base64"}],
            }
            import src.ingest.shared_state as shared_state
            async with shared_state.rpc_limiter:
                async with session.post(
                    rpc_getter(), json=send_payload, timeout=timeout
                ) as resp:
                    if resp.status == 200:
                        send_data = orjson.loads(await resp.read())
                        if "result" in send_data:
                            logger.debug(
                                f"✅ ATA burn+close done, rent recovered: {str(send_data['result'])[:8]}"
                            )
                            await shared_state.discard_from_ata_cache(ata_address)
                        else:
                            logger.debug(f"ATA burn+close failed: {send_data}")
                    else:
                        logger.debug(f"ATA burn+close send failed: {resp.status}")
    
    except Exception as e:
            logger.debug(f"ATA burn+close error: {e}")
    

if __name__ == "__main__":
    _convert_tokens_to_pubkeys()
    import platform

    if platform.system() != "Darwin":
        try:
            import uvloop

            asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
            logger.info("⚡ uvloop установлен (максимальная скорость)")
        except ImportError:
            logger.info("ℹ️ uvloop не найден, используем стандартный asyncio")
    else:
        logger.info("🍏 macOS detected: using standard asyncio to prevent SSL crashes")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    finally:
        try:
            pending = asyncio.all_tasks(loop=loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
        except Exception:
            pass
        loop.close()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    finally:
        try:
            pending = asyncio.all_tasks(loop=loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
        except Exception:
            pass
        loop.close()
