"""P0-1 bounded intake cadence, coverage receipt and universe handoff.

The cadence reuses the canonical QPR intake plane; these tests prove pacing
(pagination, backoff, attempt caps, budgets), the source coverage receipt
(the hot-pair target is never forced), the fail-closed DynamicUniverse
handoff (mint identity must be chain-proven) and zero-socket replay.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys

import httpx
import pytest

from src.assets.resolution.evidence import Evidence, EvidenceStore, digest
from src.assets.resolution.resolver import ChainAssetProof
from src.discovery.dynamic_universe.universe import DynamicUniverse
from src.qualification_campaign.identity import CampaignManifest, digest as qdigest
from src.routing.transport import HttpxJsonTransport, TransportPolicy
from src.solana_parallel_radar import din_discovery as runner
from src.solana_parallel_radar.intake_cadence import (
    CadencePolicy,
    IntakeScheduler,
    coverage_report,
    radar_universe_envelopes,
)
from src.strategy.exact_cpmm_capacity import WSOL_MINT
from tests.native_cpmm_fixtures import address

try:
    import fcntl  # noqa: F401
except ImportError:  # pragma: no cover - platform gate, documented in PR
    pytest.skip(
        "fcntl is unavailable on native Windows; run this suite under WSL or "
        "CI Linux per the WSL-first platform decision (2026-11-13)",
        allow_module_level=True,
    )

from src.qualification_campaign.evidence import CampaignEvidenceStore  # noqa: E402

USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
JITOSOL = "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn"
FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "p01_intake"


def load_fixture(name):
    manifest = json.loads((FIXTURES / "fixture-manifest.json").read_text())
    raw = (FIXTURES / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest["fixtures"][name]["sha256"], (
        "fixture pin mismatch: " + name
    )
    return json.loads(raw)


def test_fixture_pins_fail_closed_on_mutation(tmp_path):
    manifest = json.loads((FIXTURES / "fixture-manifest.json").read_text())
    name = "dexscreener_positive.json"
    raw = (FIXTURES / name).read_bytes()
    assert manifest["fixtures"][name]["evidence_kind"] == "SYNTHETIC_TEST"
    tampered = tmp_path / name
    tampered.write_bytes(raw + b" ")
    assert (
        hashlib.sha256(tampered.read_bytes()).hexdigest()
        != manifest["fixtures"][name]["sha256"]
    )


def test_adapter_normalize_positive_drift_and_foreign_rows():
    from src.market.discovery import DiscoveryRequest
    from src.solana_parallel_radar.radar import (
        BatchRadarAdapter,
        TargetedCatalogAdapter,
    )

    positive = load_fixture("dexscreener_positive.json")
    candidates, rejected = BatchRadarAdapter((WSOL_MINT, USDC, JITOSOL)).normalize(
        positive
    )
    assert len(candidates) == 2 and not rejected
    drift, rejected = BatchRadarAdapter((WSOL_MINT, USDC)).normalize(
        load_fixture("dexscreener_drift.json")
    )
    assert not drift and rejected["candidate-schema-rejected"] == 1
    foreign, rejected = BatchRadarAdapter((WSOL_MINT, USDC)).normalize(
        load_fixture("dexscreener_foreign_chain.json")
    )
    assert not foreign and rejected["candidate-schema-rejected"] == 1
    raydium = TargetedCatalogAdapter(DiscoveryRequest("raydium"), (WSOL_MINT, USDC))
    candidates, rejected = raydium.normalize(load_fixture("raydium_positive_p1.json"))
    # jitoSOL is outside the first-campaign mint filter on this adapter.
    assert len(candidates) == 1 and rejected["outside-first-campaign"] == 1
    with pytest.raises(ValueError, match="unsuccessful"):
        raydium.normalize(load_fixture("raydium_schema_drift.json"))
    meteora = TargetedCatalogAdapter(
        DiscoveryRequest("meteora-dlmm"), (WSOL_MINT, USDC, JITOSOL)
    )
    candidates, rejected = meteora.normalize(load_fixture("meteora_positive.json"))
    assert len(candidates) == 2 and not rejected
    drift, rejected = meteora.normalize(load_fixture("meteora_drift.json"))
    assert not drift and rejected["candidate-schema-rejected"] == 1


class FakePlane:
    """Records ordered collect calls and replays canned plane outcomes."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def collect(self, dossier, adapter):
        self.calls.append((dossier.source_id, adapter))
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def dossier_for(source_id):
    class _Dossier:
        pass

    marker = _Dossier()
    marker.source_id = source_id
    return marker


class _Adapter:
    def __init__(self, page):
        self.page = page


def sched_sources(script, **policy_overrides):
    policy = CadencePolicy(
        round_interval_ns=1_000_000_000,
        max_pages_per_round=policy_overrides.get("max_pages_per_round", 3),
    )
    return {
        "raydium": (dossier_for("raydium"), lambda page: _Adapter(page), policy)
    }, FakePlane(script)


def candidate(market, mints):
    from src.qualification_campaign.sources import Candidate

    return Candidate(address(market), mints, "raydium")


def test_scheduler_paginates_and_stops_on_empty_page():
    def records(page):
        return (
            (
                [
                    (
                        candidate(page + 150, (WSOL_MINT, USDC)),
                        {"source_id": "raydium"},
                    )
                ],
                {"quality_state": "accepted", "rejections": {}},
            )
            if page < 3
            else ([], {"quality_state": "empty-response", "rejections": {}})
        )

    sources, plane = sched_sources(
        [records(1), records(2), records(3), records(1), records(2), records(3)]
    )
    scheduler = IntakeScheduler(
        plane, sources, clock_ns=lambda: 10**18, max_physical_requests=10
    )
    run = asyncio.run(scheduler.run_rounds(2))
    # Round 1 walks pages 1..2 with rows, then page 3 is healthy but empty.
    assert [call[1].page for call in plane.calls] == [1, 2, 3, 1, 2, 3]
    assert len(run.records) == 4
    assert run.observation_receipts[2]["quality_state"] == "empty-response"
    assert run.round_receipts[0]["per_source"]["raydium"]["stopped"] == "empty-response"
    # Round 2 resumes the walk from page 1: pages are independent observations,
    # never a complete snapshot, and a healthy empty page is not a failure.
    assert run.round_receipts[1]["per_source"]["raydium"]["pages_attempted"] == 3
    assert run.physical_requests_spent == 6


def test_scheduler_backs_off_after_429_and_honors_bounded_retry_after():
    now = {"ns": 10**18}

    def rate_limited():
        return (
            [],
            {
                "quality_state": "rate-limited",
                "retry_after": "60",
                "rejections": {},
            },
        )

    def accepted():
        return (
            [(candidate(210, (WSOL_MINT, USDC)), {"source_id": "raydium"})],
            {"quality_state": "accepted", "rejections": {}},
        )

    sources, plane = sched_sources([rate_limited(), accepted(), accepted(), accepted()])
    scheduler = IntakeScheduler(
        plane, sources, clock_ns=lambda: now["ns"], max_physical_requests=10
    )
    run = asyncio.run(scheduler.run_rounds(2))
    # Round 1: 429 with Retry-After 60 -> next due is +60s (bounded below cap).
    assert run.round_receipts[0]["per_source"]["raydium"]["stopped"] == "rate-limited"
    assert (
        run.round_receipts[1]["per_source"]["raydium"]["skipped"] == "backoff-not-due"
    )
    assert len(plane.calls) == 1
    now["ns"] += 61 * 10**9
    run = asyncio.run(scheduler.run_rounds(1))
    # The resumed round walks a full healthy page set (1..max_pages_per_round).
    assert len(plane.calls) == 4 and len(run.records) == 3


def test_scheduler_attempt_cap_denial_is_permanent_for_the_campaign():
    denied = (
        [],
        {"quality_state": "quota-or-admission-denied", "rejections": {}},
    )
    accepted = (
        [(candidate(210, (WSOL_MINT, USDC)), {"source_id": "raydium"})],
        {"quality_state": "accepted", "rejections": {}},
    )
    sources, plane = sched_sources([accepted, denied, accepted, accepted])
    scheduler = IntakeScheduler(
        plane, sources, clock_ns=lambda: 10**18, max_physical_requests=10
    )
    run = asyncio.run(scheduler.run_rounds(4))
    # Page 2 is denied; the source never issues another physical request.
    assert len(plane.calls) == 2
    assert "raydium" in scheduler.exhausted
    assert run.round_receipts[1]["per_source"]["raydium"]["skipped"] == (
        "campaign-attempt-cap-exhausted"
    )


def test_scheduler_budget_exhaustion_stops_all_sources():
    accepted = (
        [(candidate(210, (WSOL_MINT, USDC)), {"source_id": "raydium"})],
        {"quality_state": "accepted", "rejections": {}},
    )
    sources, plane = sched_sources([accepted, accepted, accepted])
    scheduler = IntakeScheduler(
        plane, sources, clock_ns=lambda: 10**18, max_physical_requests=2
    )
    run = asyncio.run(scheduler.run_rounds(2))
    assert len(plane.calls) == 2
    assert run.round_receipts[0]["per_source"]["raydium"]["pages_attempted"] == 2
    # The budget breaks at the round boundary, so no second round is emitted.
    assert len(run.round_receipts) == 1
    assert run.physical_requests_spent == 2


def _proof(mint, decimals=9, program="TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"):
    payload = {"mint": mint, "decimals": decimals, "program": program}
    return ChainAssetProof(
        "solana",
        mint,
        decimals,
        program,
        True,
        Evidence(
            "rpc",
            "solana-rpc",
            "solana-rpc",
            "p01-test-generation",
            1000.0,
            digest(payload),
            digest({"get": mint}),
            100,
        ),
    )


def _observation(source_id, candidates, *, observed_at_ns=10**12):
    payload = {"source": source_id, "rows": len(candidates)}
    return {
        "source_id": source_id,
        "provider": source_id,
        "correlation_group": source_id + "-indexed",
        "observed_at_ns": observed_at_ns,
        "response_hash": digest(payload),
        "request_fingerprint": digest({"request": source_id}),
        "candidates": candidates,
    }


def test_universe_bridge_requires_mint_proofs_and_dedupes_aliases(tmp_path):
    from src.qualification_campaign.sources import Candidate

    # The same pool seen by two sources (Raydium API and the DEX Screener row
    # labeled "raydium") must alias into one research market record.
    radar_api_row = Candidate(address(201), (WSOL_MINT, USDC), "raydium")
    dexscreener_row = Candidate(address(201), (USDC, WSOL_MINT), "raydium")
    meteora_row = Candidate(address(203), (WSOL_MINT, JITOSOL), "meteora")
    unknown_row = Candidate(address(204), (WSOL_MINT, USDC), "orca")
    other_row = Candidate(address(202), (WSOL_MINT, JITOSOL), "raydium")
    observations = [
        _observation("raydium", [radar_api_row, other_row]),
        _observation("dexscreener", [dexscreener_row, unknown_row]),
        _observation("meteora-dlmm", [meteora_row]),
    ]
    proofs = {WSOL_MINT: _proof(WSOL_MINT), USDC: _proof(USDC, decimals=6)}
    envelopes, rejections = radar_universe_envelopes(
        observations, proofs, generation="p01-test-generation"
    )
    # pool-a is proven from both sources; jitOSOL has no proof in either row
    # that needs it, and the "orca" label is not a reviewed venue family.
    assert rejections == {
        "identity_unverified_mints": 2,
        "unknown-venue-family": 1,
    }
    store = EvidenceStore(tmp_path / "evidence")
    universe = DynamicUniverse("p01-test-generation", store)
    for envelope in envelopes:
        universe.ingest(envelope, now=1001.0)
    markets = universe.active_markets()
    # Two source aliases of one pool stay one research market record.
    assert len(markets) == 1
    market = markets[0]
    assert market.program_id == "indexed:raydium"
    assert market.venue == "raydium"
    assert market.fee_tier == "unverified"
    assert market.correlation_group == f"solana:{market.market_id}"
    assert all(
        record.lifecycle.value == "DISCOVERED" for record in universe.records.values()
    )
    assert not any(
        record.lifecycle.value == "RETIRED" for record in universe.records.values()
    )
    # An unproven pair produces no market row at all.
    single, rejections = radar_universe_envelopes(
        [_observation("raydium", [other_row])], {}, generation="p01-test-generation"
    )
    assert rejections == {"identity_unverified_mints": 2}
    assert all(envelope.markets == () for envelope in single)
    # A proof for a different identifier is an explicit mismatch rejection.
    mismatched = {USDC: _proof(WSOL_MINT)}
    _, rejections = radar_universe_envelopes(
        [_observation("raydium", [radar_api_row])],
        mismatched,
        generation="p01-test-generation",
    )
    assert rejections["identity_proof_mismatch"] == 1


def test_coverage_report_never_forces_the_hot_pair_target():
    sources = {
        "raydium": {
            "correlation_group": "raydium-indexed",
            "docs_pin_checked_at": "2026-11-13T00:00:00+00:00",
        }
    }
    rounds = [
        {
            "round_index": 1,
            "per_source": {
                "raydium": {"pages_attempted": 2, "last_quality_state": "accepted"}
            },
        }
    ]
    report = coverage_report(
        hot_pair_target=120,
        sources=sources,
        blocked_sources=[
            {"source_id": "geckoterminal", "reason": "CURRENT_DOCS_PIN_MISSING"}
        ],
        round_receipts=rounds,
        candidate_receipts=5,
        unique_identities=2,
        identity_verified_mints=0,
        identity_unverified_mints=4,
        blockers=["IDENTITY_DECIMALS_TOKEN_PROGRAM_PROOF_REQUIRED"],
    )
    assert report["schema_version"] == "p01.source-coverage.v1"
    assert report["physical_calls"] == 2
    assert report["duplicate_rows_merged"] == 3
    assert report["per_source"]["raydium"]["snapshot_completeness"] == (
        "PARTIAL_INDEXED_PAGES_ONLY"
    )
    assert report["hot_pair_target"]["status"] == (
        "TARGET_NOT_SUPPORTED_BY_MEASURED_COVERAGE"
    )
    assert report["classification"] == "DISCOVERY_ONLY"
    assert report["exact_status"] == report["production_status"] == "BLOCKED"
    unconfigured = coverage_report(
        hot_pair_target=None,
        sources=sources,
        blocked_sources=[],
        round_receipts=rounds,
        candidate_receipts=0,
        unique_identities=0,
        identity_verified_mints=0,
        identity_unverified_mints=0,
        blockers=[],
    )
    assert unconfigured["hot_pair_target"] == {"status": "TARGET_NOT_CONFIGURED"}
    with pytest.raises(ValueError, match="hot-pair"):
        coverage_report(
            hot_pair_target=0,
            sources=sources,
            blocked_sources=[],
            round_receipts=[],
            candidate_receipts=0,
            unique_identities=0,
            identity_verified_mints=0,
            identity_unverified_mints=0,
            blockers=[],
        )
    with pytest.raises(ValueError, match="not reviewed"):
        coverage_report(
            hot_pair_target=None,
            sources=sources,
            blocked_sources=[],
            round_receipts=[
                {
                    "round_index": 1,
                    "per_source": {"geckoterminal": {"pages_attempted": 1}},
                }
            ],
            candidate_receipts=0,
            unique_identities=0,
            identity_verified_mints=0,
            identity_unverified_mints=0,
            blockers=[],
        )


def pin(tmp_path):
    p = tmp_path / "docs.txt"
    p.write_bytes(b"reviewed fixture contract")
    return {
        "raydium": {
            "path": str(p),
            "url": "https://docs.raydium.io/api-reference/api-v3/overview",
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "checked_at": datetime.now(UTC).isoformat(),
        }
    }


def test_din_capture_with_cadence_retains_evidence_and_replays_offline(
    tmp_path, monkeypatch
):
    calls = []

    async def handler(request):
        calls.append(str(request.url))
        page = int(request.url.params["page"])
        if page == 1:
            return httpx.Response(200, json=load_fixture("raydium_positive_p1.json"))
        return httpx.Response(200, json=load_fixture("raydium_positive_p2.json"))

    @asynccontextmanager
    async def transport(hosts, *, policy):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False
        ) as client:
            yield HttpxJsonTransport(
                client=client, allowed_hosts=frozenset(hosts), policy=policy
            )

    def manifest(root, *, main_sha, configuration, sources):
        return CampaignManifest(
            "a" * 40,
            main_sha,
            "b" * 64,
            tuple((k, qdigest(v)) for k, v in configuration.items()),
            tuple((k, qdigest(v)) for k, v in sources.items()),
        )

    monkeypatch.setattr(runner, "campaign_transport", transport)
    monkeypatch.setattr(runner.CampaignManifest, "create", manifest)
    # The CI checkout is shallow and has no origin/main ref; pin the recorded
    # main SHA instead of invoking git.
    monkeypatch.setattr(
        runner.subprocess, "check_output", lambda *args, **kwargs: "0" * 40
    )
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "capture"
    result = asyncio.run(
        runner.capture(
            root,
            output,
            mints=(WSOL_MINT, USDC, JITOSOL),
            pins=pin(tmp_path),
            cadence={
                "rounds": 2,
                "round_interval_ns": 1,
                "max_pages_per_round": 2,
                "max_physical_requests": 8,
                "campaign_attempt_cap": 8,
                "request_limit": 8,
                "hot_pair_target": 120,
            },
        )
    )
    # Two rounds x two positive pages: every page yields candidates, so the
    # walk never hits the empty-page stop; identical rows across rounds dedupe.
    assert len(calls) == 4
    assert result["candidate_receipts"] == 6
    assert result["deduplicated_candidates"] == 3
    coverage = result["coverage"]
    assert coverage["physical_calls"] == 4
    assert coverage["duplicate_rows_merged"] == 3
    assert coverage["hot_pair_target"]["status"] == (
        "TARGET_NOT_SUPPORTED_BY_MEASURED_COVERAGE"
    )
    assert coverage["per_source"]["raydium"]["snapshot_completeness"] == (
        "PARTIAL_INDEXED_PAGES_ONLY"
    )
    assert result["round_receipts"][0]["per_source"]["raydium"]["pages_attempted"] == 2
    assert (
        result["exact_status"]
        == result["paper_status"]
        == result["production_status"]
        == "BLOCKED"
    )
    assert not result["sign_enabled"] and not result["send_enabled"]
    replay = runner.replay(output, tmp_path / "replay")
    assert replay["replay_identical"] and replay["network_reads"] == 0
