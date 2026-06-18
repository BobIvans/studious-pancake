import asyncio
import logging
import time
from typing import Dict, Set, Any, Optional

logger = logging.getLogger("SharedState")

# Global locks
execution_lock: Optional[asyncio.Lock] = None
marginfi_account_lock: Optional[asyncio.Lock] = None
stats_lock: Optional[asyncio.Lock] = None
GLOBAL_STOP_EVENT: Optional[asyncio.Event] = None
jito_bidding_manager: Optional[Any] = None

# MarginFi banks configuration (shared to avoid circular imports)
MARGINFI_BANKS: Dict[str, Any] = {}
MARGINFI_BANKS_LOCK = asyncio.Lock()

# Fix 67: Balance lock flags

stats: Dict[str, Any] = {
    "trades": 0,
    "last_balance": 0.0,
    "virtual_balance": 0.0,
    "initial_balance": 0.0,
    "bundle_send_attempts": 0,
    "bundle_successes": 0,
    "flash_loan_attempt_count": 0,
    "flash_loan_miss_count": 0,
    "state_to_execution_latencies": [],
    "current_slot": 0,
    "errors": {},
}

active_tasks: Set[asyncio.Task] = set()
WSOL_JUST_CLOSED_ATOMICALLY: float = 0.0
WSOL_CLOSE_COOLDOWN: float = 60.0

# Jito Tip Accounts & Bidding Manager
jito_tip_manager = None
jito_bidding_manager = None
jito_leader_tracker = None
leader_tracker = None

# RPC and Network
rpc = None  # Will be set in run()
cached_blockhash: Optional[str] = None

# ALT Manager for Address Lookup Table resolution
alt_manager: Optional[Any] = None

# Data Aggregator for paper trading and analytics
data_aggregator: Optional[Any] = None

# Глобальный пул MarginFi аккаунтов (синглтон для всех модулей)
marginfi_pool: Optional[Any] = None

ATA_CACHE: set = set()

def initialize_shared_state():
    global execution_lock, marginfi_account_lock, stats_lock, GLOBAL_STOP_EVENT
    execution_lock = asyncio.Lock()
    marginfi_account_lock = asyncio.Lock()
    stats_lock = asyncio.Lock()
    GLOBAL_STOP_EVENT = asyncio.Event()
    logger.info("✅ Shared state initialized with asyncio locks")

# Fix 67: Balance lock flags — moved here from wsol_manager.py and arb_bot.py
# to eliminate circular imports (wsol_manager was importing arb_bot and vice versa).
_balance_lock_paused: bool = False
_balance_lock_pause_until: float = 0.0

def mark_wsol_atomically_closed():
    global WSOL_JUST_CLOSED_ATOMICALLY
    WSOL_JUST_CLOSED_ATOMICALLY = time.time()
