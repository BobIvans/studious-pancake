"""Installed offline market-scale replay. No provider I/O or trading entrypoint."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import time
from typing import Any

from src.durability.unified_authority_pr02 import UnifiedLifecycleAuthority
from src.market.observations import ObservationGeneration
from src.strategy.arbitrage_graph import VenueIdentity
from src.strategy.cpmm_split_replay import pool_key
from src.strategy.conflict_scheduler import WorkResourceSet
from src.strategy.exact_cpmm_capacity import (
    ExactCpmmRoutePlan,
    QualifiedCpmmState,
    SolanaAssetIdentity,
)
from src.strategy.shadow_workers import ShadowReplayJob, run_shadow_replays


def load_replay_input(
    path: Path,
) -> tuple[str, tuple[ExactCpmmRoutePlan, ...], tuple[int, ...], float]:
    raw = path.read_bytes()
    if len(raw) > 2_000_000:
        raise ValueError("replay input byte bound exceeded")
    payload = json.loads(raw)
    if (
        payload.get("schema") != "shadow.market-scale-replay.v1"
        or payload.get("qualification") != "MODEL_REPLAY_ONLY"
        or payload.get("live_enabled") is not False
    ):
        raise ValueError("explicit offline replay boundary required")
    if (
        not 1 <= len(payload["pools"]) <= 32
        or not 1 <= len(payload["routes"]) <= 8
        or not 1 <= len(payload["amounts"]) <= 8
    ):
        raise ValueError("bounded pools/routes/amounts required")
    generation = ObservationGeneration(**payload["generation"])
    assets = {
        key: SolanaAssetIdentity(**value) for key, value in payload["assets"].items()
    }
    if len(assets) > 32:
        raise ValueError("asset bound exceeded")
    pools = {}
    for row in payload["pools"]:
        if row["pool_id"] in pools:
            raise ValueError("duplicate pool identity")
        optional_fee_fields = (
            "trade_fee_rate_ppm",
            "protocol_fee_rate_ppm",
            "fund_fee_rate_ppm",
            "creator_fee_rate_ppm",
            "creator_fee_on",
            "fee_accounting_revision",
            "accrued_fees_a",
            "accrued_fees_b",
        )
        required_pool_fields = {
            "pool_id",
            "venue",
            "asset_a",
            "asset_b",
            "reserve_a",
            "reserve_b",
            "fee_bps",
            "slot",
            "observed_at",
            "expires_at",
            "decoder_revision",
            "model_revision",
        }
        if set(row) - required_pool_fields - set(optional_fee_fields):
            raise ValueError("unknown pool-state fields")
        fee_fields = {key: row[key] for key in optional_fee_fields if key in row}
        pools[row["pool_id"]] = QualifiedCpmmState(
            venue=VenueIdentity(**row["venue"]),
            asset_a=assets[row["asset_a"]],
            asset_b=assets[row["asset_b"]],
            reserve_a=row["reserve_a"],
            reserve_b=row["reserve_b"],
            fee_bps=row["fee_bps"],
            slot=row["slot"],
            observed_at=row["observed_at"],
            expires_at=row["expires_at"],
            generation=generation,
            decoder_revision=row["decoder_revision"],
            model_revision=row["model_revision"],
            **fee_fields,
        )
    plans = tuple(
        ExactCpmmRoutePlan(
            assets[row["settlement_asset"]], tuple(pools[key] for key in row["pools"])
        )
        for row in payload["routes"]
    )
    if len({plan.semantic_route_id for plan in plans}) != len(plans):
        raise ValueError("duplicate route identity")
    amounts = tuple(payload["amounts"])
    if any(type(amount) is not int or amount <= 0 for amount in amounts) or len(
        set(amounts)
    ) != len(amounts):
        raise ValueError("unique positive integer amounts required")
    return (
        sha256(raw).hexdigest(),
        plans,
        tuple(sorted(amounts)),
        payload["snapshot_now"],
    )


def _replay_release_digest() -> str:
    root = Path(__file__).resolve().parents[1]
    owners = (
        "paper_shadow/market_scale_replay.py",
        "strategy/shadow_workers.py",
        "strategy/exact_cpmm_capacity.py",
        "strategy/arbitrage_graph.py",
        "direct_venue/cpmm_math.py",
        "market/observations.py",
        "durability/unified_authority_pr02.py",
    )
    payload = {
        owner: sha256((root / owner).read_bytes()).hexdigest() for owner in owners
    }
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def execute_replay(path: Path, *, authority_path: Path, workers: int) -> dict[str, Any]:
    frame, plans, amounts, now = load_replay_input(path)
    jobs = tuple(
        ShadowReplayJob(
            f"{plan.semantic_route_id}/{amount}",
            frame,
            plan,
            amount,
            now,
            time.monotonic_ns() + 60_000_000_000,
        )
        for plan in plans
        for amount in amounts
    )
    with UnifiedLifecycleAuthority(
        authority_path,
        release_digest=_replay_release_digest(),
        policy_bundle_hash=sha256(b"offline-market-scale-v1").hexdigest(),
        owner_id="offline-market-scale",
        environment="shadow",
        lease_ttl_ns=120_000_000_000,
    ) as authority:
        fences = {}
        for job in jobs:
            resources = WorkResourceSet(
                readonly_accounts=tuple(
                    sorted(pool_key(pool) for pool in job.plan.pools)
                )
            )
            fences[job.job_id] = authority.begin_shadow_work(
                work_id=job.job_id,
                generation=1,
                state_generation=frame,
                resource_payload=asdict(resources),
            )
        results = run_shadow_replays(
            jobs,
            workers=workers,
            max_pending=64,
            current_frame_id=frame,
            frame_reader=lambda: sha256(path.read_bytes()).hexdigest(),
        )
        for result in results:
            authority.commit_shadow_work(
                fences[result.job_id], evidence=asdict(result), outcome=result.status
            )
    return {
        "schema": "shadow.market-scale-report.v1",
        "frame_id": frame,
        "qualification": "MODEL_REPLAY_ONLY",
        "results": [asdict(result) for result in results],
        "workers": workers,
        "connected_feeds": 0,
        "verified_subscriptions": 0,
        "execution_right": False,
        "live_enabled": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--authority-db", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--html-review", type=Path)
    parser.add_argument("--workers", type=int, choices=(1, 2, 4, 8), default=1)
    args = parser.parse_args()
    paths = [args.input.resolve(), args.authority_db.resolve(), args.output.resolve()]
    if args.html_review is not None:
        paths.append(args.html_review.resolve())
    if len(paths) != len(set(paths)):
        parser.error("input, authority and output artifacts require separate paths")
    if args.output.resolve() in (args.input.resolve(), args.authority_db.resolve()):
        parser.error("output must not overwrite input or authority")
    report = execute_replay(
        args.input, authority_path=args.authority_db, workers=args.workers
    )
    if args.html_review is not None:
        if args.html_review.resolve() in (
            args.input.resolve(),
            args.authority_db.resolve(),
            args.output.resolve(),
        ):
            parser.error("HTML review must use a separate artifact path")
        from src.market_data_evolution.graph_review import render_graph_review
        from src.strategy.exact_cpmm_capacity import evaluate_exact_cpmm_route

        frame, plans, amounts, now = load_replay_input(args.input)
        if frame != report["frame_id"]:
            raise ValueError("input frame changed before review")
        rows = []
        for plan in plans:
            for amount in amounts:
                job_id = f"{plan.semantic_route_id}/{amount}"
                result = next(
                    row for row in report["results"] if row["job_id"] == job_id
                )
                if result["status"] != "model-replay":
                    continue
                route = evaluate_exact_cpmm_route(plan, input_amount=amount, now=now)
                if route.evaluation_id != result["evaluation_id"]:
                    raise ValueError("review evaluation differs from result")
                for index, leg in enumerate(route.legs):
                    rows.append(
                        {
                            "route_id": route.semantic_route_id,
                            "leg": index + 1,
                            "venue": leg.state_before.venue.market_id,
                            "input_asset": leg.input_asset.identity,
                            "output_asset": leg.output_asset.identity,
                            "input_atoms": leg.requested_input,
                            "output_atoms": leg.conservative_output,
                            "slot": leg.state_before.slot,
                            "evaluation_id": leg.evaluation_id,
                        }
                    )
        args.html_review.write_text(
            render_graph_review(rows, frame_id=frame), encoding="utf-8"
        )
    args.output.write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
