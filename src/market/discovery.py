"""Bounded read-only market discovery through the existing JSON transport.

Discovered pools are metadata, never price observations or executable edges.
The caller supplies its governed Transport; this module creates no HTTP client,
credentials, scheduler, subscriptions or background task.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any

from src.config.chain_registry import validate_pubkey
from src.routing.transport import Transport

from .source_catalog import MarketSourceCatalog, SourceAccess


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class DiscoveryRequest:
    source_id: str
    page: int = 1
    token_mint: str | None = None

    def __post_init__(self) -> None:
        if self.source_id not in {
            "dexscreener",
            "geckoterminal",
            "raydium",
            "meteora-dlmm",
        }:
            raise ValueError("source has no implemented public discovery adapter")
        if type(self.page) is not int or not 1 <= self.page <= 8:
            raise ValueError("discovery page outside 1..8 bound")
        if self.source_id == "dexscreener":
            if self.token_mint is None or self.page != 1:
                raise ValueError(
                    "DEX Screener requires an explicit mint, no pagination"
                )
            validate_pubkey(self.token_mint)
        elif self.token_mint is not None:
            raise ValueError("token filter is supported only for DEX Screener")

    def endpoint(self) -> tuple[str, dict[str, str]]:
        if self.source_id == "dexscreener":
            return (
                f"https://api.dexscreener.com/token-pairs/v1/solana/{self.token_mint}",
                {},
            )
        if self.source_id == "geckoterminal":
            return "https://api.geckoterminal.com/api/v2/networks/solana/pools", {
                "page": str(self.page)
            }
        if self.source_id == "raydium":
            return "https://api-v3.raydium.io/pools/info/list", {
                "poolType": "all",
                "poolSortField": "default",
                "sortType": "desc",
                "pageSize": "100",
                "page": str(self.page),
            }
        return "https://dlmm.datapi.meteora.ag/pools", {
            "page": str(self.page),
            "page_size": "100",
        }


@dataclass(frozen=True, slots=True)
class DiscoveryReceipt:
    source_id: str
    request_fingerprint: str
    response_hash: str | None
    observed_at: float
    http_status: int | None
    error: str | None = None

    @property
    def identity(self) -> str:
        return _digest(
            {
                "source": self.source_id,
                "request": self.request_fingerprint,
                "response": self.response_hash,
                "status": self.http_status,
                "error": self.error,
            }
        )


@dataclass(frozen=True, slots=True)
class DiscoveredMarket:
    domain: str
    market_id: str
    mints: tuple[str, str]
    venue_label: str
    source_id: str
    receipt_id: str

    def __post_init__(self) -> None:
        if self.domain != "solana-mainnet":
            raise ValueError("discovery adapter supports Solana mainnet only")
        validate_pubkey(self.market_id)
        for mint in self.mints:
            validate_pubkey(mint)
        if len(self.mints) != 2 or self.mints[0] == self.mints[1]:
            raise ValueError("discovered market requires two distinct mint addresses")
        if not self.venue_label or not self.source_id or not self.receipt_id:
            raise ValueError("discovery provenance is required")
        object.__setattr__(self, "mints", tuple(sorted(self.mints)))

    @property
    def identity(self) -> str:
        return _digest(
            {
                "domain": self.domain,
                "market": self.market_id,
                "mints": self.mints,
                "venue": self.venue_label,
                "source": self.source_id,
            }
        )


@dataclass(frozen=True, slots=True)
class DiscoveryBatch:
    markets: tuple[DiscoveredMarket, ...]
    receipts: tuple[DiscoveryReceipt, ...]
    rejections: tuple[tuple[str, int], ...]
    truncated: bool

    @property
    def market_count(self) -> int:
        # Sources may describe the same underlying pool. Keep every receipt,
        # count physical addresses once, and never resolve aliases into edges.
        return len({(market.domain, market.market_id) for market in self.markets})


def _rows(source_id: str, payload: Any) -> list[Any]:
    if source_id == "dexscreener":
        rows = payload
    elif source_id == "raydium":
        if payload.get("success") is not True:
            raise ValueError("Raydium discovery response was unsuccessful")
        rows = payload["data"]["data"]
    elif source_id == "geckoterminal":
        rows = payload["data"]
    else:
        rows = payload["data"]
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError("discovery response must contain at most 1000 rows")
    return rows


def _market(source_id: str, row: Any, receipt_id: str) -> DiscoveredMarket:
    if source_id == "dexscreener":
        if row["chainId"] != "solana":
            raise ValueError("foreign chain in Solana discovery")
        address, mints, label = (
            row["pairAddress"],
            (row["baseToken"]["address"], row["quoteToken"]["address"]),
            row["dexId"],
        )
    elif source_id == "raydium":
        address, mints, label = (
            row["id"],
            (row["mintA"]["address"], row["mintB"]["address"]),
            "raydium",
        )
    elif source_id == "geckoterminal":
        address = row["attributes"]["address"]
        relationships = row["relationships"]
        token_ids = tuple(
            relationships[key]["data"]["id"] for key in ("base_token", "quote_token")
        )
        if any(not token_id.startswith("solana_") for token_id in token_ids):
            raise ValueError("foreign token namespace")
        mints = (
            token_ids[0].removeprefix("solana_"),
            token_ids[1].removeprefix("solana_"),
        )
        label = relationships["dex"]["data"]["id"]
    else:
        # Current /pools endpoint uses address + token_x/token_y mint metadata.
        address = row["address"]
        mints = (row["token_x"]["address"], row["token_y"]["address"])
        label = "meteora-dlmm"
    return DiscoveredMarket(
        "solana-mainnet", address, mints, label, source_id, receipt_id
    )


class PublicMarketDiscovery:
    """Explicit one-shot requests, hard bounds, deterministic response tracing."""

    def __init__(self, transport: Transport, catalog: MarketSourceCatalog) -> None:
        self.transport = transport
        self.catalog = catalog

    async def collect(
        self,
        requests: tuple[DiscoveryRequest, ...],
        *,
        observed_at: float,
        max_markets: int = 512,
    ) -> DiscoveryBatch:
        if not 1 <= len(requests) <= 8:
            raise ValueError("discovery requires 1..8 explicit requests")
        if type(max_markets) is not int or not 1 <= max_markets <= 512:
            raise ValueError("discovery market cap outside 1..512")
        if not math.isfinite(observed_at) or observed_at <= 0:
            raise ValueError("observed_at must be a finite positive timestamp")
        for request in requests:
            if (
                self.catalog.require(request.source_id).access
                is not SourceAccess.PUBLIC_LIMITED
            ):
                raise ValueError("discovery source is not registered as a public read")
        markets: dict[str, DiscoveredMarket] = {}
        receipts: list[DiscoveryReceipt] = []
        rejected: Counter[str] = Counter()
        truncated = False
        for request in requests:
            url, params = request.endpoint()
            fingerprint = _digest({"method": "GET", "url": url, "params": params})
            try:
                status, _, payload = await self.transport.request(
                    "GET", url, params=params
                )
            except Exception:
                # Transport error messages may contain credentials; record only
                # a category. Cancellation (BaseException) still propagates.
                receipts.append(
                    DiscoveryReceipt(
                        request.source_id,
                        fingerprint,
                        None,
                        observed_at,
                        None,
                        "transport-error",
                    )
                )
                rejected["transport-error"] += 1
                break
            if status != 200:
                receipts.append(
                    DiscoveryReceipt(
                        request.source_id,
                        fingerprint,
                        None,
                        observed_at,
                        status,
                        "http-error",
                    )
                )
                rejected[f"http-{status}"] += 1
                # No retry/rate policy owner here; in particular stop on 429.
                break
            response_hash = None
            try:
                response_hash = _digest(payload)
                rows = _rows(request.source_id, payload)
            except (ValueError, TypeError, KeyError, AttributeError):
                receipts.append(
                    DiscoveryReceipt(
                        request.source_id,
                        fingerprint,
                        response_hash,
                        observed_at,
                        status,
                        "invalid-schema",
                    )
                )
                rejected["invalid-schema"] += 1
                continue
            receipt = DiscoveryReceipt(
                request.source_id, fingerprint, response_hash, observed_at, status
            )
            receipts.append(receipt)
            # Validate every row within the response bound before selecting a
            # sorted prefix, so API row ordering does not decide the cap.
            parsed: dict[str, DiscoveredMarket] = {}
            for row in rows:
                try:
                    market = _market(request.source_id, row, receipt.identity)
                    parsed[market.identity] = market
                except (ValueError, TypeError, KeyError, AttributeError):
                    rejected["invalid-market"] += 1
            for key in sorted(parsed):
                if key in markets:
                    continue
                if len(markets) == max_markets:
                    truncated = True
                    rejected["market-limit"] += len(set(parsed) - set(markets))
                    break
                markets[key] = parsed[key]
            if truncated:
                break
        return DiscoveryBatch(
            tuple(markets[key] for key in sorted(markets)),
            tuple(receipts),
            tuple(sorted(rejected.items())),
            truncated,
        )
