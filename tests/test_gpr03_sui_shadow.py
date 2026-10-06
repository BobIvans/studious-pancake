"""Deterministic Sui shadow tests. Fixture bytes are not mainnet qualification."""

import asyncio
from contextlib import asynccontextmanager
import base64
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from src.gpr_sui_shadow.bcs import metadata_decimals
from src.gpr_sui_shadow.campaign import default_profiles
from src.gpr_sui_shadow.intake import (
    CapturedJsonTransport,
    SuiIntakePlane,
    ingest_research,
    validate_capture,
)
from src.gpr_sui_shadow.models import (
    SuiCandidate,
    SuiSourceProfile,
    SuiReadRequest,
    coin_type,
)
from src.gpr_sui_shadow.sources import (
    PoolIndexAdapter,
    ScallopRateAdapter,
    checkpoint_request,
    object_request,
    residual_bps,
)
from src.gpr_sui_shadow.verification import (
    DecodedPoolState,
    RepresentationProof,
    SuiVerificationPolicy,
    SuiHardBoundGate,
    decoder_fingerprint,
)
from src.market.streams import RecoverableStreamJournal
from src.provider_governance import ProviderGovernance
from src.qualification_campaign.evidence import CampaignEvidenceStore
from src.qualification_campaign.identity import CampaignManifest, digest
from src.qualification_campaign.sources import Candidate
from src.research_economic_graph import (
    AssetRegistry,
    CampaignSeed,
    ResearchEconomicGraph,
    VerificationQueue,
    IdentityExpectation,
    StartupIdentityPolicy,
    ExecutionClass,
    EvidenceState,
    Heat,
)
from src.research_economic_graph.registry import DEFAULT_PACK
from src.routing.transport import TransportPolicy

NOW = 1002 * 10**9


def profile(index, kind="graphql", **changes):
    return replace(
        SuiSourceProfile(
            "sui-test-" + str(index),
            "provider-" + str(index),
            "operator-" + str(index),
            "independent-" + str(index),
            "https://sui" + str(index) + ".test/graphql",
            "https://docs.sui.io/test",
            "a" * 64,
            "POST" if kind == "graphql" else "GET",
            "checkpoint" if kind == "graphql" else "pool-index",
            kind,
            smoke_only=False,
        ),
        **changes,
    )


def corpus():
    registry = AssetRegistry.load(DEFAULT_PACK / "ASSET_REGISTRY_V2.json")
    seed = CampaignSeed.load(registry, DEFAULT_PACK)
    return registry, seed


def candidate_for(registry, seed):
    pool = next(
        p for p in seed.pools if any("WUSDC_ETH_ORIGIN" in r for r in p.representations)
    )
    return SuiCandidate(
        pool.canonical_object_id,
        tuple(registry.resolve(r).canonical_identifier for r in pool.representations),
        "deepbook",
    )


def metadata_bcs(address, decimals):
    return bytes.fromhex(address[2:]) + bytes([decimals]) + b"\x04coin\x03USD\x00\x00"


def object_payload(candidate):
    state = {
        "coin_types": candidate.coin_types,
        "decimals": [6, 6],
        "bid_depth_units": 100,
        "ask_depth_units": 200,
        "taker_fee_numerator": 1,
        "fee_denominator": 1000,
        "lot_size": 1,
        "tick_size": 1,
        "fee_semantics": "FIXTURE_INLINE_NO_PRODUCTION_DECODER",
    }
    tag = "0x" + "3" * 64 + "::pool::Pool<" + ",".join(candidate.coin_types) + ">"
    obj = {
        "address": candidate.pool_id,
        "version": 10,
        "digest": "object-digest",
        "asMoveObject": {
            "contents": {
                "type": {"repr": tag},
                "json": state,
                "bcs": base64.b64encode(
                    json.dumps(state, sort_keys=True).encode()
                ).decode(),
            }
        },
    }
    scoped = {"object": obj}
    for i, (alias, t) in enumerate(zip(("a", "b"), candidate.coin_types, strict=True)):
        address = "0x" + str(i + 4) * 64
        scoped[alias] = {
            "address": address,
            "version": 2,
            "digest": "metadata-digest-" + alias,
            "decimals": 6,
            "contents": {
                "type": {"repr": "0x2::coin::CoinMetadata<" + t + ">"},
                "json": {"decimals": 6},
                "bcs": base64.b64encode(metadata_bcs(address, 6)).decode(),
            },
        }
    return {
        "data": {
            "chainIdentifier": "reviewed-fixture-mainnet-id",
            "checkpoint": {
                "sequenceNumber": 100,
                "digest": "checkpoint-digest",
                "epoch": {"epochId": 1},
                "timestamp": datetime.fromtimestamp(1001, UTC).isoformat(),
                "query": scoped,
            },
        }
    }


class FixtureDecoder:
    code_sha256 = "f" * 64

    def decode(self, checkpoint, obj, bcs):
        state = json.loads(bcs)
        h = hashlib.sha256(bcs).hexdigest()
        return DecodedPoolState(
            obj["address"],
            obj["version"],
            checkpoint["sequenceNumber"],
            obj["asMoveObject"]["contents"]["type"]["repr"],
            tuple(state.pop("coin_types")),
            tuple(state.pop("decimals")),
            **state,
            state_bcs_sha256=h,
            depth_bcs_sha256=h,
            fee_bcs_sha256=h,
            metadata_bcs_sha256=tuple(
                hashlib.sha256(
                    base64.b64decode(checkpoint["query"][a]["contents"]["bcs"])
                ).hexdigest()
                for a in ("a", "b")
            ),
        )


def setup(tmp_path, profiles, *, mutate=None, ip_changes=None, policy_changes=None):
    registry, seed = corpus()
    graph = ResearchEconomicGraph(registry, seed)
    candidate = candidate_for(registry, seed)
    refs = tuple(
        registry.by_identifier("sui-mainnet", t).asset_id for t in candidate.coin_types
    )
    source = "https://proof.test/issuer#sha256=" + "b" * 64
    ip = StartupIdentityPolicy(
        tuple(
            IdentityExpectation(
                r, digest(registry.resolve(r).representation), 6, (source,)
            )
            for r in refs
        )
    )
    if ip_changes:
        ip = ip_changes(ip)
    proofs = tuple(
        RepresentationProof(
            r,
            digest(registry.resolve(r).representation),
            "Circle",
            "ethereum" if "WUSDC" in r else "sui",
            "wormhole" if "WUSDC" in r else None,
            (source,),
        )
        for r in refs
    )
    policy = SuiVerificationPolicy(
        "reviewed-fixture-mainnet-id",
        ip.generation,
        decoder_fingerprint(FixtureDecoder()),
        proofs,
        (
            (
                candidate.venue,
                object_payload(candidate)["data"]["checkpoint"]["query"]["object"][
                    "asMoveObject"
                ]["contents"]["type"]["repr"],
            ),
        ),
    )
    if policy_changes:
        policy = policy_changes(policy)
    manifest = CampaignManifest(
        "a" * 40,
        "b" * 40,
        "c" * 64,
        (
            ("gpr.registry", registry.generation),
            ("gpr.seed", seed.generation),
            ("gpr.identity_policy", ip.generation),
            ("gpr03.sui_verification", policy.generation),
        ),
        tuple({p.profile_id: p.generation for p in profiles}.items()),
    )
    journal = RecoverableStreamJournal(tmp_path / "journal.sqlite")
    evidence = CampaignEvidenceStore(journal, manifest, wall_ns=lambda: NOW)

    async def collect():
        retained = []
        for index, p in enumerate(profiles):
            payload = object_payload(candidate)
            if mutate:
                mutate(payload, index)
            client = httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda req: httpx.Response(200, json=payload)
                ),
                trust_env=False,
            )
            transport = CapturedJsonTransport(
                policy=TransportPolicy(max_attempts=1),
                allowed_hosts={p.hostname},
                client=client,
            )
            gov = ProviderGovernance(
                {p.profile_id: p.entitlement(2000)},
                clock=lambda: 1002,
                wall_clock=lambda: 1002,
            )
            intake = SuiIntakePlane(gov, transport, evidence, wall_ns=lambda: NOW)
            raw_ref, raw = await intake.collect(
                p, object_request(p.endpoint, candidate, 100)
            )
            assert raw["quality"] == "accepted-read-only"
            retained.append(raw_ref)
            await client.aclose()
        return tuple(retained)

    captures = asyncio.run(collect())
    requests = VerificationQueue(graph, evidence).build(
        {},
        top_k=32,
        per_chain_budget={"sui-mainnet": 32, "solana-mainnet": 0},
        now_ns=NOW,
    )
    request = next(
        r
        for r in requests
        if candidate.pool_id in r.pool_or_book_ids
        and set(r.representations) == set(refs)
    )
    gate = SuiHardBoundGate(
        graph,
        evidence,
        ip,
        policy,
        FixtureDecoder(),
        started_at_ns=1000 * 10**9,
        wall_ns=lambda: NOW,
    )
    return gate, evidence, candidate, captures, request


def test_positive_independent_fixture_receipts_reconstruct_and_remain_shadow(tmp_path):
    gate, evidence, candidate, captures, request = setup(
        tmp_path, (profile(1), profile(2))
    )
    verification_ref, receipt_refs = gate.qualify(request, candidate, captures)
    state = gate.require_receipts(request, candidate, verification_ref, receipt_refs)
    assert state.checkpoint == 100 and state.object_version == 10
    rows = evidence.replay()
    assert all(r.get("exact_graph_allowed") is not True for r in rows)
    receipts = [
        r["receipt"] for r in rows if r.get("kind") == "gpr03_sui_identity_receipt"
    ]
    assert len(receipts) == 2 and all(
        r["slot"] is None and r["checkpoint"] == 100 for r in receipts
    )
    assert request.heat == Heat.HOT
    assert all(
        r.evidence_state != EvidenceState.EXECUTABLE
        for r in gate.graph.relations.values()
    )


@pytest.mark.parametrize(
    "field", ["profile_id", "provider", "operator", "correlation_group"]
)
def test_correlated_quorum_fails_closed(tmp_path, field):
    first, second = profile(1), profile(2)
    if field == "profile_id":
        gate, evidence, candidate, captures, request = setup(tmp_path, (first, first))
    else:
        gate, evidence, candidate, captures, request = setup(
            tmp_path, (first, replace(second, **{field: getattr(first, field)}))
        )
    with pytest.raises(ValueError, match="CORRELATED"):
        gate.qualify(request, candidate, captures)


@pytest.mark.parametrize("field", ["provider", "operator", "correlation_group"])
def test_cosmetic_provider_case_and_whitespace_never_supply_independence(
    tmp_path, field
):
    first = profile(1, **{field: "MystenLabs"})
    second = profile(2, **{field: "mystenlabs"})
    gate, _, candidate, captures, request = setup(tmp_path, (first, second))
    with pytest.raises(ValueError, match="CORRELATED"):
        gate.qualify(request, candidate, captures)
    with pytest.raises(ValueError, match="CANONICAL"):
        profile(3, **{field: " mystenlabs "})


@pytest.mark.parametrize(
    "failure",
    [
        "network",
        "checkpoint",
        "digest",
        "version",
        "pool",
        "coin-type",
        "coin-program",
        "decimals",
        "bcs-decimals",
        "bcs-uid",
        "empty-bcs",
        "future",
        "stale",
        "disagreement",
    ],
)
def test_exact_state_fail_closed(tmp_path, failure):
    def mutate(payload, index):
        cp = payload["data"]["checkpoint"]
        obj = cp["query"]["object"]
        meta = cp["query"]["a"]
        if failure == "network":
            payload["data"]["chainIdentifier"] = "wrong-network"
        elif failure == "checkpoint":
            cp["sequenceNumber"] = 101
        elif failure == "digest":
            cp["digest"] = ""
        elif failure == "version":
            obj["version"] = 0
        elif failure == "pool":
            obj["address"] = "0x" + "9" * 64
        elif failure == "coin-type":
            meta["contents"]["type"]["repr"] = "0x2::coin::CoinMetadata<0x2::sui::SUI>"
        elif failure == "coin-program":
            meta["contents"]["type"]["repr"] = meta["contents"]["type"]["repr"].replace(
                "0x2::coin", "0x999::coin"
            )
        elif failure == "decimals":
            meta["decimals"] = 7
        elif failure == "bcs-decimals":
            meta["decimals"] = 7
            meta["contents"]["bcs"] = base64.b64encode(
                metadata_bcs(meta["address"], 7)
            ).decode()
        elif failure == "bcs-uid":
            meta["contents"]["bcs"] = base64.b64encode(
                metadata_bcs("0x" + "9" * 64, 6)
            ).decode()
        elif failure == "empty-bcs":
            obj["asMoveObject"]["contents"]["bcs"] = ""
        elif failure == "future":
            cp["timestamp"] = datetime.fromtimestamp(1003, UTC).isoformat()
        elif failure == "stale":
            cp["timestamp"] = datetime.fromtimestamp(900, UTC).isoformat()
        elif failure == "disagreement" and index == 1:
            obj["version"] = 11

    gate, evidence, candidate, captures, request = setup(
        tmp_path, (profile(1), profile(2)), mutate=mutate
    )
    with pytest.raises(ValueError):
        gate.qualify(request, candidate, captures)
    assert not any(
        r.get("kind") == "gpr03_sui_identity_receipt" for r in evidence.replay()
    )


@pytest.mark.parametrize(
    "failure",
    [
        "smoke",
        "one-provider",
        "different-campaign",
        "different-graph",
        "cross-chain",
        "rebalance",
        "wrong-target",
        "missing-proof",
        "missing-origin",
        "wrong-issuer",
        "wrong-decimals",
        "deprecated",
        "wrong-venue-type",
        "missing-decoder",
    ],
)
def test_authority_fail_closed(tmp_path, failure):
    profiles = (profile(1, smoke_only=failure == "smoke"), profile(2))
    ip_changes = None
    policy_changes = None
    if failure == "missing-proof":
        policy_changes = lambda p: replace(p, representation_proofs=())
    if failure == "missing-origin":
        policy_changes = lambda p: replace(
            p,
            representation_proofs=tuple(
                replace(r, origin_chain=None) for r in p.representation_proofs
            ),
        )
    if failure == "wrong-issuer":
        policy_changes = lambda p: replace(
            p,
            representation_proofs=tuple(
                replace(r, bridge="wrong") for r in p.representation_proofs
            ),
        )
    if failure == "wrong-decimals":
        ip_changes = lambda p: replace(
            p, expectations=tuple(replace(r, decimals=7) for r in p.expectations)
        )
    if failure == "deprecated":
        ip_changes = lambda p: replace(
            p,
            expectations=tuple(
                replace(r, deprecation_state="REPLACED") for r in p.expectations
            ),
        )
    if failure == "wrong-venue-type":
        policy_changes = lambda p: replace(
            p, venue_move_types=(("deepbook", "0x9::pool::Pool"),)
        )
    gate, evidence, candidate, captures, request = setup(
        tmp_path, profiles, ip_changes=ip_changes, policy_changes=policy_changes
    )
    if failure == "one-provider":
        captures = captures[:1]
    if failure == "different-campaign":
        request = replace(request, campaign_id="d" * 64)
    if failure == "different-graph":
        request = replace(request, graph_identity="d" * 64)
    if failure == "cross-chain":
        request = replace(request, execution_class=ExecutionClass.CROSS_CHAIN_SIGNAL)
    if failure == "rebalance":
        request = replace(request, execution_class=ExecutionClass.REBALANCE_ONLY)
    if failure == "wrong-target":
        request = replace(request, target="SOLANA_QPR02_DIRECT_STATE")
    if failure == "missing-decoder":
        with pytest.raises(ValueError, match="DECODER"):
            SuiHardBoundGate(
                gate.graph,
                evidence,
                gate.identity_policy,
                gate.policy,
                None,
                started_at_ns=1000 * 10**9,
                wall_ns=lambda: NOW,
            )
    else:
        with pytest.raises(ValueError):
            gate.qualify(request, candidate, captures)


@pytest.mark.parametrize(
    "outcome",
    [
        "200",
        "empty",
        "403",
        "429",
        "503",
        "invalid-json",
        "timeout",
        "drift",
        "cancelled",
    ],
)
def test_physical_attempt_negative_raw_evidence_budget_and_replay(tmp_path, outcome):
    async def run():
        p = profile(1, "deepbook", campaign_attempt_cap=1)
        registry, seed = corpus()
        candidate = candidate_for(registry, seed)
        payload = [
            {
                "pool_id": candidate.pool_id,
                "base_asset_id": candidate.coin_types[0],
                "quote_asset_id": candidate.coin_types[1],
            }
        ]

        def handler(req):
            if outcome == "timeout":
                raise httpx.ReadTimeout("hidden-details", request=req)
            if outcome == "cancelled":
                raise asyncio.CancelledError()
            if outcome == "invalid-json":
                return httpx.Response(403, text="Forbidden by proxy")
            return httpx.Response(
                int(outcome) if outcome.isdigit() else 200,
                json=(
                    []
                    if outcome == "empty"
                    else {"schema": "changed"} if outcome == "drift" else payload
                ),
            )

        manifest = CampaignManifest(
            "a" * 40,
            "b" * 40,
            "c" * 64,
            (("gpr.registry", registry.generation), ("gpr.seed", seed.generation)),
            ((p.profile_id, p.generation),),
        )
        journal = RecoverableStreamJournal(tmp_path / "events.sqlite")
        evidence = CampaignEvidenceStore(journal, manifest, wall_ns=lambda: NOW)
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False
        )
        transport = CapturedJsonTransport(
            policy=TransportPolicy(max_attempts=1),
            allowed_hosts={p.hostname},
            client=client,
        )
        gov = ProviderGovernance(
            {p.profile_id: p.entitlement(2000)},
            clock=lambda: 1002,
            wall_clock=lambda: 1002,
        )
        plane = SuiIntakePlane(gov, transport, evidence, wall_ns=lambda: NOW)
        request = SuiReadRequest("GET", p.endpoint, "pool-index")
        if outcome == "cancelled":
            with pytest.raises(asyncio.CancelledError):
                await plane.collect(p, request, PoolIndexAdapter("deepbook"))
            ref = next(
                e.identity
                for e in journal.events(available_at_ns=2**63 - 1)
                if evidence.expand(e.payload_json).get("kind") == "gpr03_sui_raw"
            )
            raw = validate_capture(evidence, ref)
        else:
            ref, raw = await plane.collect(p, request, PoolIndexAdapter("deepbook"))
        assert raw["physical_attempt_started"]
        if outcome == "invalid-json":
            assert base64.b64decode(raw["wire_payload_base64"]) == b"Forbidden by proxy"
            assert raw["http_status"] == 403
        graph = ingest_research(ResearchEconomicGraph(registry, seed), evidence)
        if outcome == "200":
            relation = graph.relations["gpr03:" + candidate.identity]
            assert (
                relation.execution_class == ExecutionClass.LOCAL_SIGNAL
                and relation.evidence_state == EvidenceState.DISCOVERY_ONLY
            )
        before = evidence.head
        assert (
            ingest_research(ResearchEconomicGraph(registry, seed), evidence).identity
            == graph.identity
        )
        assert evidence.head == before
        graph.persist(evidence, observed_at_ns=NOW)
        assert (
            ResearchEconomicGraph.replay(evidence, registry, seed).identity
            == graph.identity
        )
        _, denied = await plane.collect(p, request, PoolIndexAdapter("deepbook"))
        assert (
            denied["quality"] == "schema-or-admission-error"
            and not denied["physical_attempt_started"]
        )
        assert sum(r.get("kind") == "attempt" for r in evidence.replay()) == 1
        await client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "mutation",
    ["asset", "decimals", "state", "campaign", "policy", "future", "duplicate"],
)
def test_rehashed_or_missing_receipts_never_qualify(tmp_path, mutation):
    gate, evidence, candidate, captures, request = setup(
        tmp_path, (profile(1), profile(2))
    )
    ref, receipt_refs = gate.qualify(request, candidate, captures)
    rows = {
        e.identity: evidence.expand(e.payload_json)
        for e in evidence.journal.events(available_at_ns=2**63 - 1)
    }
    raw = deepcopy(rows[receipt_refs[0]])
    if mutation == "asset":
        raw["receipt"]["asset_id"] = "sui-mainnet:SUI"
    elif mutation == "decimals":
        raw["receipt"]["decimals"] = 9
    elif mutation == "state":
        raw["receipt"]["state_hash"] = "d" * 64
    elif mutation == "campaign":
        raw["receipt"]["campaign_id"] = "d" * 64
    elif mutation == "policy":
        raw["sui_verification_policy_generation"] = "d" * 64
    elif mutation == "future":
        raw["receipt"]["checked_at_ns"] = NOW + 1
    raw["receipt_hash"] = digest(raw["receipt"])
    replacement = evidence.append("gpr03-identity", raw, observed_at_ns=NOW)
    refs = (
        (replacement, receipt_refs[1])
        if mutation != "duplicate"
        else (receipt_refs[0], receipt_refs[0])
    )
    with pytest.raises(ValueError):
        gate.require_receipts(request, candidate, ref, refs)


def test_scoped_profiles_sources_no_production_credentials_and_focus_corpus():
    pins = json.loads(Path("config/gpr03_sui_source_pins.json").read_text())
    profiles = default_profiles(pins)
    assert len(profiles) == 8 and all(
        p.smoke_only and p.campaign_attempt_cap in (1, 12) for p in profiles
    )
    assert (
        next(p for p in profiles if p.source_kind == "aftermath").max_response_bytes
        == 2_097_152
    )
    assert all(
        p.max_response_bytes == 1_048_576
        for p in profiles
        if p.source_kind != "aftermath"
    )
    assert all(p.credential_ref == "anonymous-public-read" for p in profiles)
    registry, seed = corpus()
    assert len(seed.pools) == 9
    required = (
        "WUSDC_ETH_ORIGIN",
        "USDC_NATIVE",
        "USDT_WORMHOLE",
        "USDT_SUI_BRIDGE",
        "suiUSDe",
        "USDSUI",
        "XBTC",
        "ZWBTC",
        "sSUI",
        "afSUI",
        "haSUI",
        "vSUI",
        "scaSUI",
        "XAUM",
        "USDC_SOL_PORTAL_ON_SUI",
    )
    for asset in required:
        assert registry.resolve("sui-mainnet:" + asset).canonical_identifier
    for transform in seed.transformations:
        relation = transform.relation()
        if relation:
            assert relation.execution_class in (
                ExecutionClass.CROSS_CHAIN_SIGNAL,
                ExecutionClass.REBALANCE_ONLY,
            )


def test_sui_never_weakens_existing_solana_candidate_boundary():
    registry, seed = corpus()
    candidate = candidate_for(registry, seed)
    with pytest.raises(ValueError):
        Candidate(
            candidate.pool_id, candidate.coin_types, "deepbook", chain="sui-mainnet"
        )
    with pytest.raises(ValueError):
        SuiReadRequest(
            "POST",
            "https://state.test/graphql",
            "checkpoint",
            body={"query": "mutation Send { execute }"},
        )


@pytest.mark.parametrize("value", [0, -1, "NaN", "Infinity", True, None])
def test_invalid_structural_rates_fail_closed(value):
    candidates, rates, rejections = ScallopRateAdapter().normalize(
        {"pools": [{"coinType": "0x2::sui::SUI", "conversionRate": value}]}
    )
    assert not candidates and not rates and rejections


def test_structural_rates_and_integer_residual_keep_provenance_distinct():
    _, rates, rejected = ScallopRateAdapter().normalize(
        {
            "updatedAt": "1001",
            "pools": [
                {
                    "coinType": "0x2::sui::SUI",
                    "conversionRate": "1.125",
                    "supplyApy": "0.05",
                }
            ],
        }
    )
    assert (
        not rejected
        and len(rates) == 2
        and rates[0].rate_numerator == 9
        and rates[0].rate_denominator == 8
    )
    assert all(r.exact_state_ready is False for r in rates)
    assert residual_bps(102, 100, 1, 1) == 200


def test_zero_apy_is_valid_without_becoming_a_staking_exchange_rate():
    _, rates, rejected = ScallopRateAdapter().normalize(
        {
            "pools": [
                {
                    "coinType": "0x2::sui::SUI",
                    "supplyApy": 0,
                    "borrowApy": "0.0",
                    "conversionRate": 0,
                }
            ]
        }
    )
    assert {r.rate_kind for r in rates} == {"supplyApy", "borrowApy"}
    assert all(r.rate_numerator == 0 and r.rate_denominator == 1 for r in rates)
    assert rejected == {"rate-or-exact-coin-type-invalid": 1}


def test_deployed_cetus_lp_list_schema_from_retained_first_campaign():
    registry, seed = corpus()
    candidate = candidate_for(registry, seed)
    payload = {
        "code": 0,
        "msg": "success",
        "data": {
            "total": 1,
            "lp_list": [
                {
                    "address": candidate.pool_id,
                    "coin_a_address": candidate.coin_types[0],
                    "coin_b_address": candidate.coin_types[1],
                }
            ],
        },
    }
    candidates, rates, rejected = PoolIndexAdapter("cetus").normalize(payload)
    assert not rates and not rejected and len(candidates) == 1
    assert candidates[0].pool_id == candidate.pool_id and candidates[0].venue == "cetus"


def test_scallop_object_values_shape_retains_structural_rates_without_symbol_alias():
    _, rates, rejected = ScallopRateAdapter().normalize(
        {
            "pools": {
                "sui": {
                    "coinType": "0x2::sui::SUI",
                    "conversionRate": "1.1",
                    "supplyApy": 0,
                }
            }
        }
    )
    assert not rejected and len(rates) == 2


@pytest.mark.parametrize("suffix", [b"\x00", b"\x80", b"\xff" * 8])
def test_metadata_bcs_trailing_or_malformed_is_rejected(suffix):
    address = "0x" + "4" * 64
    with pytest.raises(ValueError):
        metadata_decimals(
            metadata_bcs(address, 6) + suffix,
            address=address,
            tag="0x2::coin::CoinMetadata<0x2::sui::SUI>",
            expected_coin_type="0x2::sui::SUI",
        )


def test_source_adapter_relabel_fails_before_network(tmp_path):
    gate, evidence, candidate, captures, request = setup(
        tmp_path, (profile(1), profile(2))
    )
    p = profile(1)
    with pytest.raises(ValueError, match="ADAPTER"):

        async def run():
            transport = CapturedJsonTransport(
                policy=TransportPolicy(max_attempts=1), allowed_hosts={p.hostname}
            )
            gov = ProviderGovernance(
                {p.profile_id: p.entitlement(2000)},
                clock=lambda: 1002,
                wall_clock=lambda: 1002,
            )
            await SuiIntakePlane(gov, transport, evidence, wall_ns=lambda: NOW).collect(
                p,
                object_request(p.endpoint, candidate, 100),
                PoolIndexAdapter("deepbook"),
            )

        asyncio.run(run())


def test_overlapping_reads_share_transport_without_crossing_wire_evidence(tmp_path):
    async def run():
        registry, seed = corpus()
        candidate = candidate_for(registry, seed)
        profiles = (profile(1, "deepbook"), profile(2, "deepbook"))
        manifest = CampaignManifest(
            "a" * 40,
            "b" * 40,
            "c" * 64,
            (("gpr.registry", registry.generation), ("gpr.seed", seed.generation)),
            tuple((p.profile_id, p.generation) for p in profiles),
        )
        journal = RecoverableStreamJournal(tmp_path / "overlap.sqlite")
        evidence = CampaignEvidenceStore(journal, manifest, wall_ns=lambda: NOW)
        active = 0
        maximum_active = 0

        async def handler(req):
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(active, maximum_active)
            await asyncio.sleep(0)
            payload = [
                {
                    "pool_id": candidate.pool_id,
                    "base_asset_id": candidate.coin_types[0],
                    "quote_asset_id": candidate.coin_types[1],
                    "origin_host": req.url.host,
                }
            ]
            active -= 1
            return httpx.Response(200, json=payload)

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False
        )
        transport = CapturedJsonTransport(
            policy=TransportPolicy(max_attempts=1),
            allowed_hosts={p.hostname for p in profiles},
            client=client,
        )
        gov = ProviderGovernance(
            {p.profile_id: p.entitlement(2000) for p in profiles},
            clock=lambda: 1002,
            wall_clock=lambda: 1002,
        )
        planes = [
            SuiIntakePlane(gov, transport, evidence, wall_ns=lambda: NOW)
            for _ in profiles
        ]
        results = await asyncio.gather(
            *(
                plane.collect(
                    p,
                    SuiReadRequest("GET", p.endpoint, "pool-index"),
                    PoolIndexAdapter("deepbook"),
                )
                for plane, p in zip(planes, profiles, strict=True)
            )
        )
        assert maximum_active == 1
        for p, (ref, _) in zip(profiles, results, strict=True):
            raw = validate_capture(evidence, ref)
            assert (
                json.loads(base64.b64decode(raw["wire_payload_base64"]))
                == raw["raw_payload"]
            )
            assert raw["raw_payload"][0]["origin_host"] == p.hostname
        await client.aclose()

    asyncio.run(run())


def test_complete_negative_slice_has_portable_offline_replay(tmp_path, monkeypatch):
    from src.gpr_sui_shadow import campaign as runner

    def factory(root, *, main_sha, configuration, sources):
        return CampaignManifest(
            "a" * 40,
            main_sha,
            "c" * 64,
            tuple((k, digest(v)) for k, v in configuration.items()),
            tuple((k, digest(v)) for k, v in sources.items()),
        )

    monkeypatch.setattr(CampaignManifest, "create", factory)

    @asynccontextmanager
    async def transport_factory(hosts, environment):
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(403, text="Forbidden")
            ),
            trust_env=False,
        )
        transport = CapturedJsonTransport(
            policy=TransportPolicy(max_attempts=1), allowed_hosts=hosts, client=client
        )
        try:
            yield transport
        finally:
            await client.aclose()

    monkeypatch.setattr(runner, "sui_transport", transport_factory)
    output = tmp_path / "capture"
    summary = asyncio.run(runner.capture(Path.cwd(), DEFAULT_PACK, output))
    assert summary["physical_attempts"] == 5 and summary["reserved_attempts"] == 5
    assert (
        summary["qualification_receipts"] == 0 and summary["measured_anomalies"] is None
    )
    assert len(summary["deepbook_qualification_gaps"]) == 9
    replay = runner.replay_capture(output, tmp_path / "replay")
    assert replay["replay_identical"] and replay["network_reads"] == 0
    retained = output / "retained-evidence.json"
    retained.write_bytes(retained.read_bytes() + b" ")
    with pytest.raises(ValueError, match="EXPORT_HASH"):
        runner.replay_capture(output, tmp_path / "tampered-replay")


@pytest.mark.parametrize("durable", [False, True])
def test_shared_mysten_quota_generation_and_aggregate_attempt_cap(tmp_path, durable):
    from src.durability.unified_authority_pr02 import UnifiedLifecycleAuthority
    import time

    async def run():
        registry, seed = corpus()
        pins = json.loads(Path("config/gpr03_sui_source_pins.json").read_text())
        selected = [p for p in default_profiles(pins) if p.provider == "mystenlabs"]
        profiles = tuple(replace(p, request_limit=2) for p in selected)
        assert len({p.generation for p in profiles}) == len(profiles)
        assert len({p.quota_generation for p in profiles}) == 1
        manifest = CampaignManifest(
            "a" * 40,
            "b" * 40,
            "c" * 64,
            (("gpr.registry", registry.generation), ("gpr.seed", seed.generation)),
            tuple((p.profile_id, p.generation) for p in profiles),
        )
        evidence = CampaignEvidenceStore(
            RecoverableStreamJournal(tmp_path / "quota-events.sqlite"), manifest
        )
        store = (
            UnifiedLifecycleAuthority(
                tmp_path / "quota-authority.sqlite",
                release_digest="d" * 64,
                policy_bundle_hash="e" * 64,
            )
            if durable
            else None
        )
        physical = []
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: physical.append(request) or httpx.Response(200, json={})
            ),
            trust_env=False,
        )
        transport = CapturedJsonTransport(
            policy=TransportPolicy(max_attempts=1),
            allowed_hosts={p.hostname for p in profiles},
            client=client,
        )
        entitlements = {
            p.profile_id: p.entitlement(int(time.time()) + 3600) for p in profiles
        }
        gov = ProviderGovernance(entitlements, store=store)
        plane = SuiIntakePlane(gov, transport, evidence)
        # Distinct exact endpoints and source generations spend the same physical
        # quota, including the GraphQL checkpoint source on another host.
        reads = [
            (
                profiles[1],
                SuiReadRequest(
                    "GET",
                    profiles[1].endpoint,
                    "book-reference",
                    params=(("depth", "20"), ("level", "2")),
                ),
            ),
            (profiles[-1], checkpoint_request(profiles[-1].endpoint)),
            (
                profiles[2],
                SuiReadRequest(
                    "GET",
                    profiles[2].endpoint,
                    "book-reference",
                    params=(("depth", "20"), ("level", "2")),
                ),
            ),
        ]
        captures = [await plane.collect(p, req) for p, req in reads]
        assert [r[1]["quality"] for r in captures] == [
            "accepted-read-only",
            "accepted-read-only",
            "quota-or-admission-denied",
        ]
        assert captures[-1][1]["error_code"] == "request_quota_exhausted"
        assert len(physical) == 2 and not captures[-1][1]["physical_attempt_started"]
        for p in profiles:
            assert (await gov.authority.snapshot(p.profile_id))[
                "committed_requests"
            ] == 2
        if durable:
            # A fresh wrapper must recover the shared pool and deny before send.
            restarted = ProviderGovernance(entitlements, store=store)
            _, raw = await SuiIntakePlane(
                restarted,
                CapturedJsonTransport(
                    policy=TransportPolicy(max_attempts=1),
                    allowed_hosts={p.hostname for p in profiles},
                    client=client,
                ),
                evidence,
            ).collect(
                profiles[3],
                SuiReadRequest(
                    "GET",
                    profiles[3].endpoint,
                    "book-reference",
                    params=(("depth", "20"), ("level", "2")),
                ),
            )
            assert raw["error_code"] == "request_quota_exhausted"
            assert len(physical) == 2
            store.close()
        await client.aclose()

    asyncio.run(run())


def test_supported_content_encoding_is_pinned_on_physical_request(tmp_path):
    async def run():
        registry, seed = corpus()
        pins = json.loads(Path("config/gpr03_sui_source_pins.json").read_text())
        p = next(p for p in default_profiles(pins) if p.source_kind == "scallop")
        manifest = CampaignManifest(
            "a" * 40,
            "b" * 40,
            "c" * 64,
            (("gpr.registry", registry.generation), ("gpr.seed", seed.generation)),
            ((p.profile_id, p.generation),),
        )
        evidence = CampaignEvidenceStore(
            RecoverableStreamJournal(tmp_path / "encoding.sqlite"), manifest
        )

        def handler(req):
            assert req.headers["accept-encoding"] == "gzip,deflate,identity"
            return httpx.Response(
                200, json={"pools": [{"coinType": "0x2::sui::SUI", "supplyApy": "0"}]}
            )

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False
        )
        transport = CapturedJsonTransport(
            policy=TransportPolicy(max_attempts=1),
            allowed_hosts={p.hostname},
            client=client,
        )
        gov = ProviderGovernance(
            {p.profile_id: p.entitlement(2000)},
            clock=lambda: 1002,
            wall_clock=lambda: 1002,
        )
        _, raw = await SuiIntakePlane(gov, transport, evidence).collect(
            p,
            SuiReadRequest("GET", p.endpoint, "structural-rates"),
            ScallopRateAdapter(),
        )
        assert (
            raw["quality"] == "accepted"
            and raw["sent_accept_encoding"] == "gzip,deflate,identity"
        )
        assert raw["content_encoding"] == "identity"
        await client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "failure", [None, "depth", "crossed", "unsorted", "nonfinite", "timestamp", "empty"]
)
def test_indexed_book_reference_is_bounded_and_never_exact_depth(failure):
    from src.gpr_sui_shadow.sources import indexed_book_reference

    payload = {
        "timestamp": "1791265457130",
        "bids": [["0.99", "1"], ["0.98", "2"]],
        "asks": [["1.01", "2"]],
    }
    if failure == "depth":
        payload["asks"] *= 21
    elif failure == "crossed":
        payload["asks"][0][0] = "0.9"
    elif failure == "unsorted":
        payload["bids"].reverse()
    elif failure == "nonfinite":
        payload["asks"][0][0] = "NaN"
    elif failure == "timestamp":
        payload["timestamp"] = "recent"
    elif failure == "empty":
        payload["asks"] = []
    if failure:
        with pytest.raises(ValueError):
            indexed_book_reference(payload)
    else:
        result = indexed_book_reference(payload)
        assert result["indicative_mid_spread_bps"] == {
            "numerator": 200,
            "denominator": 1,
        }
        assert (
            not result["exact_state_ready"]
            and result["book_depth_state"] == "BOOK_DEPTH_UNQUALIFIED"
        )


@pytest.mark.parametrize("value", ["1e1000000", "1e-1000000"])
def test_structural_numeric_exponent_is_bounded_before_fraction_allocation(value):
    from src.gpr_sui_shadow.sources import rational

    with pytest.raises(ValueError, match="FINITE_RATE"):
        rational(value)


@pytest.mark.parametrize(
    "params",
    [
        (("depth", "0"), ("level", "2")),
        (("depth", "20"), ("level", "999")),
        (("depth", "9" * 1000), ("level", "2")),
        (("depth", 20), ("level", "2")),
    ],
)
def test_unbounded_or_unreviewed_book_query_fails_before_any_transport(params):
    with pytest.raises(ValueError):
        SuiReadRequest("GET", "https://sui.test/book", "book-reference", params=params)
