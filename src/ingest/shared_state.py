import asyncio
import logging
import os
import time
from typing import Dict, Set, Any, Optional
from solders.pubkey import Pubkey

logger = logging.getLogger("SharedState")

# Global locks
execution_lock: Optional[asyncio.Lock] = None
marginfi_account_lock: Optional[asyncio.Lock] = None
stats_lock: Optional[asyncio.Lock] = None
GLOBAL_STOP_EVENT: Optional[asyncio.Event] = None
jito_bidding_manager: Optional[Any] = None

# MARGINFI PROGRAM ADDRESSES AND PDA DERIVATION
MARGINFI_PROGRAM_ID = Pubkey.from_string(os.getenv("MARGINFI_PROGRAM_ID", "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"))
MARGINFI_GROUP = Pubkey.from_string(os.getenv("MARGINFI_GROUP", "4qp6Fx6tnZkY5Wropq9wUYgtFxXKwE6viZxFHg3rdAG8"))

# Task 11: Hardcoded MarginFi Liquidity Vaults (Mainnet)
# In MarginFi v2 liquidity_vault is a real Token Account, NOT a PDA
MARGINFI_LIQUIDITY_VAULTS: Dict[str, str] = {
    "CCwqExrqLGHtq12X182rFvA4KEDtK13q2E7B3Jp2Cxyj": "7uttpzxsHAcX97X5ZwaX8xMpsJc9aKx2V8t4Gf6A43XJ",
    "2s37akK2eyBbp8DZgCm7RtsaEz8eWhVKGfHGA3cKMEW2": "73zNEAXx8vWeCReEwZgPZteXhH3RTo8gC1vC51g8x7j2",
}

def get_marginfi_bank_accounts(bank_pubkey: Pubkey):
    def find_pda(seed_str):
        pda, _ = Pubkey.find_program_address(
            [seed_str.encode(), bytes(bank_pubkey)], MARGINFI_PROGRAM_ID
        )
        return pda

    bank_str = str(bank_pubkey)
    liquidity_vault_str = MARGINFI_LIQUIDITY_VAULTS.get(bank_str)
    if not liquidity_vault_str:
        logger.critical(
            f"🛑 UNKNOWN MARGINFI BANK: {bank_str}\n"
            "liquidity_vault not in MARGINFI_LIQUIDITY_VAULTS map — flash loan cannot proceed."
        )

    return {
        "bank": bank_pubkey,
        "liquidity_vault": Pubkey.from_string(liquidity_vault_str) if liquidity_vault_str else None,
        "liquidity_vault_authority": find_pda("liquidity_vault_auth"),
        "insurance_vault": find_pda("insurance_vault"),
        "insurance_vault_authority": find_pda("insurance_vault_auth"),
        "fee_vault": find_pda("fee_vault"),
        "fee_vault_authority": find_pda("fee_vault_auth"),
    }

def get_marginfi_banks():
    """Get MarginFi bank configurations with lazy initialization."""
    try:
        sol_bank = os.getenv("MARGINFI_SOL_BANK", "CCwqExrqLGHtq12X182rFvA4KEDtK13q2E7B3Jp2Cxyj").strip()
        usdc_bank = os.getenv("MARGINFI_USDC_BANK", "2s37akK2eyBbp8DZgCm7RtsaEz8eWhVKGfHGA3cKMEW2").strip()
        correct_usdc = "2s37akK2eyBbp8DZgCm7RtsaEz8eWhVKGfHGA3cKMEW2"
        if usdc_bank != correct_usdc:
            logger.warning(f"⚠️ Self-healing .env: wrong MARGINFI_USDC_BANK {usdc_bank} -> {correct_usdc}")
            usdc_bank = correct_usdc

        return {
            "So11111111111111111111111111111111111111112": get_marginfi_bank_accounts(Pubkey.from_string(sol_bank)),
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": get_marginfi_bank_accounts(Pubkey.from_string(usdc_bank)),
        }
    except Exception as e:
        logger.warning(f"Failed to initialize MarginFi banks: {e}. Using empty dict.")
        return {}

MARGINFI_BANKS: Dict[str, Any] = get_marginfi_banks()

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

def retain_background_task(task: asyncio.Task, callback=None) -> asyncio.Task:
    active_tasks.add(task)
    task.add_done_callback(callback or active_tasks.discard)
    return task

WSOL_JUST_CLOSED_ATOMICALLY: float = 0.0
WSOL_CLOSE_COOLDOWN: float = 60.0

# Jito Tip Accounts & Bidding Manager
jito_tip_manager = None
jito_bidding_manager = None
# Fix 37: jito_leader_tracker removed (RNG-based)
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

# Fix 5: Authoritative function for setting balance lock pause.
# Both wsol_manager.py and arb_bot.py should call this instead of
# directly setting _balance_lock_paused to prevent synchronization bugs.
def set_balance_lock_paused(paused: bool, duration: float = 0.4) -> None:
    global _balance_lock_paused, _balance_lock_pause_until
    _balance_lock_paused = paused
    _balance_lock_pause_until = time.time() + duration if paused else 0.0
