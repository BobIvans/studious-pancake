import asyncio
import json
import logging
import time
from datetime import datetime

# Pyth Price Feed ID polucheny cherez Hermes API:
# https://hermes.pyth.network/v2/price_feeds

# Dlya polucheniya ceny na Solana ispol'zuetsya pyth-solidity-sdk ili
# @pythnetwork/pyth-solana-receiver (JS/TS).

# VAZHNO: Pyth feeds dlya akcij imeyut tri varianty:
#     - .PRE  (pre-market)
#     - .ON   (regular trading hours)
#     - .POST (after-hours)
# Nizhe ukazany OSNOVNYE feedy. Dlya polnoty dobav'te .PRE/.POST versii.

# ============================================================================
# PYTH PRICE FEED IDs (Solana Mainnet)
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

    "IBITx": {
        # Pyth IMEET feed dlya IBIT, no xStock-tokena net na Solana
        "feed_id": "9db6bc1e6e9e5e60f6884e1cd8e4399cca9d0454c6e7234ad79680cf139748f5",
        "symbol": "Equity.US.IBIT/USD",
        "asset_type": "equity",
        "category": "etf_index",
        "variant": "main",
        "note": "Pyth feed sushchestvuet, no xStock-token IBITx NE vypushchen na Solana.",
        "priority": 0,
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
        "asset_type": "equity",
        "category": "etf_index",
        "variant": "main",
        "note": "Pyth feed sushchestvuet. SLVx token - upcoming na Solana.",
        "priority": 4,
    },

    "TSLAx": {
        "feed_id": "713631e41c06db404e6a5d029f3eebfd5b885c59dce4a19f337c024e26584e26",
        "symbol": "Equity.US.TSLA/USD.ON",
        "asset_type": "equity",
        "category": "magnificent_seven",
        "variant": "regular_hours",
    },

    "AAPLx": {
        "feed_id": "8c320e4cd87c6cef41513aead15db413cf9253211923fef6e87187a7f6688906",
        "symbol": "Equity.US.AAPL/USD.PRE",
        "asset_type": "equity",
        "category": "magnificent_seven",
        "variant": "pre_market",
    },

    "AMZNx": {
        "feed_id": "82c59e36a8e0247e15283748d6cd51f5fa1019d73fbf3ab6d927e17d9e357a7f",
        "symbol": "Equity.US.AMZN/USD.PRE",
        "asset_type": "equity",
        "category": "magnificent_seven",
        "variant": "pre_market",
    },

    "MSFTx": {
        "feed_id": "556b3e4dcc1c66448ba4054a0d9485545e3227ffc90a269f630620c5a38241ab",
        "symbol": "Equity.US.MSFT/USD.POST",
        "asset_type": "equity",
        "category": "magnificent_seven",
        "variant": "after_hours",
    },

    "GOOGLx": {
        "feed_id": "07d24bb76843496a45bce0add8b51555f2ea02098cb04f4c6d61f7b5720836b4",
        "symbol": "Equity.US.GOOGL/USD.ON",
        "asset_type": "equity",
        "category": "magnificent_seven",
        "variant": "regular_hours",
    },

    "METAx": {
        "feed_id": "ce0999c4f22f35f00e8f9913694868d00279c0b9efbd7cb1c358bf2fd76295c9",
        "symbol": "Equity.US.META/USD.PRE",
        "asset_type": "equity",
        "category": "magnificent_seven",
        "variant": "pre_market",
    },

    # ---- GRUPPA 2: Kripto-Proxy ----
    "MSTRx": {
        "feed_id": "c3055f49e1dc863a7f24d9b83e86fe10d7d16fb583bc6445505b01d230e0d647",
        "symbol": "Equity.US.MSTR/USD.ON",
        "asset_type": "equity",
        "category": "crypto_proxy",
        "variant": "regular_hours",
    },

    "COINx": {
        "feed_id": "5c3bd92f2eed33779040caea9f82fac705f5121d26251f8f5e17ec35b9559cd4",
        "symbol": "Equity.US.COIN/USD.POST",
        "asset_type": "equity",
        "category": "crypto_proxy",
        "variant": "after_hours",
    },

    "HOODx": {
        "feed_id": "306736a4035846ba15a3496eed57225b64cc19230a50d14f3ed20fd7219b7849",
        "symbol": "Equity.US.HOOD/USD",
        "asset_type": "equity",
        "category": "crypto_proxy",
        "variant": "main",
    },

    "MARAx": {
        "feed_id": "0fc2ad77a9ab75bcbc3ebd7a9ff60facd08c517309e2d684baa979c910a0e43e",
        "symbol": "Equity.US.MARA/USD",
        "asset_type": "equity",
        "category": "crypto_proxy",
        "variant": "main",
    },

    "RIOTx": {
        "feed_id": "46417522a59b245c5af35c33c13426d991b36514c4c85aaefe1cf787e7daad90",
        "symbol": "Equity.US.RIOT/USD",
        "asset_type": "equity",
        "category": "crypto_proxy",
        "variant": "main",
    },

    # ---- GRUPPA 3: Indeksy i ETF ----
    "SPYx": {
        "feed_id": "05d590e94e9f51abe18ed0421bc302995673156750e914ac1600583fe2e03f99",
        "symbol": "Equity.US.SPY/USD.ON",
        "asset_type": "equity",
        "category": "etf_index",
        "variant": "regular_hours",
    },

    "QQQx": {
        "feed_id": "9695e2b96ea7b3859da9ed25b7a46a920a776e2fdae19a7bcfdf2b219230452d",
        "symbol": "Equity.US.QQQ/USD",
        "asset_type": "equity",
        "category": "etf_index",
        "variant": "main",
    },

    "IBITx": {
        # Pyth IMEET feed dlya IBIT, no xStock-tokena net na Solana
        "feed_id": "9db6bc1e6e9e5e60f6884e1cd8e4399cca9d0454c6e7234ad79680cf139748f5",
        "symbol": "Equity.US.IBIT/USD",
        "asset_type": "equity",
        "category": "etf_index",
        "variant": "main",
        "note": "Pyth feed sushchestvuet, no xStock-token IBITx NE vypushchen na Solana.",
    },

    "GLDx": {
        "feed_id": "e190f467043db04548200354889dfe0d9d314c08b8d4e62fabf4d5a3140fecca",
        "symbol": "Equity.US.GLD/USD",
        "asset_type": "equity",
        "category": "etf_index",
        "variant": "main",
    },

    "SLVx": {
        "feed_id": "6fc08c9963d266069cbd9780d98383dabf2668322a5bef0b9491e11d67e5d7e7",
        "symbol": "Equity.US.SLV/USD",
        "asset_type": "equity",
        "category": "etf_index",
        "variant": "main",
        "note": "Pyth feed sushchestvuet. SLVx token - upcoming na Solana.",
    },
}

# ============================================================================
# PARCL PRICE FEEDS (vstroennye v Parcl Protocol, ne Pyth)
# ============================================================================

PARCL_PRICE_FEEDS = {
    "NYC": {
        "price_feed_address": "34AwhUntg33954iaEc3u8E9SxykhZouex8c6VPxRwsGh",
        "location_type": "CITY",
        "market_address": "8QLQf9mA9CC823KXyLRpLCpGbkDSkS4AdSv8LBoMfXjN",
        "market_id": 1,
    },
    "MIA": {
        "price_feed_address": "AYUxU9kYCuvPG6P4yWoSocxxrTkfHDmu6SKvzzRrP8Gt",
        "location_type": "CITY",
        "market_address": "AN6JFU7WCPSPnvuBC2Sznt3prBJPGHrsgirsMe3Z3rPu",
        "market_id": 15,
    },
}

# ============================================================================
# HERMES WEBSOCKET ENDPOINT (dlya real-time cen)
# ============================================================================

HERMES_WS_URL = "wss://hermes.pyth.network/ws"
HERMES_REST_URL = "https://hermes.pyth.network/v2/price_feeds"

# Pyth Program ID na Solana mainnet
PYTH_PROGRAM_ID = "FsJ3A3u2vn5cTVofAjvy6y5kwABJAqYWp49E5U4g9ZPY"

# ============================================================================
# PRIORITETNAYA OCHERED' (PriorityQueue)
# ============================================================================

# Pary sortirovany po ozhidaemoj pribylnosti (priority 1 = samyj zhirnyj)
PRIORITY_QUEUE_ORDER = [
    # Tier 1: Maksimalnyj profit (volatilnye + kripto-proxy)
    "MSTRx",   # MicroStrategy - dvigaetsya silnee BTC
    "NVDAx",   # NVIDIA - AI-hayp
    "TSLAx",   # Tesla - ekstremalne skachki
    "MARAx",   # Marathon - majnery, vysokaya beta
    "RIOTx",   # Riot - majnery
    # Tier 2: Vysokaya volatilnost
    "COINx",   # Coinbase - lag na novostyah
    "HOODx",   # Robinhood
    "AMZNx",   # Amazon - silnye na otchetah
    "GOOGLx",  # Google
    "METAx",   # Meta
    # Tier 3: Indeksy (Monday Open Gap)
    "SPYx",    # S&P 500
    "QQQx",    # Nasdaq 100
    "AAPLx",   # Apple - bolshaya likvidnost
    "MSFTx",   # Microsoft
    "GLDx",    # Gold - arbitrazh v vykhodnye
    "SLVx",    # Silver (esli token stanet dostupen)
    # Tier 4: RWA/Parcl
    "PRCL",    # Parcl token
    "NYC_INDEX",  # Parcl NYC
    "MIA_INDEX",  # Parcl Miami
]


def get_feed_id(ticker: str) -> str | None:
    """Poluchit' Pyth feed ID po tickeru."""
    feed = PYTH_FEEDS.get(ticker)
    if feed:
        return feed.get("feed_id")
    return None


def get_feeds_by_category(category: str) -> dict:
    """Poluchit' vse feedy opredelennoj kategorii."""
    return {k: v for k, v in PYTH_FEEDS.items() if v.get("category") == category}


def get_all_feed_ids() -> list[str]:
    """Poluchit' spisok vseh Pyth feed IDs."""
    return [v["feed_id"] for v in PYTH_FEEDS.values() if v.get("feed_id")]


def build_hermes_subscription(feed_ids: list[str]) -> list[dict]:
    """
    Postroit' payload dlya podpiski na Hermes WebSocket.

    Primer ispol'zovaniya:
        import websockets
        feeds = get_all_feed_ids()
        sub = build_hermes_subscription(feeds)
        async with websockets.connect(HERMES_WS_URL) as ws:
            await ws.send(json.dumps(sub))
    """
    return [
        {
            "type": "subscribe",
            "subscription_type": "price_feed_updates",
            "price_feed_ids": feed_ids,
        }
    ]


def get_active_feed_variant(ticker: str, current_time: datetime = None) -> str:
    """
    Get the currently active feed variant based on market hours (UTC).

    Args:
        ticker: xStock ticker (e.g., 'NVDAx')
        current_time: Current UTC time (defaults to now)

    Returns:
        Active variant: 'PRE', 'ON', or 'POST'
    """
    if current_time is None:
        current_time = datetime.utcnow()

    # US Market Hours (UTC)
    # Pre-market: 14:00 - 20:59 (2 hours before open)
    # Regular: 21:00 - 03:59 (9.5 hours)
    # After-hours: 04:00 - 07:59 (4 hours)
    # Weekend/Closed: All other times

    hour = current_time.hour

    if 14 <= hour < 21:  # 14:00-20:59 UTC = Pre-market
        return "PRE"
    elif 21 <= hour <= 23 or 0 <= hour < 4:  # 21:00-03:59 UTC = Regular hours
        return "ON"
    elif 4 <= hour < 8:  # 04:00-07:59 UTC = After-hours
        return "POST"
    else:
        # Weekend or closed - use regular hours feed as fallback
        return "ON"


def get_feed_id_with_variant(ticker: str, variant: str = None) -> str | None:
    """
    Get feed ID for ticker with automatic variant selection.

    Args:
        ticker: xStock ticker
        variant: Specific variant ('PRE', 'ON', 'POST') or None for auto-selection

    Returns:
        Feed ID string or None
    """
    if variant is None:
        variant = get_active_feed_variant(ticker)

    feed_key = f"{ticker}_{variant}" if variant != "ON" else ticker

    feed = PYTH_FEEDS.get(feed_key)
    if feed:
        return feed.get("feed_id")

    # Fallback to main feed if variant not found
    feed = PYTH_FEEDS.get(ticker)
    if feed:
        return feed.get("feed_id")

    return None


def check_price_latency(publish_time: int, max_latency_seconds: float = 1.0) -> bool:
    """
    Check if price update is within acceptable latency.

    Args:
        publish_time: Unix timestamp from Pyth
        max_latency_seconds: Maximum allowed latency

    Returns:
        True if fresh, False if stale
    """
    current_time = datetime.utcnow().timestamp()
    latency = current_time - publish_time

    return latency <= max_latency_seconds


def get_priority_queue_for_updates(updates: list) -> list:
    """
    Sort price updates by priority for processing.

    Priority order: MSTRx, NVDAx, TSLAx first, then others.

    Args:
        updates: List of price update dicts from Hermes

    Returns:
        Sorted list with high-priority updates first
    """
    def get_priority(feed_id: str) -> int:
        """Get processing priority for feed ID."""
        # Find ticker for this feed_id
        for ticker, info in PYTH_FEEDS.items():
            if info.get("feed_id") == feed_id:
                return info.get("priority", 99)
        return 99  # Default low priority

    return sorted(updates, key=lambda x: get_priority(x.get("price_feed_id", "")))


def get_high_priority_tickers() -> list[str]:
    """Get list of high-priority tickers for immediate processing."""
    return [ticker for ticker, info in PYTH_FEEDS.items()
            if info.get("priority", 99) <= 3]  # Top 3 priority levels


# ============================================================================
# KRATKAYA SVODKA
# ============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("  PYTH ORACLE STREAMS: STRATEGIYA ORACLE LAG")
    print("=" * 70)

    for category in ["magnificent_seven", "crypto_proxy", "etf_index"]:
        feeds = get_feeds_by_category(category)
        print(f"\n--- {category.upper()} ---")
        for ticker, info in feeds.items():
            print(f"  {ticker:12s} | {info['feed_id'][:16]}...{info['feed_id'][-8:]} | {info['symbol']}")

    print(f"\nVsego Pyth feedov: {len(PYTH_FEEDS)}")
    print(f"Hermes WS: {HERMES_WS_URL}")
    print(f"Pyth Program: {PYTH_PROGRAM_ID}")
    print(f"Priority order: {PRIORITY_QUEUE_ORDER[:5]}...")