from dataclasses import asdict, replace
from pathlib import Path

import pytest

from src.assets.resolution.evidence import EvidenceStore, digest
from src.assets.resolution.resolver import AssetResolutionJob, resolve
from src.discovery.dynamic_universe.campaign import run_campaign
from src.discovery.dynamic_universe.promotion import (
    MarketProof,
    PromotionBoundary,
    PromotionStage,
    QPRReadiness,
)
from src.market.observations import MarketObservationV2, ObservationGeneration
from tests.test_dynamic_asset_resolution import candidate, proof, evidence, MINT, OTHER
from tests.test_dynamic_universe import market


def fixtures(store):
    assets = []
    for identifier in (MINT, OTHER):
        payload = {"identifier": identifier}
        registry = replace(evidence(), response_hash=digest(payload))
        rpc = replace(evidence("asset-rpc", 10), response_hash=digest(payload))
        store.append(registry, payload)
        store.append(rpc, payload)
        receipt = resolve(
            AssetResolutionJob("solana", identifier, "campaign"),
            (candidate(identifier=identifier, evidence=registry),),
            (proof(identifier=identifier, evidence=rpc),),
            now=101,
        )
        assets.append(receipt.identity)
    proofs = []
    for provider in ("rpc-a", "rpc-b"):
        payload = {"pool": "pool", "state": "exact"}
        e = replace(evidence(provider, 10), response_hash=digest(payload))
        store.append(e, payload)
        proofs.append(MarketProof(market(), e, MINT, OTHER, digest(payload)))
    quote = MarketObservationV2(
        provider="rpc-a",
        source="exact-fixture",
        input_mint=MINT,
        output_mint=OTHER,
        input_amount=10,
        expected_output=12,
        guaranteed_output=11,
        slot=10,
        observed_at=100,
        commitment="finalized",
        response_hash=proofs[0].evidence.response_hash,
        request_fingerprint=proofs[0].evidence.request_hash,
        generation=ObservationGeneration(
            "mainnet", "rpc", "campaign", "campaign", "fixture"
        ),
    )
    return tuple(assets), tuple(proofs), quote


def readiness(store):
    # Test-only injected owner; production default has no QPR adapter and denies.
    payload = {
        "schema_version": "prequal.campaign-handoff.v1",
        "campaign_id": "campaign",
        "manifest": {
            "mode": "CAPTURE_ONLY",
            "safety": {
                "signer_reachable": False,
                "sender_reachable": False,
                "transaction_submission_allowed": False,
                "live_authorization": False,
            },
        },
        "campaign_readiness": {
            "target": "READ_ONLY_REAL_DATA_CAMPAIGN_V1",
            "status": "PASS",
        },
        "qualification_verdict": "PASS",
        "stop_before": None,
    }
    e = replace(evidence("qpr-test-fixture"), response_hash=digest(payload))
    receipt = QPRReadiness(
        "READ_ONLY_REAL_DATA_CAMPAIGN_V1", "campaign", "PASS", store.append(e, payload)
    )
    return lambda: receipt


def test_default_qpr_gate_blocks_even_exact_fixture_evidence(tmp_path):
    store = EvidenceStore(tmp_path)
    assets, proofs, quote = fixtures(store)
    boundary = PromotionBoundary("campaign", store)
    result = boundary.evaluate(market(), assets, proofs, quote, now=101)
    assert result.stage == PromotionStage.MARKET_VERIFIED
    assert "QPR_READ_ONLY_REAL_DATA_CAMPAIGN_V1_NOT_PASS" in result.reasons
    with pytest.raises(ValueError, match="gate closed"):
        boundary.handoff(
            result, ingest=None, binding_id="pool", observation=quote, now=101
        )


def test_existing_readiness_owner_allows_exact_stage_but_no_paper_claim(tmp_path):
    store = EvidenceStore(tmp_path)
    assets, proofs, quote = fixtures(store)
    boundary = PromotionBoundary(
        "campaign", store, readiness_evaluator=readiness(store)
    )
    result = boundary.evaluate(market(), assets, proofs, quote, now=101)
    assert result.stage == PromotionStage.RPC_EXACT and not result.reasons
    assert result.paper_net is None
    assert store.replay(result.durable_ref)["payload"]["stage"] == "RPC_EXACT"


@pytest.mark.parametrize(
    "failure", ("disagreement", "alias", "stale", "wrong_generation", "missing_proof")
)
def test_exact_boundary_negative_evidence(tmp_path, failure):
    store = EvidenceStore(tmp_path)
    assets, proofs, quote = fixtures(store)
    if failure == "disagreement":
        proofs = proofs[:1] + (replace(proofs[1], decoded_state_hash=digest("other")),)
    elif failure == "alias":
        proofs = proofs[:1] + (
            replace(
                proofs[1],
                evidence=replace(
                    proofs[1].evidence,
                    correlation_group=proofs[0].evidence.correlation_group,
                ),
            ),
        )
    elif failure == "stale":
        quote = replace(quote, observed_at=90)
    elif failure == "wrong_generation":
        quote = replace(quote, generation=ObservationGeneration())
    else:
        proofs = ()
    result = PromotionBoundary(
        "campaign", store, readiness_evaluator=readiness(store)
    ).evaluate(market(), assets, proofs, quote, now=101)
    assert result.stage not in (
        PromotionStage.RPC_EXACT,
        PromotionStage.PAPER_QUALIFIED,
    )
    assert result.reasons


def test_unrun_campaign_cannot_be_pass(tmp_path):
    with pytest.raises(ValueError, match="--live"):
        run_campaign(
            Path(__file__).resolve().parents[1],
            tmp_path,
            generation="campaign",
            live=False,
        )


def test_wave_has_no_signer_sender_or_submission_imports():
    root = Path(__file__).resolve().parents[1]
    owners = (
        "src/assets",
        "src/discovery/dynamic_universe",
        "src/strategy/relation_generators",
        "src/research/correlation_ledger",
        "src/economics/flash_capital_graph",
    )
    import ast

    for owner in owners:
        for path in (root / owner).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom):
                    assert not (node.module or "").startswith(
                        ("src.execution", "isolated_signer_service", "src.ingest")
                    )


def test_research_record_is_rejected_by_existing_graph_ingest():
    from src.strategy.market_graph_ingest import ShadowMarketGraphIngest

    with pytest.raises(ValueError, match="discovery/reference"):
        ShadowMarketGraphIngest.ingest(None, "pool", market())


def test_qpr_missing_proof_and_nonpass_do_not_open_gate(tmp_path):
    store = EvidenceStore(tmp_path)
    fabricated = lambda: QPRReadiness(
        "READ_ONLY_REAL_DATA_CAMPAIGN_V1", "campaign", "PASS", "missing-handoff"
    )
    assert not PromotionBoundary(
        "campaign", store, readiness_evaluator=fabricated
    ).readiness()
    owner = readiness(store)
    assert not PromotionBoundary("other", store, readiness_evaluator=owner).readiness()


def test_qpr03_readiness_pass_does_not_bypass_stop_before_qpr04(tmp_path):
    store = EvidenceStore(tmp_path)
    positive_fixture = readiness(store)()
    payload = store.replay(positive_fixture.handoff_ref)["payload"]
    payload["qualification_verdict"] = "BLOCKED"
    payload["stop_before"] = "QPR-04"
    e = replace(evidence("qpr03-fixture"), response_hash=digest(payload))
    receipt = replace(positive_fixture, handoff_ref=store.append(e, payload))
    boundary = PromotionBoundary("campaign", store, readiness_evaluator=lambda: receipt)
    assert not boundary.readiness()


def test_closed_route_paper_and_existing_five_hop_topology_owner(tmp_path):
    from src.economics.flash_capital_graph.graph import FlashCapitalGraph
    from src.strategy.arbitrage_graph import (
        CircularShadowRoute,
        DirectedQuoteEdge,
        UniversalArbitrageGraph,
        VenueIdentity,
    )
    from src.market.observations import ObservationBatch
    from src.strategy.relation_generators.generators import shortlist_verified_cycles
    from tests.test_dynamic_flash_capital import capital

    store = EvidenceStore(tmp_path)
    assets, _, template = fixtures(store)
    third = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
    payload = {"identifier": third}
    registry = replace(evidence(), response_hash=digest(payload))
    chain = replace(evidence("asset-rpc", 10), response_hash=digest(payload))
    store.append(registry, payload)
    store.append(chain, payload)
    third_asset = resolve(
        AssetResolutionJob("solana", third, "campaign"),
        (candidate(identifier=third, evidence=registry),),
        (proof(identifier=third, evidence=chain),),
        now=101,
    ).identity
    assets += (third_asset,)
    boundary = PromotionBoundary(
        "campaign", store, readiness_evaluator=readiness(store)
    )
    edges, receipts = [], []
    mints, amounts = (MINT, OTHER, third, MINT), (10, 11, 12, 16)
    for i in range(3):
        m = market(
            market_id=f"pool-{i}",
            base=mints[i],
            quote=mints[i + 1],
            correlation_group=f"pool-{i}",
            underlying_resources=(f"pool-{i}",),
        )
        proofs = []
        for provider in ("rpc-a", "rpc-b"):
            raw = {"market": m.market_id, "state": "exact"}
            e = replace(evidence(provider, 10), response_hash=digest(raw))
            store.append(e, raw)
            proofs.append(MarketProof(m, e, m.base, m.quote, digest(raw)))
        q = replace(
            template,
            input_mint=m.base,
            output_mint=m.quote,
            input_amount=amounts[i],
            expected_output=amounts[i + 1],
            guaranteed_output=amounts[i + 1],
            response_hash=proofs[0].evidence.response_hash,
        )
        receipts.append(boundary.evaluate(m, assets, tuple(proofs), q, now=101))
        edges.append(DirectedQuoteEdge(VenueIdentity(m.program_id, m.market_id), q))
    route = CircularShadowRoute(
        tuple(edges), "batch", "watermark", edges[0].observation.generation.identity
    )
    graph = UniversalArbitrageGraph(
        ObservationBatch(tuple(e.observation for e in edges), published_at=101),
        tuple(edges),
    )
    shortlist = shortlist_verified_cycles(
        graph, boundary, receipts, start_asset=MINT, now=101
    )
    assert shortlist.routes[0].hop_count == 3
    funding = FlashCapitalGraph("campaign", store)
    edge = capital(protocol_rounding=0)
    funding.observe(edge, now=101)
    ledger = funding.paper_ledger(
        edge,
        asset=assets[0],
        principal=10,
        guaranteed_output=16,
        costs=(),
        resources=frozenset(),
        now=101,
    )
    receipt = boundary.qualify_route(
        route, tuple(receipts), ledger, capital_ref=funding.history[0], now=101
    )
    assert store.replay(receipt)["payload"]["stage"] == "PAPER_QUALIFIED"
    assert store.replay(receipt)["payload"]["executable"] is False
    with pytest.raises(ValueError):
        boundary.qualify_route(
            route,
            tuple(receipts),
            replace(
                ledger,
                flash_repayment=replace(ledger.flash_repayment, flash_fee_amount=0),
            ),
            capital_ref=funding.history[0],
            now=101,
        )


def test_observation_time_cannot_be_changed_after_exact_receipt(tmp_path):
    store = EvidenceStore(tmp_path)
    assets, proofs, quote = fixtures(store)
    boundary = PromotionBoundary(
        "campaign", store, readiness_evaluator=readiness(store)
    )
    receipt = boundary.evaluate(market(), assets, proofs, quote, now=101)
    with pytest.raises(ValueError):
        boundary.handoff(
            receipt,
            ingest=None,
            binding_id="pool",
            observation=replace(quote, observed_at=104),
            now=104,
        )
