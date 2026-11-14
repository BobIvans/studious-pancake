"""R13-K frozen quote/build kernel contract tests (offline, deterministic).

Additive contract tests for ``src/execution/quote_build_kernel.py``. They pin
the frozen kernel rules that close the R13 audit's typed blockers
``R13_GAP_NO_KERNEL`` and ``R13_GAP_NO_POOL_DEDUP``:

- pool-identity dedup: shared pool id / aggregator lineage / correlation group
  -> correlated observations, never independent liquidity; unknown pool
  evidence is UNKNOWN, never independent;
- race results preserve ALL providers (winners, losers with typed reasons,
  failed reads) in deterministic rank order;
- the no-extrapolation invariant refuses any amount other than the quote's
  exact bound amount (amount-neighborhood scaling included);
- build handoff is a typed reference to a REAL R-03 contract plan object
  (imported, not duplicated) with fail-closed integrity parity checks.

Zero network: pytest-socket applies in CI; every input is an inline offline
fixture. No provider is enabled, nothing signs or sends, and no boot path is
touched (wiring is deferred to a follow-up lane).
"""

from __future__ import annotations

import dataclasses
import hashlib

import pytest

from src.execution.quote_build_kernel import (
    QUOTE_BUILD_KERNEL_VERSION,
    BuildHandoff,
    BuildHandoffError,
    IndependenceVerdict,
    KernelContractError,
    KernelErrorCode,
    MAX_AGE_NS,
    NormalizedProviderQuote,
    PoolIdentity,
    PoolIdentityDeduplicator,
    PoolIdentityKind,
    ProviderCorrelation,
    ProviderReadFailure,
    ProviderReadFailureClass,
    QuoteComparabilityError,
    QuoteCorrelationCluster,
    QuoteDirection,
    QuoteExtrapolationError,
    QuoteFreshness,
    QuoteLossReason,
    QuoteRaceRequest,
    QuoteRaceResult,
    QuoteRaceStateError,
    R03UnsignedPlan,
    RaceVerdict,
    RankedQuoteEntry,
    RouteVenue,
    refuse_amount_extrapolation,
)
from src.lending.unsigned_builders.contract import (
    AccountMetaSpec,
    BookendKind,
    BuildStatus,
    BuilderSourcePin,
    ConformanceErrorCode,
    ConformanceViolation,
    UnsignedBorrowPlan,
    UnsignedSolanaBookend,
)

pytestmark = pytest.mark.unit

CHAIN = "solana"
INPUT_REPR = "solana-wsol-6dec"
OUTPUT_REPR = "solana-usdc-6dec"
AMOUNT = 1_000_000
NOW_NS = 1_800_000_000_000_000_000
POOL_RAYDIUM = PoolIdentity(
    PoolIdentityKind.AMM_KEY, "8bxkJSQp9dVYqMjC7WD67CYvdATUdqUPeGrD4AuFPMWF"
)
POOL_ORCA = PoolIdentity(
    PoolIdentityKind.AMM_KEY, "D4wJ6wJ5tM0otWRgHCBaz2NCGdWpdvfGheyMTKbfVtQh"
)
POOL_SUI = PoolIdentity(PoolIdentityKind.POOL_OBJECT_ID, "0x5")


def _quote(
    *,
    provider_id: str,
    output_amount_raw: int = 990_000,
    minimum_output_raw: int | None = 989_000,
    correlation_group: str = "jupiter-metis-router",
    lineage: tuple[str, ...] = (),
    pool_ids: tuple[PoolIdentity, ...] = (),
    slot: int | None = None,
    received_at_ns: int = NOW_NS,
    taker: str | None = None,
    chain: str = CHAIN,
    route_venues: tuple[RouteVenue, ...] = (),
) -> NormalizedProviderQuote:
    return NormalizedProviderQuote(
        provider_id=provider_id,
        provider_generation="gen-r13k-fixture",
        chain=chain,
        direction=QuoteDirection.EXACT_IN,
        input_representation_id=INPUT_REPR,
        output_representation_id=OUTPUT_REPR,
        input_amount_raw=AMOUNT,
        output_amount_raw=output_amount_raw,
        input_amount_normalized=AMOUNT,
        output_amount_normalized=output_amount_raw,
        minimum_output_raw=minimum_output_raw,
        correlation=ProviderCorrelation(
            correlation_group=correlation_group,
            aggregator_lineage=lineage,
            pool_ids=pool_ids,
        ),
        freshness=QuoteFreshness(
            received_at_ns=received_at_ns,
            provider_generated_at_ns=received_at_ns,
            slot=slot,
        ),
        route_venues=route_venues,
        taker=taker,
        raw_response_hash=hashlib.sha256(provider_id.encode("utf-8")).hexdigest(),
        request_fingerprint="req-" + provider_id,
    )


def _request(
    *,
    amount_raw: int = AMOUNT,
    taker: str | None = None,
    max_age_ns: int = MAX_AGE_NS,
    max_slot_gap: int = 32,
) -> QuoteRaceRequest:
    return QuoteRaceRequest(
        chain=CHAIN,
        input_representation_id=INPUT_REPR,
        output_representation_id=OUTPUT_REPR,
        direction=QuoteDirection.EXACT_IN,
        amount_raw=amount_raw,
        taker=taker,
        max_age_ns=max_age_ns,
        max_slot_gap=max_slot_gap,
    )


def _pin() -> BuilderSourcePin:
    return BuilderSourcePin(
        provider="kamino",
        chain="solana",
        repository="https://github.com/Kamino-Finance/klend-sdk",
        commit="3c3a38d4ff9d7cf7b0380a383b81c9cd4f0f58b8",
        version="13.0.2",
        license_label="MIT",
        source_paths=(
            "src/@codegen/klend/instructions/flashBorrowReserveLiquidity.ts",
        ),
        blob_sha1s=("b" * 40,),
        verified_offline=True,
    )


def _kamino_borrow_plan(
    *,
    build_status: BuildStatus = BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
) -> UnsignedBorrowPlan:
    blockers: tuple[ConformanceViolation, ...] = ()
    bookend = None
    if build_status is BuildStatus.BUILT_OFFLINE_UNQUALIFIED:
        disc = "87e734a70734d4c1"
        bookend = UnsignedSolanaBookend(
            kind=BookendKind.BORROW,
            program_id="KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD",
            discriminator_hex=disc,
            data_hex=disc + AMOUNT.to_bytes(8, "little").hex(),
            account_metas=(
                AccountMetaSpec(
                    pubkey="6QWeT6FpJrm8AF1btu6WH2k2Xhq6t5vbheKVfQavmenB",
                    is_signer=True,
                    is_writable=True,
                ),
                AccountMetaSpec(
                    pubkey="6URwbPipuA4MJLG7LCRRZuWnms3JZ9cRG3z9indXWz6t",
                    is_signer=False,
                    is_writable=True,
                ),
            ),
            amount_base_units=AMOUNT,
        )
    else:
        blockers = (
            ConformanceViolation(
                code=ConformanceErrorCode.OPERATOR_ACCOUNT_INPUT_REQUIRED,
                message="fixture blocked plan",
                provider="kamino",
            ),
        )
    return UnsignedBorrowPlan(
        provider="kamino",
        chain="solana",
        source_pin=_pin(),
        asset_id="spl:fixture-usdc",
        principal_base_units=AMOUNT,
        bookend=bookend,
        required_repayment_base_units=None,
        blockers=blockers,
        build_status=build_status,
    )


# ---------------------------------------------------------------------------
# 1. Kernel identity: reuse of R-03 contract types, kernel version constant
# ---------------------------------------------------------------------------


def test_kernel_reuses_r03_build_status_enum_and_pins_version() -> None:
    from src.execution import quote_build_kernel

    assert quote_build_kernel.BuildStatus is BuildStatus
    assert R03UnsignedPlan is not None
    assert QUOTE_BUILD_KERNEL_VERSION.startswith("r13.quote-build-kernel.")
    assert isinstance(POOL_SUI.identity, str) and POOL_SUI.identity == (
        "0x" + "0" * 63 + "5"
    )


def test_kernel_race_and_dedup_inputs_are_offline_ints() -> None:
    quote = _quote(provider_id="jupiter", pool_ids=(POOL_RAYDIUM,))
    assert type(quote.input_amount_raw) is int
    assert type(quote.output_amount_raw) is int
    assert quote.bound_amount_raw == AMOUNT


# ---------------------------------------------------------------------------
# 2. NormalizedProviderQuote fail-closed construction invariants
# ---------------------------------------------------------------------------


def test_quote_rejects_execution_authority() -> None:
    with pytest.raises(KernelContractError) as excinfo:
        dataclasses.replace(_quote(provider_id="jupiter"), execution_authority=True)
    assert excinfo.value.code is KernelErrorCode.EXECUTION_AUTHORITY_FORBIDDEN


def test_quote_unknown_minimum_is_preserved_never_zero() -> None:
    unknown = _quote(provider_id="jupiter", minimum_output_raw=None)
    assert unknown.minimum_output_raw is None
    with pytest.raises(KernelContractError):
        _quote(provider_id="jupiter", minimum_output_raw=0)
    with pytest.raises(KernelContractError):
        _quote(provider_id="jupiter", minimum_output_raw=991_000)


def test_quote_amounts_must_be_exact_ints() -> None:
    for bad in ("1000000", 1_000_000.0, True):
        with pytest.raises(KernelContractError):
            _quote(provider_id="jupiter", output_amount_raw=bad)  # type: ignore[arg-type]


def test_route_venues_carry_venue_level_and_pool_level_evidence() -> None:
    venue = RouteVenue(
        venue_label="raydium-clmm",
        pool=POOL_RAYDIUM,
        share_bps=10_000,
    )
    quote = _quote(provider_id="jupiter", route_venues=(venue,))
    assert quote.route_venues[0].pool is not None
    with pytest.raises(KernelContractError):
        RouteVenue(share_bps=10_001)
    with pytest.raises(KernelContractError):
        RouteVenue()


# ---------------------------------------------------------------------------
# 3. PoolIdentityDeduplicator: correlated vs independent vs unknown
# ---------------------------------------------------------------------------


def test_shared_pool_identity_is_correlated() -> None:
    a = _quote(provider_id="jupiter", pool_ids=(POOL_RAYDIUM,))
    b = _quote(
        provider_id="0x",
        correlation_group="0x-solana-router",
        pool_ids=(POOL_RAYDIUM,),
    )
    assert (
        PoolIdentityDeduplicator.correlation_verdict(a, b)
        is IndependenceVerdict.CORRELATED
    )
    assert PoolIdentityDeduplicator.shared_pool_ids(a, b) == (POOL_RAYDIUM,)


def test_independence_requires_positive_pool_evidence_both_sides() -> None:
    a = _quote(provider_id="jupiter", pool_ids=(POOL_RAYDIUM,))
    b = _quote(
        provider_id="0x",
        correlation_group="0x-solana-router",
        pool_ids=(POOL_ORCA,),
    )
    assert (
        PoolIdentityDeduplicator.correlation_verdict(a, b)
        is IndependenceVerdict.INDEPENDENT
    )
    unknown_a = _quote(provider_id="titan")  # no pool evidence
    unknown_b = _quote(
        provider_id="0x",
        correlation_group="0x-solana-router",
        pool_ids=(POOL_ORCA,),
    )
    assert (
        PoolIdentityDeduplicator.correlation_verdict(unknown_a, unknown_b)
        is IndependenceVerdict.UNKNOWN
    )
    assert (
        PoolIdentityDeduplicator.correlation_verdict(unknown_a, unknown_a)
        is IndependenceVerdict.CORRELATED
    )


def test_same_correlation_group_is_correlated_even_with_disjoint_pools() -> None:
    a = _quote(provider_id="jupiter", pool_ids=(POOL_RAYDIUM,))
    b = _quote(provider_id="jupiter-final", pool_ids=(POOL_ORCA,))
    assert (
        PoolIdentityDeduplicator.correlation_verdict(a, b)
        is IndependenceVerdict.CORRELATED
    )


def test_aggregator_lineage_overlap_is_correlated() -> None:
    openocean = _quote(
        provider_id="openocean",
        correlation_group="openocean-solana-meta",
        lineage=("openocean", "jupiter"),
        pool_ids=(POOL_ORCA,),
    )
    jupiter = _quote(
        provider_id="jupiter",
        correlation_group="jupiter-metis-router",
        lineage=("jupiter",),
        pool_ids=(POOL_RAYDIUM,),
    )
    titan = _quote(
        provider_id="titan",
        correlation_group="titan-solana",
        lineage=("titan",),
        pool_ids=(PoolIdentity(PoolIdentityKind.AMM_KEY, "titanpoolfixture"),),
    )
    verdicts = {
        (openocean.provider_id, other.provider_id): (
            PoolIdentityDeduplicator.correlation_verdict(openocean, other)
        )
        for other in (jupiter, titan)
    }
    assert verdicts[("openocean", "jupiter")] is IndependenceVerdict.CORRELATED
    assert verdicts[("openocean", "titan")] is IndependenceVerdict.INDEPENDENT
    assert PoolIdentityDeduplicator.shared_lineage(openocean, jupiter) == ("jupiter",)
    assert PoolIdentityDeduplicator.shared_lineage(openocean, titan) == ()


def test_sui_pool_object_ids_normalize_to_canonical_form() -> None:
    shorthand = PoolIdentity(PoolIdentityKind.POOL_OBJECT_ID, "0x05")
    assert shorthand.identity == "0x" + "0" * 63 + "5"
    a = _quote(
        provider_id="cetus",
        chain="sui",
        correlation_group="cetus-aggregator",
        pool_ids=(shorthand,),
    )
    b = _quote(
        provider_id="sevenk",
        chain="sui",
        correlation_group="sevenk-bluefin7k",
        pool_ids=(POOL_SUI,),
    )
    assert (
        PoolIdentityDeduplicator.correlation_verdict(a, b)
        is IndependenceVerdict.CORRELATED
    )
    with pytest.raises(KernelContractError):
        PoolIdentity(PoolIdentityKind.POOL_OBJECT_ID, "0xzz")


def test_group_quotes_clusters_shared_pools_deterministically() -> None:
    shared = _quote(
        provider_id="0x", correlation_group="0x-solana-router", pool_ids=(POOL_RAYDIUM,)
    )
    jupiter = _quote(provider_id="jupiter", pool_ids=(POOL_RAYDIUM,))
    independent = _quote(
        provider_id="titan",
        correlation_group="titan-solana",
        lineage=("titan",),
        pool_ids=(POOL_ORCA,),
    )
    for order in ([jupiter, shared, independent], [independent, shared, jupiter]):
        clusters = PoolIdentityDeduplicator.group_quotes(order)
        assert [tuple(m.provider_id for m in c.members) for c in clusters] == [
            ("0x", "jupiter"),
            ("titan",),
        ]
    assert isinstance(clusters[0], QuoteCorrelationCluster)


def test_independence_set_is_deterministic_and_excludes_unknown() -> None:
    jupiter = _quote(
        provider_id="jupiter", pool_ids=(POOL_RAYDIUM,), output_amount_raw=990_000
    )
    zerox = _quote(
        provider_id="0x",
        correlation_group="0x-solana-router",
        pool_ids=(POOL_RAYDIUM,),
        output_amount_raw=995_000,
    )
    titan = _quote(
        provider_id="titan",
        correlation_group="titan-solana",
        lineage=("titan",),
        pool_ids=(POOL_ORCA,),
        output_amount_raw=992_000,
    )
    no_evidence = _quote(
        provider_id="rango",
        correlation_group="rango-multichain",
        lineage=("rango",),
        pool_ids=(),
        output_amount_raw=991_000,
    )
    picked = PoolIdentityDeduplicator.independence_set(
        [no_evidence, titan, zerox, jupiter]
    )
    # Best-first greedy: zerox (highest output) wins the shared-pool cluster
    # seat, titan is pairwise independent with it, rango is UNKNOWN (no pool
    # evidence) and never joins, jupiter is correlated with zerox.
    assert [quote.provider_id for quote in picked] == ["0x", "titan"]


# ---------------------------------------------------------------------------
# 4. QuoteRaceResult: loser preservation, ranking, determinism, failures
# ---------------------------------------------------------------------------


def _race_quotes() -> list[NormalizedProviderQuote]:
    return [
        _quote(
            provider_id="jupiter",
            pool_ids=(POOL_RAYDIUM,),
            output_amount_raw=990_000,
        ),
        _quote(
            provider_id="0x",
            correlation_group="0x-solana-router",
            pool_ids=(POOL_RAYDIUM,),
            output_amount_raw=995_000,
        ),
        _quote(
            provider_id="titan",
            correlation_group="titan-solana",
            lineage=("titan",),
            pool_ids=(POOL_ORCA,),
            output_amount_raw=992_000,
        ),
    ]


def test_race_preserves_all_quotes_ranks_winner_and_types_losers() -> None:
    result = QuoteRaceResult.build(
        request=_request(), quotes=_race_quotes(), now_ns=NOW_NS
    )
    assert [entry.quote.provider_id for entry in result.entries] == [
        "0x",
        "titan",
        "jupiter",
    ]
    assert [entry.rank for entry in result.entries] == [0, 1, 2]
    assert result.entries[0].verdict is RaceVerdict.WON
    assert result.winner is result.entries[0].quote
    assert result.entries[1].loss_reasons == (QuoteLossReason.INFERIOR_OUTPUT,)
    assert result.entries[2].loss_reasons == (
        QuoteLossReason.INFERIOR_OUTPUT,
        QuoteLossReason.CORRELATED_OBSERVATION,
    )
    assert result.require_winner().provider_id == "0x"


def test_race_fingerprint_and_rank_order_stable_under_input_order() -> None:
    quotes = _race_quotes()
    forward = QuoteRaceResult.build(request=_request(), quotes=quotes, now_ns=NOW_NS)
    backward = QuoteRaceResult.build(
        request=_request(), quotes=list(reversed(quotes)), now_ns=NOW_NS
    )
    assert forward.race_fingerprint == backward.race_fingerprint
    assert [e.quote.provider_id for e in forward.entries] == [
        e.quote.provider_id for e in backward.entries
    ]
    assert [e.loss_reasons for e in forward.entries] == [
        e.loss_reasons for e in backward.entries
    ]


def test_race_stale_quote_is_preserved_and_never_wins() -> None:
    stale_high = _quote(
        provider_id="stale-big",
        output_amount_raw=999_000,
        received_at_ns=NOW_NS - MAX_AGE_NS - 1,
    )
    fresh_low = _quote(provider_id="jupiter", output_amount_raw=990_000)
    result = QuoteRaceResult.build(
        request=_request(), quotes=[stale_high, fresh_low], now_ns=NOW_NS
    )
    assert result.winner is not None and result.winner.provider_id == "jupiter"
    assert [entry.quote.provider_id for entry in result.entries] == [
        "jupiter",
        "stale-big",
    ]
    assert result.entries[1].loss_reasons[0] is QuoteLossReason.STALE


def test_race_slot_gap_beyond_bound_marks_quote_stale() -> None:
    fresh = _quote(provider_id="jupiter", slot=700, output_amount_raw=990_000)
    lagging = _quote(provider_id="0x", slot=700 - 33, output_amount_raw=995_000)
    result = QuoteRaceResult.build(
        request=_request(max_slot_gap=32),
        quotes=[fresh, lagging],
        now_ns=NOW_NS,
    )
    assert result.winner is not None and result.winner.provider_id == "jupiter"
    assert QuoteLossReason.STALE in result.entries[1].loss_reasons


def test_race_preserves_failed_reads_as_typed_negatives() -> None:
    failure = ProviderReadFailure(
        provider_id="openocean",
        failure_class=ProviderReadFailureClass.MISSING_CREDENTIAL,
        detail="OPENOCEAN_API_KEY not configured",
    )
    result = QuoteRaceResult.build(
        request=_request(),
        quotes=_race_quotes()[:1],
        failures=[failure],
        now_ns=NOW_NS,
    )
    assert result.failures == (failure,)
    assert (
        result.failures[0].failure_class is ProviderReadFailureClass.MISSING_CREDENTIAL
    )
    assert len(result.entries) == 1


def test_race_refuses_amount_and_taker_parity_mismatches() -> None:
    off_amount = _quote(provider_id="jupiter", output_amount_raw=990_000)
    request = _request(amount_raw=AMOUNT + 1)
    with pytest.raises(QuoteComparabilityError) as amount_exc:
        QuoteRaceResult.build(request=request, quotes=[off_amount], now_ns=NOW_NS)
    assert amount_exc.value.code is KernelErrorCode.COMPARABILITY_MISMATCH

    taker_quote = _quote(
        provider_id="0x", taker="6QWeT6FpJrm8AF1btu6WH2k2Xhq6t5vbheKVfQavmenB"
    )
    with pytest.raises(QuoteComparabilityError) as taker_exc:
        QuoteRaceResult.build(request=_request(), quotes=[taker_quote], now_ns=NOW_NS)
    assert taker_exc.value.code is KernelErrorCode.COMPARABILITY_MISMATCH


def test_race_refuses_future_observation_and_duplicate_providers() -> None:
    future = _quote(provider_id="jupiter", received_at_ns=NOW_NS + 1)
    with pytest.raises(QuoteComparabilityError) as future_exc:
        QuoteRaceResult.build(request=_request(), quotes=[future], now_ns=NOW_NS)
    assert future_exc.value.code is KernelErrorCode.FUTURE_OBSERVATION

    with pytest.raises(QuoteRaceStateError):
        QuoteRaceResult.build(
            request=_request(),
            quotes=[_quote(provider_id="jupiter"), _quote(provider_id="jupiter")],
            now_ns=NOW_NS,
        )


def test_race_without_fresh_quotes_has_no_winner() -> None:
    stale = _quote(provider_id="jupiter", received_at_ns=NOW_NS - MAX_AGE_NS - 1)
    result = QuoteRaceResult.build(request=_request(), quotes=[stale], now_ns=NOW_NS)
    assert result.winner is None
    with pytest.raises(QuoteRaceStateError) as excinfo:
        result.require_winner()
    assert excinfo.value.code is KernelErrorCode.RACE_NO_WINNER


def test_race_marks_unproven_minimum_output_on_losers() -> None:
    winner = _quote(provider_id="jupiter", output_amount_raw=990_000)
    loser = _quote(
        provider_id="0x",
        correlation_group="0x-solana-router",
        pool_ids=(POOL_ORCA,),
        output_amount_raw=989_000,
        minimum_output_raw=None,
    )
    result = QuoteRaceResult.build(
        request=_request(), quotes=[winner, loser], now_ns=NOW_NS
    )
    assert result.entries[1].loss_reasons == (
        QuoteLossReason.INFERIOR_OUTPUT,
        QuoteLossReason.MINIMUM_OUTPUT_UNPROVEN,
    )


def test_race_entry_validation_requires_typed_loss_reasons() -> None:
    quote = _quote(provider_id="jupiter")
    with pytest.raises(KernelContractError):
        RankedQuoteEntry(quote=quote, rank=1, verdict=RaceVerdict.LOST)
    with pytest.raises(KernelContractError):
        RankedQuoteEntry(
            quote=quote,
            rank=0,
            verdict=RaceVerdict.WON,
            loss_reasons=(QuoteLossReason.STALE,),
        )


# ---------------------------------------------------------------------------
# 5. No-extrapolation invariant (every sizing point requires a re-quote)
# ---------------------------------------------------------------------------


def test_exact_bound_amount_is_allowed() -> None:
    quote = _quote(provider_id="jupiter")
    assert (
        refuse_amount_extrapolation(quote, AMOUNT, purpose="flashloan_size") == AMOUNT
    )


def test_amount_neighborhood_extrapolation_is_refused() -> None:
    quote = _quote(provider_id="jupiter")
    neighborhood = [AMOUNT + 1, AMOUNT - 1, int(AMOUNT * 1.001), int(AMOUNT * 0.999)]
    for proposed in neighborhood:
        with pytest.raises(QuoteExtrapolationError) as excinfo:
            refuse_amount_extrapolation(quote, proposed, purpose="sizing")
        assert excinfo.value.code is KernelErrorCode.EXTRAPOLATION_REFUSED
        assert "fresh quote at the exact amount" in excinfo.value.message
        assert str(proposed) in excinfo.value.message


def test_extrapolation_guard_refuses_non_positive_and_non_integer_amounts() -> None:
    quote = _quote(provider_id="jupiter")
    for bad in (0, -5, 1_000_000.5, "1000000"):
        with pytest.raises(QuoteExtrapolationError):
            refuse_amount_extrapolation(quote, bad, purpose="sizing")  # type: ignore[arg-type]


def test_exact_out_quotes_bind_output_amount_for_sizing() -> None:
    quote = NormalizedProviderQuote(
        provider_id="sevenk",
        provider_generation="gen-r13k-fixture",
        chain="sui",
        direction=QuoteDirection.EXACT_OUT,
        input_representation_id="sui-sui-9dec",
        output_representation_id="sui-usdc-6dec",
        input_amount_raw=990_000_000,
        output_amount_raw=AMOUNT,
        input_amount_normalized=990_000_000,
        output_amount_normalized=AMOUNT,
        correlation=ProviderCorrelation(correlation_group="sevenk-bluefin7k"),
        freshness=QuoteFreshness(received_at_ns=NOW_NS, checkpoint_sequence=41),
        raw_response_hash=hashlib.sha256(b"sevenk").hexdigest(),
        request_fingerprint="req-sevenk",
    )
    assert quote.bound_amount_raw == AMOUNT
    assert (
        refuse_amount_extrapolation(quote, AMOUNT, purpose="flash_repay_size") == AMOUNT
    )
    with pytest.raises(QuoteExtrapolationError):
        refuse_amount_extrapolation(quote, AMOUNT - 1, purpose="flash_repay_size")


# ---------------------------------------------------------------------------
# 6. BuildHandoff: typed reference to a REAL R-03 plan, no construction
# ---------------------------------------------------------------------------


def _won_race(winner_provider: str = "jupiter") -> QuoteRaceResult:
    winner = _quote(
        provider_id=winner_provider,
        pool_ids=(POOL_RAYDIUM,),
        output_amount_raw=990_000,
    )
    loser = _quote(
        provider_id="0x",
        correlation_group="0x-solana-router",
        pool_ids=(POOL_RAYDIUM,),
        output_amount_raw=989_000,
    )
    return QuoteRaceResult.build(
        request=_request(), quotes=[winner, loser], now_ns=NOW_NS
    )


def test_build_handoff_binds_won_quote_to_real_r03_plan() -> None:
    race = _won_race()
    plan = _kamino_borrow_plan()
    handoff = BuildHandoff(
        race_result=race,
        won_quote=race.require_winner(),
        builder_provider="kamino",
        builder_build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
        plan=plan,
    )
    assert handoff.plan is plan
    assert handoff.builder_build_status is BuildStatus.BUILT_OFFLINE_UNQUALIFIED
    assert handoff.handoff_fingerprint == handoff.handoff_fingerprint
    assert (
        handoff.require_sizing_amount(AMOUNT, purpose="kamino_flash_borrow") == AMOUNT
    )
    with pytest.raises(QuoteExtrapolationError):
        handoff.require_sizing_amount(AMOUNT + 1, purpose="kamino_flash_borrow")


def test_build_handoff_refuses_non_winner_quote() -> None:
    race = _won_race()
    loser_entry = race.entries[1]
    with pytest.raises(BuildHandoffError) as excinfo:
        BuildHandoff(
            race_result=race,
            won_quote=loser_entry.quote,
            builder_provider="kamino",
            builder_build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
            plan=_kamino_borrow_plan(),
        )
    assert excinfo.value.code is KernelErrorCode.HANDOFF_NOT_WINNER


def test_build_handoff_refuses_status_forgery_and_provider_mismatch() -> None:
    race = _won_race()
    blocked = _kamino_borrow_plan(build_status=BuildStatus.BLOCKED_INPUT_REQUIRED)
    with pytest.raises(BuildHandoffError) as status_exc:
        BuildHandoff(
            race_result=race,
            won_quote=race.require_winner(),
            builder_provider="kamino",
            builder_build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
            plan=blocked,
        )
    assert status_exc.value.code is KernelErrorCode.HANDOFF_INTEGRITY

    with pytest.raises(BuildHandoffError) as provider_exc:
        BuildHandoff(
            race_result=race,
            won_quote=race.require_winner(),
            builder_provider="navi",
            builder_build_status=BuildStatus.BLOCKED_INPUT_REQUIRED,
            plan=blocked,
        )
    assert provider_exc.value.code is KernelErrorCode.HANDOFF_INTEGRITY


def test_build_handoff_allows_truthfully_recorded_blocked_plan() -> None:
    race = _won_race()
    blocked = _kamino_borrow_plan(build_status=BuildStatus.BLOCKED_INPUT_REQUIRED)
    handoff = BuildHandoff(
        race_result=race,
        won_quote=race.require_winner(),
        builder_provider="kamino",
        builder_build_status=BuildStatus.BLOCKED_INPUT_REQUIRED,
        plan=blocked,
    )
    assert handoff.builder_build_status is BuildStatus.BLOCKED_INPUT_REQUIRED


def test_build_handoff_requires_race_winner_and_matching_chain() -> None:
    stale_only = _quote(provider_id="jupiter", received_at_ns=NOW_NS - MAX_AGE_NS - 1)
    empty_race = QuoteRaceResult.build(
        request=_request(), quotes=[stale_only], now_ns=NOW_NS
    )
    with pytest.raises(BuildHandoffError) as excinfo:
        BuildHandoff(
            race_result=empty_race,
            won_quote=stale_only,
            builder_provider="kamino",
            builder_build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
            plan=_kamino_borrow_plan(),
        )
    assert excinfo.value.code is KernelErrorCode.HANDOFF_NOT_WINNER

    sui_quote = _quote(provider_id="jupiter", chain="sui")
    sui_request = dataclasses.replace(_request(), chain="sui")
    sui_race = QuoteRaceResult.build(
        request=sui_request,
        quotes=[sui_quote],
        now_ns=NOW_NS,
    )
    assert sui_quote.chain == "sui"
    with pytest.raises(BuildHandoffError) as chain_exc:
        BuildHandoff(
            race_result=sui_race,
            won_quote=sui_race.require_winner(),
            builder_provider="kamino",
            builder_build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
            plan=_kamino_borrow_plan(),
        )
    assert chain_exc.value.code is KernelErrorCode.HANDOFF_INTEGRITY


def test_build_handoff_rejects_non_r03_status_enum() -> None:
    race = _won_race()
    with pytest.raises(BuildHandoffError):
        BuildHandoff(
            race_result=race,
            won_quote=race.require_winner(),
            builder_provider="kamino",
            builder_build_status="built_offline_unqualified",  # type: ignore[arg-type]
            plan=_kamino_borrow_plan(),
        )
