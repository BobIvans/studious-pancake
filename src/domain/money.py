"""Typed monetary units and token metadata for execution cost accounting."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_FLOOR
from enum import Enum
from typing import Dict, Optional

from src.config.chain_registry import (
    TOKEN_2022_PROGRAM_ADDRESS,
    TOKEN_PROGRAM_ADDRESS,
)

NATIVE_SOL_MINT = "11111111111111111111111111111111"
WSOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
TOKEN_PROGRAM = TOKEN_PROGRAM_ADDRESS
TOKEN_2022_PROGRAM = TOKEN_2022_PROGRAM_ADDRESS
LAMPORTS_PER_SOL = 1_000_000_000
MICRO_LAMPORTS_PER_LAMPORT = 1_000_000
U64_MAX = 2**64 - 1
U128_MAX = 2**128 - 1


class MonetaryUnitError(ValueError):
    pass


class RoundingMode(str, Enum):
    ROUND_UP = "round_up"
    ROUND_DOWN = "round_down"


def _ceil_div(n: int, d: int) -> int:
    if d <= 0:
        raise MonetaryUnitError("denominator must be positive")
    return (n + d - 1) // d


def _reject_float(value: object, field: str) -> None:
    if isinstance(value, float):
        raise MonetaryUnitError(f"{field} cannot be a binary float")


def _check_u128(value: int, field: str) -> None:
    if value < 0 or value > U128_MAX:
        raise MonetaryUnitError(f"{field} outside u128 range")


@dataclass(frozen=True)
class TokenMetadata:
    mint: str
    symbol: str
    decimals: int
    token_program: str
    is_native: bool = False

    def __post_init__(self):
        if self.decimals < 0:
            raise MonetaryUnitError("decimals cannot be negative")
        if not self.mint or not self.token_program:
            raise MonetaryUnitError("token metadata requires mint and program")


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
        _check_u128(int(self.base_units), "token amount")
        if self.decimals < 0:
            raise MonetaryUnitError("decimals cannot be negative")
        object.__setattr__(self, "base_units", int(self.base_units))
        object.__setattr__(self, "decimals", int(self.decimals))

    @classmethod
    def from_base_units(cls, mint: str, base_units: int, decimals: int) -> "TokenAmount":
        return cls(mint, int(base_units), int(decimals))

    @classmethod
    def from_ui(cls, mint: str, ui_amount: Decimal | int | str, decimals: int) -> "TokenAmount":
        _reject_float(ui_amount, "ui_amount")
        scale = Decimal(10) ** int(decimals)
        units = (Decimal(str(ui_amount)) * scale).to_integral_value(rounding=ROUND_FLOOR)
        return cls(mint, int(units), int(decimals))

    def _check(self, other: "TokenAmount | TokenDelta") -> None:
        if (self.mint, self.decimals) != (other.mint, other.decimals):
            raise MonetaryUnitError("token mint/decimal mismatch")

    def __add__(self, other: "TokenAmount") -> "TokenAmount":
        self._check(other)
        return TokenAmount(self.mint, self.base_units + other.base_units, self.decimals)

    def __sub__(self, other: "TokenAmount") -> "TokenDelta":
        self._check(other)
        return TokenDelta(self.mint, self.base_units - other.base_units, self.decimals)

    def checked_sub_amount(self, other: "TokenAmount") -> "TokenAmount":
        delta = self - other
        if delta.base_units < 0:
            raise MonetaryUnitError("token subtraction would be negative")
        return TokenAmount(self.mint, delta.base_units, self.decimals)

    def multiply_ratio(self, numerator: int, denominator: int, rounding: RoundingMode) -> "TokenAmount":
        if numerator < 0:
            raise MonetaryUnitError("numerator cannot be negative")
        raw = self.base_units * numerator
        value = _ceil_div(raw, denominator) if rounding is RoundingMode.ROUND_UP else raw // denominator
        return TokenAmount(self.mint, value, self.decimals)

    def to_ui_decimal(self) -> Decimal:
        return Decimal(self.base_units) / (Decimal(10) ** self.decimals)

    def to_json(self) -> dict:
        return {"mint": self.mint, "base_units": str(self.base_units), "decimals": self.decimals}

    @classmethod
    def from_json(cls, payload: dict) -> "TokenAmount":
        return cls(str(payload["mint"]), int(payload["base_units"]), int(payload["decimals"]))


@dataclass(frozen=True)
class TokenDelta:
    mint: str
    base_units: int
    decimals: int

    def __post_init__(self):
        if abs(int(self.base_units)) > U128_MAX:
            raise MonetaryUnitError("token delta outside signed u128 magnitude")
        if self.decimals < 0:
            raise MonetaryUnitError("decimals cannot be negative")

    def to_amount_floor_zero(self) -> TokenAmount:
        return TokenAmount(self.mint, max(0, self.base_units), self.decimals)


@dataclass(frozen=True)
class Lamports:
    value: int

    def __post_init__(self):
        if int(self.value) < 0 or int(self.value) > U64_MAX:
            raise MonetaryUnitError("lamports outside u64 range")
        object.__setattr__(self, "value", int(self.value))

    @classmethod
    def from_sol(cls, sol: Decimal | int | str) -> "Lamports":
        _reject_float(sol, "sol")
        return cls(int((Decimal(str(sol)) * LAMPORTS_PER_SOL).to_integral_value(rounding=ROUND_FLOOR)))

    def to_sol_decimal(self) -> Decimal:
        return Decimal(self.value) / LAMPORTS_PER_SOL

    def __add__(self, other: "Lamports") -> "Lamports":
        return Lamports(self.value + other.value)

    def __sub__(self, other: "Lamports") -> "Lamports":
        if self.value < other.value:
            raise MonetaryUnitError("lamports subtraction would be negative")
        return Lamports(self.value - other.value)

    def to_json(self) -> dict:
        return {"lamports": str(self.value)}


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
        return amount.multiply_ratio(self.value, 10_000, RoundingMode.ROUND_DOWN)

    def apply_ceil(self, amount: TokenAmount) -> TokenAmount:
        return amount.multiply_ratio(self.value, 10_000, RoundingMode.ROUND_UP)


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
        if self.unit_limit < 0:
            raise MonetaryUnitError("compute unit limit cannot be negative")
        micro = self.unit_limit * self.unit_price.micro_lamports_per_cu
        return Lamports(_ceil_div(micro, MICRO_LAMPORTS_PER_LAMPORT))


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
