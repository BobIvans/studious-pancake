"""R13-A2 Aftermath (Sui) quote adapter tests (offline, deterministic, zero network).

Pins the fail-closed behavior of ``src/gpr_sui_shadow/providers/aftermath.py``
against the frozen kernel contract (``src/execution/quote_build_kernel.py``)
and the pinned Aftermath schema
(``docs/integrations/offline/aftermath-adapter-2026-11-19/``):

- positives: canonical fixture -> exact kernel ``NormalizedProviderQuote``
  fields (amounts in MIST base units, freshness, fees, venues, correlation);
- negatives: schema drift, unpinned encodings, error envelopes (HTTP-200
  ``{error}`` / ``{error_code}`` / string / null), empty routes, amount/type
  drift, nonzero SOR tradeFee — every refusal is typed, nothing is guessed;
- disabled stance: no transport ships with the adapter; ``None`` transport is
  a typed DISABLED refusal and the live-capture verdict is always BLOCKED;
- race: kernel comparability holds for the built race request (win/loss with
  typed reasons, evidence preserved);
- dedup: an Aftermath quote correlates with a direct Cetus capture via both
  lineage intersection and shared pool object id (overlap notes); two
  Aftermath quotes are always one operator observation (same group);
- regression: the providers.py -> providers/ package conversion preserves the
  GPR-03 public import surface.

Zero network: no transport ships with the adapter; every transport in these
tests is an injected pure callable or ``None``. pytest-socket applies in CI.
Nothing signs, sends, or enables a provider, and funnel/intake wiring is
untouched (DEFERRED).
"""

from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path

import pytest

from src.execution.quote_build_kernel import (
    IndependenceVerdict,
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
from src.gpr_sui_shadow import providers as gpr_providers_package
from src.gpr_sui_shadow.providers import aftermath as am
from src.gpr_sui_shadow.providers.aftermath import (
    AFTERMATH_CHAIN,
    AFTERMATH_CORRELATION_GROUP,
    AFTERMATH_EVIDENCE_STATE,
    AFTERMATH_LIVE_CAPTURE_BLOCKED,
    AftermathAdapterError,
    AftermathFailureCode,
    AftermathSwapRouteRequest,
    aftermath_live_capture_verdict,
    build_kernel_race_request,
    kernel_race_inputs,
    map_http_status_failure,
    normalize_aftermath_trade_route_response,
    normalize_via_transport,
)

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures" / "r13_aftermath_adapter"
RECEIVED_AT_NS = 1_736_000_000_000_000_000

SUI_TYPE = "0x2::sui::SUI"
USDC_TYPE = (
    "0xdba34672e30cb065b1f93e3ab55318768fd6fef66c15942c9f7cb846e2f900e7" "::usdc::USDC"
)
CETUS_POOL = "0xfcc774493db2c45c79f688f88d28023a3e7d98e4ee9f48bbf5c7990f651577ae"
AFTERMATH_POOL = "0x28e499dff5e864a2eafe476269a4f5035f1c16f338da7be18b103499abf271ce"


def _request(**overrides: object) -> AftermathSwapRouteRequest:
    params: dict[str, object] = {
        "coin_in_type": SUI_TYPE,
        "coin_out_type": USDC_TYPE,
        "amount_raw": 1_500_000_000,  # 1.5 SUI in MIST (9 decimals)
        "direction": QuoteDirection.EXACT_IN,
        "input_representation_id": "sui:mainnet:sui",
        "output_representation_id": "sui:mainnet:usdc",
    }
    params.update(overrides)
    return AftermathSwapRouteRequest(**params)  # type: ignore[arg-type]


def _fixture_payload() -> dict[str, object]:
    return json.loads(
        (FIXTURES / "trade_route_exact_in.json").read_text(encoding="utf-8")
    )


# --------------------------------------------------------------------------
# Disabled stance (no transport ships; live capture never authorized)
# --------------------------------------------------------------------------


class TestDisabledStance:
    def test_none_transport_is_typed_disabled(self) -> None:
        with pytest.raises(AftermathAdapterError) as raised:
            normalize_via_transport(None, _request(), received_at_ns=RECEIVED_AT_NS)
        assert raised.value.code is AftermathFailureCode.DISABLED
        assert AFTERMATH_LIVE_CAPTURE_BLOCKED in raised.value.detail

    def test_live_capture_verdict_always_blocked(self) -> None:
        verdict = aftermath_live_capture_verdict()
        assert verdict.status == "BLOCKED"
        assert verdict.reason == AFTERMATH_LIVE_CAPTURE_BLOCKED
        assert verdict.evidence_state == AFTERMATH_EVIDENCE_STATE
        # Deterministic: repeated calls cannot drift toward authorization.
        assert aftermath_live_capture_verdict() == verdict

    def test_adapter_module_ships_no_network_imports(self) -> None:
        import ast

        tree = ast.parse(Path(am.__file__).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for forbidden in ("requests", "urllib.request", "httpx", "aiohttp", "socket"):
            assert forbidden not in imported, f"adapter must not import {forbidden}"


# --------------------------------------------------------------------------
# Request construction (pinned trade-route body)
# --------------------------------------------------------------------------


class TestRequestConstruction:
    def test_exact_in_body_has_only_pinned_fields(self) -> None:
        body = _request().body()
        assert body == {
            "coinInType": SUI_TYPE,
            "coinOutType": USDC_TYPE,
            "coinInAmount": 1_500_000_000,
        }

    def test_exact_out_requires_slippage(self) -> None:
        with pytest.raises(AftermathAdapterError) as raised:
            _request(direction=QuoteDirection.EXACT_OUT)
        assert raised.value.code is AftermathFailureCode.REQUEST_INVALID
        exact_out = _request(direction=QuoteDirection.EXACT_OUT, slippage=0.01)
        assert exact_out.body()["coinOutAmount"] == 1_500_000_000
        assert exact_out.body()["slippage"] == 0.01

    def test_exact_in_slippage_is_missing_pin(self) -> None:
        with pytest.raises(AftermathAdapterError) as raised:
            _request(slippage=0.01)
        assert raised.value.code is AftermathFailureCode.SCHEMA_MISSING_PIN

    def test_external_fee_bounded_by_pinned_sdk_maximum(self) -> None:
        from src.gpr_sui_shadow.providers.aftermath import AftermathExternalFee

        with pytest.raises(AftermathAdapterError):
            AftermathExternalFee(recipient="0x" + "ab" * 32, fee_percentage=0.51)
        fee = AftermathExternalFee(recipient="0x" + "ab" * 32, fee_percentage=0.01)
        assert _request(external_fee=fee).body()["externalFee"] == {
            "recipient": "0x" + "ab" * 32,
            "feePercentage": 0.01,
        }

    def test_whitelist_blacklist_mutually_exclusive(self) -> None:
        with pytest.raises(AftermathAdapterError) as raised:
            _request(
                protocol_whitelist=("Cetus",),
                protocol_blacklist=("BlueMove",),
            )
        assert raised.value.code is AftermathFailureCode.REQUEST_INVALID

    def test_amount_above_u64_refused(self) -> None:
        with pytest.raises(AftermathAdapterError):
            _request(amount_raw=2**64)


# --------------------------------------------------------------------------
# Positives: canonical fixture -> kernel quote
# --------------------------------------------------------------------------


class TestNormalizePositive:
    def test_canonical_fixture_maps_to_kernel_quote(self) -> None:
        batch = normalize_aftermath_trade_route_response(
            _fixture_payload(), request=_request(), received_at_ns=RECEIVED_AT_NS
        )
        assert batch.failures == ()
        assert len(batch.entries) == 1
        entry = batch.entries[0]
        quote = entry.normalized
        assert quote.provider_id == "aftermath"
        assert quote.chain == AFTERMATH_CHAIN
        assert quote.direction is QuoteDirection.EXACT_IN
        # 1.5 SUI in / 5.0 USDC out — exact base units, normalized == raw.
        assert quote.input_amount_raw == 1_500_000_000
        assert quote.output_amount_raw == 5_000_000_000
        assert quote.input_amount_normalized == 1_500_000_000
        assert quote.output_amount_normalized == 5_000_000_000
        assert quote.minimum_output_raw is None  # unknown, never zero
        assert quote.taker is None
        assert quote.execution_authority is False
        assert quote.freshness.received_at_ns == RECEIVED_AT_NS
        assert quote.freshness.slot is None
        assert quote.freshness.checkpoint_sequence is None  # never synthesized
        assert entry.evidence_state == AFTERMATH_EVIDENCE_STATE

    def test_correlation_group_and_lineage(self) -> None:
        batch = normalize_aftermath_trade_route_response(
            _fixture_payload(), request=_request(), received_at_ns=RECEIVED_AT_NS
        )
        quote = batch.entries[0].normalized
        assert quote.correlation.correlation_group == AFTERMATH_CORRELATION_GROUP
        # Both path protocols join the lineage alongside the operator.
        assert set(quote.correlation.aggregator_lineage) == {
            "aftermath",
            "cetus",
        }

    def test_pool_identities_are_pool_object_ids(self) -> None:
        batch = normalize_aftermath_trade_route_response(
            _fixture_payload(), request=_request(), received_at_ns=RECEIVED_AT_NS
        )
        quote = batch.entries[0].normalized
        keys = {pool.key for pool in quote.correlation.pool_ids}
        assert keys == {
            ("pool_object_id", CETUS_POOL),
            ("pool_object_id", AFTERMATH_POOL),
        }
        assert all(
            venue.pool is not None
            and venue.pool.kind is PoolIdentityKind.POOL_OBJECT_ID
            for venue in quote.route_venues
        )

    def test_portion_exact_division_fills_share_bps(self) -> None:
        batch = normalize_aftermath_trade_route_response(
            _fixture_payload(), request=_request(), received_at_ns=RECEIVED_AT_NS
        )
        venues = batch.entries[0].normalized.route_venues
        # Single route portion == 1e18 (100%) -> exactly 10000 bps.
        assert all(venue.share_bps == 10_000 for venue in venues)

    def test_fees_carry_unknown_inclusion(self) -> None:
        from src.execution.quote_build_kernel import FeeInclusionState

        batch = normalize_aftermath_trade_route_response(
            _fixture_payload(), request=_request(), received_at_ns=RECEIVED_AT_NS
        )
        fees = batch.entries[0].normalized.fees
        kinds = {fee.kind for fee in fees}
        assert "fee_breakdown_0" in kinds
        assert "net_trade_fee" in kinds
        assert all(fee.inclusion_state is FeeInclusionState.UNKNOWN for fee in fees)
        breakdown = next(fee for fee in fees if fee.kind == "fee_breakdown_0")
        assert breakdown.amount_raw == 1_500_000

    def test_exact_in_and_exact_out_decimals(self) -> None:
        # Positive coverage by tenths: 2.5 SUI = 2_500_000_000 MIST.
        payload = _fixture_payload()
        payload["coinIn"]["amount"] = "2500000000n"
        payload["routes"][0]["coinIn"]["amount"] = "2500000000n"
        batch = normalize_aftermath_trade_route_response(
            payload,
            request=_request(amount_raw=2_500_000_000),
            received_at_ns=RECEIVED_AT_NS,
        )
        assert batch.entries[0].normalized.input_amount_raw == 2_500_000_000

    def test_integer_form_amount_accepted(self) -> None:
        payload = _fixture_payload()
        payload["coinIn"]["amount"] = 1_500_000_000  # JSON integer form
        payload["routes"][0]["coinIn"]["amount"] = 1_500_000_000
        batch = normalize_aftermath_trade_route_response(
            payload, request=_request(), received_at_ns=RECEIVED_AT_NS
        )
        assert batch.entries[0].normalized.input_amount_raw == 1_500_000_000


# --------------------------------------------------------------------------
# Negatives: typed refusals (never guessed)
# --------------------------------------------------------------------------


class TestNormalizeNegative:
    def test_error_envelope_error_string(self) -> None:
        batch = normalize_aftermath_trade_route_response(
            {"error": "route not found"},
            request=_request(),
            received_at_ns=RECEIVED_AT_NS,
        )
        assert batch.entries == ()
        assert batch.failures[0].code is AftermathFailureCode.API_ERROR_ENVELOPE

    def test_error_envelope_error_code_message(self) -> None:
        batch = normalize_aftermath_trade_route_response(
            {"error_code": 2019, "message": "bad request"},
            request=_request(),
            received_at_ns=RECEIVED_AT_NS,
        )
        assert batch.failures[0].code is AftermathFailureCode.API_ERROR_ENVELOPE
        assert "2019" in batch.failures[0].detail

    def test_error_envelope_string_body(self) -> None:
        batch = normalize_aftermath_trade_route_response(
            "Error 2020: upstream unavailable",
            request=_request(),
            received_at_ns=RECEIVED_AT_NS,
        )
        assert batch.failures[0].code is AftermathFailureCode.API_ERROR_ENVELOPE

    def test_error_envelope_null_body(self) -> None:
        batch = normalize_aftermath_trade_route_response(
            None, request=_request(), received_at_ns=RECEIVED_AT_NS
        )
        assert batch.failures[0].code is AftermathFailureCode.API_ERROR_ENVELOPE

    def test_empty_routes_is_typed_business_rejection(self) -> None:
        payload = _fixture_payload()
        payload["routes"] = []
        batch = normalize_aftermath_trade_route_response(
            payload, request=_request(), received_at_ns=RECEIVED_AT_NS
        )
        assert batch.failures[0].code is AftermathFailureCode.EMPTY_ROUTES
        assert (
            batch.failures[0].kernel_failure_class
            is ProviderReadFailureClass.HTTP_ERROR
        )

    def test_amount_drift_refused(self) -> None:
        payload = _fixture_payload()
        payload["coinIn"]["amount"] = "999999999n"
        payload["routes"][0]["coinIn"]["amount"] = "999999999n"
        batch = normalize_aftermath_trade_route_response(
            payload, request=_request(), received_at_ns=RECEIVED_AT_NS
        )
        assert batch.failures[0].code is AftermathFailureCode.COMPARABILITY_DRIFT

    def test_coin_type_drift_refused(self) -> None:
        payload = _fixture_payload()
        payload["coinOut"]["type"] = "0x2::sui::SUI"
        batch = normalize_aftermath_trade_route_response(
            payload, request=_request(), received_at_ns=RECEIVED_AT_NS
        )
        assert batch.failures[0].code is AftermathFailureCode.COMPARABILITY_DRIFT

    def test_float_amount_is_invalid_schema(self) -> None:
        payload = _fixture_payload()
        payload["coinIn"]["amount"] = 1.5e9
        batch = normalize_aftermath_trade_route_response(
            payload, request=_request(), received_at_ns=RECEIVED_AT_NS
        )
        assert batch.failures[0].code is AftermathFailureCode.INVALID_SCHEMA

    def test_nonzero_sor_trade_fee_refused(self) -> None:
        payload = _fixture_payload()
        payload["coinOut"]["tradeFee"] = "42n"
        batch = normalize_aftermath_trade_route_response(
            payload, request=_request(), received_at_ns=RECEIVED_AT_NS
        )
        assert batch.failures[0].code is AftermathFailureCode.COMPARABILITY_DRIFT
        assert "SOR fee model" in batch.failures[0].detail

    def test_bad_pool_id_refused(self) -> None:
        payload = _fixture_payload()
        payload["routes"][0]["paths"][0]["poolId"] = "not-an-object-id"
        batch = normalize_aftermath_trade_route_response(
            payload, request=_request(), received_at_ns=RECEIVED_AT_NS
        )
        assert batch.failures[0].code is AftermathFailureCode.INVALID_SCHEMA

    def test_non_mapping_payload_refused(self) -> None:
        batch = normalize_aftermath_trade_route_response(
            [1, 2, 3], request=_request(), received_at_ns=RECEIVED_AT_NS
        )
        assert batch.failures[0].code is AftermathFailureCode.INVALID_SCHEMA

    def test_kernel_mapping_of_transport_exception(self) -> None:
        def exploding_transport(_: AftermathSwapRouteRequest) -> dict[str, object]:
            raise RuntimeError("connection reset")

        batch = normalize_via_transport(
            exploding_transport, _request(), received_at_ns=RECEIVED_AT_NS
        )
        assert batch.entries == ()
        assert batch.failures[0].code is AftermathFailureCode.TRANSPORT
        assert (
            batch.failures[0].kernel_failure_class is ProviderReadFailureClass.TRANSPORT
        )

    def test_http_status_mapping(self) -> None:
        assert (
            map_http_status_failure(429, "slow down").kernel_failure_class
            is ProviderReadFailureClass.RATE_LIMITED
        )
        assert (
            map_http_status_failure(401, "nope").kernel_failure_class
            is ProviderReadFailureClass.UNAUTHORIZED
        )
        assert (
            map_http_status_failure(502, "upstream").kernel_failure_class
            is ProviderReadFailureClass.HTTP_ERROR
        )


# --------------------------------------------------------------------------
# Race seam + dedup (kernel contract, overlap notes)
# --------------------------------------------------------------------------


def _aftermath_quote() -> NormalizedProviderQuote:
    batch = normalize_aftermath_trade_route_response(
        _fixture_payload(), request=_request(), received_at_ns=RECEIVED_AT_NS
    )
    return batch.entries[0].normalized


def _direct_cetus_quote() -> NormalizedProviderQuote:
    """A direct Cetus capture sharing the Cetus pool with the SOR route."""
    return NormalizedProviderQuote(
        provider_id="cetus",
        provider_generation="cetus.direct.fixture",
        chain="sui",
        direction=QuoteDirection.EXACT_IN,
        input_representation_id="sui:mainnet:sui",
        output_representation_id="sui:mainnet:usdc",
        input_amount_raw=1_500_000_000,
        output_amount_raw=4_900_000_000,
        input_amount_normalized=1_500_000_000,
        output_amount_normalized=4_900_000_000,
        correlation=ProviderCorrelation(
            correlation_group="cetus-direct",
            aggregator_lineage=("cetus",),
            pool_ids=(PoolIdentity(PoolIdentityKind.POOL_OBJECT_ID, CETUS_POOL),),
        ),
        freshness=QuoteFreshness(received_at_ns=RECEIVED_AT_NS),
        raw_response_hash="a" * 64,
        request_fingerprint="cetus-direct-fixture",
    )


class TestRaceAndDedup:
    def test_race_request_comparable_and_winner_preserved(self) -> None:
        batch = normalize_aftermath_trade_route_response(
            _fixture_payload(), request=_request(), received_at_ns=RECEIVED_AT_NS
        )
        quotes, failures = kernel_race_inputs(batch)
        assert failures == ()
        race = QuoteRaceResult.build(
            request=build_kernel_race_request(_request()),
            quotes=list(quotes),
            now_ns=RECEIVED_AT_NS + 1,
        )
        assert race.winner is not None
        assert race.winner.provider_id == "aftermath"
        assert race.entries[0].verdict is RaceVerdict.WON

    def test_aftermath_loses_to_better_cetus_output_but_stale_check(self) -> None:
        aftermath = _aftermath_quote()
        cetus = dataclasses.replace(
            _direct_cetus_quote(), output_amount_raw=6_000_000_000
        )
        race = QuoteRaceResult.build(
            request=build_kernel_race_request(_request()),
            quotes=[aftermath, cetus],
            now_ns=RECEIVED_AT_NS + 1,
        )
        assert race.winner is not None
        assert race.winner.provider_id == "cetus"
        loser = next(
            entry for entry in race.entries if entry.quote.provider_id == "aftermath"
        )
        assert QuoteLossReason.CORRELATED_OBSERVATION in loser.loss_reasons

    def test_aftermath_correlates_with_direct_cetus_via_lineage_and_pool(self) -> None:
        verdict = PoolIdentityDeduplicator.correlation_verdict(
            _aftermath_quote(), _direct_cetus_quote()
        )
        assert verdict is IndependenceVerdict.CORRELATED

    def test_two_aftermath_quotes_always_correlated(self) -> None:
        verdict = PoolIdentityDeduplicator.correlation_verdict(
            _aftermath_quote(), _aftermath_quote()
        )
        assert verdict is IndependenceVerdict.CORRELATED

    def test_unknown_pool_evidence_never_independent(self) -> None:
        bare = NormalizedProviderQuote(
            provider_id="other-aggregator",
            provider_generation="x",
            chain="sui",
            direction=QuoteDirection.EXACT_IN,
            input_representation_id="sui:mainnet:sui",
            output_representation_id="sui:mainnet:usdc",
            input_amount_raw=1_500_000_000,
            output_amount_raw=4_800_000_000,
            input_amount_normalized=1_500_000_000,
            output_amount_normalized=4_800_000_000,
            correlation=ProviderCorrelation(
                correlation_group="other", pool_ids=()  # UNKNOWN pools
            ),
            freshness=QuoteFreshness(received_at_ns=RECEIVED_AT_NS),
            raw_response_hash="b" * 64,
            request_fingerprint="other-fixture",
        )
        assert (
            PoolIdentityDeduplicator.correlation_verdict(_aftermath_quote(), bare)
            is IndependenceVerdict.UNKNOWN
        )

    def test_no_extrapolation_from_aftermath_quote(self) -> None:
        quote = _aftermath_quote()
        assert (
            refuse_amount_extrapolation(quote, 1_500_000_000, purpose="sizing")
            == 1_500_000_000
        )
        with pytest.raises(QuoteExtrapolationError):
            refuse_amount_extrapolation(quote, 1_500_000_001, purpose="sizing")


# --------------------------------------------------------------------------
# Regression: providers.py -> providers/ package conversion
# --------------------------------------------------------------------------


class TestPackageConversionRegression:
    def test_gpr03_public_import_surface_preserved(self) -> None:
        # The 210-line GPR-03 owner moved verbatim; every public name it
        # exported stays importable from the same module path.
        for name in (
            "LIVE_SUI_PROVIDERS_BLOCKED",
            "PROVIDER_TRANSPORTS",
            "CheckpointProviderBinding",
            "CheckpointConsistencyEvidence",
            "OfflinePairVerdict",
            "LiveBindingVerdict",
            "require_independent_pair",
            "verify_offline_pair",
            "live_binding_verdict",
        ):
            assert hasattr(gpr_providers_package, name), name

    def test_gpr03_live_binding_still_blocked(self) -> None:
        assert (
            gpr_providers_package.LIVE_SUI_PROVIDERS_BLOCKED
            == "LIVE_SUI_PROVIDERS_NOT_AUTHORIZED"
        )
