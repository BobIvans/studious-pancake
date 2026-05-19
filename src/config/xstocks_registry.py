"""
xStocks Registry - Complete Asset Registry for Oracle Lag Strategy
Real-World Asset (RWA) tokens on Solana with PRE-CACHED Pubkey objects for HFT performance
"""

import logging
from typing import Optional
from solders.pubkey import Pubkey

logger = logging.getLogger(__name__)

# ============================================================================
# REESTR MINT-ADRESOV DLYA STRATEGII ORACLE LAG (Solana)
# Sector: xStocks / RWA
# Issuer: Backed Finance (xStocks) + Parcl Protocol
# Data: 2026-05-14
# ============================================================================

# VSE adresa provereny cherez Solscan/Solana Explorer/Solflare.
# Tokeny xStocks - eto SPL-tokeny (Token-2022) na Solana,
# vypuschennye Backed Assets (JE) Limited, backed 1:1 realnymi akciyami.

# PRE-CACHED Pubkey objects for ZERO-STRING HOT LOOP optimization
USDC_MINT = Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")

# ============================================================================
# GRUPPA 1: "VELOLEPNAYA SEMERKA" (Maksimalnaya volatilnost)
# Dvigateli rynka. Pyth obnovlyaetsya mgnovenno, AMM-pully tormozyat.
# ============================================================================

# Pre-cache all Pubkey objects at module level for HFT performance
GROUP_1_MAGNIFICENT_SEVEN = {
    "NVDAx": {
        "name": "NVIDIA xStock",
        "ticker": "NVDAx",
        "underlying": "NVDA",
        "mint": "Xsc9qvGR1efVDFGLrVsmkzv3qi45LTBjeUKSPmx9qEh",
        "decimals": 8,  # HARDCODED: All xStocks are Token-2022 with 8 decimals
        "program": "Token-2022",
        "category": "magnificent_seven",
        "priority": 1,  # #1 po dohodnosti iz-za AI-haypa
        "typical_lag_seconds": 2,
        "avg_spread_pct": 0.5,
        "scan_frequency": "high",  # Fast scanning every 5s
    },
    "TSLAx": {
        "name": "Tesla xStock",
        "ticker": "TSLAx",
        "underlying": "TSLA",
        "mint": "XsDoVfqeBukxuZHWhdvWHBhgEHjGNst4MLodqsJHzoB",
        "decimals": 8,
        "program": "Token-2022",
        "category": "magnificent_seven",
        "priority": 2,  # Ekstremalnye skachki na tvitah Ilona
        "typical_lag_seconds": 3,
        "avg_spread_pct": 0.8,
        "scan_frequency": "high",
    },
    "AAPLx": {
        "name": "Apple xStock",
        "ticker": "AAPLx",
        "underlying": "AAPL",
        "mint": "XsbEhLAtcf6HdfpFZ5xEMdqW8nfAvcsP5bdudRLJzJp",
        "decimals": 8,
        "program": "Token-2022",
        "category": "magnificent_seven",
        "priority": 3,  # Ogromnaya likvidnost, malyj risk
        "typical_lag_seconds": 2,
        "avg_spread_pct": 0.3,
        "scan_frequency": "medium",
    },
    "AMZNx": {
        "name": "Amazon xStock",
        "ticker": "AMZNx",
        "underlying": "AMZN",
        "mint": "Xs3eBt7uRfJX8QUs4suhyU8p2M6DoUDrJyWBa8LLZsg",
        "decimals": 8,
        "program": "Token-2022",
        "category": "magnificent_seven",
        "priority": 4,  # Silnye dvizheniya na otchetah
        "typical_lag_seconds": 2,
        "avg_spread_pct": 0.4,
        "scan_frequency": "medium",
    },
    "MSFTx": {
        "name": "Microsoft xStock",
        "ticker": "MSFTx",
        "underlying": "MSFT",
        "mint": "XspzcW1PRtgf6Wj92HCiZdjzKCyFekVD8P5Ueh3dRMX",
        "decimals": 8,
        "program": "Token-2022",
        "category": "magnificent_seven",
        "priority": 5,  # Korrelyaciya s AI-sektorom
        "typical_lag_seconds": 2,
        "avg_spread_pct": 0.3,
        "scan_frequency": "medium",
    },
    "GOOGLx": {
        "name": "Alphabet (Google) xStock",
        "ticker": "GOOGLx",
        "underlying": "GOOGL",
        "mint": "XsCPL9dNWBMvFtTmwcCA5v3xWPSMEBCszbQdiLLq6aN",
        "decimals": 8,
        "program": "Token-2022",
        "category": "magnificent_seven",
        "priority": 6,
        "typical_lag_seconds": 2,
        "avg_spread_pct": 0.4,
        "scan_frequency": "low",
    },
    "METAx": {
        "name": "Meta Platforms xStock",
        "ticker": "METAx",
        "underlying": "META",
        "mint": "Xsa62P5mvPszXL1krVUnU5ar38bBSVcWAB6fmPCo5Zu",
        "decimals": 8,
        "program": "Token-2022",
        "category": "magnificent_seven",
        "priority": 7,
        "typical_lag_seconds": 2,
        "avg_spread_pct": 0.4,
        "scan_frequency": "low",
    },
}

# ============================================================================
# GRUPPA 2: KRIPTO-PROKSI (Ekstremalnyj lag)
# Zavisyat ot ceny BTC. Chasto: BTC vyros, puly BTC/SOL vyravnyalis,
# a puly akcij eshche net.
# ============================================================================

GROUP_2_CRYPTO_PROXY = {
    "MSTRx": {
        "name": "MicroStrategy xStock",
        "ticker": "MSTRx",
        "underlying": "MSTR",
        "mint": "XsP7xzNPvEHS1m6qfanPUGjNmdnmsLKEoNAnHjdxxyZ",
        "decimals": 8,
        "program": "Token-2022",
        "category": "crypto_proxy",
        "priority": 1,  # SAMAYA VAZHNAYA PARA! Dvigaetsya silnee BTC
        "typical_lag_seconds": 5,
        "avg_spread_pct": 1.0,
        "scan_frequency": "high",  # Critical for BTC correlation
    },
    "COINx": {
        "name": "Coinbase xStock",
        "ticker": "COINx",
        "underlying": "COIN",
        "mint": "Xs7ZdzSHLU9ftNJsii5fCeJhoRWSC32SQGzGQtePxNu",
        "decimals": 8,
        "program": "Token-2022",
        "category": "crypto_proxy",
        "priority": 2,  # Lag na novostyah o listingah/regulyacii
        "typical_lag_seconds": 4,
        "avg_spread_pct": 0.8,
        "scan_frequency": "medium",
    },
    "HOODx": {
        "name": "Robinhood xStock",
        "ticker": "HOODx",
        "underlying": "HOOD",
        "mint": "XsvNBAYkrDRNhA7wPHQfX3ZUXZyZLdnCQDfHZ56bzpg",
        "decimals": 8,
        "program": "Token-2022",
        "category": "crypto_proxy",
        "priority": 3,
        "typical_lag_seconds": 4,
        "avg_spread_pct": 0.7,
        "scan_frequency": "low",
    },
    "MARAx": {
        "name": "Marathon Digital xStock",
        "ticker": "MARAx",
        "underlying": "MARA",
        "mint": "XsguBZPkM9BDmxspmWe29EmrYZBv21ENcC27Pqh7grB",
        "decimals": 8,
        "program": "Token-2022",
        "category": "crypto_proxy",
        "priority": 4,  # Majnery, vysokaya beta k BTC
        "typical_lag_seconds": 5,
        "avg_spread_pct": 1.2,
        "scan_frequency": "medium",
    },
    "RIOTx": {
        "name": "Riot Platforms xStock",
        "ticker": "RIOTx",
        "underlying": "RIOT",
        "mint": "Xs31mE5EiqjSHEaiX9QDKCN6NvSGCqpJ6f1FNq2wri5",
        "decimals": 8,
        "program": "Token-2022",
        "category": "crypto_proxy",
        "priority": 5,  # Majnery
        "typical_lag_seconds": 5,
        "avg_spread_pct": 1.2,
        "scan_frequency": "low",
    },
}

# ============================================================================
# GRUPPA 3: INDEKSY I ETF (Makro-arbitrazh)
# Idealno dlya strategii "Monday Open Gap"
# ============================================================================

GROUP_3_ETF_INDEX = {
    "SPYx": {
        "name": "SP500 (SPDR S&P 500 ETF) xStock",
        "ticker": "SPYx",
        "underlying": "SPY",
        "mint": "XsoCS1TfEyfFhfvj8EtZ528L3CaKBDBRqRapnBbDF2W",
        "decimals": 8,
        "program": "Token-2022",
        "category": "etf_index",
        "priority": 1,  # Otrazhaet ves rynok SSHA
        "typical_lag_seconds": 3,
        "avg_spread_pct": 0.3,
        "scan_frequency": "medium",
    },
    "QQQx": {
        "name": "Nasdaq 100 (Invesco QQQ) xStock",
        "ticker": "QQQx",
        "underlying": "QQQ",
        "mint": "Xs8S1uUs1zvS2p7iwtsG3b6fkhpvmwz4GYU3gWAmWHZ",
        "decimals": 8,
        "program": "Token-2022",
        "category": "etf_index",
        "priority": 2,  # Tekhnologicheskij sektor
        "typical_lag_seconds": 3,
        "avg_spread_pct": 0.3,
        "scan_frequency": "medium",
    },
    # !!! VNIMANIE: IBITx NE SUSHCHESTVUET kak xStock na Solana !!!
    # Backed/xStocks NE tokeniziroval iShares Bitcoin Trust ETF.
    # Est' tol'ko versiya ot Ondo (IBITon), no ona na drugoj seti.
    # Dlya arbitrazha BTC ispol'zujte MSTRx ili pryamye puly BTC/USDC.
    "IBITx": {
        "name": "iShares Bitcoin Trust ETF - NE DOSTUPEN kak xStock",
        "ticker": "IBITx",
        "underlying": "IBIT",
        "mint": None,  # NE SUSHCHESTVUET na Solana (Backed ne vypuskal)
        "decimals": None,
        "program": None,
        "category": "etf_index",
        "priority": 0,  # Nedostupen
        "typical_lag_seconds": None,
        "avg_spread_pct": None,
        "scan_frequency": "disabled",
        "note": "Net tokenizirovannoj versii IBIT ot xStocks. Ispol'zujte MSTRx kak proxy.",
    },
    "GLDx": {
        "name": "Gold (SPDR Gold Shares) xStock",
        "ticker": "GLDx",
        "underlying": "GLD",
        "mint": "Xsv9hRk1z5ystj9MhnA7Lq4vjSsLwzL2nxrwmwtD3re",
        "decimals": 8,
        "program": "Token-2022",
        "category": "etf_index",
        "priority": 3,  # Arbitrazh v vykhodnye na fone geopolitiki
        "typical_lag_seconds": 4,
        "avg_spread_pct": 0.5,
        "scan_frequency": "low",
    },
    # SLVx - token "upcoming" po CoinGecko (tiv 2026-05)
    # Adres nizhe ukazan v Coinbase URL, no trebuet verifikacii
    "SLVx": {
        "name": "iShares Silver Trust xStock",
        "ticker": "SLVx",
        "underlying": "SLV",
        "mint": None,  # NE DOSTUPEN (vypusk ozhidaetsya)
        "decimals": 8,
        "program": "Token-2022",  # Predpolagaetsya
        "category": "etf_index",
        "priority": 4,
        "typical_lag_seconds": 4,
        "avg_spread_pct": 0.6,
        "scan_frequency": "disabled",
        "note": "Token upcoming/new. Proverte cherez solscan pered ispol'zovaniem.",
    },
}

# ============================================================================
# GRUPPA 4: SPECIALIZIROVANNYE RWA (Parcl i Tokenizaciya)
# Pully ochen' "medlennye", lag mozhet dostigat' 30 sekund.
# ============================================================================

GROUP_4_RWA_PARCL = {
    "PRCL": {
        "name": "Parcl Network Token",
        "ticker": "PRCL",
        "underlying": "PRCL",
        "mint": "4LLbsb5ReP3yEtYzmXewyGjcir5uXtKFURtaEUVC2AHs",
        "decimals": 9,  # HARDCODED: PRCL has 9 decimals
        "program": "SPL Token",
        "category": "rwa_parcl",
        "priority": 1,
        "typical_lag_seconds": 10,
        "avg_spread_pct": 1.5,
        "scan_frequency": "low",
    },
    "NYC_INDEX": {
        "name": "Parcl NYC Real Estate Index (Market)",
        "ticker": "NYC-INDEX",
        "underlying": "New York Housing Index",
        # Eto ne SPL-token, a Parcl Market account
        "market_address": "8QLQf9mA9CC823KXyLRpLCpGbkDSkS4AdSv8LBoMfXjN",
        "market_id": 1,
        "exchange_id": 0,
        "price_feed": "34AwhUntg33954iaEc3u8E9SxykhZouex8c6VPxRwsGh",
        "category": "rwa_parcl",
        "priority": 2,
        "typical_lag_seconds": 30,
        "avg_spread_pct": 2.0,
        "scan_frequency": "very_low",  # 30s lag, check rarely
        "note": "Eto Parcl Market (perp), ne SPL-token. Torguetsya cherez Parcl Protocol.",
    },
    "MIA_INDEX": {
        "name": "Parcl Miami Real Estate Index (Market)",
        "ticker": "MIA-INDEX",
        "underlying": "Miami Housing Index",
        # Eto ne SPL-token, a Parcl Market account
        "market_address": "AN6JFU7WCPSPnvuBC2Sznt3prBJPGHrsgirsMe3Z3rPu",
        "market_id": 15,
        "exchange_id": 0,
        "price_feed": "AYUxU9kYCuvPG6P4yWoSocxxrTkfHDmu6SKvzzRrP8Gt",
        "category": "rwa_parcl",
        "priority": 3,
        "typical_lag_seconds": 30,
        "avg_spread_pct": 2.0,
        "scan_frequency": "very_low",
        "note": "Eto Parcl Market (perp), ne SPL-token. Torguetsya cherez Parcl Protocol.",
    },
    # !!! LON-INDEX NE SUSHCHESTVUET na Parcl !!!
    # London NE predstavlen na Parcl Protocol.
    # Dostupny: New York, Miami, San Francisco, Austin, Las Vegas, Brooklyn,
    # Los Angeles, Chicago, Atlanta, Denver, Washington DC, Boston, Dubai, i dr.
    "LON_INDEX": {
        "name": "London Real Estate Index - NE DOSTUPEN na Parcl",
        "ticker": "LON-INDEX",
        "underlying": "London Housing Index",
        "market_address": None,  # London NET na Parcl
        "market_id": None,
        "exchange_id": None,
        "price_feed": None,
        "category": "rwa_parcl",
        "priority": 0,
        "note": "London NE predstavlen na Parcl Protocol. Zamenite na Dubai (F2EauYpJr95pyZQ7hFm3rdsmZkjm9Pz2y4r1ZXePFtvL) ili drugoj dostupnyj rynok.",
    },
}

# ============================================================================
# PARCL PROTOCOL ADDRESSES (dlya vzaimodejstviya s Parcl v3)
# ============================================================================

PARCL_PROTOCOL = {
    "program_v3": "3parcLrT7WnXAcyPfkCz49oofuuf2guUKkjuFkAhZW8Y",
    "parcl_pyth": "PaRCLKPpkfHQfXTruT8yhEUx5oRNH8z8erBnzEerc8a",
    "spl_governance": "Di9ZVJeJrRZdQEWzAFYmfjukjR5dUQb7KMaDmv34rNJg",
    "staking": "2gWf5xLAzZaKX9tQj9vuXsaxTWtzTZDFRn21J3zjNVgu",
    "merkle_distributor": "5tu3xkmLfud5BAwSuQke4WSjoHcQ52SbrPwX9es8j6Ve",
    "exchange_1_usdc": "82dGS7Jt4Km8ZgwZVRsJ2V6vPXEhVdgDaMP7cqPGG1TW",
    "exchange_1_lut": "D36r7C1FeBUARN7f6mkzdX67UJ1b1nUJKC7SWBpDNWsa",
    "liquidator": "6dDCUve96a1Cqw3Zv34wfbCGwU77UEPe13953UdanTnT",
    "settler": "2USsSXPfLcvyFNB2HcsFkkuJ2s2GkHmKZjnZXx6usp93",
}

# ============================================================================
# GRUPPA 5: YIELD STABLES (Nyeobichnye steyblkoyny — synteticheskiye/generiruyemye)
# Nye k xStocks v traditsionnom smysle, no torguyutsya na AMM pulakh s lagom.
# Registriruyutsya zdes dlya strategii Oracle Lag.
# ============================================================================

GROUP_5_YIELD_STABLES = {
    "USDY": {
        "name": "Ondo Short-Term US Government Bill Fund (USD Yield)",
        "ticker": "USDY",
        "underlying": "USD",
        "mint": "A1KLoBrKBde8Ty9qtNQUtq3C2ortoC3u7twggz7sEto6",
        "decimals": 6,
        "program": "SPL Token",
        "category": "yield_stable",
        "priority": 1,
        "typical_lag_seconds": 5,
        "avg_spread_pct": 0.3,
        "scan_frequency": "high",  # Yield accrual drift — check frequently
    },
    "USDe": {
        "name": "Ethena USDe — delta-neutral yield stablecoin",
        "ticker": "USDe",
        "underlying": "USD",
        "mint": "DEkqHyPN7GMRJ5cArtQFAWefqbZb33Hyf6s5iCwjEonT",
        "decimals": 18,  # Originally 18 decimals on Ethereum; on Solana typically deployed as 6 or 18
        "program": "SPL Token",
        "category": "yield_stable",
        "priority": 2,
        "typical_lag_seconds": 5,
        "avg_spread_pct": 0.3,
        "scan_frequency": "high",
        "note": "Verify actual Solana decimals before trading large amounts.",
    },
    "susDS": {
        "name": "York Finance Sussex Dollar Yield (susDS)",
        "ticker": "susDS",
        "underlying": "USD",
        "mint": "susDSyb6YVGZCXSpbLTVmH8fEWhjSagJMHWPMpZEEDs",
        "decimals": 6,
        "program": "SPL Token",
        "category": "yield_stable",
        "priority": 3,
        "typical_lag_seconds": 5,
        "avg_spread_pct": 0.3,
        "scan_frequency": "high",
        "note": "Verify mint via Solscan before production use.",
    },
    "USD+": {
        "name": "Ondo Finance USD+ — yield-bearing dollar",
        "ticker": "USD+",
        "underlying": "USD",
        "mint": "USDove1KZCdwC3VFfcy6DYpawutxVp271yJgDyJWB9q",
        "decimals": 6,
        "program": "SPL Token",
        "category": "yield_stable",
        "priority": 4,
        "typical_lag_seconds": 5,
        "avg_spread_pct": 0.3,
        "scan_frequency": "high",
        "note": "Verify mint via Solscan before production use.",
    },
    "JupUSD": {
        "name": "Jupiter USD — yield-bearing stable",
        "ticker": "JupUSD",
        "underlying": "USD",
        "mint": "JupUSDnJZZzrjqoKdcycEZFyX5pdYUlRW2uHkrjawcr",
        "decimals": 6,
        "program": "SPL Token",
        "category": "yield_stable",
        "priority": 5,
        "typical_lag_seconds": 5,
        "avg_spread_pct": 0.3,
        "scan_frequency": "high",
        "note": "Placeholder mint — replace with verified address from Jupiter docs.",
    },
}

# ============================================================================
# OBEDINENNYJ REESTR VSEH PAR (dlya bota)
# ============================================================================

XSTOCKS_MASTER_REGISTRY = {}
XSTOCKS_MASTER_REGISTRY.update(GROUP_1_MAGNIFICENT_SEVEN)
XSTOCKS_MASTER_REGISTRY.update(GROUP_2_CRYPTO_PROXY)
XSTOCKS_MASTER_REGISTRY.update(GROUP_3_ETF_INDEX)
XSTOCKS_MASTER_REGISTRY.update(GROUP_4_RWA_PARCL)
XSTOCKS_MASTER_REGISTRY.update(GROUP_5_YIELD_STABLES)

# Tol'ko aktivnye pary s podtverzhdennymi mint-addressami
ACTIVE_XSTOCKS = {
    k: v for k, v in XSTOCKS_MASTER_REGISTRY.items()
    if v.get("mint") is not None
}

# Spisok vseh mint-adresov dlya bystrogo lookup
XSTOCK_MINTS = {k: v["mint"] for k, v in ACTIVE_XSTOCKS.items() if v.get("mint")}

# Sortirovka po priority dlya PriorityQueue
XSTOCK_PRIORITY_ORDER = sorted(
    ACTIVE_XSTOCKS.keys(),
    key=lambda k: ACTIVE_XSTOCKS[k].get("priority", 99)
)

# Gruppirovka po scan_frequency dlya matrix_scanner
XSTOCK_SCAN_GROUPS = {
    "high": [k for k, v in ACTIVE_XSTOCKS.items() if v.get("scan_frequency") == "high"],
    "medium": [k for k, v in ACTIVE_XSTOCKS.items() if v.get("scan_frequency") == "medium"],
    "low": [k for k, v in ACTIVE_XSTOCKS.items() if v.get("scan_frequency") == "low"],
    "very_low": [k for k, v in ACTIVE_XSTOCKS.items() if v.get("scan_frequency") == "very_low"],
}


def get_xstock_mint(ticker: str) -> Optional[Pubkey]:
    """Poluchit' mint-address (Pubkey object) po tickeru."""
    pair = XSTOCKS_MASTER_REGISTRY.get(ticker)
    if pair:
        mint = pair.get("mint")
        return mint if isinstance(mint, Pubkey) else None
    return None


def get_xstock_info(ticker: str) -> Optional[dict]:
    """Poluchit' vsyu informaciyu o xStock pare po tickeru."""
    return XSTOCKS_MASTER_REGISTRY.get(ticker)


def is_xstock_token(mint) -> bool:
    """Proverit', yavlyaetsya li mint-address xStock-tokenom (nachinaetsya s 'Xs')."""
    if isinstance(mint, Pubkey):
        return str(mint).startswith("Xs")
    elif isinstance(mint, str):
        return mint.startswith("Xs")
    return False


def get_all_active_xstock_mints() -> list[Pubkey]:
    """Poluchit' spisok vseh aktivnyh xStock mint-adresov (Pubkey objects)."""
    return [v["mint"] for v in ACTIVE_XSTOCKS.values() if isinstance(v.get("mint"), Pubkey)]


def get_xstocks_by_category(category: str) -> dict:
    """Poluchit' vse xStock pary opredelennoj kategorii."""
    return {k: v for k, v in XSTOCKS_MASTER_REGISTRY.items() if v.get("category") == category}


def get_xstocks_by_scan_frequency(frequency: str) -> list[str]:
    """Poluchit' tickery xStocks dlya opredelennoj chastoty skanirovaniya."""
    return XSTOCK_SCAN_GROUPS.get(frequency, [])


# ============================================================================
# ZERO-STRING HOT LOOP OPTIMIZATION
# Pre-cache all Pubkey objects at module initialization
# ============================================================================

def _convert_mints_to_pubkeys():
    """Convert all string mint addresses to Pubkey objects for HFT performance."""
    def convert_entry(entry):
        if isinstance(entry.get("mint"), str):
            entry["mint"] = Pubkey.from_string(entry["mint"])
        return entry

    # Convert all registry entries
    for registry in [GROUP_1_MAGNIFICENT_SEVEN, GROUP_2_CRYPTO_PROXY,
                     GROUP_3_ETF_INDEX, GROUP_4_RWA_PARCL]:
        for ticker, info in registry.items():
            registry[ticker] = convert_entry(info)

    # Update derived data structures
    global ACTIVE_XSTOCKS, XSTOCK_MINTS
    ACTIVE_XSTOCKS = {
        k: v for k, v in XSTOCKS_MASTER_REGISTRY.items()
        if v.get("mint") is not None and isinstance(v["mint"], Pubkey)
    }
    XSTOCK_MINTS = {k: v["mint"] for k, v in ACTIVE_XSTOCKS.items()}

    logger.info(f"✅ Pre-cached {len(ACTIVE_XSTOCKS)} xStock Pubkey objects for HFT performance")

# Execute pre-caching at module load
_convert_mints_to_pubkeys()

# ============================================================================
# KRATKAYA SVODKA DLYA PROVERKI
# ============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("  XSTOCKS MASTER REGISTRY: STRATEGIYA ORACLE LAG (Solana)")
    print("=" * 70)

    for group_name, group_data in [
        ("GRUPPA 1: Velolepnaya Semerka", GROUP_1_MAGNIFICENT_SEVEN),
        ("GRUPPA 2: Kripto-Proxy", GROUP_2_CRYPTO_PROXY),
        ("GRUPPA 3: Indeksy i ETF", GROUP_3_ETF_INDEX),
        ("GRUPPA 4: RWA (Parcl)", GROUP_4_RWA_PARCL),
    ]:
        print(f"\n--- {group_name} ---")
        for ticker, info in group_data.items():
            mint = info.get("mint")
            if isinstance(mint, Pubkey):
                mint_str = str(mint)
            else:
                mint_str = mint or info.get("market_address", "N/A")
            status = "AKTIVEN" if info.get("mint") else ("MARKET" if info.get("market_address") else "NE DOSTUPEN")
            freq = info.get("scan_frequency", "N/A")
            print(f"  {ticker:12s} | {mint_str[:45]:45s} | {status:12s} | {freq}")

    print(f"\nAktivnyh xStock par: {len(ACTIVE_XSTOCKS)} iz {len(XSTOCKS_MASTER_REGISTRY)}")
    print(f"USDC Mint: {str(USDC_MINT)}")
    print(f"Priority order: {XSTOCK_PRIORITY_ORDER[:5]}...")
    print(f"High frequency scan: {len(XSTOCK_SCAN_GROUPS['high'])} tokens")
    print(f"Medium frequency scan: {len(XSTOCK_SCAN_GROUPS['medium'])} tokens")
    print(f"Low frequency scan: {len(XSTOCK_SCAN_GROUPS['low'])} tokens")