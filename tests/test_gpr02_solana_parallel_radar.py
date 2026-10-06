"""Deterministic sender-free GPR-02 tests; every market fixture is synthetic."""

import asyncio
import base64
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import struct

import base58
import httpx
import pytest

from src.market.streams import RecoverableStreamJournal
from src.provider_governance import ProviderGovernance
from src.qualification_campaign.evidence import CampaignEvidenceStore
from src.qualification_campaign.identity import CampaignManifest, digest
from src.qualification_campaign.sources import SourceReadRequest
from src.research_economic_graph import (
    AssetRegistry,
    IdentityExpectation,
    StartupIdentityPolicy,
    VerificationQueue,
)
from src.research_economic_graph.registry import SPL_TOKEN_PROGRAM, TOKEN_2022_PROGRAM
from src.routing.transport import HttpxJsonTransport, TransportPolicy
from src.solana_parallel_radar import (
    BatchRadarAdapter,
    ManifestRadarAdapter,
    priority_pairs,
)
from src.solana_parallel_radar.cli import read_contracts, CONTRACT_PATH, capture, replay
from src.solana_parallel_radar.funnel import (
    QuotePreview,
    compare_quotes,
    normalize_jupiter,
    qualification_blockers,
)
from src.solana_parallel_radar.probes import (
    GovernedReadPlane,
    jupiter_request,
    normalized_reference,
    normalize_zero_x,
    normalize_manifest_book,
)
from src.solana_parallel_radar.qualification import (
    retained_quote,
    qualify_exact_request,
)
from src.solana_parallel_radar.structural import (
    sanctum_stake_pool_reference,
    nav_arithmetic_only,
    structural_residual_bps,
)
from src.solana_parallel_radar.token2022 import (
    Token2022SemanticsPolicy,
    decode_token2022_mint,
    inspect_token2022_semantics,
    transfer_fee,
)
from tests.native_cpmm_fixtures import address, synthetic_capture

pytestmark = pytest.mark.unit
NOW = 1_002 * 10**9


def contracts():
    return read_contracts(json.loads(CONTRACT_PATH.read_text()))


def mint_bytes(*, extensions=(), decimals=6, authority_key=None):
    b = bytearray(82)
    if authority_key:
        b[:4] = (1).to_bytes(4, "little")
        b[4:36] = base58.b58decode(authority_key)
    b[36:44] = (100_000).to_bytes(8, "little")
    b[44], b[45] = decimals, 1
    if extensions:
        b += bytes(83) + b"\x01"
        for kind, body in extensions:
            b += struct.pack("<HH", kind, len(body)) + body
    return bytes(b)


def policy_for(asset, extensions=(), **kwargs):
    expectation = IdentityExpectation(
        asset.asset_id,
        digest(asset.representation),
        6,
        ("explicit-synthetic-issuer-review",),
        tuple(str(t) for t, _ in sorted(extensions)),
    )
    return Token2022SemanticsPolicy(
        StartupIdentityPolicy((expectation,)),
        asset.asset_id,
        None,
        None,
        tuple((t, hashlib.sha256(v).hexdigest()) for t, v in extensions),
        **kwargs,
    )


@pytest.mark.parametrize("key", ["USDG", "PYUSD"])
def test_token2022_reviewed_mint_semantics_are_not_startup_pool_receipts(key):
    asset = AssetRegistry.load().resolve("solana-mainnet:" + key)
    inspected = inspect_token2022_semantics(
        asset, mint_bytes(), TOKEN_2022_PROGRAM, policy=policy_for(asset), epoch=20
    )
    assert inspected["decimals"] == 6 and inspected["owner"] == TOKEN_2022_PROGRAM
    assert not inspected["exact_pool_receipt"] and not inspected["exact_graph_allowed"]


@pytest.mark.parametrize("kind", [2, 4, 6, 7, 8, 9, 10, 11, 12, 14, 16, 20, 25, 99])
def test_unsupported_token2022_semantics_fail_closed(kind):
    with pytest.raises(ValueError, match="UNSUPPORTED"):
        decode_token2022_mint(
            mint_bytes(extensions=((kind, bytes(64)),)),
            mint=address(1),
            owner=TOKEN_2022_PROGRAM,
        )


@pytest.mark.parametrize(
    "fault",
    [
        "owner",
        "decimals",
        "mint-authority",
        "freeze-authority",
        "missing-policy",
        "wrong-representation",
        "tlv-hash",
    ],
)
def test_token2022_policy_and_authority_fail_closed(fault):
    asset = AssetRegistry.load().resolve("solana-mainnet:USDG")
    data, owner, policy = mint_bytes(), TOKEN_2022_PROGRAM, policy_for(asset)
    if fault == "owner":
        owner = SPL_TOKEN_PROGRAM
    if fault == "decimals":
        data = mint_bytes(decimals=9)
    if fault == "mint-authority":
        data = mint_bytes(authority_key=address(22))
    if fault == "freeze-authority":
        b = bytearray(data)
        b[46:50] = (1).to_bytes(4, "little")
        b[50:82] = base58.b58decode(address(22))
        data = bytes(b)
    if fault == "missing-policy":
        policy = None
    if fault == "wrong-representation":
        policy = replace(
            policy,
            identity_policy=StartupIdentityPolicy(
                (
                    replace(
                        policy.identity_policy.expectations[0],
                        representation_digest="f" * 64,
                    ),
                )
            ),
        )
    if fault == "tlv-hash":
        data = mint_bytes(extensions=((3, bytes(32)),))
    with pytest.raises(ValueError):
        inspect_token2022_semantics(asset, data, owner, policy=policy, epoch=20)


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate",
        "truncated",
        "account-type",
        "base-padding",
        "option",
        "uninitialized",
        "short-tlv",
        "extension-length",
    ],
)
def test_token2022_tlv_layout_fails_closed(fault):
    b = bytearray(mint_bytes(extensions=((3, bytes(32)),)))
    if fault == "duplicate":
        b += struct.pack("<HH", 3, 32) + bytes(32)
    if fault == "truncated":
        b.pop()
    if fault == "account-type":
        b[165] = 2
    if fault == "base-padding":
        b[90] = 1
    if fault == "option":
        b[0] = 2
    if fault == "uninitialized":
        b[45] = 0
    if fault == "short-tlv":
        b += b"\x01"
    if fault == "extension-length":
        b[168:170] = struct.pack("<H", 33)
    with pytest.raises(ValueError):
        decode_token2022_mint(bytes(b), mint=address(1), owner=TOKEN_2022_PROGRAM)


def test_token2022_metadata_self_mint_binding_and_borsh_bounds():
    mint = address(1)
    pointer = bytes(32) + base58.b58decode(mint)
    metadata = (
        bytes(32)
        + base58.b58decode(mint)
        + struct.pack("<I", 1)
        + b"n"
        + struct.pack("<I", 1)
        + b"s"
        + struct.pack("<I", 1)
        + b"u"
        + struct.pack("<I", 0)
    )
    decoded = decode_token2022_mint(
        mint_bytes(extensions=((18, pointer), (19, metadata))),
        mint=mint,
        owner=TOKEN_2022_PROGRAM,
    )
    assert set(decoded["extensions"]) == {18, 19}
    for extensions in (
        ((18, bytes(64)),),
        ((19, bytes(32) + base58.b58decode(address(2)) + metadata[64:]),),
        ((19, metadata + b"x"),),
    ):
        with pytest.raises(ValueError):
            decode_token2022_mint(
                mint_bytes(extensions=extensions), mint=mint, owner=TOKEN_2022_PROGRAM
            )


def test_transfer_fee_epoch_rollover_ceiling_and_authority():
    asset = AssetRegistry.load().resolve("solana-mainnet:USDG")
    body = bytes(72) + struct.pack("<QQH", 10, 5, 25) + struct.pack("<QQH", 20, 10, 100)
    ext = ((1, body),)
    old = inspect_token2022_semantics(
        asset,
        mint_bytes(extensions=ext),
        TOKEN_2022_PROGRAM,
        policy=policy_for(asset, ext),
        epoch=19,
    )
    new = inspect_token2022_semantics(
        asset,
        mint_bytes(extensions=ext),
        TOKEN_2022_PROGRAM,
        policy=policy_for(asset, ext),
        epoch=20,
    )
    assert old["active_transfer_fee"]["basis_points"] == 25
    assert new["active_transfer_fee"]["basis_points"] == 100
    assert transfer_fee(1, new["active_transfer_fee"]) == 1
    assert transfer_fee(10_000, new["active_transfer_fee"]) == 10
    with pytest.raises(ValueError, match="AUTHORITY"):
        inspect_token2022_semantics(
            asset,
            mint_bytes(extensions=ext),
            TOKEN_2022_PROGRAM,
            policy=policy_for(asset, ext, transfer_fee_config_authority=address(2)),
            epoch=20,
        )


def test_radar_batch_is_bounded_filtered_and_deterministic():
    adapter = BatchRadarAdapter((address(1), address(2)))
    rows = [
        {
            "chainId": "solana",
            "pairAddress": address(50),
            "baseToken": {"address": address(1)},
            "quoteToken": {"address": address(2)},
            "dexId": "untrusted",
        }
    ]
    assert adapter.normalize(rows) == adapter.normalize(list(reversed(rows)))
    assert adapter.normalize(rows)[0][0].identity
    assert (
        adapter.normalize([dict(rows[0], chainId="sui")])[1][
            "candidate-schema-rejected"
        ]
        == 1
    )
    with pytest.raises(ValueError):
        BatchRadarAdapter(tuple(address(i) for i in range(1, 32)))
    with pytest.raises(ValueError):
        adapter.normalize(rows * 1001)


def test_manifest_identifier_radar_uses_confirmed_api_and_no_program_scan():
    a = ManifestRadarAdapter((address(1), address(2)))
    assert a.request().url == "https://mfx-stats-mainnet.fly.dev/tickers"
    c, _ = a.normalize(
        [
            {
                "ticker_id": address(50),
                "base_currency": address(1),
                "target_currency": address(2),
            }
        ]
    )
    assert c[0].venue_label == "manifest"


@pytest.mark.parametrize(
    "fault", [None, "identity", "depth", "nan", "negative", "large", "shape"]
)
def test_manifest_book_depth_numeric_identity_fail_closed(fault):
    payload = {
        "ticker_id": address(50),
        "timestamp": "1002",
        "bids": [["1.0", "10"]],
        "asks": [["1.1", "10"]],
    }
    if fault == "identity":
        payload["ticker_id"] = address(51)
    if fault == "nan":
        payload["bids"] = [["NaN", "10"]]
    if fault == "negative":
        payload["bids"] = [["-1", "10"]]
    if fault == "large":
        payload["bids"] = [["1", "10"]] * 11
    if fault == "shape":
        payload["bids"] = [["1"]]
    if fault:
        with pytest.raises(ValueError):
            normalize_manifest_book(
                payload, market_id=address(50), depth=500 if fault == "depth" else 20
            )
    else:
        book = normalize_manifest_book(payload, market_id=address(50))
        assert (
            not book["depth_verified"]
            and not book["fee_verified"]
            and not book["exact_graph_allowed"]
        )


def quote_payload(input_mint=address(1), output_mint=address(2)):
    return {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "inAmount": "1000",
        "outAmount": "1010",
        "otherAmountThreshold": "1000",
        "contextSlot": 100,
        "swapMode": "ExactIn",
        "routePlan": [
            {"swapInfo": {"inputMint": input_mint, "outputMint": output_mint}}
        ],
    }


def qpreview(**kwargs):
    return QuotePreview(
        address(1),
        address(2),
        1000,
        1010,
        1000,
        100,
        NOW,
        "source",
        "a" * 64,
        "group",
        "raw",
        (address(1), address(2)),
        True,
        **kwargs,
    )


@pytest.mark.parametrize(
    "fault", ["amount", "output", "slot", "float", "future", "stale", "correlation"]
)
def test_quote_constraints_and_correlation(fault):
    a, b = qpreview(), replace(
        qpreview(), correlation_group="other", raw_evidence_ref="raw2"
    )
    if fault == "amount":
        b = replace(b, input_amount=2000)
    if fault == "output":
        b = replace(b, output_mint=address(3))
    if fault == "slot":
        b = replace(b, slot=200)
    if fault == "float":
        with pytest.raises(ValueError):
            replace(b, input_amount=1000.0)
        return
    if fault == "future":
        b = replace(b, observed_at_ns=NOW + 1)
    if fault == "stale":
        b = replace(b, observed_at_ns=NOW - 45_000_000_001)
    if fault == "correlation":
        r = compare_quotes(
            a, replace(b, correlation_group=a.correlation_group), now_ns=NOW
        )
        assert not r["independent"] and not r["execution_authority"]
        return
    with pytest.raises(ValueError):
        compare_quotes(a, b, now_ns=NOW)


def test_zero_x_quote_reads_economic_fields_without_consuming_instruction_objects():
    zc, _ = contracts()
    payload = {
        "amount_out": 1010,
        "min_amount_out": 1000,
        "route_plan": [{"token_in": address(1), "token_out": address(2)}],
        "instructions": "deliberately not deserializable",
        "address_lookup_tables": object(),
    }
    q = normalize_zero_x(
        payload,
        body={"token_in": address(1), "token_out": address(2), "amount_in": 1000},
        observed_at_ns=NOW,
        contract=zc,
        raw_evidence_ref="raw",
    )
    assert q.slot is None and q.output_amount == 1010
    assert (
        compare_quotes(q, replace(q, slot=100), now_ns=NOW)["slot_alignment"]
        == "UNKNOWN"
    )


@pytest.mark.parametrize(
    "outcome", ["200", "403", "429", "timeout", "missing-key", "reflection", "quota"]
)
def test_governed_quote_probe_retains_raw_negative_budget_and_replay(tmp_path, outcome):
    async def run():
        _, c = contracts()
        p = c.profile
        manifest = CampaignManifest(
            "a" * 40,
            "b" * 40,
            "c" * 64,
            (("config", "d" * 64),),
            ((c.source_id, c.generation), (p.profile_id, p.generation)),
        )
        journal = RecoverableStreamJournal(tmp_path / "probe.sqlite")
        evidence = CampaignEvidenceStore(journal, manifest, wall_ns=lambda: NOW)
        calls = []

        def handler(req):
            calls.append(req)
            if outcome == "timeout":
                raise httpx.ReadTimeout("private", request=req)
            payload = quote_payload()
            if outcome == "reflection":
                payload["debug"] = "SECRET-EXAMPLE"
            return httpx.Response(
                int(outcome) if outcome.isdigit() else 200,
                json=payload,
                headers={"retry-after": "2"},
            )

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            trust_env=False,
            follow_redirects=False,
        )
        transport = HttpxJsonTransport(
            policy=TransportPolicy(max_attempts=1),
            allowed_hosts=frozenset({p.hostname}),
            client=client,
        )
        gov = ProviderGovernance(
            {p.profile_id: c.entitlement(expires_at_epoch_seconds=2000)},
            clock=lambda: 1002,
            wall_clock=lambda: 1002,
        )
        plane = GovernedReadPlane(gov, transport, evidence, wall_ns=lambda: NOW)
        request = jupiter_request(address(1), address(2), 1000)
        ref, envelope = await plane.collect(
            c,
            request,
            credential=None if outcome == "missing-key" else "SECRET-EXAMPLE",
        )
        if outcome == "quota":
            for _ in range(5):
                await plane.collect(c, request, credential="SECRET-EXAMPLE")
            assert len(calls) == 4
        if outcome == "missing-key":
            assert not calls and not any(
                r.get("kind") == "attempt" for r in evidence.replay()
            )
        if outcome == "reflection":
            assert "SECRET-EXAMPLE" not in json.dumps(evidence.replay())
        if outcome in ("200", "reflection", "quota"):
            q = normalized_reference(evidence, c, request, ref, envelope)
            assert q.output_amount == 1010
        else:
            assert normalized_reference(evidence, c, request, ref, envelope) is None
        assert evidence.replay() == evidence.replay()
        await transport.aclose()
        await client.aclose()
        journal.close()

    asyncio.run(run())


def account(data, owner):
    return {
        "executable": False,
        "owner": owner,
        "data": [base64.b64encode(data).decode(), "base64"],
    }


@pytest.mark.parametrize(
    "fault", [None, "owner", "mint", "supply", "epoch", "clock-owner"]
)
def test_sanctum_current_structural_reference_binds_mint_pool_and_epoch(fault):
    ref = json.loads(CONTRACT_PATH.read_text())["sanctum_references"][0]
    p = bytearray(282)
    p[0] = 1
    p[162:194] = base58.b58decode(ref["mint"])
    p[226:258] = base58.b58decode(SPL_TOKEN_PROGRAM)
    struct.pack_into("<QQQ", p, 258, 200_000, 100_000, 20)
    m = mint_bytes(decimals=9)
    clock = struct.pack("<QqQQq", 100, 0, 20, 20, 1002)
    pa, ma, ca = (
        account(bytes(p), ref["program_id"]),
        account(m, SPL_TOKEN_PROGRAM),
        account(clock, "Sysvar1111111111111111111111111111111111111"),
    )
    if fault == "owner":
        pa["owner"] = address(2)
    if fault == "clock-owner":
        ca["owner"] = address(2)
    if fault == "mint":
        p[162:194] = base58.b58decode(address(2))
        pa = account(bytes(p), ref["program_id"])
    if fault == "supply":
        struct.pack_into("<Q", p, 266, 99)
        pa = account(bytes(p), ref["program_id"])
    if fault == "epoch":
        struct.pack_into("<Q", p, 274, 19)
        pa = account(bytes(p), ref["program_id"])
    if fault:
        with pytest.raises(ValueError):
            sanctum_stake_pool_reference(pa, ma, ca, reference=ref, slot=100)
    else:
        r = sanctum_stake_pool_reference(pa, ma, ca, reference=ref, slot=100)
        assert r["lamports_per_raw_unit_numerator"] == 2 and not r["fee_adjusted"]
        assert structural_residual_bps(2100, 1000, 2, 1) == 500


def test_nav_arithmetic_does_not_claim_live_nav_receipt():
    r = nav_arithmetic_only(
        aum_usd_atoms=10_000_000,
        jlp_supply=2_000_000,
        jlp_decimals=6,
        aum_decimals=6,
        slot=100,
        oracle_slot=100,
        raw_refs=("unverified",),
    )
    assert r["usd_per_jlp_numerator"] == 5 and not r["live_nav_qualified"]


def test_priority_pairs_preserve_ws_sol_and_all_token2022_registry_identities():
    r = AssetRegistry.load()
    p = priority_pairs(r)
    assert len(p) == 9 and p[5][1].asset_key == "WSOL"
    assert r.resolve("solana-mainnet:SOL") != p[5][1]
    assert (
        r.resolve("solana-mainnet:USDG").standard
        == r.resolve("solana-mainnet:PYUSD").standard
        == "Token-2022"
    )


def test_capture_offline_records_real_transport_failures_and_deterministic_replay(
    tmp_path, monkeypatch
):
    import src.solana_parallel_radar.cli as cli
    from contextlib import asynccontextmanager

    def manifest_factory(root, *, main_sha, configuration, sources):
        return CampaignManifest(
            "a" * 40,
            main_sha,
            "c" * 64,
            tuple((k, digest(v)) for k, v in configuration.items()),
            tuple((k, digest(v)) for k, v in sources.items()),
        )

    @asynccontextmanager
    async def mock_transport(hosts, *, policy):
        def handler(req):
            return httpx.Response(403, json={"error": "synthetic proxy denied"})

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False
        )
        transport = HttpxJsonTransport(
            policy=policy, allowed_hosts=frozenset(hosts), client=client
        )
        try:
            yield transport
        finally:
            await transport.aclose()
            await client.aclose()

    monkeypatch.setattr(cli.CampaignManifest, "create", manifest_factory)
    monkeypatch.setattr(cli, "campaign_transport", mock_transport)
    monkeypatch.delenv("JUPITER_API_KEY", raising=False)
    monkeypatch.delenv("ZEROX_API_KEY", raising=False)
    output = tmp_path / "campaign"
    result = asyncio.run(capture(output, main_sha="b" * 40))
    assert (
        result["measurement_readiness"] == "BLOCKED"
        and result["successful_http_reads"] == 0
    )
    assert result["reserved_attempts"] == 5 and result["quotes_measured"] == 0
    assert replay(output) == result
    with pytest.raises(ValueError, match="NEW_CAMPAIGN"):
        asyncio.run(capture(output, main_sha="b" * 40))


def test_manifest_ticker_book_share_pinned_provider_and_durable_quota(
    tmp_path, monkeypatch
):
    import src.solana_parallel_radar.cli as cli
    from contextlib import asynccontextmanager
    from src.strategy.exact_cpmm_capacity import MAINNET_GENESIS

    mints = [a.canonical_identifier for a in priority_pairs(AssetRegistry.load())[0]]
    calls = []

    def manifest_factory(root, *, main_sha, configuration, sources):
        return CampaignManifest(
            "a" * 40,
            main_sha,
            "c" * 64,
            tuple((k, digest(v)) for k, v in configuration.items()),
            tuple((k, digest(v)) for k, v in sources.items()),
        )

    @asynccontextmanager
    async def mock_transport(hosts, *, policy):
        def handler(req):
            calls.append(req.url.path)
            if req.url.path == "/tickers":
                payload = [
                    {
                        "ticker_id": address(50),
                        "base_currency": mints[0],
                        "target_currency": mints[1],
                    }
                ]
            elif req.url.path == "/orderbook":
                payload = {
                    "ticker_id": address(50),
                    "timestamp": "1002",
                    "bids": [["1", "10"]],
                    "asks": [["1.01", "10"]],
                }
            elif req.url.host == "api.dexscreener.com":
                payload = []
            elif req.url.host == "api-v3.raydium.io":
                payload = {"success": True, "data": {"data": []}}
            elif req.url.host == "dlmm.datapi.meteora.ag":
                payload = {"data": []}
            else:
                body = json.loads(req.content)
                result = (
                    MAINNET_GENESIS
                    if body["method"] == "getGenesisHash"
                    else {
                        "context": {"slot": 100},
                        "value": [None] * len(body["params"][0]),
                    }
                )
                payload = {"jsonrpc": "2.0", "id": body["id"], "result": result}
            return httpx.Response(200, json=payload)

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False
        )
        transport = HttpxJsonTransport(
            policy=policy, allowed_hosts=frozenset(hosts), client=client
        )
        try:
            yield transport
        finally:
            await transport.aclose()
            await client.aclose()

    monkeypatch.setattr(cli.CampaignManifest, "create", manifest_factory)
    monkeypatch.setattr(cli, "campaign_transport", mock_transport)
    monkeypatch.delenv("JUPITER_API_KEY", raising=False)
    p = tmp_path / "book-campaign"
    result = asyncio.run(capture(p, main_sha="b" * 40))
    assert calls.count("/tickers") == calls.count("/orderbook") == 1
    assert any(
        e["kind"] == "gpr02_manifest_book_reference"
        for e in result["manifest_measurements"]
    )
    outcome = next(
        e for e in result["source_outcomes"] if e["source_id"] == "gpr02-manifest-book"
    )
    assert (
        outcome["http_status"] == 200
        and outcome["correlation_group"] == "manifest-indexed"
    )
    assert result == replay(p)


@pytest.mark.parametrize(
    "fault", [None, "forged-quote", "wrong-amount", "correlated-rpc", "ingest-rejected"]
)
def test_actual_funnel_reconstructs_quotes_and_delegates_existing_exact_owners(
    tmp_path, monkeypatch, fault
):
    import tests.test_gpr01_research_economic_graph as lab
    from src.qualification_campaign.profiles import ProviderProfile
    from src.qualification_campaign.rpc import NativeRootedSnapshotProvider
    from src.market.native_cpmm_capture import GovernedNativeCpmmCollector
    from src.research_economic_graph.graph import retained_records
    from src.strategy.exact_cpmm_capacity import MAINNET_GENESIS, WSOL_MINT

    zx, jc = contracts()
    original_manifest = lab.make_manifest

    def extended_manifest(graph, *, policy=None, sources=None):
        return original_manifest(
            graph,
            policy=policy,
            sources=[
                *sources,
                (zx.source_id, zx.generation),
                (zx.profile.profile_id, zx.profile.generation),
                (jc.source_id, jc.generation),
                (jc.profile.profile_id, jc.profile.generation),
            ],
        )

    monkeypatch.setattr(lab, "make_manifest", extended_manifest)

    async def run():
        graph, evidence, gate, _, _ = await lab.build_lab(
            tmp_path, rpc_fault="correlated" if fault == "correlated-rpc" else "none"
        )
        relation, request = lab.exact_request(graph, evidence)
        from src.research_economic_graph import CandidateScore

        queue_ref = VerificationQueue(graph, evidence).persist(
            {relation.relation_id: CandidateScore((("liquidity_change", 10),))},
            top_k=1,
            now_ns=NOW,
        )
        fixture = synthetic_capture()
        accounts = {a["address"]: a["value"] for a in fixture["accounts"]}
        native_calls = []

        def handler(req):
            if req.url.host == "api.jup.ag":
                return httpx.Response(200, json=quote_payload(WSOL_MINT, address(3)))
            body = json.loads(req.content)
            if req.url.host == "api.0x.org":
                return httpx.Response(
                    200,
                    json={
                        "amount_out": 1010,
                        "min_amount_out": 1000,
                        "route_plan": [
                            {"token_in": WSOL_MINT, "token_out": address(3)}
                        ],
                        "instructions": [{"inert": "never decoded"}],
                    },
                )
            native_calls.append(body["method"])
            method = body["method"]
            if method == "getGenesisHash":
                result = MAINNET_GENESIS
            elif method == "getMultipleAccounts":
                result = {
                    "context": {"slot": 100},
                    "value": [accounts[a] for a in body["params"][0]],
                }
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

        rpcs = tuple(
            ProviderProfile(
                f"rpc-{k}",
                k,
                f"operator-{k}",
                f"backend-{k}",
                f"https://rpc-{k}.test",
                f"https://docs.test/{k}",
            )
            for k in ("a", "b")
        )
        if fault == "correlated-rpc":
            rpcs = (
                rpcs[0],
                replace(rpcs[1], correlation_group=rpcs[0].correlation_group),
            )
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            trust_env=False,
            follow_redirects=False,
        )
        transport = HttpxJsonTransport(
            policy=TransportPolicy(max_attempts=1, max_string_length=900_000),
            allowed_hosts=frozenset(
                p.hostname for p in (*rpcs, zx.profile, jc.profile)
            ),
            client=client,
        )
        entitlements = {
            p.profile_id: p.entitlement(expires_at_epoch_seconds=2000) for p in rpcs
        }
        entitlements.update(
            {
                c.profile.profile_id: c.entitlement(expires_at_epoch_seconds=2000)
                for c in (zx, jc)
            }
        )
        gov = ProviderGovernance(
            entitlements, clock=lambda: 1002, wall_clock=lambda: 1002
        )
        plane = GovernedReadPlane(gov, transport, evidence, wall_ns=lambda: NOW)
        body = {
            "token_in": WSOL_MINT,
            "token_out": address(3),
            "amount_in": 1000,
            "taker": address(25),
            "slippage_bps": 50,
        }
        refs = []
        for c, req, request_body in (
            (
                zx,
                SourceReadRequest(
                    zx.profile.endpoint, semantic_headers=zx.semantic_headers
                ),
                body,
            ),
            (jc, jupiter_request(WSOL_MINT, address(3), 1000), None),
            (jc, jupiter_request(WSOL_MINT, address(3), 1000), None),
        ):
            raw, e = await plane.collect(
                c, req, credential="TEST-ONLY-SECRET", json_body=request_body
            )
            assert normalized_reference(evidence, c, req, raw, e, body=request_body)
            refs.append(
                next(
                    reversed(
                        [
                            r
                            for r, b in retained_records(evidence).items()
                            if b.get("kind") == "gpr02_quote_preview"
                        ]
                    )
                )
            )
        if fault == "forged-quote":
            refs[0] = "made-up-ref"
        collectors = [
            GovernedNativeCpmmCollector(
                gov, transport, profile=p, evidence_store=evidence, wall_ns=lambda: NOW
            )
            for p in rpcs
        ]
        provider = NativeRootedSnapshotProvider(
            collectors, evidence, monotonic_ms=lambda: 10_000, wall_ns=lambda: NOW
        )
        sink = lab.exact_sink()
        if fault == "ingest-rejected":
            monkeypatch.setattr(sink, "ingest", lambda *args: False)
        kwargs = dict(
            queue_ref=queue_ref,
            zero_x_contract=zx,
            jupiter_contract=jc,
            zero_x_quote_ref=refs[0],
            jupiter_reference_ref=refs[1],
            jupiter_final_ref=refs[2],
            binding_id="lab-pool",
            input_asset_id="solana-mainnet:LAB_A",
            input_amount=999 if fault == "wrong-amount" else 1000,
            cursor_offset=1,
        )
        if fault:
            with pytest.raises(ValueError):
                await qualify_exact_request(
                    request, graph, gate, provider, sink, **kwargs
                )
            assert not any(
                r.get("kind") == "gpr02_exact_shadow_handoff" for r in evidence.replay()
            )
            if fault in ("forged-quote", "wrong-amount"):
                assert not native_calls
        else:
            result = await qualify_exact_request(
                request, graph, gate, provider, sink, **kwargs
            )
            assert result.input_amount == 1000 and native_calls
            row = next(
                r
                for r in evidence.replay()
                if r.get("kind") == "gpr02_exact_shadow_handoff"
            )
            assert len(row["receipt_refs"]) == 2 and not row["live_authorization"]
        await transport.aclose()
        await client.aclose()
        evidence.journal.close()

    asyncio.run(run())
