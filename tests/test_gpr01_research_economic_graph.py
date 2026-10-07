"""GPR V2.2 deterministic, network-disabled and fail-closed acceptance corpus."""

import asyncio
import base64
import copy
from dataclasses import asdict, replace
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

from src.market.native_cpmm_capture import GovernedNativeCpmmCollector
from src.market.source_catalog import load_market_source_catalog
from src.market.streams import RecoverableStreamJournal
from src.provider_governance import ProviderGovernance
from src.qualification_campaign.evidence import CampaignEvidenceStore
from src.qualification_campaign.identity import CampaignManifest, digest
from src.qualification_campaign.profiles import ProviderProfile
from src.qualification_campaign.rpc import NativeRootedSnapshotProvider
from src.qualification_campaign.sources import (
    Candidate,
    SourceDossier,
    SourceIntakePlane,
    SourceReadRequest,
)
from src.research_economic_graph import (
    AnchorType,
    AssetRegistry,
    CampaignSeed,
    CandidateScore,
    EvidenceState,
    ExecutionClass,
    HardBoundIdentityGate,
    Heat,
    IdentityExpectation,
    ResearchEconomicGraph,
    ResearchRelation,
    SolanaResearchAdapter,
    StartupIdentityPolicy,
    VerificationQueue,
    VerificationTarget,
    ingest_solana_exact,
)
from src.research_economic_graph.registry import DEFAULT_PACK, TOKEN_2022_PROGRAM
from src.routing.transport import HttpxJsonTransport, TransportPolicy
from src.strategy.arbitrage_graph import VenueIdentity
from src.strategy.exact_cpmm_capacity import (
    MAINNET_GENESIS,
    RAYDIUM_CPMM_PROGRAM_ID,
    WSOL_MINT,
)
from src.strategy.market_graph_ingest import (
    ShadowMarketBinding,
    ShadowMarketGraphIngest,
)
from tests.native_cpmm_fixtures import address, synthetic_capture

pytestmark = pytest.mark.unit
NOW_NS = 1002 * 10**9


def registry_raw():
    return json.loads((DEFAULT_PACK / "ASSET_REGISTRY_V2.json").read_text())


def full_graph():
    registry = AssetRegistry.load()
    seed = CampaignSeed.load(registry)
    return ResearchEconomicGraph(registry, seed)


def make_manifest(graph, *, policy=None, sources=None):
    config = [
        ("gpr.registry", graph.registry.generation),
        ("gpr.seed", graph.seed.generation),
    ]
    if policy is not None:
        config.append(("gpr.identity_policy", policy.generation))
    return CampaignManifest(
        "a" * 40,
        "b" * 40,
        "c" * 64,
        tuple(config),
        tuple(sources or (("offline", "d" * 64),)),
    )


def test_registry_92_research_only_and_order_independent():
    raw = registry_raw()
    registry = AssetRegistry(raw)
    assert len(registry.assets) == 92
    raw["assets"].reverse()
    reversed_registry = AssetRegistry(raw)
    assert reversed_registry.generation == registry.generation
    assert list(reversed_registry.assets.items()) == list(registry.assets.items())
    assert all(
        not a.runtime_enabled and not a.exact_graph_allowed
        for a in registry.assets.values()
    )
    assert (
        registry.resolve("solana-mainnet:USDG").token_program_or_move_type
        == TOKEN_2022_PROGRAM
    )
    assert registry.resolve("solana-mainnet:PYUSD").standard == "Token-2022"
    assert registry.resolve("solana-mainnet:USDC").decimals is None
    assert registry.resolve("sui-mainnet:XAUM").decimals == 9
    assert registry.resolve("sui-mainnet:XAUM").economic_asset == "XAU"
    assert digest(registry.configuration) == registry.generation
    assert (
        digest(CampaignSeed.load(registry).configuration)
        == CampaignSeed.load(registry).generation
    )
    for asset in registry.assets.values():
        if asset.canonical_identifier is not None:
            assert (
                registry.by_identifier(asset.chain, asset.canonical_identifier) == asset
            )
    usdc = [
        registry.resolve(ref)
        for ref in (
            "solana-mainnet:USDC",
            "sui-mainnet:USDC_NATIVE",
            "sui-mainnet:WUSDC_ETH_ORIGIN",
            "sui-mainnet:USDC_SOL_PORTAL_ON_SUI",
        )
    ]
    assert len({digest(a.representation) for a in usdc}) == 4


@pytest.mark.parametrize(
    "chain,keys",
    [
        ("solana-mainnet", ("xBTC_OKX", "cbBTC", "WBTC_WORMHOLE", "tBTC")),
        ("sui-mainnet", ("USDC_NATIVE", "WUSDC_ETH_ORIGIN", "USDC_SOL_PORTAL_ON_SUI")),
        ("sui-mainnet", ("USDT_SUI_BRIDGE", "USDT_WORMHOLE")),
        ("sui-mainnet", ("XBTC", "WBTC_WORMHOLE", "WBTC_SUI_BRIDGE", "ZWBTC")),
    ],
)
def test_representations_never_alias_by_ticker_or_underlying(chain, keys):
    registry = AssetRegistry.load()
    assets = [registry.resolve(f"{chain}:{k}") for k in keys]
    assert len({a.canonical_identifier for a in assets}) == len(keys)
    assert len({digest(a.representation) for a in assets}) == len(keys)
    for asset in assets:
        assert registry.by_identifier(chain, asset.canonical_identifier) == asset
    with pytest.raises(ValueError, match="unqualified"):
        registry.resolve(keys[0])


def test_all_legacy_aliases_are_chain_scoped_and_collision_checked():
    registry = AssetRegistry.load()
    assert len(registry.aliases) == 1
    for alias, asset in registry.aliases.items():
        assert registry.resolve(alias) == asset
        assert registry.by_identifier(asset.chain, asset.canonical_identifier) == asset
    wormhole = registry.resolve("sui-mainnet:USDC_WORMHOLE")
    assert wormhole.origin_chain == "ethereum" and wormhole.bridge == "wormhole"
    portal = registry.resolve("sui-mainnet:USDC_SOL_PORTAL_ON_SUI")
    assert portal.origin_chain == "solana" and portal != wormhole
    raw = registry_raw()
    next(r for r in raw["assets"] if r["asset_key"] == "USDC_NATIVE")[
        "legacy_aliases"
    ] = ["USDC_WORMHOLE"]
    with pytest.raises(ValueError, match="ambiguous"):
        AssetRegistry(raw)


@pytest.mark.parametrize(
    "mutation", ["key", "identifier", "move-alias", "alias-shadow", "runtime", "exact"]
)
def test_registry_rejects_alias_collisions_and_authority_flags(mutation):
    raw = registry_raw()
    if mutation == "key":
        raw["assets"].append(copy.deepcopy(raw["assets"][0]))
    elif mutation == "identifier":
        raw["assets"][1]["canonical_id"] = raw["assets"][0]["canonical_id"]
    elif mutation == "move-alias":
        row = copy.deepcopy(next(r for r in raw["assets"] if r["asset_key"] == "SUI"))
        row["asset_key"] = "SUI_ALIAS"
        row["canonical_id"] = "0x" + "2".zfill(64) + "::sui::SUI"
        raw["assets"].append(row)
    elif mutation == "alias-shadow":
        raw["assets"][0]["legacy_aliases"] = [raw["assets"][1]["asset_key"]]
    else:
        raw["assets"][0][
            "runtime_enabled" if mutation == "runtime" else "exact_graph_allowed"
        ] = True
    with pytest.raises(ValueError):
        AssetRegistry(raw)


def test_14_families_9_books_and_reference_semantics():
    graph = full_graph()
    assert len(graph.seed.relations) == 14 and len(graph.seed.pools) == 9
    assert {r.relation_id for r in graph.seed.relations} == {
        f"F{i:02d}" for i in range(1, 15)
    }
    assert all(
        r.evidence_state == EvidenceState.IDENTIFIER_VERIFIED
        for r in graph.seed.relations
    )
    assert graph.relations["F01"].heat == Heat.HOT
    assert graph.relations["F02"].execution_class == ExecutionClass.LOCAL_ATOMIC
    assert graph.relations["F14"].execution_class == ExecutionClass.CROSS_CHAIN_SIGNAL
    assert graph.relations["F05"].anchor_types == (AnchorType.NAV,)
    assert graph.relations["F13"].anchor_types == (AnchorType.ORACLE_REFERENCE,)
    assert graph.relations["F13"].frictions == (
        "market_liquidity",
        "redemption",
        "tokenization",
    )
    assert graph.relations["F13"].reference == "Pyth XAU/USD"
    assert {a for r in graph.seed.relations for a in r.anchor_types} >= {
        AnchorType.USD_REDEMPTION,
        AnchorType.NAV,
        AnchorType.SAME_UNDERLYING,
        AnchorType.STAKING_EXCHANGE_RATE,
        AnchorType.BRIDGE_PARITY,
        AnchorType.ORACLE_REFERENCE,
    }
    assert all(
        p.evidence_state == EvidenceState.IDENTIFIER_VERIFIED
        and not p.exact_graph_allowed
        and not p.runtime_enabled
        for p in graph.seed.pools
    )
    assert len({p.canonical_object_id for p in graph.seed.pools}) == 9
    assert len({p.representations for p in graph.seed.pools}) == 9
    assert {p.pool_id for p in graph.seed.pools} == {
        p for r in graph.seed.relations for p in r.known_pool_or_book_ids
    }


def test_synthetic_identity_is_preserved_when_a_direct_market_is_discovered():
    graph = full_graph()
    synthetic = graph.relations["F03"]
    assert not synthetic.direct_venues and not synthetic.known_pool_or_book_ids
    assert synthetic.synthetic_paths[0].representations == (
        "solana-mainnet:PYUSD",
        "solana-mainnet:USDC",
        "solana-mainnet:USDG",
    )
    graph.add(
        ResearchRelation(
            "direct-pyusd-usdg",
            "SWAP_CANDIDATE",
            ("solana-mainnet:PYUSD", "solana-mainnet:USDG"),
            Heat.WARM,
            ExecutionClass.LOCAL_ATOMIC,
            EvidenceState.DISCOVERY_ONLY,
            known_pool_or_book_ids=(address(60),),
        )
    )
    assert graph.relations["F03"] == synthetic


@pytest.mark.parametrize("heat", list(Heat))
@pytest.mark.parametrize("execution", list(ExecutionClass))
def test_axes_are_independent_and_never_imply_executable(heat, execution):
    graph = full_graph()
    base = graph.relations["F01"]
    relation = replace(
        base, relation_id="independent", heat=heat, execution_class=execution
    )
    graph.add(relation)
    assert (
        graph.relations["independent"].evidence_state
        == EvidenceState.IDENTIFIER_VERIFIED
    )
    with pytest.raises(ValueError, match="self-promote"):
        graph.add(
            replace(
                relation,
                relation_id="forged-exact",
                evidence_state=EvidenceState.EXECUTABLE,
            )
        )


@pytest.mark.parametrize(
    "kind",
    [
        "CCTP",
        "WORMHOLE",
        "BRIDGE",
        "NATIVE_BURN_MINT",
        "LOCK_MINT_BRIDGE",
        "INVENTORY_REBALANCE",
    ],
)
def test_transport_cannot_masquerade_as_atomic_swap_even_on_one_chain(kind):
    with pytest.raises(ValueError, match="transport"):
        replace(full_graph().relations["F01"], relation_class=kind)


def test_cross_chain_topology_and_reference_anchors_fail_closed():
    graph = full_graph()
    for execution in (ExecutionClass.LOCAL_ATOMIC, ExecutionClass.LOCAL_SIGNAL):
        with pytest.raises(ValueError, match="cross-chain"):
            replace(graph.relations["F14"], execution_class=execution)
    for family in ("F05", "F13"):
        with pytest.raises(ValueError, match="fixed USD"):
            replace(graph.relations[family], anchor_types=(AnchorType.USD_REDEMPTION,))


@pytest.mark.parametrize(
    "ref",
    [
        "solana-mainnet:tBTC",
        "solana-mainnet:sUSDS",
        "sui-mainnet:AUSD",
        "sui-mainnet:CETUS",
    ],
)
def test_unresolved_revalidation_is_visible_but_cannot_promote(ref):
    graph = full_graph()
    asset = graph.registry.resolve(ref)
    assert not asset.identifier_verified
    relation = ResearchRelation(
        "needs-review",
        "REFERENCE",
        (ref,),
        Heat.HOT,
        ExecutionClass.LOCAL_SIGNAL,
        EvidenceState.DISCOVERY_ONLY,
    )
    graph.add(relation)
    with pytest.raises(ValueError, match="revalidation"):
        graph.add(
            replace(
                relation,
                relation_id="forged",
                evidence_state=EvidenceState.IDENTIFIER_VERIFIED,
            )
        )
    policy = StartupIdentityPolicy(
        (
            IdentityExpectation(
                ref,
                digest(asset.representation),
                9,
                ("reviewed-source:sha256=" + "f" * 64,),
            ),
        )
    )
    with pytest.raises(ValueError, match="REVALIDATION"):
        policy.require(asset)


def test_seed_durable_replay_and_bounded_queue(tmp_path):
    graph = full_graph()
    journal = RecoverableStreamJournal(tmp_path / "seed.sqlite")
    evidence = CampaignEvidenceStore(
        journal, make_manifest(graph), wall_ns=lambda: NOW_NS
    )
    graph.persist(evidence, observed_at_ns=NOW_NS)
    scores = {
        "F14": CandidateScore(
            (("cross_chain_basis", 5), ("rebalance_latency_penalty", 2))
        )
    }
    queue = VerificationQueue(graph, evidence).build(
        scores,
        top_k=4,
        per_chain_budget={"solana-mainnet": 2, "sui-mainnet": 2},
        now_ns=NOW_NS,
    )
    assert len(queue) == 4 and queue[0].score.total == 3
    assert queue[0].relation_id == "F14" and queue[1].relation_id == "F14"
    assert queue[0].target == queue[1].target == VerificationTarget.CROSS_CHAIN_RESEARCH
    assert len([r for r in queue if r.chain == "solana-mainnet"]) == 2
    queue_ref = VerificationQueue(graph, evidence).persist(
        scores,
        top_k=4,
        per_chain_budget={"solana-mainnet": 2, "sui-mainnet": 2},
        now_ns=NOW_NS,
    )
    journal.close()
    journal = RecoverableStreamJournal(tmp_path / "seed.sqlite")
    reopened = CampaignEvidenceStore(
        journal, make_manifest(graph), wall_ns=lambda: NOW_NS
    )
    replay = ResearchEconomicGraph.replay(reopened, graph.registry, graph.seed)
    assert replay.identity == graph.identity and replay.snapshot() == graph.snapshot()
    assert (
        VerificationQueue(replay, reopened).build(
            scores,
            top_k=4,
            per_chain_budget={"solana-mainnet": 2, "sui-mainnet": 2},
            now_ns=NOW_NS,
        )
        == queue
    )
    assert VerificationQueue(replay, reopened).replay(queue_ref) == queue
    assert (
        VerificationQueue(replay, reopened).build(
            {}, top_k=2, per_chain_budget={}, now_ns=NOW_NS
        )
        == ()
    )
    with pytest.raises(ValueError, match="REGISTRY_GENERATION"):
        VerificationQueue(
            replay,
            type(
                "Foreign",
                (),
                {
                    "manifest": replace(
                        reopened.manifest,
                        configuration_digests=(("gpr.registry", "f" * 64),),
                    )
                },
            )(),
        )
    journal.close()


@pytest.mark.parametrize(
    "inputs",
    [
        (("profit", 1),),
        (("liquidity_change", -1),),
        (("liquidity_change", True),),
        (("liquidity_change", 1), ("liquidity_change", 2)),
        (("liquidity_change", 1_000_001),),
    ],
)
def test_scores_are_bounded_and_not_profit(inputs):
    with pytest.raises(ValueError):
        CandidateScore(inputs)


class LabDiscoveryAdapter:
    def request(self):
        return SourceReadRequest("https://radar.test/pools")

    def schema_contract(self):
        return {"request": "lab-v1", "response": "lab-v1"}

    def normalize(self, payload):
        return tuple(Candidate(**r) for r in payload["rows"]), {}


async def build_lab(
    tmp_path,
    *,
    rpc_fault="none",
    discovery_status=200,
    identity_fault=None,
    discovery_reads=1,
):
    """Synthetic bytes served by the real governed collectors and QPR owners."""
    raw = registry_raw()
    raw["assets"] = [
        {
            "asset_key": key,
            "economic_asset_key": key,
            "chain": "solana-mainnet",
            "canonical_id": mint,
            "standard": "SPL",
            "representation": "fixture-only",
            "verification_status": "RND_VERIFIED_CURRENT",
            "runtime_enabled": False,
            "exact_graph_allowed": False,
        }
        for key, mint in (("LAB_A", WSOL_MINT), ("LAB_B", address(3)))
    ]
    if identity_fault == "program":
        raw["assets"][0]["standard"] = "Token-2022"
    registry = AssetRegistry(raw, source_ref="explicit-synthetic-lab")
    relation = ResearchRelation(
        "LAB",
        "SWAP_CANDIDATE",
        tuple(registry.assets),
        Heat.HOT,
        ExecutionClass.LOCAL_ATOMIC,
        EvidenceState.IDENTIFIER_VERIFIED,
        known_pool_or_book_ids=(address(50),),
    )
    seed = CampaignSeed((relation,), (), digest(relation.to_dict()))
    graph = ResearchEconomicGraph(registry, seed)
    policy = StartupIdentityPolicy(
        tuple(
            IdentityExpectation(
                a.asset_id,
                digest(a.representation),
                9,
                ("explicit-synthetic-lab:sha256=" + "f" * 64,),
            )
            for a in registry.assets.values()
        )
    )
    if identity_fault in ("decimals", "representation", "extensions", "deprecated"):
        fields = {
            "decimals": {"decimals": 6},
            "representation": {"representation_digest": "f" * 64},
            "extensions": {"extensions": ("transfer-fee",)},
            "deprecated": {"deprecation_state": "REPLACED"},
        }[identity_fault]
        policy = replace(
            policy,
            expectations=(
                replace(policy.expectations[0], **fields),
                policy.expectations[1],
            ),
        )
    profiles = tuple(
        ProviderProfile(
            f"rpc-{key}",
            key,
            f"operator-{key}",
            f"backend-{key}",
            f"https://rpc-{key}.test",
            f"https://docs.test/{key}",
        )
        for key in ("a", "b")
    )
    if rpc_fault == "single":
        profiles = profiles[:1]
    elif rpc_fault == "correlated":
        profiles = (
            profiles[0],
            replace(profiles[1], correlation_group=profiles[0].correlation_group),
        )
    elif rpc_fault == "smoke":
        profiles = (replace(profiles[0], smoke_only=True), profiles[1])
    radar = ProviderProfile(
        "radar",
        "index",
        "index-op",
        "index-backend",
        "https://radar.test/pools",
        "https://docs.test/radar",
        role="discovery",
    )
    adapter = LabDiscoveryAdapter()
    dossier = SourceDossier(
        "FREE-SOURCE-001",
        "lab discovery",
        radar,
        datetime.fromtimestamp(1000, UTC).isoformat(),
        "e" * 64,
        "lab-v1",
        "lab-v1",
        digest(adapter.schema_contract()),
        "https://docs.test/terms",
        slot_id="FREE-SOURCE-001",
    )
    manifest = make_manifest(
        graph,
        policy=policy,
        sources=[(p.profile_id, p.generation) for p in (*profiles, radar)]
        + [(dossier.source_id, dossier.generation)],
    )
    journal = RecoverableStreamJournal(tmp_path / "lab.sqlite")
    evidence = CampaignEvidenceStore(journal, manifest, wall_ns=lambda: NOW_NS)
    fixture = synthetic_capture()
    accounts = {r["address"]: r["value"] for r in fixture["accounts"]}
    calls = []

    def handler(req):
        calls.append(str(req.url.host))
        if req.url.host == "radar.test":
            return httpx.Response(
                discovery_status,
                headers={"retry-after": "8"},
                json={
                    "rows": [
                        {
                            "market_id": address(50),
                            "mints": [WSOL_MINT, address(3)],
                            "venue_label": "indexed-alias",
                        },
                        {
                            "market_id": address(51),
                            "mints": [address(3), address(4)],
                            "venue_label": "unregistered-pair",
                        },
                    ]
                },
            )
        body = json.loads(req.content)
        b = req.url.host == "rpc-b.test"
        if b and rpc_fault == "timeout":
            raise httpx.ReadTimeout("fixture timeout", request=req)
        if b and rpc_fault == "429":
            return httpx.Response(429, json={"error": "quota"})
        method = body["method"]
        if method == "getGenesisHash":
            result = MAINNET_GENESIS
        elif method == "getMultipleAccounts":
            result = {
                "context": {"slot": 100},
                "value": [copy.deepcopy(accounts[a]) for a in body["params"][0]],
            }
            if b and rpc_fault == "conflict" and len(body["params"][0]) > 5:
                result["value"][0]["lamports"] += 1
            if (
                b
                and rpc_fault in ("mint-owner", "mint-decimals")
                and WSOL_MINT in body["params"][0]
            ):
                index = body["params"][0].index(WSOL_MINT)
                if rpc_fault == "mint-owner":
                    result["value"][index]["owner"] = TOKEN_2022_PROGRAM
                else:
                    data = bytearray(
                        base64.b64decode(result["value"][index]["data"][0])
                    )
                    data[44] = 6
                    result["value"][index]["data"][0] = base64.b64encode(data).decode()
        elif method == "getBlock":
            result = fixture["block"]
        elif method == "getVersion":
            result = {"solana-core": "3.1.0", "feature-set": 123}
        elif method == "getSlot":
            result = 100
        else:
            raise AssertionError(method)
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": body["id"], "result": result}
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False, follow_redirects=False
    )
    transport = HttpxJsonTransport(
        policy=TransportPolicy(max_attempts=1, max_string_length=900_000),
        allowed_hosts=frozenset(p.hostname for p in (*profiles, radar)),
        client=client,
    )
    gov = ProviderGovernance(
        {
            p.profile_id: p.entitlement(expires_at_epoch_seconds=2000)
            for p in (*profiles, radar)
        },
        clock=lambda: 1002,
        wall_clock=lambda: 1002,
    )
    intake = SourceIntakePlane(
        load_market_source_catalog().with_intake(dossier.catalog_entry()),
        gov,
        transport,
        evidence,
        wall_ns=lambda: NOW_NS,
    )
    for _ in range(discovery_reads):
        await intake.collect(dossier, adapter)
    SolanaResearchAdapter(graph).ingest(evidence)
    collectors = [
        GovernedNativeCpmmCollector(
            gov, transport, profile=p, evidence_store=evidence, wall_ns=lambda: NOW_NS
        )
        for p in profiles
    ]
    provider = NativeRootedSnapshotProvider(
        collectors, evidence, monotonic_ms=lambda: 10_000, wall_ns=lambda: NOW_NS
    )
    await provider.collect(tuple(fixture["pool_ids"]))
    bundle_ref = next(
        e.identity
        for e in journal.events(available_at_ns=2**63 - 1)
        if evidence.expand(e.payload_json).get("kind") == "rooted_snapshot_bundle"
    )
    await transport.aclose()
    await client.aclose()
    gate = HardBoundIdentityGate(
        registry,
        evidence,
        policy,
        campaign_started_at_ns=1000 * 10**9,
        wall_ns=lambda: NOW_NS,
    )
    return graph, evidence, gate, bundle_ref, calls


@pytest.mark.parametrize("status", [200, 401, 429, 503])
def test_qpr03_adapter_retains_negative_raw_provenance_and_replays_without_network(
    tmp_path, status
):
    graph, evidence, gate, bundle, calls = asyncio.run(
        build_lab(tmp_path, discovery_status=status)
    )
    before_calls = list(calls)
    SolanaResearchAdapter(graph).ingest(evidence)
    candidate_relations = [
        r for r in graph.relations.values() if r.relation_id.startswith("qpr03:")
    ]
    if status == 200:
        assert len(candidate_relations) == 1
        r = candidate_relations[0]
        assert r.evidence_state == EvidenceState.DISCOVERY_ONLY and r.heat == Heat.HOT
        assert (
            r.evidence[0].operator == "index-op"
            and r.evidence[0].correlation_group == "index-backend"
        )
        assert (
            r.evidence[0].request_hash
            and r.evidence[0].response_hash
            and r.evidence[0].retained_payload_hash
        )
        assert graph.snapshot()["rejections"][0][-1] == "unregistered-representation"
    else:
        assert candidate_relations == []
        assert any(o["quality"] != "accepted" for o in graph.snapshot()["observations"])
    graph.persist(evidence, observed_at_ns=NOW_NS)
    replay = ResearchEconomicGraph.replay(evidence, graph.registry, graph.seed)
    assert replay.identity == graph.identity and calls == before_calls
    assert any(e["kind"] == "attempt" for e in evidence.replay())
    evidence.journal.close()


def exact_sink():
    binding = ShadowMarketBinding(
        "lab-pool",
        "raydium",
        "qpr02-direct",
        VenueIdentity(RAYDIUM_CPMM_PROGRAM_ID, address(50)),
        (WSOL_MINT, address(3)),
        "qpr02-native-decoder",
    )
    return ShadowMarketGraphIngest(load_market_source_catalog(), (binding,))


def test_dedup_preserves_correlated_reads_and_score_inputs_on_replay(tmp_path):
    graph, evidence, gate, bundle, calls = asyncio.run(
        build_lab(tmp_path, discovery_reads=2)
    )
    relation, request = exact_request(graph, evidence)
    assert len(relation.evidence) == 2 and calls.count("radar.test") == 2
    assert len({e.raw_evidence_id for e in relation.evidence}) == 2
    assert dict(request.score.decomposition)["source_correlation_penalty"] == -1
    first = replace(
        relation,
        evidence=(relation.evidence[0],),
        provenance_refs=(relation.evidence[0].raw_evidence_id,),
    )
    second = replace(
        relation,
        evidence=(relation.evidence[1],),
        provenance_refs=(relation.evidence[1].raw_evidence_id,),
    )
    graphs = [ResearchEconomicGraph(graph.registry, graph.seed) for _ in range(2)]
    for r in (first, second):
        graphs[0].add(r)
    for r in (second, first):
        graphs[1].add(r)
    assert graphs[0].identity == graphs[1].identity
    scores = {relation.relation_id: CandidateScore((("liquidity_change", 10),))}
    queue = VerificationQueue(graph, evidence)
    ref = queue.persist(scores, top_k=1, now_ns=NOW_NS + relation.staleness_ttl_ns + 1)
    replayed = queue.replay(ref)
    assert dict(replayed[0].score.decomposition)["staleness_penalty"] == -1
    assert dict(replayed[0].score.decomposition)["source_correlation_penalty"] == -1
    assert replayed[0].score.total == 8
    evidence.journal.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"heat": "HOT_EXEC"},
        {"execution_class": "ATOMIC_BRIDGE"},
        {"evidence_state": "TRUSTED"},
    ],
)
def test_unknown_classification_axes_fail_closed(changes):
    with pytest.raises(ValueError):
        replace(full_graph().relations["F01"], **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"top_k": 257},
        {"top_k": 0},
        {"top_k": True},
        {"per_chain_budget": {"sui-mainnet": 257}},
        {"per_chain_budget": {"ton-mainnet": 1}},
    ],
)
def test_queue_bounds_fail_before_creating_work(tmp_path, changes):
    graph = full_graph()
    evidence = CampaignEvidenceStore(
        RecoverableStreamJournal(tmp_path / "bounds.sqlite"),
        make_manifest(graph),
        wall_ns=lambda: NOW_NS,
    )
    with pytest.raises(ValueError):
        VerificationQueue(graph, evidence).build({}, now_ns=NOW_NS, **changes)
    evidence.journal.close()


def test_offline_inspection_is_deterministic_and_read_only():
    cmd = [
        sys.executable,
        "-m",
        "src.research_economic_graph",
        "--pack",
        str(DEFAULT_PACK),
    ]
    first = subprocess.check_output(cmd, text=True)
    assert subprocess.check_output(cmd, text=True) == first
    result = json.loads(first)
    assert (
        result["assets"],
        result["first_campaign_families"],
        result["deepbook_pool_identifiers"],
    ) == (92, 14, 9)
    assert not result["runtime_enabled"] and not result["live_authorization"]
    assert result["hard_bound"] == "BLOCKED_UNTIL_STARTUP_CHAIN_STATE_RECEIPTS"


def exact_request(graph, evidence):
    relation = next(
        r for r in graph.relations.values() if r.relation_id.startswith("qpr03:")
    )
    request = VerificationQueue(graph, evidence).build(
        {relation.relation_id: CandidateScore((("liquidity_change", 10),))},
        top_k=1,
        now_ns=NOW_NS,
    )[0]
    return relation, request


def test_startup_receipt_and_exact_handoff_use_qpr02_and_existing_owners(tmp_path):
    graph, evidence, gate, bundle, calls = asyncio.run(build_lab(tmp_path))
    relation, request = exact_request(graph, evidence)
    sink = exact_sink()
    options = dict(
        binding_id="lab-pool",
        verification_id=bundle,
        input_asset_id="solana-mainnet:LAB_A",
        input_amount=10,
        cursor_offset=0,
    )
    with pytest.raises(ValueError, match="RECEIPTS_REQUIRED"):
        ingest_solana_exact(request, graph, gate, sink, receipt_refs=(), **options)
    assert not sink.publish(now=1002).graph.edges
    refs = gate.startup_receipts(relation, verification_id=bundle, pool_id=address(50))
    assert len(refs) == 2
    records = [
        e["receipt"]
        for e in evidence.replay()
        if e.get("kind") == "gpr_identity_receipt"
    ]
    assert all(
        r["campaign_id"] == evidence.manifest.campaign_id
        and r["repository_sha"] == "a" * 40
        for r in records
    )
    assert all(
        r["decimals"] == 9
        and r["slot"] == 100
        and r["checkpoint"] is None
        and tuple(r["extensions"]) == ()
        for r in records
    )
    quote = ingest_solana_exact(
        request, graph, gate, sink, receipt_refs=refs, **options
    )
    assert (
        quote.input_amount == 10
        and quote.guaranteed_output > 0
        and quote.commitment == "finalized"
    )
    assert quote.source == "qpr02-rooted-direct-state"
    sink.mark_backfill_complete("qpr02-direct")
    snapshot = sink.publish(now=1002)
    assert len(snapshot.graph.edges) == 1 and snapshot.coverage.batch_complete
    assert relation.evidence_state == EvidenceState.DISCOVERY_ONLY
    assert calls.count("radar.test") == 1
    evidence.journal.close()


@pytest.mark.parametrize(
    "fault",
    [
        "single",
        "smoke",
        "correlated",
        "conflict",
        "timeout",
        "429",
        "mint-owner",
        "mint-decimals",
    ],
)
def test_hard_bound_fails_closed_for_all_qpr02_negative_quorum_outcomes(
    tmp_path, fault
):
    graph, evidence, gate, bundle, calls = asyncio.run(
        build_lab(tmp_path, rpc_fault=fault)
    )
    with pytest.raises(ValueError, match="QUORUM_BLOCKED"):
        gate.startup_receipts(
            graph.relations["LAB"], verification_id=bundle, pool_id=address(50)
        )
    assert not any(r.get("kind") == "gpr_identity_receipt" for r in evidence.replay())
    assert any(r.get("kind") == "rpc_observation" for r in evidence.replay())
    evidence.journal.close()


@pytest.mark.parametrize(
    "fault",
    [
        "decimals",
        "program",
        "representation",
        "extensions",
        "deprecated",
        "stale",
        "before-startup",
        "unknown-pool",
        "unretained-proof",
        "policy-generation",
    ],
)
def test_startup_identity_assertions_fail_closed(tmp_path, fault):
    graph, evidence, gate, bundle, calls = asyncio.run(
        build_lab(tmp_path, identity_fault=fault)
    )
    relation = graph.relations["LAB"]
    if fault == "stale":
        gate.wall_ns = lambda: NOW_NS + 46 * 10**9
    elif fault == "before-startup":
        gate.started_at_ns = NOW_NS + 1
        gate.wall_ns = lambda: NOW_NS + 2
    elif fault == "unknown-pool":
        relation = replace(relation, known_pool_or_book_ids=(address(99),))
    elif fault == "unretained-proof":
        bundle = "f" * 64
    elif fault == "policy-generation":
        with pytest.raises(ValueError, match="POLICY_GENERATION"):
            HardBoundIdentityGate(
                gate.registry,
                evidence,
                replace(gate.policy, max_age_ns=1),
                campaign_started_at_ns=1000 * 10**9,
                wall_ns=lambda: NOW_NS,
            )
        evidence.journal.close()
        return
    expected = {
        "decimals": "CHAIN_IDENTITY_PROGRAM_OR_DECIMALS",
        "program": "SEMANTICS_UNQUALIFIED",
        "representation": "REPRESENTATION_RECEIPT_REQUIRED",
        "extensions": "SEMANTICS_UNQUALIFIED",
        "deprecated": "DEPRECATED_OR_REPLACED",
        "stale": "STARTUP_CHAIN_STATE_STALE",
        "before-startup": "STARTUP_CHAIN_STATE_STALE",
        "unknown-pool": "EXACT_POOL_IDENTITY",
        "unretained-proof": "RETAINED_QPR02_DIRECT_STATE",
    }[fault]
    with pytest.raises(ValueError, match=expected):
        gate.startup_receipts(
            relation, verification_id=bundle, pool_id=relation.known_pool_or_book_ids[0]
        )
    evidence.journal.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("decimals", 6),
        ("issuer", "other"),
        ("registry_generation", "f" * 64),
        ("repository_sha", "f" * 40),
        ("pool_or_book_id", address(99)),
        ("slot", 99),
    ],
)
def test_forged_receipt_with_recomputed_hash_cannot_authorize_exact_use(
    tmp_path, field, value
):
    graph, evidence, gate, bundle, calls = asyncio.run(build_lab(tmp_path))
    relation, request = exact_request(graph, evidence)
    refs = gate.startup_receipts(relation, verification_id=bundle, pool_id=address(50))
    original = next(
        e["receipt"]
        for e in evidence.replay()
        if e.get("kind") == "gpr_identity_receipt"
    )
    forged = {**original, field: value}
    forged_ref = evidence.append(
        "gpr-identity",
        {
            "kind": "gpr_identity_receipt",
            "receipt": forged,
            "receipt_hash": digest(forged),
        },
        observed_at_ns=NOW_NS,
    )
    sink = exact_sink()
    with pytest.raises(ValueError, match="RECEIPT_GENERATION_OR_STATE"):
        ingest_solana_exact(
            request,
            graph,
            gate,
            sink,
            receipt_refs=(forged_ref, refs[1]),
            binding_id="lab-pool",
            verification_id=bundle,
            input_asset_id="solana-mainnet:LAB_A",
            input_amount=10,
            cursor_offset=0,
        )
    assert not sink.publish(now=1002).graph.edges
    evidence.journal.close()


def test_hot_crosschain_rebalance_and_sui_never_enter_atomic_graph(tmp_path):
    graph = full_graph()
    base_policy = StartupIdentityPolicy(
        (
            IdentityExpectation(
                "solana-mainnet:USDC",
                digest(graph.registry.resolve("solana-mainnet:USDC").representation),
                6,
                ("reviewed",),
            ),
        )
    )
    evidence = CampaignEvidenceStore(
        RecoverableStreamJournal(tmp_path / "cross.sqlite"),
        make_manifest(graph, policy=base_policy),
        wall_ns=lambda: NOW_NS,
    )
    gate = HardBoundIdentityGate(
        graph.registry,
        evidence,
        base_policy,
        campaign_started_at_ns=1000 * 10**9,
        wall_ns=lambda: NOW_NS,
    )
    relations = (
        graph.relations["F14"],
        replace(graph.relations["F14"], execution_class=ExecutionClass.REBALANCE_ONLY),
        replace(graph.relations["F07"], execution_class=ExecutionClass.LOCAL_ATOMIC),
    )
    for relation in relations:
        with pytest.raises(ValueError, match="NON_ATOMIC_OR_UNSUPPORTED"):
            gate.startup_receipts(
                relation, verification_id="f" * 64, pool_id=address(50)
            )
    queue = VerificationQueue(graph, evidence).build({}, top_k=32, now_ns=NOW_NS)
    assert any(
        r.target == VerificationTarget.SUI_GOVERNED_CHECKPOINT_OBJECT for r in queue
    )
    assert all(
        r.target == VerificationTarget.CROSS_CHAIN_RESEARCH
        for r in queue
        if r.relation_id == "F14"
    )
    evidence.journal.close()


def test_replay_rejects_journal_corruption(tmp_path):
    graph = full_graph()
    journal = RecoverableStreamJournal(tmp_path / "corrupt.sqlite")
    evidence = CampaignEvidenceStore(
        journal, make_manifest(graph), wall_ns=lambda: NOW_NS
    )
    graph.persist(evidence, observed_at_ns=NOW_NS)
    row = journal.db.execute(
        "SELECT identity,payload FROM raw_stream_events WHERE source='gpr-graph'"
    ).fetchone()
    payload = json.loads(row[1])
    payload["payload_json"] = "{}"
    journal.db.execute(
        "UPDATE raw_stream_events SET payload=? WHERE identity=?",
        (json.dumps(payload), row[0]),
    )
    journal.db.commit()
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        ResearchEconomicGraph.replay(evidence, graph.registry, graph.seed)
    journal.close()


def test_gpr_composition_imports_no_signer_sender_or_submission():
    code = """
import sys
import src.research_economic_graph
bad = [name for name in sys.modules if name.startswith(('src.execution.senders', 'src.signer', 'isolated_signer_service'))]
assert not bad, bad
"""
    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        cwd=Path(__file__).resolve().parents[1],
    )
