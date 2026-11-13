#!/usr/bin/env python3
"""Verify checked-in Solana P0 docs without network access."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BASE = Path("docs/integrations/offline/solana-p0")
MANIFEST = ROOT / BASE / "SOURCE_MANIFEST.json"

REQUIRED = (
    "README.md",
    "SOURCE_MANIFEST.json",
    "SOLANA_RPC_STATE.md",
    "JUPITER_SWAP_V2.md",
    "JUPITER_SWAP_V2.openapi.yaml",
    "ZEROX_SOLANA_SWAP.md",
    "DIRECT_STATE_RAYDIUM_ORCA_METEORA.md",
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
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    errors: list[str] = []
    for relative in REQUIRED:
        path = ROOT / BASE / relative
        if not path.is_file():
            errors.append(f"MISSING:{relative}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        print(f"OK_FILE {relative} sha256={digest}")

    yaml_path = ROOT / BASE / "JUPITER_SWAP_V2.openapi.yaml"
    expected = data["sources"]["jupiter_swap_v2_openapi"]["upstream_git_blob_sha1"]
    actual = git_blob_sha1(yaml_path) if yaml_path.is_file() else ""
    if actual != expected:
        errors.append(
            f"JUPITER_OPENAPI_GIT_BLOB_MISMATCH expected={expected} actual={actual}"
        )
    else:
        print(f"OK_UPSTREAM_GIT_BLOB jupiter_swap_v2_openapi={actual}")

    for task in (
        ROOT / "docs/roadmap/p0-offline-execution-master-2026-11-13/tasks/P0-1_SOLANA_INTAKE_DYNAMIC_UNIVERSE.md",
        ROOT / "docs/roadmap/p0-offline-execution-master-2026-11-13/tasks/P0-2_JUPITER_0X_QUOTES.md",
        ROOT / "docs/roadmap/p0-offline-execution-master-2026-11-13/tasks/P0-3_DIRECT_STATE_VERIFICATION.md",
        ROOT / "docs/roadmap/p0-offline-execution-master-2026-11-13/tasks/P1_P2_AFTER_P0.md",
    ):
        if not task.is_file():
            errors.append(f"MISSING_TASK:{task.relative_to(ROOT)}")
        else:
            print(f"OK_TASK {task.relative_to(ROOT)}")

    if errors:
        for error in errors:
            print(f"FAIL {error}", file=sys.stderr)
        return 1
    print("OFFLINE_DOC_BUNDLE_OK (no network requests performed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
