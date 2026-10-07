"""Bounded real-data read-only campaign. Reports blockers; never sets QPR PASS."""

import argparse
import asyncio
from collections import Counter
from dataclasses import asdict
from pathlib import Path
import json
import time

from src.assets.resolution.chain_readers import SolanaMintVerifier
from src.assets.resolution.evidence import EvidenceStore, digest
from src.assets.resolution.resolver import AssetResolutionJob, bootstrap_jobs, resolve
from src.discovery.dynamic_universe.ingestors import (
    DeepBookIngestor,
    JupiterTokensIngestor,
    ReadOnlyFetcher,
    SanctumLstIngestor,
)
from src.discovery.dynamic_universe.promotion import PromotionBoundary
from src.discovery.dynamic_universe.ton_radar import StonRadarIngestor
from src.discovery.dynamic_universe.universe import DynamicUniverse


class TonReadOnlyTransport:
    """Use the platform HTTPS proxy with retained bounded raw payloads."""

    def __init__(self, fetcher: ReadOnlyFetcher):
        self.fetcher = fetcher

    async def request(self, method, url, **kwargs):
        if method != "GET" or kwargs:
            raise ValueError("TON campaign permits only GET")
        payload, evidence = await asyncio.to_thread(self.fetcher.fetch, url, "ston")
        if evidence.negative_reason:
            return 503, {}, {"negative_reason": evidence.negative_reason}
        return payload["status"], {}, json.loads(payload["body"])


def run_campaign(
    repo_root: Path,
    output: Path,
    *,
    generation: str,
    live: bool,
    rpc_endpoints: tuple[str, ...] = ("https://api.mainnet-beta.solana.com",),
    max_rpc_assets: int = 1,
) -> dict:
    if not live:
        raise ValueError("use --live explicitly for real read-only provider requests")
    if type(max_rpc_assets) is not int or not 0 <= max_rpc_assets <= 4:
        raise ValueError("RPC asset budget must be 0..4")
    output.mkdir(parents=True, exist_ok=True)
    store = EvidenceStore(output / "evidence")
    fetcher = ReadOnlyFetcher(store, generation)
    universe = DynamicUniverse(generation, store)
    jobs = bootstrap_jobs(repo_root, generation)
    envelopes = tuple(
        e
        for ingestor in (
            SanctumLstIngestor(fetcher),
            DeepBookIngestor(fetcher),
            JupiterTokensIngestor(
                fetcher, "So11111111111111111111111111111111111111112"
            ),
        )
        for e in ingestor.poll(None, 1)
    )
    for envelope in envelopes:
        universe.ingest(envelope, now=time.time())
    candidates = tuple(c for e in envelopes for c in e.assets)
    verifier = SolanaMintVerifier(fetcher, rpc_endpoints)
    proof_by_id = {}
    for candidate in tuple(
        c for c in candidates if c.chain == "solana" and c.authoritative
    )[:max_rpc_assets]:
        proof_by_id[candidate.identifier] = verifier(candidate)
    receipts = []
    for job in jobs:
        matching = tuple(
            c
            for c in candidates
            if c.chain == job.chain
            and (
                c.identifier == job.seed_identifier
                or c.symbol == job.query.split(" ")[0]
            )
        )
        proofs = tuple(p for c in matching for p in proof_by_id.get(c.identifier, ()))
        receipts.append(resolve(job, matching, proofs, now=time.time(), store=store))
    # Demonstrate new live identifiers follow the same runtime workflow.
    for identifier in proof_by_id:
        matching = tuple(c for c in candidates if c.identifier == identifier)
        receipts.append(
            resolve(
                AssetResolutionJob("solana", identifier, generation),
                matching,
                proof_by_id[identifier],
                now=time.time(),
                store=store,
            )
        )
    ton = StonRadarIngestor(
        TonReadOnlyTransport(fetcher),
        campaign_generation=generation,
        journal_path=output / "ton-radar.jsonl",
    )
    ton_envelopes = asyncio.run(ton.poll(None, 3))
    negatives: list[dict] = [
        {"source": e.evidence.source, "reason": e.evidence.negative_reason}
        for e in envelopes
        if e.evidence.negative_reason
    ]
    negatives += [
        {"source": e.source_url, "reason": e.negative_evidence}
        for e in ton_envelopes
        if e.negative_evidence
    ]
    negatives += [
        {"source": e.source, "reason": e.negative_reason}
        for e in verifier.negative_evidence
    ]
    counts = Counter(r.state for r in receipts)
    symbol_ids: dict[tuple[str, str], set[str]] = {}
    for c in candidates:
        symbol_ids.setdefault((c.chain, c.symbol), set()).add(c.identifier)
    report = {
        "schema": "dynamic-universe.campaign.v1",
        "generation": generation,
        "campaign": "READ_ONLY_REAL_DATA_CAMPAIGN_V1",
        "capture_kind": "BOUNDED_DISCOVERY_DIAGNOSTIC_NOT_QPR_QUALIFICATION",
        "verdict": "BLOCKED",
        "qpr_readiness": "NOT_ESTABLISHED",
        "executable_promotion_enabled": PromotionBoundary(
            generation, store
        ).readiness(),
        "signer_sender_live_capital_enabled": False,
        "source_counts": {
            e.evidence.provider: {
                "assets": len(e.assets),
                "markets": len(e.markets),
                "complete": e.complete_snapshot,
                "negative": e.evidence.negative_reason,
            }
            for e in envelopes
        },
        "bootstrap_jobs": len(jobs),
        "resolution_counts": dict(counts),
        "unresolved_identities": [
            {
                "chain": r.job.chain,
                "query": r.job.query,
                "state": r.state,
                "reasons": r.reasons,
                "candidates": [c.identifier for c in r.candidates],
            }
            for r in receipts
            if r.identity is None
        ],
        "source_disagreements": [
            {
                "chain": c.chain,
                "symbol": c.symbol,
                "identifier": c.identifier,
                "historical_symbol": j.query,
                "seed": j.seed_identifier,
            }
            for c in candidates
            for j in jobs
            if c.chain == j.chain
            and c.identifier == j.seed_identifier
            and c.symbol != j.query.split(" ")[0]
        ],
        "ticker_collisions": [
            {"chain": k[0], "symbol": k[1], "identifiers": sorted(v)}
            for k, v in sorted(symbol_ids.items())
            if len(v) > 1
        ],
        "shared_liquidity_aliases": [],
        "discovered_markets": len(universe.active_markets()),
        "qualified_relations": 0,
        "profitable_size_bands": [],
        "correlation_findings": [],
        "capital_observations": [],
        "false_positive_rate": None,
        "ton": {
            "records": sum(len(e.records) for e in ton_envelopes),
            "execution_class": "TON_ASYNC_MULTI_CONTRACT",
            "negative_envelopes": sum(bool(e.negative_evidence) for e in ton_envelopes),
        },
        "negative_evidence": negatives,
        "blockers": [
            "Generation-matched QPR owner/journal absent in checkout; upstream QPR-03 readiness PASS still stops before QPR-04 with qualification BLOCKED",
            "Independent exact market/quote/financing verification not established",
            "Sui gRPC/Core and lender SDK read-only bridges not configured",
        ],
        "recommended_next_integrations": [
            "Explicit verified Manifest/Orca/Meteora/Raydium market bindings through ShadowMarketGraphIngest",
            "Sui gRPC/Core full coin/package metadata verifier and DeepBook decoder",
            "Project0/Kamino bank/reserve SDK readers and NAVI/DeepBook/Scallop live financing readers",
            "Review required proxy domains; rerun the bounded real campaign after access changes",
        ],
        "storage_bytes": sum(
            p.stat().st_size for p in output.rglob("*") if p.is_file()
        ),
        "retention": {
            "raw_days": 7,
            "normalized_days": 30,
            "anomaly_window_seconds": 300,
            "proofs": "indefinite",
            "automatic_deletion": False,
        },
    }
    path = output / (digest(report) + ".report.json")
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--generation", required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--max-rpc-assets", type=int, default=1)
    args = parser.parse_args(argv)
    report = run_campaign(
        args.repo_root,
        args.output,
        generation=args.generation,
        live=args.live,
        max_rpc_assets=args.max_rpc_assets,
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "verdict",
                    "source_counts",
                    "bootstrap_jobs",
                    "resolution_counts",
                    "discovered_markets",
                    "ton",
                    "storage_bytes",
                )
            },
            indent=2,
        )
    )
    return 2 if report["verdict"] != "PASS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
