"""PR-180 / VAULT-01: immediate vault-share NAV parity."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping
from .core import EvidenceBinding, Mega802Error, require_positive_int


@dataclass(frozen=True, slots=True)
class VaultSemantics:
    vault_id: str
    share_asset: str
    total_shares: int
    reserves: Mapping[str, int]
    mint_capacity: int
    burn_capacity: int
    evidence: EvidenceBinding


def register_vault_share_semantics(vault: VaultSemantics, *, now: int) -> str:
    vault.evidence.assert_usable(now=now)
    require_positive_int(vault.total_shares, "total_shares")
    if not vault.reserves:
        raise Mega802Error("VAULT_RESERVES_REQUIRED")
    return vault.evidence.identity


def read_vault_nav_and_capacity(
    vault: VaultSemantics, prices_ppm: Mapping[str, int], *, now: int
) -> tuple[int, int, int]:
    vault.evidence.assert_usable(now=now)
    total_value = 0
    for asset, amount in vault.reserves.items():
        if asset not in prices_ppm:
            raise Mega802Error("MISSING_VAULT_PRICE")
        total_value += amount * prices_ppm[asset] // 1_000_000
    nav_ppm = total_value * 1_000_000 // vault.total_shares
    return nav_ppm, vault.mint_capacity, vault.burn_capacity


def quote_share_mint_burn(
    vault: VaultSemantics, *, shares: int, nav_ppm: int, mint: bool
) -> int:
    require_positive_int(shares, "shares")
    cap = vault.mint_capacity if mint else vault.burn_capacity
    if shares > cap:
        raise Mega802Error("VAULT_CAPACITY_EXCEEDED")
    return shares * nav_ppm // 1_000_000


def detect_vault_share_parity(
    *, intrinsic_value: int, market_value: int, minimum_edge: int = 1
) -> int:
    edge = abs(intrinsic_value - market_value)
    if edge < minimum_edge:
        raise Mega802Error("NO_VAULT_SHARE_PARITY")
    return edge
