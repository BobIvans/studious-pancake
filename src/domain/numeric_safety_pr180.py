"""PR-180 immutable numeric and spend safety ceilings.

The constants in this module are hard maxima for the sender-free paper/live
execution boundary. Runtime config may lower these values but cannot raise
them without changing this reviewed code.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

U64_MAX: Final = 2**64 - 1
U128_MAX: Final = 2**128 - 1
MICRO_LAMPORTS_PER_LAMPORT: Final = 1_000_000
BPS_DENOMINATOR: Final = 10_000

MAX_BASIS_POINTS: Final = BPS_DENOMINATOR
MAX_TOKEN_DECIMALS: Final = 255
MAX_COMPUTE_UNIT_LIMIT: Final = 1_400_000
MAX_MICRO_LAMPORTS_PER_CU: Final = 10_000_000
MAX_PRIORITY_FEE_LAMPORTS: Final = 20_000_000
MAX_TIP_LAMPORTS: Final = 10_000_000
MAX_SINGLE_TOKEN_AMOUNT_U64: Final = U64_MAX
MAX_JUPITER_SLIPPAGE_BPS: Final = 1_000
MAX_JUPITER_DEX_FILTERS: Final = 16
MAX_JUPITER_DEX_NAME_CHARS: Final = 64
MAX_TRACE_ID_CHARS: Final = 128
MAX_MINT_CHARS: Final = 64
MAX_WALLET_CHARS: Final = 64


class NumericSafetyCode(str, Enum):
    BOOL_IS_NOT_INTEGER = "BOOL_IS_NOT_INTEGER"
    INTEGER_OUT_OF_RANGE = "INTEGER_OUT_OF_RANGE"
    BPS_OUT_OF_RANGE = "BPS_OUT_OF_RANGE"
    TOKEN_DECIMALS_OUT_OF_RANGE = "TOKEN_DECIMALS_OUT_OF_RANGE"
    TOKEN_AMOUNT_OUT_OF_RANGE = "TOKEN_AMOUNT_OUT_OF_RANGE"
    COMPUTE_UNIT_LIMIT_OUT_OF_RANGE = "COMPUTE_UNIT_LIMIT_OUT_OF_RANGE"
    COMPUTE_UNIT_PRICE_OUT_OF_RANGE = "COMPUTE_UNIT_PRICE_OUT_OF_RANGE"
    PRIORITY_FEE_OUT_OF_RANGE = "PRIORITY_FEE_OUT_OF_RANGE"
    TIP_OUT_OF_RANGE = "TIP_OUT_OF_RANGE"
    SLIPPAGE_OUT_OF_RANGE = "SLIPPAGE_OUT_OF_RANGE"
    STRING_OUT_OF_RANGE = "STRING_OUT_OF_RANGE"
    DEX_FILTER_OUT_OF_RANGE = "DEX_FILTER_OUT_OF_RANGE"
    SPEND_ENVELOPE_EXCEEDED = "SPEND_ENVELOPE_EXCEEDED"


class NumericSafetyError(ValueError):
    """Fail-closed PR-180 numeric boundary error."""

    def __init__(
        self,
        code: NumericSafetyCode,
        field: str,
        message: str,
        *,
        value: object | None = None,
        limit: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.field = field
        self.value = value
        self.limit = limit


def checked_int(
    value: object,
    field: str,
    *,
    minimum: int,
    maximum: int,
    code: NumericSafetyCode = NumericSafetyCode.INTEGER_OUT_OF_RANGE,
) -> int:
    """Return an int only when it is an exact non-bool integer in range."""

    if isinstance(value, bool):
        raise NumericSafetyError(
            NumericSafetyCode.BOOL_IS_NOT_INTEGER,
            field,
            f"{field} cannot be bool",
            value=value,
        )
    if not isinstance(value, int):
        raise NumericSafetyError(
            code,
            field,
            f"{field} must be int",
            value=value,
            limit=maximum,
        )
    if value < minimum or value > maximum:
        raise NumericSafetyError(
            code,
            field,
            f"{field} outside allowed range",
            value=value,
            limit=maximum,
        )
    return value


@dataclass(frozen=True, slots=True)
class SpendEnvelopeCeilings:
    """Reviewed non-overridable ceilings for one execution attempt."""

    max_compute_unit_limit: int = MAX_COMPUTE_UNIT_LIMIT
    max_micro_lamports_per_cu: int = MAX_MICRO_LAMPORTS_PER_CU
    max_priority_fee_lamports: int = MAX_PRIORITY_FEE_LAMPORTS
    max_tip_lamports: int = MAX_TIP_LAMPORTS
    max_single_token_amount_base_units: int = MAX_SINGLE_TOKEN_AMOUNT_U64
    max_slippage_bps: int = MAX_JUPITER_SLIPPAGE_BPS

    def __post_init__(self) -> None:
        checked_int(
            self.max_compute_unit_limit,
            "max_compute_unit_limit",
            minimum=1,
            maximum=MAX_COMPUTE_UNIT_LIMIT,
        )
        checked_int(
            self.max_micro_lamports_per_cu,
            "max_micro_lamports_per_cu",
            minimum=0,
            maximum=MAX_MICRO_LAMPORTS_PER_CU,
        )
        checked_int(
            self.max_priority_fee_lamports,
            "max_priority_fee_lamports",
            minimum=0,
            maximum=MAX_PRIORITY_FEE_LAMPORTS,
        )
        checked_int(
            self.max_tip_lamports,
            "max_tip_lamports",
            minimum=0,
            maximum=MAX_TIP_LAMPORTS,
        )
        checked_int(
            self.max_single_token_amount_base_units,
            "max_single_token_amount_base_units",
            minimum=0,
            maximum=MAX_SINGLE_TOKEN_AMOUNT_U64,
        )
        checked_int(
            self.max_slippage_bps,
            "max_slippage_bps",
            minimum=0,
            maximum=MAX_JUPITER_SLIPPAGE_BPS,
        )


DEFAULT_SPEND_CEILINGS: Final = SpendEnvelopeCeilings()


def checked_bps(value: object, field: str, *, maximum: int = MAX_BASIS_POINTS) -> int:
    return checked_int(
        value,
        field,
        minimum=0,
        maximum=maximum,
        code=NumericSafetyCode.BPS_OUT_OF_RANGE,
    )


def checked_basis_points(value: object, field: str = "basis_points") -> int:
    return checked_bps(value, field)


def checked_token_decimals(value: object, field: str = "decimals") -> int:
    return checked_int(
        value,
        field,
        minimum=0,
        maximum=MAX_TOKEN_DECIMALS,
        code=NumericSafetyCode.TOKEN_DECIMALS_OUT_OF_RANGE,
    )


def checked_token_account_amount_u64(
    value: object,
    field: str = "token_amount",
) -> int:
    return checked_int(
        value,
        field,
        minimum=0,
        maximum=MAX_SINGLE_TOKEN_AMOUNT_U64,
        code=NumericSafetyCode.TOKEN_AMOUNT_OUT_OF_RANGE,
    )


def checked_compute_unit_limit(
    value: object,
    *,
    ceilings: SpendEnvelopeCeilings = DEFAULT_SPEND_CEILINGS,
) -> int:
    return checked_int(
        value,
        "compute_unit_limit",
        minimum=1,
        maximum=ceilings.max_compute_unit_limit,
        code=NumericSafetyCode.COMPUTE_UNIT_LIMIT_OUT_OF_RANGE,
    )


def checked_micro_lamports_per_cu(
    value: object,
    *,
    ceilings: SpendEnvelopeCeilings = DEFAULT_SPEND_CEILINGS,
) -> int:
    return checked_int(
        value,
        "micro_lamports_per_cu",
        minimum=0,
        maximum=ceilings.max_micro_lamports_per_cu,
        code=NumericSafetyCode.COMPUTE_UNIT_PRICE_OUT_OF_RANGE,
    )


def checked_priority_fee_lamports(
    value: object,
    *,
    ceilings: SpendEnvelopeCeilings = DEFAULT_SPEND_CEILINGS,
) -> int:
    return checked_int(
        value,
        "priority_fee_lamports",
        minimum=0,
        maximum=ceilings.max_priority_fee_lamports,
        code=NumericSafetyCode.PRIORITY_FEE_OUT_OF_RANGE,
    )


def checked_tip_lamports(
    value: object,
    *,
    ceilings: SpendEnvelopeCeilings = DEFAULT_SPEND_CEILINGS,
) -> int:
    return checked_int(
        value,
        "tip_lamports",
        minimum=0,
        maximum=ceilings.max_tip_lamports,
        code=NumericSafetyCode.TIP_OUT_OF_RANGE,
    )


def checked_slippage_bps(
    value: object,
    *,
    ceilings: SpendEnvelopeCeilings = DEFAULT_SPEND_CEILINGS,
) -> int:
    return checked_int(
        value,
        "slippage_bps",
        minimum=0,
        maximum=ceilings.max_slippage_bps,
        code=NumericSafetyCode.SLIPPAGE_OUT_OF_RANGE,
    )


def checked_jupiter_amount(
    value: object,
    *,
    ceilings: SpendEnvelopeCeilings = DEFAULT_SPEND_CEILINGS,
) -> int:
    return checked_int(
        value,
        "jupiter_amount",
        minimum=1,
        maximum=ceilings.max_single_token_amount_base_units,
        code=NumericSafetyCode.TOKEN_AMOUNT_OUT_OF_RANGE,
    )


def checked_short_string(value: object, field: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value:
        raise NumericSafetyError(
            NumericSafetyCode.STRING_OUT_OF_RANGE,
            field,
            f"{field} must be a non-empty string",
            value=value,
            limit=maximum,
        )
    if len(value) > maximum:
        raise NumericSafetyError(
            NumericSafetyCode.STRING_OUT_OF_RANGE,
            field,
            f"{field} exceeds maximum length",
            value="<redacted>",
            limit=maximum,
        )
    return value


def checked_dex_filters(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    if len(values) > MAX_JUPITER_DEX_FILTERS:
        raise NumericSafetyError(
            NumericSafetyCode.DEX_FILTER_OUT_OF_RANGE,
            field,
            f"{field} has too many entries",
            value=len(values),
            limit=MAX_JUPITER_DEX_FILTERS,
        )
    return tuple(
        checked_short_string(item, field, maximum=MAX_JUPITER_DEX_NAME_CHARS)
        for item in values
    )


def ceil_priority_fee_lamports(unit_limit: int, micro_lamports_per_cu: int) -> int:
    micro_lamports = unit_limit * micro_lamports_per_cu
    return (micro_lamports + MICRO_LAMPORTS_PER_LAMPORT - 1) // (
        MICRO_LAMPORTS_PER_LAMPORT
    )


def checked_compute_priority_fee(
    unit_limit: object,
    micro_lamports_per_cu: object,
    *,
    ceilings: SpendEnvelopeCeilings = DEFAULT_SPEND_CEILINGS,
) -> int:
    limit = checked_compute_unit_limit(unit_limit, ceilings=ceilings)
    price = checked_micro_lamports_per_cu(micro_lamports_per_cu, ceilings=ceilings)
    return checked_priority_fee_lamports(
        ceil_priority_fee_lamports(limit, price),
        ceilings=ceilings,
    )


__all__ = [
    "BPS_DENOMINATOR",
    "DEFAULT_SPEND_CEILINGS",
    "MAX_BASIS_POINTS",
    "MAX_COMPUTE_UNIT_LIMIT",
    "MAX_JUPITER_DEX_FILTERS",
    "MAX_JUPITER_SLIPPAGE_BPS",
    "MAX_MICRO_LAMPORTS_PER_CU",
    "MAX_PRIORITY_FEE_LAMPORTS",
    "MAX_SINGLE_TOKEN_AMOUNT_U64",
    "MAX_TIP_LAMPORTS",
    "MAX_TOKEN_DECIMALS",
    "MICRO_LAMPORTS_PER_LAMPORT",
    "NumericSafetyCode",
    "NumericSafetyError",
    "SpendEnvelopeCeilings",
    "U64_MAX",
    "U128_MAX",
    "ceil_priority_fee_lamports",
    "checked_basis_points",
    "checked_bps",
    "checked_compute_priority_fee",
    "checked_compute_unit_limit",
    "checked_dex_filters",
    "checked_int",
    "checked_jupiter_amount",
    "checked_micro_lamports_per_cu",
    "checked_priority_fee_lamports",
    "checked_short_string",
    "checked_slippage_bps",
    "checked_tip_lamports",
    "checked_token_account_amount_u64",
    "checked_token_decimals",
]
