"""Canonical integer-only economic primitives for sender-free execution.

These types are deliberately small and dependency-free.  They are the wire
boundary used by planners and reconciliation code: Python's coercive numeric
types are rejected and every arithmetic operation is checked explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

U64_MAX = (1 << 64) - 1
U128_MAX = (1 << 128) - 1


class ExactAmountError(ValueError):
    """An amount or asset identity is not safe for economic authority."""


class AmountDomain(StrEnum):
    UNSIGNED_WIRE = "unsigned_wire"
    UNSIGNED_INTERMEDIATE = "unsigned_intermediate"
    SIGNED_LEDGER = "signed_ledger"


class NativeSemantics(StrEnum):
    TOKEN = "token"
    NATIVE_SOL = "native_sol"
    WRAPPED_SOL = "wrapped_sol"


def strict_int(value: object, *, field: str) -> int:
    """Accept an actual integer, never bool, float, string, or Decimal."""

    if type(value) is not int:
        raise ExactAmountError(f"{field} must be a non-bool integer")
    return value


@dataclass(frozen=True, slots=True)
class AssetIdentity:
    """An asset generation bound to rooted cluster and mint metadata."""

    cluster_genesis: str
    mint: str
    token_program: str
    rooted_mint_hash: str
    decimals: int
    decimals_generation: str
    metadata_slot: int
    native_semantics: NativeSemantics = NativeSemantics.TOKEN
    token_2022_extensions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field in (
            "cluster_genesis",
            "mint",
            "token_program",
            "rooted_mint_hash",
            "decimals_generation",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ExactAmountError(f"{field} must be non-empty text")
        decimals = strict_int(self.decimals, field="decimals")
        if not 0 <= decimals <= 255:
            raise ExactAmountError("decimals must fit u8")
        slot = strict_int(self.metadata_slot, field="metadata_slot")
        if slot < 0 or slot > U64_MAX:
            raise ExactAmountError("metadata_slot must fit u64")
        extensions = tuple(self.token_2022_extensions)
        if len(extensions) != len(set(extensions)):
            raise ExactAmountError("token extensions must be unique")
        if any(not isinstance(item, str) or not item for item in extensions):
            raise ExactAmountError("token extensions must be non-empty text")
        object.__setattr__(self, "token_2022_extensions", extensions)

    def require_compatible(self, other: "AssetIdentity") -> None:
        if type(other) is not AssetIdentity or self != other:
            raise ExactAmountError("asset identity generation mismatch")


@dataclass(frozen=True, slots=True)
class AtomicAmount:
    """Asset-qualified atomic units with an explicit sign/bound domain."""

    asset: AssetIdentity
    units: int
    domain: AmountDomain = AmountDomain.UNSIGNED_WIRE

    def __post_init__(self) -> None:
        if type(self.asset) is not AssetIdentity:
            raise ExactAmountError("asset must be a canonical AssetIdentity")
        units = strict_int(self.units, field="units")
        if self.domain is AmountDomain.UNSIGNED_WIRE:
            if not 0 <= units <= U64_MAX:
                raise ExactAmountError("wire units must fit u64")
        elif self.domain is AmountDomain.UNSIGNED_INTERMEDIATE:
            if not 0 <= units <= U128_MAX:
                raise ExactAmountError("intermediate units must fit u128")
        elif self.domain is AmountDomain.SIGNED_LEDGER:
            if not -(1 << 127) <= units <= (1 << 127) - 1:
                raise ExactAmountError("ledger units must fit i128")
        else:
            raise ExactAmountError("unknown amount domain")

    def checked_add(self, other: "AtomicAmount") -> "AtomicAmount":
        self._same_authority(other)
        return AtomicAmount(self.asset, self.units + other.units, self.domain)

    def checked_sub(self, other: "AtomicAmount") -> "AtomicAmount":
        self._same_authority(other)
        return AtomicAmount(self.asset, self.units - other.units, self.domain)

    def checked_mul_ratio(
        self, numerator: int, denominator: int
    ) -> tuple["AtomicAmount", int]:
        numerator = strict_int(numerator, field="numerator")
        denominator = strict_int(denominator, field="denominator")
        if numerator < 0:
            raise ExactAmountError("numerator must be unsigned")
        if denominator <= 0:
            raise ExactAmountError("denominator must be positive")
        product = self.units * numerator
        if product > U128_MAX:
            raise ExactAmountError("ratio intermediate exceeds u128")
        quotient, remainder = divmod(product, denominator)
        return AtomicAmount(self.asset, quotient, self.domain), remainder

    def _same_authority(self, other: "AtomicAmount") -> None:
        if type(other) is not AtomicAmount:
            raise ExactAmountError("operand must be AtomicAmount")
        self.asset.require_compatible(other.asset)
        if self.domain is not other.domain:
            raise ExactAmountError("amount domains differ")


class CanonicalAssetRegistry:
    """Immutable release-generation registry for built-in asset identities."""

    __slots__ = ("_assets", "release_generation")

    def __init__(self, release_generation: str, assets: Mapping[str, AssetIdentity]):
        if not isinstance(release_generation, str) or not release_generation:
            raise ExactAmountError("release_generation is required")
        copied = dict(assets)
        if set(copied) != {"SOL", "wSOL", "USDC"}:
            raise ExactAmountError("canonical registry requires SOL, wSOL, and USDC")
        if copied["SOL"].native_semantics is not NativeSemantics.NATIVE_SOL:
            raise ExactAmountError("SOL must use native semantics")
        if copied["wSOL"].native_semantics is not NativeSemantics.WRAPPED_SOL:
            raise ExactAmountError("wSOL must use wrapped semantics")
        if copied["SOL"].mint == copied["wSOL"].mint:
            raise ExactAmountError("native SOL sentinel must not equal wSOL mint")
        self.release_generation = release_generation
        self._assets = MappingProxyType(copied)

    @property
    def assets(self) -> Mapping[str, AssetIdentity]:
        return self._assets

    def migrate(self, *_: object, **__: object) -> "CanonicalAssetRegistry":
        raise ExactAmountError(
            "canonical assets require a reviewed registry migration and new release"
        )


__all__ = [
    "AmountDomain",
    "AssetIdentity",
    "AtomicAmount",
    "CanonicalAssetRegistry",
    "ExactAmountError",
    "NativeSemantics",
    "U64_MAX",
    "U128_MAX",
    "strict_int",
]
