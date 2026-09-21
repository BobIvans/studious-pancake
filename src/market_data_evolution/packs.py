"""Concrete default-off cross-market packs for Market Data Layer Evolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .contracts import MarketDataEvolutionError


@dataclass(frozen=True, slots=True)
class CrossMarketPack:
    pack_id: str
    name: str
    source_ids: tuple[str, ...]
    initial_mode: str
    blockers: tuple[str, ...]
    state: str = "DISABLED"
    evidence_status: str = "BLOCKED_EXTERNAL"
    live_enabled: bool = False
    signing_allowed: bool = False
    submission_allowed: bool = False
    funds_movement_allowed: bool = False

    def __post_init__(self) -> None:
        if not self.pack_id.startswith("MDE-P"):
            raise MarketDataEvolutionError("MARKET_PACK_ID_INVALID")
        if not self.source_ids or not self.blockers:
            raise MarketDataEvolutionError("MARKET_PACK_EVIDENCE_BOUNDARY_REQUIRED")
        if self.state != "DISABLED" or self.evidence_status != "BLOCKED_EXTERNAL":
            raise MarketDataEvolutionError("MARKET_PACK_MUST_START_BLOCKED")
        if (
            self.live_enabled
            or self.signing_allowed
            or self.submission_allowed
            or self.funds_movement_allowed
        ):
            raise MarketDataEvolutionError("MARKET_PACK_EFFECT_FORBIDDEN")


_PACKS: Mapping[str, CrossMarketPack] = {
    "MDE-P01": CrossMarketPack(
        pack_id="MDE-P01",
        name="Crypto Derivatives and Basis",
        source_ids=("S03", "S04", "S05", "S06"),
        initial_mode="research_only",
        blockers=(
            "DERIVATIVES_SOURCE_ENTITLEMENT_SCHEMA_NOT_MATERIALIZED",
            "REAL_FUTURES_OPTIONS_PIT_CORPUS_NOT_CAPTURED",
            "EXECUTABLE_FILL_AND_MARGIN_EVIDENCE_NOT_MATERIALIZED",
        ),
    ),
    "MDE-P02": CrossMarketPack(
        pack_id="MDE-P02",
        name="Gold Underlying and Claims",
        source_ids=("S07", "S08", "S09", "S10", "S11", "S12"),
        initial_mode="research_only",
        blockers=(
            "GOLD_DATA_LICENCE_ENTITLEMENT_NOT_MATERIALIZED",
            "PAXG_XAUT_ACCESS_REDEMPTION_RIGHTS_NOT_ATTESTED",
            "CME_LBMA_SESSION_SETTLEMENT_DATA_NOT_CAPTURED",
        ),
    ),
    "MDE-P03": CrossMarketPack(
        pack_id="MDE-P03",
        name="Macro Vintage and Cross Asset Regimes",
        source_ids=("S01", "S02", "S08"),
        initial_mode="research_only",
        blockers=(
            "FRED_ALFRED_CFTC_VINTAGE_FEEDS_NOT_MATERIALIZED",
            "PUBLICATION_AVAILABLE_AT_CORPUS_NOT_CAPTURED",
            "HELD_OUT_CROSS_ASSET_CAMPAIGN_NOT_RUN",
        ),
    ),
}


def build_crypto_derivatives_pack() -> CrossMarketPack:
    return _PACKS["MDE-P01"]


def build_gold_claim_pack() -> CrossMarketPack:
    return _PACKS["MDE-P02"]


def build_macro_vintage_pack() -> CrossMarketPack:
    return _PACKS["MDE-P03"]


def all_cross_market_packs() -> tuple[CrossMarketPack, ...]:
    return tuple(_PACKS[key] for key in sorted(_PACKS))


def build_market_pack(pack_id: str) -> CrossMarketPack:
    try:
        return _PACKS[pack_id]
    except KeyError as exc:
        raise MarketDataEvolutionError("MARKET_PACK_UNKNOWN") from exc


__all__ = [
    "CrossMarketPack",
    "all_cross_market_packs",
    "build_crypto_derivatives_pack",
    "build_gold_claim_pack",
    "build_macro_vintage_pack",
    "build_market_pack",
]
