#!/usr/bin/env python
"""Offline verifier for the pmm-sim caller-profile implementation slice (PR #665).

Convention: verify(root) -> dict; --json for machine output; exit 0 on success.
Checks (all offline, network-free):
  1. Pack governance JSONs parse and every activation flag is false.
  2. Vendored pmm-sim mirror matches its SHA256SUMS and provenance pins.
  3. N01 dossier + snapshot provenance exist, owner assertions PASS, digest chain holds.
  4. Harness artifacts: tracked patch + BUILD_RECEIPT identity, validation subset
     coverage (via committed validator semantics), runnable snapshot manifest.
  5. Scenario manifest integrity: exactly 2700 unique scenario ids, one terminal
     status each, status taxonomy valid, results CSV digest matches receipt,
     every row classified, HumidiFi production blockers stated.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

REQUIRED_FALSE_FLAGS = [
    "capture",
    "paid_feed",
    "provider_activation",
    "simulation_live_network",
    "sign",
    "send",
    "borrow",
    "live",
]
PACK = "docs/strategy-expansion/2026-11-21/prop-amm-competitive-toolchain"
MIRROR = "vendor/strategy-research/pmm-sim-cc4ae891"
DOSSIER = "docs/integrations/offline/humidifi-venue-2026-11-21"
RESEARCH = "research/pmm-sim-caller-profile"
HARNESS = "tools/prop-amm-harnesses/pmm-sim-caller-profile"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(root: Path) -> dict:
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    # 1. governance flags
    gov_bad = []
    for name in (
        "PACK_MANIFEST_V1.json",
        "SOURCE_AUDIT_V1.json",
        "VENDORED_SOURCE_MANIFEST_V1.json",
        "RELAY_PROVIDER_TIP_PROFILES_V1.json",
    ):
        text = (root / PACK / name).read_text(encoding="utf-8")
        for flag in REQUIRED_FALSE_FLAGS:
            if f'"{flag}": true' in text:
                gov_bad.append(f"{name}:{flag}")
    check("governance_activation_flags_false", not gov_bad, "; ".join(gov_bad))

    # 2. vendored mirror integrity
    sums = (root / MIRROR / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    bad = []
    for line in sums:
        digest, rel = line.split("  ", 1)
        p = root / MIRROR / rel
        if not p.exists() or sha256_file(p) != digest:
            bad.append(rel)
    check(
        "vendor_mirror_sha256sums",
        not bad and len(sums) >= 100,
        f"files={len(sums)}; mismatches={bad[:3]}",
    )
    provenance = json.loads(
        (root / MIRROR / "provenance.json").read_text(encoding="utf-8")
    )
    check(
        "vendor_pin_verified",
        provenance["source"]["upstream_commit"]
        == "cc4ae891a2a765d92c89d4381f96dce4afd446bb"
        and provenance["source"]["license"] == "MIT",
    )

    # 3. dossier + snapshot
    manifest = json.loads(
        (root / DOSSIER / "SOURCE_MANIFEST.json").read_text(encoding="utf-8")
    )
    check("n01_dossier_owner_taken", "PR #665" in manifest.get("owner", ""))
    cap = manifest["sources"]["humidifi_one_time_capture_2026_11_21"]
    snap_dir = root / RESEARCH / "snapshot" / str(cap["slot"])
    snap_manifest = json.loads(
        (snap_dir / "SNAPSHOT_MANIFEST.json").read_text(encoding="utf-8")
    )
    h = hashlib.sha256()
    for stem in sorted(snap_manifest["per_account_sha256"]):
        h.update(f"{stem}.json".encode())
        h.update(snap_manifest["per_account_sha256"][stem].encode())
    ok = (
        snap_manifest["owner_assertions"] == "PASS"
        and h.hexdigest()
        == snap_manifest["whole_snapshot_digest"]
        == cap["whole_snapshot_digest"]
    )
    check("snapshot_digest_chain", ok, f"slot={cap['slot']}")

    # 4. harness artifacts
    receipt = json.loads(
        (root / HARNESS / "upstream_patches" / "BUILD_RECEIPT.json").read_text(
            encoding="utf-8"
        )
    )
    patch_file = (
        root / HARNESS / "upstream_patches" / "sp665_benchmark_observability.patch"
    )
    check(
        "build_receipt_identity",
        receipt["binary_sha256"] and receipt["patch_sha256"] == sha256_file(patch_file),
        f"binary={receipt['binary_sha256'][:12]}…",
    )
    subset = json.loads(
        (root / RESEARCH / "validation_subset_v1.json").read_text(encoding="utf-8")
    )
    profiles = {s["scenario_id"].split("|")[3] for s in subset["scenarios"]}
    variants = {s["scenario_id"].split("|")[1] for s in subset["scenarios"]}
    check(
        "validation_subset_stratified",
        30 <= len(subset["scenarios"]) <= 50
        and profiles
        == {
            "DIRECT",
            "MAGNUS_NATIVE",
            "JUPITER_SIM",
            "DFLOW_SIM",
            "OKX_SIM",
            "TITAN_SIM",
        }
        and variants == {"humidifi", "humidifi-swap-v2", "humidifi-swap-v3"},
        f"n={len(subset['scenarios'])}",
    )
    runnable = json.loads(
        (
            root
            / RESEARCH
            / "runtime_snapshot_401101387"
            / "cfg"
            / "RUNNABLE_SNAPSHOT_MANIFEST.json"
        ).read_text(encoding="utf-8")
    )
    check(
        "aliases_verified",
        runnable.get("alias_status") == "verified"
        and all(
            a["status"] == "verified" and a["equals_primary"]
            for a in runnable.get("aliases", {}).values()
        ),
    )

    # 5. scenario manifest
    results_dir = root / RESEARCH
    receipt_m = json.loads(
        (results_dir / "scenario_manifest_v1.json").read_text(encoding="utf-8")
    )
    csv_path = results_dir / "caller_profile_results.csv"
    check(
        "manifest_count_2700",
        receipt_m["scenario_count_terminal"] == 2700
        and receipt_m["unique_scenario_ids"] == 2700,
        f"terminal={receipt_m['scenario_count_terminal']} unique={receipt_m['unique_scenario_ids']}",
    )
    check(
        "results_digest_chain", sha256_file(csv_path) == receipt_m["results_csv_sha256"]
    )
    with open(csv_path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    check(
        "results_all_classified",
        all(r["classification"] for r in rows),
        f"rows={len(rows)}",
    )
    check(
        "results_unique_ids", len({r["scenario_id"] for r in rows}) == len(rows) == 2700
    )
    valid_status_prefixes = (
        "OK_COMPLETE_ROUND_TRIP",
        "FORWARD_SWAP_FAILED",
        "REVERSE_SWAP_FAILED",
        "BLOCKED_INFRA",
        "OFFLINE_VIOLATION",
    )
    check(
        "status_taxonomy_valid",
        all(
            any(r["status"].startswith(p) for p in valid_status_prefixes) for r in rows
        ),
    )
    check(
        "deterministic_failures_preserved",
        receipt_m["status_counts"].get("FORWARD_SWAP_FAILED", 0) > 0
        and receipt_m["status_counts"].get("REVERSE_SWAP_FAILED", 0) > 0,
        str(receipt_m["status_counts"]),
    )
    check(
        "offline_zero_configured_rpc_attempts",
        receipt_m["offline_status"] == ["ZERO_CONFIGURED_RPC_ATTEMPTS"],
    )
    check(
        "humidifi_min_out_blocker_stated",
        any("min_amount_out" in b for b in manifest["promotion_blockers"]),
    )
    labels = receipt_m["row_label_counts"]
    check(
        "synthetic_vs_genuine_labels",
        "BEST_REAL_EXECUTABLE_ROUTE" in labels
        and ("BEST_SIMULATED_CALLER_PROFILE" in labels or "NO_DIFFERENCE" in labels),
        str(labels),
    )

    passed = sum(1 for c in checks if c["ok"])
    return {
        "schema": "studious-pancake.verify-pmm-sim-caller-profile.v1",
        "ok": all(c["ok"] for c in checks),
        "passed": passed,
        "total": len(checks),
        "checks": checks,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = verify(Path(args.root))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for c in report["checks"]:
            print(f"[{'PASS' if c['ok'] else 'FAIL'}] {c['name']} {c['detail']}")
        print(f"{report['passed']}/{report['total']} checks passed")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
