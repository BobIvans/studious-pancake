"""R13-A1 Titan quote adapter tests (offline, deterministic, zero network).

Pins the fail-closed behavior of ``src/solana_parallel_radar/providers/titan.py``
against the frozen kernel contract (``src/execution/quote_build_kernel.py``)
and the pinned Titan schema
(``docs/integrations/offline/titan-adapter-2026-11-14/TITAN_ADAPTER_SCHEMA_PIN.md``):

- positives: canonical fixture -> exact kernel ``NormalizedProviderQuote``
  fields (amounts, freshness, fees, venues, correlation, build-output class);
- negatives: schema drift, missing amounts, unpinned encodings, empty quotes,
  429/timeout typed failures — every refusal is typed, nothing is guessed;
- race/freshness: a stale quote never wins (kernel freshness bounds), slot-gap
  staleness, all evidence preserved with typed loss reasons;
- dedup: Titan ``Okx`` entries correlate with OKX DEX captures per the wave-1
  overlap notes (lineage + shared pool), transitively grouped;
- extrapolation: the kernel no-extrapolation invariant refuses any amount
  other than the quote's exact bound amount.

Zero network: no transport ships with the adapter; every transport in these
tests is an injected pure callable or ``None`` (typed DISABLED refusal).
pytest-socket applies in CI. Nothing signs, sends, or enables a provider, and
``probes.py``/``funnel.py`` are untouched (funnel wiring DEFERRED).
"""

from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path

import pytest

from src.execution.quote_build_kernel import (
    FeeInclusionState,
    IndependenceVerdict,
    KernelContractError,
    MAX_AGE_NS,
    NormalizedProviderQuote,
    PoolIdentity,
    PoolIdentityDeduplicator,
    PoolIdentityKind,
    ProviderCorrelation,
    ProviderReadFailureClass,
    QuoteDirection,
    QuoteExtrapolationError,
    QuoteFreshness,
    QuoteLossReason,
    QuoteRaceResult,
    RaceVerdict,
    refuse_amount_extrapolation,
)
from src.solana_parallel_radar.providers import titan as titan_module
from src.solana_parallel_radar.providers.titan import (
    TITAN_CHAIN,
    TITAN_CORRELATION_GROUP,
    TITAN_EVIDENCE_STATE,
    TITAN_LIVE_CAPTURE_BLOCKED,
    TitanBuildOutputClass,
    TitanFailureCode,
    TitanSwapQuoteRequest,
    build_kernel_race_request,
    kernel_race_inputs,
    map_http_status_failure,
    normalize_titan_quote_response,
    normalize_via_transport,
    titan_live_capture_verdict,
)

pytestmark = pytest.mark.unit

FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "r13_titan_adapter"
    / "quote_swap_portal_wave1.json"
)

INPUT_MINT = "So11111111111111111111111111111111111111112"
OUTPUT_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USER_KEY = "72neGwRAi6QWsFQjy3PkDuYBC5GNCRwC2aUMGcrkoJuP"
INPUT_REPR = "solana-wsol-6dec"
OUTPUT_REPR = "solana-usdc-6dec"
AMOUNT_RAW = 1_000_000_000
NOW_NS = 1_800_000_000_000_000_000
POOL_RAYDIUM_AMM_KEY = "8bxkJSQp9dVYqMjC7WD67CYvdATUdqUPeGrD4AuFPMWF"
POOL_ORCA_AMM_KEY = "CtZAcRdmMb6NkKxtB9rTWPFSsMCLHMicyFaC8nmzK9vL"


def _load_fixture() -> dict[str, object]:
    with FIXTURE_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _make_request() -> TitanSwapQuoteRequest:
    return TitanSwapQuoteRequest(
        input_mint=INPUT_MINT,
        output_mint=OUTPUT_MINT,
        amount_raw=AMOUNT_RAW,
        user_public_key=USER_KEY,
        input_representation_id=INPUT_REPR,
        output_representation_id=OUTPUT_REPR,
        slippage_bps=50,
    )


def _parse(
    payload: dict[str, object], *, received_at_ns: int = NOW_NS
) -> "titan_module.TitanQuoteBatch":
    return normalize_titan_quote_response(
        payload, request=_make_request(), received_at_ns=received_at_ns
    )


def _entry_by_key(
    batch: "titan_module.TitanQuoteBatch", key: str
) -> "titan_module.TitanQuoteEntry":
    for entry in batch.entries:
        if entry.provider_entry == key:
            return entry
    raise AssertionError(f"missing fixture entry {key!r}")


def _okx_direct_quote(
    pool_keys: tuple[str, ...], *, slot: int = 300_000_001
) -> NormalizedProviderQuote:
    """Synthetic OKX-DEX-direct capture for dedup interaction tests.

    Kernel-level evidence record (not parsed through the Titan adapter): one
    OKX capture sharing a Titan ``Okx``-entry pool demonstrates the overlap
    note "one OKX capture can quote the same pools as a Titan capture".
    """
    return NormalizedProviderQuote(
        provider_id="okx-dex",
        provider_generation="okx.dex-aggregator.capture-2026-11-14",
        chain=TITAN_CHAIN,
        direction=QuoteDirection.EXACT_IN,
        input_representation_id=INPUT_REPR,
        output_representation_id=OUTPUT_REPR,
        input_amount_raw=AMOUNT_RAW,
        output_amount_raw=162_240_000,
        input_amount_normalized=AMOUNT_RAW,
        output_amount_normalized=162_240_000,
        correlation=ProviderCorrelation(
            correlation_group="okx-dex",
            aggregator_lineage=("okx",),
            pool_ids=tuple(
                PoolIdentity(PoolIdentityKind.AMM_KEY, key) for key in pool_keys
            ),
        ),
        freshness=QuoteFreshness(
            received_at_ns=NOW_NS,
            slot=slot,
        ),
        taker=USER_KEY,
        raw_response_hash="a" * 64,
        request_fingerprint="okx-request-fingerprint",
    )


# --------------------------------------------------------------------------
# Gate + disabled stance
# --------------------------------------------------------------------------


def test_live_capture_gate_is_constant_blocked() -> None:
    verdict = titan_live_capture_verdict()
    assert verdict.status == "BLOCKED"
    assert verdict.reason == TITAN_LIVE_CAPTURE_BLOCKED
    assert verdict.reason == "TITAN_LIVE_CAPTURE_NOT_AUTHORIZED"
    assert verdict.evidence_state == TITAN_EVIDENCE_STATE
    assert verdict.evidence_state == "ADAPTER_BUILT_OFFLINE_UNQUALIFIED"


def test_adapter_ships_no_transport_none_is_typed_disabled() -> None:
    with pytest.raises(titan_module.TitanAdapterError) as excinfo:
        normalize_via_transport(None, _make_request(), received_at_ns=NOW_NS)
    assert excinfo.value.code is TitanFailureCode.DISABLED
    assert TITAN_LIVE_CAPTURE_BLOCKED in excinfo.value.detail


# --------------------------------------------------------------------------
# Typed request construction (portal REST, pinned params only)
# --------------------------------------------------------------------------


def test_request_query_params_exact_pinned_schema() -> None:
    params = _make_request().query_params()
    assert params == {
        "inputMint": INPUT_MINT,
        "outputMint": OUTPUT_MINT,
        "amount": str(AMOUNT_RAW),
        "userPublicKey": USER_KEY,
        "slippageBps": "50",
    }


def test_request_fee_params_and_deterministic_fingerprint() -> None:
    request = dataclasses.replace(
        _make_request(),
        fee_account="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        fee_bps=10,
        fee_from_input_mint=False,
    )
    params = request.query_params()
    assert params["feeAccount"] == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    assert params["feeBps"] == "10"
    assert params["feeFromInputMint"] == "false"
    assert request.request_fingerprint == request.request_fingerprint
    assert len(request.request_fingerprint) == 64


@pytest.mark.parametrize(
    "mutation, expected_code",
    [
        pytest.param(
            lambda r: dataclasses.replace(r, input_mint="not_base58!!"),
            TitanFailureCode.REQUEST_INVALID,
            id="bad-input-mint",
        ),
        pytest.param(
            lambda r: dataclasses.replace(r, user_public_key=""),
            TitanFailureCode.REQUEST_INVALID,
            id="missing-user-public-key",
        ),
        pytest.param(
            lambda r: dataclasses.replace(r, amount_raw=0),
            TitanFailureCode.REQUEST_INVALID,
            id="non-positive-amount",
        ),
        pytest.param(
            lambda r: dataclasses.replace(r, amount_raw=1.5),
            TitanFailureCode.REQUEST_INVALID,
            id="float-amount",
        ),
        pytest.param(
            lambda r: dataclasses.replace(r, fee_bps=10_001),
            TitanFailureCode.REQUEST_INVALID,
            id="fee-bps-above-documented-limit",
        ),
        pytest.param(
            lambda r: dataclasses.replace(
                r,
                input_representation_id="same",
                output_representation_id="same",
            ),
            TitanFailureCode.REQUEST_INVALID,
            id="identical-representations",
        ),
    ],
)
def test_request_rejects_invalid_constructions(
    mutation, expected_code: TitanFailureCode
) -> None:
    with pytest.raises(titan_module.TitanAdapterError) as excinfo:
        mutation(_make_request())
    assert excinfo.value.code is expected_code


def test_request_refuses_unpinned_portal_swap_mode() -> None:
    # The portal param table pins no swapMode query parameter (TITAN-U5);
    # emitting one would guess a shape.
    exact_out = dataclasses.replace(
        _make_request(), swap_direction=QuoteDirection.EXACT_OUT
    )
    with pytest.raises(titan_module.TitanAdapterError) as excinfo:
        exact_out.query_params()
    assert excinfo.value.code is TitanFailureCode.SCHEMA_MISSING_PIN


# --------------------------------------------------------------------------
# Normalization positives: fixture -> exact kernel evidence
# --------------------------------------------------------------------------


def test_canonical_fixture_parses_two_entries_no_failures() -> None:
    batch = _parse(_load_fixture())
    assert batch.batch_id == "qbatch-offline-2026-11-14-0001"
    assert batch.expected_winner == "Titan"
    assert batch.failures == ()
    assert tuple(entry.provider_entry for entry in batch.entries) == ("Titan", "Okx")
    assert len(batch.raw_payload_sha256) == 64


def test_titan_entry_kernel_quote_exact_fields() -> None:
    batch = _parse(_load_fixture())
    entry = _entry_by_key(batch, "Titan")
    quote = entry.normalized
    assert isinstance(quote, NormalizedProviderQuote)
    assert quote.provider_id == "titan:Titan"
    assert quote.provider_generation == "titan.swap-quote-api.wave1-2026-11-14"
    assert quote.chain == "solana"
    assert quote.direction is QuoteDirection.EXACT_IN
    assert quote.input_representation_id == INPUT_REPR
    assert quote.output_representation_id == OUTPUT_REPR
    assert quote.input_amount_raw == AMOUNT_RAW
    assert quote.output_amount_raw == 162_300_000
    # Pinned base-unit wire amounts: canonical representation IS base units.
    assert quote.input_amount_normalized == quote.input_amount_raw
    assert quote.output_amount_normalized == quote.output_amount_raw
    assert quote.taker == USER_KEY
    assert quote.execution_authority is False
    assert len(quote.raw_response_hash) == 64
    assert quote.request_fingerprint == _make_request().request_fingerprint


def test_titan_entry_freshness_slot_and_expiry_when_supplied() -> None:
    entry = _entry_by_key(_parse(_load_fixture()), "Titan")
    freshness = entry.normalized.freshness
    assert freshness.received_at_ns == NOW_NS
    assert freshness.slot == 300_000_001  # pinned optional contextSlot
    assert freshness.expires_at_ns == 1_800_000_003_000_000_000  # ms -> ns exact
    assert freshness.provider_generated_at_ns is None  # duration is not a timestamp
    assert entry.expires_after_slot == 300_000_033


def test_unknown_fields_stay_none_never_zero() -> None:
    entry = _entry_by_key(_parse(_load_fixture()), "Okx")
    quote = entry.normalized
    assert quote.minimum_output_raw is None  # no minOut on this surface
    assert quote.freshness.slot is None  # no contextSlot supplied
    assert quote.freshness.expires_at_ns is None  # no expiresAtMs supplied
    assert entry.compute_units_safe is None
    assert quote.compute_unit_estimate == 210_000  # computeUnits fallback


def test_correlation_group_lineage_and_pool_ids_exact() -> None:
    batch = _parse(_load_fixture())
    titan_entry = _entry_by_key(batch, "Titan")
    okx_entry = _entry_by_key(batch, "Okx")
    assert (
        titan_entry.normalized.correlation.correlation_group == TITAN_CORRELATION_GROUP
    )
    assert titan_entry.normalized.correlation.correlation_group == "titan-argos-router"
    assert titan_entry.normalized.correlation.aggregator_lineage == ("titan",)
    # Titan's quote map carries Okx/Metis entries (overlap notes): lineage
    # records the entry provider so OKX captures dedup against it.
    assert okx_entry.normalized.correlation.aggregator_lineage == ("okx", "titan")
    titan_pools = titan_entry.normalized.correlation.pool_ids
    okx_pools = okx_entry.normalized.correlation.pool_ids
    assert [pool.identity for pool in titan_pools] == [POOL_RAYDIUM_AMM_KEY]
    assert [pool.identity for pool in okx_pools] == [
        POOL_ORCA_AMM_KEY,
        "GdNvAQ9p5ScyeqVzzgNViGDNrkQ6qHz9KrSBS4aNXvGQ",
    ]
    assert all(
        pool.kind is PoolIdentityKind.AMM_KEY for pool in titan_pools + okx_pools
    )


def test_route_venues_labels_and_exact_share_conversion() -> None:
    batch = _parse(_load_fixture())
    titan_venues = _entry_by_key(batch, "Titan").normalized.route_venues
    assert len(titan_venues) == 1
    assert titan_venues[0].venue_label == "Raydium AMM"
    assert titan_venues[0].share_bps == 10_000  # 1_000_000_000 ppb exact
    assert titan_venues[0].pool is not None
    assert titan_venues[0].pool.identity == POOL_RAYDIUM_AMM_KEY
    okx_venues = _entry_by_key(batch, "Okx").normalized.route_venues
    assert [venue.share_bps for venue in okx_venues] == [7_000, 3_000]
    assert [venue.venue_label for venue in okx_venues] == ["Orca Whirlpool", "Phoenix"]


def test_non_divisible_alloc_ppb_stays_unknown_never_rounded() -> None:
    payload = _load_fixture()
    payload["quotes"]["Okx"]["steps"][0]["allocPpb"] = 123_456_789
    entry = _entry_by_key(_parse(payload), "Okx")
    assert entry.normalized.route_venues[0].share_bps is None
    assert entry.normalized.route_venues[1].share_bps == 3_000


def test_platform_fee_component_proven_inclusion_unknown_side() -> None:
    entry = _entry_by_key(_parse(_load_fixture()), "Titan")
    fees = entry.normalized.fees
    assert [fee.kind for fee in fees] == ["platform_fee"]
    fee = fees[0]
    assert fee.amount_raw == 162_300
    assert fee.rate_text == "10bps"  # documented request feeBps / response fee_bps
    assert fee.inclusion_state is FeeInclusionState.PROVEN
    assert fee.asset_id is None  # fee side not carried by the response


def test_route_step_venue_fee_component_unknown_inclusion() -> None:
    entry = _entry_by_key(_parse(_load_fixture()), "Okx")
    fees = entry.normalized.fees
    assert [fee.kind for fee in fees] == ["route_step_1_venue_fee"]
    assert fees[0].amount_raw == 1_000
    assert fees[0].asset_id == OUTPUT_MINT
    assert fees[0].inclusion_state is FeeInclusionState.UNKNOWN


def test_build_output_classification_instruction_bundle() -> None:
    entry = _entry_by_key(_parse(_load_fixture()), "Titan")
    assert entry.build_output is TitanBuildOutputClass.INSTRUCTION_BUNDLE
    assert entry.instruction_program_ids == (
        "ComputeBudget1111111111111111111111111111111",
        "T1TANpTeScyeqVzzgNViGDNrkQ6qHz9KrSBS4aNXvGT",
    )
    assert entry.alt_addresses == ("4vLTpTeScyeqVzzgNViGDNrkQ6qHz9KrSBS4aNXvGTw",)
    assert entry.recommended_winner is True


def test_build_output_classification_unsigned_transaction_evidence_only() -> None:
    entry = _entry_by_key(_parse(_load_fixture()), "Okx")
    assert entry.build_output is TitanBuildOutputClass.UNSIGNED_TRANSACTION
    assert entry.instruction_program_ids == ()
    assert entry.reference_id == "okx-rfq-ref-0001"
    # The opaque transaction string is never carried into the kernel quote.
    assert all(
        "transaction" not in str(field_value)
        for field_value in dataclasses.asdict(entry.normalized).values()
    )


def test_build_output_classification_quote_only() -> None:
    payload = _load_fixture()
    payload["quotes"]["Titan"]["instructions"] = []
    entry = _entry_by_key(_parse(payload), "Titan")
    assert entry.build_output is TitanBuildOutputClass.QUOTE_ONLY
    assert entry.instruction_program_ids == ()


def test_compute_unit_estimate_prefers_safe_budget() -> None:
    entry = _entry_by_key(_parse(_load_fixture()), "Titan")
    assert entry.compute_units == 180_000
    assert entry.compute_units_safe == 200_000
    assert entry.normalized.compute_unit_estimate == 200_000


def test_expected_winner_flag_only_on_recommended_entry() -> None:
    batch = _parse(_load_fixture())
    assert _entry_by_key(batch, "Titan").recommended_winner is True
    assert _entry_by_key(batch, "Okx").recommended_winner is False


def test_kernel_race_wins_expected_winner_and_preserves_losers() -> None:
    batch = _parse(_load_fixture())
    quotes, failures = kernel_race_inputs(batch)
    assert failures == ()
    race = QuoteRaceResult.build(
        request=build_kernel_race_request(_make_request()),
        quotes=list(quotes),
        failures=list(failures),
        now_ns=NOW_NS,
    )
    winner = race.require_winner()
    assert winner.provider_id == "titan:Titan"
    assert winner.output_amount_raw == 162_300_000
    assert race.entries[0].verdict is RaceVerdict.WON
    loser = race.entries[1]
    assert loser.quote.provider_id == "titan:Okx"
    assert loser.verdict is RaceVerdict.LOST
    assert QuoteLossReason.INFERIOR_OUTPUT in loser.loss_reasons
    assert QuoteLossReason.MINIMUM_OUTPUT_UNPROVEN in loser.loss_reasons


# --------------------------------------------------------------------------
# Negatives: typed schema drift, missing amounts, unpinned encodings
# --------------------------------------------------------------------------


def test_quotes_not_a_map_is_batch_level_invalid_schema() -> None:
    payload = _load_fixture()
    payload["quotes"] = ["Titan"]
    batch = _parse(payload)
    assert batch.entries == ()
    assert len(batch.failures) == 1
    assert batch.failures[0].code is TitanFailureCode.INVALID_SCHEMA
    assert batch.failures[0].provider_entry == "titan"


def test_missing_id_is_batch_level_invalid_schema() -> None:
    payload = _load_fixture()
    del payload["id"]
    batch = _parse(payload)
    assert batch.entries == ()
    assert batch.failures[0].code is TitanFailureCode.INVALID_SCHEMA


def test_top_level_amount_mismatch_is_comparability_drift() -> None:
    payload = _load_fixture()
    payload["amount"] = 999
    batch = _parse(payload)
    assert batch.entries == ()
    assert batch.failures[0].code is TitanFailureCode.COMPARABILITY_DRIFT


def test_top_level_mint_mismatch_is_comparability_drift() -> None:
    payload = _load_fixture()
    payload["outputMint"] = INPUT_MINT
    batch = _parse(payload)
    assert batch.entries == ()
    assert batch.failures[0].code is TitanFailureCode.COMPARABILITY_DRIFT


def test_unknown_swap_mode_wire_value_is_schema_missing_pin() -> None:
    payload = _load_fixture()
    payload["swapMode"] = "ExactInOut"
    batch = _parse(payload)
    assert batch.entries == ()
    assert batch.failures[0].code is TitanFailureCode.SCHEMA_MISSING_PIN


def test_string_encoded_amount_is_missing_pin_not_parsed() -> None:
    # TITAN-U1: portal JSON u64 encoding unpinned; a string amount is never
    # guessed into an integer.
    payload = _load_fixture()
    payload["quotes"]["Titan"]["outAmount"] = "162300000"
    batch = _parse(payload)
    assert [entry.provider_entry for entry in batch.entries] == ["Okx"]
    assert batch.failures[0].code is TitanFailureCode.SCHEMA_MISSING_PIN
    assert batch.failures[0].provider_entry == "Titan"


def test_missing_steps_key_is_entry_level_invalid_schema() -> None:
    payload = _load_fixture()
    del payload["quotes"]["Titan"]["steps"]
    batch = _parse(payload)
    assert [entry.provider_entry for entry in batch.entries] == ["Okx"]
    assert batch.failures[0].code is TitanFailureCode.INVALID_SCHEMA
    assert batch.failures[0].provider_entry == "Titan"


def test_entry_amount_mismatch_is_comparability_drift() -> None:
    payload = _load_fixture()
    payload["quotes"]["Okx"]["inAmount"] = 999_999_999
    batch = _parse(payload)
    assert [entry.provider_entry for entry in batch.entries] == ["Titan"]
    assert batch.failures[0].code is TitanFailureCode.COMPARABILITY_DRIFT


def test_unpinned_instruction_data_is_missing_pin() -> None:
    payload = _load_fixture()
    payload["quotes"]["Titan"]["instructions"][0]["d"] = ["ff"]
    batch = _parse(payload)
    assert batch.failures[0].code is TitanFailureCode.SCHEMA_MISSING_PIN


def test_transaction_with_instructions_is_schema_drift() -> None:
    payload = _load_fixture()
    payload["quotes"]["Titan"]["transaction"] = "5OpaqueEvidenceOnly0000"
    batch = _parse(payload)
    assert [entry.provider_entry for entry in batch.entries] == ["Okx"]
    assert batch.failures[0].code is TitanFailureCode.INVALID_SCHEMA


def test_expected_winner_not_in_quotes_is_invalid_schema() -> None:
    payload = _load_fixture()
    payload["metadata"]["ExpectedWinner"] = "Missing"
    batch = _parse(payload)
    assert batch.entries == ()
    assert batch.failures[0].code is TitanFailureCode.INVALID_SCHEMA


def test_steps_beyond_kernel_venue_bound_are_refused() -> None:
    payload = _load_fixture()
    big_step = copy.deepcopy(payload["quotes"]["Okx"]["steps"][0])
    payload["quotes"]["Okx"]["steps"] = [big_step] * 33
    batch = _parse(payload)
    assert [entry.provider_entry for entry in batch.entries] == ["Titan"]
    assert batch.failures[0].code is TitanFailureCode.INVALID_SCHEMA


def test_empty_quotes_map_is_typed_empty_quotes_not_drift() -> None:
    payload = _load_fixture()
    payload["quotes"] = {}
    batch = _parse(payload)
    assert batch.entries == ()
    assert batch.failures[0].code is TitanFailureCode.EMPTY_QUOTES
    kernel_failure = batch.failures[0].to_kernel_failure()
    assert kernel_failure.failure_class is ProviderReadFailureClass.HTTP_ERROR
    assert "no quotes returned" in kernel_failure.detail


def test_failure_kernel_mapping_table() -> None:
    assert (
        map_http_status_failure(429, "slow down").kernel_failure_class
        is ProviderReadFailureClass.RATE_LIMITED
    )
    assert (
        map_http_status_failure(429, "slow down").code is TitanFailureCode.RATE_LIMITED
    )
    assert (
        map_http_status_failure(401, "credential mismatch").kernel_failure_class
        is ProviderReadFailureClass.UNAUTHORIZED
    )
    assert (
        map_http_status_failure(500, "boom").kernel_failure_class
        is ProviderReadFailureClass.HTTP_ERROR
    )
    assert map_http_status_failure(418, "teapot").code is TitanFailureCode.HTTP_ERROR


def test_transport_timeout_and_error_are_typed_failures() -> None:
    def timeout_transport(request: TitanSwapQuoteRequest) -> dict[str, object]:
        raise TimeoutError("injected timeout")

    def broken_transport(request: TitanSwapQuoteRequest) -> dict[str, object]:
        raise ValueError("injected transport break")

    timeout_batch = normalize_via_transport(
        timeout_transport, _make_request(), received_at_ns=NOW_NS
    )
    assert timeout_batch.entries == ()
    assert timeout_batch.failures[0].code is TitanFailureCode.TIMEOUT
    assert (
        timeout_batch.failures[0].kernel_failure_class
        is ProviderReadFailureClass.TRANSPORT
    )
    broken_batch = normalize_via_transport(
        broken_transport, _make_request(), received_at_ns=NOW_NS
    )
    assert broken_batch.entries == ()
    assert broken_batch.failures[0].code is TitanFailureCode.TRANSPORT


def test_injected_fixture_transport_round_trip() -> None:
    payload = _load_fixture()
    batch = normalize_via_transport(
        lambda request: payload, _make_request(), received_at_ns=NOW_NS
    )
    assert tuple(entry.provider_entry for entry in batch.entries) == ("Titan", "Okx")
    assert batch.failures == ()


# --------------------------------------------------------------------------
# Freshness bounds: a stale quote never wins
# --------------------------------------------------------------------------


def test_stale_quote_never_wins_per_kernel_freshness_bound() -> None:
    batch = _parse(_load_fixture())
    quotes, failures = kernel_race_inputs(batch)
    # Push the highest-output quote (titan:Titan) beyond the kernel default
    # freshness bound; the kernel must still win the lower fresh quote.
    stale_quotes = [
        (
            titan_module._stale_copy(quote, NOW_NS - MAX_AGE_NS - 1_000_000_000)
            if quote.provider_id == "titan:Titan"
            else quote
        )
        for quote in quotes
    ]
    race = QuoteRaceResult.build(
        request=build_kernel_race_request(_make_request()),
        quotes=stale_quotes,
        failures=list(failures),
        now_ns=NOW_NS,
    )
    winner = race.require_winner()
    assert winner.provider_id == "titan:Okx"
    stale_entry = race.entries[1]
    assert stale_entry.quote.provider_id == "titan:Titan"
    assert stale_entry.verdict is RaceVerdict.LOST
    assert QuoteLossReason.STALE in stale_entry.loss_reasons


def test_slot_gap_beyond_request_bound_is_stale() -> None:
    batch = _parse(_load_fixture())
    quotes, _ = kernel_race_inputs(batch)
    race_request = dataclasses.replace(
        build_kernel_race_request(_make_request()), max_slot_gap=0
    )
    # okx-direct observes the newest slot; the Titan entry (slot 300000001,
    # gap 32 > 0) must be flagged stale and never win.
    okx_direct = _okx_direct_quote(pool_keys=(POOL_ORCA_AMM_KEY,), slot=300_000_033)
    race = QuoteRaceResult.build(
        request=race_request,
        quotes=[*quotes, okx_direct],
        failures=[],
        now_ns=NOW_NS,
    )
    winner = race.require_winner()
    # Fresh eligible set: titan:Okx (slotless, 162250000 out) and okx-dex
    # (162240000 out); titan:Titan is slot-stale and must not win despite
    # its higher output.
    assert winner.provider_id == "titan:Okx"
    titan_entry = next(
        entry for entry in race.entries if entry.quote.provider_id == "titan:Titan"
    )
    assert QuoteLossReason.STALE in titan_entry.loss_reasons


def test_future_observation_is_refused_not_shifted() -> None:
    batch = _parse(_load_fixture(), received_at_ns=NOW_NS + 1)
    quotes, _ = kernel_race_inputs(batch)
    with pytest.raises(KernelContractError):
        QuoteRaceResult.build(
            request=build_kernel_race_request(_make_request()),
            quotes=list(quotes),
            failures=[],
            now_ns=NOW_NS,
        )


# --------------------------------------------------------------------------
# Pool-identity dedup interaction (overlap notes: Titan carries Okx entries)
# --------------------------------------------------------------------------


def test_titan_okx_entry_correlates_with_okx_direct_capture() -> None:
    batch = _parse(_load_fixture())
    okx_entry = _entry_by_key(batch, "Okx")
    okx_direct = _okx_direct_quote(pool_keys=(POOL_ORCA_AMM_KEY,))
    verdict = PoolIdentityDeduplicator.correlation_verdict(
        okx_entry.normalized, okx_direct
    )
    assert verdict is IndependenceVerdict.CORRELATED
    shared = PoolIdentityDeduplicator.shared_pool_ids(okx_entry.normalized, okx_direct)
    assert [pool.identity for pool in shared] == [POOL_ORCA_AMM_KEY]
    assert PoolIdentityDeduplicator.shared_lineage(
        okx_entry.normalized, okx_direct
    ) == ("okx",)


def test_titan_entry_vs_okx_direct_with_disjoint_pools_is_independent() -> None:
    batch = _parse(_load_fixture())
    titan_entry = _entry_by_key(batch, "Titan")
    okx_direct = _okx_direct_quote(pool_keys=(POOL_ORCA_AMM_KEY,))
    # Positive disjoint evidence on both sides (non-empty disjoint pools,
    # disjoint lineage, different groups) — the only independence case.
    assert (
        PoolIdentityDeduplicator.correlation_verdict(titan_entry.normalized, okx_direct)
        is IndependenceVerdict.INDEPENDENT
    )


def test_okx_direct_without_pool_evidence_is_unknown_never_independent() -> None:
    batch = _parse(_load_fixture())
    titan_entry = _entry_by_key(batch, "Titan")
    blind_okx = _okx_direct_quote(pool_keys=())
    assert (
        PoolIdentityDeduplicator.correlation_verdict(titan_entry.normalized, blind_okx)
        is IndependenceVerdict.UNKNOWN
    )


def test_transitive_correlation_cluster_covers_titan_okx_and_okx_direct() -> None:
    batch = _parse(_load_fixture())
    quotes, _ = kernel_race_inputs(batch)
    okx_direct = _okx_direct_quote(pool_keys=(POOL_ORCA_AMM_KEY,))
    clusters = PoolIdentityDeduplicator.group_quotes([*quotes, okx_direct])
    # titan:Titan + titan:Okx share the operator group; titan:Okx + okx-dex
    # share lineage "okx" and the Orca pool -> one transitive cluster.
    assert len(clusters) == 1
    assert len(clusters[0].members) == 3


def test_race_labels_correlated_observations_as_losers() -> None:
    batch = _parse(_load_fixture())
    quotes, _ = kernel_race_inputs(batch)
    # One correlated duplicate of the winner: same operator group evidence.
    okx_direct = _okx_direct_quote(pool_keys=(POOL_RAYDIUM_AMM_KEY,))
    race = QuoteRaceResult.build(
        request=build_kernel_race_request(_make_request()),
        quotes=[*quotes, okx_direct],
        failures=[],
        now_ns=NOW_NS,
    )
    okx_entry = next(
        entry for entry in race.entries if entry.quote.provider_id == "okx-dex"
    )
    assert okx_entry.verdict is RaceVerdict.LOST
    assert QuoteLossReason.CORRELATED_OBSERVATION in okx_entry.loss_reasons


def test_independence_set_never_double_counts_titan_family() -> None:
    batch = _parse(_load_fixture())
    quotes, _ = kernel_race_inputs(batch)
    okx_direct = _okx_direct_quote(pool_keys=(POOL_ORCA_AMM_KEY,))
    independent = PoolIdentityDeduplicator.independence_set([*quotes, okx_direct])
    # All Titan-family members share one correlation group -> at most one
    # representative; okx-dex joins only via positive disjoint evidence.
    titan_family = [
        quote
        for quote in independent
        if quote.correlation.correlation_group == TITAN_CORRELATION_GROUP
    ]
    assert len(titan_family) <= 1


# --------------------------------------------------------------------------
# Extrapolation refusal through the kernel
# --------------------------------------------------------------------------


def test_exact_bound_amount_passes_refusal_guard() -> None:
    batch = _parse(_load_fixture())
    winner = _entry_by_key(batch, "Titan").normalized
    bound = winner.bound_amount_raw
    assert refuse_amount_extrapolation(winner, bound, purpose="exact-sizing") == bound


@pytest.mark.parametrize("off_by", [-1, 1, 1_000, -1_000])
def test_amount_neighborhood_extrapolation_is_refused(off_by: int) -> None:
    batch = _parse(_load_fixture())
    winner = _entry_by_key(batch, "Titan").normalized
    with pytest.raises(QuoteExtrapolationError):
        refuse_amount_extrapolation(
            winner, winner.bound_amount_raw + off_by, purpose="neighborhood"
        )


def test_extrapolation_refusal_through_build_handoff_guard_shape() -> None:
    # The typed kernel error must carry the frozen kernel code, proving the
    # adapter consumed the kernel invariant (not a local re-implementation).
    batch = _parse(_load_fixture())
    quote = _entry_by_key(batch, "Titan").normalized
    with pytest.raises(QuoteExtrapolationError) as excinfo:
        refuse_amount_extrapolation(quote, quote.bound_amount_raw * 2, purpose="scaled")
    assert excinfo.value.code.value == "R13_KERNEL_QUOTE_EXTRAPOLATION_REFUSED"


# --------------------------------------------------------------------------
# Offline replay helper
# --------------------------------------------------------------------------


def test_stale_copy_preserves_all_other_evidence() -> None:
    batch = _parse(_load_fixture())
    quote = _entry_by_key(batch, "Titan").normalized
    stale = titan_module._stale_copy(quote, NOW_NS - MAX_AGE_NS - 1)
    assert stale == dataclasses.replace(
        quote,
        freshness=dataclasses.replace(
            quote.freshness, received_at_ns=NOW_NS - MAX_AGE_NS - 1
        ),
    )
    assert stale.raw_response_hash == quote.raw_response_hash
    assert stale.correlation == quote.correlation
