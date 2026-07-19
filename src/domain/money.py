"""Typed monetary units and token metadata for execution cost accounting."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from enum import Enum
from typing import Dict, Optional

NATIVE_SOL_MINT = "11111111111111111111111111111111"
WSOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhfqASPWnGD1x1gUghStfV2hLwx"
LAMPORTS_PER_SOL = 1_000_000_000
MICRO_LAMPORTS_PER_LAMPORT = 1_000_000


class MonetaryUnitError(ValueError):
    pass


@dataclass(frozen=True)
class TokenMetadata:
    mint: str
    symbol: str
    decimals: int
    token_program: str
    is_native: bool = False


class TokenRegistry:
    def __init__(self, tokens: Optional[Dict[str, TokenMetadata]] = None):
        self._tokens = dict(DEFAULT_TOKENS)
        if tokens:
            self._tokens.update(tokens)

    def get(self, mint: str) -> TokenMetadata:
        try:
            return self._tokens[mint]
        except KeyError as exc:
            raise MonetaryUnitError(f"unknown token mint: {mint}") from exc

    def decimals(self, mint: str) -> int:
        return self.get(mint).decimals


DEFAULT_TOKENS: Dict[str, TokenMetadata] = {
    NATIVE_SOL_MINT: TokenMetadata(NATIVE_SOL_MINT, "SOL", 9, "native", True),
    WSOL_MINT: TokenMetadata(WSOL_MINT, "wSOL", 9, TOKEN_PROGRAM, False),
    USDC_MINT: TokenMetadata(USDC_MINT, "USDC", 6, TOKEN_PROGRAM, False),
}


@dataclass(frozen=True)
class TokenAmount:
    mint: str
    base_units: int
    decimals: int

    def __post_init__(self):
        if self.base_units < 0:
            raise MonetaryUnitError("TokenAmount cannot be negative")
        if self.decimals < 0:
            raise MonetaryUnitError("decimals cannot be negative")

    @classmethod
    def from_base_units(cls, mint: str, base_units: int, decimals: int) -> "TokenAmount":
        return cls(mint, int(base_units), int(decimals))

    @classmethod
    def from_ui(cls, mint: str, ui_amount: Decimal | int | str | float, decimals: int) -> "TokenAmount":
        scale = Decimal(10) ** int(decimals)
        units = (Decimal(str(ui_amount)) * scale).to_integral_value(rounding=ROUND_FLOOR)
        return cls(mint, int(units), int(decimals))

    def _check(self, other: "TokenAmount") -> None:
        if (self.mint, self.decimals) != (other.mint, other.decimals):
            raise MonetaryUnitError("token mint/decimal mismatch")

    def __add__(self, other: "TokenAmount") -> "TokenAmount":
        self._check(other)
        return TokenAmount(self.mint, self.base_units + other.base_units, self.decimals)

    def __sub__(self, other: "TokenAmount") -> "TokenDelta":
        self._check(other)
        return TokenDelta(self.mint, self.base_units - other.base_units, self.decimals)

    def to_ui_decimal(self) -> Decimal:
        return Decimal(self.base_units) / (Decimal(10) ** self.decimals)


@dataclass(frozen=True)
class TokenDelta:
    mint: str
    base_units: int
    decimals: int

    def to_amount_floor_zero(self) -> TokenAmount:
        return TokenAmount(self.mint, max(0, self.base_units), self.decimals)


@dataclass(frozen=True)
class Lamports:
    value: int
    def __post_init__(self):
        if self.value < 0:
            raise MonetaryUnitError("lamports cannot be negative")
    @classmethod
    def from_sol(cls, sol: Decimal | int | str | float) -> "Lamports":
        return cls(int((Decimal(str(sol)) * LAMPORTS_PER_SOL).to_integral_value(rounding=ROUND_FLOOR)))
    def to_sol_decimal(self) -> Decimal:
        return Decimal(self.value) / LAMPORTS_PER_SOL
    def __add__(self, other: "Lamports") -> "Lamports":
        return Lamports(self.value + other.value)


def lamports_to_wrapped_sol(amount: Lamports) -> TokenAmount:
    return TokenAmount(WSOL_MINT, amount.value, 9)


def wrapped_sol_to_lamports(amount: TokenAmount) -> Lamports:
    if amount.mint != WSOL_MINT or amount.decimals != 9:
        raise MonetaryUnitError("explicit wSOL conversion requires wSOL mint with 9 decimals")
    return Lamports(amount.base_units)


@dataclass(frozen=True)
class BasisPoints:
    value: int
    def __post_init__(self):
        if self.value < 0:
            raise MonetaryUnitError("basis points cannot be negative")
    def apply_floor(self, amount: TokenAmount) -> TokenAmount:
        return TokenAmount(amount.mint, amount.base_units * self.value // 10_000, amount.decimals)


@dataclass(frozen=True)
class ComputeUnitPrice:
    micro_lamports_per_cu: int
    def __post_init__(self):
        if self.micro_lamports_per_cu < 0:
            raise MonetaryUnitError("compute unit price cannot be negative")


@dataclass(frozen=True)
class ComputeBudget:
    unit_limit: int
    unit_price: ComputeUnitPrice
    def priority_fee(self) -> Lamports:
        micro = self.unit_limit * self.unit_price.micro_lamports_per_cu
        return Lamports((micro + MICRO_LAMPORTS_PER_LAMPORT - 1) // MICRO_LAMPORTS_PER_LAMPORT)


class FeeComponentKind(str, Enum):
    FLASH_LOAN = "flash_loan"
    DEX = "dex"
    PROTOCOL = "protocol"
    TOKEN_2022_TRANSFER = "token_2022_transfer"
    NETWORK_BASE = "network_base"
    PRIORITY = "priority"
    JITO_TIP = "jito_tip"
    ATA_CREATION = "ata_creation"
    SLIPPAGE_BUFFER = "slippage_buffer"
    ORACLE_BUFFER = "oracle_buffer"
    SAFETY_BUFFER = "safety_buffer"
