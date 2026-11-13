#!/usr/bin/env python3
"""Verify the offline Solana P0 source bundle without network access."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BASE = Path("docs/integrations/offline/solana-p0")
MANIFEST = ROOT / BASE / "SOURCE_MANIFEST.json"
VENDOR_MANIFEST = ROOT / BASE / "VENDOR_SOURCE_MANIFEST.json"

REQUIRED = (
    "README.md",
    "SOURCE_MANIFEST.json",
    "VENDOR_SOURCE_MANIFEST.json",
    "SOLANA_RPC_STATE.md",
    "SOLANA_DISCOVERY_SOURCES.md",
    "JUPITER_SWAP_V2.md",
    "JUPITER_SWAP_V2.openapi.yaml",
    "ZEROX_SOLANA_SWAP.md",
    "DIRECT_STATE_RAYDIUM_ORCA_METEORA.md",
    "vendor-reference/README.md",
    "verify_offline_bundle.py",
)

def git_blob_sha1(path: Path) -> str:
    result = subprocess.run(
        ["git", "hash-object", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()

def main() -> int:
    main_manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    vendor_manifest = json.loads(VENDOR_MANIFEST.read_text(encoding="utf-8"))
    errors: list[str] = []

    for relative in REQUIRED:
        path = ROOT / BASE / relative
        if not path.is_file():
            errors.append(f"MISSING:{relative}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        print(f"OK_FILE {relative} sha256={digest}")

    jup_path = ROOT / BASE / "JUPITER_SWAP_V2.openapi.yaml"
    expected_jup = main_manifest["sources"]["jupiter_swap_v2_openapi"]["upstream_git_blob_sha1"]
    actual_jup = git_blob_sha1(jup_path) if jup_path.is_file() else ""
    if actual_jup != expected_jup:
        errors.append(f"JUPITER_OPENAPI_GIT_BLOB_MISMATCH expected={expected_jup} actual={actual_jup}")
    else:
        print(f"OK_UPSTREAM_GIT_BLOB jupiter_swap_v2_openapi={actual_jup}")

    for item in vendor_manifest["files"]:
        path = ROOT / item["local_path"]
        if not path.is_file():
            errors.append(f"MISSING_VENDOR:{item['local_path']}")
            continue
        actual = git_blob_sha1(path)
        expected = item["upstream_git_blob_sha1"]
        if actual != expected:
            errors.append(f"VENDOR_BLOB_MISMATCH:{item['local_path']} expected={expected} actual={actual}")
        else:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            print(f"OK_VENDOR {item['key']} git_blob_sha1={actual} sha256={digest}")

    if errors:
        for error in errors:
            print(f"FAIL {error}", file=sys.stderr)
        return 1

    print(f"OFFLINE_DOC_BUNDLE_OK vendor_files={len(vendor_manifest['files'])} (no network requests performed)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
