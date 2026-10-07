#!/usr/bin/env python3
"""Reproducible offline acceptance and MD/JSON/TXT/ZIP receipts, never live claims."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import importlib
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agg02.contracts import RawEventEnvelope
from src.agg02.storage import DurableRawJournal
from src.market_data_evolution.contracts import MarketEpisode
from src.research.evidence import ResearchExperimentManifest
from src.intelligence.common import digest, load_json, save_json, seal
from src.intelligence.repo_snapshot import git
from src.intelligence.experiment_manifest import seal_experiment
from src.intelligence.episode_builder import build_market_episode
from src.intelligence.parquet_compaction import publish_partition
from src.intelligence.rollups import (
    build_1m_rollup,
    build_5m_rollup,
    build_1h_rollup,
    verify_rollup_coverage,
)
from src.intelligence.sampling import select_periodic_baseline
from src.intelligence.retention_policy import retention_dry_run
from src.intelligence.prune import prune_verified_payloads
from src.intelligence.storage_budget import read_disk_budget, forecast_days_until_budget
from src.intelligence.reports import build_report, bundle_report


def verify_backlog() -> dict:
    backlog = load_json(
        ROOT / "docs/strategy/local-intelligence-v2/FUNCTION_BACKLOG.json"
    )
    functions = []
    for row in backlog["functions"]:
        module = importlib.import_module(
            row["module"].removesuffix(".py").replace("/", ".")
        )
        for name in row["functions"]:
            if not callable(getattr(module, name, None)):
                raise ValueError(f"missing implementation: {row['id']}.{name}")
            functions.append(
                {"id": row["id"], "function": name, "module": module.__name__}
            )
    return {
        "status": "IMPLEMENTED_SURFACES",
        "functions": functions,
        "note": "Importability is structural evidence; behavioral tests are required separately.",
    }


def run_acceptance(out: Path) -> dict:
    if out.resolve().is_relative_to(ROOT):
        raise ValueError("acceptance output must be outside checkout")
    if out.exists() and any(out.iterdir()):
        raise ValueError("acceptance output must be new or empty")
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    head = git(ROOT, "rev-parse", "HEAD").decode().strip()
    # Fixed fixture clock keeps data deterministic and cannot imply a live 24h campaign.
    feature_time, now = 200_000, 200_000_000
    identity = seal_experiment(
        ResearchExperimentManifest(
            experiment_id="local-v2-offline-acceptance",
            hypothesis_id="retention-replay-integrity",
            baseline_id="exact-raw",
            problem_sha256=digest("retention"),
            dataset_sha256=digest("fixture-v2"),
            code_sha256=digest(head),
            source_ids=("provider-a", "provider-b"),
            compute_budget_units=100,
        ),
        repo_sha=head,
        config_sha=digest({"fixture": True}),
        policy_sha=digest({"minimum_age_ms": 86_400_000}),
    )
    with DurableRawJournal(out / "agg02.db", max_journal_bytes=10_000_000) as journal:
        for index in range(1, 101):
            payload = (f'{{"state":{index % 4},"fixture":true}}'.encode()) * 100
            source = "provider-a" if index % 2 else "provider-b"
            envelope = RawEventEnvelope(
                event_id=f"event-{index:03d}",
                source_id=source,
                chain_id="offline-fixture",
                payload_sha256=hashlib.sha256(payload).hexdigest(),
                received_at_ms=index * 1000,
                available_at_ms=index * 1000 + 1,
                decoder_version="fixture-v2",
                cursor_source=source,
                cursor_partition="pair",
                cursor_offset=(index + 1) // 2,
                reconnect_epoch=0,
                slot=index,
                commitment="confirmed",
            )
            journal.append(envelope, payload)
        rows = journal.retention_rows()
        raw_refs = ["event-099", "event-100"]
        observations = [
            {
                "observation_id": "observation-1",
                "available_at_ms": 100_001,
                "raw_event_ids": raw_refs,
            }
        ]
        decisions = [
            {
                "decision_id": "reject-1",
                "stage": "PRE_QUOTE",
                "available_at_ms": feature_time,
                "source_refs": ["observation-1"],
                "features": {"candidate_age_ms": 99_999},
                "action": "REJECT",
                "reason_code": "STALE_QUOTE",
                "thresholds": {"maximum_age_ms": 1000},
                "strategy_id": "offline-baseline",
                "strategy_version": "v1",
            }
        ]
        episode = build_market_episode(
            MarketEpisode("episode-1", feature_time, None, None, "CENSORED"),
            experiment=identity,
            observations=observations,
            decisions=decisions,
            journal=journal,
            raw_event_ids=raw_refs,
            candidate_id="candidate-1",
            resource_usage={"quota_units": 2},
        )
        save_json(out / "EPISODE.json", episode)
        proofs = {}
        for label, builder in (
            ("1m", build_1m_rollup),
            ("5m", build_5m_rollup),
            ("1h", build_1h_rollup),
        ):
            rollup = builder(list(rows))
            proofs[label] = verify_rollup_coverage(rollup, list(rows))
            save_json(out / f"ROLLUP_{label}.json", rollup)
        baseline = select_periodic_baseline(list(rows))
        compaction = publish_partition(journal, out / "raw.parquet")
        records = [
            {
                **{k: v for k, v in r.items() if k != "payload"},
                "candidate_window": r["event_id"] in raw_refs,
                "baseline_sample": r["event_id"] in baseline,
                "referenced": r["event_id"] in raw_refs,
                "active_experiment": False,
                **{
                    key: True
                    for key in (
                        "reference_inventory_complete",
                        "representation_verified",
                        "provenance_verified",
                        "compaction_verified",
                        "replay_verified",
                        "minimum_samples_retained",
                    )
                },
            }
            for r in rows
        ]
        retention = retention_dry_run(records, now_ms=now)
        save_json(out / "RETENTION.json", retention)
        pruned = prune_verified_payloads(
            journal,
            compaction=compaction,
            retention=retention,
            records=records,
            references=[
                {"evidence_id": episode["receipt_sha256"], "raw_event_ids": raw_refs}
            ],
            inventory_complete=True,
            receipt_path=out / "TOMBSTONE.json",
        )
        for row in rows:
            if journal.payload(str(row["event_id"])) != row["payload"]:
                raise ValueError("post-prune exact replay mismatch")
        replay = {
            "verified_events": len(rows),
            "exact": True,
            "candidate_evidence_preserved": True,
            "cursor_provider_a": asdict(journal.cursor("provider-a", "pair")),
            "cursor_provider_b": asdict(journal.cursor("provider-b", "pair")),
        }
        save_json(out / "REPLAY.json", replay)
    with DurableRawJournal(out / "agg02.db") as reopened:
        if reopened.payload("event-100") != rows[-1]["payload"]:
            raise ValueError("reopened owner replay mismatch")
    campaign = {
        "experiment": identity,
        "episodes": [episode],
        "data_kind": "OFFLINE_SYNTHETIC_FIXTURE",
        "window": {
            "start_ms": 1001,
            "end_ms": feature_time,
            "real_24h_campaign": False,
        },
        "provider_rows": [
            {
                "event_id": r["event_id"],
                "source_id": r["source_id"],
                "available_at_ms": r["available_at_ms"],
                "payload_sha256": r["payload_sha256"],
                "quota_units": 1,
                "candidate_ids": ["candidate-1"] if r["event_id"] in raw_refs else [],
            }
            for r in rows
        ],
        "qualification": {
            "episodes": [
                {"episode_id": "episode-1", "observation_ids": ["observation-1"]}
            ],
            "variants": [],
            "probes": [],
            "survival_horizon_ms": 1000,
        },
    }
    storage = read_disk_budget(out, journal=out / "agg02.db")
    storage.update(
        forecast_days_until_budget(
            storage["measured_files_bytes"],
            storage["intelligence_budget_bytes"],
            None,
            None,
        )
    )
    save_json(out / "campaign.json", campaign)
    report = build_report(
        campaign, out / "report", storage=storage, retention=retention
    )
    archive = bundle_report(out / "report", out / "report.zip")
    result = seal(
        {
            "schema": "studious.local-v2-acceptance.v2",
            "repo_sha": head,
            "data_kind": "OFFLINE_SYNTHETIC_FIXTURE",
            "backlog": verify_backlog(),
            "rollup_proofs": proofs,
            "replay": replay,
            "archived_events": pruned["archived_events"],
            "baseline_samples_preserved": baseline,
            "report_sha256": report["receipt_sha256"],
            "archive": archive,
            "elapsed_seconds": time.monotonic() - started,
            "live_authorized": False,
            "real_24h_campaign": "NOT_OBSERVED",
        }
    )
    save_json(out / "ACCEPTANCE.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = run_acceptance(args.out)
    print(
        f"OFFLINE_ACCEPTANCE_OK: {result['replay']['verified_events']} exact replay events; "
        f"{result['archived_events']} reversible archives; {len(result['backlog']['functions'])} backlog functions"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
