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
    # ---- GRUPPA 1: Velolepnaya Semerka ----
    "NVDAx": {
        "feed_id": "b1073854ed24cbc755dc527418f52b7d271f6cc967bbf8d8129112b18860a593",
        "symbol": "Equity.US.NVDA/USD",
        "asset_type": "equity",
        "category": "magnificent_seven",
        "variant": "main",
        "priority": 1,
    },
    "NVDAx_PRE": {
        "feed_id": "61c4ca5b9731a79e285a01e24432d57d89f0ecdd4cd7828196ca8992d5eafef6",
        "symbol": "Equity.US.NVDA/USD.PRE",
        "asset_type": "equity",
        "category": "magnificent_seven",
        "variant": "pre_market",
        "priority": 1,
    },
    "NVDAx_ON": {
        "feed_id": "c949a96fd1626e82abc5e1496e6e8d44683ac8ac288015ee90bf37257e3e6bf6",
        "symbol": "Equity.US.NVDA/USD.ON",
        "asset_type": "equity",
        "category": "magnificent_seven",
        "variant": "regular_hours",
        "priority": 1,
    },
    "NVDAx_POST": {
        "feed_id": "25719379353a508b1531945f3c466759d6efd866f52fbaeb3631decb70ba381f",
        "symbol": "Equity.US.NVDA/USD.POST",
        "asset_type": "equity",
        "category": "magnificent_seven",
        "variant": "after_hours",
        "priority": 1,
    },
    "TSLAx": {
        "feed_id": "713631e41c06db404e6a5d029f3eebfd5b885c59dce4a19f337c024e26584e26",
        "symbol": "Equity.US.TSLA/USD.ON",
        "asset_type": "equity",
        "category": "magnificent_seven",
        "variant": "regular_hours",
        "priority": 2,
    },
    "AAPLx": {
        "feed_id": "8c320e4cd87c6cef41513aead15db413cf9253211923fef6e87187a7f6688906",
        "symbol": "Equity.US.AAPL/USD.PRE",
        "asset_type": "equity",
        "category": "magnificent_seven",
        "variant": "pre_market",
        "priority": 3,
    },
    "AMZNx": {
        "feed_id": "82c59e36a8e0247e15283748d6cd51f5fa1019d73fbf3ab6d927e17d9e357a7f",
        "symbol": "Equity.US.AMZN/USD.PRE",
        "asset_type": "equity",
        "category": "magnificent_seven",
        "variant": "pre_market",
        "priority": 4,
    },
    "MSFTx": {
        "feed_id": "556b3e4dcc1c66448ba4054a0d9485545e3227ffc90a269f630620c5a38241ab",
        "symbol": "Equity.US.MSFT/USD.POST",
        "asset_type": "equity",
        "category": "magnificent_seven",
        "variant": "after_hours",
        "priority": 5,
    },
    "GOOGLx": {
        "feed_id": "07d24bb76843496a45bce0add8b51555f2ea02098cb04f4c6d61f7b5720836b4",
        "symbol": "Equity.US.GOOGL/USD.ON",
        "asset_type": "equity",
        "category": "magnificent_seven",
        "variant": "regular_hours",
        "priority": 6,
    },
    "METAx": {
        "feed_id": "ce0999c4f22f35f00e8f9913694868d00279c0b9efbd7cb1c358bf2fd76295c9",
        "symbol": "Equity.US.META/USD.PRE",
        "asset_type": "equity",
        "category": "magnificent_seven",
        "variant": "pre_market",
        "priority": 7,
    },

    # ---- GRUPPA 2: Kripto-Proxy ----
    "MSTRx": {
        "feed_id": "c3055f49e1dc863a7f24d9b83e86fe10d7d16fb583bc6445505b01d230e0d647",
        "symbol": "Equity.US.MSTR/USD.ON",
        "asset_type": "equity",
        "category": "crypto_proxy",
        "variant": "regular_hours",
        "priority": 1,
    },
    "COINx": {
        "feed_id": "5c3bd92f2eed33779040caea9f82fac705f5121d26251f8f5e17ec35b9559cd4",
        "symbol": "Equity.US.COIN/USD.POST",
        "asset_type": "equity",
        "category": "crypto_proxy",
        "variant": "after_hours",
        "priority": 2,
    },
    "HOODx": {
        "feed_id": "306736a4035846ba15a3496eed57225b64cc19230a50d14f3ed20fd7219b7849",
        "symbol": "Equity.US.HOOD/USD",
        "asset_type": "equity",
        "category": "crypto_proxy",
        "variant": "main",
        "priority": 3,
    },
    "MARAx": {
        "feed_id": "0fc2ad77a9ab75bcbc3ebd7a9ff60facd08c517309e2d684baa979c910a0e43e",
        "symbol": "Equity.US.MARA/USD",
        "asset_type": "equity",
        "category": "crypto_proxy",
        "variant": "main",
        "priority": 4,
    },
    "RIOTx": {
        "feed_id": "46417522a59b245c5af35c33c13426d991b36514c4c85aaefe1cf787e7daad90",
        "symbol": "Equity.US.RIOT/USD",
        "asset_type": "equity",
        "category": "crypto_proxy",
        "variant": "main",
        "priority": 5,
    },

    # ---- GRUPPA 3: Indeksy i ETF ----
    "SPYx": {
        "feed_id": "05d590e94e9f51abe18ed0421bc302995673156750e914ac1600583fe2e03f99",
        "symbol": "Equity.US.SPY/USD.ON",
        "asset_type": "equity",
        "category": "etf_index",
        "variant": "regular_hours",
        "priority": 1,
    },
    "QQQx": {
        "feed_id": "9695e2b96ea7b3859da9ed25b7a46a920a776e2fdae19a7bcfdf2b219230452d",
        "symbol": "Equity.US.QQQ/USD",
        "asset_type": "equity",
        "category": "etf_index",
        "variant": "main",
        "priority": 2,
    },
    "GLDx": {
        "feed_id": "e190f467043db04548200354889dfe0d9d314c08b8d4e62fabf4d5a3140fecca",
        "symbol": "Equity.US.GLD/USD",
        "asset_type": "equity",
        "category": "etf_index",
        "variant": "main",
        "priority": 3,
    },
    "SLVx": {
        "feed_id": "6fc08c9963d266069cbd9780d98383dabf2668322a5bef0b9491e11d67e5d7e7",
        "symbol": "Equity.US.SLV/USD",
        "asset_type": "etf_index",
        "category": "etf_index",
        "variant": "main",
        "priority": 4,
    },
}

XSTOCK_MINTS = {
    "USDY": "A1KLoBrKBde8Ty9qtNQUtq3C2ortoC3u7twggz7sEto6",
    "USDe": "DEkqHyPN7GMRJ5cArtQFAWefqbZb33Hyf6s5iCwjEonT",
    "sUSDe": "Eh6XEPhSwoLv5wFApukmnaVSHQ6sAnoD9BmgmwQoN2sN",
    "sUSDS": "SKYTAiJRkgexqQqFoqhXdCANyfziwrVrzjhBaCzdbKW",
    "USD+": "B7vF87HGPJLcQwPhNn8apCH5n1E4DfRrG8HYXoS9dPEo",
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