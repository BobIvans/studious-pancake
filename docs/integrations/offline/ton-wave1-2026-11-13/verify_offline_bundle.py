#!/usr/bin/env python3
"""Verify the offline TON wave-1 source bundle without network access."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BASE = Path("docs/integrations/offline/ton-wave1-2026-11-13")
MANIFEST = ROOT / BASE / "SOURCE_MANIFEST.json"

REQUIRED = (
    "README.md",
    "SOURCE_MANIFEST.json",
    "TON_DISCOVERY_SOURCES.md",
    "STONFI_REST_V1.md",
    "OMNISTON_V1BETA8.md",
    "DEDUST_API_V2.md",
    "SWAPCOFFEE_AGGREGATOR_V1.md",
    "TON_STATE_PROVIDERS.md",
    "verify_offline_bundle.py",
)

# Every mirrored upstream file must be byte-identical to the pinned upstream
# Git blob (ston-fi/api @ 0a6113ba3aa43da2ac1c9094977e181d3881f226, MIT).
VENDOR_DIR = "vendor-reference/stonfi-api"


def git_blob_sha1(path: Path) -> str:
    result = subprocess.run(
        ["git", "hash-object", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> int:
    if not MANIFEST.is_file():
        print(f"FAIL MISSING:{MANIFEST}", file=sys.stderr)
        return 1
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    errors: list[str] = []
    vendor_checks = 0

    for relative in REQUIRED:
        path = ROOT / BASE / relative
        if not path.is_file():
            errors.append(f"MISSING:{relative}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        print(f"OK_FILE {relative} sha256={digest}")

    sources = manifest.get("sources", {})
    stonfi = sources.get("stonfi_dex_rest_v1", {})
    blob_pins = stonfi.get("upstream_git_blob_sha1", {})
    if not blob_pins:
        errors.append("MISSING_PINS:stonfi_dex_rest_v1.upstream_git_blob_sha1")
    for relative, expected in sorted(blob_pins.items()):
        path = ROOT / BASE / relative
        if not path.is_file():
            errors.append(f"MISSING_VENDOR:{relative}")
            continue
        actual = git_blob_sha1(path)
        if actual != expected:
            errors.append(
                f"VENDOR_BLOB_MISMATCH:{relative} expected={expected} actual={actual}"
            )
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        vendor_checks += 1
        print(f"OK_VENDOR {relative} git_blob_sha1={actual} sha256={digest}")

    # Contract-critical pins must appear verbatim in the dossier texts.
    invariants = {
        "STONFI_REST_V1.md": (
            "asset_list",
            "pool_list",
            "0a6113ba3aa43da2ac1c9094977e181d3881f226",
        ),
        "DEDUST_API_V2.md": ("/v2/pools", "reserves", "tradeFee"),
        "SWAPCOFFEE_AGGREGATOR_V1.md": ("/v1/pools", "total_count", "max 100"),
        "OMNISTON_V1BETA8.md": (
            "stonfi.omni.v1beta8",
            "QuoteRpc.Quote",
            "omni-ws.ston.fi",
        ),
        "TON_STATE_PROVIDERS.md": ("Ratelimit exceed", "BLOCKED_MISSING_PIN"),
        "TON_DISCOVERY_SOURCES.md": (
            "TON_ASYNC_MULTI_CONTRACT",
            "correlation_group=ton:pool:",
        ),
    }
    for relative, needles in invariants.items():
        path = ROOT / BASE / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for needle in needles:
            if needle not in text:
                errors.append(f"INVARIANT_MISSING:{relative}:{needle}")

    # Drift and blocker records must exist and be typed.
    drift = manifest.get("known_contract_drift", [])
    if not any(item.get("status") == "DRIFT_RECORDED_NEEDS_LIVE_PIN" for item in drift):
        errors.append("DRIFT_RECORD_MISSING:/v1/stats legacy drift")
    if not sources.get("tonco", {}).get("snapshot_status") == "BLOCKED_MISSING_PIN":
        errors.append("BLOCKER_MISSING:tonco BLOCKED_MISSING_PIN")
    if (
        not sources.get("toncenter", {})
        .get("snapshot_status", "")
        .startswith("RATE_LIMIT_AND_429_ENVELOPE_VERIFIED")
    ):
        errors.append("BLOCKER_MISSING:toncenter method-schema pin record")
    if (
        not sources.get("tonapi", {})
        .get("snapshot_status", "")
        .startswith("BASE_URL_ENDPOINTS_AND_TIERS_VERIFIED")
    ):
        errors.append("BLOCKER_MISSING:tonapi response-schema pin record")
    if not manifest.get("live_capture_blockers"):
        errors.append("BLOCKER_MISSING:live capture authorization record")

    if errors:
        for error in errors:
            print(f"FAIL {error}", file=sys.stderr)
        return 1

    print(
        "OFFLINE_DOC_BUNDLE_OK "
        f"vendor_files={vendor_checks} "
        "(no network requests performed)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
