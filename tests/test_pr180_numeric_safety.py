from __future__ import annotations

import pytest

from src.domain.money import (
    U64_MAX,
    BasisPoints,
    ComputeBudget,
    ComputeUnitPrice,
    Lamports,
    MonetaryUnitError,
    TokenAmount,
    TokenMetadata,
)
from src.domain.numeric_safety_pr180 import (
    MAX_MICRO_LAMPORTS_PER_CU,
    MAX_TOKEN_DECIMALS,
    NumericSafetyCode,
    NumericSafetyError,
    SpendEnvelopeCeilings,
    checked_int,
)


def test_pr180_basis_points_have_absolute_hard_ceiling() -> None:
    with pytest.raises(MonetaryUnitError):
        BasisPoints(1_000_000)

    assert BasisPoints(10_000).value == 10_000


def test_pr180_token_decimals_are_protocol_bounded_before_decimal_math() -> None:
    with pytest.raises(MonetaryUnitError):
        TokenMetadata("mint", "BAD", 100_000, "program")

    assert TokenMetadata("mint", "OK", MAX_TOKEN_DECIMALS, "program").decimals == 255


def test_pr180_compute_unit_price_has_hard_maximum() -> None:
    with pytest.raises(MonetaryUnitError):
        ComputeUnitPrice(10**1000)

    assert (
        ComputeUnitPrice(MAX_MICRO_LAMPORTS_PER_CU).micro_lamports_per_cu
        == MAX_MICRO_LAMPORTS_PER_CU
    )


def test_pr180_bool_never_satisfies_monetary_integer() -> None:
    with pytest.raises(MonetaryUnitError):
        Lamports(True)

    with pytest.raises(MonetaryUnitError):
        TokenAmount("mint", True, 6)

    with pytest.raises(NumericSafetyError) as caught:
        checked_int(True, "amount", minimum=0, maximum=1)

    assert caught.value.code == NumericSafetyCode.BOOL_IS_NOT_INTEGER


def test_pr180_wire_amount_narrowing_is_explicit_u128_to_u64() -> None:
    intermediate = TokenAmount("mint", U64_MAX + 1, 6)

    with pytest.raises(MonetaryUnitError):
        intermediate.to_wire_amount_u64()

    assert TokenAmount("mint", U64_MAX, 6).to_wire_amount_u64() == U64_MAX


def test_pr180_compute_budget_recomputes_priority_fee_against_ceiling() -> None:
    budget = ComputeBudget(
        unit_limit=1_400_000,
        unit_price=ComputeUnitPrice(MAX_MICRO_LAMPORTS_PER_CU),
    )

    assert budget.priority_fee().value == 14_000_000

    with pytest.raises(MonetaryUnitError):
        ComputeBudget(
            unit_limit=1_400_000,
            unit_price=ComputeUnitPrice(MAX_MICRO_LAMPORTS_PER_CU + 1),
        ).priority_fee()


def test_pr180_config_can_lower_but_not_raise_signed_ceilings() -> None:
    lowered = SpendEnvelopeCeilings(max_tip_lamports=1)
    assert lowered.max_tip_lamports == 1

    with pytest.raises(NumericSafetyError):
        SpendEnvelopeCeilings(max_micro_lamports_per_cu=MAX_MICRO_LAMPORTS_PER_CU + 1)
