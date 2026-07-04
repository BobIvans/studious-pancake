"""LST Fair Price Monitor — tracks on-chain fair price ratios for LST tokens.

Reads stake-pool state from Jito, Marinade and BlazeStake contracts to derive
the *theoretical* exchange rate of each LST vs SOL, then compares it to the
live market price fetched from Jupiter Price API.  When the deviation exceeds
a configurable threshold (default 15 BPS), a DepegSignal is emitted so the
arbitrage scanner can act.
Dynamic sizing: passes 95% of MarginFi vault liquidity to callback via
DepegSignal so the caller can run OptimalTradeSizer before committing capital.
"""

import asyncio
import base64
import logging
import struct
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Dict, List, Optional, Tuple, Any

import aiohttp

from src.ingest.pyth_core_price_feeder import get_pyth_core_feeder

logger = logging.getLogger("LstFairPrice")

# ── Known stake-pool / program addresses ─────────────────────────────────

# Jito Stake Pool (SPL Stake Pool layout)
JITO_STAKE_POOL = "Jito4APyf642JPZPx3hGc6WWJ8zPKtRbRs4P815Awbb"
JITOSOL_MINT    = "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn"

# Marinade State (custom layout)
MARINADE_STATE  = "8szGkuLTAux9XMgZ2vtY39jVSowEcpBfFfD8hXSEqdGC"
MSOL_MINT       = "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So"

# BlazeStake Pool (SPL Stake Pool layout)
BLAZE_STAKE_POOL = "stk9ApL5HeVAwPLr3TLhDXdZS8ptVu7zp6ov8HFDuMi"
BSOL_MINT        = "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1"

# Jupiter SOL mint
SOL_MINT = "So11111111111111111111111111111111111111112"

# Jupiter Price API
JUPITER_PRICE_URL = "https://api.jup.ag/price/v2"


@dataclass
class DepegSignal:
    """A signal indicating that an LST token has deviated from fair price."""
    token_symbol: str
    token_mint: str
    fair_price: float        # theoretical SOL value of 1 LST
    market_price: float      # live market SOL value of 1 LST
    deviation_bps: float     # signed: positive = LST undervalued on market
    direction: str           # "BUY_LST" if market < fair, "SELL_LST" if market > fair
    timestamp: float = field(default_factory=time.time)
    # Dynamic sizing: 95% of MarginFi vault (no hard cap)
    optimal_borrow_lamports: int = 0

    @property
    def abs_deviation_bps(self) -> float:
        return abs(self.deviation_bps)


class LstFairPriceMonitor:
    """Monitors on-chain fair price vs market price for LST tokens."""

    # SPL Stake Pool layout offsets (v0.7+)
    # total_lamports at offset 290 (u64), pool_token_supply at offset 298 (u64)
    # Fix: Original offsets 258/266 pointed at token_program_id (32-byte Pubkey),
    # not actual balances.  This caused garbage fair price ratios.
    _SPL_POOL_TOTAL_LAMPORTS_OFFSET = 290  # Phase 18: corrected from 258 to real on-chain offset
    _SPL_POOL_TOKEN_SUPPLY_OFFSET = 298

    # Marinade State layout (custom)
    # mSOL supply at offset 200 (u64), total_virtual_staked_lamports at offset 192 (u64)
    _MARINADE_TOTAL_LAMPORTS_OFFSET = 192
    _MARINADE_MSOL_SUPPLY_OFFSET = 200

    def __init__(
        self,
        session: aiohttp.ClientSession,
        rpc_url: str,
        poll_interval: float = 2.0,
        optimal_trade_sizer: Optional[Any] = None,
    ):
        self.session = session
        self.rpc_url = rpc_url
        self.poll_interval = poll_interval
        self.optimal_trade_sizer = optimal_trade_sizer

        # Cached fair-price ratios: mint -> ratio (SOL per 1 LST)
        self._fair_prices: Dict[str, float] = {}
        # Cached market prices: mint -> price in SOL
        self._market_prices: Dict[str, float] = {}
        # Last update timestamps
        self._last_fair_update: float = 0
        self._last_market_update: float = 0

        # Pool configs: (pool_address, mint, symbol, parser_method)
        self._pools = [
            (JITO_STAKE_POOL,  JITOSOL_MINT, "jitoSOL", self._parse_spl_stake_pool),
            (BLAZE_STAKE_POOL, BSOL_MINT,    "bSOL",    self._parse_spl_stake_pool),
            (MARINADE_STATE,   MSOL_MINT,     "mSOL",    self._parse_marinade_state),
        ]

    # ── Public API ────────────────────────────────────────────────────────

    async def _get_sanctum_fair_price(self, mint: str) -> Optional[float]:
        """Fetch fair price from Sanctum Router API (theoretical unstake rate)."""
        url = f"https://api.sanctum.so/v1/price?input={mint}&output={SOL_MINT}"
        try:
            async with self.session.get(url, timeout=2.0) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return float(data.get("price", 0))
        except Exception as e:
            logger.debug(f"Sanctum price fetch failed for {mint}: {e}")
        return None

    async def update_fair_prices(self) -> Dict[str, float]:
        """Fetch official protocol prices for all LSTs via Sanctum."""
        for _, mint, symbol, _ in self._pools:
            fair = await self._get_sanctum_fair_price(mint)
            if fair and fair > 0:
                self._fair_prices[mint] = fair
                logger.debug(f"Fair price {symbol}: {fair:.6f} SOL/LST (via Sanctum)")

        self._last_fair_update = time.time()
        return dict(self._fair_prices)

    async def update_market_prices(self, price_matrix: Optional[Dict[str, tuple]] = None) -> Dict[str, float]:
        """Fetch live market prices from in-memory price_matrix (PythCorePriceFeeder).

        CRITICAL FIX: Removed direct Jupiter API calls to prevent HTTP 429 rate limiting and IP blocking.
        Prices are now read from the shared price_matrix which is updated every ~400ms by PythCorePriceFeeder
        via WebSocket, eliminating the network overhead and rate limit issues.
        """
        if price_matrix is None:
            # Fallback: try to get from global feeder
            feeder = get_pyth_core_feeder()
            if feeder:
                price_matrix = feeder.as_price_matrix()
            else:
                price_matrix = {}

        mints = [p[1] for p in self._pools]
        sol_entry = price_matrix.get(SOL_MINT)

        if sol_entry and sol_entry[0] > 0:
            sol_usd_price = sol_entry[0]
            for mint in mints:
                token_entry = price_matrix.get(mint)
                if token_entry and token_entry[0] > 0:
                    # Convert USD price to SOL equivalent (price_matrix stores USD prices)
                    self._market_prices[mint] = token_entry[0] / sol_usd_price

        self._last_market_update = time.time()
        return dict(self._market_prices)

    def get_depeg_signals(self, threshold_bps: float = 50.0) -> List[DepegSignal]:
        """Compare fair prices to market prices and return depeg signals."""
        # FIX 152: Sanctum API outage protection (TTL check)
        if time.time() - self._last_fair_update > 300.0:
            logger.warning("🚫 Sanctum fair price cache expired (>300s old) — ignoring depeg signals to prevent trading blind")
            return []
        signals = []
        for pool_addr, mint, symbol, _ in self._pools:
            fair = self._fair_prices.get(mint)
            market = self._market_prices.get(mint)
            if fair is None or market is None or fair == 0:
                continue

            deviation_bps = ((fair - market) / fair) * 10000
            if abs(deviation_bps) >= threshold_bps:
                direction = "BUY_LST" if deviation_bps > 0 else "SELL_LST"
                signals.append(DepegSignal(
                    token_symbol=symbol,
                    token_mint=mint,
                    fair_price=fair,
                    market_price=market,
                    deviation_bps=deviation_bps,
                    direction=direction,
                ))

        # Sort by absolute deviation descending (biggest opportunity first)
        signals.sort(key=lambda s: s.abs_deviation_bps, reverse=True)
        return signals

    async def subscribe_to_depeg(
        self,
        callback: Callable[[DepegSignal], None],
        threshold_bps: float = 50.0,
        interval: float = 0.5,
    ):
        """Continuously monitor for depeg opportunities and invoke callback."""
        logger.info(
            f"📡 LST Fair Price Monitor started | threshold={threshold_bps} BPS | "
            f"interval={interval}s | pools={len(self._pools)}"
        )
        while True:
            try:
                await self.update_fair_prices()
                # Get price_matrix from PythCorePriceFeeder (updated every ~400ms via WebSocket)
                feeder = get_pyth_core_feeder()
                price_matrix = feeder.as_price_matrix() if feeder else {}
                await self.update_market_prices(price_matrix)
                signals = self.get_depeg_signals(threshold_bps)

                if signals:
                    # Dynamic sizing: fetch 95% of MarginFi SOL vault, pass to OptimalTradeSizer
                    # antes de cada señal para evitar slips excesivos (Step 2 — динамический сайзинг)
                    sol_mint_str = str(SOL_MINT)
                    from src.ingest.shared_state import MARGINFI_BANKS
                    sol_bank_vault = (
                        str(MARGINFI_BANKS[sol_mint_str]["liquidity_vault"])
                        if sol_mint_str in MARGINFI_BANKS
                        else None
                    )
                    vault_lamports = 0
                    if sol_bank_vault and self.optimal_trade_sizer:
                        try:
                            payload = {
                                "jsonrpc": "2.0", "id": 1,
                                "method": "getTokenAccountBalance",
                                "params": [sol_bank_vault],
                            }
                            async with self.session.post(
                                self.rpc_url, json=payload, timeout=aiohttp.ClientTimeout(total=2.0)
                            ) as r2:
                                if r2.status == 200:
                                    d = await r2.json()
                                    vault_lamports = int(d["result"]["value"]["amount"])
                        except Exception as e:
                            logger.debug(f"MarginFi SOL vault fetch failed: {e}")

                    for sig in signals:
                        # OptimalTradeSizer: O(1) analytical formula — no iterative search
                        borrow_lamports = 0
                        if vault_lamports > 0 and self.optimal_trade_sizer:
                            borrow_lamports = int(
                                self.optimal_trade_sizer.find_optimal_trade_size(
                                    routes=[],                    # routes resolved later in scanner
                                    amount_in=int(vault_lamports * 0.95),
                                    decimals_in=9, decimals_out=9,
                                    jito_tip_sol=0.0001,
                                )
                            )
                        sig.optimal_borrow_lamports = borrow_lamports

                        logger.info(
                            f"🔔 DEPEG {sig.token_symbol}: "
                            f"fair={sig.fair_price:.6f} market={sig.market_price:.6f} "
                            f"dev={sig.deviation_bps:+.1f}bps → {sig.direction} "
                            f"| optimal_borrow={borrow_lamports/1e9:.4f} SOL"
                        )
                        await callback(sig) if asyncio.iscoroutinefunction(callback) else callback(sig)
            except Exception as e:
                logger.warning(f"Depeg monitor error: {e}")
            await asyncio.sleep(interval)

    def get_status(self) -> Dict:
        """Return current monitor status for logging."""
        return {
            "fair_prices": {
                next((s for _, m, s, _ in self._pools if m == mint), mint[:8]): round(price, 6)
                for mint, price in self._fair_prices.items()
            },
            "market_prices": {
                next((s for _, m, s, _ in self._pools if m == mint), mint[:8]): round(price, 6)
                for mint, price in self._market_prices.items()
            },
            "last_fair_update": self._last_fair_update,
            "last_market_update": self._last_market_update,
        }

    # ── On-chain parsers ──────────────────────────────────────────────────

    def _parse_spl_stake_pool(self, raw_bytes: bytes, symbol: str) -> Optional[float]:
        """Parse SPL Stake Pool account data to derive fair price.

        On-chain fallback when Sanctum API is unavailable.
        SPL Stake Pool layout (v0.7+):
          - total_lamports at offset 258 (u64, 8 bytes)
          - pool_token_supply at offset 266 (u64, 8 bytes)
        Fair price = total_lamports / pool_token_supply (SOL per 1 LST)
        """
        try:
            # FIX 204: Корректная проверка размера структуры SPL Stake Pool (минимум 306 байт для смещения 298)
            if len(raw_bytes) < 306:
                logger.debug(f"{symbol}: raw_bytes too short ({len(raw_bytes)}) for SPL Stake Pool parsing")
                return None

            total_lamports = struct.unpack_from('<Q', raw_bytes, self._SPL_POOL_TOTAL_LAMPORTS_OFFSET)[0]
            token_supply = struct.unpack_from('<Q', raw_bytes, self._SPL_POOL_TOKEN_SUPPLY_OFFSET)[0]

            if total_lamports == 0 or token_supply == 0:
                return None

            fair_price = total_lamports / token_supply
            logger.debug(f"{symbol}: on-chain fair price = {fair_price:.6f} SOL/LST "
                         f"(lamports={total_lamports}, supply={token_supply})")
            return fair_price
        except Exception as e:
            logger.warning(f"{symbol}: SPL Stake Pool parsing failed: {e}")
            return None

    def _parse_marinade_state(self, raw_bytes: bytes, symbol: str) -> Optional[float]:
        """Parse Marinade State account data to derive fair price.

        On-chain fallback when Sanctum API is unavailable.
        Marinade State layout:
          - total_virtual_staked_lamports at offset 192 (u64, 8 bytes)
          - mSOL supply at offset 200 (u64, 8 bytes)
        Fair price = total_virtual_staked_lamports / mSOL_supply
        """
        try:
            if len(raw_bytes) < 208:
                logger.debug(f"{symbol}: raw_bytes too short ({len(raw_bytes)}) for Marinade parsing")
                return None

            total_lamports = struct.unpack_from('<Q', raw_bytes, self._MARINADE_TOTAL_LAMPORTS_OFFSET)[0]
            msol_supply = struct.unpack_from('<Q', raw_bytes, self._MARINADE_MSOL_SUPPLY_OFFSET)[0]

            if total_lamports == 0 or msol_supply == 0:
                return None

            fair_price = total_lamports / msol_supply
            logger.debug(f"{symbol}: on-chain fair price = {fair_price:.6f} SOL/LST "
                         f"(lamports={total_lamports}, msol_supply={msol_supply})")
            return fair_price
        except Exception as e:
            logger.warning(f"{symbol}: Marinade parsing failed: {e}")
            return None

    # ── RPC helpers ───────────────────────────────────────────────────────

    async def _get_multiple_accounts(self, addresses: List[str]) -> Dict[str, Optional[bytes]]:
        """Fetch multiple accounts in a single RPC call."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getMultipleAccounts",
            "params": [
                addresses,
                {"encoding": "base64", "commitment": "confirmed"}
            ]
        }
        result_map: Dict[str, Optional[bytes]] = {a: None for a in addresses}

        for attempt in range(3):  # Retry up to 3 times
            try:
                timeout = aiohttp.ClientTimeout(total=3.0)
                async with self.session.post(self.rpc_url, json=payload, timeout=timeout) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if "result" in data and "value" in data["result"]:
                            for i, account_info in enumerate(data["result"]["value"]):
                                if account_info and account_info.get("data"):
                                    # Fix #5: Add proper base64 padding before decoding.
                                    # Some RPC nodes return base64 without trailing '='.
                                    b64_string = account_info["data"][0]
                                    padded = b64_string + "=" * (-len(b64_string) % 4)
                                    raw = base64.b64decode(padded)
                                    result_map[addresses[i]] = raw
                        break  # Success, exit retry loop
                    else:
                        logger.warning(f"getMultipleAccounts failed (attempt {attempt+1}): HTTP {resp.status}")
            except Exception as e:
                logger.warning(f"getMultipleAccounts RPC error (attempt {attempt+1}): {e}")

            if attempt < 2:  # Don't sleep after last attempt
                await asyncio.sleep(0.5 * (attempt + 1))  # Exponential backoff

        return result_map
