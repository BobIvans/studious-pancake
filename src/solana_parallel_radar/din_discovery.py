"""DIN-01 bounded indexed discovery using restored QPR/GPR owners only."""

import argparse
import asyncio
from dataclasses import asdict
import hashlib
import gzip
import json
from pathlib import Path
import subprocess
import time

from src.durability import UnifiedLifecycleAuthority
from src.market.discovery import DiscoveryRequest
from src.market.source_catalog import load_market_source_catalog
from src.market.streams import RecoverableStreamJournal, RawStreamEvent
from src.provider_governance import ProviderGovernance
from src.qualification_campaign.evidence import CampaignEvidenceStore
from src.qualification_campaign.identity import (
    CampaignManifest,
    canonical_bytes,
    digest,
    manifest_from_dict,
)
from src.qualification_campaign.profiles import ProviderProfile
from src.qualification_campaign.sources import (
    SourceDossier,
    Candidate,
    SourceIntakePlane,
    deduplicate_candidates,
)
from src.qualification_campaign.transport import campaign_transport
from src.research_economic_graph import (
    AssetRegistry,
    CampaignSeed,
    ResearchEconomicGraph,
    SolanaResearchAdapter,
)
from src.routing.transport import TransportPolicy
from src.solana_parallel_radar.radar import BatchRadarAdapter, TargetedCatalogAdapter

SOURCES = {
    "dexscreener": "dexscreener",
    "geckoterminal": "coingecko",
    "raydium": "raydium",
    "meteora-dlmm": "meteora",
}


def reviewed_sources(mints, pins):
    """Unavailable docs block the source; never synthesize a review or quota."""
    sources, blocked = [], []
    for source, operator in SOURCES.items():
        pin = pins.get(source)
        if not pin:
            blocked.append(
                {
                    "source_id": source,
                    "reason": "CURRENT_DOCS_PIN_MISSING",
                    "physical_calls": 0,
                }
            )
            continue
        data = Path(pin["path"]).read_bytes()
        if (
            not data
            or len(data) > 2_000_000
            or hashlib.sha256(data).hexdigest() != pin["sha256"]
        ):
            raise ValueError("DOCS_PIN_HASH_OR_SIZE_MISMATCH")
        adapter = (
            BatchRadarAdapter(mints)
            if source == "dexscreener"
            else TargetedCatalogAdapter(DiscoveryRequest(source), mints)
        )
        request = adapter.request()
        profile = ProviderProfile(
            "din01-" + source,
            source,
            operator,
            operator + "-indexed",
            request.url,
            pin["url"],
            role="discovery",
            request_limit=1,
            window_seconds=60,
            campaign_attempt_cap=1,
            smoke_only=True,
            allowed_query_parameters=tuple(k for k, _ in request.params),
        )
        dossier = SourceDossier(
            source,
            "DIN-01 bounded " + source,
            profile,
            pin["checked_at"],
            pin["sha256"],
            "din01.indexed-request.v1",
            "din01.indexed-response.v1",
            digest(adapter.schema_contract()),
            pin["url"],
        )
        dossier.require_current(time.time_ns())
        sources.append((dossier, adapter))
    return tuple(sources), tuple(blocked)


async def capture(root, output, *, mints, pins):
    if output.exists():
        raise ValueError("NEW_CAMPAIGN_OUTPUT_REQUIRED")
    sources, blocked = reviewed_sources(mints, pins)
    if not sources:
        raise ValueError("NO_CURRENT_REVIEWED_SOURCE")
    registry = AssetRegistry.load()
    seed = CampaignSeed.load(registry)
    main_sha = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "origin/main^{commit}"], text=True
    ).strip()
    manifest = CampaignManifest.create(
        root,
        main_sha=main_sha,
        configuration={
            "gpr.registry": registry.configuration,
            "gpr.seed": seed.configuration,
            "din01": {
                "maximum_physical_calls": len(sources),
                "mints": mints,
                "blocked_sources": blocked,
                "budget_class": "ENGINEERING_ONE_SHOT_NOT_PUBLISHED_ENTITLEMENT",
                "max_response_bytes": 1_048_576,
            },
        },
        sources={
            key: value
            for d, _ in sources
            for key, value in (
                (d.source_id, asdict(d)),
                (d.profile.profile_id, asdict(d.profile)),
            )
        },
    )
    output.mkdir(parents=True)
    journal = RecoverableStreamJournal(output / "evidence.sqlite")
    authority = UnifiedLifecycleAuthority(
        output / "authority.sqlite",
        release_digest=manifest.runtime_authority_sha256,
        policy_bundle_hash=manifest.campaign_id,
    )
    try:
        evidence = CampaignEvidenceStore(journal, manifest)
        gov = ProviderGovernance(
            {
                d.profile.profile_id: d.profile.entitlement(
                    expires_at_epoch_seconds=int(time.time()) + 600
                )
                for d, _ in sources
            },
            store=authority,
        )
        receipts, records = [], []
        async with campaign_transport(
            {d.profile.hostname for d, _ in sources},
            policy=TransportPolicy(max_attempts=1),
        ) as transport:
            intake = SourceIntakePlane(
                load_market_source_catalog(), gov, transport, evidence
            )
            for dossier, adapter in sources:
                evidence.append(
                    dossier.source_id,
                    {"kind": "source_dossier", "dossier": asdict(dossier)},
                    observed_at_ns=time.time_ns(),
                )
                gathered, receipt = await intake.collect(dossier, adapter)
                records.extend(gathered)
                receipts.append(
                    {k: v for k, v in receipt.items() if k != "raw_payload"}
                )
        universe = deduplicate_candidates(records)
        graph = SolanaResearchAdapter(ResearchEconomicGraph(registry, seed)).ingest(
            evidence
        )
        expanded = evidence.replay()
        export = {
            "events": [asdict(e) for e in journal.events(available_at_ns=2**63 - 1)],
            "expanded_rows": expanded,
        }
        result = {
            "schema_version": "din01.bounded-discovery.v1",
            "manifest": manifest.to_dict(),
            "campaign_id": manifest.campaign_id,
            "receipts": receipts,
            "blocked_sources": blocked,
            "candidate_receipts": len(records),
            "deduplicated_candidates": len(universe),
            "graph_identity": graph.identity,
            "journal_head": evidence.head,
            "retained_evidence_sha256": hashlib.sha256(
                canonical_bytes(export)
            ).hexdigest(),
            "exact_status": "BLOCKED",
            "paper_status": "BLOCKED",
            "production_status": "BLOCKED",
            "sign_enabled": False,
            "send_enabled": False,
            "blockers": [
                "INDEPENDENT_ROOTED_RPC_PROFILES_REQUIRED",
                "IDENTITY_DECIMALS_TOKEN_PROGRAM_PROOF_REQUIRED",
                "DYNAMIC_UNIVERSE_EXACT_HANDOFF_NOT_ADMITTED",
                "PUBLISHED_PROVIDER_ENTITLEMENTS_NOT_REVERIFIED",
            ],
        }
        (output / "retained-evidence.json").write_bytes(canonical_bytes(export))
        (output / "summary.json").write_bytes(canonical_bytes(result))
        return result
    finally:
        journal.close()
        authority.close()


def replay(capture_dir, output):
    """Restore existing QPR event identities and recompute the research graph."""
    if output.exists():
        raise ValueError("NEW_REPLAY_OUTPUT_REQUIRED")
    summary = json.loads((capture_dir / "summary.json").read_text())
    plain = capture_dir / "retained-evidence.json"
    if plain.exists():
        encoded = plain.read_bytes()
    else:
        with gzip.open(capture_dir / "retained-evidence.json.gz", "rb") as handle:
            encoded = handle.read(16_000_001)
    if (
        len(encoded) > 16_000_000
        or hashlib.sha256(encoded).hexdigest() != summary["retained_evidence_sha256"]
    ):
        raise ValueError("RETAINED_EXPORT_HASH_OR_SIZE_MISMATCH")
    retained = json.loads(encoded)
    manifest = manifest_from_dict(summary["manifest"])
    if manifest.campaign_id != summary["campaign_id"]:
        raise ValueError("CAMPAIGN_GENERATION_MISMATCH")
    output.mkdir(parents=True)
    journal = RecoverableStreamJournal(output / "evidence.sqlite")
    try:
        for event, expanded in zip(
            retained["events"], retained["expanded_rows"], strict=True
        ):
            raw = RawStreamEvent(**event)
            small = json.loads(raw.payload_json)
            if small.get("kind") == "blob_reference":
                name = small["raw_payload_ref"]
                if name != digest(expanded) or small["raw_payload_hash"] != name:
                    raise ValueError("RETAINED_BLOB_HASH_MISMATCH")
                blobs = Path(str(output / "evidence.sqlite") + ".blobs")
                blobs.mkdir(exist_ok=True)
                (blobs / (name + ".json")).write_bytes(canonical_bytes(expanded))
            journal.append(raw)
        evidence = CampaignEvidenceStore(journal, manifest)
        rows = evidence.replay()
        if evidence.head != summary["journal_head"] or canonical_bytes(
            rows
        ) != canonical_bytes(retained["expanded_rows"]):
            raise ValueError("JOURNAL_REPLAY_MISMATCH")
        registry = AssetRegistry.load()
        graph = SolanaResearchAdapter(
            ResearchEconomicGraph(registry, CampaignSeed.load(registry))
        ).ingest(evidence)
        records = [
            (Candidate(**r["candidate"]), r["provenance"])
            for r in rows
            if r["kind"] == "discovery_candidate"
        ]
        if (
            graph.identity != summary["graph_identity"]
            or len(deduplicate_candidates(records))
            != summary["deduplicated_candidates"]
        ):
            raise ValueError("GRAPH_OR_CANDIDATE_REPLAY_MISMATCH")
        return {
            "campaign_id": manifest.campaign_id,
            "replay_identical": True,
            "network_reads": 0,
            "deduplicated_candidates": summary["deduplicated_candidates"],
        }
    finally:
        journal.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--docs-pins", type=Path)
    parser.add_argument("--mint", action="append")
    args = parser.parse_args()
    if args.replay:
        print(json.dumps(replay(args.replay, args.output)))
        return
    if not args.docs_pins or not args.mint:
        parser.error("capture requires --docs-pins and --mint")
    result = asyncio.run(
        capture(
            Path(__file__).resolve().parents[2],
            args.output,
            mints=tuple(args.mint),
            pins=json.loads(args.docs_pins.read_text()),
        )
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "campaign_id",
                    "candidate_receipts",
                    "deduplicated_candidates",
                    "blocked_sources",
                    "exact_status",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
