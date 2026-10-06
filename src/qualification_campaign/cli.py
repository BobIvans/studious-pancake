"""Bounded real read-only campaign and offline evidence replay.

No transaction builder, signer, submission client or promotion route exists here.
"""

import argparse
import asyncio
from contextlib import AsyncExitStack
from dataclasses import asdict
import importlib
import json
import os
from pathlib import Path
import subprocess
import time

from src.durability import UnifiedLifecycleAuthority
from src.market.discovery import DiscoveryRequest
from src.market.native_cpmm_capture import GovernedNativeCpmmCollector
from src.market.source_catalog import load_market_source_catalog
from src.market.streams import RecoverableStreamJournal
from src.provider_governance import ProviderGovernance
from src.providers.raydium_cpmm_native import NativeCaptureError
from src.routing.transport import TransportPolicy
from src.strategy.exact_cpmm_capacity import RAYDIUM_CPMM_PROGRAM_ID
from .identity import CampaignManifest, canonical_bytes, digest, manifest_from_dict
from .profiles import ProviderProfile, public_rpc_profile
from .evidence import CampaignEvidenceStore
from .rpc import NativeRootedSnapshotProvider
from .sources import (
    SourceDossier,
    CatalogDiscoveryAdapter,
    SourceIntakePlane,
    deduplicate_candidates,
)
from .transport import campaign_transport

ROOT = Path(__file__).resolve().parents[2]


def load_sources(path):
    raw = json.loads(Path(path).read_text())
    if (
        raw.get("schema_version") != "prequal.source-intake-config.v1"
        or not 1 <= len(raw.get("sources", [])) <= 8
    ):
        raise ValueError("require 1..8 reviewed source entries")
    result = []
    for row in raw["sources"]:
        dossier = dict(row["dossier"])
        dossier["profile"] = ProviderProfile(**dossier["profile"])
        d = SourceDossier(**dossier)
        adapter = row["adapter"]
        if adapter["kind"] == "catalog":
            request = DiscoveryRequest(**adapter["request"])
            if request.source_id != d.source_id:
                raise ValueError("catalog adapter/dossier source mismatch")
            a = CatalogDiscoveryAdapter(request)
        elif adapter["kind"] == "plugin":
            module, name = adapter["factory"].split(":")
            if not (
                module.startswith("src.market.")
                or module.startswith("src.qualification_campaign.")
            ):
                raise ValueError(
                    "adapter factory must be a reviewed source-checkout discovery owner"
                )
            a = getattr(importlib.import_module(module), name)(
                adapter.get("configuration", {})
            )
        else:
            raise ValueError("unsupported discovery adapter")
        result.append((d, a))
    if len({d.source_id for d, _ in result}) != len(result) or len(
        {d.profile.profile_id for d, _ in result}
    ) != len(result):
        raise ValueError("duplicate source/provider IDs")
    slots = [d.slot_id for d, _ in result if d.slot_id]
    if len(set(slots)) != len(slots):
        raise ValueError("duplicate free-source slot assignment")
    return tuple(result)


def report(evidence):
    events = evidence.replay()
    observations = [e for e in events if e.get("kind") == "source_observation"]
    statuses = {}
    for e in observations:
        by_source = statuses.setdefault(e["source_id"], {})
        by_source[e["quality_state"]] = by_source.get(e["quality_state"], 0) + 1
    candidates = {
        e["candidate_id"] for e in events if e.get("kind") == "discovery_candidate"
    }
    negatives = [
        {
            "source_id": e.get("source_id", e.get("provider_id")),
            "quality_state": e.get("quality_state", e.get("error")),
            "failure_reason": e.get("failure_reason"),
            "request_fingerprint": e.get("request_fingerprint"),
        }
        for e in events
        if e.get("error")
        or e.get("quality_state")
        in (
            "rate-limited",
            "unauthorized",
            "schema-drift",
            "empty-response",
            "http-error",
        )
    ]
    quorum = [e for e in events if e.get("kind") == "rooted_snapshot_bundle"]
    real_observation = any(
        e.get("http_status") == 200 and e.get("response_hash") for e in observations
    )
    return {
        "schema_version": "prequal.campaign-handoff.v1",
        "campaign_id": evidence.manifest.campaign_id,
        "manifest": evidence.manifest.to_dict(),
        "journal_head": evidence.head,
        "campaign_readiness": {
            "target": "READ_ONLY_REAL_DATA_CAMPAIGN_V1",
            "status": "PASS" if real_observation else "BLOCKED",
            "reasons": (
                [] if real_observation else ["NO_SUCCESSFUL_REAL_SOURCE_OBSERVATION"]
            ),
        },
        "qualification_verdict": "BLOCKED",
        "production_promotion": False,
        "candidate_count": len(candidates),
        "source_outcomes": statuses,
        "negative_evidence": negatives,
        "rpc_verdicts": [q["quorum"] for q in quorum],
        "remaining_verdict_blockers": [
            "INDEPENDENT_ROOTED_QUORUM_REQUIRED",
            "DEPLOYMENT_SOURCE_BINDING_MISSING",
            "CONTINUOUS_CAPTURE_NOT_IMPLEMENTED",
            "FORWARD_HOLDOUT_MISSING",
            "COST_FINANCING_UNKNOWN",
            "UNKNOWN_TOKEN_ORACLE_SEMANTICS_FAIL_CLOSED",
        ],
        "production_only_blockers": [
            "ACTIVE_PERSISTENCE_CUTOVER",
            "RELEASE_BOUND_72H_SOAK",
            "SECURITY_DEPLOYMENT_ROLLBACK_EVIDENCE",
        ],
        "stop_before": "QPR-04",
    }


async def capture(source_config, output, rpc_profiles=None, verify_native=1):
    sources = load_sources(source_config)
    rpcs = (
        tuple(ProviderProfile(**r) for r in json.loads(rpc_profiles.read_text()))
        if rpc_profiles
        else (public_rpc_profile(),)
    )
    if (
        not 0 <= verify_native <= 2
        or not 1 <= len(rpcs) <= 4
        or any(p.role != "rpc" for p in rpcs)
    ):
        raise ValueError("bounded read-only native verification required")
    profiles = (*tuple(d.profile for d, _ in sources), *rpcs)
    if len({p.profile_id for p in profiles}) != len(profiles):
        raise ValueError("duplicate provider IDs")
    generations = {}
    for d, _ in sources:
        d.require_current(time.time_ns())
        generations[d.source_id] = asdict(d)
    for p in profiles:
        if p.profile_id in generations:
            raise ValueError("source and provider IDs must be distinct")
        generations[p.profile_id] = asdict(p)
    manifest = CampaignManifest.create(
        ROOT,
        main_sha=subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "origin/main^{commit}"], text=True
        ).strip(),
        configuration={
            "capture": {
                "sources": json.loads(Path(source_config).read_text()),
                "verify_native": verify_native,
            },
            "transport": {
                "max_attempts": 1,
                "max_response_bytes": 8_000_000,
                "max_string_length": 6_000_000,
            },
        },
        sources=generations,
    )
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "campaign-manifest.json"
    if manifest_path.exists() and manifest_path.read_bytes() != canonical_bytes(
        manifest.to_dict()
    ):
        raise ValueError("CAMPAIGN_GENERATION_MISMATCH")
    if not manifest_path.exists():
        with manifest_path.open("xb") as handle:
            handle.write(canonical_bytes(manifest.to_dict()))
            handle.flush()
            os.fsync(handle.fileno())
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
        gov = ProviderGovernance(
            {
                p.profile_id: p.entitlement(expires_at_epoch_seconds=expires)
                for p in profiles
            },
            store=store,
        )
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
        credential_headers = {}
        for p in profiles:
            if p.auth_header:
                value = os.environ.get(p.credential_ref)
                if not value:
                    raise ValueError("MISSING_CREDENTIAL_BINDING:" + p.credential_ref)
                credential_headers[p.profile_id] = {
                    p.auth_header: (
                        ("Bearer " + value)
                        if p.auth_header == "Authorization"
                        else value
                    )
                }
        catalog = load_market_source_catalog()
        for d, _ in sources:
            try:
                catalog.require(d.source_id)
            except ValueError:
                if d.slot_id is None:
                    raise ValueError("new source requires existing FREE-SOURCE slot")
                catalog = catalog.with_intake(d.catalog_entry())
        intake = SourceIntakePlane(
            catalog, gov, transport, evidence, credential_headers=credential_headers
        )
        records = []
        for d, a in sources:
            evidence.append(
                d.source_id,
                {"kind": "source_dossier", "dossier": asdict(d)},
                observed_at_ns=time.time_ns(),
            )
            gathered, _ = await intake.collect(d, a)
            records.extend(gathered)
        universe = deduplicate_candidates(records)
        evidence.append(
            "universe",
            {"kind": "candidate_universe", "candidates": universe},
            observed_at_ns=time.time_ns(),
        )
        # Only supported CPMM metadata is a verification hint; it is never execution truth.
        selected = [(c, p) for c, p in records if p["source_id"] == "raydium"]
        selected = sorted(
            {c.identity: (c, p) for c, p in selected}.values(),
            key=lambda r: r[0].identity,
        )[:verify_native]
        for candidate, provenance in selected:
            collectors = [
                GovernedNativeCpmmCollector(
                    gov,
                    transport,
                    profile=p,
                    evidence_store=evidence,
                    auth_headers=credential_headers.get(p.profile_id),
                )
                for p in rpcs
            ]
            provider = NativeRootedSnapshotProvider(collectors, evidence)
            try:
                await provider.collect((candidate.market_id,))
            except NativeCaptureError:
                continue
            bundles = [
                e
                for e in journal.events(available_at_ns=2**63 - 1)
                if e.source == "rpc-quorum"
            ]
            intake.link_verification(candidate, provenance, bundles[-1].identity)
        final = report(evidence)
        final["governance"] = {
            p.profile_id: await gov.snapshot(p.profile_id) for p in profiles
        }
    (output / "report.json").write_bytes(canonical_bytes(final))
    return final


def replay(output):
    manifest = manifest_from_dict(
        json.loads((output / "campaign-manifest.json").read_text())
    )
    journal = RecoverableStreamJournal(
        output / "campaign-evidence.sqlite", max_events=10_000
    )
    try:
        return report(CampaignEvidenceStore(journal, manifest))
    finally:
        journal.close()


def blank_source_template(slot_id):
    path = (
        ROOT
        / "docs/roadmap/prequal-rnd-2026-10-06/package/data/blank_source_slots.json"
    )
    slots = json.loads(path.read_text())["slots"]
    slot = next((s for s in slots if s["slot_id"] == slot_id), None)
    if slot is None:
        raise ValueError("unknown FREE-SOURCE slot")
    return {
        "schema_version": "prequal.source-intake-config.v1",
        "planning_slot": slot,
        "sources": [
            {
                "dossier": {
                    "source_id": slot_id,
                    "slot_id": slot_id,
                    "label": "",
                    "profile": {
                        "profile_id": "discovery-" + slot_id,
                        "provider": "",
                        "operator": "",
                        "correlation_group": "",
                        "endpoint": "",
                        "official_docs": "",
                        "role": "discovery",
                        "request_limit": 1,
                        "window_seconds": 60,
                        "campaign_attempt_cap": 10,
                    },
                    "checked_at": "",
                    "docs_sha256": "",
                    "request_schema_version": "",
                    "response_schema_version": "",
                    "schema_fingerprint": "",
                    "terms_url": "",
                    "classification": "DISCOVERY_ONLY",
                },
                "adapter": {"kind": "plugin", "factory": "", "configuration": {}},
            }
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("capture")
    c.add_argument("--source-config", type=Path, required=True)
    c.add_argument("--output", type=Path, required=True)
    c.add_argument("--rpc-profiles", type=Path)
    c.add_argument("--verify-native", type=int, default=1)
    r = sub.add_parser("replay")
    r.add_argument("--output", type=Path, required=True)
    t = sub.add_parser("intake-template")
    t.add_argument("--slot", required=True)
    t.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "intake-template":
            args.output.write_text(
                json.dumps(blank_source_template(args.slot), indent=2) + "\n"
            )
            return 0
        result = (
            asyncio.run(
                capture(
                    args.source_config,
                    args.output,
                    args.rpc_profiles,
                    args.verify_native,
                )
            )
            if args.command == "capture"
            else replay(args.output)
        )
        print(
            json.dumps(
                {
                    "campaign_id": result["campaign_id"],
                    "readiness": result["campaign_readiness"],
                    "qualification_verdict": result["qualification_verdict"],
                    "candidate_count": result["candidate_count"],
                },
                sort_keys=True,
            )
        )
        return 0 if result["campaign_readiness"]["status"] == "PASS" else 3
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(
            json.dumps(
                {
                    "campaign_readiness": "BLOCKED",
                    "error_category": type(exc).__name__,
                    "reason": (
                        str(exc)
                        if isinstance(exc, ValueError)
                        else "setup-or-runtime-failure"
                    ),
                }
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
