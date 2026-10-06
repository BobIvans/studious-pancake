import asyncio
from dataclasses import asdict, replace
from datetime import UTC, datetime
import json
import time

import httpx
import pytest

from tests.native_cpmm_fixtures import address
from src.market.source_catalog import load_market_source_catalog
from src.market.streams import RecoverableStreamJournal
from src.provider_governance import ProviderGovernance
from src.routing.transport import HttpxJsonTransport, TransportPolicy
from src.qualification_campaign.identity import (
    CampaignManifest,
    digest,
    manifest_from_dict,
)
from src.qualification_campaign.profiles import ProviderProfile
from src.qualification_campaign.evidence import CampaignEvidenceStore
from src.qualification_campaign.sources import (
    SourceDossier,
    SourceIntakePlane,
    SourceReadRequest,
    Candidate,
    deduplicate_candidates,
)
from src.qualification_campaign.cli import blank_source_template, load_sources


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


@pytest.mark.parametrize(
    "outcome",
    [
        "success",
        "empty",
        "drift",
        "401",
        "403",
        "429",
        "503",
        "timeout",
        "cancelled",
        "secret-reflection",
    ],
)
def test_new_free_slot_source_is_governed_and_replayable(tmp_path, outcome):
    async def run():
        d = dossier()
        m = manifest(d)
        a = NewSourceAdapter()
        calls = []
        reply = {
            "timestamp": 999,
            "slot": 100,
            "rows": [
                {
                    "pool": address(10),
                    "mints": [address(11), address(12)],
                    "venue": "unknown-venue",
                }
            ],
        }

        def handler(req):
            calls.append(req)
            if outcome == "timeout":
                raise httpx.ReadTimeout("private data", request=req)
            if outcome == "cancelled":
                raise asyncio.CancelledError()
            if outcome == "empty":
                payload = {"rows": []}
            elif outcome == "drift":
                payload = {"changed": "schema"}
            elif outcome == "secret-reflection":
                payload = {
                    **reply,
                    "message": "Bearer TOP-SECRET",
                    "api_key": "TOP-SECRET",
                }
            else:
                payload = reply
            return httpx.Response(
                int(outcome) if outcome.isdigit() else 200,
                json=payload,
                headers={"retry-after": "10"},
            )

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
            {
                d.profile.profile_id: d.profile.entitlement(
                    expires_at_epoch_seconds=2000
                )
            },
            clock=lambda: 1002,
            wall_clock=lambda: 1002,
        )
        journal = RecoverableStreamJournal(tmp_path / "events.sqlite")
        evidence = CampaignEvidenceStore(journal, m, wall_ns=lambda: 1002 * 10**9)
        catalog = load_market_source_catalog().with_intake(d.catalog_entry())
        intake = SourceIntakePlane(
            catalog,
            gov,
            transport,
            evidence,
            wall_ns=lambda: 1002 * 10**9,
            credential_headers={
                d.profile.profile_id: {"Authorization": "Bearer TOP-SECRET"}
            },
        )
        if outcome == "cancelled":
            with pytest.raises(asyncio.CancelledError):
                await intake.collect(d, a)
        else:
            records, envelope = await intake.collect(d, a)
            assert envelope["classification"] == "DISCOVERY_ONLY"
            if outcome in ("success", "secret-reflection"):
                assert len(records) == 1
                assert (
                    envelope["source_provided_time"] == 999 and envelope["slot"] == 100
                )
                rows = deduplicate_candidates(records)
                assert all(
                    r["classification"] == "DISCOVERY_ONLY"
                    and r["exact_state_ready"] is False
                    for r in rows.values()
                )
            else:
                assert not records
            if outcome == "429":
                assert (
                    envelope["quality_state"] == "rate-limited"
                    and envelope["retry_after"] == "10"
                )
            if outcome == "empty":
                assert envelope["quality_state"] == "empty-response"
        assert len(calls) == 1
        before = evidence.replay()
        head = evidence.head
        assert any(e.get("kind") == "source_observation" for e in before)
        if outcome == "secret-reflection":
            assert "TOP-SECRET" not in json.dumps(before)
            assert any(e.get("redaction_applied") for e in before)
        journal.close()
        journal = RecoverableStreamJournal(tmp_path / "events.sqlite")
        evidence = CampaignEvidenceStore(journal, m, wall_ns=lambda: 1002 * 10**9)
        assert evidence.replay() == before and evidence.head == head
        assert len(calls) == 1  # replay did not invoke transport
        journal.close()
        await transport.aclose()
        await client.aclose()

    asyncio.run(run())


def test_intake_rejects_promotion_stale_docs_and_schema_bypass():
    d = dossier()
    with pytest.raises(ValueError, match="DISCOVERY_ONLY"):
        replace(d, classification="EXACT_SHADOW")
    with pytest.raises(ValueError, match="capability"):
        replace(d, capabilities=("exact-output",))
    with pytest.raises(ValueError, match="STALE"):
        d.require_current(100000 * 10**9)
    with pytest.raises(ValueError):
        replace(d, slot_id="FREE-SOURCE-065")
    with pytest.raises(ValueError):
        SourceReadRequest(
            "https://new.test/pools", semantic_headers=(("Authorization", "secret"),)
        )


def test_dedup_is_source_order_independent_and_preserves_provenance():
    c = Candidate(address(1), (address(2), address(3)), "venue-a")
    c2 = replace(c, mints=tuple(reversed(c.mints)), venue_label="indexed-alias")
    records = [
        (c, {"source_id": "a", "raw_evidence_id": "x"}),
        (c2, {"source_id": "b", "raw_evidence_id": "y"}),
    ]
    left = deduplicate_candidates(records)
    right = deduplicate_candidates(list(reversed(records)))
    assert left == right and len(left) == 1
    assert len(next(iter(left.values()))["provenance"]) == 2


def test_templates_use_original_blank_slots_and_builtin_dossiers_are_current():
    assert (
        blank_source_template("FREE-SOURCE-001")["planning_slot"]["source_name"] == ""
    )
    assert (
        blank_source_template("FREE-SOURCE-064")["sources"][0]["dossier"][
            "classification"
        ]
        == "DISCOVERY_ONLY"
    )
    with pytest.raises(ValueError):
        blank_source_template("FREE-SOURCE-065")
    from pathlib import Path

    sources = load_sources(
        Path(__file__).parents[1] / "config/qualification/representative-sources.json"
    )
    assert {d.source_id for d, _ in sources} == {
        "dexscreener",
        "geckoterminal",
        "raydium",
    }
    for d, a in sources:
        assert d.schema_fingerprint == digest(a.schema_contract())
        assert d.profile.endpoint == a.request().url


def test_manifest_safety_cannot_be_reinterpreted_on_replay():
    m = manifest(dossier())
    raw = m.to_dict()
    raw["safety"]["signer_reachable"] = True
    with pytest.raises(ValueError, match="SAFETY"):
        manifest_from_dict(raw)


def test_campaign_import_graph_cannot_load_signer_or_submission(tmp_path):
    # This is an import guard in a fresh interpreter, including the installed runtime modules.
    import subprocess, sys

    code = """
import importlib.abc,sys
class Guard(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.startswith(('src.signer','src.signing','src.execution.senders','src.submission','isolated_signer_service')):
   raise AssertionError('forbidden read-only import: '+fullname)
sys.meta_path.insert(0,Guard())
from src.qualification_campaign.cli import blank_source_template
assert blank_source_template('FREE-SOURCE-001')['planning_slot']['status']=='BLANK_RESEARCH_SLOT'
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
