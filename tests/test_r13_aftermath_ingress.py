"""R13 Aftermath offline-to-governed quote ingress tests (offline, zero network).

Pins the fail-closed behavior of ``src/gpr_sui_shadow/providers/
aftermath_ingress.py`` (PR #667 vertical slice) against the frozen kernel
contract (``src/execution/quote_build_kernel.py``) and the existing offline
normalizer (``src/gpr_sui_shadow/providers/aftermath.py``, PR #661):

- fail-closed stance: no transport ships with the ingress; ``None`` is a
  typed DISABLED refusal and ANY transport attempt is a typed
  ``LIVE_READ_NOT_AUTHORIZED`` refusal carrying both existing gate reasons
  (``AFTERMATH_LIVE_CAPTURE_NOT_AUTHORIZED`` +
  ``LIVE_SUI_PROVIDERS_NOT_AUTHORIZED``); no environment variable or
  credential can flip the gate;
- offline positives: retained fixture -> adapter batch -> kernel race with
  exact full Move CoinTypes, integer base-unit amounts, route legs, canonical
  pool object ids, fee components, provider/correlation provenance, request
  fingerprint and raw response hash — nothing redefined, nothing scaled;
- state evidence binding: ``QuoteFreshness.checkpoint_sequence`` is attached
  ONLY from validated ``AftermathStateEvidence``; without it the checkpoint
  stays UNKNOWN (never zero) and ``AFTERMATH_STATE_EVIDENCE_REQUIRED`` is
  recorded; malformed evidence is a typed refusal;
- race/dedup reuse: competing quotes are ranked by the frozen kernel and the
  R13 ``PoolIdentityDeduplicator`` correlation rules run there and nowhere
  else (shared pool/lineage => CORRELATED; disjoint evidence => INDEPENDENT);
- status ladder: ``provider_lane_status`` is deterministic and typed;
- replay: same inputs produce identical records and identical race
  fingerprints; payload hashes do not drift with freshness;
- regression: the ingress is not boot-exported from the GPR-03 package
  surface and imports nothing from the N09-owned NAVI/multichain owners.

Zero network: no transport ships with the ingress; every transport in these
tests is an injected pure callable or ``None``. pytest-socket applies in CI.
Nothing signs, sends, borrows, or enables a provider; NAVI qualification
(DAG N09) is untouched.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

from src.execution.quote_build_kernel import (
    FeeInclusionState,
    IndependenceVerdict,
    NormalizedProviderQuote,
    PoolIdentity,
    PoolIdentityDeduplicator,
    PoolIdentityKind,
    ProviderCorrelation,
    QuoteDirection,
    QuoteFreshness,
    QuoteLossReason,
    RaceVerdict,
)
from src.gpr_sui_shadow.providers import LIVE_SUI_PROVIDERS_BLOCKED
from src.gpr_sui_shadow.providers import aftermath as am
from src.gpr_sui_shadow.providers.aftermath import (
    AFTERMATH_EVIDENCE_STATE,
    AFTERMATH_LIVE_CAPTURE_BLOCKED,
    AftermathSwapRouteRequest,
    normalize_aftermath_trade_route_response,
)
from src.gpr_sui_shadow.providers.aftermath_ingress import (
    AFTERMATH_INGRESS_EVIDENCE_STATE,
    AFTERMATH_INGRESS_VERSION,
    AFTERMATH_STATE_EVIDENCE_ATTACHED_FROM_INDEPENDENT_CAPTURE,
    AFTERMATH_STATE_EVIDENCE_REQUIRED,
    AFTERMATH_STATE_EVIDENCE_UNATTACHED,
    AFTERMATH_SUI_PROVIDER_QUORUM_REQUIRED,
    AftermathIngressError,
    AftermathIngressFailureCode,
    AftermathStateEvidence,
    ingest_offline_payload,
    ingest_via_transport,
    live_read_gate_verdict,
    provider_lane_status,
)

import src.gpr_sui_shadow as gpr03

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures" / "r13_aftermath_adapter"
RECEIVED_AT_NS = 1_736_000_000_000_000_000

SUI_TYPE = "0x2::sui::SUI"
USDC_TYPE = (
    "0xdba34672e30cb065b1f93e3ab55318768fd6fef66c15942c9f7cb846e2f900e7" "::usdc::USDC"
)
CETUS_POOL = "0xfcc774493db2c45c79f688f88d28023a3e7d98e4ee9f48bbf5c7990f651577ae"
AFTERMATH_POOL = "0x28e499dff5e864a2eafe476269a4f5035f1c16f338da7be18b103499abf271ce"
INDEPENDENT_POOL = "0x" + "cd" * 32


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


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _state_evidence(**overrides: object) -> AftermathStateEvidence:
    params: dict[str, object] = {
        "checkpoint_sequence": 12_345,
        "checkpoint_digest": _sha("checkpoint-digest"),
        "capture_provider": "sui-state-quorum",
        "capture_correlation_group": "sui-checkpoint-quorum",
        "capture_request_hash": _sha("state-request"),
        "capture_response_hash": _sha("state-response"),
        "captured_at_ns": RECEIVED_AT_NS - 1_000_000,
        "source_generation": "gpr03.offline-pair.v1",
        "evidence_ref": _sha("offline-pair-verdict"),
    }
    params.update(overrides)
    return AftermathStateEvidence(**params)  # type: ignore[arg-type]


def _competing_quote(
    *,
    provider_id: str,
    correlation_group: str,
    lineage: tuple[str, ...],
    pool_id: str,
    output_amount_raw: int,
) -> NormalizedProviderQuote:
    return NormalizedProviderQuote(
        provider_id=provider_id,
        provider_generation="competing.fixture.v1",
        chain="sui",
        direction=QuoteDirection.EXACT_IN,
        input_representation_id="sui:mainnet:sui",
        output_representation_id="sui:mainnet:usdc",
        input_amount_raw=1_500_000_000,
        output_amount_raw=output_amount_raw,
        input_amount_normalized=1_500_000_000,
        output_amount_normalized=output_amount_raw,
        correlation=ProviderCorrelation(
            correlation_group=correlation_group,
            aggregator_lineage=lineage,
            pool_ids=(PoolIdentity(PoolIdentityKind.POOL_OBJECT_ID, pool_id),),
        ),
        freshness=QuoteFreshness(received_at_ns=RECEIVED_AT_NS),
        raw_response_hash=_sha(provider_id),
        request_fingerprint=f"{provider_id}-fixture",
    )


def _correlated_cetus_quote(
    output_amount_raw: int = 6_000_000_000,
) -> NormalizedProviderQuote:
    # Shares lineage ("cetus") and the Cetus pool object with the fixture
    # route: one correlated view of the same liquidity, never extra liquidity.
    return _competing_quote(
        provider_id="cetus-direct",
        correlation_group="cetus-direct",
        lineage=("cetus",),
        pool_id=CETUS_POOL,
        output_amount_raw=output_amount_raw,
    )


def _independent_quote(output_amount_raw: int) -> NormalizedProviderQuote:
    # Disjoint group, lineage and pool ids with positive evidence on both
    # sides: the only kernel rule that establishes INDEPENDENT.
    return _competing_quote(
        provider_id="other-direct",
        correlation_group="other-direct",
        lineage=("otherdex",),
        pool_id=INDEPENDENT_POOL,
        output_amount_raw=output_amount_raw,
    )


# --------------------------------------------------------------------------
# Fail-closed stance (no transport ships; live read never authorized)
# --------------------------------------------------------------------------


class TestFailClosedStance:
    def test_none_transport_is_typed_disabled(self) -> None:
        with pytest.raises(AftermathIngressError) as raised:
            ingest_via_transport(None, _request(), received_at_ns=RECEIVED_AT_NS)
        assert raised.value.code is AftermathIngressFailureCode.DISABLED
        assert AFTERMATH_LIVE_CAPTURE_BLOCKED in raised.value.detail

    def test_transport_attempt_refused_with_both_gate_reasons(self) -> None:
        # The transport is never invoked: the gate runs first and cannot pass.
        def transport(request: AftermathSwapRouteRequest) -> object:  # pragma: no cover
            raise AssertionError("transport must never be invoked while BLOCKED")

        with pytest.raises(AftermathIngressError) as raised:
            ingest_via_transport(transport, _request(), received_at_ns=RECEIVED_AT_NS)
        assert raised.value.code is AftermathIngressFailureCode.LIVE_READ_NOT_AUTHORIZED
        assert AFTERMATH_LIVE_CAPTURE_BLOCKED in raised.value.detail
        assert AFTERMATH_SUI_PROVIDER_QUORUM_REQUIRED in raised.value.detail

    def test_gate_verdict_is_deterministically_blocked(self) -> None:
        verdict = live_read_gate_verdict()
        assert verdict == live_read_gate_verdict()
        assert verdict.status == "BLOCKED"
        assert verdict.reasons == (
            AFTERMATH_LIVE_CAPTURE_BLOCKED,
            AFTERMATH_SUI_PROVIDER_QUORUM_REQUIRED,
        )
        assert verdict.capture_verdict.status == "BLOCKED"
        assert verdict.ingress_version == AFTERMATH_INGRESS_VERSION

    def test_correlated_provider_pair_reason_is_preserved(self) -> None:
        # Two identical non-smoke bindings violate the GPR-03 independence
        # rule; the typed ValueError string is preserved verbatim as a gate
        # reason instead of being collapsed into a generic refusal.
        from src.gpr_sui_shadow.providers import CheckpointProviderBinding

        binding = CheckpointProviderBinding(
            profile_id="p1",
            provider="a",
            operator="a",
            correlation_group="a",
            transport="graphql",
            endpoint="https://sui.example/graphql",
            schema_pin=_sha("schema"),
            genesis_chain_identifier="sui-mainnet",
        )
        verdict = live_read_gate_verdict(((binding, binding), ()))  # type: ignore[arg-type]
        assert verdict.status == "BLOCKED"
        assert "SUI_TWO_INDEPENDENT_PROVIDER_BINDINGS_REQUIRED" in verdict.reasons

    def test_no_environment_variable_flips_the_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AFTERMATH_LIVE_AUTHORIZED", "1")
        monkeypatch.setenv("LIVE_SUI_PROVIDERS_AUTHORIZED", "1")
        assert live_read_gate_verdict().status == "BLOCKED"
        with pytest.raises(AftermathIngressError) as raised:
            ingest_via_transport(
                lambda request: _fixture_payload(),
                _request(),
                received_at_ns=RECEIVED_AT_NS,
            )
        assert raised.value.code is AftermathIngressFailureCode.LIVE_READ_NOT_AUTHORIZED

    def test_ingress_module_ships_no_network_imports(self) -> None:
        from src.gpr_sui_shadow.providers import aftermath_ingress as ing

        tree = ast.parse(Path(ing.__file__).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for forbidden in ("requests", "urllib.request", "httpx", "aiohttp", "socket"):
            assert forbidden not in imported, f"ingress must not import {forbidden}"


# --------------------------------------------------------------------------
# Offline positives: retained fixture -> governed race evidence
# --------------------------------------------------------------------------


class TestOfflineIngestPositive:
    def test_fixture_ingest_races_through_existing_kernel(self) -> None:
        result = ingest_offline_payload(
            _fixture_payload(), request=_request(), received_at_ns=RECEIVED_AT_NS
        )
        assert result.batch.failures == ()
        assert len(result.batch.entries) == 1
        assert result.race.winner is not None
        assert result.race.winner.provider_id == "aftermath"
        assert result.race.entries[0].verdict is RaceVerdict.WON

    def test_governed_record_carries_exact_provenance(self) -> None:
        request = _request()
        result = ingest_offline_payload(
            _fixture_payload(), request=request, received_at_ns=RECEIVED_AT_NS
        )
        quote = result.race.winner
        assert quote is not None
        # Exact full Move CoinTypes travel through the request binding, and
        # amounts stay exact integer base units (no floats, no scaling).
        assert request.coin_in_type == SUI_TYPE
        assert request.coin_out_type == USDC_TYPE
        assert type(quote.input_amount_raw) is int
        assert type(quote.output_amount_raw) is int
        assert quote.input_amount_raw == 1_500_000_000
        assert quote.output_amount_raw == 5_000_000_000
        assert quote.input_amount_normalized == quote.input_amount_raw
        assert quote.output_amount_normalized == quote.output_amount_raw
        # Route legs in response order with canonical pool object identities.
        assert [venue.venue_label for venue in quote.route_venues] == [
            "Cetus",
            "Aftermath",
        ]
        assert [venue.pool.identity for venue in quote.route_venues] == [
            CETUS_POOL,
            AFTERMATH_POOL,
        ]
        assert all(
            venue.pool.kind is PoolIdentityKind.POOL_OBJECT_ID
            for venue in quote.route_venues
        )
        # Provider/correlation provenance: one SOR operator view.
        assert quote.correlation.correlation_group == "aftermath-sor"
        assert "aftermath" in quote.correlation.aggregator_lineage
        assert "cetus" in quote.correlation.aggregator_lineage
        assert {pool.identity for pool in quote.correlation.pool_ids} == {
            CETUS_POOL,
            AFTERMATH_POOL,
        }
        # Fee components preserve the pinned unknown inclusion state: the
        # fixture's one feeBreakdown entry plus the pinned netTradeFee rate.
        assert len(quote.fees) == 2
        assert quote.fees[0].kind == "fee_breakdown_0"
        assert quote.fees[0].inclusion_state is FeeInclusionState.UNKNOWN
        assert quote.fees[1].kind == "net_trade_fee"
        assert quote.fees[1].inclusion_state is FeeInclusionState.UNKNOWN
        # Raw evidence hashes and kernel invariants.
        assert quote.raw_response_hash == result.batch.raw_payload_sha256
        assert len(quote.raw_response_hash) == 64
        assert quote.request_fingerprint == request.request_fingerprint
        assert quote.execution_authority is False
        assert result.batch.evidence_state == AFTERMATH_EVIDENCE_STATE
        assert result.evidence_state == AFTERMATH_INGRESS_EVIDENCE_STATE

    def test_state_evidence_unattached_records_typed_blocker(self) -> None:
        result = ingest_offline_payload(
            _fixture_payload(), request=_request(), received_at_ns=RECEIVED_AT_NS
        )
        assert result.state_binding == AFTERMATH_STATE_EVIDENCE_UNATTACHED
        assert result.state_evidence is None
        assert result.blockers == (AFTERMATH_STATE_EVIDENCE_REQUIRED,)
        winner = result.race.winner
        assert winner is not None
        assert winner.freshness.checkpoint_sequence is None
        assert winner.freshness.slot is None
        assert winner.freshness.expires_at_ns is None


# --------------------------------------------------------------------------
# State evidence binding (checkpoint provenance is never synthesized)
# --------------------------------------------------------------------------


class TestStateEvidenceBinding:
    def test_valid_evidence_attaches_checkpoint(self) -> None:
        evidence = _state_evidence()
        result = ingest_offline_payload(
            _fixture_payload(),
            request=_request(),
            received_at_ns=RECEIVED_AT_NS,
            state_evidence=evidence,
        )
        assert result.state_binding == (
            AFTERMATH_STATE_EVIDENCE_ATTACHED_FROM_INDEPENDENT_CAPTURE
        )
        assert result.blockers == ()
        assert result.state_evidence == evidence
        winner = result.race.winner
        assert winner is not None
        assert winner.freshness.checkpoint_sequence == 12_345
        # Every other freshness field stays exactly as the adapter decoded it.
        assert winner.freshness.received_at_ns == RECEIVED_AT_NS
        assert winner.freshness.provider_generated_at_ns is None

    def test_malformed_evidence_is_typed_refusal(self) -> None:
        bad_evidence_cases = (
            {"checkpoint_sequence": 0},
            {"checkpoint_sequence": 12_345.5},
            {"checkpoint_digest": "not-a-digest"},
            {"capture_provider": "Sui-State-Quorum"},
            {"capture_correlation_group": ""},
            {"capture_request_hash": "z" * 64},
            {"evidence_ref": _sha("ok") + "extra"},
            {"captured_at_ns": 0},
        )
        for overrides in bad_evidence_cases:
            with pytest.raises(AftermathIngressError) as raised:
                _state_evidence(**overrides)
            assert (
                raised.value.code is AftermathIngressFailureCode.STATE_EVIDENCE_INVALID
            )

    def test_non_evidence_object_refused(self) -> None:
        with pytest.raises(AftermathIngressError) as raised:
            ingest_offline_payload(
                _fixture_payload(),
                request=_request(),
                received_at_ns=RECEIVED_AT_NS,
                state_evidence={"checkpoint_sequence": 1},  # type: ignore[arg-type]
            )
        assert raised.value.code is AftermathIngressFailureCode.STATE_EVIDENCE_INVALID


# --------------------------------------------------------------------------
# Race/dedup reuse (the kernel owns ranking and correlation rules)
# --------------------------------------------------------------------------


class TestRaceAndDedupReuse:
    def test_correlated_competing_quote_loses_with_typed_reason(self) -> None:
        result = ingest_offline_payload(
            _fixture_payload(),
            request=_request(),
            received_at_ns=RECEIVED_AT_NS,
            competing_quotes=(_correlated_cetus_quote(),),
        )
        assert result.race.winner is not None
        assert result.race.winner.provider_id == "cetus-direct"
        loser = next(
            entry
            for entry in result.race.entries
            if entry.quote.provider_id == "aftermath"
        )
        assert QuoteLossReason.CORRELATED_OBSERVATION in loser.loss_reasons
        assert QuoteLossReason.INFERIOR_OUTPUT in loser.loss_reasons

    def test_independent_competing_quote_wins_cleanly(self) -> None:
        result = ingest_offline_payload(
            _fixture_payload(),
            request=_request(),
            received_at_ns=RECEIVED_AT_NS,
            competing_quotes=(_independent_quote(output_amount_raw=6_000_000_000),),
        )
        assert result.race.winner is not None
        assert result.race.winner.provider_id == "other-direct"
        loser = next(
            entry
            for entry in result.race.entries
            if entry.quote.provider_id == "aftermath"
        )
        assert QuoteLossReason.CORRELATED_OBSERVATION not in loser.loss_reasons
        assert QuoteLossReason.INFERIOR_OUTPUT in loser.loss_reasons

    def test_independent_verdict_requires_disjoint_positive_evidence(self) -> None:
        aftermath = ingest_offline_payload(
            _fixture_payload(), request=_request(), received_at_ns=RECEIVED_AT_NS
        ).race.winner
        independent = _independent_quote(output_amount_raw=4_000_000_000)
        correlated = _correlated_cetus_quote()
        assert aftermath is not None
        assert (
            PoolIdentityDeduplicator.correlation_verdict(aftermath, independent)
            is IndependenceVerdict.INDEPENDENT
        )
        assert (
            PoolIdentityDeduplicator.correlation_verdict(aftermath, correlated)
            is IndependenceVerdict.CORRELATED
        )

    def test_independent_competing_quote_preserved_as_loser(self) -> None:
        result = ingest_offline_payload(
            _fixture_payload(),
            request=_request(),
            received_at_ns=RECEIVED_AT_NS,
            competing_quotes=(_independent_quote(output_amount_raw=4_000_000_000),),
        )
        # The Aftermath quote still wins; the losing observation is preserved
        # with typed reasons (nothing is dropped).
        assert result.race.winner is not None
        assert result.race.winner.provider_id == "aftermath"
        assert len(result.race.entries) == 2
        loser = result.race.entries[1]
        assert loser.quote.provider_id == "other-direct"
        assert QuoteLossReason.INFERIOR_OUTPUT in loser.loss_reasons


# --------------------------------------------------------------------------
# Provider status ladder (deterministic, typed)
# --------------------------------------------------------------------------


class TestStatusLadder:
    def test_ladder_is_deterministic_and_complete(self) -> None:
        ladder = provider_lane_status()
        assert ladder == provider_lane_status()
        statuses = {stage.stage: stage.status for stage in ladder}
        assert set(statuses) == {
            "DOCUMENTED",
            "ADAPTER",
            "BOOT_WIRED",
            "COMPARABLE",
            "LIVE_READ",
            "ROOTED",
            "BUILDABLE",
            "R02_QUALIFIED",
            "R05_SIMULATED",
            "R06_PAPER_QUALIFIED",
        }
        assert statuses["ADAPTER"] == "ACHIEVED"
        assert statuses["BOOT_WIRED"] == "ACHIEVED"
        assert statuses["COMPARABLE"] == "ACHIEVED"
        assert statuses["LIVE_READ"] == "BLOCKED"
        assert statuses["ROOTED"] == "BLOCKED"
        assert statuses["R02_QUALIFIED"] == "BLOCKED"
        assert statuses["R06_PAPER_QUALIFIED"] == "BLOCKED"
        assert statuses["BUILDABLE"] == "NOT_STARTED"
        assert statuses["R05_SIMULATED"] == "NOT_STARTED"

    def test_live_stages_carry_the_exact_gate_reasons(self) -> None:
        reasons = {stage.stage: stage.reason for stage in provider_lane_status()}
        assert AFTERMATH_LIVE_CAPTURE_BLOCKED in reasons["LIVE_READ"]
        assert LIVE_SUI_PROVIDERS_BLOCKED in reasons["LIVE_READ"]
        assert LIVE_SUI_PROVIDERS_BLOCKED in reasons["ROOTED"]
        assert "N09" in reasons["R02_QUALIFIED"]


# --------------------------------------------------------------------------
# Deterministic replay
# --------------------------------------------------------------------------


class TestDeterministicReplay:
    def test_replay_is_identical(self) -> None:
        kwargs: dict[str, object] = {
            "request": _request(),
            "received_at_ns": RECEIVED_AT_NS,
            "state_evidence": _state_evidence(),
            "competing_quotes": (_independent_quote(output_amount_raw=4_000_000_000),),
        }
        first = ingest_offline_payload(_fixture_payload(), **kwargs)  # type: ignore[arg-type]
        second = ingest_offline_payload(_fixture_payload(), **kwargs)  # type: ignore[arg-type]
        assert first == second
        # The race fingerprint doubles as the deterministic replay receipt.
        assert first.race.race_fingerprint == second.race.race_fingerprint
        assert len(first.race.race_fingerprint) == 64

    def test_freshness_drift_does_not_drift_payload_hash(self) -> None:
        early = ingest_offline_payload(
            _fixture_payload(), request=_request(), received_at_ns=RECEIVED_AT_NS
        )
        late = ingest_offline_payload(
            _fixture_payload(),
            request=_request(),
            received_at_ns=RECEIVED_AT_NS + 5_000_000_000,
        )
        assert early.batch.raw_payload_sha256 == late.batch.raw_payload_sha256
        assert (
            early.race.winner.freshness.received_at_ns
            != late.race.winner.freshness.received_at_ns
        )


# --------------------------------------------------------------------------
# Regression: package surface and N09 owner boundary
# --------------------------------------------------------------------------


class TestPackageRegression:
    def test_ingress_is_not_boot_exported(self) -> None:
        # Deliberate: the GPR-03 public surface stays unchanged; the ingress
        # is imported explicitly by the R13 lane, never wired into a boot path.
        assert not hasattr(gpr03, "ingest_offline_payload")
        assert not hasattr(gpr03, "AftermathIngressResult")
        from src.gpr_sui_shadow import providers

        assert not hasattr(providers, "ingest_offline_payload")
        assert not hasattr(providers, "AftermathStateEvidence")

    def test_adapter_surface_untouched(self) -> None:
        assert hasattr(am, "normalize_aftermath_trade_route_response")
        assert hasattr(am, "normalize_via_transport")
        assert hasattr(am, "aftermath_live_capture_verdict")

    def test_ingress_imports_no_navi_or_multichain_owner(self) -> None:
        from src.gpr_sui_shadow.providers import aftermath_ingress as ing

        tree = ast.parse(Path(ing.__file__).read_text(encoding="utf-8"))
        modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
        for owner in ("src.multichain", "src.lending"):
            assert not any(
                module == owner or module.startswith(owner + ".") for module in modules
            ), f"ingress must not import N09-owned owner {owner}"
