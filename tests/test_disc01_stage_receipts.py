"""DISC-01: per-source stage receipts, no streaming claims, independence.

Acceptance (docs/roadmap/data-to-paper-readiness-2026-11-22/TASK_BACKLOG_V1.json):
- per-source request/attempt/candidate counts, response size, latency, quota
  status, schema drift and rejects are receipted;
- no unsupported streaming claim; deterministic replay; stage denominators
  reported;
- no duplicate catalog or discovery adapter; no paid provider activation or
  credential probing; no aggregator route counted as independent liquidity.
"""

import asyncio
from dataclasses import asdict, replace as dataclasses_replace
from datetime import UTC, datetime

import httpx
import pytest

from tests.native_cpmm_fixtures import address
from src.market.source_catalog import load_market_source_catalog
from src.market.streams import RecoverableStreamJournal
from src.provider_governance import ProviderGovernance
from src.routing.transport import HttpxJsonTransport, TransportPolicy
from src.qualification_campaign.identity import CampaignManifest, digest
from src.qualification_campaign.profiles import ProviderProfile
from src.qualification_campaign.evidence import CampaignEvidenceStore
from src.qualification_campaign.sources import (
    SourceDossier,
    SourceIntakePlane,
    SourceReadRequest,
    Candidate,
    independent_correlation_groups,
    require_supported_capabilities,
)

pytestmark = pytest.mark.unit


class NewSourceAdapter:
    def request(self):
        return SourceReadRequest("https://new.test/pools")

    def schema_contract(self):
        return {"request": "public-pools-v1", "response": "rows-v1"}

    def context(self, payload):
        return {
            "source_provided_time": payload.get("timestamp"),
            "slot": payload.get("slot"),
        }

    def normalize(self, payload):
        return (
            tuple(
                Candidate(row["pool"], tuple(row["mints"]), row["venue"])
                for row in payload["rows"]
            ),
            {},
        )


def dossier():
    profile = ProviderProfile(
        "new-profile",
        "new-provider",
        "new-operator",
        "new-index",
        "https://new.test/pools",
        "https://docs.new.test/api",
        role="discovery",
        request_limit=2,
        campaign_attempt_cap=2,
    )
    return SourceDossier(
        "FREE-SOURCE-001",
        "new public source",
        profile,
        datetime.fromtimestamp(1000, UTC).isoformat(),
        "a" * 64,
        "public-pools-v1",
        "rows-v1",
        digest(NewSourceAdapter().schema_contract()),
        "https://new.test/terms",
        slot_id="FREE-SOURCE-001",
    )


def manifest(d):
    return CampaignManifest(
        "a" * 40,
        "b" * 40,
        "c" * 64,
        (("config", "d" * 64),),
        ((d.source_id, d.generation), (d.profile.profile_id, d.profile.generation)),
    )


def make_intake(tmp_path, d, payload_rows):
    reply = {
        "timestamp": 999,
        "slot": 100,
        "rows": [
            {
                "pool": address(10 + i),
                "mints": [address(11 + i), address(12 + i)],
                "venue": "unknown-venue",
            }
            for i in range(payload_rows)
        ],
    }

    def handler(req):
        return httpx.Response(200, json=reply)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        trust_env=False,
        follow_redirects=False,
    )
    transport = HttpxJsonTransport(
        policy=TransportPolicy(max_attempts=1),
        allowed_hosts=frozenset({"new.test"}),
        client=client,
    )
    gov = ProviderGovernance(
        {d.profile.profile_id: d.profile.entitlement(expires_at_epoch_seconds=2000)},
        clock=lambda: 1002,
        wall_clock=lambda: 1002,
    )
    journal = RecoverableStreamJournal(tmp_path / "events.sqlite")
    evidence = CampaignEvidenceStore(journal, manifest(d), wall_ns=lambda: 1002 * 10**9)
    catalog = load_market_source_catalog().with_intake(d.catalog_entry())
    intake = SourceIntakePlane(
        catalog,
        gov,
        transport,
        evidence,
        wall_ns=lambda: 1002 * 10**9,
    )
    return intake, NewSourceAdapter()


def test_stage_receipt_reports_all_denominators(tmp_path):
    async def run():
        d = dossier()
        intake, adapter = make_intake(tmp_path, d, payload_rows=2)
        await intake.collect(d, adapter)
        receipts = intake.stage_receipts()
        assert len(receipts) == 1
        r = receipts[0]
        assert r.source_id == "FREE-SOURCE-001"
        denominators = r.to_dict()["stage_denominators"]
        assert denominators["requests"] == 1
        assert denominators["attempts"] == 1
        assert denominators["responded"] == 1
        assert denominators["candidates"] == 2
        assert r.response_bytes_total > 0
        assert r.latency_ns_total == 0  # fixed wall clock in this fixture
        assert r.quota_status == "UNKNOWN"
        assert r.schema_drift is False
        assert r.terminal_results == {"ACCEPTED": 1}

    asyncio.run(run())


def test_rejects_and_empty_response_are_receipted(tmp_path):
    async def run():
        d = dossier()
        intake, adapter = make_intake(tmp_path, d, payload_rows=0)
        records, envelope = await intake.collect(d, adapter)
        receipts = intake.stage_receipts()
        r = receipts[0]
        # Adapter normalizes an empty rows payload to zero candidates; the
        # typed terminal result and the denominator both record it.
        assert r.schema_drift is False
        assert r.terminal_results == {"EMPTY_RESPONSE": 1}
        assert r.candidates == 0
        assert r.responded == 1

    asyncio.run(run())


def test_stage_receipts_are_deterministic_across_replay(tmp_path):
    async def run():
        d = dossier()
        intake, adapter = make_intake(tmp_path, d, payload_rows=1)
        await intake.collect(d, adapter)
        digest_before = intake.stage_receipts_digest()
        assert intake.stage_receipts_digest() == digest_before
        # Fresh process equivalent: a new plane over the same durable journal.
        replay_plane = SourceIntakePlane(
            intake.catalog,
            intake.governance,
            intake.transport,
            CampaignEvidenceStore(
                RecoverableStreamJournal(tmp_path / "events.sqlite"),
                manifest(d),
                wall_ns=lambda: 1002 * 10**9,
            ),
            wall_ns=lambda: 1002 * 10**9,
        )
        assert replay_plane.stage_receipts_digest() == digest_before

    asyncio.run(run())


def test_unsupported_streaming_claim_fails_closed():
    d = dossier()

    # SourceDossier validation already refuses capability upgrades; the
    # guard is the second fail-closed layer for programmatically supplied
    # dossiers (catalog merges, stored documents).
    class _StreamingDossier:
        capabilities = ("candidate-discovery", "streaming")

    with pytest.raises(ValueError, match="UNSUPPORTED_SOURCE_CAPABILITY:streaming"):
        require_supported_capabilities(_StreamingDossier())
    require_supported_capabilities(d)  # the baseline dossier claims nothing new


def test_aggregator_routes_are_never_independent_liquidity():
    d = dossier()
    agg_profile = dataclasses_replace(
        d.profile,
        profile_id="agg-profile",
        provider="agg-provider",
        operator="agg-operator",
        correlation_group="aggregator-index",
        endpoint="https://agg.test/pools",
        official_docs="https://docs.agg.test/api",
    )
    aggregator = dataclasses_replace(
        d,
        source_id="AGG-1",
        profile=agg_profile,
        capabilities=("candidate-discovery",),
    )
    report = independent_correlation_groups([d, aggregator])
    assert report["independent_correlation_groups"] == 1
    assert report["aggregator_sources_excluded"] == 1
    assert report["groups"]["new-index"] == ["FREE-SOURCE-001"]


def test_no_duplicate_catalog_entry_or_adapter(tmp_path):
    d = dossier()
    intake, adapter = make_intake(tmp_path, d, payload_rows=1)
    # The catalog owns exactly one entry for this source id.
    assert intake.catalog.require(d.source_id).source_id == d.source_id
    with pytest.raises(ValueError):
        load_market_source_catalog().with_intake(d.catalog_entry()).with_intake(
            d.catalog_entry()
        )
