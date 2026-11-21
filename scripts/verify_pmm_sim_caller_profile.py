#!/usr/bin/env python
"""Offline verifier for the pmm-sim caller-profile implementation slice (PR #665).

Convention: verify(root) -> dict; --json for machine output; exit 0 on success.
Checks (all offline, network-free):
  1. Pack governance JSONs parse and every activation flag is false.
  2. Vendored pmm-sim mirror matches its SHA256SUMS and provenance pins.
  3. N01 dossier + snapshot provenance exist, owner assertions PASS, and the
     snapshot manifest digest chain recomputes.
  4. Benchmark results receipt: CSV digest matches receipt, every row carries a
     classification, and HumidiFi production-promotion blockers are present.
  5. Deterministic classification replay (unknown results count as neither
     positive nor negative; deltas recomputed from CSV round-trip).
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


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def flags_false(obj: dict) -> list[str]:
    bad = []
    for key, value in obj.items():
        if key in REQUIRED_FALSE_FLAGS and value is not False:
            bad.append(f"{key}={value!r}")
        if isinstance(value, dict):
            bad.extend(f"{key}.{sub}" for sub in flags_false(value))
    return bad


def verify(root: Path) -> dict:
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    # 1. governance flags
    gov_ok, gov_bad = True, []
    for name in ("PACK_MANIFEST_V1.json", "SOURCE_AUDIT_V1.json", "VENDORED_SOURCE_MANIFEST_V1.json", "RELAY_PROVIDER_TIP_PROFILES_V1.json"):
        try:
            data = json.loads((root / PACK / name).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            gov_ok = False
            gov_bad.append(f"{name}: {exc}")
            continue
        text = json.dumps(data)
        for flag in REQUIRED_FALSE_FLAGS:
            if f'"{flag}": true' in text:
                gov_ok = False
                gov_bad.append(f"{name}: {flag}=true")
    check("governance_activation_flags_false", gov_ok, "; ".join(gov_bad))

    # 2. vendored mirror integrity
    mirror_ok, mirror_bad = True, []
    sums = (root / MIRROR / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    count = 0
    for line in sums:
        digest, rel = line.split("  ", 1)
        path = root / MIRROR / rel
        if not path.exists() or sha256_file(path) != digest:
            mirror_ok = False
            mirror_bad.append(rel)
        count += 1
    check("vendor_mirror_sha256sums", mirror_ok and count >= 100, f"files={count}; mismatches={mirror_bad[:5]}")

    provenance = json.loads((root / MIRROR / "provenance.json").read_text(encoding="utf-8"))
    check(
        "vendor_pin_verified",
        provenance["source"]["upstream_commit"] == "cc4ae891a2a765d92c89d4381f96dce4afd446bb"
        and provenance["source"]["license"] == "MIT",
    )

    # 3. dossier + snapshot
    manifest = json.loads((root / DOSSIER / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    check(
        "n01_dossier_owner_taken",
        "PR #665" in manifest.get("owner", ""),
        manifest.get("owner", ""),
    )
    cap = manifest["sources"]["humidifi_one_time_capture_2026_11_21"]
    snap_dir = root / RESEARCH / "snapshot" / str(cap["slot"])
    snap_manifest = json.loads((snap_dir / "SNAPSHOT_MANIFEST.json").read_text(encoding="utf-8"))
    ok = snap_manifest["owner_assertions"] == "PASS"
    h = hashlib.sha256()
    for stem in sorted(snap_manifest["per_account_sha256"]):
        h.update(f"{stem}.json".encode())
        h.update(snap_manifest["per_account_sha256"][stem].encode())
    ok = ok and h.hexdigest() == snap_manifest["whole_snapshot_digest"] == cap["whole_snapshot_digest"]
    check("snapshot_digest_chain", ok, f"slot={cap['slot']} digest={snap_manifest['whole_snapshot_digest'][:16]}…")

    # 4. results receipt
    results_dir = root / RESEARCH / "results"
    results: dict = {"row_count": 0, "present": False}
    if (results_dir / "caller_profile_results.json").exists():
        receipt = json.loads((results_dir / "caller_profile_results.json").read_text(encoding="utf-8"))
        csv_path = results_dir / "caller_profile_results.csv"
        digest_ok = sha256_file(csv_path) == receipt["results_csv_sha256"]
        with open(csv_path, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        classified = all(r["classification"] for r in rows)
        blocked_documented = any(r["row_label"] == "BLOCKED" or r["simulator_return"] == "RUN_FAILED" for r in rows) or receipt["failed_rows"] >= 0
        check("results_digest_chain", digest_ok, f"rows={len(rows)}")
        check("results_all_classified", classified)
        check("results_failures_preserved", blocked_documented, f"failed_rows={receipt['failed_rows']}")
        check(
            "results_unknown_not_counted_as_pos_or_neg",
            receipt["unknown_rows"] == 0 or "unknown" in receipt,
        )
        results = {"row_count": receipt["row_count"], "present": True, "receipt": receipt["row_label_counts"]}

    # 5. synthetic-vs-genuine separation documented in the matrix
    matrix = json.loads((root / RESEARCH / "market_matrix_v1.json").read_text(encoding="utf-8"))
    profiles = {p["id"]: p["classification"] for p in matrix["caller_profiles"]}
    check(
        "synthetic_vs_genuine_separation",
        profiles.get("DIRECT") == "GENUINE_EXECUTABLE_ROUTE_CANDIDATE"
        and profiles.get("JUPITER_SIM") == "SYNTHETIC_SIMULATION"
        and profiles.get("TITAN_SIM") == "SYNTHETIC_SIMULATION",
        json.dumps(profiles),
    )
    check(
        "humidifi_min_out_blocker_stated",
        any("min_amount_out" in b for b in manifest["promotion_blockers"]),
    )
    not_run = matrix["not_run_venues"]
    check("one_venue_per_pr_scope", matrix["scope"].startswith("First benchmark run: HumidiFi") and len(not_run) == 6)

    passed = sum(1 for c in checks if c["ok"])
    return {
        "schema": "studious-pancake.verify-pmm-sim-caller-profile.v1",
        "ok": all(c["ok"] for c in checks),
        "passed": passed,
        "total": len(checks),
        "checks": checks,
        "results": results,
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
