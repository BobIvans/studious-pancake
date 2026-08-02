from dataclasses import replace

import pytest

from src.economics.exact_amounts import (
    AmountDomain,
    AssetIdentity,
    AtomicAmount,
    CanonicalAssetRegistry,
    ExactAmountError,
    NativeSemantics,
    U64_MAX,
    U128_MAX,
)


def asset(
    name: str = "mint", semantics: NativeSemantics = NativeSemantics.TOKEN
) -> AssetIdentity:
    return AssetIdentity(
        cluster_genesis="genesis",
        mint=name,
        token_program="spl-token",
        rooted_mint_hash="a" * 64,
        decimals=9,
        decimals_generation="mint-hash:a",
        metadata_slot=42,
        native_semantics=semantics,
    )


@pytest.mark.parametrize("bad", [True, False, 1.0, "1", None])
def test_wire_amount_is_non_coercive(bad: object) -> None:
    with pytest.raises(ExactAmountError, match="non-bool integer"):
        AtomicAmount(asset(), bad)  # type: ignore[arg-type]


def test_checked_domains_reject_overflow_underflow_and_zero_denominator() -> None:
    identity = asset()
    with pytest.raises(ExactAmountError, match="fit u64"):
        AtomicAmount(identity, U64_MAX + 1)
    with pytest.raises(ExactAmountError, match="fit u64"):
        AtomicAmount(identity, 0).checked_sub(AtomicAmount(identity, 1))
    with pytest.raises(ExactAmountError, match="positive"):
        AtomicAmount(identity, 1).checked_mul_ratio(1, 0)
    with pytest.raises(ExactAmountError, match="exceeds u128"):
        AtomicAmount(identity, U64_MAX).checked_mul_ratio(U128_MAX, 1)


def test_ratio_records_remainder_and_never_rounds_implicitly() -> None:
    result, remainder = AtomicAmount(asset(), 10).checked_mul_ratio(1, 3)
    assert result.units == 3
    assert remainder == 1


def test_assets_are_generation_bound() -> None:
    amount = AtomicAmount(asset(), 1, AmountDomain.UNSIGNED_INTERMEDIATE)
    drifted = AtomicAmount(
        replace(asset(), decimals_generation="mint-hash:b"),
        1,
        AmountDomain.UNSIGNED_INTERMEDIATE,
    )
    with pytest.raises(ExactAmountError, match="identity generation"):
        amount.checked_add(drifted)


def test_canonical_registry_is_immutable_and_distinguishes_sol_wsol() -> None:
    registry = CanonicalAssetRegistry(
        "release-6",
        {
            "SOL": asset("native-sol-sentinel", NativeSemantics.NATIVE_SOL),
            "wSOL": asset("wrapped-sol-mint", NativeSemantics.WRAPPED_SOL),
            "USDC": replace(asset("usdc-mint"), decimals=6),
        },
    )
    with pytest.raises(TypeError):
        registry.assets["SOL"] = asset()  # type: ignore[index]
    with pytest.raises(ExactAmountError, match="reviewed registry migration"):
        registry.migrate("SOL", asset())


def test_native_sol_and_wsol_may_not_share_mint_identity() -> None:
    with pytest.raises(ExactAmountError, match="must not equal"):
        CanonicalAssetRegistry(
            "release-6",
            {
                "SOL": asset("same", NativeSemantics.NATIVE_SOL),
                "wSOL": asset("same", NativeSemantics.WRAPPED_SOL),
                "USDC": replace(asset("usdc"), decimals=6),
            },
        )
