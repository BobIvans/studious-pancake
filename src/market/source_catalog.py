"""Installable source inventory; a listing never authorizes graph or HTTP use."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
import json
from urllib.parse import urlsplit


class SourceAccess(StrEnum):
    PUBLIC_LIMITED = "public-rate-limited"
    FREE_TIER_KEY = "free-tier-key-required"
    OPEN_SOURCE = "open-source-rpc-or-host-required"
    UNVERIFIED = "access-not-verified"


class SourceFamily(StrEnum):
    DISCOVERY = "discovery"
    AMM = "amm-tool"
    ORDERBOOK = "orderbook-tool"
    ROUTER = "router"
    REFERENCE = "reference"
    RPC = "rpc"
    CEX = "cex-orderbook"
    LENDING = "lending-tool"
    INFRASTRUCTURE = "infrastructure"


@dataclass(frozen=True, slots=True)
class MarketDataSource:
    source_id: str
    label: str
    family: SourceFamily
    domains: tuple[str, ...]
    access: SourceAccess
    evidence_urls: tuple[str, ...]
    limitation: str

    def __post_init__(self) -> None:
        if not self.source_id or not self.label or not self.limitation:
            raise ValueError("source identity and access limitations are required")
        if not self.domains or not self.evidence_urls:
            raise ValueError("source domains and primary evidence are required")
        for url in self.evidence_urls:
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
            ):
                raise ValueError("source evidence must be a credential-free HTTPS URL")


@dataclass(frozen=True, slots=True)
class MarketSourceCatalog:
    checked_at: str
    sources: tuple[MarketDataSource, ...]

    def __post_init__(self) -> None:
        if not self.checked_at or not 1 <= len(self.sources) <= 128:
            raise ValueError("catalog must have a check date and 1..128 sources")
        ids = tuple(source.source_id for source in self.sources)
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate catalog source")
        object.__setattr__(
            self, "sources", tuple(sorted(self.sources, key=lambda s: s.source_id))
        )

    def with_intake(self, source: MarketDataSource) -> "MarketSourceCatalog":
        """Admit a reviewed free-slot source through this existing catalog owner."""
        if any(item.source_id == source.source_id for item in self.sources):
            raise ValueError("duplicate catalog source")
        return MarketSourceCatalog(self.checked_at, (*self.sources, source))

    def require(self, source_id: str) -> MarketDataSource:
        for source in self.sources:
            if source.source_id == source_id:
                return source
        raise ValueError(f"unregistered market data source: {source_id}")


def load_market_source_catalog() -> MarketSourceCatalog:
    payload = json.loads(
        resources.files("src.resources")
        .joinpath("market_source_catalog.json")
        .read_text(encoding="utf-8")
    )
    if payload["schema_version"] != "shadow.market-source-catalog.v1":
        raise ValueError("unsupported source catalog")
    return MarketSourceCatalog(
        checked_at=payload["checked_at"],
        sources=tuple(
            MarketDataSource(
                source_id=row["source_id"],
                label=row["label"],
                family=SourceFamily(row["family"]),
                domains=tuple(row["domains"]),
                access=SourceAccess(row["access"]),
                evidence_urls=tuple(row["evidence_urls"]),
                limitation=row["limitation"],
            )
            for row in payload["sources"]
        ),
    )
