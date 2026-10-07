"""Offline repository/AGG-02 intelligence CLI; pruning is explicitly gated."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sqlite3
import sys
import time

from src.agg02.storage import DurableRawJournal
from .common import canonical, digest, load_json, save_json
from .repo_snapshot import (
    git,
    start_snapshot,
    snapshot_status,
    verify_snapshot_roundtrip,
)
from .repo_source import (
    analyze_source,
    build_import_graph,
    resolve_reverse_imports,
)
from .repo_groups import (
    build_scc_groups,
    build_logical_segments,
    attach_tests_and_contracts,
)
from .repo_coverage import coverage_summary
from .repo_history import delta_between_snapshots
from .context_pack import build_context_pack, MODES
from .context_benchmark import (
    seed_oracle,
    benchmark_exact_retrieval,
    benchmark_context_pack,
)
from .context_archive import build_portable_archive
from .context_recovery import backup_index, restore_to_copy
from .storage_budget import read_disk_budget, forecast_days_until_budget
from .retention_policy import retention_dry_run
from .parquet_compaction import publish_partition
from .prune import prune_verified_payloads
from .rollups import build_1m_rollup, build_5m_rollup, build_1h_rollup
from .sampling import select_periodic_baseline, reservoir_sample_failures
from .reports import build_report, bundle_report
from .laya_triage import batch_score
from .triage_loop import collect_candidates_for_triage


def duration(value: str) -> int:
    match = re.fullmatch(r"([1-9][0-9]*)(s|m|h|d)", value)
    if not match:
        raise argparse.ArgumentTypeError("expected positive duration such as 24h")
    return (
        int(match[1])
        * {"s": 1000, "m": 60_000, "h": 3_600_000, "d": 86_400_000}[match[2]]
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state-root", type=Path, default=Path("/workspace/local-intelligence-data")
    )
    planes = parser.add_subparsers(dest="plane", required=True)
    repo = planes.add_parser("repo").add_subparsers(dest="command", required=True)
    scan = repo.add_parser("scan")
    scan.add_argument("--repo", type=Path, default=Path.cwd())
    scan.add_argument("--ref", default="HEAD")
    scan.add_argument("--batch-size", type=int)
    for command in ("status", "benchmark", "coverage"):
        repo.add_parser(command)
    export = repo.add_parser("export")
    export.add_argument("--mode", choices=sorted(MODES), default="WHOLE_REPO_INDEXED")
    export.add_argument("--seed")
    export.add_argument("--goal", default="")
    export.add_argument("--budget-bytes", type=int, default=64_000)
    export.add_argument("--out", type=Path, required=True)
    export.add_argument("--continuation", type=Path)
    export.add_argument("--changed", nargs="*", default=[])
    delta = repo.add_parser("delta")
    delta.add_argument("--from", dest="before", required=True)
    delta.add_argument("--offset", type=int, default=0)
    delta.add_argument("--limit", type=int, default=100)
    archive = repo.add_parser("archive")
    archive.add_argument("--out", type=Path, required=True)
    backup = repo.add_parser("backup")
    backup.add_argument("--out", type=Path, required=True)
    restore = repo.add_parser("restore")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--sha256", required=True)
    restore.add_argument("--out", type=Path, required=True)
    storage = planes.add_parser("storage").add_subparsers(dest="command", required=True)
    for command in (
        "status",
        "forecast",
        "retention-dry-run",
        "compact",
        "prune",
        "rollups",
    ):
        sub = storage.add_parser(command)
        sub.add_argument("--journal", type=Path)
        sub.add_argument("--since", type=duration, default=21_600_000)
        sub.add_argument("--before", type=duration, default=86_400_000)
        sub.add_argument("--out", type=Path)
        sub.add_argument("--records", type=Path)
        if command == "prune":
            sub.add_argument("--dry-run", action="store_true")
            sub.add_argument("--execute", action="store_true")
            sub.add_argument("--compaction", type=Path)
            sub.add_argument("--retention", type=Path)
            sub.add_argument("--references", type=Path)
    report = planes.add_parser("report").add_subparsers(dest="command", required=True)
    for command in ("build", "bundle"):
        sub = report.add_parser(command)
        sub.add_argument("--campaign", type=Path)
        sub.add_argument("--experiment")
        sub.add_argument("--since", type=duration, default=86_400_000)
        sub.add_argument("--out", type=Path, required=True)
        sub.add_argument("--formats", default="md,txt,json,zip")
        sub.add_argument("--journal", type=Path)
    compare = report.add_parser("compare")
    compare.add_argument("--baseline", type=Path, required=True)
    compare.add_argument("--candidate", type=Path, required=True)
    laya = planes.add_parser("laya").add_subparsers(dest="command", required=True)
    for command in ("triage-observations", "triage-episodes", "score-repo"):
        sub = laya.add_parser(command)
        sub.add_argument("--since", type=duration, default=3_600_000)
        sub.add_argument("--records", type=Path)
        sub.add_argument("--goal", default="")
        sub.add_argument("--model-version", default="NOT_CONFIGURED")
        sub.add_argument(
            "--decisions",
            type=Path,
            help="recorded outputs from an optional local Laya adapter, keyed by compact-state SHA",
        )
    return parser


def _current(root: Path) -> Path:
    current = load_json(root / "current.json")
    value = current["repo_sha"]
    if not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", value):
        raise ValueError("invalid current snapshot")
    return root / "snapshots" / value


def _metadata_rows(journal: Path) -> list[dict]:
    import json

    with sqlite3.connect(journal.resolve().as_uri() + "?mode=ro", uri=True) as db:
        return [
            json.loads(row[0])
            for row in db.execute(
                "SELECT envelope_json FROM raw_events ORDER BY event_id"
            )
        ]


def repo_commands(args) -> dict:
    root = args.state_root
    if args.command == "scan":
        head = (
            git(args.repo, "rev-parse", "--verify", args.ref + "^{commit}")
            .decode()
            .strip()
        )
        snapshot = root / "snapshots" / head
        state = start_snapshot(
            args.repo, snapshot, ref=head, batch_size=args.batch_size
        )
        if state["status"] != "COMPLETE":
            return {
                "status": state["status"],
                "completed": state["completed"],
                "tracked": len(state["entries"]),
            }
        proof = verify_snapshot_roundtrip(snapshot)
        manifest = load_json(snapshot / "manifest.json")
        analyses = [
            analyze_source(e["path"], (snapshot / "blobs" / e["sha256"]).read_bytes())
            for e in manifest["entries"]
            if e["status"] == "EXACT"
        ]
        graph = build_import_graph(analyses)
        groups = attach_tests_and_contracts(
            build_logical_segments(build_scc_groups(graph), analyses),
            [e["path"] for e in manifest["entries"]],
        )
        save_json(
            snapshot / "analysis.json",
            {
                "analyses": analyses,
                "graph": graph,
                "reverse_imports": resolve_reverse_imports(graph),
                "groups": groups,
            },
        )
        with sqlite3.connect(snapshot / "index.sqlite") as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS sources(path TEXT PRIMARY KEY, sha256 TEXT, analysis_json TEXT)"
            )
            db.executemany(
                "INSERT OR REPLACE INTO sources VALUES (?,?,?)",
                [(a["path"], a["sha256"], canonical(a).decode()) for a in analyses],
            )
        save_json(
            root / "current.json",
            {"repo_sha": head, "snapshot_id": manifest["snapshot_id"]},
        )
        return {
            **proof,
            "status": "COMPLETE",
            "logical_groups": len(groups),
            "coverage": coverage_summary(manifest, analyses),
        }
    snapshot = _current(root)
    if args.command == "status":
        state = snapshot_status(snapshot)
        return {
            "repo_sha": state["repo_sha"],
            "status": state["status"],
            "completed": state["completed"],
        }
    if args.command == "coverage":
        return coverage_summary(
            load_json(snapshot / "manifest.json"),
            load_json(snapshot / "analysis.json")["analyses"],
        )
    if args.command == "export":
        token = (
            load_json(args.continuation)["continuation"] if args.continuation else None
        )
        pack = build_context_pack(
            snapshot,
            mode=args.mode,
            seed=args.seed,
            goal=args.goal,
            budget_bytes=args.budget_bytes,
            continuation=token,
            changed=args.changed,
        )
        args.out.mkdir(parents=True, exist_ok=True)
        save_json(args.out / "CONTEXT.json", pack)
        return {
            "snapshot_id": pack["snapshot_id"],
            "source_bytes": pack["source_bytes"],
            "continuation": pack["continuation"],
            "proof": benchmark_context_pack(snapshot, pack),
        }
    if args.command == "benchmark":
        oracle = seed_oracle(snapshot)
        save_json(snapshot / "oracle.json", oracle)
        return benchmark_exact_retrieval(snapshot, oracle)
    if args.command == "delta":
        if not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", args.before):
            raise ValueError("--from must be a pinned repo SHA")
        return delta_between_snapshots(
            load_json(root / "snapshots" / args.before / "manifest.json"),
            load_json(snapshot / "manifest.json"),
            offset=args.offset,
            limit=args.limit,
        )
    if args.command == "archive":
        return build_portable_archive(snapshot, args.out)
    if args.command == "backup":
        return backup_index(snapshot / "index.sqlite", args.out)
    if args.command == "restore":
        return restore_to_copy(args.backup, args.out, expected_sha256=args.sha256)
    raise ValueError("unsupported repo command")


def storage_commands(args) -> dict:
    args.state_root.mkdir(parents=True, exist_ok=True)
    now = int(time.time() * 1000)
    if (
        args.command == "prune"
        and args.execute
        and (
            args.dry_run
            or not all(
                (
                    args.journal,
                    args.compaction,
                    args.retention,
                    args.references,
                    args.records,
                    args.out,
                )
            )
        )
    ):
        raise ValueError(
            "execute requires journal, compaction/retention receipts, records, references and out"
        )
    if args.command in {"status", "forecast"}:
        result = read_disk_budget(args.state_root, journal=args.journal)
        if args.command == "forecast":
            history = sorted((args.state_root / "storage-history").glob("*.json"))
            previous = [
                load_json(p) for p in history if now - int(p.stem) >= args.since
            ]
            old = previous[-1] if previous else None
            result.update(
                forecast_days_until_budget(
                    result["measured_files_bytes"],
                    result["intelligence_budget_bytes"],
                    (
                        max(
                            0,
                            result["measured_files_bytes"]
                            - old["measured_files_bytes"],
                        )
                        if old
                        else None
                    ),
                    (now - old["measured_at_ms"]) // 1000 if old else None,
                )
            )
        save_json(
            args.state_root / "storage-history" / f"{now}.json",
            {**result, "measured_at_ms": now},
        )
        return result
    if args.command == "compact":
        if args.journal is None or not args.journal.is_file() or args.out is None:
            raise ValueError("existing --journal and --out required")
        with DurableRawJournal(args.journal) as journal:
            return publish_partition(
                journal, args.out, max_available_at_ms=now - args.before
            )
    if args.command == "rollups":
        if args.journal is None or args.out is None:
            raise ValueError("--journal and --out required")
        rows = _metadata_rows(args.journal)
        result = {
            "1m": build_1m_rollup(rows),
            "5m": build_5m_rollup(rows),
            "1h": build_1h_rollup(rows),
            "baseline_sample_ids": select_periodic_baseline(rows),
            "negative_sample_ids": reservoir_sample_failures(rows),
        }
        save_json(args.out, result)
        return {"rows": len(rows), "receipt_sha256": digest(result)}
    records = (
        load_json(args.records)["records"]
        if args.records
        else (_metadata_rows(args.journal) if args.journal else [])
    )
    if not records:
        return {
            "status": "NOT_OBSERVED",
            "reason": "NO_RETENTION_RECORDS",
            "physical_mutation": False,
        }
    dry_run = retention_dry_run(records, now_ms=now, minimum_age_ms=args.before)
    if args.command == "prune" and args.execute:
        if args.dry_run or not all(
            (
                args.journal,
                args.compaction,
                args.retention,
                args.references,
                args.records,
                args.out,
            )
        ):
            raise ValueError(
                "execute requires journal, compaction/retention receipts, records, references and out"
            )
        references = load_json(args.references)
        with DurableRawJournal(args.journal) as journal:
            return prune_verified_payloads(
                journal,
                compaction=load_json(args.compaction),
                retention=load_json(args.retention),
                records=records,
                references=references["records"],
                inventory_complete=references.get("inventory_complete") is True,
                receipt_path=args.out,
            )
    if args.out:
        save_json(args.out, dry_run)
    return dry_run


def report_commands(args) -> dict:
    if args.command == "compare":
        from .experiment_manifest import compare_experiment_identity

        return compare_experiment_identity(
            load_json(args.baseline), load_json(args.candidate)
        )
    campaign_path = args.campaign
    if campaign_path is None and args.experiment:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", args.experiment):
            raise ValueError("invalid experiment path")
        campaign_path = (
            args.state_root / "experiments" / args.experiment / "campaign.json"
        )
    campaign = load_json(campaign_path) if campaign_path else {}
    if campaign:
        end = campaign.get("window", {}).get("end_ms", int(time.time() * 1000))
        start = max(0, end - args.since)
        campaign = {
            **campaign,
            "window": {
                **campaign.get("window", {}),
                "requested_start_ms": start,
                "requested_end_ms": end,
            },
        }
        if "episodes" in campaign:
            campaign["episodes"] = [
                e
                for e in campaign["episodes"]
                if start <= e["episode"]["feature_available_at"] <= end
            ]
            episode_ids = {e["episode"]["episode_id"] for e in campaign["episodes"]}
            if "qualification" in campaign:
                original = campaign["qualification"]
                variants = [
                    v for v in original["variants"] if v["episode_id"] in episode_ids
                ]
                variant_ids = {v["variant_id"] for v in variants}
                campaign["qualification"] = {
                    **original,
                    "episodes": [
                        e
                        for e in original["episodes"]
                        if e["episode_id"] in episode_ids
                    ],
                    "variants": variants,
                    "probes": [
                        p for p in original["probes"] if p["variant_id"] in variant_ids
                    ],
                }
            for key in ("paired_results", "delay_samples"):
                if key in campaign:
                    campaign[key] = [
                        r for r in campaign[key] if r["episode_id"] in episode_ids
                    ]
        if "provider_rows" in campaign:
            if any(
                type(r.get("available_at_ms")) is not int
                for r in campaign["provider_rows"]
            ):
                raise ValueError("provider availability required for --since report")
            campaign["provider_rows"] = [
                r
                for r in campaign["provider_rows"]
                if start <= r["available_at_ms"] <= end
            ]
    storage = (
        read_disk_budget(args.state_root, journal=args.journal)
        if args.state_root.exists()
        else None
    )
    manifest = build_report(campaign, args.out, storage=storage)
    if args.command == "bundle" or "zip" in args.formats.split(","):
        bundle = bundle_report(args.out, args.out.with_suffix(".zip"))
    else:
        bundle = None
    return {"receipt_sha256": manifest["receipt_sha256"], "bundle": bundle}


def laya_commands(args) -> dict:
    kind = {
        "triage-observations": "observation",
        "triage-episodes": "episode",
        "score-repo": "repo_group",
    }[args.command]
    records = load_json(args.records)["records"] if args.records else []
    if kind == "repo_group" and not records:
        groups = load_json(_current(args.state_root) / "analysis.json")["groups"]
        records = [
            {"group_id": digest(g["paths"]), "paths": g["paths"], "goal": args.goal}
            for g in sorted(
                groups,
                key=lambda g: (
                    -sum(w in " ".join(g["paths"]) for w in args.goal.split()),
                    g["paths"],
                ),
            )[:32]
        ]
    elif records:
        cutoff = int(time.time() * 1000) - args.since
        records = collect_candidates_for_triage(
            [r for r in records if r.get("available_at_ms", 0) >= cutoff]
        )
    decisions = load_json(args.decisions) if args.decisions else None
    backend = (
        (lambda state, questions: decisions["decisions"][digest(state)])
        if decisions
        else None
    )
    return {
        "decisions": batch_score(
            records,
            kind=kind,
            backend=backend,
            cache_root=args.state_root / "laya-cache",
            model_version=args.model_version,
            policy_sha=digest({"advisory": True, "prompt": "v2"}),
        ),
        "delete_authorized": False,
        "live_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = {
            "repo": repo_commands,
            "storage": storage_commands,
            "report": report_commands,
            "laya": laya_commands,
        }[args.plane](args)
        print(canonical(result).decode())
        return 0
    except (ValueError, KeyError, OSError) as exc:
        print(
            canonical({"status": "BLOCKED", "reason": str(exc)}).decode(),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
