"""Executable collection/replay qualification for native CPMM shadow evidence.

Reports distinguish decoded snapshots, model conformance and missing deployment
or forward evidence. No result from this module grants live authority, subscribes
to orderbooks or proves realized profit. PR118 still owns the finite amount grid.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import AsyncExitStack
from dataclasses import asdict
import json
from pathlib import Path
import time
import os
import subprocess
from typing import Any

from src.durability import UnifiedLifecycleAuthority
from src.economics.non_monotonic_sizing import (
    PR118SizingPointRejected,
    build_pr118_amount_grid,
)
from src.providers.raydium_cpmm_native import (
    NativeCaptureError,
    canonical_json,
    content_hash,
    decode_native_capture,
)
from src.market.native_cpmm_capture import (
    DISCOVERY_PROVIDER,
    RPC_PROVIDER,
    SOURCE,
    GovernedNativeCpmmCollector,
    partition_for,
    public_read_entitlements,
)
from src.market.observations import MarketObservationV2, ObservationError, SourceCursor
from src.market.source_catalog import load_market_source_catalog
from src.market.streams import RecoverableStreamJournal
from src.provider_governance import ProviderGovernance
from src.qualification_pr186 import InterpreterIdentity, source_tree_identity
from src.routing.transport import HttpxJsonTransport, TransportPolicy
from src.strategy.arbitrage_graph import (
    CircularGraphCandidateDetector,
    CircularGraphPolicy,
)
from src.strategy.exact_cpmm_capacity import (
    CpmmEvaluationError,
    ExactCpmmEdgeEvaluation,
    PINNED_DECODER_REVISION,
    QualifiedRaydiumCpmmAdapter,
    WSOL_MINT,
    enumerate_exact_cpmm_routes,
    evaluate_exact_cpmm_route,
)
from src.strategy.market_graph_ingest import (
    ShadowMarketBinding,
    ShadowMarketGraphIngest,
)

REPORT_SCHEMA = "shadow.native-cpmm-qualification.v1"


def replay_native_journal(
    journal: RecoverableStreamJournal,
    *,
    partition: str,
    as_of_ns: int,
    base_mint: str = WSOL_MINT,
    lower_amount: int = 10_000,
    upper_amount: int = 1_000_000,
    max_points: int = 8,
    max_evaluations: int = 64,
    max_age_seconds: float = 120,
) -> dict[str, Any]:
    """Restore raw state before quotes; availability is the only replay clock."""
    if type(max_evaluations) is not int or not 1 <= max_evaluations <= 64:
        raise NativeCaptureError("evaluation cap outside 1..64")
    if type(max_points) is not int or not 1 <= max_points <= 8:
        raise NativeCaptureError("amount grid cap outside 1..8")
    amounts = build_pr118_amount_grid(
        lower_lamports=lower_amount, upper_lamports=upper_amount, max_points=max_points
    )
    body, head = journal.reconstruct_with_head(
        source=SOURCE, partition=partition, available_at_ns=as_of_ns
    )
    capture = decode_native_capture(body, max_age_seconds=max_age_seconds)
    if (
        capture.available_at_ns != head.available_at_ns
        or capture.observed_at_ns != head.observed_at_ns
        or capture.block_hash != head.block_hash
        or capture.parent_hash != head.parent_hash
        or head.revision != PINNED_DECODER_REVISION
        or partition_for(tuple(p.venue.market_id for p in capture.pools)) != partition
    ):
        raise NativeCaptureError("journal envelope/native state mismatch")
    now = as_of_ns / 10**9
    if any(p.observed_at > now or now >= p.expires_at for p in capture.pools):
        raise NativeCaptureError("native state stale or future at replay cutoff")
    bindings = tuple(
        ShadowMarketBinding(
            p.venue.market_id,
            "raydium",
            SOURCE,
            p.venue,
            (p.asset_a.mint, p.asset_b.mint),
            PINNED_DECODER_REVISION,
        )
        for p in capture.pools
    )
    ingest = ShadowMarketGraphIngest(load_market_source_catalog(), bindings)
    evaluator = QualifiedRaydiumCpmmAdapter()
    memo: dict[str, MarketObservationV2] = {}

    def observation(leg: ExactCpmmEdgeEvaluation) -> MarketObservationV2:
        prior = memo.get(leg.evaluation_id)
        if prior is not None:
            return prior
        state = leg.state_before
        quote = MarketObservationV2(
            provider="raydium",
            source=SOURCE,
            input_mint=leg.input_asset.mint,
            output_mint=leg.output_asset.mint,
            input_amount=leg.requested_input,
            expected_output=leg.expected_output,
            guaranteed_output=leg.conservative_output,
            slot=state.slot,
            observed_at=state.observed_at,
            expires_at=state.expires_at,
            quote_id=leg.evaluation_id,
            confidence="native-state-local-integer-shadow",
            commitment="finalized",
            generation=state.generation,
            request_fingerprint=content_hash(
                {"capture": capture.capture_hash, "evaluation": leg.evaluation_id}
            ),
            response_hash=str(body["account_response_hash"]),
            cursor=SourceCursor(
                SOURCE, state.venue.market_id, len(memo) + 1, state.slot
            ),
        )
        ingest.ingest(state.venue.market_id, quote)
        memo[leg.evaluation_id] = quote
        return quote

    rejected: list[dict[str, Any]] = []
    # Seed both directions for every bound pool. Candidate legs below are then
    # recomputed at coupled amounts; a seed is never linearly scaled.
    for state in capture.pools:
        for asset in (state.asset_a, state.asset_b):
            for amount in amounts:
                try:
                    observation(
                        evaluator.evaluate(
                            state, input_asset=asset, requested_input=amount
                        )
                    )
                except CpmmEvaluationError as exc:
                    rejected.append(
                        {
                            "market": state.venue.market_id,
                            "mint": asset.mint,
                            "amount": str(amount),
                            "reason": exc.reason.value,
                        }
                    )
    base_assets = {
        a for p in capture.pools for a in (p.asset_a, p.asset_b) if a.mint == base_mint
    }
    topology = None
    attempts: list[dict[str, Any]] = []
    search_stop = "base-asset-not-in-capture"
    if len(base_assets) == 1:
        topology = enumerate_exact_cpmm_routes(capture.pools, next(iter(base_assets)))
        search_stop = topology.stop_reason
        for plan in topology.plans:
            for amount in amounts:
                if len(attempts) == max_evaluations:
                    search_stop = "evaluation-limit"
                    break
                record: dict[str, Any] = {
                    "semantic_route_id": plan.semantic_route_id,
                    "amount": str(amount),
                }
                try:
                    result = evaluate_exact_cpmm_route(
                        plan,
                        input_amount=amount,
                        now=now,
                        max_snapshot_age_seconds=max_age_seconds,
                        observation_builder=observation,
                    )
                    record.update(
                        status="gross-shadow-candidate",
                        evaluation_id=result.evaluation_id,
                        output=str(result.conservative_output),
                        route_id=result.graph_route.identity,
                    )
                except PR118SizingPointRejected as exc:
                    record.update(status="amount-rejected", reason=str(exc))
                except CpmmEvaluationError as exc:
                    record.update(status="amount-rejected", reason=exc.reason.value)
                attempts.append(record)
            if search_stop == "evaluation-limit":
                break
    if memo:
        ingest.mark_backfill_complete(SOURCE)
    snapshot = ingest.publish(now=now, max_age_seconds=max_age_seconds, max_slot_skew=0)
    policy = CircularGraphPolicy(
        base_mint=base_mint,
        lower_amount_base_units=lower_amount,
        upper_amount_base_units=upper_amount,
        max_amount_points=max_points,
        max_snapshot_age_seconds=max_age_seconds,
        max_slot_skew=0,
        min_gross_profit_base_units=0,
    )
    detected = CircularGraphCandidateDetector(policy).detect(snapshot.graph, now=now)
    quorum = body.get(
        "rpc_quorum", {"accepted": False, "reason": "BLOCKED_SINGLE_SOURCE_OR_UNBOUND"}
    )
    if not isinstance(quorum, dict):
        raise NativeCaptureError("rpc quorum evidence must be an object")
    return {
        "schema": REPORT_SCHEMA,
        "shadow_only": True,
        "live_authorization": False,
        "as_of_ns": as_of_ns,
        "journal_head": head.identity,
        "capture_hash": capture.capture_hash,
        "evidence_kind": capture.evidence_kind,
        "slot": capture.slot,
        "block_hash": capture.block_hash,
        "parent_hash": capture.parent_hash,
        "binary_sha256": capture.binary_sha256,
        "deployment_slot": capture.deployment_slot,
        "decoder_revision": PINNED_DECODER_REVISION,
        "amount_points": [str(a) for a in amounts],
        "quote_count": len(memo),
        "coverage": asdict(snapshot.coverage),
        "traces": [asdict(t) for t in snapshot.traces],
        "topology_plans": len(topology.plans) if topology else 0,
        "topology_expansions": topology.expansions if topology else 0,
        "search_stop": search_stop,
        "evaluations": attempts,
        "quote_rejections": rejected,
        "graph_stop": detected.stop_reason.value,
        "graph_rejections": dict(detected.rejections),
        "gross_shadow_candidates": [
            {
                "route_id": c.identity,
                "hops": len(c.edges),
                "input": str(c.edges[0].observation.input_amount),
                "output": str(c.edges[-1].observation.guaranteed_output),
                "markets": [e.venue.market_id for e in c.edges],
                "legs": [
                    {
                        "market": e.venue.market_id,
                        "input_mint": e.observation.input_mint,
                        "output_mint": e.observation.output_mint,
                        "input": str(e.observation.input_amount),
                        "output": str(e.observation.guaranteed_output),
                        "observation_id": e.observation.observation_id,
                    }
                    for e in c.edges
                ],
            }
            for c in detected.candidates
        ],
        "campaign_manifest_hash": body.get("campaign_manifest_hash"),
        "rpc_quorum": quorum,
        "qualification": {
            "rpc_independence": quorum.get(
                "reason", "BLOCKED_SINGLE_SOURCE_OR_UNBOUND"
            ),
            "raw_decode": "PASS",
            "restart_replay": "NOT_RUN_BY_SINGLE_REPLAY",
            "deployment_source_binding": "MISSING",
            "forward_holdout": "NOT_RUN",
            "complete_account_subscription": "NOT_IMPLEMENTED_ONE_SHOT_ONLY",
            "execution_costs_and_financing": "UNKNOWN",
            "overall": "BLOCKED",
        },
    }


async def collect_report(
    output: Path,
    *,
    pool_ids: tuple[str, ...],
    discover: bool,
    base_mint: str = WSOL_MINT,
    lower_amount: int = 10_000,
    upper_amount: int = 1_000_000,
    rpc_profiles: Path | None = None,
) -> dict[str, Any]:
    CircularGraphPolicy(base_mint, lower_amount, upper_amount)
    output.mkdir(parents=True, exist_ok=True)
    from dataclasses import asdict as profile_dict
    from src.qualification_campaign.identity import CampaignManifest
    from src.qualification_campaign.profiles import ProviderProfile, public_rpc_profile
    from src.qualification_campaign.evidence import CampaignEvidenceStore
    from src.qualification_campaign.rpc import NativeRootedSnapshotProvider
    from src.qualification_campaign.transport import campaign_transport

    root = Path(__file__).resolve().parents[2]
    source = source_tree_identity(root)
    profiles = (
        tuple(ProviderProfile(**p) for p in json.loads(rpc_profiles.read_text()))
        if rpc_profiles
        else (public_rpc_profile(),)
    )
    main_sha = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "origin/main^{commit}"], text=True
    ).strip()
    campaign = CampaignManifest.create(
        root,
        main_sha=main_sha,
        configuration={
            "capture": {
                "pool_ids": sorted(pool_ids),
                "discover": discover,
                "base_mint": base_mint,
                "lower_amount": lower_amount,
                "upper_amount": upper_amount,
            }
        },
        sources={p.profile_id: profile_dict(p) for p in profiles},
    )
    expires = (int(time.time()) // 86400 + 1) * 86400
    manifests = {
        p.profile_id: p.entitlement(expires_at_epoch_seconds=expires) for p in profiles
    }
    if discover:
        manifests[DISCOVERY_PROVIDER] = public_read_entitlements(
            expires_at_epoch_seconds=expires
        )[DISCOVERY_PROVIDER]
    partition: str | None = None
    async with AsyncExitStack() as resources:
        transport = await resources.enter_async_context(
            campaign_transport(
                policy=TransportPolicy(
                    max_string_length=6_000_000,
                    max_response_bytes=8_000_000,
                    max_wire_bytes=8_000_000,
                    max_attempts=1,
                ),
                hosts=frozenset(
                    {p.hostname for p in profiles}
                    | ({"api-v3.raydium.io"} if discover else set())
                ),
            )
        )
        store = resources.enter_context(
            UnifiedLifecycleAuthority(
                output / "authority.sqlite",
                release_digest=campaign.runtime_authority_sha256,
                policy_bundle_hash=campaign.campaign_id,
            )
        )
        journal = RecoverableStreamJournal(
            output / "raw.sqlite", max_events=512, max_payload_bytes=16 * 1024 * 1024
        )
        resources.callback(journal.close)
        governance = ProviderGovernance(manifests, store=store)
        campaign_journal = RecoverableStreamJournal(
            output / "campaign-evidence.sqlite", max_events=10_000
        )
        resources.callback(campaign_journal.close)
        evidence = CampaignEvidenceStore(campaign_journal, campaign)
        collectors = []
        for p in profiles:
            headers = None
            if p.auth_header:
                value = os.environ.get(p.credential_ref)
                if not value:
                    raise NativeCaptureError(
                        "MISSING_CREDENTIAL_BINDING:" + p.credential_ref
                    )
                headers = {
                    p.auth_header: (
                        ("Bearer " + value)
                        if p.auth_header == "Authorization"
                        else value
                    )
                }
            collectors.append(
                GovernedNativeCpmmCollector(
                    governance,
                    transport,
                    profile=p,
                    evidence_store=evidence,
                    auth_headers=headers,
                )
            )
        provider = NativeRootedSnapshotProvider(collectors, evidence)
        collector = GovernedNativeCpmmCollector(
            governance, transport, profile=profiles[0], snapshot_provider=provider
        )

        try:
            if discover:
                pool_ids = await collector.discover()
            partition = partition_for(pool_ids)
            payload = await collector.collect_into(journal, pool_ids)
            kwargs = dict(
                partition=partition,
                as_of_ns=payload["available_at_ns"],
                base_mint=base_mint,
                lower_amount=lower_amount,
                upper_amount=upper_amount,
            )
            baseline = replay_native_journal(journal, **kwargs)
            # Restore state from raw evidence in a newly opened connection.
            journal.close()
            journal = RecoverableStreamJournal(
                output / "raw.sqlite",
                max_events=512,
                max_payload_bytes=16 * 1024 * 1024,
            )
            resources.callback(journal.close)
            report = replay_native_journal(journal, **kwargs)
            if canonical_json(baseline) != canonical_json(report):
                raise NativeCaptureError("restart replay identity mismatch")
            report["qualification"]["restart_replay"] = "PASS"
            report["restart_replay_digest"] = content_hash(baseline)
        except Exception as exc:
            barrier_error = None
            try:
                journal.block(
                    source=SOURCE,
                    partition=partition or "*",
                    available_at_ns=time.time_ns(),
                    reason=type(exc).__name__,
                )
            except Exception as barrier_exc:
                barrier_error = type(barrier_exc).__name__
            report = {
                "schema": REPORT_SCHEMA,
                "shadow_only": True,
                "live_authorization": False,
                "qualification": {"overall": "BLOCKED", "raw_decode": "NOT_EXECUTED"},
                "error_category": type(exc).__name__,
                "barrier_error_category": barrier_error,
                "gross_shadow_candidates": [],
            }
        report["governance"] = {p: await governance.snapshot(p) for p in manifests}
        report["campaign"] = {
            "manifest": campaign.to_dict(),
            "campaign_id": campaign.campaign_id,
            "journal_head": evidence.head,
        }
    report.update(
        partition=partition,
        rpc_receipts=collector.receipts,
        discovery=collector.discovery,
        source_identity=source.to_dict(),
        interpreter_identity=asdict(InterpreterIdentity.capture()),
        read_manifests={p: m.to_dict() for p, m in manifests.items()},
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--collect", action="store_true")
    mode.add_argument("--replay", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pool", action="append", default=[])
    parser.add_argument("--discover", action="store_true")
    parser.add_argument(
        "--rpc-profiles",
        type=Path,
        help="reviewed JSON array of ProviderProfile objects",
    )
    parser.add_argument("--partition")
    parser.add_argument("--as-of-ns", type=int)
    parser.add_argument("--base-mint", default=WSOL_MINT)
    parser.add_argument("--lower-amount", type=int, default=10_000)
    parser.add_argument("--upper-amount", type=int, default=1_000_000)
    args = parser.parse_args(argv)
    if args.collect:
        if bool(args.pool) == args.discover:
            parser.error("collection needs explicit --pool addresses or --discover")
        try:
            report = asyncio.run(
                collect_report(
                    args.output,
                    pool_ids=tuple(args.pool),
                    discover=args.discover,
                    rpc_profiles=args.rpc_profiles,
                    base_mint=args.base_mint,
                    lower_amount=args.lower_amount,
                    upper_amount=args.upper_amount,
                )
            )
        except Exception as exc:
            report = {
                "schema": REPORT_SCHEMA,
                "shadow_only": True,
                "live_authorization": False,
                "qualification": {"overall": "BLOCKED"},
                "error_category": type(exc).__name__,
                "phase": "initialization-or-unhandled-failure",
                "gross_shadow_candidates": [],
            }
        target = args.output / "report.json"
    else:
        if (
            args.discover
            or args.pool
            or args.partition is None
            or args.as_of_ns is None
        ):
            parser.error(
                "replay needs --partition and --as-of-ns; collection flags are forbidden"
            )
        if not args.replay.is_file():
            parser.error("replay journal does not exist")
        journal = RecoverableStreamJournal(
            args.replay, max_events=512, max_payload_bytes=16 * 1024 * 1024
        )
        try:
            report = replay_native_journal(
                journal,
                partition=args.partition,
                as_of_ns=args.as_of_ns,
                base_mint=args.base_mint,
                lower_amount=args.lower_amount,
                upper_amount=args.upper_amount,
            )
        except (NativeCaptureError, ObservationError) as exc:
            report = {
                "schema": REPORT_SCHEMA,
                "shadow_only": True,
                "live_authorization": False,
                "qualification": {"overall": "BLOCKED"},
                "error_category": type(exc).__name__,
                "gross_shadow_candidates": [],
            }
        finally:
            journal.close()
        target = args.output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(canonical_json(report) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str(target),
                "qualification": report["qualification"],
                "candidates": len(report["gross_shadow_candidates"]),
            }
        )
    )
    return 2 if "error_category" in report else 0


if __name__ == "__main__":
    raise SystemExit(main())
