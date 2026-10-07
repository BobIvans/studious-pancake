"""Offline campaign bundles: exact evidence and unknowns, never invented metrics."""

from collections import Counter
from pathlib import Path
import zipfile
from src.production_qualification import (
    AGG04EpisodeEvidence,
    AGG04VariantEvidence,
    AGG04ProbeEvidence,
    AGG04PairedEpisodeResult,
    AGG04DelayStressSample,
)
from .common import (
    atomic_bytes,
    canonical,
    digest,
    file_hash,
    save_json,
    seal,
    verify_seal,
)
from .experiment_manifest import verify_experiment_identity
from .provider_utility import provider_funnel
from .strategy_report import (
    build_strategy_funnel,
    compare_strategy_baselines,
    build_delay_stress,
    build_resource_cost_report,
)

UNKNOWN = {"status": "NOT_OBSERVED", "value": None}


def build_report(
    campaign: dict,
    destination: str | Path,
    *,
    storage: dict | None = None,
    retention: dict | None = None,
) -> dict:
    out = Path(destination)
    if out.exists() and any(out.iterdir()):
        raise ValueError("report output must be a new or empty directory")
    identity = campaign.get("experiment")
    if identity is not None:
        verify_experiment_identity(identity)
    episodes = campaign.get("episodes", [])
    for episode in episodes:
        verify_seal(episode)
        if identity is None or episode["experiment_identity"] != identity:
            raise ValueError("episode experiment identity mismatch")
    providers = campaign.get("provider_rows")
    qualification = campaign.get("qualification")
    if qualification is not None:
        funnel = build_strategy_funnel(
            episodes=tuple(
                AGG04EpisodeEvidence(**r) for r in qualification["episodes"]
            ),
            variants=tuple(
                AGG04VariantEvidence(**r) for r in qualification["variants"]
            ),
            probes=tuple(AGG04ProbeEvidence(**r) for r in qualification["probes"]),
            survival_horizon_ms=qualification["survival_horizon_ms"],
        )
    else:
        funnel = dict(UNKNOWN)
    negative = [r for episode in episodes for r in episode["negative_examples"]]
    refs = [
        {
            "episode_ref": e["receipt_sha256"],
            "experiment_ref": identity["receipt_sha256"] if identity else None,
            "raw_source_refs": e["raw_source_refs"],
        }
        for e in episodes
    ]
    paired = campaign.get("paired_results")
    delays = campaign.get("delay_samples")
    comparison = (
        compare_strategy_baselines([AGG04PairedEpisodeResult(**r) for r in paired])
        if paired is not None
        else dict(UNKNOWN)
    )
    metrics = {
        "comparison": comparison,
        "delay_stress": (
            build_delay_stress([AGG04DelayStressSample(**r) for r in delays])
            if delays is not None
            else dict(UNKNOWN)
        ),
        "top_rejection_reasons": dict(Counter(r["reason_code"] for r in negative)),
        "episode_outcomes": dict(
            Counter(e["episode"]["outcome_state"] for e in episodes)
        ),
        "top_pairs_routes": campaign.get("pairs_routes", dict(UNKNOWN)),
    }
    resources = build_resource_cost_report(
        [e["resource_usage"] or {} for e in episodes]
    )
    quality = {
        "gap_events": (
            sum(
                bool(r.get("gap_before"))
                for e in episodes
                for r in e["raw_source_refs"]
            )
            if episodes
            else None
        ),
        "episode_count": len(episodes) if "episodes" in campaign else None,
        "observation_generations": [
            m["generation_identity"] for e in episodes for m in e["market_observations"]
        ],
        "status": "OBSERVED" if episodes else "NOT_OBSERVED",
    }
    files = {
        "STORAGE.json": storage or dict(UNKNOWN),
        "RETENTION.json": retention or dict(UNKNOWN),
        "FUNNEL.json": funnel,
        "STRATEGY_METRICS.json": metrics,
        "PROVIDER_UTILITY.json": (
            provider_funnel(providers) if providers is not None else dict(UNKNOWN)
        ),
        "DATA_QUALITY.json": quality,
        "RESOURCE_USAGE.json": resources,
        "CHANGE_VS_BASELINE.json": comparison,
    }
    streams = {
        "NEGATIVE_EXAMPLES.jsonl": negative,
        "TOP_EPISODES.jsonl": episodes,
        "LAYA_TRIAGE.jsonl": campaign.get("laya_triage", []),
        "FINDINGS.jsonl": campaign.get("findings", []),
        "EVIDENCE_REFS.jsonl": refs,
    }
    for receipt in streams["LAYA_TRIAGE.jsonl"]:
        verify_seal(receipt)
        if receipt["live_authorized"] or receipt["delete_authorized"]:
            raise ValueError("triage authority violation")
    out.mkdir(parents=True, exist_ok=True)
    for name, value in files.items():
        save_json(out / name, value)
    for name, rows in streams.items():
        atomic_bytes(out / name, b"".join(canonical(r) + b"\n" for r in rows))
    summary = (
        "# Local intelligence retrospective\n\n"
        f"Experiment: {identity['experiment']['experiment_id'] if identity else 'NOT_OBSERVED'}\n\n"
        f"Repo SHA: {identity['repo_sha'] if identity else 'NOT_OBSERVED'}\n\n"
        f"Episodes: {len(episodes) if 'episodes' in campaign else 'NOT_OBSERVED'}; "
        f"negative examples: {len(negative) if episodes else 'NOT_OBSERVED'}.\n\n"
        "All numerical conclusions are in the checksum-bound JSON files. "
        "Absent campaign, provider, quota or disk-rate measurements remain NOT_OBSERVED.\n\n"
        "Laya is advisory. Live authority is disabled. Raw pruning defaults to dry-run.\n"
    )
    atomic_bytes(out / "00_SUMMARY.md", summary.encode())
    atomic_bytes(
        out / "REPORT.txt", (summary + "\n" + canonical(files).decode() + "\n").encode()
    )
    manifest = seal(
        {
            "schema": "studious.report-bundle.v2",
            "experiment": identity,
            "campaign_sha256": digest(campaign),
            "window": campaign.get("window", dict(UNKNOWN)),
            "files": {
                p.name: {"sha256": file_hash(p), "bytes": p.stat().st_size}
                for p in sorted(out.iterdir())
            },
            "live_authorized": False,
            "data_kind": campaign.get("data_kind", "UNKNOWN"),
        }
    )
    save_json(out / "MANIFEST.json", manifest)
    verify_report(out)
    return manifest


def verify_report(root: str | Path) -> dict:
    from .common import load_json

    root = Path(root)
    manifest = load_json(root / "MANIFEST.json")
    verify_seal(manifest)
    for name, metadata in manifest["files"].items():
        if Path(name).name != name or file_hash(root / name) != metadata["sha256"]:
            raise ValueError("report file checksum mismatch")
        if (root / name).stat().st_size != metadata["bytes"]:
            raise ValueError("report byte count mismatch")
    return {
        "verified": True,
        "files": len(manifest["files"]),
        "receipt_sha256": manifest["receipt_sha256"],
    }


def bundle_report(root: str | Path, destination: str | Path) -> dict:
    root, destination = Path(root), Path(destination)
    proof = verify_report(root)
    if destination.exists():
        raise ValueError("bundle destination exists")
    with zipfile.ZipFile(
        destination, "w", zipfile.ZIP_DEFLATED, allowZip64=True
    ) as archive:
        from .common import load_json

        manifest = load_json(root / "MANIFEST.json")
        for name in sorted([*manifest["files"], "MANIFEST.json"]):
            archive.write(root / name, name)
    with zipfile.ZipFile(destination) as archive:
        for name, metadata in manifest["files"].items():
            import hashlib

            if hashlib.sha256(archive.read(name)).hexdigest() != metadata["sha256"]:
                raise ValueError("bundle checksum mismatch")
    return {
        **proof,
        "archive_sha256": file_hash(destination),
        "archive_bytes": destination.stat().st_size,
    }
