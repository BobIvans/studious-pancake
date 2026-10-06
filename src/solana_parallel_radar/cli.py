"""Bounded real GPR-02 capture and offline deterministic replay."""

import argparse
import asyncio
from contextlib import AsyncExitStack
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from collections import Counter

from src.durability import UnifiedLifecycleAuthority
from src.market.discovery import DiscoveryRequest
from src.market.native_cpmm_capture import GovernedNativeCpmmCollector
from src.market.source_catalog import load_market_source_catalog
from src.market.streams import RecoverableStreamJournal
from src.provider_governance import ProviderGovernance
from src.providers.raydium_cpmm_native import NativeCaptureError
from src.qualification_campaign.evidence import CampaignEvidenceStore
from src.qualification_campaign.identity import (
    CampaignManifest,
    canonical_bytes,
    digest,
    manifest_from_dict,
)
from src.qualification_campaign.profiles import ProviderProfile, public_rpc_profile
from src.qualification_campaign.rpc import NativeRootedSnapshotProvider
from src.qualification_campaign.sources import (
    SourceDossier,
    SourceIntakePlane,
    SourceReadRequest,
)
from src.qualification_campaign.transport import campaign_transport
from src.research_economic_graph import (
    AssetRegistry,
    CampaignSeed,
    ResearchEconomicGraph,
    SolanaResearchAdapter,
    VerificationQueue,
    IdentityExpectation,
    StartupIdentityPolicy,
)
from src.research_economic_graph.graph import retained_records
from src.research_economic_graph.registry import DEFAULT_PACK
from src.routing.transport import TransportPolicy
from src.strategy.exact_cpmm_capacity import MAINNET_GENESIS, RAYDIUM_CPMM_PROGRAM_ID
from .funnel import priority_pairs, persist_funnel_plan, compare_quotes
from .probes import (
    ReadContract,
    GovernedReadPlane,
    jupiter_request,
    normalized_reference,
    normalize_manifest_book,
)
from .radar import BatchRadarAdapter, ManifestRadarAdapter, TargetedCatalogAdapter
from .structural import (
    CLOCK,
    account_bytes,
    sanctum_stake_pool_reference,
    structural_residual_bps,
)
from .token2022 import (
    Token2022SemanticsPolicy,
    decode_token2022_mint,
    inspect_token2022_semantics,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "config/qualification/gpr02-solana-contracts.json"


def source_configuration(registry, contracts, *, checked_at=None):
    mints = tuple(
        sorted(
            {a.canonical_identifier for pair in priority_pairs(registry) for a in pair}
        )
    )
    adapters = (
        ("manifest", ManifestRadarAdapter(mints)),
        ("dexscreener", BatchRadarAdapter(mints)),
        (
            "meteora-dlmm",
            TargetedCatalogAdapter(DiscoveryRequest("meteora-dlmm"), mints),
        ),
        ("raydium", TargetedCatalogAdapter(DiscoveryRequest("raydium"), mints)),
    )
    old = json.loads(
        (ROOT / "config/qualification/representative-sources.json").read_text()
    )
    old_dossiers = {r["dossier"]["source_id"]: r["dossier"] for r in old["sources"]}
    result = []
    for source, adapter in adapters:
        profile = ProviderProfile(
            "gpr02-radar-" + source,
            source,
            source,
            source + "-indexed",
            adapter.request().url,
            (
                "https://github.com/CKS-Systems/manifest"
                if source == "manifest"
                else (
                    "https://docs.meteora.ag/api-reference/dlmm/overview"
                    if source == "meteora-dlmm"
                    else old_dossiers[source]["profile"]["official_docs"]
                )
            ),
            role="discovery",
            request_limit=2,
            campaign_attempt_cap=2,
            allowed_query_parameters=tuple(k for k, _ in adapter.request().params),
        )
        # Indexed research uses the published source-owner/roadmap contract where
        # current official provider docs could not be fetched. Do not claim live review.
        docs_hash = (
            contracts["pins"]["manifest"]["files"]["client/ts/src/client.ts"]
            if source == "manifest"
            else (
                old_dossiers[source]["docs_sha256"]
                if source in old_dossiers
                else hashlib.sha256(
                    (DEFAULT_PACK / "SOURCE_MATRIX.md").read_bytes()
                ).hexdigest()
            )
        )
        dossier = SourceDossier(
            source,
            "GPR-02 bounded " + source,
            profile,
            checked_at or datetime.now(UTC).isoformat(),
            docs_hash,
            "gpr02.radar-request.v1",
            "gpr02.radar-response.v1",
            digest(adapter.schema_contract()),
            profile.official_docs,
            renewal_ttl_seconds=86400,
        )
        result.append((dossier, adapter))
    return tuple(result)


def read_contracts(contracts):
    pins = contracts["pins"]
    params = (
        "inputMint",
        "outputMint",
        "amount",
        "slippageBps",
        "swapMode",
        "restrictIntermediateTokens",
        "instructionVersion",
        "onlyDirectRoutes",
        "dexes",
    )
    j = ProviderProfile(
        "gpr02-jupiter-provider",
        "jupiter",
        "jupiter",
        "jupiter-metis-router",
        "https://api.jup.ag/swap/v1/quote",
        "https://dev.jup.ag/api-reference/swap/quote",
        credential_ref="JUPITER_API_KEY",
        role="discovery",
        request_limit=4,
        campaign_attempt_cap=4,
        allowed_query_parameters=params,
    )
    z = ProviderProfile(
        "gpr02-0x-provider",
        "0x",
        "0x",
        "0x-solana-router",
        "https://api.0x.org/solana/swap-instructions",
        "https://docs.0x.org/docs/solana-swap-api/overview",
        credential_ref="ZEROX_API_KEY",
        role="discovery",
        request_limit=2,
        campaign_attempt_cap=2,
    )
    jc = ReadContract(
        "gpr02-jupiter-reference",
        j,
        pins["jupiter"]["git_sha"],
        pins["jupiter"]["files"]["swap/v1/get-quote.mdx"],
        pins["jupiter"]["files"]["openapi-spec/swap/v1/swap.yaml"],
        auth_header="x-api-key",
    )
    zc = ReadContract(
        "gpr02-0x-preview",
        z,
        pins["0x"]["git_sha"],
        pins["0x"]["files"]["fern/docs/pages/solana-swap-api/guides/get-started.mdx"],
        pins["0x"]["files"]["fern/openapi-solana-swap.json"],
        method="POST",
        auth_header="0x-api-key",
        semantic_headers=(
            ("Accept", "application/json"),
            ("Content-Type", "application/json"),
        ),
    )
    return zc, jc


def load_token_policies(path):
    if path is None:
        return ()
    raw = json.loads(path.read_text())
    return tuple(
        Token2022SemanticsPolicy(
            identity_policy=StartupIdentityPolicy(
                tuple(IdentityExpectation(**e) for e in p.pop("expectations"))
            ),
            **p,
        )
        for p in raw
    )


def manifest_book_contract(contracts, profile):
    pin = contracts["pins"]["manifest"]
    return ReadContract(
        "gpr02-manifest-book",
        profile,
        pin["git_sha"],
        pin["files"]["scripts/stats-server.ts"],
        pin["files"]["scripts/stats_utils/manifestStatsServer.ts"],
        request_endpoint="https://mfx-stats-mainnet.fly.dev/orderbook",
    )


async def structural_capture(
    collectors, evidence, registry, contracts, token_policies, quotes=()
):
    refs = contracts["sanctum_references"]
    token_assets = [registry.resolve("solana-mainnet:" + k) for k in ("USDG", "PYUSD")]
    ids = tuple(
        sorted(
            {
                CLOCK,
                contracts["jlp_reference"]["pool_id"],
                registry.resolve("solana-mainnet:JLP").canonical_identifier,
                *(a.canonical_identifier for a in token_assets),
                *(r["mint"] for r in refs),
                *(r["pool_id"] for r in refs),
            }
        )
    )
    for collector in collectors:
        now = evidence.wall_ns()
        try:
            genesis = (await collector._rpc("getGenesisHash", []))["result"]
            if genesis != MAINNET_GENESIS:
                raise ValueError("SOLANA_MAINNET_GENESIS_MISMATCH")
            response = (
                await collector._rpc(
                    "getMultipleAccounts",
                    [list(ids), {"encoding": "base64", "commitment": "finalized"}],
                )
            )["result"]
            slot, values = response["context"]["slot"], response["value"]
            if (
                type(slot) is not int
                or slot <= 0
                or not isinstance(values, list)
                or len(values) != len(ids)
            ):
                raise ValueError("STRUCTURAL_ACCOUNT_BANK_OR_COUNT_MISMATCH")
            accounts = dict(zip(ids, values, strict=True))
            raw_refs = tuple(
                ref
                for ref, b in retained_records(evidence).items()
                if b.get("kind") == "rpc_observation"
                and b.get("provider_id") == collector.profile.profile_id
            )
            for ref in refs:
                try:
                    row = sanctum_stake_pool_reference(
                        accounts[ref["pool_id"]],
                        accounts[ref["mint"]],
                        accounts[CLOCK],
                        reference=ref,
                        slot=slot,
                    )
                    row.update(
                        provider_id=collector.profile.profile_id,
                        provider_generation=collector.profile.generation,
                        correlation_group=collector.profile.correlation_group,
                        raw_refs=raw_refs,
                        independent_quorum=False,
                        fee_redemption_qualification=False,
                    )
                    for quote in quotes:
                        if (
                            quote.input_mint == ref["mint"]
                            and quote.output_mint
                            == registry.resolve(
                                "solana-mainnet:WSOL"
                            ).canonical_identifier
                            and quote.slot is not None
                            and abs(quote.slot - slot) <= 32
                            and 0
                            <= evidence.wall_ns() - quote.observed_at_ns
                            <= 45_000_000_000
                        ):
                            evidence.append(
                                "gpr02-structural-comparison",
                                {
                                    "kind": "gpr02_lst_market_rate_residual",
                                    "asset_id": ref["asset_id"],
                                    "quote_raw_ref": quote.raw_evidence_ref,
                                    "state_raw_refs": raw_refs,
                                    "residual_bps": structural_residual_bps(
                                        quote.output_amount,
                                        quote.input_amount,
                                        row["lamports_per_raw_unit_numerator"],
                                        row["lamports_per_raw_unit_denominator"],
                                    ),
                                    "fee_redemption_qualified": False,
                                    "exact_graph_allowed": False,
                                },
                                observed_at_ns=evidence.wall_ns(),
                            )
                except (KeyError, ValueError, TypeError) as exc:
                    row = {
                        "kind": "gpr02_structural_rejection",
                        "asset_id": ref["asset_id"],
                        "reason": (
                            str(exc)
                            if isinstance(exc, ValueError)
                            else "STRUCTURAL_SCHEMA_REJECTED"
                        ),
                        "raw_refs": raw_refs,
                    }
                evidence.append("gpr02-structural", row, observed_at_ns=now)
            for asset in token_assets:
                account = accounts[asset.canonical_identifier]
                try:
                    policy = next(
                        (p for p in token_policies if p.asset_id == asset.asset_id),
                        None,
                    )
                    data = account_bytes(account)
                    decode_token2022_mint(
                        data, mint=asset.canonical_identifier, owner=account["owner"]
                    )
                    if policy is None:
                        raise ValueError(
                            "REVIEWED_TOKEN_2022_SEMANTICS_POLICY_REQUIRED"
                        )
                    clock_data = account_bytes(accounts[CLOCK])
                    epoch = int.from_bytes(clock_data[16:24], "little")
                    result = inspect_token2022_semantics(
                        asset, data, account["owner"], policy=policy, epoch=epoch
                    )
                    row = {
                        "kind": "gpr02_token2022_mint_semantics",
                        "inspection": result,
                        "slot": slot,
                        "raw_refs": raw_refs,
                        "independent_quorum": False,
                        "startup_hard_bound_receipt": False,
                    }
                except (ValueError, KeyError, TypeError) as exc:
                    row = {
                        "kind": "gpr02_token2022_rejection",
                        "asset_id": asset.asset_id,
                        "reason": (
                            str(exc)
                            if isinstance(exc, ValueError)
                            else "TOKEN_2022_SCHEMA_REJECTED"
                        ),
                        "raw_refs": raw_refs,
                        "startup_hard_bound_receipt": False,
                    }
                evidence.append("gpr02-token2022", row, observed_at_ns=now)
            evidence.append(
                "gpr02-structural",
                {
                    "kind": "gpr02_jlp_nav_rejection",
                    "reason": "CURRENT_AUM_SUPPLY_ORACLE_STATE_REVIEW_REQUIRED",
                    "slot": slot,
                    "raw_refs": raw_refs,
                    "live_nav_measured": False,
                },
                observed_at_ns=now,
            )
        except (NativeCaptureError, ValueError, KeyError, TypeError) as exc:
            evidence.append(
                "gpr02-structural",
                {
                    "kind": "gpr02_structural_capture_failure",
                    "provider_id": collector.profile.profile_id,
                    "provider_generation": collector.profile.generation,
                    "correlation_group": collector.profile.correlation_group,
                    "reason": (
                        str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                    ),
                    "requested_identifiers": ids,
                    "successful_state_read": False,
                },
                observed_at_ns=now,
            )


def report(evidence, registry, seed):
    events = evidence.replay()
    graph = ResearchEconomicGraph.replay(evidence, registry, seed)
    queue_refs = [
        ref
        for ref, b in retained_records(evidence).items()
        if b.get("kind") == "gpr_verification_queue"
    ]
    requests = VerificationQueue(graph, evidence).replay(queue_refs[-1])
    reads = [
        e
        for e in events
        if e.get("kind")
        in ("source_observation", "gpr02_reference_read", "rpc_observation")
    ]
    outcomes = [
        {
            "source_id": e.get("source_id", e.get("provider_id")),
            "quality_state": e.get("quality_state"),
            "http_status": e.get("http_status"),
            "failure_reason": e.get("failure_reason"),
            "binding_name": e.get("binding_name"),
            "source_generation": e.get("source_generation"),
            "provider_generation": e.get(
                "provider_generation", e.get("source_generation")
            ),
            "correlation_group": e.get("correlation_group"),
        }
        for e in reads
    ]
    candidates = [e for e in events if e.get("kind") == "discovery_candidate"]
    pair_coverage: Counter[str] = Counter()
    for e in candidates:
        try:
            keys = sorted(
                registry.by_identifier("solana-mainnet", mint).asset_key
                for mint in e["candidate"]["mints"]
            )
            pair_coverage["/".join(keys)] += 1
        except ValueError:
            continue
    return {
        "schema_version": "gpr02.solana-handoff.v1",
        "campaign_id": evidence.manifest.campaign_id,
        "capture_repository_sha": evidence.manifest.repository_sha,
        "graph_identity": graph.identity,
        "journal_head": evidence.head,
        "verification_request_ids": [r.identity for r in requests],
        "discovery_candidate_count": sum(
            e.get("kind") == "discovery_candidate" for e in events
        ),
        "unique_pool_count": len({e["candidate_id"] for e in candidates}),
        "candidates_by_source": dict(
            Counter(e["provenance"]["source_id"] for e in candidates)
        ),
        "pair_coverage": dict(sorted(pair_coverage.items())),
        "source_outcomes": outcomes,
        "reserved_attempts": sum(e.get("kind") == "attempt" for e in events),
        "successful_http_reads": sum(e.get("http_status") == 200 for e in reads),
        "quotes_measured": sum(e.get("kind") == "gpr02_quote_preview" for e in events),
        "quote_comparisons": [
            e for e in events if e.get("kind") == "gpr02_quote_comparison"
        ],
        "structural_findings": [
            e
            for e in events
            if e.get("kind", "").startswith(
                (
                    "gpr02_structural",
                    "gpr02_sanctum",
                    "gpr02_token2022",
                    "gpr02_jlp",
                    "gpr02_lst",
                )
            )
        ],
        "native_verification_failures": [
            e
            for e in events
            if e.get("kind") in ("capture_failure", "rooted_snapshot_bundle")
        ],
        "manifest_measurements": [
            e
            for e in events
            if e.get("kind")
            in (
                "gpr02_manifest_payload_metrics",
                "gpr02_manifest_book_reference",
                "gpr02_manifest_book_rejected",
            )
        ],
        "anomaly_recurrence_measured": False,
        "exact_qualification": "BLOCKED",
        "runtime_enabled": False,
        "production_promotion": False,
        "stop_before": "GPR-04",
        "measurement_readiness": (
            "PASS" if any(e.get("http_status") == 200 for e in reads) else "BLOCKED"
        ),
        "blockers": [
            "INDEPENDENT_ROOTED_RPC_PROFILES_REQUIRED",
            "STARTUP_HARD_BOUND_REQUIRED",
            "TOKEN_2022_EXACT_POOL_DECODER_UNSUPPORTED",
            "JLP_LIVE_NAV_ORACLE_STATE_REQUIRED",
            "BOUNDED_FORWARD_RECURRENCE_NOT_MEASURED",
        ],
        "replay": "PASS",
    }


async def capture(
    output,
    *,
    main_sha,
    rpc_profiles=None,
    zero_x_taker=None,
    token_policy_path=None,
    quote_pair_index=0,
):
    if output.exists():
        raise ValueError("NEW_CAMPAIGN_OUTPUT_DIRECTORY_REQUIRED")
    if type(quote_pair_index) is not int or not 0 <= quote_pair_index <= 8:
        raise ValueError("BOUNDED_FIRST_CAMPAIGN_PAIR_INDEX_REQUIRED")
    contracts = json.loads(CONTRACT_PATH.read_text())
    registry, seed = AssetRegistry.load(), None
    seed = CampaignSeed.load(registry)
    sources = source_configuration(registry, contracts)
    zc, jc = read_contracts(contracts)
    bc = manifest_book_contract(contracts, sources[0][0].profile)
    rpcs = (
        tuple(ProviderProfile(**p) for p in json.loads(rpc_profiles.read_text()))
        if rpc_profiles
        else (public_rpc_profile(),)
    )
    if not 1 <= len(rpcs) <= 4 or any(p.role != "rpc" for p in rpcs):
        raise ValueError("BOUNDED_REVIEWED_RPC_PROFILES_REQUIRED")
    policies = load_token_policies(token_policy_path)
    profiles = (
        *(d.profile for d, _ in sources),
        zc.profile,
        jc.profile,
        *rpcs,
    )
    if len({p.profile_id for p in profiles}) != len(profiles):
        raise ValueError("DUPLICATE_PROVIDER_PROFILE")
    generations: dict[str, object] = {p.profile_id: asdict(p) for p in profiles}
    generations.update({d.source_id: asdict(d) for d, _ in sources})
    generations.update({c.source_id: asdict(c) for c in (zc, jc, bc)})
    manifest_policy = TransportPolicy(
        max_attempts=1,
        max_wire_bytes=8_000_000,
        max_response_bytes=8_000_000,
        max_string_length=6_000_000,
        max_json_nodes=120_000,
        max_container_items=5_000,
    )
    manifest = CampaignManifest.create(
        ROOT,
        main_sha=main_sha,
        configuration={
            "gpr.registry": registry.configuration,
            "gpr.seed": seed.configuration,
            "gpr02.contracts": contracts,
            "gpr02.manifest_transport": asdict(manifest_policy),
            "gpr02.campaign": {
                "zero_x_taker": zero_x_taker,
                "token_policies": [asdict(p) for p in policies],
                "quote_input_raw_units": 1_000_000,
                "quote_pair_index": quote_pair_index,
                "radar_documentation_review": "PUBLISHED_CONTRACT_AND_PINNED_GIT_ONLY",
                "max_radar_reads": 4,
                "max_quote_reads": 4,
                "max_native_pools": 1,
            },
        },
        sources=generations,
    )
    output.mkdir(parents=True)
    (output / "campaign-manifest.json").write_bytes(canonical_bytes(manifest.to_dict()))
    async with AsyncExitStack() as stack:
        journal = RecoverableStreamJournal(
            output / "campaign-evidence.sqlite", max_events=10_000
        )
        stack.callback(journal.close)
        evidence = CampaignEvidenceStore(journal, manifest)
        store = stack.enter_context(
            UnifiedLifecycleAuthority(
                output / "authority.sqlite",
                release_digest=manifest.runtime_authority_sha256,
                policy_bundle_hash=manifest.campaign_id,
            )
        )
        expires = (int(time.time()) // 86400 + 1) * 86400
        entitlements = {
            p.profile_id: p.entitlement(expires_at_epoch_seconds=expires)
            for p in profiles
        }
        entitlements.update(
            {
                c.profile.profile_id: c.entitlement(expires_at_epoch_seconds=expires)
                for c in (zc, jc)
            }
        )
        entitlements[bc.profile.profile_id] = bc.entitlement(
            expires_at_epoch_seconds=expires
        )
        gov = ProviderGovernance(entitlements, store=store)
        transport = await stack.enter_async_context(
            campaign_transport(
                {p.hostname for p in profiles},
                policy=TransportPolicy(
                    max_attempts=1,
                    max_response_bytes=8_000_000,
                    max_wire_bytes=8_000_000,
                    max_string_length=6_000_000,
                ),
            )
        )
        intake = SourceIntakePlane(
            load_market_source_catalog(), gov, transport, evidence
        )
        manifest_transport = await stack.enter_async_context(
            campaign_transport({"mfx-stats-mainnet.fly.dev"}, policy=manifest_policy)
        )
        manifest_intake = SourceIntakePlane(
            load_market_source_catalog(), gov, manifest_transport, evidence
        )
        records = []
        for d, a in sources:
            evidence.append(
                d.source_id,
                {"kind": "source_dossier", "dossier": asdict(d)},
                observed_at_ns=time.time_ns(),
            )
            gathered, _ = await (
                manifest_intake if d.source_id == "manifest" else intake
            ).collect(d, a)
            records.extend(gathered)
            if d.source_id == "manifest":
                raw = next(
                    (
                        b
                        for b in reversed(tuple(retained_records(evidence).values()))
                        if b.get("kind") == "source_observation"
                        and b.get("source_id") == "manifest"
                    ),
                    None,
                )
                if raw and raw.get("raw_payload") is not None:
                    nodes, pending = 0, [raw["raw_payload"]]
                    while pending:
                        item = pending.pop()
                        nodes += 1
                        if isinstance(item, dict):
                            pending.extend(item.values())
                        elif isinstance(item, list):
                            pending.extend(item)
                    evidence.append(
                        "gpr02-manifest-metrics",
                        {
                            "kind": "gpr02_manifest_payload_metrics",
                            "json_nodes": nodes,
                            "canonical_bytes": len(canonical_bytes(raw["raw_payload"])),
                            "rows": (
                                len(raw["raw_payload"])
                                if isinstance(raw["raw_payload"], list)
                                else None
                            ),
                            "max_nodes": 120_000,
                            "max_rows": 5_000,
                            "max_response_bytes": 8_000_000,
                            "response_hash": raw.get("response_hash"),
                        },
                        observed_at_ns=time.time_ns(),
                    )
        graph = SolanaResearchAdapter(ResearchEconomicGraph(registry, seed)).ingest(
            evidence
        )
        manifest_candidates = sorted(
            {
                c.identity: c for c, p in records if p["source_id"] == "manifest"
            }.values(),
            key=lambda c: c.identity,
        )
        if manifest_candidates:
            c = manifest_candidates[0]
            request = SourceReadRequest(
                bc.request_endpoint,
                (("depth", "20"), ("ticker_id", c.market_id)),
                bc.semantic_headers,
            )
            book_plane = GovernedReadPlane(gov, manifest_transport, evidence)
            raw_ref, envelope = await book_plane.collect(bc, request)
            if envelope["quality_state"] == "accepted":
                try:
                    book = normalize_manifest_book(
                        envelope["raw_payload"], market_id=c.market_id
                    )
                    evidence.append(
                        "gpr02-book",
                        {
                            "kind": "gpr02_manifest_book_reference",
                            "book": book,
                            "raw_evidence_ref": raw_ref,
                            "classification": "DISCOVERY_ONLY",
                            "exact_graph_allowed": False,
                        },
                        observed_at_ns=time.time_ns(),
                    )
                except (ValueError, KeyError, TypeError, AttributeError):
                    evidence.append(
                        "gpr02-book",
                        {
                            "kind": "gpr02_manifest_book_rejected",
                            "raw_evidence_ref": raw_ref,
                            "reason": "BOUNDED_BOOK_SCHEMA_REJECTED",
                        },
                        observed_at_ns=time.time_ns(),
                    )
        graph.persist(evidence, observed_at_ns=time.time_ns())
        queue = VerificationQueue(graph, evidence)
        ref = queue.persist(
            {},
            top_k=14,
            per_chain_budget={"solana-mainnet": 14, "sui-mainnet": 0},
            now_ns=time.time_ns(),
        )
        persist_funnel_plan(evidence, queue.replay(ref), registry)
        plane = GovernedReadPlane(gov, transport, evidence)
        a, b = priority_pairs(registry)[quote_pair_index]
        zero_quote = None
        if zero_x_taker is None:
            evidence.append(
                zc.source_id,
                {
                    "kind": "gpr02_reference_read",
                    "source_id": zc.source_id,
                    "source_generation": zc.generation,
                    "provider_generation": zc.profile.generation,
                    "correlation_group": zc.profile.correlation_group,
                    "quality_state": "missing-public-taker",
                    "http_status": None,
                    "physical_attempt": False,
                    "binding_name": "--zero-x-taker (public address), ZEROX_API_KEY",
                },
                observed_at_ns=time.time_ns(),
            )
        else:
            body = {
                "token_in": a.canonical_identifier,
                "token_out": b.canonical_identifier,
                "amount_in": 1_000_000,
                "slippage_bps": 50,
                "taker": zero_x_taker,
            }
            request = SourceReadRequest(
                zc.profile.endpoint, semantic_headers=zc.semantic_headers
            )
            r, e = await plane.collect(
                zc, request, json_body=body, credential=os.environ.get("ZEROX_API_KEY")
            )
            zero_quote = normalized_reference(evidence, zc, request, r, e, body=body)
        quotes = []
        for direct in (False, True):
            request = jupiter_request(
                a.canonical_identifier, b.canonical_identifier, 1_000_000, direct=direct
            )
            r, e = await plane.collect(
                jc, request, credential=os.environ.get("JUPITER_API_KEY")
            )
            q = normalized_reference(evidence, jc, request, r, e)
            if q:
                quotes.append(q)
        # A fresh final diagnostic quote has its own physical read and provenance.
        request = jupiter_request(
            a.canonical_identifier, b.canonical_identifier, 1_000_000
        )
        r, e = await plane.collect(
            jc, request, credential=os.environ.get("JUPITER_API_KEY")
        )
        final = normalized_reference(evidence, jc, request, r, e)
        if final:
            for q in ([zero_quote] if zero_quote else []) + quotes:
                try:
                    evidence.append(
                        "gpr02-comparison",
                        compare_quotes(q, final, now_ns=time.time_ns()),
                        observed_at_ns=time.time_ns(),
                    )
                except ValueError:
                    evidence.append(
                        "gpr02-comparison",
                        {
                            "kind": "gpr02_comparison_rejected",
                            "reason": "STALE_OR_UNALIGNED_CONTEXT",
                        },
                        observed_at_ns=time.time_ns(),
                    )
        if a.asset_key in ("BNSOL", "bbSOL", "hSOL", "dSOL"):
            request = jupiter_request(
                a.canonical_identifier, b.canonical_identifier, 1_000_000, sanctum=True
            )
            r, e = await plane.collect(
                jc, request, credential=os.environ.get("JUPITER_API_KEY")
            )
            q = normalized_reference(evidence, jc, request, r, e)
            if q:
                quotes.append(q)
        credential_headers = {}
        for p in rpcs:
            if p.auth_header:
                value = os.environ.get(p.credential_ref)
                if not value:
                    evidence.append(
                        p.profile_id,
                        {
                            "kind": "gpr02_rpc_profile_blocked",
                            "reason": "MISSING_CREDENTIAL_BINDING",
                            "binding_name": p.credential_ref,
                        },
                        observed_at_ns=time.time_ns(),
                    )
                    continue
                credential_headers[p.profile_id] = {
                    p.auth_header: (
                        "Bearer " + value if p.auth_header == "Authorization" else value
                    )
                }
        collectors = [
            GovernedNativeCpmmCollector(
                gov,
                transport,
                profile=p,
                evidence_store=evidence,
                auth_headers=credential_headers.get(p.profile_id),
            )
            for p in rpcs
            if not p.auth_header or p.profile_id in credential_headers
        ]
        await structural_capture(
            collectors,
            evidence,
            registry,
            contracts,
            policies,
            tuple(quotes) + ((final,) if final else ()),
        )
        retained = retained_records(evidence)
        selected = sorted(
            {
                c.identity: c
                for c, p in records
                if p["source_id"] == "raydium"
                and any(
                    row.get("id") == c.market_id
                    and row.get("programId") == RAYDIUM_CPMM_PROGRAM_ID
                    for row in retained[p["raw_evidence_id"]]["raw_payload"]["data"][
                        "data"
                    ]
                )
            }.values(),
            key=lambda c: c.identity,
        )[:1]
        if selected and collectors:
            # QPR-02 owns direct state/quorum/decoder. This produces data evidence only.
            evidence.append(
                "gpr02-capability",
                {
                    "kind": "gpr02_qpr02_decoder_capability_probe",
                    "market_id": selected[0].market_id,
                    "qualification_funnel_completed": False,
                    "exact_graph_handoff_allowed": False,
                },
                observed_at_ns=time.time_ns(),
            )
            try:
                await NativeRootedSnapshotProvider(collectors, evidence).collect(
                    (selected[0].market_id,)
                )
            except NativeCaptureError:
                pass
        evidence.append(
            "gpr02-budget",
            {
                "kind": "gpr02_budget_snapshot",
                "governance": {
                    p.profile_id: await gov.snapshot(p.profile_id) for p in profiles
                },
                "cost_usd_known": False,
                "engineering_caps_not_provider_sla": True,
            },
            observed_at_ns=time.time_ns(),
        )
        result = report(evidence, registry, seed)
    (output / "report.json").write_bytes(canonical_bytes(result))
    return result


def replay(output):
    manifest = manifest_from_dict(
        json.loads((output / "campaign-manifest.json").read_text())
    )
    journal = RecoverableStreamJournal(
        output / "campaign-evidence.sqlite", max_events=10_000
    )
    try:
        registry = AssetRegistry.load()
        return report(
            CampaignEvidenceStore(journal, manifest),
            registry,
            CampaignSeed.load(registry),
        )
    finally:
        journal.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("capture", "replay"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--base-sha", default="8c59759b491b6318f259138671dccfea25f2752e"
    )
    parser.add_argument("--rpc-profiles", type=Path)
    parser.add_argument("--zero-x-taker")
    parser.add_argument("--token2022-policy", type=Path)
    parser.add_argument("--pair-index", type=int, default=0)
    args = parser.parse_args(argv)
    result = (
        asyncio.run(
            capture(
                args.output,
                main_sha=args.base_sha,
                rpc_profiles=args.rpc_profiles,
                zero_x_taker=args.zero_x_taker,
                token_policy_path=args.token2022_policy,
                quote_pair_index=args.pair_index,
            )
        )
        if args.command == "capture"
        else replay(args.output)
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "campaign_id",
                    "capture_repository_sha",
                    "measurement_readiness",
                    "discovery_candidate_count",
                    "quotes_measured",
                    "reserved_attempts",
                    "replay",
                )
            },
            sort_keys=True,
        )
    )
    return 0 if result["measurement_readiness"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
