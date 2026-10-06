"""One bounded real, read-only slice using the clean QPR campaign factory."""

import argparse
import asyncio
from collections import Counter
from dataclasses import asdict, replace
import hashlib
import gzip
import json
import os
from pathlib import Path
import time

from src.market.streams import RecoverableStreamJournal, RawStreamEvent
from src.provider_governance import ProviderGovernance
from src.qualification_campaign.evidence import CampaignEvidenceStore
from src.qualification_campaign.identity import (
    CampaignManifest,
    canonical_bytes,
    digest,
    manifest_from_dict,
)
from src.research_economic_graph import (
    AssetRegistry,
    CampaignSeed,
    ResearchEconomicGraph,
    VerificationQueue,
)
from src.research_economic_graph.registry import DEFAULT_PACK
from .intake import SuiIntakePlane, sui_transport, ingest_research, validate_capture
from .models import SuiCandidate, SuiReadRequest, SuiSourceProfile, sha
from .sources import (
    PoolIndexAdapter,
    ScallopRateAdapter,
    checkpoint_request,
    object_request,
)

BASE_SHA = "8c59759b491b6318f259138671dccfea25f2752e"


def default_profiles(pins):
    rows = [
        (
            "deepbook-index",
            "MystenLabs",
            "MystenLabs",
            "mysten-deepbook-index",
            "https://deepbook-indexer.mainnet.mystenlabs.com/get_pools",
            "https://docs.sui.io/standards/deepbookv3-indexer",
            "deepbook",
            "GET",
            "pool-index",
        ),
        (
            "aftermath-pools",
            "Aftermath",
            "AftermathFinance",
            "aftermath-index",
            "https://aftermath.finance/api/pools",
            "https://github.com/AftermathFinance/aftermath-ts-sdk",
            "aftermath",
            "POST",
            "pool-index",
        ),
        (
            "cetus-pools",
            "Cetus",
            "CetusProtocol",
            "cetus-index",
            "https://api-sui.cetus.zone/v2/sui/stats_pools",
            "https://github.com/CetusProtocol/cetus-clmm-sui-sdk",
            "cetus",
            "GET",
            "pool-index",
        ),
        (
            "scallop-rates",
            "Scallop",
            "scallop-io",
            "scallop-index",
            "https://sdk.api.scallop.io/api/market/migrate",
            "https://github.com/scallop-io/sui-scallop-sdk",
            "scallop",
            "GET",
            "structural-rates",
        ),
        (
            "sui-graphql-smoke",
            "MystenLabs",
            "MystenLabs",
            "mysten-sui-public",
            "https://graphql.mainnet.sui.io/graphql",
            "https://github.com/MystenLabs/ts-sdks",
            "graphql",
            "POST",
            "checkpoint",
        ),
    ]
    base = tuple(
        SuiSourceProfile(
            key,
            provider,
            operator,
            group,
            url,
            docs,
            digest(pins[pin]),
            method,
            purpose,
            pin,
            campaign_attempt_cap=12,
            smoke_only=True,
        )
        for key, provider, operator, group, url, docs, pin, method, purpose in rows
    )
    base = tuple(
        (
            replace(
                p,
                max_response_bytes=pins["aftermath"]["engineering_budget"][
                    "max_response_bytes"
                ],
                max_json_nodes=pins["aftermath"]["engineering_budget"][
                    "max_json_nodes"
                ],
            )
            if p.source_kind == "aftermath"
            else p
        )
        for p in base
    )
    books = tuple(
        SuiSourceProfile(
            "deepbook-book-" + book["name"],
            "MystenLabs",
            "MystenLabs",
            "mysten-deepbook-index",
            "https://deepbook-indexer.mainnet.mystenlabs.com/orderbook/" + book["name"],
            "https://docs.sui.io/standards/deepbookv3-indexer",
            digest(pins["deepbook"]),
            "GET",
            "book-reference",
            "deepbook-book",
            campaign_attempt_cap=1,
            allowed_query_parameters=("depth", "level"),
        )
        for book in pins["deepbook"]["priority_book_identifiers"]
    )
    return (*base[:4], *books, base[-1])


async def capture(root, pack, output):
    if output.exists():
        raise ValueError("SUI_NEW_CAMPAIGN_OUTPUT_REQUIRED")
    registry = AssetRegistry.load(pack / "ASSET_REGISTRY_V2.json")
    seed = CampaignSeed.load(registry, pack)
    pins = json.loads((root / "config/gpr03_sui_source_pins.json").read_text())
    profiles = default_profiles(pins)
    configuration = {
        "gpr.registry": registry.configuration,
        "gpr.seed": seed.configuration,
        "gpr03.source_pins": pins,
        "gpr03.capture_policy": {
            "base_sha": BASE_SHA,
            "maximum_pools": 9,
            "maximum_attempts": 18,
            "read_only": True,
            "shadow_only": True,
            "production_promotion": False,
            "identity_policy": "MISSING_REVIEWED_DECIMALS_REPRESENTATION_BINDINGS",
            "exact_decoder": "MISSING_REVIEWED_CHECKPOINT_DEPTH_FEE_LAYOUT",
            "public_state_source": "SMOKE_ONLY_NO_QUORUM_AUTHORITY",
        },
    }
    manifest = CampaignManifest.create(
        root,
        main_sha=BASE_SHA,
        configuration=configuration,
        sources={p.profile_id: asdict(p) for p in profiles},
    )
    output.mkdir(parents=True)
    started = time.time_ns()
    journal = RecoverableStreamJournal(output / "evidence.sqlite")
    evidence = CampaignEvidenceStore(journal, manifest)
    governance = ProviderGovernance(
        {p.profile_id: p.entitlement(int(time.time()) + 3600) for p in profiles}
    )
    outcomes = []
    pool_capture_refs = {}
    book_capture_refs = {}
    deepbook_index = None
    async with sui_transport({p.hostname for p in profiles}, os.environ) as transport:
        intake = SuiIntakePlane(governance, transport, evidence)
        for p in profiles[:4]:
            request = SuiReadRequest(
                p.method, p.endpoint, p.purpose, body={} if p.method == "POST" else None
            )
            adapter = (
                ScallopRateAdapter()
                if p.purpose == "structural-rates"
                else PoolIndexAdapter(
                    {
                        "deepbook-index": "deepbook",
                        "aftermath-pools": "aftermath",
                        "cetus-pools": "cetus",
                    }[p.profile_id]
                )
            )
            ref, raw = await intake.collect(p, request, adapter)
            if p.source_kind == "deepbook" and raw["quality"] == "accepted":
                deepbook_index = raw["raw_payload"]
            outcomes.append(
                {
                    "profile": p.profile_id,
                    "ref": ref,
                    "quality": raw["quality"],
                    "http_status": raw.get("http_status"),
                }
            )
        p = profiles[-1]
        ref, raw = await intake.collect(p, checkpoint_request(p.endpoint))
        outcomes.append(
            {
                "profile": p.profile_id,
                "ref": ref,
                "quality": raw["quality"],
                "http_status": raw.get("http_status"),
            }
        )
        if raw["quality"] == "accepted-read-only":
            try:
                checkpoint = raw["raw_payload"]["data"]["checkpoint"]["sequenceNumber"]
                for pool in seed.pools:
                    candidate = SuiCandidate(
                        pool.canonical_object_id,
                        tuple(
                            registry.resolve(r).canonical_identifier
                            for r in pool.representations
                        ),
                        "deepbook",
                    )
                    obj_ref, obj_raw = await intake.collect(
                        p, object_request(p.endpoint, candidate, checkpoint)
                    )
                    outcomes.append(
                        {
                            "profile": p.profile_id,
                            "pool_id": candidate.pool_id,
                            "ref": obj_ref,
                            "quality": obj_raw["quality"],
                            "http_status": obj_raw.get("http_status"),
                        }
                    )
                    pool_capture_refs[candidate.pool_id] = obj_ref
            except (ValueError, KeyError, TypeError) as exc:
                evidence.append(
                    "gpr03-checkpoint-rejection",
                    {
                        "kind": "gpr03_checkpoint_schema_rejection",
                        "raw_ref": ref,
                        "reason": type(exc).__name__,
                    },
                    observed_at_ns=time.time_ns(),
                )
        if isinstance(deepbook_index, list):
            for book, p in zip(
                pins["deepbook"]["priority_book_identifiers"],
                profiles[4:-1],
                strict=True,
            ):
                pool = next(
                    (
                        pool
                        for pool in seed.pools
                        if pool.canonical_object_id == book["pool_id"]
                    ),
                    None,
                )
                row = next(
                    (
                        r
                        for r in deepbook_index
                        if r.get("pool_id") == book["pool_id"]
                        and r.get("pool_name") == book["name"]
                    ),
                    None,
                )
                if pool is None or row is None:
                    continue
                candidate = SuiCandidate(
                    row["pool_id"],
                    (row["base_asset_id"], row["quote_asset_id"]),
                    "deepbook",
                )
                if {
                    registry.by_identifier("sui-mainnet", t).asset_id
                    for t in candidate.coin_types
                } != set(pool.representations):
                    continue
                book_ref, book_raw = await intake.collect(
                    p,
                    SuiReadRequest(
                        "GET",
                        p.endpoint,
                        "book-reference",
                        params=(("depth", "20"), ("level", "2")),
                    ),
                )
                book_capture_refs[pool.canonical_object_id] = book_ref
                outcomes.append(
                    {
                        "profile": p.profile_id,
                        "pool_id": pool.canonical_object_id,
                        "ref": book_ref,
                        "quality": book_raw["quality"],
                        "http_status": book_raw.get("http_status"),
                    }
                )
    graph = ingest_research(ResearchEconomicGraph(registry, seed), evidence)
    graph_ref = graph.persist(evidence, observed_at_ns=time.time_ns())
    queue = VerificationQueue(graph, evidence)
    queue_ref = queue.persist(
        {},
        top_k=16,
        per_chain_budget={"sui-mainnet": 16, "solana-mainnet": 0},
        now_ns=time.time_ns(),
    )
    restored = ResearchEconomicGraph.replay(evidence, registry, seed)
    requests = VerificationQueue(restored, evidence).replay(queue_ref)
    evidence.append(
        "gpr03-stop",
        {
            "kind": "gpr03_stop",
            "qualification": "BLOCKED",
            "blockers": [
                "reviewed-decimals-and-full-representation-policy-missing",
                "independent-nonsmoke-state-provider-bindings-missing",
                "verified-dynamic-object-depth-fee-decoder-missing",
            ],
            "gpr04_started": False,
        },
        observed_at_ns=time.time_ns(),
    )
    rows = evidence.replay()
    payload = canonical_bytes(
        {
            "events": [asdict(e) for e in journal.events(available_at_ns=2**63 - 1)],
            "expanded_rows": rows,
        }
    )
    (output / "retained-evidence.json").write_bytes(payload)
    summary = {
        "schema_version": "gpr03.campaign-report.v1",
        "base_sha": BASE_SHA,
        "capture_code_head": manifest.repository_sha,
        "campaign_id": manifest.campaign_id,
        "manifest": manifest.to_dict(),
        "started_at_ns": started,
        "finished_at_ns": time.time_ns(),
        "outcomes": outcomes,
        "quality_counts": dict(Counter(o["quality"] for o in outcomes)),
        "physical_attempts": sum(
            r.get("physical_attempt_started") is True for r in rows
        ),
        "reserved_attempts": sum(r.get("kind") == "attempt" for r in rows),
        "candidate_count": sum(r.get("kind") == "gpr03_sui_candidate" for r in rows),
        "registered_discovery_relations": sum(
            r.relation_id.startswith("gpr03:") for r in graph.relations.values()
        ),
        "indexed_book_reads": len(book_capture_refs),
        "structural_rate_count": sum(
            r.get("kind") == "gpr03_structural_rate" for r in rows
        ),
        "known_deepbook_identifiers": len(seed.pools),
        "deepbook_qualification_gaps": [
            {
                "pool_id": p.canonical_object_id,
                "representations": list(p.representations),
                "checkpoint_object_capture_ref": pool_capture_refs.get(
                    p.canonical_object_id
                ),
                "indexed_book_capture_ref": book_capture_refs.get(
                    p.canonical_object_id
                ),
                "book_reference": p.canonical_object_id,
                "book_reference_evidence_state": "IDENTIFIER_VERIFIED",
                "book_depth_state": "BOOK_DEPTH_UNQUALIFIED",
                "reason": (
                    "checkpoint-state-not-observed"
                    if p.canonical_object_id not in pool_capture_refs
                    else "reviewed-dynamic-field-book-and-fee-decoder-missing"
                ),
            }
            for p in seed.pools
        ],
        "measurement_availability": {
            "representation_basis": "UNMEASURED: no comparable verified market quotes",
            "lst_exchange_rate_vs_market": "UNMEASURED: no paired timestamp/unit-qualified structural and market quote",
            "deepbook_vs_amm_router": "UNMEASURED: BOOK_DEPTH_UNQUALIFIED",
            "xaum_vs_xau_usd": "UNMEASURED: governed oracle source/feed/entitlement binding missing",
            "usdc_solana_portal_basis": "UNMEASURED: representation-specific market quote unavailable",
        },
        "graph_ref": graph_ref,
        "queue_ref": queue_ref,
        "graph_identity": graph.identity,
        "queued_requests": len(requests),
        "journal_head": evidence.head,
        "retained_evidence_sha256": hashlib.sha256(payload).hexdigest(),
        "qualification_receipts": 0,
        "measured_anomalies": None,
        "replay_identical": graph.identity == restored.identity,
        "blockers": rows[-1]["blockers"],
        "safety": manifest.to_dict()["safety"],
    }
    (output / "summary.json").write_bytes(canonical_bytes(summary))
    journal.close()
    return summary


def replay_capture(capture_dir, output, *, pack=DEFAULT_PACK):
    """Import exact retained journal events and reproduce graph/queue offline."""
    if output.exists():
        raise ValueError("SUI_NEW_REPLAY_OUTPUT_REQUIRED")
    summary = json.loads((capture_dir / "summary.json").read_text())
    plain = capture_dir / "retained-evidence.json"
    if plain.exists():
        encoded = plain.read_bytes()
    else:
        with gzip.open(capture_dir / "retained-evidence.json.gz", "rb") as handle:
            encoded = handle.read(64 * 1024 * 1024 + 1)
    if len(encoded) > 64 * 1024 * 1024:
        raise ValueError("SUI_CAPTURE_EXPORT_SIZE_LIMIT")
    if hashlib.sha256(encoded).hexdigest() != summary["retained_evidence_sha256"]:
        raise ValueError("SUI_CAPTURE_EXPORT_HASH_MISMATCH")
    retained = json.loads(encoded)
    manifest = manifest_from_dict(summary["manifest"])
    if manifest.campaign_id != summary["campaign_id"]:
        raise ValueError("SUI_CAPTURE_MANIFEST_MISMATCH")
    output.mkdir(parents=True)
    journal = RecoverableStreamJournal(output / "evidence.sqlite")
    for event, expanded in zip(
        retained["events"], retained["expanded_rows"], strict=True
    ):
        raw = RawStreamEvent(**event)
        small = json.loads(raw.payload_json)
        if small.get("kind") == "blob_reference":
            sha(small["raw_payload_ref"])
            blobs = Path(str(output / "evidence.sqlite") + ".blobs")
            blobs.mkdir(exist_ok=True)
            if digest(expanded) != small["raw_payload_hash"]:
                raise ValueError("SUI_CAPTURE_BLOB_EXPORT_HASH_MISMATCH")
            (blobs / (small["raw_payload_ref"] + ".json")).write_bytes(
                canonical_bytes(expanded)
            )
        journal.append(raw)
    evidence = CampaignEvidenceStore(journal, manifest)
    if (
        digest(evidence.replay()) != digest(retained["expanded_rows"])
        or evidence.head != summary["journal_head"]
    ):
        raise ValueError("SUI_CAPTURE_JOURNAL_EXPORT_MISMATCH")
    for event, row in zip(retained["events"], retained["expanded_rows"], strict=True):
        if row.get("kind") == "gpr03_sui_raw":
            validate_capture(evidence, RawStreamEvent(**event).identity)
    registry = AssetRegistry.load(pack / "ASSET_REGISTRY_V2.json")
    seed = CampaignSeed.load(registry, pack)
    graph = ResearchEconomicGraph.replay(evidence, registry, seed)
    reconstructed = ingest_research(ResearchEconomicGraph(registry, seed), evidence)
    requests = VerificationQueue(graph, evidence).replay(summary["queue_ref"])
    if (
        graph.identity != reconstructed.identity
        or graph.identity != summary["graph_identity"]
        or len(requests) != summary["queued_requests"]
    ):
        raise ValueError("SUI_CAPTURE_GRAPH_QUEUE_REPLAY_MISMATCH")
    journal.close()
    return {
        "capture_code_head": manifest.repository_sha,
        "campaign_id": manifest.campaign_id,
        "replay_identical": True,
        "queued_requests": len(requests),
        "network_reads": 0,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Bounded Sui capture; no signer/sender/executor"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--replay", type=Path)
    args = parser.parse_args()
    if args.replay is not None:
        print(
            json.dumps(
                replay_capture(args.replay, args.output, pack=args.pack), indent=2
            )
        )
        return
    result = asyncio.run(
        capture(Path(__file__).resolve().parents[2], args.pack, args.output.resolve())
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "capture_code_head",
                    "campaign_id",
                    "physical_attempts",
                    "candidate_count",
                    "structural_rate_count",
                    "quality_counts",
                    "replay_identical",
                    "blockers",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
