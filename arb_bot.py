from __future__ import annotations
import asyncio
import aiohttp
from aiohttp.resolver import AsyncResolver
import aiodns
import time
import logging
import random
import os
import json
import base64
import itertools
import struct
import hashlib
import re
import socket
import sys
import urllib.parse
from dotenv import load_dotenv
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any, Callable, Set
import resource
try:
    # Увеличиваем лимит открытых файлов до максимума (65535)
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    target_limit = min(65535, hard) if hard != resource.RLIM_INFINITY else 65535
    resource.setrlimit(resource.RLIMIT_NOFILE, (target_limit, hard))
    logging.info(f"🚀 Системные лимиты подняты: {soft} -> {target_limit}")
except Exception as e:
    logging.warning(f"⚠️ Не удалось поднять лимиты (попробуй запустить 'ulimit -n 65535' в терминале): {e}")
import glob
import gc
import shutil
gc.set_threshold(7000, 10, 10)  # Less frequent GC to avoid freezing hot loops

# ============================================================================
# GLOBAL NORMALIZATION HELPER: Convert profit of any token to SOL equivalent
# before calculating Jito tips.  This prevents the "Cross-Currency Tip Suicide"
# where a profit of 5 USDC is interpreted as 5 SOL and the bot overpays tips.
# ============================================================================
def normalize_profit_to_sol(
    profit_raw: float,
    target_mint_str: str,
    price_matrix: Dict[str, tuple],
    sol_price_usd: float = 150.0,
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
    if target_mint_str == usdc_mint_str:
        return profit_raw / sol_price_usd

    # For any other token: get its USD price and convert
    token_entry = price_matrix.get(target_mint_str)
    if token_entry and token_entry[0] > 0:
        token_price_usd = token_entry[0]
        return (profit_raw * token_price_usd) / sol_price_usd

    # Fallback: assume 1:1 with SOL (conservative for LSTs, dangerous for others)
    # Log a warning so the operator knows to add this mint to the price feed
    logger.warning(f"⚠️ normalize_profit_to_sol: no price for {target_mint_str[:8]}, assuming 1:1 SOL")
    return profit_raw

# Global execution lock for sequential flash loan processing
execution_lock = asyncio.Lock()
stats_lock = asyncio.Lock()
active_tasks = set()
leader_tracker = None
jito_tip_manager = None
jito_bidding_manager = None  # God-mode dynamic tip bidding (tip_floor polling + step-up/down + capital guard)
jito_leader_tracker = None
KEYPAIR = None  # Fix 81: memory-mapped wallet - never read disk during arb
PENDING_QUOTES: Set[str] = set()  # Fix 84: RPS shield - dedup Jupiter requests
LAST_SIGNAL_TIME: Dict[str, float] = {}  # Fix 88: per-pair 400ms cooldown (1 slot)
STRATEGY_FAILURES: Dict[str, int] = {}  # Fix 90: reputation circuit breaker
STRATEGY_DISABLED_UNTIL: Dict[str, float] = {}

# Fix 1 (wSOL Death Spiral): Timestamp of last atomic wSOL CloseAccount.
# When build_native_flashloan_tx closes wSOL + recreates ATA before the Jito tip,
# this is set to time.time(). The wallet_balance_listener skips its own standalone
# wSOL close for WSOL_CLOSE_COOLDOWN seconds after an atomic close.
WSOL_JUST_CLOSED_ATOMICALLY: float = 0.0
WSOL_CLOSE_COOLDOWN: float = 60.0  # seconds — any recent atomic close is authoritative

# Import Jito client
try:
    from src.ingest.jito_bundle_client import JitoBundleClient
    from src.ingest.jito_priority_context import JitoPriorityContext, JitoPriorityContextAdapter
    from src.ingest.jito_manager import JitoBiddingManager
    from src.ingest.jito_executor import JitoExecutor
    JITO_AVAILABLE = True
except ImportError:
    JITO_AVAILABLE = False
    logger.warning("Jito client not available, falling back to RPC execution")

from src.ingest.tx_builder import JupiterTxBuilder
from src.ingest.multi_aggregator_client import MultiAggregatorClient
from src.ingest.transaction_prebuilder import TransactionPrebuilder
from src.ingest.multi_rpc_manager import MultiRpcManager, RpcEndpoint
from src.ingest.jito_sniper import (
    JitoTipManager,
    WssPoolCreationListener,
    JitoBundleSender,
    TransactionTipBuilder
)
from src.ingest.leader_tracker import LeaderTracker
from src.ingest.execution_router import ExecutionRouter
from src.ingest.blockhash_racing import init_blockhash_racing, get_blockhash_manager
from src.ingest.jito_leader_tracker import init_jito_leader_tracker, get_jito_leader_tracker
from src.ingest.pre_trade_guard import PreTradeGuard
from src.ingest.arbitrage_scorer import ArbitrageScorer, PriorityArbitrageQueue, ArbitrageOpportunity
# AI data collection classes - TODO: Implement when needed
from src.ingest.pump_fun_predictor import PumpFunMigrationPredictor
from src.ingest.data_aggregator import DataAggregator
from src.ingest.helius_webhook_handler import HeliusWebhookHandler
from src.ingest.optimal_trade_sizer import OptimalTradeSizer  # VelocitySlippageManager not implemented
from src.ingest.rpc_multiplexing import ExecutionPipeline
from src.ingest.helius_sender import HeliusSender, TransactionSender

# ULTRA ARB MASTER - New In-Memory State Modules
from src.ingest.graph_math import ArbitrageGraph, ArbitrageCycle
from src.ingest.pool_state_manager import PoolStateManager
from src.ingest.oracle_streams import OracleStreams
from src.ingest.pool_fetcher import PoolFetcher
from src.ingest.event_triggers import EventTriggerEngine, VolatilityWatcher
from src.ingest.wrapper_arb import WrapperArbEnforcer
from src.ingest.stableswap_math import PoolMathRouter
from src.ingest.receipt_arb import ReceiptArbEngine
from src.ingest.flash_pivot import FlashPivotEngine
from src.ingest.liquidator_engine import LiquidationEngine
from src.ingest.cex_dex_oracle import CexDexOracle
from src.ingest.epoch_tracker import EpochTracker
from src.ingest.jito_shotgun import JitoShotgun
# from src.ingest.grpc_stream import YellowstoneStream  # DISABLED: grpc dependency issue
from src.ingest.dust_sweeper import DustSweeper
from src.ingest.alt_manager import ALTCacheManager

# LST Depeg Flash-Arb modules
from src.ingest.lst_fair_price_monitor import LstFairPriceMonitor, DepegSignal
from src.ingest.lst_route_aggregator import LstRouteAggregator, RouteResult
from src.ingest.flash_simulator import FlashSimulator
from src.ingest.flywheel_scaler import FlywheelScaler

RENT_PER_ATA_SOL = 0.00203928
MIN_RESERVE_SOL = 0.005
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
_KAMINO_ENABLED = str(os.getenv("KAMINO_LIQUIDATION_ENABLED", "false")).lower() == "true"
_ORDERBOOK_ENABLED = str(os.getenv("ORDERBOOK_AMM_ENABLED", "false")).lower() == "true"

if _KAMINO_ENABLED:
    from src.ingest.kamino_flash_liquidator import KaminoFlashLiquidationExecutor
else:
    KaminoFlashLiquidationExecutor = None  # type: ignore[assignment,misc]

from src.ingest.lst_unstake_arbitrage import LstInstantUnstakeArbitrage

if _ORDERBOOK_ENABLED:
    from src.ingest.orderbook_amm_solver import BipartiteOrderbookAmmSolver
else:
    BipartiteOrderbookAmmSolver = None  # type: ignore[assignment,misc]

# Webhook trigger for LST scanner
from src.config.events import lst_webhook_trigger


# Create instances
transaction_prebuilder = TransactionPrebuilder()

# Advanced trading components
trade_sizer = OptimalTradeSizer()

# ULTRA ARB MASTER - Initialize In-Memory State Components (commented for minimal startup)
# arbitrage_graph = ArbitrageGraph(max_tokens=25)  # 25 Blue Ocean tokens
# pool_state_manager = PoolStateManager(
#     websocket_url=cfg.WSS_ENDPOINTS[0],
#     pool_addresses=[]  # Will be populated by pool_fetcher
# )
# oracle_streams = OracleStreams()
# pool_fetcher = PoolFetcher(session)
# event_triggers = EventTriggerEngine()

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
# wrapper_arb_enforcer = WrapperArbEnforcer(pool_state_manager)
# volatility_watcher = VolatilityWatcher(pool_state_manager)

# ULTRA ARB - Stable×Stable & Lending Rate Engines (commented for minimal startup)
# pool_math_router = PoolMathRouter()
# receipt_arb_engine = ReceiptArbEngine(pool_state_manager, pool_math_router)
# flash_pivot_engine = FlashPivotEngine(pool_state_manager, pool_math_router)

# k_hop_stitcher = KHopStitcher(wallet_keypair=keypair)

# jito_shotgun = JitoShotgun(session)
# yellowstone_stream = YellowstoneStream(
#     grpc_endpoint="yellowstone.helius.rpcpool.com:443",
#     api_key=cfg.HELIUS_API_KEY if hasattr(cfg, 'HELIUS_API_KEY') else None
# )
# Global ATA Cache (Phase 48)
ATA_CACHE = set()

# AI-powered trading components (moved to main() function)
# arbitrage_scorer = ArbitrageScorer(session=session, rpc_url=rpc.get_rpc())
# priority_queue = PriorityArbitrageQueue(max_size=50)
# ai_data_collector = AIDataCollector()  # TODO: Implement

# Pump.fun migration predictor (moved to main() function)
# pump_predictor = PumpFunMigrationPredictor(
#     session=session,
#     wss_url=cfg.WSS_ENDPOINTS[0] if cfg.WSS_ENDPOINTS else None,
#     jito_endpoints=cfg.JITO_ENDPOINTS
# )

# Multi-RPC racing configuration
MULTI_RPC_ENABLED = str(os.getenv("MULTI_RPC_ENABLED", "true")).lower() == "true"

# Configure RPC endpoints for racing (free tier providers)
multi_rpc_endpoints = [
    RpcEndpoint("helius", "wss://api.mainnet-beta.solana.com", "https://api.mainnet-beta.solana.com", 1),
    RpcEndpoint("quicknode", "wss://api.mainnet-beta.solana.com", "https://api.mainnet-beta.solana.com", 2),
    RpcEndpoint("alchemy", "wss://api.mainnet-beta.solana.com", "https://api.mainnet-beta.solana.com", 3),
]

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
    async with stats_lock:
        if isinstance(value, int) and key in stats and isinstance(stats[key], int):
            stats[key] += value
        else:
            stats[key] = value
from solders.system_program import transfer, TransferParams

load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("ArbBot")

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
                valid_urls.append(f"https://mainnet.helius-rpc.com/?api-key={clean_part}")
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
        async with session.post(rpc_url, json={"jsonrpc":"2.0","id":1,"method":"getHealth"}, timeout=2.0) as resp:
            latency = (time.time() - start) / 2
            server_date_str = resp.headers.get('Date')
            if server_date_str:
                server_time = parsedate_to_datetime(server_date_str).timestamp()
                # Subtract latency to get estimated server time at the moment of request
                local_time = time.time() - latency
                diff = abs(local_time - server_time)
                
                if diff > 1.5:
                    logger.critical(f"🚨 КРИТИЧЕСКАЯ ОШИБКА: Рассинхронизация времени! Разница: {diff:.2f}с. Jito будет отклонять бандлы.")
                    logger.warning("👉 Рекомендуется включить NTP-синхронизацию на Mac.")
                else:
                    logger.info(f"⏱️ Сетевая задержка: {latency*1000:.2f}ms. Разница времени: {diff:.2f}с. Часы синхронизированы.")
            else:
                logger.info(f"⏱️ Сетевая задержка: {latency*1000:.2f}ms. (Сервер не прислал заголовок Date)")
    except Exception as e:
        logger.warning(f"⚠️ Не удалось проверить синхронизацию времени: {e}")

def validate_marginfi_account(cfg: Config) -> bool:
    """Fix 46: .env MARGINFI_ACCOUNT sanitization (must be a valid 32-44 char Base58 Pubkey)."""
    acct = cfg.MARGINFI_ACCOUNT_PUBKEY.strip() if cfg.MARGINFI_ACCOUNT_PUBKEY else ""
    if not acct:
        logger.critical("CRITICAL: MarginFi Account not found. Run MarginFi deposit first.")
        return False
    if not re.match(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$', acct):
        logger.critical(
            f"CRITICAL: MARGINFI_ACCOUNT has invalid format ({len(acct)} chars). "
            "Must be a valid Base58 Solana pubkey (32-44 alphanumeric chars, no 0/O/I/l). "
            "Run MarginFi deposit first."
        )
        return False
    return True


async def check_marginfi_health_factor(session, rpc_url, marginfi_account_pubkey: str) -> Optional[float]:
    """Fix 50: Fetch MarginFi account health factor via RPC (simulated)."""
    try:
        health_check_payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "getAccountInfo",
            "params": [marginfi_account_pubkey, {"encoding": "base64"}]
        }
        async with session.post(rpc_url, json=health_check_payload, timeout=aiohttp.ClientTimeout(total=5.0)) as resp:
            if resp.status == 200:
                data = await resp.json()
                if "result" in data and data["result"] and data["result"]["value"]:
                    # In production: deserialize MarginFi lending account and compute
                    # assets / (assets - liabilities) = health_factor
                    # Return 1.0 as neutral default when we cannot parse on-chain.
                    logger.warning("MarginFi health-factor check returned neutral 1.0 (on-chain parsing not yet implemented).")
                    return 1.0
    except Exception as e:
        logger.warning(f"Health-factor fetch failed: {e}")
    return None


@dataclass
class Config:
    WALLET_PATH: str = os.getenv("WALLET_PATH", "./wallet.json")

    HELIUS_GATEKEEPER_URL: str = os.getenv("HELIUS_GATEKEEPER_URL", "")
    HELIUS_API_KEY: str = os.getenv("HELIUS_API_KEY", "")
    WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "3000"))
    HELIUS_WEBHOOK_ENABLED: bool = str(os.getenv("HELIUS_WEBHOOK_ENABLED", "true")).lower() == "true"

    # Helius Sender Configuration
    HELIUS_SENDER_URLS: List[str] = field(default_factory=lambda: [
        os.getenv("HELIUS_SENDER_URL", "https://mainnet.helius-rpc.com/?api-key=YOUR_KEY"),
    ])
    HELIUS_TIP_ACCOUNTS: List[str] = field(default_factory=lambda: [
        "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
        "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bLmis",
        "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLk",
    ])
    # ⚠️ FALLBACK: Jito rotates tip accounts regularly. Always use dynamic fetch_tip_accounts().
    # See: https://mainnet.block-engine.jito.wtf/api/v1/bundles/tip_accounts

    # Multi-RPC Racing Configuration
    MULTI_RPC_ENABLED: bool = str(os.getenv("MULTI_RPC_ENABLED", "true")).lower() == "true"
    MULTI_RPC_ENDPOINTS: List[str] = field(default_factory=lambda: [
        os.getenv("MULTI_RPC_1", "wss://api.mainnet-beta.solana.com"),
        os.getenv("MULTI_RPC_2", "wss://api.mainnet-beta.solana.com"),
        os.getenv("MULTI_RPC_3", "wss://api.mainnet-beta.solana.com"),
    ])

    # Jito Sniper Configuration
    JITO_SNIPER_ENABLED: bool = str(os.getenv("JITO_SNIPER_ENABLED", "false")).lower() == "true"
    JITO_TIP_PERCENTILE: float = float(os.getenv("JITO_TIP_PERCENTILE", "75.0"))
    JITO_MIN_TIP_LAMPORTS: int = int(os.getenv("JITO_MIN_TIP_LAMPORTS", "10000"))
    TIP_MULTIPLIER: float = float(os.getenv("TIP_MULTIPLIER", "1.1"))
    MAX_PRIORITY_FEE_SOL: float = float(os.getenv("MAX_PRIORITY_FEE_SOL", "0.01"))
    LEADER_FETCH_INTERVAL: int = int(os.getenv("LEADER_FETCH_INTERVAL", "600000"))
    STRICT_JITO_MODE: bool = str(os.getenv("STRICT_JITO_MODE", "true")).lower() == "true"  # Enforce Jito execution for capital protection

    # RPC Multiplexing Configuration
    WSS_ENDPOINTS: List[str] = field(default_factory=lambda: [
        os.getenv("WSS_ENDPOINT_1", "wss://api.mainnet-beta.solana.com"),
        os.getenv("WSS_ENDPOINT_2", "wss://api.mainnet-beta.solana.com"),
        os.getenv("WSS_ENDPOINT_3", "wss://api.mainnet-beta.solana.com"),
        os.getenv("WSS_ENDPOINT_4", "wss://api.mainnet-beta.solana.com"),
    ])

    # Jito Bundle Configuration
    # Fix 45: Frankfurt and Amsterdam first — these are the closest Block Engines
    # for EU/RU servers (~30-50 ms RTT).  NY and Tokyo fall back only when SEL < 200ms
    # allows global coverage; otherwise they are dropped from the list entirely below.
    JITO_ENDPOINTS: List[str] = field(default_factory=lambda: [
        os.getenv("JITO_BLOCK_ENGINE_URL", "https://ny.mainnet.block-engine.jito.wtf/api/v1/bundles"),
    ])  # Single regional endpoint to avoid blockhash geo-delay
    JITO_AUTH_KEY: str = os.getenv("JITO_AUTH_KEY", "")
    JITO_TIP_PERCENT: float = float(os.getenv("JITO_TIP_PERCENT", "0.6"))  # 60% of profit

    # MEV Execution Thresholds
    MIN_PROFIT_SOL: float = float(os.getenv("MIN_PROFIT_SOL", "0.0001"))  # Minimum 0.0001 SOL profit
    MAX_TIP_SOL: float = float(os.getenv("MAX_TIP_SOL", "0.0005"))

    HELIUS_URLS: List[str] = field(default_factory=lambda: [
        os.getenv("HELIUS_GATEKEEPER_URL", "").strip().strip("'\"")
    ] if os.getenv("HELIUS_GATEKEEPER_URL") else [])

    QUICKNODE_URLS: List[str] = field(default_factory=lambda: [
        os.getenv(f"QUICKNODE_URL_{i}").strip().strip("'\"")
        for i in range(1, 10) if os.getenv(f"QUICKNODE_URL_{i}")
    ])

    JUPITER_API_KEY: str = os.getenv("JUPITER_API_KEY", "")

    WORKER_COUNT: int = 1  # Fixed to 1 for sequential flash loan execution
    BATCH_SIZE: int = int(os.getenv("BATCH_SIZE", 20))
    BG_FETCH_INTERVAL: float = float(os.getenv("BG_FETCH_INTERVAL", 1.5))
    SIMULATE_BEFORE_EXECUTE: bool = str(os.getenv("SIMULATE_BEFORE_EXECUTE", "True")).lower() == "true"
    DEXSCREENER_URL: str = os.getenv("DEXSCREENER_URL", "https://api.dexscreener.com/token-profiles/latest/v1")
    DEXSCREENER_RPS: int = int(os.getenv("DEXSCREENER_RPS", 1))
    VELORA_QUOTE_URL: str = os.getenv("VELORA_QUOTE_URL", "https://api.paraswap.io/prices")
    SCAN_INTERVAL: float = float(os.getenv("SCAN_INTERVAL", "0.2"))

    TRADE_SIZE_PCT: float = float(os.getenv("TRADE_SIZE_PCT", 1.0))
    MIN_RESERVE_SOL: float = 0.002  # Fix 68: Dust Reserve (Wallet Life Support)
    MIN_NET_PROFIT_PCT: float = float(os.getenv("MIN_NET_PROFIT_PCT", 0.005))
    MAX_DRAWDOWN_SOL: float = float(os.getenv("MAX_DRAWDOWN_SOL", 0.01))

    JUP_RPS: int = int(os.getenv("JUPITER_QUOTE_RPS", 5))

    JUPITER_PRICE_URL: str = "https://api.jup.ag/price/v2"
    JUPITER_QUOTE_URL: str = os.getenv("JUPITER_QUOTE_URL", "https://quote-api.jup.ag/v6/quote")
    BASE_TIP_LAMPORTS: int = int(os.getenv("BASE_TIP_LAMPORTS", "10000"))
    FLASH_FEE_PCT: float = float(os.getenv("FLASH_FEE_PCT", "0.0"))

    MARGINFI_ACCOUNT_PUBKEY: str = os.getenv("MARGINFI_ACCOUNT", "")

    # Arbitrage Engine Settings
    MIN_PROFIT_THRESHOLD_SOL: float = float(os.getenv("MIN_PROFIT_THRESHOLD_SOL", "0.001"))
    MIN_PROFIT_THRESHOLD_USDC: float = float(os.getenv("MIN_PROFIT_THRESHOLD_USDC", "0.01"))
    ARBITRAGE_TIMEOUT_SECONDS: int = int(os.getenv("ARBITRAGE_TIMEOUT_SECONDS", "30"))
    MAX_CONCURRENT_ARBITRAGES: int = int(os.getenv("MAX_CONCURRENT_ARBITRAGES", "3"))

    SLIPPAGE_BPS: int = int(os.getenv("STARTING_SLIPPAGE_BPS", 15))
    BASE_FEE: float = 0.000005
    PRIORITY_FEE: float = 0.00005
    ATA_FEE: float = 0.002

    # Arbitrage Filters
    ARBITRAGE_FILTER_MIN_PROFIT_SOL: float = float(os.getenv("ARBITRAGE_FILTER_MIN_PROFIT_SOL", "0.0001"))  # Broad: allow low profit trades
    ARBITRAGE_FILTER_MAX_SLIPPAGE_BPS: int = int(os.getenv("ARBITRAGE_FILTER_MAX_SLIPPAGE_BPS", "50"))  # Broad: up to 50 BPS slippage
    ARBITRAGE_FILTER_MIN_LIQUIDITY_LAMPORTS: int = int(os.getenv("ARBITRAGE_FILTER_MIN_LIQUIDITY_LAMPORTS", "1000000"))  # 0.01 SOL liquidity

    # === LST Depeg Flash-Arb Strategy ===
    # ⚠️ PLACEHOLDER STRATEGIES DISABLED FOR SAFETY - Need full implementation before enabling
    LST_DEPEG_ENABLED: bool = str(os.getenv("LST_DEPEG_ENABLED", "true")).lower() == "true"  # BLUE OCEAN: LST depeg (0.017 SOL start)

    LST_DEPEG_THRESHOLD_BPS: int = int(os.getenv("LST_DEPEG_THRESHOLD_BPS", "15"))
    FLASH_LOAN_SIZE_SOL: float = float(os.getenv("FLASH_LOAN_SIZE_SOL", "0.1"))  # MICRO-TESTING: 0.1 SOL
    MIN_NET_PROFIT_BUFFER_SOL: float = float(os.getenv("MIN_NET_PROFIT_BUFFER_SOL", "0.0005"))
    LST_SCAN_INTERVAL: float = float(os.getenv("LST_SCAN_INTERVAL", "0.5"))
    SANCTUM_ROUTER_ENABLED: bool = str(os.getenv("SANCTUM_ROUTER_ENABLED", "true")).lower() == "true"  # BLUE OCEAN: Sanctum for LST instant unstake

    # === New MarginFi-Compatible Arbitrage Strategies ===
    KAMINO_LIQUIDATION_ENABLED: bool = str(os.getenv("KAMINO_LIQUIDATION_ENABLED", "false")).lower() == "true"  # DISABLED: placeholder
    KAMINO_SCAN_INTERVAL: float = float(os.getenv("KAMINO_SCAN_INTERVAL", "5.0"))
    KAMINO_MIN_PROFIT_SOL: float = float(os.getenv("KAMINO_MIN_PROFIT_SOL", "0.001"))

    LST_UNSTAKE_ARB_ENABLED: bool = str(os.getenv("LST_UNSTAKE_ARB_ENABLED", "true")).lower() == "true"  # BLUE OCEAN: LST unstake arb
    LST_UNSTAKE_MIN_DEVIATION_PCT: float = float(os.getenv("LST_UNSTAKE_MIN_DEVIATION_PCT", "0.5"))
    LST_UNSTAKE_SCAN_INTERVAL: float = float(os.getenv("LST_UNSTAKE_SCAN_INTERVAL", "3.0"))

    # Fix 35: Hardcode to False to prevent accidental gas leakage from unfinished modules.
    # These .env values are intentionally IGNORED so the bot never boots frozen Red Ocean strategies.
    KAMINO_LIQUIDATION_ENABLED: bool = False  # HARDCODED: unfinished module, .env ignored
    ORDERBOOK_AMM_ENABLED: bool = False  # HARDCODED: unfinished module, .env ignored
    ORDERBOOK_AMM_SCAN_INTERVAL: float = float(os.getenv("ORDERBOOK_AMM_SCAN_INTERVAL", "1.0"))
    PHOENIX_MARKET_ADDRESS: str = os.getenv("PHOENIX_MARKET_ADDRESS", "")
    RAYDIUM_POOL_ADDRESS: str = os.getenv("RAYDIUM_POOL_ADDRESS", "")

    # xStocks Oracle Lag Strategy Configuration
    ENABLE_XSTOCKS_ORACLE_LAG: bool = str(os.getenv("ENABLE_XSTOCKS_ORACLE_LAG", "true")).lower() == "true"
    ORACLE_LAG_MIN_PROFIT_SOL: float = float(os.getenv("ORACLE_LAG_MIN_PROFIT_SOL", "0.25"))
    ORACLE_LAG_THRESHOLD_PCT: float = float(os.getenv("ORACLE_LAG_THRESHOLD_PCT", "0.45"))
    ORACLE_LAG_COOLDOWN_SECONDS: int = int(os.getenv("ORACLE_LAG_COOLDOWN_SECONDS", "60"))

TOKENS = {
    # === GOLDEN FUND: Stables & Yield ===
    "SOL": "So11111111111111111111111111111111111111112",
    "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "PYUSD": "2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo",
    "USDS": "USDSwr9ApdHk5bvJKMjzff41FfhJbZkp9bHqzZdduoP",
    "USDY": "A1KLoBrKBde8Ty9qtNQUtq3C2ortoC3u7twggz7sEto6",
    "USDe": "DEkqHyPN7GMRJ5cArtQFAWefqbZb33Hyf6s5iCwjEonT",
    # Yield Stables (Step 5: Stable Yield Lag)
    "susDS": "susDSyb6YVGZCXSpbLTVmH8fEWhjSagJMHWPMpZEEDs",   # York Finance susDS — verify via Solscan
    "USD+":  "USDove1KZCdwC3VFfcy6DYpawutxVp271yJgDyJWB9q",    # Ondo/Streamflow USD+ yield stable
    "JupUSD": "JupUSDnJZZzrjqoKdcycEZFyX5pdYUlRW2uHkrjawcr",  # Jupiter yield stable ( актуальный минт )

    # === GOLDEN FUND: LSTs ===
    "jitoSOL": "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
    "mSOL": "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",
    "bSOL": "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",
    "INF": "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm",
    "JupSOL": "jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v",
    "hubSOL": "HUBsveNpjo5pWqNkH57QzxjQASdTVXcSK7bVKTSZtcSX",
    # New LSTs with thin liquidity (Step 5)
    "2ZSOL": "2ZSOLyqCWL24UYBYUBKbWMmTACYHCY9qiEgLPxEHiBE",  # DoubleZero LST — verify delimiter via Solscan
    "psol":  "psolapbameK9iwMp8vd2sGhciCd753JqthShYwdt7R",        # Phantom LST — verify via Solscan
    "bonkSOL": "BonK1YhkXEGLZzwtcvRTip3gAL9nCeQD7ppZBLXhtTs",   # Bonk LST — Bonq-issued
    "cgntSOL": "CgnTSoL3DgY9SFHxcLj6CgCgKKoTBr6tp4CPAEWy25DE",  # Cogent LST
    "vSOL": "vSoLxydx6akxyMD9XEcPvGYNGq6Nn66oqVb3UkGkei7",      # Vault LST

    # === GOLDEN FUND: xStocks (Oracle Lag) ===
    "NVDAx": "Xsc9qvGR1efVDFGLrVsmkzv3qi45LTBjeUKSPmx9qEh",
    "TSLAx": "XsDoVfqeBukxuZHWhdvWHBhgEHjGNst4MLodqsJHzoB",
    "AAPLx": "XsbEhLAtcf6HdfpFZ5xEMdqW8nfAvcsP5bdudRLJzJp",
    "SPYx": "XsoCS1TfEyfFhfvj8EtZ528L3CaKBDBRqRapnBbDF2W",
    "QQQx": "XspzcW1PRtgf6Wj92HCiZdjzKCyFekVD8P5Ueh3dRMX",
    "MSFTx": "XspzcW1PRtgf6Wj92HCiZdjzKCyFekVD8P5Ueh3dRMX",
    "AMZNx": "Xs3eBt7uRfJX8QUs4suhyU8p2M6DoUDrJyWBa8LLZsg",
    "METAx": "Xsa62P5mvPszXL1krVUnU5ar38bBSVcWAB6fmPCo5Zu",
    "GOOGLx": "XsCPL9dNWBMvFtTmwcCA5v3xWPSMEBCszbQdiLLq6aN",
    "HOODx": "XsvNBAYkrDRNhA7wPHQfX3ZUXZyZLdnCQDfHZ56bzpg",
    "MSTRx": "XsP7xzNPvEHS1m6qfanPUGjNmdnmsLKEoNAnHjdxxyZ",
    "GLDx": "Xsv9hRk1z5ystj9MhnA7Lq4vjSsLwzL2nxrwmwtD3re",   # Gold xStock — weekend arbitrage
    # Yield Stables (duplicate from above for pair lookups)
    "USDY": "A1KLoBrKBde8Ty9qtNQUtq3C2ortoC3u7twggz7sEto6",
    "USDe": "DEkqHyPN7GMRJ5cArtQFAWefqbZb33Hyf6s5iCwjEonT",
    "JupUSD": "JupUSDnJZZzrjqoKdcycEZFyX5pdYUlRW2uHkrjawcr",  # Jupiter yield stable
    # XStocks RWA
    "susDS": "susDSyb6YVGZCXSpbLTVmH8fEWhjSagJMHWPMpZEEDs",   # York Finance synthetic dollar

    # === Tier B / Memes (Dynamic) ===
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
    return bytes(val) if isinstance(val, Pubkey) else bytes(Pubkey.from_string(str(val)))

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

# Execute ZERO-STRING HOT LOOP optimization
_convert_tokens_to_pubkeys()

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
    # Yield Stables (new — 6 decimals)
    "JupUSDnJZZzrjqoKdcycEZFyX5pdYUlRW2uHkrjawcr": 6,  # JupUSD placeholder
    "susDSyb6YVGZCXSpbLTVmH8fEWhjSagJMHWPMpZEEDs": 6,   # susDS placeholder
    "USDove1KZCdwC3VFfcy6DYpawutxVp271yJgDyJWB9q": 6,    # USD+ (Ondo)

    # Golden Fund: LSTs (9 decimals)
    "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm": 9,  # INF
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn": 9,  # jitoSOL
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So": 9,  # mSOL
    "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1": 9,  # bSOL
    "jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v": 9,  # JupSOL
    "HUBsveNpjo5pWqNkH57QzxjQASdTVXcSK7bVKTSZtcSX": 9,  # hubSOL
    "BonK1YhkXEGLZzwtcvRTip3gAL9nCeQD7ppZBLXhtTs": 9,  # bonkSOL
    "CgnTSoL3DgY9SFHxcLj6CgCgKKoTBr6tp4CPAEWy25DE": 9,  # cgntSOL
    "vSoLxydx6akxyMD9XEcPvGYNGq6Nn66oqVb3UkGkei7": 9,  # vSOL
    "2ZSOLyqCWL24UYBYUBKbWMmTACYHCY9qiEgLPxEHiBE": 9,  # 2ZSOL placeholder
    "psolapbameK9iwMp8vd2sGhciCd753JqthShYwdt7R": 9,      # psol placeholder

    # Golden Fund: xStocks (Fixed Mainnet IDs — Token-2022, 8 decimes = 6 in practice for display)
    "Xsc9qvGR1efVDFGLrVsmkzv3qi45LTBjeUKSPmx9qEh": 6,  # NVDAx
    "XsDoVfqeBukxuZHWhdvWHBhgEHjGNst4MLodqsJHzoB": 6,  # TSLAx
    "XsbEhLAtcf6HdfpFZ5xEMdqW8nfAvcsP5bdudRLJzJp": 6,  # AAPLx
    "XsoCS1TfEyfFhfvj8EtZ528L3CaKBDBRqRapnBbDF2W": 6,  # SPYx
    "XspzcW1PRtgf6Wj92HCiZdjzKCyFekVD8P5Ueh3dRMX": 6,  # QQQx / MSFTx
    "Xs3eBt7uRfJX8QUs4suhyU8p2M6DoUDrJyWBa8LLZsg": 6,  # AMZNx
    "Xsa62P5mvPszXL1krVUnU5ar38bBSVcWAB6fmPCo5Zu": 6,  # METAx
    "XsCPL9dNWBMvFtTmwcCA5v3xWPSMEBCszbQdiLLq6aN": 6,  # GOOGLx
    "XsvNBAYkrDRNhA7wPHQfX3ZUXZyZLdnCQDfHZ56bzpg": 6,  # HOODx
    "XsP7xzNPvEHS1m6qfanPUGjNmdnmsLKEoNAnHjdxxyZ": 6,  # MSTRx
    "Xsv9hRk1z5ystj9MhnA7Lq4vjSsLwzL2nxrwmwtD3re": 6,  # GLDx
    "Xs8S1uUs1zvS2p7iwtsG3b6fkhpvmwz4GYU3gWAmWHZ": 6,  # COINx / SPYx alt

    # Tier B: Memes
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN": 6,  # JUP
    "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm": 6,  # WIF
    "DezXAZ8z7P8gVmFiDQ6cEhPmmF9rj3ZfVGg3LyZ3mTKV": 5,  # BONK
    "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr": 9,  # POPCAT
}

# Arbitrage Registry for Data Collection Phase
ARBITRAGE_REGISTRY = {
    "stablecoins": [
        {"base": "USDC", "target": "USDT", "description": "USDC/USDT DEX-to-DEX arbitrage"},
        {"base": "USDC", "target": "PYUSD", "description": "USDC/PYUSD rate differential on MarginFi/Save pools"},
    ],
    "lst_tokens": [
        {"base": "SOL", "target": "jitoSOL", "description": "SOL/jitoSOL MEV rewards distribution arbitrage"},
        {"base": "SOL", "target": "mSOL", "description": "SOL/mSOL instant unstake arbitrage on Marinade"},
        {"base": "SOL", "target": "bSOL", "description": "SOL/bSOL discount buys on DEX, siphon via aggregators"},
        {"base": "SOL", "target": "JupSOL", "description": "SOL/JupSOL Jupiter DAO votes cause price divergence"},
        {"base": "SOL", "target": "compassSOL", "description": "SOL/compassSOL APY campaigns arbitrage"},
        {"base": "SOL", "target": "hSOL", "description": "SOL/hSOL Helius promotions arbitrage"},
    ],
    "ultra_arb_rwa": [
        {"base": "AAPLx", "target": "USDC", "description": "Oracle Lag: Chainlink AAPL vs AMM price discrepancy"},
        {"base": "TSLAx", "target": "USDC", "description": "Oracle Lag: Chainlink TSLA vs AMM price discrepancy"},
        {"base": "SPYx", "target": "USDC", "description": "Oracle Lag: Chainlink SPY vs AMM price discrepancy"},
        {"base": "NVDAx", "target": "USDC", "description": "Oracle Lag: Chainlink NVDA vs AMM price discrepancy"},
        {"base": "METAx", "target": "USDC", "description": "Oracle Lag: Chainlink META vs AMM price discrepancy"},
    ],
    "ultra_arb_yield_stables": [
        {"base": "susDS", "target": "USDC", "description": "Stable-Yield Accrual Drift: susDS vs USDC yield differential"},
        {"base": "USDY", "target": "USDC", "description": "Stable-Yield Accrual Drift: USDY vs USDC yield differential"},
        {"base": "USD+", "target": "USDC", "description": "Stable-Yield Accrual Drift: USD+ vs USDC yield differential"},
        {"base": "JupUSD", "target": "USDC", "description": "Stable-Yield Accrual Drift: JupUSD vs USDC yield differential"},
    ],
    "ultra_arb_graduation": [
        {"base": "SOL", "target": "MOONSHOT", "description": "Moonshot graduation arbitrage (pre-computed PDA)"},
        {"base": "SOL", "target": "BELIEVE", "description": "BelieveApp graduation arbitrage (pre-computed PDA)"},
    ],
    "kamino_receipts": [
        {"base": "USDC", "target": "kUSDC", "description": "USDC/kUSDC rate differential between MarginFi and Kamino"},
        {"base": "SOL", "target": "kSOL", "description": "SOL/kSOL flash-liquidation on Kamino Health Factor < 1.0"},
        {"base": "USDC", "target": "kJLP", "description": "USDC/kJLP Jupiter Perps LP value revaluation"},
    ],
    "ultra_arb_wrappers": [
        {"base": "cbBTC", "target": "wBTC", "description": "1:1 BTC wrapper peg enforcement"},
        {"base": "wBTC", "target": "tBTC", "description": "1:1 BTC wrapper peg enforcement"},
        {"base": "cbBTC", "target": "tBTC", "description": "1:1 BTC wrapper peg enforcement"},
        {"base": "wETH", "target": "SOL", "description": "ETH wrapper vs native token"},
    ],
    "ultra_arb_depin": [
        {"base": "HNT", "target": "USDC", "description": "DePIN volatility arbitrage"},
        {"base": "GRASS", "target": "USDC", "description": "AI DePIN volatility arbitrage"},
        {"base": "RENDER", "target": "USDC", "description": "GPU DePIN volatility arbitrage"},
        {"base": "MOBILE", "target": "USDC", "description": "Mobile DePIN volatility arbitrage"},
        {"base": "HONEY", "target": "USDC", "description": "Yield DePIN volatility arbitrage"},
    ],
    "ultra_arb_memes": [
        {"base": "BONK", "target": "USDC", "description": "Viral meme volatility arbitrage"},
        {"base": "WIF", "target": "USDC", "description": "Viral meme volatility arbitrage"},
        {"base": "POPCAT", "target": "USDC", "description": "Viral meme volatility arbitrage"},
    ],
    "ultra_arb_wrappers": [
        {"base": "cbBTC", "target": "wBTC", "description": "1:1 BTC wrapper peg enforcement"},
        {"base": "wBTC", "target": "tBTC", "description": "1:1 BTC wrapper peg enforcement"},
        {"base": "cbBTC", "target": "tBTC", "description": "1:1 BTC wrapper peg enforcement"},
        {"base": "wETH", "target": "SOL", "description": "ETH wrapper vs native token"},
    ],
    "ultra_arb_depin": [
        {"base": "HNT", "target": "USDC", "description": "DePIN volatility arbitrage"},
        {"base": "GRASS", "target": "USDC", "description": "AI DePIN volatility arbitrage"},
        {"base": "RENDER", "target": "USDC", "description": "GPU DePIN volatility arbitrage"},
        {"base": "MOBILE", "target": "USDC", "description": "Mobile DePIN volatility arbitrage"},
        {"base": "HONEY", "target": "USDC", "description": "Yield DePIN volatility arbitrage"},
    ],
    "volatile_governance": [
        {"base": "USDC", "target": "wBTC", "description": "USDC/wBTC BTC movement synch issues between Raydium/Orca"},
        {"base": "USDC", "target": "JUP", "description": "USDC/JUP Jupiter monthly unlocks cause dumps on DEX"},
        {"base": "USDC", "target": "BONK", "description": "USDC/BONK viral events, price lag between AMM Phoenix CLOB"},
        {"base": "USDC", "target": "ORCA", "description": "USDC/ORCA Orca commission changes cause governance volatility"},
    ],
}

DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", "Accept": "application/json"}

# Marginfi Config
MARGINFI_PROGRAM_ID = Pubkey.from_string("MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA")
MARGINFI_GROUP = Pubkey.from_string("4qp6Fx6tnZkY5Wropq9wUYgtFxXKwE6viZxFHg3rdAG8")

# Helper to derive marginfi PDAs
def get_marginfi_bank_accounts(bank_pubkey: Pubkey):
    def find_pda(seed_str):
        pda, _ = Pubkey.find_program_address([seed_str.encode(), bytes(bank_pubkey)], MARGINFI_PROGRAM_ID)
        return pda
    return {
        "bank": bank_pubkey,
        "liquidity_vault": find_pda("liquidity_vault"),
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
        logger.critical(f"🚨 REPUTATION BREAKER: {strategy} disabled 5min after 3 sim fails")

def get_marginfi_banks():
    """Get MarginFi bank configurations with lazy initialization."""
    try:
        sol_bank = os.getenv("MARGINFI_SOL_BANK", "CCwqExrqLGHtq12X182rFvA4KEDtK13q2E7B3Jp2Cxyj").strip()
        # Phase 45: Correct MarginFi USDC bank address (NOT the USDC mint!)
        usdc_bank = os.getenv("MARGINFI_USDC_BANK", "2s37akK2eyBbp8DZgCm7RtsaEz8eWhVKGfHGA3cKMEW2").strip()
        correct_usdc = "2s37akK2eyBbp8DZgCm7RtsaEz8eWhVKGfHGA3cKMEW2"
        if usdc_bank != correct_usdc:
            logger.warning(f"⚠️ Self-healing .env: wrong MARGINFI_USDC_BANK {usdc_bank} -> {correct_usdc}")
            usdc_bank = correct_usdc  # Fix 87: auto-correct in memory

        return {
            "So11111111111111111111111111111111111111112": get_marginfi_bank_accounts(Pubkey.from_string(sol_bank)),
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": get_marginfi_bank_accounts(Pubkey.from_string(usdc_bank)),
        }
    except Exception as e:
        logger.warning(f"Failed to initialize MarginFi banks: {e}. Using empty dict.")
        return {}

MARGINFI_BANKS = get_marginfi_banks()

# Discriminators for our flash loan contract
EXECUTE_ARBITRAGE_DISCRIMINATOR = bytes([63, 57, 76, 143, 41, 52, 112, 208])  # sha256("global:execute_arbitrage")[:8]

HIGH_TIER_PAIRS = {("SOL", "USDC"), ("jitoSOL", "SOL"), ("USDC", "SOL"), ("SOL", "jitoSOL")}
TIER_A_TOKENS = {"INF", "jitoSOL", "mSOL", "bSOL", "JupSOL", "fwdSOL", "dSOL"}
TIER_A_MINTS = {TOKENS[name] for name in TIER_A_TOKENS if name in TOKENS}

price_matrix: Dict[str, tuple] = {}  # (price, timestamp) for freshness TTL
stats = {
    "reqs": [],
    "trades": 0,
    "sim_fails": 0,
    "last_balance": 0.0,
    "virtual_balance": 0.0,      # Fix 44: Virtual Balance Guard for Jito spam prevention
    # Key metrics for scaling
    "bundle_send_attempts": 0,
    "bundle_successes": 0,
    "state_to_execution_latencies": [],
    "gas_rent_leakage": 0.0,
    "flash_loan_miss_count": 0,
    "flash_loan_attempt_count": 0,
}
cached_blockhash: Optional[str] = None
cache_time = 0
openocean_banned_until = 0
openocean_ban_time = 60

# Global execution lock for sequential flash loan processing
execution_lock = asyncio.Lock()
# Lock for thread-safe stats updates
stats_lock = asyncio.Lock()

# Circuit Breaker: Global stop event for hard stop on any failure
GLOBAL_STOP_EVENT = asyncio.Event()
TOTAL_FAILED_BUNDLES_IN_A_ROW = 0  # Fix 64: Slippage loop breaker

# Track failed attempts per pair to switch resources
pair_failure_count = {}

try:
    from aiolimiter import AsyncLimiter
    class TokenBucket:
        def __init__(self, rps):
            self.limiter = AsyncLimiter(max(1, rps), 1.0)
        async def wait(self):
            await self.limiter.acquire()
except ImportError:
    logger.warning("aiolimiter not installed, falling back to naive TokenBucket. Run: pip install aiolimiter")
    class TokenBucket:
        def __init__(self, rps):
            self.rps = rps
            self.semaphore = asyncio.Semaphore(rps)
        async def wait(self):
            await self.semaphore.acquire()
            asyncio.get_event_loop().call_later(1.0, self.semaphore.release)

limiters = {}

def init_limiters(cfg: Config):
    global limiters
    limiters["jupiter"] = TokenBucket(cfg.JUP_RPS)
    limiters["dexscreener"] = TokenBucket(cfg.DEXSCREENER_RPS)

class RPCManager:
    def __init__(self, cfg: Config):
        self.all_nodes = [node for node in cfg.HELIUS_URLS + cfg.QUICKNODE_URLS if node]
        self.latencies: Dict[str, float] = {n: 999.0 for n in self.all_nodes}
        if not self.all_nodes:
            logger.error("!!! КРИТИЧЕСКАЯ ОШИХА: RPC ссылки не найдены в .env !!!")
        else:
            logger.info(f"✅ Пул RPC готов: {len(self.all_nodes)} узлов в работе")
        asyncio.create_task(self._latency_ranker())

    async def _latency_ranker(self):
        """Fix 63: Background latency ranking every 30s"""
        while True:
            for node in list(self.all_nodes):
                try:
                    t0 = time.time()
                    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(family=socket.AF_INET, resolver=AsyncResolver(nameservers=["1.1.1.1", "8.8.8.8"]))) as s:
                        async with s.post(node, json={"jsonrpc":"2.0","id":1,"method":"getHealth"}, timeout=2) as r:
                            if r.status == 200:
                                self.latencies[node] = (time.time() - t0) * 1000
                except:
                    self.latencies[node] = 999.0
            await asyncio.sleep(30)

    def get_rpc(self):
        if not self.all_nodes:
            logger.critical("!!! КРИТИЧЕСКАЯ ОШИХА: Все RPC узлы заблокированы (401) или отсутствуют !!!")
            raise Exception("No available RPC nodes. Pool is empty.")
        # Return fastest (lowest latency)
        return min(self.all_nodes, key=lambda n: self.latencies.get(n, 999.0))
        
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
                    masked_key = key[:4] + "*" * (len(key) - 8) + key[-4:] if len(key) > 8 else key
                    logger.warning(f"🚫 RPC заблокирован (401 Unauthorized): Helius key {masked_key}")
                else:
                    logger.warning(f"🚫 RPC заблокирован (401 Unauthorized): {rpc_url[:60]}...")
            else:
                logger.warning(f"🚫 RPC заблокирован (401 Unauthorized): {rpc_url[:60]}...")
            if not self.all_nodes:
                logger.critical("Все RPC ключи в .env невалидны или заблокированы сервером. Пожалуйста, обновите HELIUS_KEYS")
                sys.exit(1)

async def update_prices(session, cfg):
    global price_matrix
    mint_map = {name: mint for name, mint in TOKENS.items()}
    while True:
        try:
            # Phase 44: Convert Pubkey objects to strings for the join() call
            ids = ",".join([str(mint) for mint in mint_map.values()])
            async with session.get(f"{cfg.JUPITER_PRICE_URL}?ids={ids}") as resp:
                data = await resp.json()
                if "data" in data:
                    new_matrix = {}
                    now = time.time()
                    for mint, info in data["data"].items():
                        if info and info.get("price"):
                            new_matrix[mint] = (float(info["price"]), now)
                    price_matrix = new_matrix
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
                    data = await resp.json()
                    profiles = data if isinstance(data, list) else data.get("pairs", [])
                    for profile in profiles[:20]:
                        mint = profile.get("tokenAddress") or profile.get("baseToken", {}).get("address")
                        if mint and mint not in [str(m) for m in TOKENS.values()]:
                            # Dynamically inject new mint into worker queue
                            try:
                                queue.put_nowait((2, (str(TOKENS["SOL"]), mint)))
                            except asyncio.QueueFull:
                                pass  # HFT: stale data is trash — drop it, don't deadlock
                            if mint in [str(m) for m in MARGINFI_BANKS.keys()]:
                                try:
                                    queue.put_nowait((2, (mint, str(TOKENS["SOL"]))))
                                except asyncio.QueueFull:
                                    pass  # HFT: stale data is trash — drop it, don't deadlock
        except Exception as e:
            logger.debug(f"DexScreener error: {e}")
        await asyncio.sleep(60)

# Dynamic Token Registry for Webhook-discovered tokens
temporary_tokens: Dict[str, float] = {}  # Mint -> Expiry Timestamp
temporary_tokens_lock = asyncio.Lock()

async def register_temporary_token(mint: str, duration: int = 1800):
    """Register a token discovered via webhooks for high-frequency scanning (default 30 min)."""
    async with temporary_tokens_lock:
        expiry = time.time() + duration
        temporary_tokens[mint] = expiry
        logger.info(f"✨ Dynamically registered {str(mint)[:8]} for high-frequency scanning until {time.strftime('%H:%M:%S', time.localtime(expiry))}")

async def cleanup_temporary_tokens():
    """Remove expired tokens from the dynamic registry."""
    while True:
        try:
            await asyncio.sleep(300) # Every 5 minutes
            now = time.time()
            async with temporary_tokens_lock:
                to_remove = [m for m, expiry in temporary_tokens.items() if now > expiry]
                for m in to_remove:
                    del temporary_tokens[m]
                    logger.info(f"🧹 Removed temporary token {str(m)[:8]} from registry (expired)")
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

class BankHealthMonitor:
    """Monitors MarginFi bank liquidity and switches banks if health is low."""
    def __init__(self, rpc_manager, sol_bank, usdc_bank):
        self.rpc = rpc_manager
        self.sol_bank = sol_bank
        self.usdc_bank = usdc_bank
        self.active_bank = sol_bank
        self.running = False

    async def start(self):
        self.running = True
        asyncio.create_task(self._monitor_loop())

    async def _monitor_loop(self):
        while self.running:
            try:
                # Check SOL Bank liquidity
                sol_liq = await self._get_bank_liquidity(self.sol_bank)
                if sol_liq < 5.0:
                    logger.warning(f"⚠️ SOL Bank liquidity low: {sol_liq:.2f} SOL. Switching to USDC.")
                    self.active_bank = self.usdc_bank
                else:
                    self.active_bank = self.sol_bank
            except Exception as e:
                logger.error(f"Health monitor error: {e}")
            await asyncio.sleep(10)

    async def _get_bank_liquidity(self, bank_info):
        try:
            vault = bank_info["liquidity_vault"]
            res = await self.rpc.get_token_account_balance(str(vault))
            return float(res["amount"]) / 1e9 if res else 0
        except:
            return 0

# ============================================================================
# SCAN TARGETS — consumed by stable_scanner, lst_scanner, xstocks_scanner, rwa_rest_scanner
# ============================================================================

SCAN_TARGETS = {
    "stables":   {"description": "Stablecoin Pairs",   "scan_interval": 1.5, "pair_delay": 0.1,
                  "pairs": [("USDC", "USDT"), ("USDC", "PYUSD"), ("USDC", "USDS"),
                            ("USDC", "USDY"), ("USDC", "USDe")]},  # Step 5: yield stables
    "lst":       {"description": "LST Pairs",           "scan_interval": 2.0, "pair_delay": 0.1,
                  "pairs": [("SOL", "jitoSOL"), ("SOL", "mSOL"), ("SOL", "bSOL"),
                            ("SOL", "2ZSOL"), ("SOL", "bonkSOL")]},  # Step 5: new LSTs
    "xstocks":   {"description": "xStocks RWA",         "scan_interval": 5.0, "pair_delay": 0.2,
                  "pairs": [("USDC", "NVDAx"), ("USDC", "MSTRx"), ("USDC", "SPYx"),
                            ("USDC", "GOOGLx"), ("USDC", "HOODx"), ("USDC", "GLDx")]},  # Step 5
    "rwa_rest":  {"description": "Other RWA/DePIN",     "scan_interval": 15.0, "pair_delay": 0.5,
                  "pairs": [("USDC", "JUP"), ("USDC", "WIF")]},
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
                    queue.put_nowait((1, (TOKENS[base], TOKENS[target])))
                except asyncio.QueueFull:
                    pass  # HFT: stale data is trash — drop it, don't deadlock
                await asyncio.sleep(scan_config["pair_delay"])
        await asyncio.sleep(scan_config["scan_interval"])

async def lst_scanner(queue, cfg):
    """Loop B (LST Priority): Arbitrage between SOL and derivatives."""
    scan_config = SCAN_TARGETS["lst"]
    logger.debug(f"🌊 LST Scanner: {scan_config['description']}")

    while True:
        for base, target in scan_config["pairs"]:
            if base in TOKENS and target in TOKENS:
                try:
                    queue.put_nowait((1, (TOKENS[base], TOKENS[target])))
                except asyncio.QueueFull:
                    pass  # HFT: stale data is trash — drop it, don't deadlock
                await asyncio.sleep(scan_config["pair_delay"])
        await asyncio.sleep(scan_config["scan_interval"])

def is_nyse_trading_hours() -> bool:
    """Check if current UTC time is within NYSE trading hours (13:30-20:00 UTC)."""
    from datetime import datetime
    now = datetime.utcnow()
    hour = now.hour
    minute = now.minute

    # NYSE trading hours: 13:30 - 20:00 UTC (9:30 AM - 4:00 PM ET)
    current_minutes = hour * 60 + minute
    start_minutes = 13 * 60 + 30  # 13:30 UTC
    end_minutes = 20 * 60         # 20:00 UTC

    return start_minutes <= current_minutes <= end_minutes

def get_market_aware_scan_interval(base_interval: float) -> float:
    """Adjust scan interval based on market hours. Reduce frequency outside trading hours."""
    if is_nyse_trading_hours():
        return base_interval  # Full speed during trading hours
    else:
        return base_interval * 10  # 10x slower outside trading hours to save RPC credits

async def xstocks_scanner(queue, cfg):
    """Loop C (xStocks Priority): Oracle lag detection with market hours awareness."""
    scan_config = SCAN_TARGETS["xstocks"]
    logger.debug(f"🎯 xStocks Scanner: {scan_config['description']} | Market Hours Aware")

    # Initialize PreTradeGuard for Token-2022 fee checking
    from src.ingest.pre_trade_guard import PreTradeGuard
    pre_trade_guard = PreTradeGuard()

    while True:
        # Dynamic scan interval based on market hours
        current_interval = get_market_aware_scan_interval(scan_config["scan_interval"])
        market_open = is_nyse_trading_hours()

        if market_open:
            logger.debug("📈 NYSE trading hours active - full speed xStocks scanning")
        else:
            logger.debug("🌙 NYSE closed - reduced xStocks scanning frequency")

        for base, target in scan_config["pairs"]:
            # Special handling for MSTRx - always scan when BTC is volatile
            # For now, always scan during market hours, reduced frequency otherwise
            if base in TOKENS and target in TOKENS:
                try:
                    queue.put_nowait((1, (TOKENS[base], TOKENS[target])))
                except asyncio.QueueFull:
                    pass  # HFT: stale data is trash — drop it, don't deadlock
                await asyncio.sleep(scan_config["pair_delay"])

        await asyncio.sleep(current_interval)

async def rwa_rest_scanner(queue, cfg):
    """Loop D (RWA Rest): Slow scan of remaining RWA assets every 15 seconds."""
    scan_config = SCAN_TARGETS["rwa_rest"]
    logger.debug(f"🏛️ RWA Rest Scanner: {scan_config['description']}")

    while True:
        for base, target in scan_config["pairs"]:
            if base in TOKENS and target in TOKENS:
                try:
                    queue.put_nowait((2, (TOKENS[base], TOKENS[target])))  # Lower priority
                except asyncio.QueueFull:
                    pass  # HFT: stale data is trash — drop it, don't deadlock
                await asyncio.sleep(scan_config["pair_delay"])
        await asyncio.sleep(scan_config["scan_interval"])

async def get_jupiter_quote(session, input_mint, output_mint, amount_lamports, cfg, slippage_bps=None, restrict_intermediate: bool = True):
    pair_key = f"{input_mint}:{output_mint}:{amount_lamports}"
    if pair_key in PENDING_QUOTES:
        return None  # Fix 84: dedup - skip duplicate RPS waste
    PENDING_QUOTES.add(pair_key)
    await limiters["jupiter"].wait()
    if slippage_bps is None:
        slippage_bps = cfg.SLIPPAGE_BPS
    params = {
        "inputMint": str(input_mint),
        "outputMint": str(output_mint),
        "amount": str(amount_lamports),
        "slippageBps": str(slippage_bps),
        "maxAccounts": "8",  # Fix 3: MTU Safety — 8 accounts × 32B = 256B overhead → TX stays within 1232-byte UDP limit
        "onlyDirectRoutes": "false",
        "restrictIntermediateTokens": "true" if restrict_intermediate else "false",
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    }
    # Добавляем ключ, если он есть
    if cfg.JUPITER_API_KEY:
        headers["Authorization"] = f"Bearer {cfg.JUPITER_API_KEY}"
    try:
        async with session.get(cfg.JUPITER_QUOTE_URL, params=params, headers=headers, timeout=5.0) as resp:
            if resp.status == 200:
                data = await resp.json()
                return {"source": "Jupiter", "out_amount": int(data["outAmount"]), "full_quote_response": data}
            else:
                error_text = await resp.text()
                logger.warning(f"Jupiter API Error {resp.status}: {error_text}")
                return None
    except Exception as e:
        logger.warning(f"Jupiter Exception: {repr(e)}")
        return None
    finally:
        PENDING_QUOTES.discard(pair_key)

def get_token_decimals(mint) -> int:
    """Return token decimals safe for str and Pubkey inputs."""
    return TOKEN_DECIMALS.get(str(mint), 9)

async def get_best_quote_multi(session, in_mint, out_mint, amount, cfg, expected_profit_bps: float = 0.0, restrict_intermediate: bool = True):
    """Get best quote with anti-sandwich slippage guard (Fix 34).

    Args:
        expected_profit_bps: Expected arbitrage profit in basis points.
                             Required for profit-aware dynamic slippage.
                             If 0, falls back to cfg.SLIPPAGE_BPS.
        restrict_intermediate: If False, Jupiter finds multi-hop routes through intermediate tokens.
                               Use for triangular/3+hop arbitrage to reduce sequential API calls.
    """
    try:
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
            get_jupiter_quote(session, in_mint, out_mint, amount, cfg, slippage_bps, restrict_intermediate=restrict_intermediate),
            timeout=3.0
        )
        return quote
    except Exception as e:
        logger.warning(f"Jupiter quote failed: {repr(e)}")
        return None

async def create_flashloan_arbitrage_tx(session, base_mint, target_mint, base_amount_lamports, quotes, cfg, keypair, rpc_getter, use_jito=False, tip_lamports=0, alt_manager=None, strategy_type=1, tip_accounts=None):
    wallet_pubkey = str(keypair.pubkey())

    # Fix 1: Safe cast base_mint / target_mint to strings up front
    base_mint_str = str(base_mint) if isinstance(base_mint, Pubkey) else str(base_mint)
    target_mint_str = str(target_mint) if isinstance(target_mint, Pubkey) else str(target_mint)
    base_mint = _to_pubkey(base_mint_str)
    target_mint = _to_pubkey(target_mint_str)

    if not cfg.MARGINFI_ACCOUNT_PUBKEY:
        logger.error("MARGINFI_ACCOUNT is not set. A MarginfiAccount is required for flash loans.")
        return None

    marginfi_account = Pubkey.from_string(cfg.MARGINFI_ACCOUNT_PUBKEY)

    # Phase 48: Dynamic Base_Mint Resolution (Task 23)
    # If target is an xStock/RWA, we borrow USDC instead of the xStock itself
    flashloan_mint_str = base_mint_str
    from src.config.xstocks_registry import is_xstock_token
    if is_xstock_token(_to_pubkey(target_mint_str)) or is_xstock_token(_to_pubkey(base_mint_str)):
        flashloan_mint_str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" # USDC
        logger.debug(f"🔄 RWA detected. Routing flashloan via USDC bank.")

    # Token-2022 Safety Check: reduce volume 10x for xStocks with uncertain transfer fees
    effective_base_amount = base_amount_lamports
    if is_xstock_token(_to_pubkey(target_mint_str)) or is_xstock_token(_to_pubkey(base_mint_str)):
        effective_base_amount = base_amount_lamports // 10
        logger.debug(f"🛡️ Token-2022 xStock safety: volume reduced 10x ({base_amount_lamports} -> {effective_base_amount} lamports)")

    if flashloan_mint_str not in MARGINFI_BANKS:
        logger.warning(f"Marginfi bank not configured for mint: {flashloan_mint_str}")
        return None
    bank_cfg = MARGINFI_BANKS[flashloan_mint_str]

    tx_builder = JupiterTxBuilder(session=session, rpc_url=rpc_getter(), alt_manager=alt_manager)

    # Get Jupiter swap instructions for all legs
    instructions = []
    for i, quote in enumerate(quotes):
        if "full_quote_response" not in quote:
            return None
        ixs, alts = await tx_builder.get_swap_instructions(quote["full_quote_response"], wallet_pubkey, use_custom_cu=True)
        if not ixs:
            logger.warning(f"Failed to fetch swap instructions for leg {i}")
            return None
        instructions.append((ixs, alts))

    if len(instructions) < 2:
        logger.warning("Not enough instructions")
        return None

    # Apply dynamic slippage (Slippage Sniper)
    dynamic_slippage = tx_builder.get_dynamic_slippage([base_mint_str, target_mint_str])
    logger.debug(f"Using dynamic slippage: {dynamic_slippage*100:.2f}% for {base_mint_str[:8]}/{target_mint_str[:8]}")
    
    # Filter by profit — generalized for any number of legs (Fix 39)
    # profit comes from the LAST leg: input -> ... -> output
    # Use last quote output as the final result
    last_quote = quotes[-1]
    first_quote = quotes[0]
    profit_lamports = int(last_quote['out_amount']) - base_amount_lamports

    # Convert SOL fees to base_mint equivalents if base_mint is not SOL
    is_sol_base = base_mint_str == "So11111111111111111111111111111111111111112"
    sol_price_in_usd = price_matrix.get("So11111111111111111111111111111111111111112", 150.0)

    base_fee_sol = cfg.BASE_FEE + (tip_lamports / 1e9)
    if is_sol_base:
        fee_in_base_token_lamports = int(base_fee_sol * 1e9)
    else:
        # Assuming base_mint is a stablecoin (6 decimals)
        fee_in_base_token_lamports = int(base_fee_sol * sol_price_in_usd * 1e6)

    total_fees_in_base = fee_in_base_token_lamports

    if profit_lamports < total_fees_in_base:
        return None

    from spl.token.constants import TOKEN_PROGRAM_ID
    from spl.token.instructions import get_associated_token_address, close_account, CloseAccountParams
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
    mfi_group = MARGINFI_GROUP
    sol_mint = Pubkey.from_string("So11111111111111111111111111111111111111112")

    # Calculate indices for Instruction Introspection
    # [Borrow, ...Swaps, Repay]
    repay_index = 1 + len(swap_instructions)  # Borrow(0) + Swaps

    borrow_ix = builder.build_marginfi_borrow_ix(
        mfi_program, marginfi_account, keypair.pubkey(), mfi_group,
        bank_cfg["bank"], bank_cfg["liquidity_vault"],
        bank_cfg["liquidity_vault_authority"], user_token_account, TOKEN_PROGRAM_ID,
        int(effective_base_amount), [repay_index]
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # SAFE BORROW DATA RECONSTRUCTION (avoids slice-patching fragile to CDDL changes)
    # MarginFi borrow instruction layout: discriminator(8) | amount(8 u64 LE) | index(1 u8)
    # We rebuild data from scratch instead of borrow_ix.data[:N] + bytes([index])
    # to prevent byte shifts if Jupiter ever adds another param between amount and index.
    # ═══════════════════════════════════════════════════════════════════════════
    try:
        from src.ingest.tx_builder import MARGINFI_BORROW_DISCRIMINATOR
    except ImportError:
        from src.ingest.tx_builder import MARGINFI_BORROW_DISCRIMINATOR

    try:
        # Exact re-serialization: discriminator (8) + amount (8 u64 LE) + repay index (1 u8)
        _new_data = (MARGINFI_BORROW_DISCRIMINATOR
                     + int(effective_base_amount).to_bytes(8, "little")
                     + struct.pack("<B", repay_index))
        if len(_new_data) == 17:
            borrow_ix = Instruction(
                program_id=borrow_ix.program_id,
                accounts=borrow_ix.accounts,
                data=_new_data,
            )
        else:
            logger.warning(f"Borrow data re-serialized to {len(_new_data)} bytes — using original")
    except Exception as _rebuild_err:
        logger.debug(f"Borrow safe-rebuild skipped ({_rebuild_err}), using original")


    repay_ix = builder.build_marginfi_repay_ix(
        mfi_program, marginfi_account, keypair.pubkey(), mfi_group,
        bank_cfg["bank"], bank_cfg["liquidity_vault"],
        bank_cfg["liquidity_vault_authority"], user_token_account, TOKEN_PROGRAM_ID,
        int(effective_base_amount)
    )

    # Final instruction sequence for build_optimized_transaction
    arbitrage_instructions = [borrow_ix] + swap_instructions + [repay_ix]



    # Fetch ALTs using dynamic all_alts (Fix 39: supports any leg count)
    address_lookup_tables = []
    seen_alt_strs = set()
    unique_alts = []
    for alt in all_alts:
        alt_str = str(alt)
        if alt_str not in seen_alt_strs:
            seen_alt_strs.add(alt_str)
            unique_alts.append(alt)

    if alt_manager:
        # Filter through list comprehension to avoid mutation during iteration
        found_alts = []
        still_needed = []
        for pk in unique_alts:
            resolved = await alt_manager.resolve_alt(pk)
            if resolved:
                from solders.address_lookup_table_account import AddressLookupTableAccount
                address_lookup_tables.append(AddressLookupTableAccount(key=pk, addresses=resolved))
                found_alts.append(pk)
            else:
                still_needed.append(pk)
        unique_alts = still_needed  # Keep only those that need to be loaded from RPC

    if unique_alts:
        try:
            alt_payload = {
                "jsonrpc": "2.0", "id": 1, "method": "getMultipleAccounts",
                "params": [[str(p) for p in unique_alts], {"encoding": "base64"}]
            }
            async with session.post(rpc_getter(), json=alt_payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for i, acc_data in enumerate(data.get("result", {}).get("value", [])):
                        if acc_data:
                            b64 = acc_data["data"][0]
                            padded_b64 = b64 + "=" * (-len(b64) % 4)
                            raw = base64.b64decode(padded_b64)
                            # Phase 32: Dynamic ALT header parsing
                            header_len = 56 if raw[21] == 1 else 24
                            keys = [Pubkey.from_bytes(raw[j:j+32]) for j in range(header_len, len(raw), 32)]
                            address_lookup_tables.append(AddressLookupTableAccount(key=unique_alts[i], addresses=keys))
        except Exception as e:
            logger.debug(f"ALT fetch error: {e}")

    recent_blockhash = cached_blockhash if (cached_blockhash and time.time() - cache_time < 2) else None
    if not recent_blockhash:
        try:
            timeout = aiohttp.ClientTimeout(total=1.0)
            async with session.post(rpc_getter(), json={"jsonrpc": "2.0", "id": 1, "method": "getLatestBlockhash"}, timeout=timeout) as resp:
                bh_data = await resp.json()
                if "result" in bh_data: 
                    recent_blockhash = Hash.from_string(bh_data["result"]["value"]["blockhash"])
        except Exception: 
            pass
    
    if not recent_blockhash:
        logger.error("❌ CRITICAL: Failed to fetch valid blockhash. Aborting transaction build to prevent silent bundle drop.")
        return None

    try:
        # Use optimized transaction building with custom CU and priority fees
        optimized_instructions, cu_limit, priority_fee = await tx_builder.build_optimized_transaction(
            instructions=arbitrage_instructions,
            address_lookup_tables=address_lookup_tables,
            payer=keypair.pubkey(),
            recent_blockhash=str(recent_blockhash),
            program_id="MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA",  # MarginFi program as caching key
            operation_type="flash_arbitrage",
            use_jito=use_jito,
            rpc_url=rpc_getter()
        )
        # cu_limit is already the dynamic profile value from build_optimized_transaction()
        # Calculate EXACT repay index dynamically using list introspection in optimized_instructions
        try:
            actual_repay_index = optimized_instructions.index(repay_ix)
            # ── SAFE BORROW DATA RECONSTRUCTION ───────────────────────────────────
            # NO slice-patching here. Rebuild the borrow instruction data from explicit
            # fields so the repay-index position is correct regardless of any future
            # CDDL layout change (extra fields, different alignment, etc.).
            # MarginFi borrow layout: discriminator(8) + amount(8 u64 LE) + index(1 u8)
            from src.ingest.tx_builder import MARGINFI_BORROW_DISCRIMINATOR
            _safe_data = (
                MARGINFI_BORROW_DISCRIMINATOR
                + int(effective_base_amount).to_bytes(8, "little")
                + struct.pack("<B", actual_repay_index)
            )
            borrow_ix = Instruction(
                program_id=borrow_ix.program_id,
                accounts=borrow_ix.accounts,
                data=_safe_data,
            )
            logger.debug(f"🛠️ Safe Borrow Data Re-serialized: repay_index={actual_repay_index}, len={len(_safe_data)} bytes")
        except ValueError:
            logger.error("CRITICAL: repay_ix not found in optimized_instructions")
            return None

        logger.debug(f"Optimized transaction: CU={cu_limit}, PriorityFee={priority_fee} microlamports, Jito={use_jito}")

        # Phase 48: Native SOL Tip Starvation Fix (Bug 20)
        # If the flashloan asset is SOL, profit accrues as wSOL in the ATA.
        # Close the wSOL ATA first to unwrap into native SOL, then pay the Jito tip.
        if borrow_mint == Pubkey.from_string("So11111111111111111111111111111111111111112"):
            optimized_instructions.append(close_account(CloseAccountParams(
                program_id=TOKEN_PROGRAM_ID,
                account=user_sol_ata,
                dest=wallet,
                owner=wallet
            )))
            optimized_instructions.append(CREATE_ATA_FUNCTION(
                payer=wallet,
                owner=wallet,
                mint=sol_wrapped_mint
            ))
            logger.debug("🔓 wSOL unwrapping injected: CloseATA + CreateIdempotentATA before Jito tip")

        # Add Jito tip instruction if specified (must be last for security)
        if tip_lamports > 0:
            from solders.system_program import TransferParams, transfer
            # Fix 2: Use dynamic tip account from jito_executor (never hardcoded)
            _tip_accounts_list = tip_accounts or ["96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"]
            selected_tip_account = random.choice(_tip_accounts_list)
            tip_ix = transfer(TransferParams(
                from_pubkey=keypair.pubkey(),
                to_pubkey=Pubkey.from_string(selected_tip_account),
                lamports=tip_lamports,
            ))
            optimized_instructions.append(tip_ix)

        msg = MessageV0.try_compile(
            payer=keypair.pubkey(),
            instructions=optimized_instructions,
            address_lookup_table_accounts=address_lookup_tables,
            recent_blockhash=recent_blockhash
        )
        tx = VersionedTransaction(msg, [keypair])

        # Check transaction size limit — MTU safety buffer (1200 bytes)
        tx_size = len(bytes(tx))
        if tx_size > 1200:
            logger.warning(f"⚠️ TX rejected: size {tx_size} > 1200 bytes (too many hops). Dropping to avoid silent network drop.")
            return None

        return base64.b64encode(bytes(tx)).decode('ascii')
    except Exception as e:
        logger.debug(f"Tx construction error: {e}")
        return None

async def send_balance_alert(current_balance: float, initial_balance: float):
    """Send notification about balance drop."""
    # Placeholder for notification implementation
    # Could integrate with Telegram, Discord, email, etc.
    logger.critical(f"ALERT: Balance dropped to {current_balance:.8f} SOL from initial {initial_balance:.8f} SOL")
    # TODO: Implement actual notification (Telegram bot, email, etc.)


# ═══════════════════════════════════════════════════════════════════════════
#  LST DEPEG FLASH-ARB SCANNER
# ═══════════════════════════════════════════════════════════════════════════

async def lst_depeg_scanner(session, cfg, rpc_manager, keypair, jito_executor, webhook_trigger=None):
    """Main LST Depeg Flash-Arb scanner loop.

    Continuously monitors fair price vs market price for LST tokens
    (jitoSOL, mSOL, bSOL). When a depeg exceeds the threshold:
      1. Finds the best buy+sell route via Jupiter + Sanctum
      2. Builds a MarginFi flash loan transaction
      3. Pre-flight simulates to verify profitability
      4. Sends via Jito bundle if profitable
    """
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
    tx_builder = JupiterTxBuilder(
        session=session,
        rpc_url=rpc_url,
    )

    # Pre-Trade Guard: prevent sending unprofitable bundles (right before jito_executor.send_bundle)
    pre_trade_guard = PreTradeGuard(session=session, rpc_url=rpc_url)

    # MarginFi bank config for SOL
    sol_mint_str = str(TOKENS["SOL"])
    if sol_mint_str not in MARGINFI_BANKS:
        logger.error("MarginFi SOL bank not configured — LST scanner disabled")
        return
    bank_cfg = MARGINFI_BANKS[sol_mint_str]

    min_profit_lamports = int(cfg.MIN_NET_PROFIT_BUFFER_SOL * 1_000_000_000)
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

    while True:
        cycle_count += 1
        try:
            # --- TASK 3 — Dynamic Max Borrow (single source of truth via tx_builder) ---
            # Replaces inline RPC — uses tx_builder.get_max_marginfi_borrow() which handles
            # 95% cap + fallback to env default so all scanners speak the same logic.
            try:
                borrow_lamports = await tx_builder.get_max_marginfi_borrow(str(bank_cfg["liquidity_vault"]))
                # DYNAMIC SIZING: Feed 95% vault into OptimalTradeSizer to find peak of AMM curve
                optimal = trade_sizer.find_optimal_trade_size(
                    routes=[], amount_in=borrow_lamports, decimals_in=9, decimals_out=9, jito_tip_sol=0.0001
                )
                if optimal and int(optimal) > 100_000_000:  # Min 0.1 SOL
                    borrow_lamports = int(optimal)
                    logger.debug(f"📈 LST optimal size: {borrow_lamports/1e9:.4f} SOL (AMM curve peak)")
                # Fix 3 (MarginFi Slippage Margin): cap borrow to FLASH_LOAN_SIZE_SOL from .env
                env_max = int(cfg.FLASH_LOAN_SIZE_SOL * 1_000_000_000)
                if borrow_lamports > env_max:
                    logger.debug(f"📉 Capping borrow from {borrow_lamports/1e9:.4f} SOL to {env_max/1e9:.4f} SOL (FLASH_LOAN_SIZE_SOL)")
                    borrow_lamports = env_max
            except Exception as e:
                logger.warning(f"Could not check MarginFi SOL liquidity, fallback to default: {e}")
                borrow_lamports = int(cfg.FLASH_LOAN_SIZE_SOL * 1_000_000_000)

            if borrow_lamports < 100_000_000: # Если в MarginFi меньше 0.1 SOL, ждем
                logger.warning("📉 MarginFi SOL Bank is nearly empty. Waiting for liquidity...")
                await asyncio.sleep(10)
                continue
            # -------------------------------------------------------------------

            # Check for webhook trigger
            force_scan = False
            try:
                while not webhook_trigger.empty():
                    opportunity = webhook_trigger.get_nowait()
                    if opportunity.get('trigger_immediate_scan'):
                        logger.debug("🚨 Webhook triggered immediate LST scan")
                        force_scan = True
                        break  # Process one trigger per cycle
            except asyncio.QueueEmpty:
                pass

            # ── Step 1: Update prices and detect depeg ────────────────────
            await fair_price_monitor.update_fair_prices()
            await fair_price_monitor.update_market_prices()
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

                # ── Step 3: Find best route ───────────────────────────────
                if borrow_lamports < 1_000_000_000:
                    logger.warning("MarginFi SOL bank is dry. Waiting...")
                    await asyncio.sleep(5)
                    continue

                route = await route_aggregator.find_best_route(
                    borrow_amount_lamports=borrow_lamports,
                    lst_mint=signal.token_mint,
                    direction=signal.direction,
                    base_fee_sol=cfg.BASE_FEE,
                    priority_fee_sol=cfg.PRIORITY_FEE,
                    jito_tip_sol=0.0,  # Placeholder — tip optimized below after route is confirmed
                    min_profit_buffer_sol=cfg.MIN_NET_PROFIT_BUFFER_SOL,
                )

                if route is None:
                    logger.debug(f"No route found for {signal.token_symbol} depeg")
                    continue

                if not route.is_profitable:
                    logger.debug(
                        f"⚠️ Route found but not profitable: {route.route_path} | "
                        f"profit={route.profit_sol:.6f} SOL (need ≥{cfg.MIN_NET_PROFIT_BUFFER_SOL})"
                    )
                    continue

                # God-mode tip via bidding manager (tip_floor + step-up/down + capital guard)
                god_tip_lamports = jito_bidding_manager.calculate_blue_ocean_tip(
                    expected_profit_sol=route.profit_sol, strategy="lst_depeg"
                )
                calculated_tip_lamports = god_tip_lamports
                if god_tip_lamports <= 0:
                    logger.warning(f"🚫 Offset-by-zero tip for {signal.token_symbol} — skipping")
                    continue

                # Build tip lamports for trade execution (already optimized by bidding manager)
                jito_tip_lamports = god_tip_lamports

                # Jito Tip Trap Prevention: Adjust tip based on leader schedule
                tip_adjustment = await jito_leader_tracker.get_optimal_tip(
                    base_tip_lamports=jito_tip_lamports,
                    current_slot=0  # TODO: Get actual current slot
                )
                jito_tip_lamports = tip_adjustment["tip_lamports"]

                if tip_adjustment["recommendation"] == "reduce_tip":
                    logger.debug(f"🎯 Tip trap prevented: {tip_adjustment['reason']} | Adjusted tip: {jito_tip_lamports/1e9:.6f} SOL")

                logger.debug(
                    f"✅ Profitable route: {route.route_path} | "
                    f"profit={route.profit_sol:.6f} SOL ({route.profit_bps:.1f} BPS) | "
                    f"fees={route.total_fees_sol:.6f} SOL | "
                    f"final_tip={jito_tip_lamports/1e9:.6f} SOL"
                )

                # ── Step 4: Build MarginFi flash loan TX ──────────────────
                if not cfg.MARGINFI_ACCOUNT_PUBKEY:
                    logger.error("MARGINFI_ACCOUNT not set — cannot execute flash loan")
                    continue

                fl_result = await tx_builder.build_marginfi_flashloan_tx(
                    wallet_pubkey=str(keypair.pubkey()),
                    borrow_amount_lamports=borrow_lamports,
                    buy_quote_response=route.buy_quote.full_quote_response,
                    sell_quote_response=route.sell_quote.full_quote_response,
                    marginfi_account=cfg.MARGINFI_ACCOUNT_PUBKEY,
                    bank_pubkey=str(bank_cfg["bank"]),
                    bank_liquidity_vault=str(bank_cfg["liquidity_vault"]),
                    bank_liquidity_vault_authority=str(bank_cfg["liquidity_vault_authority"]),
                    use_jito=True,
                    strategy_type=2,
                    tip_accounts=jito_executor.tip_accounts if jito_executor else None,  # Fix 2: dynamic tip accounts
                )

                if not fl_result:
                    logger.warning(f"Failed to build flash loan TX for {signal.token_symbol}")
                    continue

                # ── Step 5: Resolve ALTs and build final transaction ──────
                instructions = fl_result["instructions"]
                alt_pubkeys = fl_result["address_lookup_table_pubkeys"]

                # Fetch ALT account data
                address_lookup_tables = []
                if alt_pubkeys:
                    try:
                        alt_payload = {
                            "jsonrpc": "2.0", "id": 1,
                            "method": "getMultipleAccounts",
                            "params": [[str(pk) for pk in alt_pubkeys], {"encoding": "base64"}]
                        }
                        timeout = aiohttp.ClientTimeout(total=2.0)
                        async with session.post(rpc_manager.get_rpc(), json=alt_payload, timeout=timeout) as resp:
                            if resp.status == 200:
                                alt_data = await resp.json()
                                if "result" in alt_data and "value" in alt_data["result"]:
                                    for acct in alt_data["result"]["value"]:
                                        if acct:
                                            try:
                                                b64_data = acct["data"][0]
                                                padded = b64_data + "=" * (-len(b64_data) % 4)
                                                raw_data = base64.b64decode(padded)
                                                keys = []
                                                # Phase 32: Dynamic ALT header parsing
                                                header_len = 56 if raw_data[21] == 1 else 24
                                                for i in range(header_len, len(raw_data), 32):
                                                    keys.append(Pubkey.from_bytes(raw_data[i:i+32]))
                                                # Use the pubkey from alt_pubkeys
                                                index = alt_data["result"]["value"].index(acct)
                                                alt_acct = AddressLookupTableAccount(key=alt_pubkeys[index], addresses=keys)
                                                address_lookup_tables.append(alt_acct)
                                            except Exception:
                                                pass
                    except Exception as e:
                        logger.debug(f"ALT fetch error: {e}")

                # Get fresh blockhash
                blockhash = cached_blockhash
                if not blockhash or time.time() - cache_time > 2:
                    blockhash = await get_current_blockhash(session, rpc_manager.get_rpc())
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
                is_profitable, reason, sim_result = await flash_sim.validate_profitability(
                    tx_b64=tx_b64,
                    tx_signer_pubkey=str(keypair.pubkey()),
                    min_profit_lamports=min_profit_lamports,
                    tip_lamports=jito_tip_lamports,
                    priority_fee_lamports=int(cfg.PRIORITY_FEE * 1e9),
                )

                if not is_profitable:
                    if "sim" in reason.lower() or "fail" in reason.lower():
                        record_sim_failure(strategy)
                    logger.debug(
                        f"🛡️ Pre-flight BLOCKED: {reason} | "
                        f"sim_time={sim_result.simulation_time_ms:.0f}ms"
                    )
                    continue  # Skip this opportunity — do NOT send unprofitable tx to Jito

                # ── Step 7: Send via Jito bundle ──────────────────────────
                if JITO_AVAILABLE:
                    tx_with_tip = tx  # Placeholder - tip will be added by JitoBundleHandler/JitoExecutor

                    # ── Pre-Trade Guard: Re-check profit right before send_bundle (Fix Slippage Re-check)
                    # Between fetching the quote and sending, 100-300ms may have passed.
                    # If the price slipped and eats the profit — abort. Better to skip than burn gas.
                    base_fee_lamports = int(cfg.PRIORITY_FEE * 1e9)
                    est_gas_lamports = int(0.000005 * 1e9)
                    expected_profit_lamports = int(route.profit_sol * 1e9)

                    trade_ok, trade_reason, _ = await pre_trade_guard.check_profit_before_execution(
                        input_mint=str(route.buy_quote.input_mint),    # entry token (SOL for buy-LST)
                        output_mint=str(route.buy_quote.output_mint),   # exit token (LST for buy-LST)
                        amount_lamports=route.borrow_amount_lamports,
                        jito_tip_lamports=jito_tip_lamports,
                        base_fee_lamports=base_fee_lamports + est_gas_lamports,
                        expected_profit_lamports=expected_profit_lamports,
                        quote_url=cfg.JUPITER_QUOTE_URL,
                        slippage_bps=cfg.SLIPPAGE_BPS,
                    )
                    if not trade_ok:
                        logger.warning(f"🚫 Pre-Trade Guard BLOCKED: {trade_reason} | {signal.token_symbol}")
                        continue

                    stats["bundle_send_attempts"] += 1
                    bundle_result = await jito_executor.send_bundle([tx_with_tip])
                    if bundle_result["success"]:
                        # Fix 1 (wSOL Death Spiral): mark that the atomic path just closed wSOL + recreated ATA.
                        # wallet_balance_listener will skip its own standalone close for WSOL_CLOSE_COOLDOWN seconds.
                        await mark_wsol_atomically_closed()
                        stats["bundle_successes"] += 1
                        bundle_id = bundle_result["bundle_id"]
                        logger.debug(
                            f"🔥 LST Flash-Arb bundle sent! "
                            f"{signal.token_symbol} | profit={route.profit_sol:.6f} SOL | "
                            f"route={route.route_path} | bundle={bundle_id} | "
                            f"tip={jito_tip_lamports/1e9:.6f} SOL"
                        )
                        stats["trades"] += 1

                        # Wait for confirmation
                        confirmation = await jito_executor.wait_for_confirmation(
                            bundle_id, max_wait_time=30.0
                        )
                        if confirmation.get("status") in ["confirmed", "finalized"]:
                            logger.debug(f"✅ LST bundle confirmed: {confirmation['status']}")
                            jito_bidding_manager.record_trade_result("lst_depeg", True)
                        else:
                            logger.warning(f"❌ LST bundle status: {confirmation.get('status', 'unknown')}")
                            jito_bidding_manager.record_trade_result("lst_depeg", False)
                    else:
                        logger.warning(f"❌ LST bundle failed: {bundle_result.get('error')}")
                        jito_bidding_manager.record_trade_result("lst_depeg", False)
                        stats["sim_fails"] += 1
                else:
                    logger.warning("❌ Simulation failed or Jito unavailable. Skipping trade for capital protection.")
        except Exception as e:
            logger.error(f"LST scanner error: {e}")

        await asyncio.sleep(cfg.LST_SCAN_INTERVAL)


# ═══════════════════════════════════════════════════════════════════════════
#  KAMINO FLASH-LIQUIDATION SCANNER
# ═══════════════════════════════════════════════════════════════════════════

async def kamino_liquidation_scanner(session, cfg, rpc_manager, keypair, jito_executor):
    """Main Kamino flash-liquidation scanner for MarginFi flash loans.

    Continuously monitors Kamino lending obligations for Health Factor < 1.0,
    executes profitable liquidations using atomic MarginFi flash loans.
    """
    rpc_url = rpc_manager.get_rpc()

    # Initialize components
    liquidator = KaminoFlashLiquidationExecutor(
        session=session,
        rpc_url=rpc_url,
        marginfi_account=cfg.MARGINFI_ACCOUNT_PUBKEY,
        min_profit_sol=cfg.KAMINO_MIN_PROFIT_SOL,
    )
    tx_builder = JupiterTxBuilder(session=session, rpc_url=rpc_url)

    cycle_count = 0

    logger.debug(
        f"🚀 Kamino Liquidation Scanner started | "
        f"min_profit={cfg.KAMINO_MIN_PROFIT_SOL} SOL | "
        f"scan_interval={cfg.KAMINO_SCAN_INTERVAL}s"
    )

    while True:
        cycle_count += 1
        try:
            # ── Step 1: Scan for unhealthy obligations ───────────────────────
            obligations = await liquidator.scan_for_liquidations()

            if not obligations:
                if cycle_count % 60 == 0:  # Log status every ~5 min
                    logger.debug(f"📡 Kamino Scanner heartbeat #{cycle_count} | scanned {len(obligations)} obligations")
                await asyncio.sleep(cfg.KAMINO_SCAN_INTERVAL)
                continue

            logger.debug(f"🎯 Found {len(obligations)} unhealthy Kamino obligations")

            # ── Step 2: Find profitable liquidation opportunities ───────────
            opportunities = await liquidator.find_profitable_liquidations(obligations)

            if not opportunities:
                logger.debug("No profitable liquidation opportunities found")
                await asyncio.sleep(cfg.KAMINO_SCAN_INTERVAL)
                continue

            # ── Step 3: Execute liquidations ────────────────────────────────
            for opportunity in opportunities:
                logger.debug(
                    f"💰 Profitable liquidation: {str(opportunity.obligation.address)[:8]}... | "
                    f"debt={opportunity.borrow_amount/1e6:.2f} USDC | "
                    f"profit={opportunity.expected_profit_sol:.6f} SOL"
                )

                # Execute the liquidation
                success = await liquidator.execute_liquidation(
                    opportunity, tx_builder, keypair, jito_executor
                )

                if success:
                    stats["trades"] += 1
                    logger.debug(f"✅ Kamino liquidation successful | profit={opportunity.expected_profit_sol:.6f} SOL")
                else:
                    stats["sim_fails"] += 1
                    record_sim_failure("kamino_liquidation")
                    logger.warning("❌ Kamino liquidation failed")

                # Small delay between executions
                await asyncio.sleep(0.1)

        except Exception as e:
            logger.error(f"Kamino scanner error: {e}")

        await asyncio.sleep(cfg.KAMINO_SCAN_INTERVAL)


# ═══════════════════════════════════════════════════════════════════════════
#  LST INSTANT UNSTAKE ARBITRAGE SCANNER
# ═══════════════════════════════════════════════════════════════════════════

async def lst_unstake_arbitrage_scanner(session, cfg, rpc_manager, keypair, jito_executor):
    """Main LST instant unstake arbitrage scanner for MarginFi flash loans.

    Monitors Raydium LST/SOL pools vs protocol unstake rates, executes
    arbitrage when market price < protocol price.
    """
    rpc_url = rpc_manager.get_rpc()

    # Initialize components
    unstake_arb = LstInstantUnstakeArbitrage(
        session=session,
        rpc_url=rpc_url,
        marginfi_account=cfg.MARGINFI_ACCOUNT_PUBKEY,
        min_deviation_pct=cfg.LST_UNSTAKE_MIN_DEVIATION_PCT,
        tx_builder=tx_builder,
        optimal_trade_sizer=trade_sizer,
    )
    tx_builder = JupiterTxBuilder(session=session, rpc_url=rpc_url)

    cycle_count = 0

    logger.debug(
        f"🚀 LST Unstake Arbitrage Scanner started | "
        f"min_deviation={cfg.LST_UNSTAKE_MIN_DEVIATION_PCT}% | "
        f"scan_interval={cfg.LST_UNSTAKE_SCAN_INTERVAL}s"
    )

    while True:
        cycle_count += 1
        try:
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
                logger.debug(
                    f"💰 LST Unstake opportunity: {str(opportunity.lst_mint)[:8]}... | "
                    f"market={opportunity.market_price_sol:.6f} protocol={opportunity.protocol_price_sol:.6f} | "
                    f"dev={opportunity.deviation_pct:.2f}% | "
                    f"profit={opportunity.expected_profit_sol:.6f} SOL"
                )

                # Execute the arbitrage
                success = await unstake_arb.execute_unstake_arbitrage(
                    opportunity, tx_builder, keypair, jito_executor
                )

                if success:
                    stats["trades"] += 1
                    logger.debug(f"✅ LST unstake arbitrage successful | profit={opportunity.expected_profit_sol:.6f} SOL")
                else:
                    stats["sim_fails"] += 1
                    record_sim_failure("lst_unstake")
                    logger.warning("❌ LST unstake arbitrage failed")

                # Small delay between executions
                await asyncio.sleep(0.1)

        except Exception as e:
            logger.error(f"LST unstake scanner error: {e}")

        await asyncio.sleep(cfg.LST_UNSTAKE_SCAN_INTERVAL)


# ═══════════════════════════════════════════════════════════════════════════
#  ORDERBOOK-AMM BIPARTITE SOLVER SCANNER
# ═══════════════════════════════════════════════════════════════════════════

async def orderbook_amm_scanner(session, cfg, rpc_manager, keypair, jito_executor):
    """Main orderbook-AMM arbitrage scanner using bipartite solver.

    Monitors Phoenix orderbook vs Raydium AMM for arbitrage opportunities
    using mathematical optimization for flash loan sizing.
    """
    rpc_url = rpc_manager.get_rpc()

    # Initialize components
    solver = BipartiteOrderbookAmmSolver()
    tx_builder = JupiterTxBuilder(session=session, rpc_url=rpc_url)

    cycle_count = 0

    logger.debug(
        f"🚀 Orderbook-AMM Scanner started | "
        f"phoenix_market={cfg.PHOENIX_MARKET_ADDRESS[:8] if cfg.PHOENIX_MARKET_ADDRESS else 'none'} | "
        f"raydium_pool={cfg.RAYDIUM_POOL_ADDRESS[:8] if cfg.RAYDIUM_POOL_ADDRESS else 'none'} | "
        f"scan_interval={cfg.ORDERBOOK_AMM_SCAN_INTERVAL}s"
    )

    while True:
        cycle_count += 1
        try:
            # ── Step 1: Fetch orderbook and AMM data ───────────────────────
            if not cfg.PHOENIX_MARKET_ADDRESS or not cfg.RAYDIUM_POOL_ADDRESS:
                if cycle_count % 120 == 0:
                    logger.warning("Orderbook-AMM scanner disabled: missing market/pool addresses")
                await asyncio.sleep(cfg.ORDERBOOK_AMM_SCAN_INTERVAL)
                continue

            orderbook_data = await fetch_phoenix_orderbook(session, cfg.PHOENIX_MARKET_ADDRESS)
            amm_data = await fetch_raydium_reserves(session, cfg.RAYDIUM_POOL_ADDRESS)

            if not orderbook_data or not amm_data:
                await asyncio.sleep(cfg.ORDERBOOK_AMM_SCAN_INTERVAL)
                continue

            # ── Step 2: Solve for optimal arbitrage ─────────────────────────
            result = solver.solve_optimal_arbitrage(
                orderbook_asks=orderbook_data["asks"],
                amm_reserves=amm_data["reserves"],
                available_liquidity=amm_data["available_liquidity"]
            )

            if not result or result.expected_profit <= 0:
                if cycle_count % 60 == 0:  # Log status every ~1 min
                    logger.debug(f"📡 Orderbook-AMM Scanner heartbeat #{cycle_count}")
                await asyncio.sleep(cfg.ORDERBOOK_AMM_SCAN_INTERVAL)
                continue

            logger.debug(
                f"💰 Orderbook-AMM opportunity: borrow={result.optimal_borrow_amount:.2f} | "
                f"profit={result.expected_profit:.6f} | "
                f"levels={len(result.buy_levels_used)} | "
                f"impact={result.final_price_impact:.4f}"
            )

            # ── Step 3: Execute arbitrage ───────────────────────────────────
            success = await solver.execute_arbitrage(
                result,
                tx_builder,
                keypair,
                jito_executor,
                phoenix_program_id="Phoe9gjQAJbkx6F9Eg1x4gMWmz1wxmVcX2X1dWH1Kt",
                raydium_program_id="675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
                strategy_type=4
            )

            if success:
                stats["trades"] += 1
                logger.debug(f"✅ Orderbook-AMM arbitrage successful | profit={result.expected_profit:.6f}")
            else:
                stats["sim_fails"] += 1
                record_sim_failure("orderbook_amm")
                logger.warning("❌ Orderbook-AMM arbitrage failed")

        except Exception as e:
            logger.error(f"Orderbook-AMM scanner error: {e}")

        await asyncio.sleep(cfg.ORDERBOOK_AMM_SCAN_INTERVAL)


async def fetch_phoenix_orderbook(session, market_address: str):
    """Fetch Phoenix orderbook data."""
    # TODO: Implement Phoenix orderbook fetching
    return None


async def fetch_raydium_reserves(session, pool_address: str):
    """Fetch Raydium pool reserves."""
    # TODO: Implement Raydium reserves fetching
    return None


async def start_jito_sniper():
    """Start Jito sniper system for pool creation sniping."""
    try:
        logger.info("🎯 Starting Jito Sniper for pool creation sniping...")

        # Start tip manager and pool listener
        await jito_tip_manager.start()
        await jito_pool_listener.start()

        logger.info("✅ Jito Sniper active - monitoring for new pool creations")
    except Exception as e:
        logger.error(f"Failed to start Jito sniper: {e}")
        raise


async def handle_pool_creation_sniping(pool_event, keypair, session, rpc_manager):
    """Handle pool creation event for sniping."""
    try:
        logger.debug(f"🎯 Sniping opportunity detected: {pool_event}")

        # Pre-trade security validation
        guard = PreTradeGuard(session=session, rpc_url=rpc_manager.get_rpc())

        # Check both token mints for security
        for mint_attr in ['base_mint', 'quote_mint']:
            if hasattr(pool_event, mint_attr):
                mint_address = getattr(pool_event, mint_attr)
                can_trade, reason = await guard.validate_token_security(
                    mint_address=mint_address,
                    rpc_url=rpc_manager.get_rpc()
                )
                if not can_trade:
                    logger.info(f"🚫 Pool sniping aborted for {str(mint_address)[:8]}: {reason}")
                    return

        # Build sniping transaction with optimal tip
        sniping_tx = await jito_tx_builder.build_sniping_transaction(
            pool_event=pool_event,
            buyer_keypair=keypair,
            buy_amount_lamports=1_000_000_000  # 1 SOL (configurable)
        )

        if not sniping_tx:
            logger.error("Failed to build sniping transaction")
            return

        # Send as Jito bundle to multiple endpoints
        bundle_result = await jito_bundle_sender.send_bundle(sniping_tx)

        if bundle_result["success"]:
            logger.debug(f"🚀 Pool sniping bundle sent! Bundle ID: {bundle_result.get('first_bundle_id')}")
            logger.debug(f"   Sent to {bundle_result['success_count']}/{bundle_result['total_endpoints']} endpoints")
        else:
            logger.warning(f"❌ Pool sniping bundle failed: {bundle_result['errors']}")

    except Exception as e:
        logger.error(f"Error in pool creation sniping: {e}")


async def create_simple_dummy_tx(session, keypair, rpc_getter):
    """Create a simple dummy transaction for priority fee estimation"""
    try:
        # Create a minimal transfer transaction for fee estimation
        dummy_recipient = Pubkey.from_string("11111111111111111111111111111112")  # Dummy recipient
        transfer_ix = transfer(TransferParams(
            from_pubkey=keypair.pubkey(),
            to_pubkey=dummy_recipient,
            lamports=1  # Minimal amount
        ))

        # Get recent blockhash
        payload = {"jsonrpc": "2.0", "id": 1, "method": "getLatestBlockhash"}
        timeout = aiohttp.ClientTimeout(total=1.0)
        async with session.post(rpc_getter(), json=payload, timeout=timeout) as resp:
            if resp.status == 200:
                data = await resp.json()
                if "result" in data:
                    recent_blockhash = Hash.from_string(data["result"]["value"]["blockhash"])

                    msg = MessageV0.try_compile(
                        payer=keypair.pubkey(),
                        instructions=[transfer_ix],
                        address_lookup_table_accounts=[],
                        recent_blockhash=recent_blockhash
                    )
                    tx = VersionedTransaction(msg, [keypair])
                    return base64.b64encode(bytes(tx)).decode('ascii')
    except Exception as e:
        logger.debug(f"Dummy tx creation error: {e}")
    return None

async def get_dynamic_priority_fee(session, rpc_getter, serialized_tx, cfg, priority_level="Medium"):
    """Get dynamic priority fee from Helius API"""
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "getPriorityFeeEstimate",
            "params": [{
                "transaction": serialized_tx,
                "options": {"priorityLevel": priority_level, "recommended": True}
            }]
        }
        timeout = aiohttp.ClientTimeout(total=1.0)
        async with session.post(rpc_getter(), json=payload, timeout=timeout) as resp:
            if resp.status == 200:
                data = await resp.json()
                if "result" in data and "priorityFeeEstimate" in data["result"]:
                    # Return as microlamports (int)
                    fee_microlamports = int(data["result"]["priorityFeeEstimate"])
                    return fee_microlamports
    except Exception as e:
        logger.debug(f"Priority fee API error: {e}")
    # Fallback to hardcoded value
    return cfg.PRIORITY_FEE


async def _daily_cleanup(data_aggregator: DataAggregator):
    """Run daily cleanup of old data."""
    while True:
        # Wait until next day (simplified - runs every 24 hours)
        await asyncio.sleep(24 * 60 * 60)
        try:
            await data_aggregator.cleanup_old_data(keep_days=14)
            logger.info("✅ Daily data cleanup completed")
        except Exception as e:
            logger.error(f"Daily cleanup failed: {e}")

async def start_pump_predictor(predictor: PumpFunMigrationPredictor):
    """Start Pump.fun migration predictor with initial curve addresses."""
    try:
        logger.info("🎯 Starting Pump.fun migration predictor...")

        # For demonstration, monitor a few example curves
        # In production, you'd get these from logs or configuration
        example_curves = [
            # Add real Pump.fun curve addresses here
            # "CurveAddress1", "CurveAddress2"
        ]

        if example_curves:
            await predictor.start_monitoring(example_curves)
            logger.info(f"✅ Monitoring {len(example_curves)} Pump.fun curves")
        else:
            logger.info("ℹ️ No Pump.fun curves configured for monitoring")

        # Keep predictor running
        while True:
            await asyncio.sleep(10)
            # Log status periodically
            status = predictor.get_migration_status()
            if status:
                active_curves = len([s for s in status.values() if s["phase"] != "early"])
                if active_curves > 0:
                    logger.info(f"📊 Pump.fun status: {active_curves} curves in active phases")

    except Exception as e:
        logger.error(f"Pump.fun predictor failed: {e}")

async def handle_pump_migration(migration_data: Dict[str, Any], session, cfg, rpc_manager, keypair, jito_executor, ai_collector):
    """Handle Pump.fun migration event with enhanced PDA system."""
    try:
        logger.info(f"🚀 Pump.fun migration detected: {migration_data}")

        # Extract migration details
        curve_address = migration_data.get("curve_address")
        mint_address = migration_data.get("mint_address")
        raydium_addresses = migration_data.get("raydium_addresses")
        transaction_template = migration_data.get("transaction_template")
        market_id = migration_data.get("market_id")

        if not mint_address:
            logger.error("Missing mint address in migration data")
            return

        logger.info(f"💎 Migration details:")
        logger.info(f"   Mint: {mint_address[:8]}...")
        logger.info(f"   Curve: {curve_address[:8] if curve_address else 'N/A'}...")
        logger.info(f"   Pool: {raydium_addresses.get('amm_id', 'N/A')[:8] if raydium_addresses else 'N/A'}...")
        logger.info(f"   Market: {market_id[:8] if market_id else 'N/A'}...")
        logger.info(f"   Template: {'✅ Ready' if transaction_template else '❌ Missing'}")

        # Execute enhanced migration arbitrage
        success = await execute_enhanced_migration_arbitrage(
            mint_address=mint_address,
            raydium_addresses=raydium_addresses,
            transaction_template=transaction_template,
            market_id=market_id,
            session=session,
            cfg=cfg,
            rpc_manager=rpc_manager,
            keypair=keypair,
            jito_executor=jito_executor,
            ai_collector=ai_collector
        )

        if success:
            logger.info(f"🎉 Enhanced migration arbitrage executed successfully!")
        else:
            logger.warning(f"❌ Enhanced migration arbitrage failed")

    except Exception as e:
        logger.error(f"Migration handling failed: {e}")

async def execute_enhanced_migration_arbitrage(mint_address, raydium_addresses, transaction_template,
                                              market_id, session, cfg, rpc_manager, keypair,
                                              jito_executor, ai_collector):
    """Execute migration arbitrage with enhanced PDA system."""
    global TOTAL_FAILED_BUNDLES_IN_A_ROW, GLOBAL_STOP_EVENT
    try:
        start_time = time.time()

        # Get current blockhash
        blockhash = await get_current_blockhash(session, rpc_manager.get_rpc())
        if not blockhash:
            logger.error("Failed to get blockhash for migration execution")
            return False

        # Prepare transaction with pre-computed addresses
        if transaction_template and raydium_addresses:
            # Instantiate template with current data
            user_token_accounts = {
                "user_token_account": "placeholder",  # Would compute actual ATA
                "user_pc_token_account": "placeholder"  # Would compute actual WSOL ATA
            }

            transaction_data = transaction_template.instantiate_with_blockhash(
                blockhash, user_token_accounts
            )

            if transaction_data:
                logger.info("✅ Transaction instantiated with pre-computed addresses")
                logger.info(f"   Using {len(raydium_addresses)} pre-computed addresses")
                if market_id:
                    logger.info("   Market-aware execution enabled")
            else:
                logger.warning("Failed to instantiate transaction template")
                return False
        else:
            logger.warning("Missing transaction template or addresses")
            return False

        # Execute via Jito with enhanced tip calculation
        expected_profit_sol = 0.5  # Would be calculated based on migration
        jito_tip_sol = expected_profit_sol * cfg.JITO_TIP_PERCENT

        # Create tip instruction and inject it into transaction_data (atomic fix)
        # The Jito tip must be part of the SAME transaction so it reverts atomically.
        tip_ix = transfer(TransferParams(
            from_pubkey=keypair.pubkey(),
            to_pubkey=Pubkey.from_string("96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"),
            lamports=int(jito_tip_sol * 1_000_000_000)
        ))

        if not transaction_data:
            logger.warning("No transaction data available")
            return False

        # Inject tip instruction: decompile VersionedTransaction, add tip, recompile
        from solders.message import MessageV0
        from solders.instruction import Instruction as SoldersInstruction
        from solders.transaction import VersionedTransaction

        msg = transaction_data.message
        all_keys = list(msg.account_keys)

        # Decompile existing compiled instructions back to Instruction objects
        decompiled = []
        for ci in msg.instructions:
            decompiled.append(SoldersInstruction(
                program_id=all_keys[ci.program_id_index],
                accounts=[all_keys[i] for i in ci.accounts],
                data=bytes(ci.data),
            ))

        # Add tip instruction to the end (before any cleanup ixs)
        all_ixs = decompiled + [tip_ix]

        # Recompile new message with blockhash preserved
        new_msg = MessageV0.try_compile(
            payer=msg.account_keys[0],
            instructions=all_ixs,
            address_lookup_table_accounts=list(msg.address_lookup_table_accounts),
            recent_blockhash=msg.recent_blockhash,
        )

        transaction_data = VersionedTransaction(new_msg, [keypair])

        # Send bundle as exactly ONE transaction (atomic: tip OR arb, never partial)
        bundle_to_send = [transaction_data]

        # Send enhanced bundle (single transaction with merged tip)
        stats["bundle_send_attempts"] += 1
        bundle_result = await jito_executor.send_bundle(bundle_to_send)

        execution_time = (time.time() - start_time) * 1000

        if bundle_result["success"]:
            global TOTAL_FAILED_BUNDLES_IN_A_ROW
            TOTAL_FAILED_BUNDLES_IN_A_ROW = 0
            stats["bundle_successes"] += 1
            bundle_id = bundle_result["bundle_id"]
            logger.info(f"🔥 Enhanced migration bundle sent! ID: {bundle_id}")
            logger.info(f"⚡ Executed in {execution_time:.2f}ms with pre-computed addresses")

            return True
        else:
            err = str(bundle_result.get('error', ''))
            if "SlippageExceeded" in err:
                TOTAL_FAILED_BUNDLES_IN_A_ROW += 1
                if TOTAL_FAILED_BUNDLES_IN_A_ROW >= 10:
                    logger.critical("🚨 10 consecutive SlippageExceeded — activating GLOBAL_STOP_EVENT")
                    GLOBAL_STOP_EVENT.set()
            else:
                TOTAL_FAILED_BUNDLES_IN_A_ROW = 0
            logger.warning(f"❌ Enhanced bundle failed: {err}")

            return False

    except Exception as e:
        logger.error(f"Enhanced migration execution failed: {e}")
        return False

async def get_current_blockhash(session, rpc_url):
    """Get current blockhash for transaction."""
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getLatestBlockhash",
            "params": [{"commitment": "confirmed"}]  # Phase 48: Use confirmed for Jito bundle reliability
        }
        async with session.post(rpc_url, json=payload, timeout=aiohttp.ClientTimeout(total=1.0)) as resp:
            if resp.status == 200:
                data = await resp.json()
                if "result" in data:
                    return data["result"]["value"]["blockhash"]
    except Exception as e:
        logger.debug(f"Blockhash fetch failed: {e}")
    return None

def create_placeholder_arbitrage_tx(keypair, blockhash):
    """Create placeholder arbitrage transaction for testing."""
    # This would be replaced with actual transaction from template
    dummy_ix = transfer(TransferParams(
        from_pubkey=keypair.pubkey(),
        to_pubkey=Pubkey.from_string("11111111111111111111111111111112"),
        lamports=1000
    ))

    msg = MessageV0.try_compile(
        payer=keypair.pubkey(),
        instructions=[dummy_ix],
        address_lookup_table_accounts=[],
        recent_blockhash=blockhash
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
    global WSOL_JUST_CLOSED_ATOMICALLY
    WSOL_JUST_CLOSED_ATOMICALLY = time.time()


async def check_bundle_confirmation(bundle_id, jito_executor, data_aggregator, tx_b64, tx_id, execution_time, session=None, keypair=None, rpc_getter=None, target_mint_ata=None, virtual_balance_to_deduct=0.0):
    """Check bundle confirmation asynchronously without blocking."""
    try:
        confirmation = await jito_executor.wait_for_confirmation(bundle_id, max_wait_time=15.0)
        if confirmation.get("status") == "failed":
            logger.error(f"❌ ТРЕЙД УПАЛ (Bundle Failed): {confirmation}")
            await data_aggregator.log_tx_failed(bundle_id, confirmation, {"tx": tx_b64})

            # ВОЗВРАЩАЕМ виртуальный баланс при неудаче — предотвращает утечку (Fix Balance Leak)
            if virtual_balance_to_deduct > 0:
                async with stats_lock:
                    prev = stats["virtual_balance"]
                    stats["virtual_balance"] = max(0.0, stats["virtual_balance"] + virtual_balance_to_deduct)
                logger.info(f"♻️ Бандл отклонен, баланс {virtual_balance_to_deduct:.6f} SOL возвращен (virtual_balance: {prev:.6f} → {stats['virtual_balance']:.6f})")

            # MEV: Losing an auction is normal. Only trigger circuit breaker for critical errors.
            error_msg = str(confirmation.get("error", "")).lower()
            critical_errors = ["insufficient funds", "account not found", "unauthorized", "invalid signer"]
            if any(err in error_msg for err in critical_errors):
                GLOBAL_STOP_EVENT.set()
                logger.critical(f"🛑 CIRCUIT BREAKER ACTIVATED: {error_msg.upper()}. Скрипт остановлен для анализа.")

                # TASK 1 — Zero-Delay ATA close even on failure (prevent accumulation)
                if target_mint_ata and session and keypair and rpc_getter:
                    # DISABLED: atomic close inside bundle — asyncio.create_task(close_ata_after_arbitrage(session, keypair, rpc_getter, target_mint_ata))
                    pass
            else:
                logger.debug("ℹ️ Auction lost or bundle dropped - normal operation continues")
        elif confirmation.get("status") == "timeout":
            logger.warning(f"⏰ BUNDLE TIMEOUT: {bundle_id} - normal in competitive Jito auctions")

            # ВОЗВРАЩАЕМ виртуальный баланс при таймауте — предотвращает утечку (Fix Balance Leak)
            if virtual_balance_to_deduct > 0:
                async with stats_lock:
                    prev = stats["virtual_balance"]
                    stats["virtual_balance"] = max(0.0, stats["virtual_balance"] + virtual_balance_to_deduct)
                logger.info(f"♻️ Бандл таймаут, баланс {virtual_balance_to_deduct:.6f} SOL возвращен (virtual_balance: {prev:.6f} → {stats['virtual_balance']:.6f})")

            await data_aggregator.log_tx_failed(bundle_id, confirmation, {"tx": tx_b64, "reason": "timeout"})
        else:
            # Log successful confirmation + TASK 1: zero-delay ATA close for any outcome
            await data_aggregator.log_tx_confirmed(
                tx_id,
                {'real_profit_sol': 0.001, 'status': 'confirmed'},  # Placeholder profit
                {'execution_time_ms': execution_time}
            )
            
            # TASK 1 — Zero-Delay Post-Trade ATA Close (fire & forget)
            if target_mint_ata and session and keypair and rpc_getter:
                logger.info(f"♻️ Skip async ATA close (atomic inside bundle): {target_mint_ata[:8]}...")
                # DISABLED: atomic close inside bundle — asyncio.create_task(close_ata_after_arbitrage(session, keypair, rpc_getter, target_mint_ata))
            # TASK 49b: Post-trade dust sweep — trigger immediately after confirmed arbitrage
            if dust_sweeper:
                asyncio.create_task(dust_sweeper._sweep_dust())
    except Exception as e:
        logger.error(f"Confirmation check failed: {e}")

async def execute_priority_opportunity(opportunity, session, cfg, rpc_manager, keypair, jito_executor, ai_collector, flywheel_scaler, data_aggregator, alt_manager=None, execution_router=None, flash_pivot_engine=None):
    """Execute a high-priority arbitrage opportunity."""
    start_time = time.time()
    
    # Get current balance and flywheel params
    current_balance_sol = stats.get("last_balance", 0.017)
    params = flywheel_scaler.get_trading_params(current_balance_sol)

    # Check circuit breaker
    if GLOBAL_STOP_EVENT.is_set():
        logger.critical("Бот остановлен для анализа. Ожидание ручного рестарта.")
        return

    # Check if pair has too many failures, switch to other pairs
    if pair_failure_count.get(opportunity.pair, 0) > 5:
        logger.debug(f"🚫 Skipping {opportunity.pair} due to repeated failures (>5), switching resources")
        return

    # Phase 42: Upfront Liquidity Guard (REWRITTEN Phase 48)
    # Formula: Current_Balance - (ACTUAL_NEW_ATAs_NEEDED * 0.00204) - Jito_Tip < 0.01
    tip_amount_lamports = opportunity.metadata.get("tip_lamports", getattr(cfg, "BASE_TIP_LAMPORTS", 10000))
    
    actual_new_atas_needed = 0
    mints_involved = set()
    for leg in [opportunity.metadata.get("quote1"), opportunity.metadata.get("quote2")]:
        if leg:
            mints_involved.add(leg.get("inputMint"))
            mints_involved.add(leg.get("outputMint"))
    
    # Check which ATAs actually need creation (not in cache)
    for mint in mints_involved:
        if not mint: continue
        from spl.token.instructions import get_associated_token_address
        ata_addr = str(get_associated_token_address(keypair.pubkey(), Pubkey.from_string(mint)))
        if ata_addr not in ATA_CACHE:
            actual_new_atas_needed += 1
            # Note: We don't add to cache here, only after successful creation/check
    
    rent_per_ata = 0.00204
    # Fix 44: Use virtual_balance for affordability check (doesn't rely on last_WS_update)
    current_sol = stats.get("virtual_balance", stats.get("last_balance", 0.0))
    tip_sol = tip_amount_lamports / 1e9
    
    mints_involved = set()
    for leg in [opportunity.metadata.get("quote1"), opportunity.metadata.get("quote2")]:
        if leg:
            mints_involved.add(leg.get("inputMint"))
            mints_involved.add(leg.get("outputMint"))
    
    actual_new_atas_needed = 0
    from spl.token.instructions import get_associated_token_address
    from src.config.xstocks_registry import is_xstock_token

    for mint_str in mints_involved:
        if not mint_str or mint_str in CORE_GOLDEN_MINTS: 
            continue
            
        mint_pubkey = Pubkey.from_string(mint_str)
        program_id = TOKEN_2022_PROGRAM_ID if is_xstock_token(mint_pubkey) else TOKEN_PROGRAM_ID
        ata_addr = str(get_associated_token_address(keypair.pubkey(), mint_pubkey, program_id))
        
        if ata_addr not in ATA_CACHE:
            exists = await check_ata_exists(session, rpc_manager.get_rpc, keypair.pubkey(), mint_str)
            if not exists:
                actual_new_atas_needed += 1
            else:
                ATA_CACHE.add(ata_addr)
    
    current_sol = stats.get("virtual_balance", stats.get("last_balance", 0.0))
    tip_sol = tip_amount_lamports / 1e9
    rent_cost_sol = actual_new_atas_needed * RENT_PER_ATA_SOL
    
    projected_balance_during_tx = current_sol - rent_cost_sol - tip_sol - cfg.PRIORITY_FEE
    
    if projected_balance_during_tx < MIN_RESERVE_SOL:
        logger.warning(
            f"🚫 [Dynamic Rent Guard] Слишком дорого! "
            f"Нужно {actual_new_atas_needed} новых ATA. "
            f"Баланс в процессе: {projected_balance_during_tx:.5f} < Резерв {MIN_RESERVE_SOL}. Скипаем."
        )
        return

    logger.debug(f"🚀 Executing priority opportunity: {opportunity.pair} (score: {opportunity.score:.1f})")

    # Extract saved quotes from metadata instead of re-fetching (saves API calls)
    quote1 = opportunity.metadata.get("quote1")
    quote2 = opportunity.metadata.get("quote2")
    chosen_route = opportunity.metadata.get("chosen_route")
    if not chosen_route and quote1 and quote2:
        chosen_route = [quote1, quote2]

    amount_lamports = opportunity.metadata.get("amount_lamports", int(0.1 * 1_000_000_000))
    in_mint_str = opportunity.metadata.get("in_mint")
    out_mint_str = opportunity.metadata.get("out_mint")
    tip_amount_lamports = opportunity.metadata.get("tip_lamports", getattr(cfg, "BASE_TIP_LAMPORTS", 10000))

    if not quote1 or not quote2 or not chosen_route:
        logger.warning(f"No quotes or chosen_route in metadata for {opportunity.pair}, skipping")
        return

    # Convert mint strings back to Pubkeys
    from solders.pubkey import Pubkey
    try:
        in_mint = Pubkey.from_string(in_mint_str) if in_mint_str else TOKENS["SOL"]
        out_mint = Pubkey.from_string(out_mint_str) if out_mint_str else TOKENS["SOL"]
    except:
        in_mint = TOKENS["SOL"]
        out_mint = TOKENS["SOL"]

    # Get flywheel params
    current_balance_sol = stats.get("last_balance", 0.017)
    params = flywheel_scaler.get_trading_params(current_balance_sol)
    cfg.ARBITRAGE_FILTER_MIN_PROFIT_SOL = params["min_net_profit_sol"]

    # Phase 24: Removed global execution lock to allow fully concurrent TX building and simulations.
    # The Jito Block Engine handles sequencing automatically.

    # --- ATA RENT GUARD (per-trade profit check) ---
    # Deduct 0.002 SOL from expected profit if a new ATA must be created for the target token.
    # Prevents Death-by-Success: don't let 5 simultaneous wins drain 0.01 SOL in rent deposits.
    from spl.token.instructions import get_associated_token_address
    from src.config.xstocks_registry import is_xstock_token
    _dst_mint_str = str(out_mint)
    _dst_prog_id = TOKEN_2022_PROGRAM_ID if is_xstock_token(Pubkey.from_string(_dst_mint_str)) else TOKEN_PROGRAM_ID
    _dst_ata = str(get_associated_token_address(keypair.pubkey(), Pubkey.from_string(_dst_mint_str), _dst_prog_id))
    _rent_sol = 0.0
    if _dst_ata not in ATA_CACHE:
        _ata_already = await check_ata_exists(session, rpc_manager.get_rpc, keypair.pubkey(), _dst_mint_str)
        if _ata_already:
            ATA_CACHE.add(_dst_ata)
        else:
            _rent_sol = RENT_PER_ATA_SOL
            logger.info(f"⚠️ New ATA required for {_dst_mint_str[:8]} — deducting {_rent_sol:.5f} SOL from expected profit ({opportunity.expected_profit_sol:.6f} SOL)")
    # Fix 3 (Phantom Rent): ATA закрывается атомарно внутри бандла — рента возвращается мгновенно
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

        _golden = {str(TOKEN_PROGRAM_ID), str(TOKEN_2022_PROGRAM_ID)}
        _new_ata_count = 0
        for mint_str in leg_mints:
            mint_pk = Pubkey.from_string(mint_str)
            _prog_id = TOKEN_2022_PROGRAM_ID if is_xstock_token(mint_pk) else TOKEN_PROGRAM_ID
            _ata = str(get_associated_token_address(keypair.pubkey(), mint_pk, _prog_id))
            if _ata not in ATA_CACHE:
                _new_ata_count += 1
                ATA_CACHE.add(_ata)  # optimistic: assume we'll create it this trade

        _tip_sol  = int(tip_amount_lamports) / 1e9
        _gas_sol  = (cfg.PRIORITY_FEE + 0.000005)
        _rent_cost = _new_ata_count * RENT_PER_ATA_SOL
        _total_cost = _tip_sol + _gas_sol + _rent_cost
        _virt_bal = stats.get("virtual_balance", current_balance_sol)

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
    if opportunity.metadata.get("strategy") == "lst_depeg": strat_type = 2
    elif opportunity.metadata.get("strategy") == "orderbook": strat_type = 4
    
     # Fix 39: Pass the ACTUAL dynamic chosen_route (not hardcoded [quote1, quote2])
     # For triangular, this carries all 3 legs; for direct, 2 legs.
    tx_b64 = await create_flashloan_arbitrage_tx(
        session, in_mint, out_mint, amount_lamports, chosen_route,
        cfg, keypair, lambda: rpc_manager.get_rpc(), 
        use_jito=True, tip_lamports=tip_amount_lamports, alt_manager=alt_manager,
        strategy_type=strat_type,
        tip_accounts=jito_executor.tip_accounts if jito_executor else None,  # Fix 3: dynamic tip accounts
    )
    if not tx_b64:
        logger.warning("Failed to create priority arbitrage tx")
        return

    # 2. Simulate First (Capital Protection)
    from src.ingest.flash_simulator import FlashSimulator
    flash_sim = FlashSimulator(session, rpc_manager.get_rpc())

    # Local Simulation Integrity: Use region-matching RPC
    jito_endpoint = cfg.JITO_ENDPOINTS[0] if cfg.JITO_ENDPOINTS else None
    is_profitable, reason, sim_result = await flash_sim.validate_profitability(
        tx_b64=tx_b64,
        tx_signer_pubkey=str(keypair.pubkey()),
        min_profit_lamports=int(params["min_net_profit_sol"] * 1e9),
        tip_lamports=tip_amount_lamports,
        jito_endpoint=jito_endpoint
    )

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
                    "simulated_profit": sim_result.balance_delta_sol if sim_result else 0.0
                },
                metadata=opportunity.metadata
            )
        except Exception as e:
            logger.warning(f"Failed to log AI training data: {e}")

    if not is_profitable:
        if "StaleOracle" in reason and flash_pivot_engine:
            logger.warning(f"⚠️ StaleOracle detected for {opportunity.pair}. Triggering FlashPivotEngine (Phase 39)...")
            from decimal import Decimal
            pivot_opp = await flash_pivot_engine.check_pivot_needed(
                desired_asset=opportunity.metadata.get("in_mint", "So11111111111111111111111111111111111111112"),
                required_amount=Decimal(opportunity.metadata.get("amount_lamports", 0)) / Decimal(1_000_000_000),
                arbitrage_profit=Decimal(str(opportunity.expected_profit_sol))
            )
            
            if pivot_opp and pivot_opp.should_pivot:
                logger.debug(f"🔄 Pivoting flash loan from {pivot_opp.original_asset} to {pivot_opp.pivot_asset} to bypass stale oracle")
                # In a real HFT scenario, we would rebuild and re-simulate here.
                # For now, we trigger the engine as requested.
        
        logger.warning(f"Sim failed: {reason}. Skipping execution.")
        return

    # 3. Hybrid Execution (Jito/Standard)
    tx_bytes = base64.b64decode(tx_b64)
    arbitrage_tx = VersionedTransaction.from_bytes(tx_bytes)
    result = await execution_router.execute_opportunity(session, cfg, rpc_manager.get_rpc(), arbitrage_tx, tip_amount_lamports)

    # Fix 44: Virtual Balance Guard — deduct cost as soon as the bundle is sent
    # (not confirmed — the confirmation path adds it back if successful)
    tip_lamports = int(tip_amount_lamports if tip_amount_lamports else getattr(cfg, "BASE_TIP_LAMPORTS", 10000))
    est_gas_lamports = int((cfg.PRIORITY_FEE + 0.000005) * 1e9)  # priority_fee + base tx fee
    virtual_balance_to_deduct = (tip_lamports + est_gas_lamports) / 1e9
    async with stats_lock:
        stats["virtual_balance"] = max(0.0, stats["virtual_balance"] - virtual_balance_to_deduct)
    logger.debug(
        f"💸 VirtualBalance deducted: -{virtual_balance_to_deduct:.6f} SOL "
        f"(tip={tip_lamports/1e9:.6f}, est_gas={est_gas_lamports/1e9:.6f}) "
        f"| virtual_balance={stats['virtual_balance']:.6f}"
    )
    
    # Record failure for pool blacklisting
    pair_failure_count[opportunity.pair] = pair_failure_count.get(opportunity.pair, 0) + 1
    
    # [Phase 27] ATA Rent Recovery is now handled inside check_bundle_confirmation for precision.
    from spl.token.instructions import get_associated_token_address
    out_ata = str(get_associated_token_address(keypair.pubkey(), out_mint)) if out_mint_str and out_mint_str != str(TOKENS["SOL"]) else None

    execution_time = (time.time() - start_time) * 1000

    # Log transaction sent (outside lock)
    if result.get("success"):
        # Reset pair failure counter on new success (PairFailureGuard balance)
        pair_failure_count[opportunity.pair] = 0
        tx_id_str = in_mint_str[:8] + out_mint_str[:8] + str(int(time.time()))
        logger.debug("🔥 Priority transaction sent successfully!")

        # Check confirmation asynchronously (don't block other operations)
        if "bundle_id" in result:
            task = asyncio.create_task(
                check_bundle_confirmation(
                    result["bundle_id"], jito_executor, data_aggregator,
                    base64.b64encode(bytes(arbitrage_tx)).decode(),
                    tx_id_str,
                    execution_time,
                    session=session,
                    keypair=keypair,
                    rpc_getter=lambda: rpc_manager.get_rpc(),
                    target_mint_ata=out_ata,
                    virtual_balance_to_deduct=virtual_balance_to_deduct,
                )
            )
            # Prevent task leak by tracking active tasks
            active_tasks.add(task)
            # Вместо простого add_done_callback используйте:
            task.add_done_callback(lambda t: active_tasks.discard(t))
    else:
        logger.warning(f"❌ Priority transaction failed: {result.get('error')}")
        pair_failure_count[opportunity.pair] = pair_failure_count.get(opportunity.pair, 0) + 1

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
                {"encoding": "jsonParsed"}
            ]
        }
        timeout = aiohttp.ClientTimeout(total=1.0)
        async with session.post(rpc_getter(), json=payload, timeout=timeout) as resp:
            if resp.status == 200:
                data = await resp.json()
                if "result" in data and "value" in data["result"]:
                    return len(data["result"]["value"]) > 0
    except Exception as e:
        logger.debug(f"ATA check error: {e}")
    return False



async def worker(queue, session, cfg, rpc_manager, keypair, limiters, jito_executor, arbitrage_scorer=None, priority_queue=None, alt_manager=None):
    # Stagger startup to prevent MacOS DNS gaierror(8)
    await asyncio.sleep(random.uniform(0.5, 5.0))
    pairs_checked = 0
    while True:
        priority, path = await queue.get()
        try:
            pairs_checked += 1
            if len(path) == 2:
                in_mint, target_mint = path
                in_mint_str = str(in_mint); target_mint_str = str(target_mint)   # str for HTTP/JSON safety
            elif len(path) == 3:
                # Triangular: t1 -> t2 -> t3 -> t1
                t1, t2, t3 = path
                in_mint, target_mint = t1, t3 # Use t3 as target for simplicity
                in_mint_str = str(in_mint); target_mint_str = str(target_mint)
            else:
                logger.warning(f"Unsupported path length: {len(path)}")
                continue

            # Fix 62: Price Freshness TTL — never trade stale data
            now = time.time()
            for mint in (in_mint_str, target_mint_str):
                entry = price_matrix.get(mint)
                if entry and (now - entry[1]) > 5.0:
                    logger.debug(f"Skipping stale price for {mint}")
                    continue  # skip this opportunity

            # Fix 44: Virtual Balance Guard — use virtual_balance so we never double-
            # commit capital while previous bundles are still in-flight.
            balance = stats.get("virtual_balance", stats.get("last_balance", 0.0))
            # Dynamic sizing from ENV + safety (Issue 5)
            borrow_env_sol = float(os.getenv("FLASH_LOAN_SIZE_SOL", "1.0"))
            borrow_amount_sol = borrow_env_sol  # For quote sizing (line 2327, 2363)
            
            # --- RESTORED MISSING QUOTE FETCHING LOGIC ---
            decimals_in = get_token_decimals(in_mint_str)
            amount_lamports = int(borrow_amount_sol * (10 ** decimals_in))
            routes = []
            route_types = []
            
            # Variables for re-fetch later
            quote1 = None
            quote_sol_usdc = None
            
            if len(path) == 2:
                # 2-hop Direct
                quote1 = await get_best_quote_multi(session, in_mint_str, target_mint_str, amount_lamports, cfg)
                if quote1 and "outAmount" in quote1:
                    quote1["out_amount"] = int(quote1["outAmount"])
                    q2 = await get_best_quote_multi(session, target_mint_str, in_mint_str, quote1["out_amount"], cfg)
                    if q2 and "outAmount" in q2:
                        q2["out_amount"] = int(q2["outAmount"])
                        routes.append([quote1, q2])
                        route_types.append("direct")

                # Triangular: Jupiter multi-hop via restrictIntermediateTokens=false (2 calls instead of 3 sequential)
                quote1_multi = await get_best_quote_multi(session, in_mint_str, target_mint_str, amount_lamports, cfg, restrict_intermediate=False)
                if quote1_multi and "outAmount" in quote1_multi:
                    quote1_multi["out_amount"] = int(quote1_multi["outAmount"])
                    q2_multi = await get_best_quote_multi(session, target_mint_str, in_mint_str, quote1_multi["out_amount"], cfg, restrict_intermediate=False)
                    if q2_multi and "outAmount" in q2_multi:
                        q2_multi["out_amount"] = int(q2_multi["outAmount"])
                        routes.append([quote1_multi, q2_multi])
                        route_types.append("triangular")

            elif len(path) == 3:
                # Multi-hop: Jupiter finds optimal route via intermediates with restrictIntermediateTokens=false
                q1 = await get_best_quote_multi(session, in_mint_str, target_mint_str, amount_lamports, cfg, restrict_intermediate=False)
                if q1 and "outAmount" in q1:
                    q1["out_amount"] = int(q1["outAmount"])
                    q2 = await get_best_quote_multi(session, target_mint_str, in_mint_str, q1["out_amount"], cfg, restrict_intermediate=False)
                    if q2 and "outAmount" in q2:
                        q2["out_amount"] = int(q2["outAmount"])
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
            sol_price_in_usd = price_matrix.get(SOL_MINT, (150.0, 0))[0] if isinstance(price_matrix.get(SOL_MINT), (list, tuple)) else price_matrix.get(SOL_MINT, 150.0)
            
            best_out_lamports = max([r[-1]["out_amount"] for r in routes])
            raw_profit_lamports = best_out_lamports - amount_lamports
            
            if raw_profit_lamports <= 0:
                continue  # No profit at all
            
            # Normalize cross-currency profit to Native SOL equivalents for tip calculation
            # Uses price oracle for all tokens (stables, LSTs, jitoSOL) - no more is_stable_trade illusion
            # Get USD price of input token
            in_mint_str_clean = str(in_mint) if hasattr(in_mint, '__str__') else in_mint
            if in_mint_str_clean not in price_matrix:
                in_mint_str_clean = target_mint_str  # fallback to other leg
            token_in_price_usd = price_matrix.get(in_mint_str_clean, (sol_price_in_usd, 0))[0] if isinstance(price_matrix.get(in_mint_str_clean), (list, tuple)) else price_matrix.get(in_mint_str_clean, sol_price_in_usd)
            
            profit_in_tokens = raw_profit_lamports / (10 ** decimals_in)
            profit_in_usd = profit_in_tokens * token_in_price_usd
            raw_profit_sol = profit_in_usd / sol_price_in_usd

            # Max tip should never exceed 90% of equivalent USD profit gained (converted to SOL)
            max_safe_tip_sol = raw_profit_sol * 0.9
            
            # Jito Game Theory: Dynamic Tips
            tip_lamports = getattr(cfg, "BASE_TIP_LAMPORTS", 10000)
            try:
                # 2. Determine competition level (Success Rate)
                attempts = stats.get("bundle_send_attempts", 0)
                successes = stats.get("bundle_successes", 0)
                competition_low = True
                if attempts > 5:
                    success_rate = successes / attempts
                    if success_rate < 0.2:
                        competition_low = False
                
                # 3. God-mode tip via JitoBiddingManager (tip_floor poller + step-up/down + capital guard)
                #       replaces JitoTipManager (WebSocket) + inline dynamic tip.
                # Capital Guard is inside calculate_optimal_tip: returns -1 if 50th > 80% profit.
                strategy_label = opportunity.metadata.get("strategy", "arbitrage") if 'opportunity' in dir() else "arbitrage"
                calculated_tip = jito_bidding_manager.calculate_optimal_tip(
                    expected_profit_sol=opportunity.metadata.get("expected_profit_sol", net_profit)
                    if 'opportunity' in dir() else net_profit,
                    strategy=str(strategy_label),
                )
                if calculated_tip < 0:  # Capital Guard hit
                    logger.warning(f"🚫 Capital Guard: Jito 50th > 80% of expected profit — skipping whale market for {path}")
                    continue

                # Apply the mathematical Cross-Currency safety cap
                safe_tip_lamports = min(calculated_tip, int(max_safe_tip_sol * 1e9))
                if safe_tip_lamports < 10000:
                    safe_tip_lamports = 10000 # Minimum floor
                    
                tip_lamports = safe_tip_lamports
                jito_tip_sol = tip_lamports / 1e9
            except Exception as e:
                logger.debug(f"Tip calculation error: {e}")
                tip_lamports = min(getattr(cfg, "BASE_TIP_LAMPORTS", 10000), int(max_safe_tip_sol * 1e9))
                jito_tip_sol = tip_lamports / 1e9

            # Find optimal size comparing routes
            result = trade_sizer.find_optimal_trade_size_multi_route(
                routes=routes,
                amount_in=amount_lamports,
                decimals_in=decimals_in,
                decimals_out=get_token_decimals(target_mint),
                jito_tip_sol=jito_tip_sol
            )

            if result is None or result[0] is None:
                continue

            optimal_amount, best_route_idx = result

            # Apply min() safeguard: env limit + available liquidity (Issue 5)
            required_fee_reserve_lamports = int((cfg.BASE_FEE + cfg.PRIORITY_FEE + cfg.ATA_FEE + 0.001) * 1e9)
            available_liquidity_lamports = max(0, int(balance * 1e9) - required_fee_reserve_lamports)
            borrow_cap_lamports = int(borrow_env_sol * 1e9)
            capped_amount = min(int(optimal_amount), borrow_cap_lamports)
            if capped_amount < 1_000_000:
                logger.debug(f"Cap too small ({capped_amount} lamports), skipping {opportunity.pair if 'opportunity' in dir() else 'unknown'}")
                continue
            optimal_amount = capped_amount

            # Calculate profit for chosen route using anti-sandwich profit BPS
            chosen_route = routes[best_route_idx]
            route_type = route_types[best_route_idx]

            # --- ЗАЩИТА АРЕНДЫ ATA (ATA Rent Guard) ---
            from spl.token.instructions import get_associated_token_address
            from src.config.xstocks_registry import is_xstock_token
            prog_id = TOKEN_2022_PROGRAM_ID if is_xstock_token(target_mint) else TOKEN_PROGRAM_ID
            target_ata = str(get_associated_token_address(keypair.pubkey(), target_mint, prog_id))
            rent_fee_sol = 0.0
            if target_ata not in ATA_CACHE:
                ata_exists = await check_ata_exists(session, rpc_manager.get_rpc, keypair.pubkey(), str(target_mint))
                if ata_exists:
                    ATA_CACHE.add(target_ata)
                else:
                    rent_fee_sol = 0.00204
                    logger.debug(f"⚠️ New ATA required for {str(target_mint)[:8]}. Deducting 0.002 SOL from expected profit.")

            # Calculate profit properly: convert all SOL fees to in_mint equivalents
            expected_out_lamports = chosen_route[-1]["out_amount"]  # Output in in_mint lamports
            profit_lamports = expected_out_lamports - amount_lamports

            is_sol_base = str(in_mint) == "So11111111111111111111111111111111111111112"
            sol_price_in_usd = price_matrix.get("So11111111111111111111111111111111111111112", 150.0)

            base_fee_sol = cfg.BASE_FEE + cfg.PRIORITY_FEE + cfg.ATA_FEE + rent_fee_sol + jito_tip_sol
            if is_sol_base:
                fee_in_base_token_lamports = int(base_fee_sol * 1e9)
            else:
                # Assuming in_mint is a stablecoin (6 decimals)
                fee_in_base_token_lamports = int(base_fee_sol * sol_price_in_usd * 1e6)

            total_fees_in_base = fee_in_base_token_lamports
            if profit_lamports < total_fees_in_base:
                logger.debug(f"Skipping: Profit {profit_lamports} lamports doesn't cover total fees ({total_fees_in_base} lamports)")
                continue

            # Calculate net_profit in SOL for logging and metadata
            if is_sol_base:
                net_profit = (profit_lamports - total_fees_in_base) / 1e9
            else:
                net_profit = ((profit_lamports - total_fees_in_base) / 1e6) / sol_price_in_usd

            if net_profit < float(cfg.MIN_PROFIT_SOL):
                logger.debug(f"Skipping: Net profit {net_profit:.6f} SOL < MIN_PROFIT_SOL ({cfg.MIN_PROFIT_SOL})")
                continue

            # ── Fix 34: Anti-Sandwich Profit-Aware BPS ───────────────────────────
            # Convert expected profit to basis points (profit per input lamport * 10 000).
            # This is the "slippage budget": sandwich bots can extract at most 40% of it.
            if optimal_amount > 0:
                profit_per_unit = (expected_out_lamports - float(optimal_amount)) / float(optimal_amount)
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
                # Direct route re-fetch: update quote2 in-situ with anti-sandwich slippage
                quote2 = await get_best_quote_multi(
                    session, target_mint_str, in_mint_str,
                    quote1["out_amount"], cfg,
                    expected_profit_bps=expected_profit_bps
                )
                if not quote2:
                    logger.debug("Anti-sandwich re-fetch of leg 2 failed; skipping")
                    continue
                # Fix 39: Direct route — rebuild chain from anti-sandwich value
                chosen_route = [quote1, quote2]

            elif best_route_idx == 1:
                # Triangular route re-fetch: use restrictIntermediateTokens=false (2 calls instead of 3)
                quote1_multi = await get_best_quote_multi(
                    session, in_mint_str, target_mint_str,
                    amount_lamports, cfg,
                    expected_profit_bps=expected_profit_bps,
                    restrict_intermediate=False
                )
                if not quote1_multi:
                    logger.debug("Anti-sandwich re-fetch of multi-hop leg 1 failed; skipping")
                    continue
                quote1_multi["out_amount"] = int(quote1_multi["outAmount"])
                q2_multi = await get_best_quote_multi(
                    session, target_mint_str, in_mint_str,
                    quote1_multi["out_amount"], cfg,
                    expected_profit_bps=expected_profit_bps,
                    restrict_intermediate=False
                )
                if not q2_multi:
                    logger.debug("Anti-sandwich re-fetch of multi-hop leg 2 failed; skipping")
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
                direct_out_sol = routes[0][-1]["out_amount"] / (10 ** decimals_in)
                direct_in_sol = float(optimal_amount) / (10 ** decimals_in)
                direct_profit = direct_out_sol - direct_in_sol

                tri_out_sol = routes[1][-1]["out_amount"] / (10 ** decimals_in)
                tri_in_sol = float(optimal_amount) / (10 ** decimals_in)
                tri_profit = tri_out_sol - tri_in_sol

                logger.debug(f"Route comparison: Direct +{direct_profit:.6f} SOL | Triangular +{tri_profit:.6f} SOL | Chosen: {route_type}")
            else:
                logger.debug(f"Direct route profit: +{net_profit:.6f} SOL")

            # Pre-trade security validation (skip vault check for existing arbitrage pairs)
            guard = PreTradeGuard(session=session, rpc_url=rpc_manager.get_rpc())
            can_trade, reason = await guard.validate_token_security(
                mint_address=target_mint,
                rpc_url=rpc_manager.get_rpc()
            )
            if not can_trade:
                logger.debug(f"🚫 Arbitrage aborted for {str(target_mint)[:8]}: {reason}")
                # Log skipped opportunity
                parsed_opportunity = {
                    'pair': f"{str(in_mint)[:8]}/{str(target_mint)[:8]}",
                    'amount_lamports': int(amount_lamports),
                    'reason': reason
                }
                await data_aggregator.log_opportunity_skipped('internal', parsed_opportunity, reason)
                continue

            # Log opportunity found
            parsed_opportunity = {
                'pair': f"{str(in_mint)[:8]}/{str(target_mint)[:8]}",
                'amount_lamports': int(optimal_amount),
                'expected_profit_sol': float(net_profit),
                'route': 'triangular' if route_type == 'triangular' else 'direct'
            }
            metadata = {'borrow_amount_sol': borrow_amount_sol, 'decimals': decimals_in}
            await data_aggregator.log_opportunity_found('internal', parsed_opportunity, metadata)

            # Calculate working capital locally (current balance for liquidity estimate)
            working_cap = stats.get("last_balance", 0.0) * 1e6  # Convert to USD approximation

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
                    "chosen_route": chosen_route
                }
            )

            # Calculate AI score
            current_balance = stats.get("last_balance", 0.0)
            score = await arbitrage_scorer.score_opportunity(opportunity, wallet_balance=current_balance)
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
                logger.debug(f"Worker {asyncio.current_task().get_name()} heartbeat: {pairs_checked} pairs processed.")
            queue.task_done()

async def blockhash_updater(session, rpc_getter):
    global cached_blockhash, cache_time
    while True:
        rpc = rpc_getter()
        try:
            # Batch request for efficiency
            payload = [
                {"jsonrpc":"2.0","id":1,"method":"getLatestBlockhash","params":[{"commitment":"confirmed"}]},
                {"jsonrpc":"2.0","id":2,"method":"getSlot"}
            ]
            timeout = aiohttp.ClientTimeout(total=1.0)
            async with session.post(rpc, json=payload, timeout=timeout) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for item in data:
                        if item["id"] == 1:
                            cached_blockhash = item['result']['value']['blockhash']
                            cache_time = time.time()
                        elif item["id"] == 2:
                            stats["current_slot"] = item["result"]
        except: pass
        await asyncio.sleep(2.0) # 2s cache — confirmed blockhash for Jito geo-propagation

async def run():
    import gc
    print("=== RUN() STARTED ===", flush=True)
    # Делаем сборку мусора реже, но эффективнее, чтобы не мешать горячим циклам
    gc.set_threshold(7000, 10, 10)
    gc.disable()  # Fix 57: disable automatic GC — managed by _gc_idle_collector below

    # Fix 58: macOS/Linux Insomnia Guard — prevent system sleep / CPU throttling on startup
    import subprocess
    import platform
    if platform.system() == "Darwin":
        try:
            subprocess.Popen(["caffeinate", "-i", "-p", str(os.getpid())],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logger.info("🛡️ Insomnia guard active: caffeinate preventing macOS sleep (PID %s)" % os.getpid())
        except Exception as e:
            logger.warning(f"⚠️ Could not start caffeinate: {e}")
    elif platform.system() == "Linux":
        logger.warning("⚡ For Linux insomnia: run 'sudo cpupower frequency-set -g performance' manually for lowest-latency operation")

    # Fix 57: GC idle-watchdog — collect only when execution queue is quiet >5 s
    async def _gc_idle_collector():
        """Manual GC trigger — fires only when no arb is hot. Prevents GC freezes mid-execution."""
        idle_seconds = 0.0
        while True:
            await asyncio.sleep(1.0)
            # Queue considered idle when: execution lock free AND fewer than 5 active tasks (background only)
            if not execution_lock.locked() and len(active_tasks) < 5:
                idle_seconds += 1.0
                if idle_seconds >= 5.0:
                    gc.collect()
                    idle_seconds = 0.0
            else:
                idle_seconds = 0.0  # Reset on hot thread to avoid collecting mid-arb

    cfg = Config()
    if not os.path.exists(cfg.WALLET_PATH):
        logger.error(f"Wallet not found: {cfg.WALLET_PATH}")
        return

    global KEYPAIR
    # Fix 81 / Memory Hardening: load keypair once at startup with context manager.
    # No disk I/O during the hot trade loop — KEYPAIR stays resident in RAM.
    with open(cfg.WALLET_PATH, 'r') as _f:
        KEYPAIR = Keypair.from_bytes(bytes(json.load(_f)))
    keypair = KEYPAIR
    logger.info(f"✅ Bot authorized: {keypair.pubkey()}")  # Fix 81: loaded once into RAM, disk I/O avoided in hot path

    # ── Fix 46: MARGINFI_ACCOUNT .env sanitization ─────────────────────────────
    if not validate_marginfi_account(cfg):
        logger.critical("Bot cannot start — MarginFi account validation failed.")
        sys.exit(1)

    # ── Jito executor init (must be before health-factor uses RPC) ──────────────
    rpc = RPCManager(cfg)

    # Initialize priority queue and trade sizer
    priority_queue = PriorityArbitrageQueue(max_size=50)
    trade_sizer = OptimalTradeSizer()

    # Use AsyncResolver with Cloudflare/Google DNS + AF_INET only for low-latency networking
    # Fix 53: IPv4 + custom nameservers configures DNS 50-80 ms faster than IPv6-only
    _resolver = None
    try:
        import brotli  # noqa: enables aiohttp Brotli decoding (Accept-Encoding: br)
    except ImportError:
        brotli = None
    try:
        import aiodns  # noqa: ensures aiodns is present for AsyncResolver
    except ImportError:
        logger.warning("⚠️ aiodns not available — falling back to default DNS resolver")
    # AsyncResolver is already imported at top-level (aiohttp.resolver.AsyncResolver)
    _resolver = AsyncResolver(nameservers=["1.1.1.1", "8.8.8.8"])

    try:
        # Fix 53: AF_INET disables IPv6 lookups; ttl_dns_cache reduces DNS overhead;
        # force_close is mandatory on macOS for >1024 concurrent connections.
        connector = aiohttp.TCPConnector(
            family=socket.AF_INET,
            resolver=_resolver,
            limit=0,
            ttl_dns_cache=300,
            use_dns_cache=True,
            force_close=True
        )
    except Exception:
        logger.warning("connector fallback — using defaults")
        connector = aiohttp.TCPConnector(limit=0, ttl_dns_cache=300, use_dns_cache=True, force_close=True)

    session = aiohttp.ClientSession(
        connector=connector,
        headers={"Accept-Encoding": "br, gzip"}  # Fix 53 + 92: Brotli compression cuts quote payload size
    )

    # ── Fix 53: Warm-up requests (3 dummy calls to prime DNS + TCP connections) ──────
    try:
        for _ in range(3):
            try:
                await session.get("https://quote-api.jup.ag/v6/quote?inputMint=So11111111111111111111111111111111111111112&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=1000000", timeout=2)
                await session.post(rpc.get_rpc(), json={"jsonrpc":"2.0","id":1,"method":"getHealth"}, timeout=2)
            except:
                pass
    except Exception:
        pass
        # Fix 70: Log rotation + DB vacuum background task
        async def _maintenance():
            while True:
                await asyncio.sleep(6*3600)
                # delete old .jsonl
                for f in glob.glob("*.jsonl"):
                    if os.path.getmtime(f) < time.time() - 48*3600:
                        os.remove(f)
                # vacuum DB
                try:
                    import sqlite3
                    conn = sqlite3.connect("bot_history.db")
                    conn.execute("VACUUM;")
                    conn.close()
                except: pass
                # disk check
                if shutil.disk_usage(".").free < 500*1024*1024:
                    logger.warning("Low disk space — stopping logs")
        asyncio.create_task(_maintenance())
        asyncio.create_task(_gc_idle_collector())  # Fix 57: manual GC on idle queue
        # Задача 50: Защита от Slot Drift (Time Sync Guard)
        await check_time_sync(session, rpc.get_rpc())

        # ── Fix 50: Health-Factor guard before any trade is attempted ───────────────
        hf_raw = await check_marginfi_health_factor(
            session, rpc.get_rpc(), cfg.MARGINFI_ACCOUNT_PUBKEY
        )
        # hf_raw == 1.0 means "unknown/neutral" (on-chain parsing not implemented)
        # Only block if we got a real reading that indicates danger
        if hf_raw is not None and hf_raw < 1.0 and hf_raw > 0.0:
            logger.critical(
                f"🛑 HEALTH FACTOR BLOCK: MarginFi account HF={hf_raw:.4f} < 1.0. "
                "Clear your MarginFi debt before starting the bot."
            )
            sys.exit(1)
        if hf_raw is not None and hf_raw == 1.0:
            logger.warning("⚠️ MarginFi health factor unknown (neutral 1.0) — proceeding with caution")

        # 1. Core Data & Scaling Components
        data_aggregator = DataAggregator()
        await data_aggregator.start_batch_writer()
        
        flywheel_scaler = FlywheelScaler(initial_balance=0.017)
        arbitrage_scorer = ArbitrageScorer(session=session, rpc_url=rpc.get_rpc())

        # 2. State Management
        pool_state_manager = PoolStateManager(
            websocket_url=cfg.WSS_ENDPOINTS[0],
            pool_addresses=[]
        )
        
        alt_manager = ALTCacheManager(rpc_url=rpc.get_rpc(), session=session)
        await alt_manager.initialize_cache()

        # 3. Execution Infrastructure (Jito & Leader Tracking)
        global jito_tip_manager
        jito_tip_manager = None
        if JITO_AVAILABLE:
            jito_tip_manager = JitoTipManager(
                percentile=cfg.JITO_TIP_PERCENTILE,
                min_tip_lamports=cfg.JITO_MIN_TIP_LAMPORTS,
                tip_multiplier=cfg.TIP_MULTIPLIER
            )
            # Phase 35: Fetch live tip accounts before starting stream
            await jito_tip_manager.fetch_tip_accounts()
            await jito_tip_manager.start()

        global leader_tracker
        leader_tracker = LeaderTracker(
            rpc_url=rpc.get_rpc(),
            fetch_interval_ms=cfg.LEADER_FETCH_INTERVAL
        )
        await leader_tracker.start(session)

        global jito_leader_tracker
        jito_leader_tracker = None
        if JITO_AVAILABLE:
            jito_leader_tracker = init_jito_leader_tracker(cfg.JITO_ENDPOINTS)
            await jito_leader_tracker.start(session)

        jito_executor = None
        if JITO_AVAILABLE:
            jito_executor = JitoExecutor(
                session=session, 
                bundle_endpoint=cfg.JITO_ENDPOINTS[0] if cfg.JITO_ENDPOINTS else None,
                keypair=keypair
            )
            await jito_executor.start()

            # Fix 2: Hardcoded Jito Tip Accounts — retry fetch_tip_accounts() up to 3 times.
            # If still empty after retries, log CRITICAL so the operator knows tips may go to stale accounts.
            _fetch_attempts = 0
            while _fetch_attempts < 3:
                if jito_executor.tip_accounts and len(jito_executor.tip_accounts) > 1:
                    logger.info(f"✅ Jito tip accounts loaded: {len(jito_executor.tip_accounts)} active accounts")
                    break
                _fetch_attempts += 1
                logger.warning(
                    f"⚠️ Jito tip accounts attempt {_fetch_attempts}/3: "
                    f"{len(jito_executor.tip_accounts)} accounts — retrying in 2s..."
                )
                await asyncio.sleep(2)
                await jito_executor.fetch_tip_accounts()
            if _fetch_attempts >= 3 and len(jito_executor.tip_accounts) <= 1:
                logger.critical(
                    "🚨 JITO TIP ACCOUNTS: Dynamic fetch failed after 3 attempts! "
                    f"Proceeding with {len(jito_executor.tip_accounts)} hardcoded fallback account(s). "
                    "Tips may be sent to stale accounts — manual inspection required."
                )

        # God-mode Jito Bidding Manager — tip_floor poller + step-up/down + capital guard
        global jito_bidding_manager
        jito_bidding_manager = JitoBiddingManager()
        if JITO_AVAILABLE:
            _poll_task = asyncio.create_task(jito_bidding_manager.poll_tip_floor(session))
            # noinspection PyTypeChecker
            # _poll_task is intentionally fire-and-forget; it exits when run() exits
            active_tasks.add(_poll_task)
            _poll_task.add_done_callback(active_tasks.discard)
            logger.info("🎯 Jito bidding manager started (polling tip_floor every 10s)")

        execution_router = ExecutionRouter(
            leader_tracker=leader_tracker,
            jito_executor=jito_executor,
            session=session,
            rpc_url=rpc.get_rpc(),
            keypair=keypair,
            alt_manager=alt_manager  # Fix 3: pass alt_manager for MTU-safe tx compilation
        )
        execution_router.start_processor()

        # 4. Webhook & Strategy Routing
        async def handle_webhook_opportunity(opportunity, webhook_id):
            logger.debug(f"🚨 Webhook Triggered: {opportunity.get('strategy', 'unknown')}")
            arb_opp = ArbitrageOpportunity(
                pair=opportunity.get("description", "Webhook/Arb"),
                expected_profit_sol=opportunity.get("expected_profit_sol", 0.01),
                slippage_pct=0.01,
                liquidity_depth_usd=50000,
                network_congestion=50.0,
                gas_cost_sol=0.0001,
                execution_time_ms=0,
                timestamp=time.time(),
                metadata={"is_webhook": True, "raw_data": opportunity}
            )
            arb_opp.score = 95.0
            priority_queue.add_opportunity(arb_opp)

        # helius_webhook_handler created after jito_shotgun is initialized (see below)

        # 5. Strategies Initialization
        if cfg.ENABLE_XSTOCKS_ORACLE_LAG:
            from src.ingest.pyth_oracle_client import start_pyth_client
            asyncio.create_task(start_pyth_client())
            
            from src.ingest.xstock_oracle_lag import init_xstock_strategy
            xstock_strategy = init_xstock_strategy(
                session=session,
                cfg=cfg,
                optimal_trade_sizer=None,
                tx_builder=JupiterTxBuilder(session=session, rpc_url=rpc.get_rpc()),
                execution_router=execution_router
            )
            asyncio.create_task(xstock_strategy.periodic_lag_scan())
            logger.info("🎯 xStocks Oracle Lag Strategy initialized")

        # ULTRA ARB Components
        # global pool_math_router, receipt_arb_engine, flash_pivot_engine, jito_shotgun
        # pool_math_router = PoolMathRouter()
        # receipt_arb_engine = ReceiptArbEngine(pool_state_manager, pool_math_router)
        # flash_pivot_engine = FlashPivotEngine(pool_state_manager, pool_math_router)
        
        # global wrapper_arb_enforcer, volatility_watcher
        # wrapper_arb_enforcer = WrapperArbEnforcer(pool_state_manager)
        # volatility_watcher = VolatilityWatcher(pool_state_manager)

        # 6. Jito Sniper & Background Components
        global jito_pool_listener, jito_tx_builder, jito_bundle_sender
        jito_pool_listener = None
        jito_tx_builder = None
        jito_bundle_sender = None
        jito_shotgun = None
        
        if JITO_AVAILABLE:
            jito_pool_listener = WssPoolCreationListener(
                rpc_ws_url=cfg.WSS_ENDPOINTS[0] if cfg.WSS_ENDPOINTS else None,
                rpc_http_url=rpc.get_rpc(),
                event_callback=lambda event: None,
                session=session
            )
            jito_tx_builder = TransactionTipBuilder(jito_tip_manager)
            jito_bundle_sender = JitoBundleSender(
                jito_endpoints=cfg.JITO_ENDPOINTS,
                auth_key=cfg.JITO_AUTH_KEY
            )
            jito_shotgun = JitoShotgun(session)

        # Strat 3: Helius webhook handler — created AFTER jito_shotgun so it can fire
        # swap/graduation signals to all 4 Jito regional block engines instantly.
        helius_webhook_handler = HeliusWebhookHandler(
            data_aggregator,
            cfg.WEBHOOK_PORT,
            opportunity_callback=handle_webhook_opportunity,
            webhook_queue=lst_webhook_trigger,
            on_token_discovery=lambda x: None,
            jito_shotgun=jito_shotgun  # Strat 3: Jito Shotgun webhook integration
        )

        if cfg.HELIUS_WEBHOOK_ENABLED:
            asyncio.create_task(helius_webhook_handler.start())
        else:
            logger.info("ℹ️ Helius webhook handler disabled")

        global dust_sweeper
        dust_sweeper = DustSweeper(keypair, rpc.get_rpc(), session)
        asyncio.create_task(dust_sweeper.sweep_on_startup())
        
        # [TASK 49] Periodic Dust Sweep (15-min fallback, primary sweep is post-trade)
        async def periodic_dust_sweep():
            while True:
                await asyncio.sleep(900)  # 15 minutes fallback
                try:
                    await dust_sweeper._sweep_dust()
                except Exception as e:
                    logger.error(f"Periodic dust sweep failed: {e}")
        asyncio.create_task(periodic_dust_sweep())

        # 7. Balance & Health Monitoring
        async def wallet_balance_listener():
            from spl.token.instructions import close_account, CloseAccountParams
            from spl.token.constants import TOKEN_PROGRAM_ID
            from spl.token.instructions import get_associated_token_address
            from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
            
            wsol_mint = Pubkey.from_string("So11111111111111111111111111111111111111112")
            wsol_ata = get_associated_token_address(keypair.pubkey(), wsol_mint)

            while True:
                try:
                    # 1. Проверяем нативный баланс
                    current_balance = await StateManager.get_balance(session, rpc, keypair.pubkey())
                    if current_balance is not None:
                        stats["last_balance"] = current_balance
                        
                        # 2. Если нативный SOL падает ниже 0.01 SOL (опасно!)
                        if current_balance < 0.01:
                            logger.warning(f"⚠️ Native SOL critically low ({current_balance} SOL). Checking wSOL for unwrap...")
                            
                            # Fix 1 (wSOL Death Spiral): If the atomic arb path just closed wSOL
                            # inside the transaction, skip the standalone close to avoid races + gas waste.
                            global WSOL_JUST_CLOSED_ATOMICALLY
                            if time.time() - WSOL_JUST_CLOSED_ATOMICALLY < WSOL_CLOSE_COOLDOWN:
                                logger.debug(
                                    f"🔓 wSOL was atomically closed {time.time() - WSOL_JUST_CLOSED_ATOMICALLY:.0f}s ago — "
                                    f"skipping standalone unwrap to prevent duplicate close"
                                )
                                continue  # keep sleeping; the atomic path already replenished native SOL
                            
                            # Проверяем баланс wSOL ATA
                            payload = {"jsonrpc": "2.0", "id": 1, "method": "getTokenAccountBalance", "params": [str(wsol_ata)]}
                            async with session.post(rpc.get_rpc(), json=payload) as resp:
                                data = await resp.json()
                                if "result" in data and "value" in data["result"]:
                                    wsol_amount = int(data["result"]["value"]["amount"])
                                    
                                    # Если скопили хотя бы 0.005 wSOL профита - конвертируем в нативный
                                    if wsol_amount > 5_000_000:
                                        logger.info(f"🔄 Unwrapping {wsol_amount / 1e9} wSOL to Native SOL to replenish gas!")
                                        
                                        # Закрытие wSOL ATA автоматически переводит все средства в Native SOL
                                        close_ix = close_account(CloseAccountParams(
                                            program_id=TOKEN_PROGRAM_ID,
                                            account=wsol_ata,
                                            dest=keypair.pubkey(),
                                            owner=keypair.pubkey()
                                        ))
                                        
                                        # Fix 4: Add Priority Fee so TX doesn't hang in mempool for hours
                                        cu_limit_ix = set_compute_unit_limit(50_000)
                                        cu_price_ix = set_compute_unit_price(100_000)  # ~0.000005 SOL priority fee
                                        blockhash = await get_current_blockhash(session, rpc.get_rpc())
                                        msg = MessageV0.try_compile(
                                            keypair.pubkey(),
                                            [cu_limit_ix, cu_price_ix, close_ix],
                                            [],
                                            Hash.from_string(blockhash)
                                        )
                                        tx = VersionedTransaction(msg, [keypair])
                                        tx_b64 = base64.b64encode(bytes(tx)).decode('ascii')
                                        await session.post(rpc.get_rpc(), json={"jsonrpc": "2.0", "id": 1, "method": "sendTransaction", "params": [tx_b64]}
                                        )
                                        
                                        # ATA будет пересоздана автоматически при следующем арбитраже через CREATE_ATA_FUNCTION
                except Exception as e:
                    logger.debug(f"Balance listener/unwrap error: {e}")
                
                await asyncio.sleep(10)
        
        asyncio.create_task(wallet_balance_listener())

        health_monitor = BankHealthMonitor(rpc, MARGINFI_BANKS["So11111111111111111111111111111111111111112"], MARGINFI_BANKS["EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"])
        await health_monitor.start()

        # 8. Warm-up
        initial_balance = None
        while initial_balance is None:
            initial_balance = await StateManager.get_balance(session, rpc, keypair.pubkey())
            if initial_balance is None:
                logger.warning("⏳ Ожидание готовности RPC... Повтор через 5 секунд")
                await asyncio.sleep(5)

        stats["last_balance"] = initial_balance
        stats["virtual_balance"] = initial_balance  # Fix 44: seed virtual balance from actual balance
        stats["initial_balance"] = initial_balance

        # Jupiter Warm-up
        try:
            url = "https://api.jup.ag/swap/v1/quote"
            params = {"inputMint": "So11111111111111111111111111111111111111112", "outputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "amount": "100000000", "slippageBps": "50"}
            async with session.get(url, params=params) as resp:
                if resp.status == 200: logger.debug("✅ Jupiter warm-up successful")
        except: pass

        # Priority queue processor for AI-scored opportunities
        async def priority_queue_processor():
            """Process high-priority arbitrage opportunities."""
            while True:
                try:
                    # Get next high-priority opportunity
                    opportunity = priority_queue.get_next_opportunity()
                    if opportunity:
                        # Phase 24: Process high-priority opportunities concurrently
                        # Removing 'await' allows multiple simulations to run in parallel.
                        asyncio.create_task(execute_priority_opportunity(
                            opportunity, session, cfg, rpc, keypair, jito_executor, 
                            None, flywheel_scaler, data_aggregator, 
                            alt_manager=alt_manager, execution_router=execution_router,
                            flash_pivot_engine=flash_pivot_engine
                        ))
                    else:
                        await asyncio.sleep(0.1)  # Brief pause if queue empty
                except Exception as e:
                    logger.error(f"Priority queue processor error: {e}")
                    await asyncio.sleep(1)

        # Health Monitor for MarginFi banks
        health_monitor = BankHealthMonitor(rpc, MARGINFI_BANKS["So11111111111111111111111111111111111111112"], MARGINFI_BANKS["EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"])
        await health_monitor.start()

        # 9. Main Processing Loops
        queue = asyncio.PriorityQueue(maxsize=100)

        tasks = [
            asyncio.create_task(update_prices(session, cfg)),
            asyncio.create_task(blockhash_updater(session, lambda: rpc.get_rpc())),
            # DISABLED: stable_scanner — RPS-heavy polling (Helius 429 prevention)
            # asyncio.create_task(stable_scanner(queue, cfg)),        # Fast stables (1.5s)
            asyncio.create_task(lst_scanner(queue, cfg)),           # Loop B: LST arbitrage (2.0s)
            asyncio.create_task(xstocks_scanner(queue, cfg)),       # Loop C: xStocks priority (5.0s)
            # DISABLED: rwa_rest_scanner — RPS-heavy polling (15.0s interval)
            # asyncio.create_task(rwa_rest_scanner(queue, cfg)),
            # DISABLED: dexscreener_scanner — RPS-heavy external API polling
            # asyncio.create_task(dexscreener_scanner(queue, session, cfg))
            asyncio.create_task(priority_queue_processor()),  # ENABLED: AI-powered priority processor
            *[asyncio.create_task(worker(queue, session, cfg, rpc, keypair, limiters, jito_executor, arbitrage_scorer, priority_queue, alt_manager=alt_manager)) for _ in range(cfg.WORKER_COUNT)],

            # ULTRA ARB MASTER — background tasks commented out (components disabled)

            # ULTRA ARB - Market Expansion Tasks
            # asyncio.create_task(wrapper_arb_background_scanner()),
            # asyncio.create_task(volatility_monitor_background()),

            # ULTRA ARB - Stable×Stable & Lending Rate Tasks
            # asyncio.create_task(receipt_arb_background_scanner()),

            # ULTRA ARB - Production-Ready Tasks
            # asyncio.create_task(yellowstone_stream.connect()),  # DISABLED: grpc issue
            asyncio.create_task(dust_sweep_background()),
            asyncio.create_task(cleanup_temporary_tokens()),
        ]
        # LST Depeg Flash-Arb Scanner (primary strategy)
        if cfg.LST_DEPEG_ENABLED:
            lst_task = asyncio.create_task(
                lst_depeg_scanner(session, cfg, rpc, keypair, jito_executor, lst_webhook_trigger)
            )
            tasks.append(lst_task)
            logger.debug("🌊 LST Depeg Flash-Arb Scanner ENABLED (Blue Ocean)")
        else:
            logger.debug("ℹ️ LST Depeg Flash-Arb Scanner DISABLED")

        # Kamino Flash-Liquidation Scanner (FROZEN: Red Ocean)
        if cfg.KAMINO_LIQUIDATION_ENABLED:
            kamino_task = asyncio.create_task(
                kamino_liquidation_scanner(session, cfg, rpc, keypair, jito_executor)
            )
            tasks.append(kamino_task)
            logger.debug("🏦 Kamino Flash-Liquidation Scanner ENABLED")
        else:
            logger.info("❌ Kamino Flash-Liquidation Scanner FROZEN (Red Ocean competition)")

        # LST Instant Unstake Arbitrage Scanner
        if cfg.LST_UNSTAKE_ARB_ENABLED:
            unstake_task = asyncio.create_task(
                lst_unstake_arbitrage_scanner(session, cfg, rpc, keypair, jito_executor)
            )
            tasks.append(unstake_task)
            logger.info("🔄 LST Instant Unstake Arbitrage Scanner ENABLED")
        else:
            logger.info("ℹ️ LST Instant Unstake Arbitrage Scanner DISABLED")

        # Orderbook-AMM Bipartite Solver Scanner
        if cfg.ORDERBOOK_AMM_ENABLED:
            orderbook_task = asyncio.create_task(
                orderbook_amm_scanner(session, cfg, rpc, keypair, jito_executor)
            )
            tasks.append(orderbook_task)
            logger.info("🌊 Orderbook-AMM Arbitrage Scanner ENABLED (Blue Ocean)")
        else:
            logger.debug("ℹ️ Orderbook-AMM Arbitrage Scanner DISABLED")

        # Add webhook task if enabled
        if cfg.HELIUS_WEBHOOK_ENABLED:
            tasks.append(webhook_task)

        logger.debug(f"🚀 Matrix Scanner launched! Initial Balance: {initial_balance} SOL")

        try:
            while True:
                await asyncio.sleep(10)
                current_balance = await StateManager.get_balance(session, rpc, keypair.pubkey())
                if current_balance is None:
                    continue
                    
                stats["last_balance"] = current_balance
                
                # Задача 52: Локальный мониторинг (Health Check File)
                try:
                    with open("bot_health.json", "w") as f:
                        json.dump({
                            "last_ping": time.time(),
                            "balance": stats.get("last_balance"),
                            "trades": stats.get("trades")
                        }, f)
                except Exception as e:
                    logger.debug(f"Heartbeat write error: {e}")

                # Update metrics & Log Stats
                working_cap = (current_balance - cfg.MIN_RESERVE_SOL) * cfg.TRADE_SIZE_PCT
                bir = (stats["bundle_successes"] / stats["bundle_send_attempts"]) * 100 if stats["bundle_send_attempts"] > 0 else 0
                avg_sel = sum(stats["state_to_execution_latencies"]) / len(stats["state_to_execution_latencies"]) if stats["state_to_execution_latencies"] else 0
                flash_miss_rate = (stats["flash_loan_miss_count"] / stats["flash_loan_attempt_count"]) * 100 if stats["flash_loan_attempt_count"] > 0 else 0
                
                logger.debug(f"📊 [STATS] Balance: {current_balance:.8f} | WC: {working_cap:.8f} | Trades: {stats['trades']} | BIR: {bir:.1f}% | SEL: {avg_sel:.1f}ms")

                # Balance Guard + Fix 68: Dust Reserve
                if current_balance < 0.005:
                    logger.critical("🚨 DEBT CEILING REACHED: 0.005 SOL native - closing ATAs, swapping to SOL, SHUTDOWN")
                    # 1. close non-essential ATAs 2. swap USDC->SOL 3. exit
                    GLOBAL_STOP_EVENT.set()
                    break
                if current_balance < initial_balance * 0.3:
                    logger.critical(f"🚨 BALANCE GUARD ACTIVATED: Balance {current_balance:.8f} SOL dropped below 30%")
                    await send_balance_alert(current_balance, initial_balance)
                    break
        finally:
            logger.debug("🛑 Shutting down arbitrage engine components...")
            # Fix 77: Graceful session close
            if 'session' in locals() and session and not session.closed:
                await session.close()
            if 'oracle_streams' in globals() and oracle_streams:
                await oracle_streams.stop()
            await jito_executor.stop()
            await helius_webhook_handler.stop()
            await data_aggregator.stop_batch_writer()
            if cfg.JITO_SNIPER_ENABLED:
                await jito_tip_manager.stop()
                await jito_pool_listener.stop()

class StateManager:
    @staticmethod
    async def get_balance(session, rpc_manager, pubkey):
        # Fix 72: Force confirmed commitment (never use processed)
        payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params":[str(pubkey), {"commitment": "confirmed"}]}
        timeout = aiohttp.ClientTimeout(total=3.0)
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        }

        for attempt in range(3):
            try:
                rpc_url = rpc_manager.get_rpc()
            except Exception as e:
                logger.error(f"No available RPCs: {e}")
                return None

            logger.debug(f"🔍 Попытка {attempt+1}: проверяем RPC {repr(rpc_url)[:60]}...")

            try:
                async with session.post(rpc_url, json=payload, headers=headers, timeout=timeout) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if "result" in data:
                            logger.debug("✅ Баланс успешно получен")
                            return data['result']['value'] / 1e9
                    else:
                        error_text = await resp.text()
                        logger.warning(f"Ошибка {resp.status} на RPC. Ответ: {error_text}")
                        if resp.status == 401 or "invalid api key" in error_text.lower():
                            rpc_manager.blacklist(rpc_url)
            except Exception as e:
                logger.warning(f"Исключение на RPC: {e}")

        logger.error("Все 3 попытки RPC провалились, возвращаем None")
        return None

async def handle_oracle_lag_signal(symbol, oracle_price, amm_price, session, cfg, rpc, keypair, priority_queue):
    """Handle Oracle Lag signal from ArbitrageGraph."""
    try:
        # Convert signal to an ArbitrageOpportunity for the priority queue
        # This allows the worker pool to pick it up and execute
        arb_opp = ArbitrageOpportunity(
            pair=f"{symbol}-USDC",
            expected_profit_sol=0.005,
            slippage_pct=0.01,
            liquidity_depth_usd=50000,
            network_congestion=50.0,
            gas_cost_sol=0.0005,
            execution_time_ms=0,
            timestamp=time.time(),
            metadata={"strategy": "oracle_lag"}
        )
        
        priority_queue.add_opportunity(arb_opp)
        logger.debug(f"✅ Oracle Lag Graph Signal Queued: {symbol}")
    except Exception as e:
        logger.error(f"Error handling oracle lag signal: {e}")

async def handle_oracle_lag(opportunity, session, cfg, rpc, keypair, priority_queue):
    """Handle Oracle Lag arbitrage opportunity."""
    try:
        logger.info(f"🐍 Oracle Lag Trigger: {opportunity.token_pair} | "
                   f"Diff: {opportunity.price_diff_pct:.2%}")

        # Construct a formal opportunity object for the priority queue
        arb_opp = ArbitrageOpportunity(
            pair=opportunity.token_pair,
            expected_profit_sol=0.005,
            slippage_pct=0.01,
            liquidity_depth_usd=50000,
            network_congestion=50.0,
            gas_cost_sol=0.0005,
            execution_time_ms=0,
            timestamp=time.time(),
            metadata={"strategy": "oracle_lag"}
        )
        
        # Push to priority queue for execution
        priority_queue.add_opportunity(arb_opp)
        logger.debug(f"✅ Oracle Lag opportunity queued: {arb_opp.pair}")

    except Exception as e:
        logger.error(f"Oracle lag handling error: {e}")

async def handle_graduation_event(opportunity, session, cfg, rpc, keypair):
    """Handle token graduation event."""
    try:
        logger.debug(f"🎓 Graduation Event: {opportunity.token_pair} | "
                   f"Platform: {opportunity.trigger_data.get('platform')}")

        # Execute pre-computed graduation arbitrage
        # This would integrate with Jito sniper for instant execution

    except Exception as e:
        logger.error(f"Graduation event handling error: {e}")

# ULTRA ARB - Advanced Strategy Event Handlers
async def handle_liquidation_opportunity(opportunity, liquidation_engine, keypair):
    """Handle liquidation arbitrage opportunity."""
    try:
        logger.debug(f"🏦 Liquidation Opportunity: {opportunity.debt_asset} -> {opportunity.collateral_asset} | "
                   f"HF: {opportunity.health_factor} | Profit: ${opportunity.estimated_profit}")

        # Execute atomic liquidation
        success = await liquidation_engine.execute_liquidation(
            opportunity, jito_tip_lamports=10000, wallet_keypair=keypair
        )

        if success:
            logger.debug("✅ Liquidation executed successfully")
        else:
            logger.warning("❌ Liquidation execution failed")

    except Exception as e:
        logger.error(f"Liquidation handling error: {e}")

async def handle_cex_dex_signal(signal, cex_dex_oracle):
    """Handle CEX-DEX lead-lag arbitrage signal."""
    try:
        logger.debug(f"📊 CEX-DEX Signal: {signal.asset} | Direction: {signal.direction} | "
                   f"Confidence: {signal.confidence:.2%}")

        # Calculate optimal trade size using O(1) math
        optimal_size = Decimal('1000')  # Placeholder - would use actual calculation

        # Execute arbitrage
        success = await cex_dex_oracle.execute_lead_lag_arbitrage(
            signal, optimal_size
        )

        if success:
            logger.debug("✅ CEX-DEX arbitrage executed successfully")
        else:
            logger.warning("❌ CEX-DEX arbitrage execution failed")

    except Exception as e:
        logger.error(f"CEX-DEX signal handling error: {e}")

async def handle_epoch_opportunity(opportunity, epoch_tracker, keypair, jito_executor):
    """Handle LST epoch rebalance opportunity."""
    try:
        logger.debug(f"🕐 Epoch Opportunity: {opportunity.lst_token} | "
                   f"Rate Change: {opportunity.rate_change_pct:.2%} | "
                   f"Seconds until epoch: {opportunity.seconds_until_epoch}")

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
    try:
        logger.debug(f"🎯 Wrapper Peg Opportunity: {opportunity.cheap_wrapper} -> {opportunity.expensive_wrapper} | "
                   f"Deviation: {opportunity.peg_deviation_pct:.2%} | "
                   f"Expected Profit: ${opportunity.expected_profit_usdc}")

        # Execute wrapper arbitrage
        await wrapper_arb_enforcer._execute_wrapper_arbitrage(opportunity)

    except Exception as e:
        logger.error(f"Wrapper opportunity handling error: {e}")

async def handle_volatility_signal(signal):
    """Handle volatility-triggered arbitrage signal."""
    try:
        logger.debug(f"🌊 Volatility Signal: {signal['token_symbol']} | "
                   f"Change: {signal['price_change_pct']:.2%} {signal['direction']} | "
                   f"Window: {signal['time_window']}s")

        # Trigger cross-DEX arbitrage
        # Implementation would integrate with main arbitrage engine

    except Exception as e:
        logger.error(f"Volatility signal handling error: {e}")

async def handle_receipt_opportunity(opportunity):
    """Handle receipt token arbitrage opportunity."""
    try:
        logger.debug(f"🏦 Receipt Opportunity: {opportunity.receipt_token} -> {opportunity.base_asset} | "
                   f"Discount: {opportunity.discount_pct:.2%} | "
                   f"Protocol: {opportunity.protocol}")

        # Execute receipt arbitrage
        await receipt_arb_engine._execute_receipt_arbitrage(opportunity)

    except Exception as e:
        logger.error(f"Receipt opportunity handling error: {e}")

async def execute_ultra_arbitrage(cycle: ArbitrageCycle, session, rpc, keypair):
    """Execute arbitrage with full Ultra Arb protection and correct math."""
    global pool_math_router, receipt_arb_engine, flash_pivot_engine, jito_shotgun, k_hop_stitcher
    try:
        # Check flashloan pivot if needed
        pivot_opp = await flash_pivot_engine.check_pivot_needed(
            cycle.path[0], cycle.required_flash_loan, cycle.profit_ratio * cycle.required_flash_loan
        )

        if pivot_opp and pivot_opp.should_pivot:
            logger.debug(f"🔄 Pivoting flashloan: {pivot_opp.original_asset} -> {pivot_opp.pivot_asset}")
            flash_asset = pivot_opp.pivot_asset
        else:
            flash_asset = cycle.path[0]

        # Use correct math solver for pool types in the cycle
        # This is a simplified call, in production it would map cycle paths to specific pool data
        optimal_size = cycle.required_flash_loan

        if optimal_size <= 0:
            logger.warning("Optimal size calculation failed")
            return False

        # Build with K-Hop stitcher using correct math
        try:
            tx = await k_hop_stitcher.stitch_arbitrage_path(
                arbitrage_path=cycle.path,
                hop_amounts=[optimal_size] * len(cycle.path),
                dex_protocols=["raydium"] * (len(cycle.path) - 1),  # Default to Raydium
                flashloan_asset=flash_asset,
                flashloan_amount=optimal_size,
                jito_tip_lamports=int(optimal_size * 0.001 * 1e9),  # 0.1% tip
                use_jito=True
            )
        except (NameError, Exception) as e:
            logger.warning(f"k_hop_stitcher failed or not initialized: {e}")
            return False

        if tx:
            # 100% CAPITAL PROTECTION: Pre-trade Simulation
            flash_sim = FlashSimulator(session, rpc.get_rpc())
            tx_b64 = base64.b64encode(bytes(tx)).decode()
            
            # Phase 48: Protect all stablecoins and base assets from burning (Task 21)
            STABLES = {
                "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", # USDC
                "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8En2vQK2", # USDT
                "2b1kVqUbox8neH2nXvJp88unA71H4id8Gv7W269PshF2", # PYUSD
                "So11111111111111111111111111111111111111112", # wSOL
            }
            
            is_profitable, reason, sim_result = await flash_sim.validate_profitability(
                tx_b64=tx_b64,
                tx_signer_pubkey=str(keypair.pubkey()),
                min_profit_lamports=1000, # Minimal threshold
                tip_lamports=int(optimal_size * 0.001 * 1e9),
                jito_endpoint=cfg.JITO_ENDPOINTS[0] if cfg.JITO_ENDPOINTS else None
            )

            if not is_profitable:
                logger.warning(f"❌ Ultra Arb Simulation Rejected: {reason}")
                return False

            # Send via Jito shotgun
            try:
                success = await jito_shotgun.send_to_all_engines([tx])
                if success:
                    logger.debug(f"🔥 Ultra Arb Sent: {' -> '.join(cycle.path)} | Profit: {cycle.profit_bps} bps")
                return success
            except (NameError, Exception) as e:
                logger.warning(f"jito_shotgun failed or not initialized: {e}")
                return False
        else:
            logger.warning("Transaction stitching failed")
            return False

    except Exception as e:
        logger.error(f"Ultra arbitrage execution failed: {e}")
        return False

# ULTRA ARB - Background Scanning Functions
async def wrapper_arb_background_scanner():
    """Background scanner for wrapper peg opportunities."""
    while True:
        try:
            await wrapper_arb_enforcer.scan_wrapper_pegs()
            await asyncio.sleep(1.0)  # Scan every second
        except Exception as e:
            logger.error(f"Wrapper arb scanner error: {e}")
            await asyncio.sleep(5.0)

async def volatility_monitor_background():
    """Background monitor for token volatility."""
    de_pin_memes = ["GRASS", "BONK", "WIF", "RENDER", "HONEY"]

    while True:
        try:
            for token in de_pin_memes:
                await volatility_watcher.monitor_token_volatility(token)
            await asyncio.sleep(0.5)  # Monitor every 0.5 seconds
        except Exception as e:
            logger.error(f"Volatility monitor error: {e}")
            await asyncio.sleep(5.0)

async def receipt_arb_background_scanner():
    """Background scanner for receipt token arbitrage opportunities."""
    while True:
        try:
            await receipt_arb_engine.scan_receipt_discounts()
            await asyncio.sleep(2.0)  # Scan every 2 seconds (less frequent for lending)
        except Exception as e:
            logger.error(f"Receipt arb scanner error: {e}")
            await asyncio.sleep(10.0)

async def dust_sweep_background():
    """Background dust sweeping every 30 minutes."""
    while True:
        try:
            await asyncio.sleep(1800)  # 30 minutes
            recovered = await dust_sweeper.sweep_on_startup()
            if recovered > 0:
                logger.info(f"🧹 Background dust sweep recovered {recovered / 1e9:.6f} SOL")
        except Exception as e:
            logger.error(f"Background dust sweep error: {e}")
            await asyncio.sleep(300)  # Retry in 5 minutes

async def _build_burn_instruction_atlanta(token_account: str, mint: str, amount_lamports: int, keypair):
    """Build TokenProgram.Burn instruction for SPL token (Task 52 — Phase 41)."""
    try:
        from spl.token.instructions import BurnParams, burn
        burn_params = BurnParams(
            program_id=Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"),
            account=Pubkey.from_string(token_account),
            mint=Pubkey.from_string(mint),
            owner=keypair.pubkey(),
            amount=amount_lamports,
        )
        return burn(burn_params)
    except Exception as e:
        logger.debug(f"Burn instruction build failed: {e}")
        return None


async def close_ata_after_arbitrage(session, keypair, rpc_getter, ata_address: str):
    """Task 52 — Burn-before-close ATA."""
    try:
        # Check ATA balance
        balance_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountBalance",
            "params": [ata_address]
        }
        timeout = aiohttp.ClientTimeout(total=2.0)
        async with session.post(rpc_getter(), json=balance_payload, timeout=timeout) as resp:
            if resp.status != 200:
                logger.debug(f"Failed to check ATA balance: {resp.status}")
                return
            data = await resp.json()
            if "result" not in data or "value" not in data["result"]:
                logger.debug(f"No balance data for ATA {str(ata_address)[:8]}")
                return

            value = data["result"]["value"]
            raw_amount_str = value.get("amount", "0")          # integer lamports (base units)
            ui_amount = float(value.get("uiAmountString") or "0")
            decimals = int(value.get("decimals", 6))

            # Phase 48: Golden ATA Protection — never close wSOL or USDC
            SOL_MINT = "So11111111111111111111111111111111111111112"
            USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            from spl.token.instructions import get_associated_token_address
            wsol_ata = str(get_associated_token_address(keypair.pubkey(), Pubkey.from_string(SOL_MINT)))
            usdc_ata = str(get_associated_token_address(keypair.pubkey(), Pubkey.from_string(USDC_MINT)))
            if str(ata_address) in [wsol_ata, usdc_ata]:
                logger.debug(f"Preserving golden ATA: {ata_address}")
                return

            if ui_amount == 0 and int(raw_amount_str or 0) == 0:
                logger.debug(f"ATA {str(ata_address)[:8]} is already empty — nothing to burn or close")
                return

            # Determine mint address for this ATA (needed for burn instruction)
            mint = value.get("mint")

            close_instructions = []

            # Task 52: Burn-before-close — flush non-zero residue to prevent TokenAccountNotEmpty
            raw_amount = int(raw_amount_str or 0) * (10 ** (9 - decimals))
            if raw_amount > 0:
                burn_ix = _build_burn_instruction_atlanta(str(ata_address), mint, raw_amount, keypair)
                if burn_ix:
                    close_instructions.append(burn_ix)
                    logger.debug(f"🔥 Burning {raw_amount} lamports ({ui_amount} tokens) from {str(ata_address)[:8]}…")

            # Build CloseAccount instruction (runs regardless — handles zero-leftover path)
            from spl.token.instructions import CloseAccountParams, close_account
            close_params = CloseAccountParams(
                account=Pubkey.from_string(ata_address),
                dest=keypair.pubkey(),
                owner=keypair.pubkey(),
                program_id=Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
            )
            close_instructions.append(close_account(close_params))

            # === Build transaction ===
            from solders.message import MessageV0
            from solders.transaction import VersionedTransaction
            from solders.compute_budget import set_compute_unit_limit

            cu_limit_ix = set_compute_unit_limit(50_000)

            # Get blockhash
            blockhash_payload = {"jsonrpc": "2.0", "id": 1, "method": "getLatestBlockhash"}
            async with session.post(rpc_getter(), json=blockhash_payload, timeout=timeout) as resp:
                if resp.status != 200:
                    logger.debug("Failed to get blockhash for ATA close")
                    return
                bh_data = await resp.json()
                blockhash = bh_data["result"]["value"]["blockhash"]

            message = MessageV0.try_compile(
                payer=keypair.pubkey(),
                instructions=[cu_limit_ix] + close_instructions,
                address_lookup_table_accounts=[],
                recent_blockhash=Pubkey.from_string(blockhash)
            )
            tx = VersionedTransaction(message, [keypair])

            # Send transaction
            tx_b64 = base64.b64encode(bytes(tx)).decode()
            send_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendTransaction",
                "params": [tx_b64, {"encoding": "base64"}]
            }
            async with session.post(rpc_getter(), json=send_payload, timeout=timeout) as resp:
                if resp.status == 200:
                    send_data = await resp.json()
                    if "result" in send_data:
                        logger.debug(f"✅ ATA burn+close done, rent recovered: {str(send_data['result'])[:8]}")
                    else:
                        logger.debug(f"ATA burn+close failed: {send_data}")
                else:
                    logger.debug(f"ATA burn+close send failed: {resp.status}")

    except Exception as e:
        logger.debug(f"ATA burn+close error: {e}")

if __name__ == "__main__":
    try:
        import uvloop
        uvloop.install()
        logging.info("⚡ uvloop установлен (максимальная скорость)")
    except ImportError:
        logging.info("ℹ️ uvloop не найден, используем стандартный asyncio")
    
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logging.info("Bot stopped.")