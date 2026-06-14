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

# Stats and tracking
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

def initialize_shared_state():
    global execution_lock, marginfi_account_lock, stats_lock, GLOBAL_STOP_EVENT
    execution_lock = asyncio.Lock()
    marginfi_account_lock = asyncio.Lock()
    stats_lock = asyncio.Lock()
    GLOBAL_STOP_EVENT = asyncio.Event()
    logger.info("✅ Shared state initialized with asyncio locks")

def mark_wsol_atomically_closed():
    global WSOL_JUST_CLOSED_ATOMICALLY
    WSOL_JUST_CLOSED_ATOMICALLY = time.time()
