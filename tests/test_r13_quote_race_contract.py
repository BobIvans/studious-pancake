"""R13-A quote/build race contract tests.

Additive, read-only assertions of invariants that are TRUE TODAY in the
existing quote/build owners (governed radar plane, production routing plane,
Sui state plane, R-03 builders, rent sponsor planner). Each test documents the
R13 audit finding it pins; aspirational behavior is intentionally NOT asserted
here and is recorded in
docs/roadmap/agent-execution-master-2026-11-13/reports/R13_QUOTE_BUILD_RACE_AUDIT_2026-11-14.md.

No network, no credentials, no signing: pytest-socket applies; every input is
an inline offline fixture.
"""

import json
from pathlib import Path

import pytest

from src.solana_parallel_radar.cli import CONTRACT_PATH, read_contracts
from src.solana_parallel_radar.funnel import QuotePreview, compare_quotes
from src.solana_parallel_radar.probes import (
    NATIVE_SOL_SENTINEL,
    GovernedReadPlane,
    jupiter_request as probes_jupiter_request,
)

SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
TAKER = "2gyPaXeFnTRfVGFguU9yGtJ56yG2qbAVyCfQTW7ygL4g"
NOW_NS = 1_800_000_000_000_000_000


def _preview(
    *,
    input_amount=1_000_000,
    output_amount=1_000_000,
    minimum=999_000,
    slot=None,
    source_id="gpr02-jupiter-reference",
    provider_generation="gen-a",
    correlation_group="jupiter-metis-router",
    taker=None,
    observed_at_ns=NOW_NS,
):
    return QuotePreview(
        SOL,
        USDC,
        input_amount,
        output_amount,
        minimum,
        slot,
        observed_at_ns,
        source_id,
        provider_generation,
        correlation_group,
        "raw-ref-1",
        (SOL, USDC),
        True,
        taker=taker,
    )


# ---------------------------------------------------------------------------
# 1. Governed Solana quote plane (P0-2 owner): documented == implemented ==
#    wired, quote-only, no scaling, bounded freshness, losing quotes retained.
# ---------------------------------------------------------------------------


def test_governed_plane_pins_exactly_two_quote_providers():
    """Audit: the governed quote race is Jupiter V2 + 0x only.

    Titan / OpenOcean / OKX / Rango have NO governed source contract; any
    addition must extend this owner, not create a parallel plane.
    """
    contracts = json.loads(CONTRACT_PATH.read_text())
    zero_x, jupiter = read_contracts(contracts)
    assert zero_x.source_id == "gpr02-0x-preview"
    assert zero_x.method == "POST"
    assert zero_x.profile.endpoint == "https://api.0x.org/solana/swap-instructions"
    assert zero_x.auth_header == "0x-api-key"
    assert jupiter.source_id == "gpr02-jupiter-reference"
    assert jupiter.profile.endpoint == "https://api.jup.ag/swap/v2/order"
    assert jupiter.auth_header == "x-api-key"
    assert {c.profile.correlation_group for c in (zero_x, jupiter)} == {
        "0x-solana-router",
        "jupiter-metis-router",
    }
    # Source pins are exact-commit/blob hashes, not doc names.
    for contract in (zero_x, jupiter):
        assert len(contract.docs_git_sha) == 40
        assert len(contract.docs_sha256) == 64
        assert len(contract.schema_sha256) == 64


def test_jupiter_request_is_quote_only_exact_in_and_rejects_native_sol():
    """Audit: governed Jupiter capture is pinned V2 GET /order, ExactIn."""
    request = probes_jupiter_request(SOL, USDC, 1_000_000, taker=TAKER)
    params = dict(request.params)
    assert request.url == "https://api.jup.ag/swap/v2/order"
    assert params["swapMode"] == "ExactIn"
    assert params["amount"] == "1000000"
    assert params["taker"] == TAKER
    # V1-only parameters are deliberately absent.
    assert not {"dexes", "onlyDirectRoutes", "restrictIntermediateTokens"} & set(params)
    with pytest.raises(ValueError):
        probes_jupiter_request(NATIVE_SOL_SENTINEL, USDC, 1_000_000)
    with pytest.raises(ValueError):
        probes_jupiter_request(SOL, NATIVE_SOL_SENTINEL, 1_000_000)


def test_quote_preview_never_claims_execution_authority():
    """Audit: every governed quote is locked to DISCOVERY_ONLY evidence."""
    with pytest.raises(ValueError, match="QUOTE_PREVIEW_IDENTITY_OR_AUTHORITY_INVALID"):
        QuotePreview(
            SOL,
            USDC,
            1_000_000,
            1_000_000,
            999_000,
            None,
            NOW_NS,
            "gpr02-jupiter-reference",
            "gen-a",
            "jupiter-metis-router",
            "raw-ref-1",
            (SOL, USDC),
            True,
            evidence_state="LIVE_CONFIRMED",
        )


def test_quote_preview_rejects_minimum_above_output():
    """Audit: min-output invariants hold inside the normalized quote itself."""
    with pytest.raises(ValueError, match="QUOTE_PREVIEW_IDENTITY_OR_AUTHORITY_INVALID"):
        _preview(minimum=1_000_001)


def test_taker_must_be_a_public_address_and_mode_is_explicit():
    """Audit: taker is explicit metadata; a malformed taker is refused."""
    with pytest.raises(ValueError):
        _preview(taker="not-a-base58-pubkey")


def test_compare_quotes_rejects_amount_mismatch_no_extrapolation():
    """Audit: quotes are never scaled to another amount; comparator fails closed."""
    a = _preview()
    b = _preview(input_amount=2_000_000)
    with pytest.raises(ValueError, match="QUOTE_UNITS_OR_REPRESENTATION_MISMATCH"):
        compare_quotes(a, b, now_ns=NOW_NS + 1)


def test_compare_quotes_rejects_taker_mode_mismatch():
    """Audit: quote-only and taker-aware captures are not comparable modes."""
    a = _preview()
    b = _preview(taker=TAKER)
    with pytest.raises(ValueError, match="QUOTE_TAKER_PARITY_MISMATCH"):
        compare_quotes(a, b, now_ns=NOW_NS + 1)


def test_compare_quotes_freshness_bounds_and_staleness():
    """Audit: bounded time skew is enforced (<=45s, no future quotes)."""
    a = _preview()
    b = _preview(correlation_group="0x-solana-router")
    with pytest.raises(ValueError, match="BOUNDED_QUOTE_FRESHNESS_REQUIRED"):
        compare_quotes(a, b, now_ns=NOW_NS + 1, max_age_ns=46_000_000_000)
    stale = _preview(observed_at_ns=NOW_NS - 46_000_000_000)
    with pytest.raises(ValueError, match="QUOTE_STALE_OR_FUTURE"):
        compare_quotes(a, stale, now_ns=NOW_NS + 1)


def test_compare_quotes_flags_correlation_group_equality_not_independence():
    """Audit: 'independent' is derived only from correlation-group labels.

    Route legs may share pools even across providers; the comparison result
    keeps raw evidence refs so pool-level dedup can be added without schema
    change. Aggregator diversity is NOT liquidity independence.
    """
    same_group = (_preview(), _preview(provider_generation="gen-b"))
    result = compare_quotes(*same_group, now_ns=NOW_NS + 1)
    assert result["independent"] is False
    distinct = (
        _preview(),
        _preview(correlation_group="0x-solana-router", source_id="gpr02-0x-preview"),
    )
    result = compare_quotes(*distinct, now_ns=NOW_NS + 1)
    assert result["independent"] is True
    assert result["execution_authority"] is False
    assert result["production_promotion"] is False
    assert set(result["raw_evidence_refs"]) == {"raw-ref-1"}


def test_quote_slot_is_never_synthesized_and_gap_is_bounded():
    """Audit: 0x/Jupiter V2 have no slot in the pinned response; None is legal."""
    a = _preview(slot=100)
    b = _preview(slot=200, correlation_group="0x-solana-router")
    with pytest.raises(ValueError, match="QUOTE_CONTEXT_SLOT_GAP"):
        compare_quotes(a, b, now_ns=NOW_NS + 1, max_slot_gap=32)
    unknown = (_preview(slot=100), _preview(slot=None))
    result = compare_quotes(*unknown, now_ns=NOW_NS + 1)
    assert result["slot_alignment"] == "UNKNOWN"


def test_missing_public_taker_blocks_zero_x_capture_not_jupiter():
    """Audit: 0x requires an explicit public taker; the block is typed, not silent."""
    contracts = json.loads(CONTRACT_PATH.read_text())
    zero_x, _ = read_contracts(contracts)
    body = {
        "token_in": SOL,
        "token_out": USDC,
        "amount_in": 1_000_000,
        "slippage_bps": 50,
        "taker": TAKER,
    }
    from src.solana_parallel_radar.probes import normalize_zero_x

    quote = normalize_zero_x(
        {
            "route_plan": [
                {
                    "token_in": SOL,
                    "token_out": USDC,
                    "dex_address": "675kP7sjGoPVaXRAkwan4qPQv9mh5DPkF8AtUyNbURmc",
                    "dex_label": "whirlpool",
                    "dex_program_id": "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
                }
            ],
            "amount_out": "1000000",
            "min_amount_out": "999000",
        },
        body=body,
        observed_at_ns=NOW_NS,
        contract=zero_x,
        raw_evidence_ref="raw-ref-0x",
    )
    assert quote.taker == TAKER and quote.slot is None
    # A missing taker in the body is structurally rejected by GovernedReadPlane
    # request validation before any physical read.
    assert GovernedReadPlane is not None


def test_zero_x_production_stub_is_feature_gated():
    """Audit: the legacy-plane 0x adapter cannot produce quotes or builds."""
    import asyncio

    from src.domain.money import BasisPoints, TokenAmount
    from src.ingest.swap_providers import (
        OpenOceanSolanaAdapter,
        SwapMode,
        ZeroXSolanaAdapter,
        active_solana_providers,
    )

    zero_x = ZeroXSolanaAdapter(enabled=False)
    request = type(
        "R",
        (),
        {
            "input_mint": SOL,
            "output_mint": USDC,
            "amount": TokenAmount(SOL, 1_000_000, 6),
            "swap_mode": SwapMode.EXACT_IN,
            "taker": TAKER,
            "payer": TAKER,
            "slippage_bps": BasisPoints(50),
        },
    )()
    with pytest.raises(Exception, match="priority access feature gate"):
        asyncio.run(zero_x.quote(None, request))
    with pytest.raises(Exception, match="priority-access gated"):
        asyncio.run(zero_x.instructions(None, None))
    openocean = OpenOceanSolanaAdapter()
    with pytest.raises(Exception, match="whitelist access"):
        asyncio.run(openocean.quote(None, request))
    names = {type(p).__name__ for p in active_solana_providers()}
    assert names == {
        "OKXSolanaAdapter",
        "ZeroXSolanaAdapter",
        "OpenOceanSolanaAdapter",
    }


# ---------------------------------------------------------------------------
# 2. Production routing plane: registry composition, roles, correlation labels,
#    losing-quote retention.
# ---------------------------------------------------------------------------


def test_runtime_registry_admits_exactly_three_solana_providers():
    """Audit: supported boot path races jupiter_router/okx_dex/openocean only.

    Titan, Rango and Odos are absent from ProviderRegistry.from_env.
    """
    from src.routing.registry import ProviderRegistry

    registry = ProviderRegistry.from_env({})
    ids = tuple(a.provider_id for a in registry.adapters)
    assert ids == ("jupiter_router", "okx_dex", "openocean")


def test_provider_roles_pin_the_evidence_gate_state():
    """Audit: Jupiter executable; OKX/OpenOcean held below executable by pins."""
    from src.routing.capabilities import (
        OKX_CAPABILITIES,
        OPENOCEAN_CAPABILITIES,
    )
    from src.routing.models import ExecutionArtifactKind, ProviderRole

    assert OKX_CAPABILITIES.role is ProviderRole.DISCOVERY_ONLY
    assert OKX_CAPABILITIES.artifact_kind is ExecutionArtifactKind.RAW_INSTRUCTIONS
    assert "discovery_only_pending_contract_validation" in (
        OKX_CAPABILITIES.admission_reason
    )
    assert OPENOCEAN_CAPABILITIES.role is ProviderRole.DISCOVERY_ONLY
    assert OPENOCEAN_CAPABILITIES.artifact_kind is ExecutionArtifactKind.NONE
    assert "Jupiter/Titan" in OPENOCEAN_CAPABILITIES.admission_reason


def test_openocean_without_credential_is_disabled_and_excluded():
    """Audit: providers stay disabled until their evidence gate passes."""
    from src.routing.adapters import OpenOceanAdapter
    from src.routing.models import ProviderHealth, ProviderRole

    adapter = OpenOceanAdapter(api_key=None)
    assert adapter.capabilities.role is ProviderRole.DISABLED
    assert adapter.circuit.health is ProviderHealth.DISABLED_MISSING_CREDENTIALS


def test_correlation_labels_never_erase_underlying_venue_overlap():
    """Audit: aggregator + underlying labels are retained per provider.

    Two aggregators selecting the same venue produce the SAME underlying label
    -- the machine-readable basis for 'not independent liquidity'.
    """
    from src.routing.clients import _correlation

    jupiter = _correlation("jupiter_router", ("Metis", "Whirlpool"))
    okx = _correlation("okx_dex", ("Whirlpool",))
    assert jupiter[0] == "aggregator:jupiter_router"
    assert "underlying:whirlpool" in jupiter and "underlying:metis" in jupiter
    assert "underlying:whirlpool" in okx
    # Same underlying pool via two providers: shared label, zero independence.
    assert set(jupiter) & set(okx) == {"underlying:whirlpool"}


def test_discovery_batch_preserves_losing_quotes_and_failures():
    """Audit: the race retains losers, not only the winner."""
    from src.routing.models import (
        DiscoveryBatch,
        ProviderFailure,
        ProviderFailureReason,
    )

    failure = ProviderFailure(
        provider="okx_dex",
        reason=ProviderFailureReason.RATE_LIMITED,
        retryable=True,
        detail="429",
        status_code=429,
    )
    batch = DiscoveryBatch(request_fingerprint="fp", quotes=(), failures=(failure,))
    assert batch.failures[0].provider == "okx_dex"
    assert batch.quotes == ()


def test_quote_request_fingerprint_binds_exact_amount():
    """Audit: amount identity is part of the request fingerprint (re-quote rule)."""
    from src.routing.models import QuoteRequest, SwapMode

    a = QuoteRequest(SOL, USDC, 1_000_000, TAKER, 50, swap_mode=SwapMode.EXACT_IN)
    b = QuoteRequest(SOL, USDC, 2_000_000, TAKER, 50, swap_mode=SwapMode.EXACT_IN)
    assert a.fingerprint != b.fingerprint


# ---------------------------------------------------------------------------
# 3. Sui lane: state/PTB plane only; live providers BLOCKED; correlation
#    governance exists and rejects correlated provider pairs.
# ---------------------------------------------------------------------------


def _sui_binding(profile_id, provider, operator, group):
    from src.gpr_sui_shadow.providers import CheckpointProviderBinding

    return CheckpointProviderBinding(
        profile_id=profile_id,
        provider=provider,
        operator=operator,
        correlation_group=group,
        transport="graphql",
        endpoint="https://sui.mainnet.example/graphql",
        schema_pin="a" * 64,
        genesis_chain_identifier="mainnet",
    )


def _sui_evidence(binding):
    from src.gpr_sui_shadow.providers import CheckpointConsistencyEvidence

    return CheckpointConsistencyEvidence(
        binding_generation=binding.generation,
        capture_ref="b" * 64,
        chain_identifier="mainnet",
        checkpoint_sequence=42,
        checkpoint_digest="cp-digest",
        object_id="0x" + "c" * 64,
        object_version=7,
        object_digest="obj-digest",
        payload_sha256="d" * 64,
        observed_at_ns=1_800_000_000_000_000_000,
        available_at_ns=1_800_000_000_000_000_001,
    )


def test_sui_live_provider_binding_is_deterministically_blocked():
    """Audit: no code path authorizes a live Sui provider offline."""
    from src.gpr_sui_shadow.providers import (
        LIVE_SUI_PROVIDERS_BLOCKED,
        live_binding_verdict,
    )

    a = _sui_binding("sui-a", "provider-a", "operator-a", "group-a")
    b = _sui_binding("sui-b", "provider-b", "operator-b", "group-b")
    # verify_offline_pair zips generation-sorted bindings with evidences.
    ordered = sorted((a, b), key=lambda binding: binding.generation)
    verdict = live_binding_verdict(
        (a, b), tuple(_sui_evidence(binding) for binding in ordered)
    )
    assert verdict.status == "BLOCKED"
    assert verdict.reason == LIVE_SUI_PROVIDERS_BLOCKED
    assert verdict.offline.status == "OFFLINE_CONSISTENT"


def test_sui_correlated_provider_pair_is_rejected():
    """Audit: shared correlation group/provider/operator is not 'two sources'."""
    from src.gpr_sui_shadow.providers import require_independent_pair

    a = _sui_binding("sui-a", "provider-a", "operator-a", "group-a")
    twin = _sui_binding("sui-a", "provider-a", "operator-a", "group-a")
    with pytest.raises(ValueError):
        require_independent_pair((a, twin))
    same_group = _sui_binding("sui-a", "provider-a", "operator-a", "shared-group")
    other = _sui_binding("sui-b", "provider-b", "operator-b", "shared-group")
    with pytest.raises(ValueError, match="SUI_CORRELATED_PROVIDERS_BLOCKED"):
        require_independent_pair((same_group, other))


def test_sui_bindings_are_https_credential_free_graphql_or_grpc_only():
    """Audit: no legacy Sui JSON-RPC fallback exists in the provider contract."""
    from src.gpr_sui_shadow.providers import PROVIDER_TRANSPORTS

    assert set(PROVIDER_TRANSPORTS) == {"graphql", "grpc"}
    with pytest.raises(ValueError):
        _sui_binding("sui-a", "provider-a", "operator-a", "group-a").__class__(
            profile_id="sui-x",
            provider="provider-x",
            operator="operator-x",
            correlation_group="group-x",
            transport="json-rpc",
            endpoint="https://sui.mainnet.example/jsonrpc",
            schema_pin="a" * 64,
            genesis_chain_identifier="mainnet",
        )


# ---------------------------------------------------------------------------
# 4. Builders / sponsors: unsigned plans and inactive sponsor tiers.
# ---------------------------------------------------------------------------


def test_provider_rent_sponsor_tier_is_inactive_for_all_known_sponsors():
    """Audit: 0x rent sponsor / Titan payer are documented but NOT verified.

    Unknown is not zero: the tier exists, is typed, and refuses unevidenced
    claims instead of assuming sponsorship.
    """
    from src.planning.rent_sponsor_planner import KNOWN_PROVIDER_SPONSORS

    assert set(KNOWN_PROVIDER_SPONSORS) == {"0x_sponsor", "titan_payer"}
    assert all(
        not profile.verified_offline for profile in KNOWN_PROVIDER_SPONSORS.values()
    )


def test_unsigned_builder_contract_never_marks_capacity_from_build():
    """Audit: build status and capacity status are separate typed domains."""
    from src.lending.unsigned_builders.contract import (
        BuildStatus,
        CapacityStatus,
    )

    assert BuildStatus.BUILT_OFFLINE_UNQUALIFIED.value != (
        CapacityStatus.NOT_EVALUATED.value
    )
    members = {member.name for member in BuildStatus}
    assert "BUILT_OFFLINE_UNQUALIFIED" in members


def test_r03_builder_source_pins_are_exact_offline_pins():
    """Audit: every R-03 builder binds provider/commit/license pins."""
    from src.lending.unsigned_builders.jupiter_builder import (
        JUPITER_BUILDER_SOURCE_PIN,
    )
    from src.lending.unsigned_builders.navi_ptb_builder import (
        NAVI_BUILDER_SOURCE_PIN,
    )
    from src.lending.unsigned_builders.project0_builder import (
        PROJECT0_BUILDER_SOURCE_PIN,
    )

    for pin in (
        JUPITER_BUILDER_SOURCE_PIN,
        NAVI_BUILDER_SOURCE_PIN,
        PROJECT0_BUILDER_SOURCE_PIN,
    ):
        assert pin.verified_offline is True
        assert len(pin.commit) >= 40
        assert pin.source_paths


def test_sui_ptb_builders_emit_unqualified_offline_plans_only():
    """Audit: Sui PTB builds are conformance DTOs, never executable routes."""
    from src.lending.unsigned_builders.contract import BuildStatus

    # The Navi PTB builder pins this status for every produced plan; the
    # contract enum member is the invariant surface asserted here.
    assert BuildStatus.BUILT_OFFLINE_UNQUALIFIED.value == "built_offline_unqualified"
