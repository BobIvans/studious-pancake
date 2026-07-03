"""
Monitored addresses configuration for Helius Webhook monitoring.
Contains program addresses and their associated arbitrage strategies with priorities.
"""

import os
import logging
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# Main monitored addresses dictionary - OPTIMIZED FOR MINIMAL HELIUS USAGE
MONITORED_ADDRESSES = {
    # TIER A - HIGHEST PRIORITY (MINIMAL NOISE, MAXIMUM PROFIT)
    "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg": {
        "name": "Pump.fun Migration Account",
        "strategies": ["R1", "pump_migration", "pre_position_85sol", "virtual_vs_real"],
        "priority": "HIGHEST",
        "enabled": False,  # DISABLED: Too much MEV competition, use BelieveApp/Moonshot instead
        "transaction_types": ["MIGRATION", "CREATE_POOL", "ADD_LIQUIDITY", "SWAP"],
        "note": "Отключен - слишком высокая конкуренция MEV-ботов",
        "cooldown_seconds": 5,
        "last_triggered": 0
    },
    "dbcij3LWUppTiACKHVKtjUi2Vn3JBmXu4quMErSMFpN": {
        "name": "BelieveApp Meteora DBC",
        "strategies": ["R2", "believeapp_graduation", "meteora_dynamic_fee"],
        "priority": "HIGHEST",
        "enabled": True,
        "transaction_types": ["GRADUATION", "ADD_LIQUIDITY", "SWAP"],
        "note": "Высочайший rate, меньше шума",
        "cooldown_seconds": 3,
        "last_triggered": 0
    },
    "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj": {
        "name": "LetsBonk LaunchLab",
        "strategies": ["letsbonk_graduation", "launchlab_powered"],
        "priority": "HIGH",
        "enabled": True,
        "transaction_types": ["GRADUATION", "ADD_LIQUIDITY"],
        "note": "Хороший rate",
        "cooldown_seconds": 10,
        "last_triggered": 0
    },
    "LBUZKhRxPF3XUpBCjp4YzTKgLLjggiJWUna9LZJRQD3": {
        "name": "Meteora DLMM",
        "strategies": ["believeapp_graduation", "meteora_dlmm_arb", "dynamic_fee_arb"],
        "priority": "HIGH",
        "enabled": True,
        "transaction_types": ["GRADUATION", "CREATE_POOL", "SWAP", "POSITION_UPDATE"],
        "note": "Blue Ocean - Meteora DLMM for BelieveApp/LaunchLab",
        "cooldown_seconds": 5,
        "last_triggered": 0
    },
    "MoonCVVNZFSYkqNXP6bxHL13nk21VGGf25sUnyP6HjU": {
        "name": "Moonshot Program",
        "strategies": ["moonshot_graduation", "alternative_launchpad"],
        "priority": "HIGH",
        "enabled": True,
        "transaction_types": ["GRADUATION", "CREATE_POOL", "SWAP"],
        "note": "Blue Ocean - Less competition than Pump.fun",
        "cooldown_seconds": 3,
        "last_triggered": 0
    },
    "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C": {
        "name": "Raydium CPMM v4",
        "strategies": ["raydium_cpmm_arb", "cross_dex_arb"],
        "priority": "MEDIUM",
        "enabled": True,
        "transaction_types": ["CREATE_POOL", "SWAP", "ADD_LIQUIDITY"],
        "note": "New Raydium CPMM standard for arbitrage",
        "cooldown_seconds": 8,
        "last_triggered": 0
    },

    # DISABLED BY DEFAULT - TOO NOISY FOR MINIMAL CREDIT USAGE
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P": {
        "name": "Pump.fun Main Program",
        "strategies": ["pump_graduation", "bonding_curve_progress", "pre_graduation"],
        "priority": "HIGH",
        "enabled": False,
        "transaction_types": ["GRADUATION", "CREATE_POOL"],
        "note": "Слишком шумный",
        "cooldown_seconds": 30,
        "last_triggered": 0
    },
    # REMOVED: Duplicate Meteora DLMM entry (had enabled: False, conflicting with the enabled: True entry above)
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": {
        "name": "Raydium AMM v4",
        "strategies": ["raydium_graduation", "letsbonk_graduation", "launchlab_graduation"],
        "priority": "HIGH",
        "enabled": False,
        "transaction_types": ["GRADUATION", "CREATE_POOL", "SWAP"],
        "note": "Очень шумный DEX",
        "cooldown_seconds": 20,
        "last_triggered": 0
    },
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK": {
        "name": "Raydium CLMM",
        "strategies": ["clmm_tick_boundary", "launchlab_clmm"],
        "priority": "MEDIUM",
        "enabled": False,
        "transaction_types": ["CREATE_POOL", "SWAP"],
        "note": "Сложная математика",
        "cooldown_seconds": 25,
        "last_triggered": 0
    }
}

def get_enabled_addresses() -> Dict[str, Dict]:
    """Get only enabled monitored addresses (OPTIMIZED FOR MINIMAL CREDIT USAGE)."""
    enabled_addresses = {}
    enabled_count = 0
    total_count = len(MONITORED_ADDRESSES)

    for addr, data in MONITORED_ADDRESSES.items():
        # Check environment variable for enabling/disabling
        env_var = f"MONITOR_{data['name'].upper().replace(' ', '_').replace('.', '').replace('-', '_')}"
        enabled = os.getenv(env_var, str(data.get("enabled", True))).lower() in ('true', '1', 'yes', 'on')

        if enabled:
            enabled_addresses[addr] = data
            enabled_count += 1

    logger.info(f"📊 Address monitoring: {enabled_count}/{total_count} enabled")
    for addr, data in enabled_addresses.items():
        priority = data.get("priority", "UNKNOWN")
        note = data.get("note", "")
        logger.info(f"  ✓ {data['name']} ({priority}) - {note}")

    return enabled_addresses

def get_addresses_by_priority(priority: str) -> Dict[str, Dict]:
    """Get addresses filtered by priority level."""
    return {addr: data for addr, data in MONITORED_ADDRESSES.items()
            if data.get("priority") == priority and data.get("enabled", True)}

def get_all_strategies() -> List[str]:
    """Get all unique strategies from monitored addresses."""
    strategies = set()
    for addr_data in MONITORED_ADDRESSES.values():
        strategies.update(addr_data.get("strategies", []))
    return sorted(list(strategies))

def get_priority_order() -> List[str]:
    """Get priority levels in order of importance."""
    return ["HIGHEST", "HIGH", "MEDIUM", "LOW"]

# ============================================================================
# PYTH ORACLE FEEDS
# ============================================================================

PYTH_FEEDS = {
    # SOL / USDC / USDT дублируются здесь для надежности обратного поиска
    "SOL": {
        "feed_id": "ef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d",
        "mint": "So11111111111111111111111111111111111111112"
    },
    "USDC": {
        "feed_id": "eaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a",
        "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    },
    "USDT": {
        "feed_id": "2b89b9dc8fdf9f34709a5b106b472f0f39bb6ca9ce04b0fd7f2e971688e2e53b",
        "mint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
    },
    # LST-токены (Mainnet Price Feed IDs)
    "jitoSOL": {
        "feed_id": "67be9f519b95cf24338801051f9a808eff0a578ccb388db73b7f6fe1de019ffb",
        "mint": "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn"
    },
    "mSOL": {
        "feed_id": "c2289a6a43d2ce91c6f55caec370f4acc38a2ed477f58813334c6d03749ff2a4",
        "mint": "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So"
    },
    "INF": {
        "feed_id": "f51570985c642c49c2d6e50156390fdba80bb6d5f7fa389d2f012ced4f7d208f",
        "mint": "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm"
    },
    "JUP": {
        "feed_id": "0a0408d619e9380abad35060f9192039ed5042fa6f82301d0e48bb52be830996",
        "mint": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
    },
    "WIF": {
        "feed_id": "b3e32b8aa075775f0a0ffaa2a9bfccdbdb21df4ff1a6c1e54a012ced4f7d208f",
        "mint": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"
    },
    "BONK": {
        "feed_id": "72b021217ca3fe68922a19aaf990109cb9d84e9ad004b4d2025ad6f529314419",
        "mint": "DezXAZ8z7P8gVmFiDQ6cEhPmmF9rj3ZfVGg3LyZ3mTKV"
    }
}

XSTOCK_MINTS = {
    "USDY": "A1KLoBrKBde8Ty9qtNQUtq3C2ortoC3u7twggz7sEto6",
    "USDe": "DEkqHyPN7GMRJ5cArtQFAWefqbZb33Hyf6s5iCwjEonT",
    "sUSDe": "Eh6XEPhSwoLv5wFApukmnaVSHQ6sAnoD9BmgmwQoN2sN",
    "sUSDS": "SKYTAiJRkgexqQqFoqhXdCANyfziwrVrzjhBaCzdbKW",
    "JupUSD": "JuprjznTrTSp2UFa3ZBUFgwdAmtZCq4MQCwysN55USD",
}

XSTOCK_ADDRESSES = list(XSTOCK_MINTS.values())


def is_xstock_token(mint: str) -> bool:
    """Return True if mint is a registered xStocks/RWA token."""
    return str(mint) in XSTOCK_MINTS.values()


def get_xstock_ticker(mint: str) -> Optional[str]:
    """Reverse lookup: mint address → ticker name."""
    for ticker, address in XSTOCK_MINTS.items():
        if address == str(mint):
            return ticker
    return None

# ============================================================================
# PYTH CORE TOKEN FEEDS (Task 13: Real-Time Tip Normalization)
# Used to bypass Jupiter Price API (10-30s cache lag) for SOL/USDC/USDT.
# Pyth Hermes updates every ~400ms directly from validators.
# ============================================================================

HERMES_WS_URL = "wss://hermes.pyth.network/ws"

PYTH_CORE_FEEDS: Dict[str, Dict[str, Any]] = {
    "SOL": {
        "feed_id": "ef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d",
        "symbol": "Crypto.SOL/USD",
        "mint": "So11111111111111111111111111111111111111112",
        "asset_type": "crypto",
        "priority": 1,
    },
    "USDC": {
        "feed_id": "eaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a",
        "symbol": "Crypto.USDC/USD",
        "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "asset_type": "crypto",
        "priority": 2,
    },
    "USDT": {
        "feed_id": "2b89b9dc8fdf9f34709a5b106b472f0f39bb6ca9ce04b0fd7f2e971688e2e53b",
        "symbol": "Crypto.USDT/USD",
        "mint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
        "asset_type": "crypto",
        "priority": 3,
    },
}

def get_all_pyth_feed_ids(with_core: bool = True) -> List[str]:
    """Get all Pyth feed IDs for subscription, optionally including core tokens.

    PYTH_FEEDS and PYTH_CORE_FEEDS are module-level dicts defined below.
    Since Python resolves names at call-time (not definition-time), we reference
    them inside the function body where they are guaranteed to exist.
    """
    feed_ids = [
        feed["feed_id"]
        for feed in PYTH_FEEDS.values()
        if isinstance(feed, dict) and "feed_id" in feed
    ]
    if with_core:
        feed_ids.extend(
            feed["feed_id"]
            for feed in PYTH_CORE_FEEDS.values()
            if isinstance(feed, dict) and "feed_id" in feed
        )
    return feed_ids


def get_core_feed_id(ticker: str) -> Optional[str]:
    """Get Pyth feed ID for a core token ticker (SOL, USDC, USDT)."""
    feed = PYTH_CORE_FEEDS.get(ticker)
    return feed.get("feed_id") if feed else None


def get_mint_for_core_feed(feed_id: str) -> Optional[str]:
    """Reverse-lookup mint address from a core token feed ID."""
    for ticker, info in PYTH_CORE_FEEDS.items():
        if info.get("feed_id") == feed_id and info.get("mint"):
            return info["mint"]
    return None