"""Exact non-money dimensions for the canonical routing boundary.

MPR-041 absorbs the former PR-048 scope.  Values crossing provider and runtime
boundaries are represented without binary floating point and reject bools,
implicit unit conversion, overflow and ambiguous scale.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final

U64_MAX: Final = (1 << 64) - 1
BPS_DENOMINATOR: Final = 10_000
PERCENT_MICROS_PER_PERCENT: Final = 1_000_000
NANOSECONDS_PER_SECOND: Final = 1_000_000_000


class DimensionError(ValueError):
    """A value crossed a boundary with an invalid or ambiguous dimension."""


def strict_int(value: object, field: str, *, minimum: int, maximum: int) -> int:
    if type(value) is not int:
        raise DimensionError(f"{field} must be a non-bool integer")
    if value < minimum or value > maximum:
        raise DimensionError(f"{field} outside [{minimum}, {maximum}]")
    return value


@dataclass(frozen=True, slots=True, order=True)
class BasisPoints:
    value: int

    def __post_init__(self) -> None:
        strict_int(self.value, "basis_points", minimum=0, maximum=BPS_DENOMINATOR)

    def __int__(self) -> int:
        return self.value

    def to_percent_text(self) -> str:
        """Serialize bps to provider percent text exactly (50 bps -> ``0.5``)."""

        whole, remainder = divmod(self.value, 100)
        if remainder == 0:
            return str(whole)
        return f"{whole}.{remainder:02d}".rstrip("0")


@dataclass(frozen=True, slots=True, order=True)
class PercentMicros:
    """Millionths of one percent; 1 percent is 1_000_000 units."""

    value: int

    def __post_init__(self) -> None:
        strict_int(
            self.value,
            "percent_micros",
            minimum=-(1 << 63),
            maximum=(1 << 63) - 1,
        )

    @classmethod
    def parse(cls, value: object, field: str = "percent") -> "PercentMicros":
        decimal = exact_decimal(value, field)
        scaled = decimal * PERCENT_MICROS_PER_PERCENT
        if scaled != scaled.to_integral_value():
            raise DimensionError(f"{field} exceeds six decimal places")
        return cls(int(scaled))

    def to_decimal_text(self) -> str:
        return _scaled_decimal_text(self.value, PERCENT_MICROS_PER_PERCENT)


@dataclass(frozen=True, slots=True, order=True)
class DurationNs:
    value: int

    def __post_init__(self) -> None:
        strict_int(self.value, "duration_ns", minimum=0, maximum=U64_MAX)

    @classmethod
    def from_seconds(cls, seconds: int) -> "DurationNs":
        checked = strict_int(seconds, "seconds", minimum=0, maximum=U64_MAX)
        result = checked * NANOSECONDS_PER_SECOND
        if result > U64_MAX:
            raise DimensionError("duration_ns overflows u64")
        return cls(result)


@dataclass(frozen=True, slots=True, order=True)
class UnixTimeNs:
    value: int

    def __post_init__(self) -> None:
        strict_int(self.value, "unix_time_ns", minimum=0, maximum=U64_MAX)


@dataclass(frozen=True, slots=True, order=True)
class MonotonicNs:
    value: int

    def __post_init__(self) -> None:
        strict_int(self.value, "monotonic_ns", minimum=0, maximum=U64_MAX)


@dataclass(frozen=True, slots=True, order=True)
class Slot:
    value: int

    def __post_init__(self) -> None:
        strict_int(self.value, "slot", minimum=0, maximum=U64_MAX)

    def __int__(self) -> int:
        return self.value


@dataclass(frozen=True, slots=True, order=True)
class BlockHeight:
    value: int

    def __post_init__(self) -> None:
        strict_int(self.value, "block_height", minimum=0, maximum=U64_MAX)


@dataclass(frozen=True, slots=True, order=True)
class TokenDecimals:
    value: int

    def __post_init__(self) -> None:
        strict_int(self.value, "token_decimals", minimum=0, maximum=255)


@dataclass(frozen=True, slots=True, order=True)
class RequestCount:
    value: int

    def __post_init__(self) -> None:
        strict_int(self.value, "request_count", minimum=0, maximum=U64_MAX)


@dataclass(frozen=True, slots=True, order=True)
class BoundedRatio:
    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        strict_int(self.numerator, "ratio_numerator", minimum=0, maximum=U64_MAX)
        strict_int(self.denominator, "ratio_denominator", minimum=1, maximum=U64_MAX)


class ProviderPercentConvention(StrEnum):
    BPS_INTEGER = "bps_integer"
    PERCENT_DECIMAL = "percent_decimal"


@dataclass(frozen=True, slots=True)
class ProviderNumericRule:
    provider: str
    field: str
    convention: ProviderPercentConvention
    minimum_bps: int = 0
    maximum_bps: int = BPS_DENOMINATOR

    def serialize_bps(self, value: BasisPoints) -> str:
        if not self.minimum_bps <= value.value <= self.maximum_bps:
            raise DimensionError(
                f"{self.provider}.{self.field} outside reviewed bps range"
            )
        if self.convention is ProviderPercentConvention.BPS_INTEGER:
            return str(value.value)
        return value.to_percent_text()


PROVIDER_NUMERIC_RULES: Final = {
    ("jupiter_router", "slippageBps"): ProviderNumericRule(
        "jupiter_router", "slippageBps", ProviderPercentConvention.BPS_INTEGER
    ),
    ("okx_dex", "slippagePercent"): ProviderNumericRule(
        "okx_dex", "slippagePercent", ProviderPercentConvention.PERCENT_DECIMAL
    ),
    ("openocean", "slippage"): ProviderNumericRule(
        "openocean", "slippage", ProviderPercentConvention.PERCENT_DECIMAL
    ),
    ("odos", "slippageLimitPercent"): ProviderNumericRule(
        "odos", "slippageLimitPercent", ProviderPercentConvention.PERCENT_DECIMAL
    ),
}


def serialize_provider_bps(provider: str, field: str, bps: BasisPoints) -> str:
    try:
        rule = PROVIDER_NUMERIC_RULES[(provider, field)]
    except KeyError as exc:
        raise DimensionError(f"no numeric rule for {provider}.{field}") from exc
    return rule.serialize_bps(bps)


def exact_decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise DimensionError(f"{field} must be exact decimal text or integer")
    if isinstance(value, int):
        return Decimal(value)
    if not isinstance(value, str) or not value.strip():
        raise DimensionError(f"{field} must be exact decimal text or integer")
    text = value.strip()
    if "e" in text.lower():
        raise DimensionError(f"{field} cannot use scientific notation")
    try:
        result = Decimal(text)
    except InvalidOperation as exc:
        raise DimensionError(f"{field} is not valid decimal text") from exc
    if not result.is_finite():
        raise DimensionError(f"{field} must be finite")
    return result


def exact_non_negative_int(value: object, field: str, *, maximum: int = U64_MAX) -> int:
    if isinstance(value, bool):
        raise DimensionError(f"{field} cannot be bool")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value and value.isascii() and value.isdigit():
        result = int(value)
    else:
        raise DimensionError(f"{field} must be an unsigned decimal integer")
    return strict_int(result, field, minimum=0, maximum=maximum)


def exact_positive_int(value: object, field: str, *, maximum: int = U64_MAX) -> int:
    result = exact_non_negative_int(value, field, maximum=maximum)
    if result == 0:
        raise DimensionError(f"{field} must be positive")
    return result


def _scaled_decimal_text(value: int, scale: int) -> str:
    sign = "-" if value < 0 else ""
    value = abs(value)
    whole, remainder = divmod(value, scale)
    if remainder == 0:
        return f"{sign}{whole}"
    width = len(str(scale)) - 1
    return f"{sign}{whole}.{remainder:0{width}d}".rstrip("0")


__all__ = [
    "BPS_DENOMINATOR",
    "BasisPoints",
    "BlockHeight",
    "BoundedRatio",
    "DimensionError",
    "DurationNs",
    "MonotonicNs",
    "PercentMicros",
    "ProviderNumericRule",
    "RequestCount",
    "Slot",
    "TokenDecimals",
    "UnixTimeNs",
    "exact_decimal",
    "exact_non_negative_int",
    "exact_positive_int",
    "serialize_provider_bps",
]
