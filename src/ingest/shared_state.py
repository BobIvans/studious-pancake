import aiohttp
import asyncio
import logging
import os
import time
from typing import Dict, Set, Any, Optional, List
from solders.pubkey import Pubkey
from src.ingest.circuit_breaker import CapitalProtection

logger = logging.getLogger("SharedState")

# Global locks
execution_lock: Optional[asyncio.Lock] = None
marginfi_account_lock: Optional[asyncio.Lock] = None
stats_lock: Optional[asyncio.Lock] = None
GLOBAL_STOP_EVENT: Optional[asyncio.Event] = None
jito_bidding_manager: Optional[Any] = None

# Fix 64: Lock for ATA_CACHE and WSOL flags to prevent race conditions
ata_cache_lock: Optional[asyncio.Lock] = None
wsol_state_lock: Optional[asyncio.Lock] = None
marginfi_init_lock: Optional[asyncio.Lock] = None

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
            "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn": get_marginfi_bank_accounts(Pubkey.from_string(sol_bank)),
            "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So": get_marginfi_bank_accounts(Pubkey.from_string(sol_bank)),
            "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1": get_marginfi_bank_accounts(Pubkey.from_string(sol_bank)),
        }
    except Exception as e:
        logger.warning(f"Failed to initialize MarginFi banks: {e}. Using empty dict.")
        return {}

# Fix 64: Lazy initialization wrapper — call init_marginfi_banks() after .env is loaded
MARGINFI_BANKS: Dict[str, Any] = {}
_MARGINFI_BANKS_INITIALIZED: bool = False


def init_marginfi_banks() -> Dict[str, Any]:
    """(Re)initialize MarginFi bank configs.
    
    Must be called after .env is fully loaded to read MARGINFI_SOL_BANK and
    MARGINFI_USDC_BANK from environment.  The module-level dict was previously
    initialized at import time when .env may not have been loaded yet.
    
    IMPORTANT: Mutates the existing dict in-place so that all existing
    references from other modules (arb_bot, lst_unstake_arbitrage, etc.)
    see the populated data.
    Returns the populated MARGINFI_BANKS dict.
    """
    global _MARGINFI_BANKS_INITIALIZED
    banks = get_marginfi_banks()
    MARGINFI_BANKS.clear()
    MARGINFI_BANKS.update(banks)
    _MARGINFI_BANKS_INITIALIZED = True
    logger.info(f"✅ MarginFi banks initialized: {len(MARGINFI_BANKS)} banks")
    return MARGINFI_BANKS

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
    "state_to_execution_latencies": [],  # Fix 64: Capped to 1000 max via append_latency()
    "current_slot": 0,
    "errors": {},
    "last_opportunity_ts": 0.0,
    "consecutive_failures": 0,
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

# Capital Protection (Circuit Breaker for realized losses)
capital_protection: Optional[CapitalProtection] = None

# ALT Manager for Address Lookup Table resolution
alt_manager: Optional[Any] = None

# Data Aggregator for paper trading and analytics
data_aggregator: Optional[Any] = None

# Глобальный пул MarginFi аккаунтов (синглтон для всех модулей)
marginfi_pool: Optional[Any] = None

# Unified Pair Reputation Circuit Breaker (single instance for all modules)
pair_reputation: Optional["PairReputationCircuitBreaker"] = None

ATA_CACHE: set = set()

# Default slippage in basis points — single source of truth for all modules
# Phase 8.2: Unified 15 bps default (0.15%) across arb_bot, jupiter_api_client, and paper_trader
DEFAULT_SLIPPAGE_BPS: int = int(os.getenv("SLIPPAGE_BPS", "15"))

def initialize_shared_state():
    global execution_lock, marginfi_account_lock, stats_lock, GLOBAL_STOP_EVENT
    global ata_cache_lock, wsol_state_lock, marginfi_init_lock, pair_reputation
    # Phase 19: Safety check — asyncio.Lock()/Event() must be created inside a running event loop
    # to avoid binding to a dummy loop (Python 3.10+), which causes future await calls to hang.
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError as e:
        raise RuntimeError(
            f"initialize_shared_state() called outside a running event loop: {e}. "
            "Call this function inside async def run() after the event loop is active."
        ) from e
    execution_lock = asyncio.Lock()
    marginfi_account_lock = asyncio.Lock()
    stats_lock = asyncio.Lock()
    ata_cache_lock = asyncio.Lock()
    wsol_state_lock = asyncio.Lock()
    marginfi_init_lock = asyncio.Lock()
    GLOBAL_STOP_EVENT = asyncio.Event()
    from src.ingest.flywheel_scaler import PairReputationCircuitBreaker
    pair_reputation = PairReputationCircuitBreaker(
        limit=3, cooldown_seconds=600,
        error_keywords=("slippage", "insufficient", "liquidity", "simulation failed", "blockhash"),
    )
    logger.info("✅ Shared state initialized with asyncio locks and unified pair reputation")

# Fix 67: Balance lock flags — moved here from wsol_manager.py and arb_bot.py
# to eliminate circular imports (wsol_manager was importing arb_bot and vice versa).
_balance_lock_paused: bool = False
_balance_lock_pause_until: float = 0.0

# Phase 9: Centralised ATA rent constants — single source of truth for all modules.
# Standard SPL Token ATA rent-exempt lamports: 2_039_280 lamports = 0.00203928 SOL
# Token-2022 ATA rent is higher due to extension space: 0.0035 SOL
ATA_RENT_SOL_SPL = 0.00203928
ATA_RENT_SOL_TOKEN2022 = 0.0035

# Fix 64: Appends a latency measurement to the capped list (max 1000 entries)
def append_latency(value: float) -> None:
    """Append latency measurement, capping list at 1000 entries to prevent memory leak."""
    latencies = stats.get("state_to_execution_latencies", [])
    if len(latencies) >= 1000:
        latencies.pop(0)  # Remove oldest
    latencies.append(value)


# Phase 22 T4: Thread-safe stats increment helper
async def increment_stat(key: str, amount: int = 1) -> None:
    """Increment a numeric stat counter atomically under stats_lock.
    
    Prevents read-modify-write race conditions when multiple async tasks
    mutate shared_state.stats concurrently (e.g. stats["trades"] += 1).
    """
    async with stats_lock:
        if key in stats and isinstance(stats[key], (int, float)):
            stats[key] += amount
        else:
            stats[key] = amount


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

def to_lamports(amount_ui: float, decimals: int) -> int:
    """Convert UI token amount to raw lamports/base units."""
    return int(amount_ui * (10 ** decimals))

def to_ui_amount(amount_lamports: int, decimals: int) -> float:
    """Convert raw lamports/base units to UI token amount."""
    return float(amount_lamports) / (10 ** decimals)

async def send_telegram_alert(message: str):
    """Send an emergency alert via Telegram."""
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    tg_chat = os.getenv("TELEGRAM_CHAT_ID")

    if not tg_token or not tg_chat:
        logger.error(f"Telegram alert not sent (missing env vars): {message}")
        return

    url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
    payload = {
        "chat_id": tg_chat,
        "text": f"🚨 [ARB BOT ALERT]\n\n{message}",
        "parse_mode": "HTML"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=5.0) as resp:
                if resp.status != 200:
                    logger.error(f"Failed to send TG alert: {await resp.text()}")
    except Exception as e:
        logger.error(f"Telegram API exception: {e}")
