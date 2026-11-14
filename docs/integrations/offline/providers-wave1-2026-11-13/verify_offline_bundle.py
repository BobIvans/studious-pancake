#!/usr/bin/env python3
"""Verify the offline providers-wave1 source-dossier bundle without network access.

Checks (zero network):
1. Every REQUIRED file exists.
2. SOURCE_MANIFEST.json internal completeness per source entry:
   provider, chain, canonical_urls (non-empty), retrieved_at_utc, snapshot_status
   (from the mandated flag taxonomy), build_output_semantics, fee_fields,
   endpoints_for_quote_race, license_status, content_sha256.
3. SHA-256 of every declared dossier file matches the manifest.
4. Every acquisitions entry (BLOCKED_MISSING_PIN rows) has a typed cause,
   owner pointer and exact acquisition step.
Exit 0 = bundle OK; exit 1 = FAIL lines on stderr.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BASE = ROOT / "docs" / "integrations" / "offline" / "providers-wave1-2026-11-13"
MANIFEST = BASE / "SOURCE_MANIFEST.json"

REQUIRED = (
    "README.md",
    "SOURCE_MANIFEST.json",
    "TITAN_SOLANA.md",
    "OKX_DEX_MULTICHAIN.md",
    "OPENOCEAN_SOLANA.md",
    "RANGO_MULTICHAIN.md",
    "AFTERMATH_SUI.md",
    "CETUS_AGGREGATOR_SUI.md",
    "SEVENK_BLUEFIN7K_SUI.md",
    "FLOWX_SUI.md",
    "PROVIDER_OVERLAP_NOTES.md",
    "verify_offline_bundle.py",
)

ALLOWED_FLAGS = {
    "RAW_OFFICIAL_SNAPSHOT",
    "OFFICIAL_CONTRACT_EXTRACT_ONLY",
    "SOURCE_PIN_ONLY",
    "DOCS_REFERENCE_ONLY",
    "BLOCKED_MISSING_PIN",
}

REQUIRED_SOURCE_FIELDS = (
    "provider",
    "chain",
    "canonical_urls",
    "retrieved_at_utc",
    "snapshot_status",
    "build_output_semantics",
    "fee_fields",
    "endpoints_for_quote_race",
    "license_status",
    "dossier_file",
    "content_sha256",
)


def sha256_file(path: Path) -> str:
    """SHA-256 over line-ending-normalized bytes (CRLF->LF) so the check is
    stable across git autocrlf/eol settings; still catches any content edit."""
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    errors: list[str] = []

    for relative in REQUIRED:
        path = BASE / relative
        if path.is_file():
            print(f"OK_FILE {relative} sha256={sha256_file(path)}")
        else:
            errors.append(f"MISSING_FILE:{relative}")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    schema_version = manifest.get("schema_version", "")
    if not schema_version:
        errors.append("MANIFEST_MISSING_FIELD:schema_version")

    sources = manifest.get("sources", {})
    if len(sources) != 8:
        errors.append(f"MANIFEST_SOURCE_COUNT expected=8 actual={len(sources)}")

    for key, source in sources.items():
        for field in REQUIRED_SOURCE_FIELDS:
            value = source.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                errors.append(f"SOURCE_MISSING_FIELD:{key}.{field}")
            if field == "canonical_urls":
                if not isinstance(value, list) or not value:
                    errors.append(f"SOURCE_EMPTY_CANONICAL_URLS:{key}")
        flag = source.get("snapshot_status", "")
        if flag not in ALLOWED_FLAGS:
            errors.append(f"SOURCE_BAD_FLAG:{key}:{flag}")
        dossier_file = source.get("dossier_file", "")
        if dossier_file:
            dossier_path = BASE / dossier_file
            if not dossier_path.is_file():
                errors.append(f"SOURCE_DOSSIER_MISSING:{key}:{dossier_file}")
            else:
                actual = sha256_file(dossier_path)
                expected = source.get("content_sha256", "")
                if actual != expected:
                    errors.append(
                        f"DOSSIER_HASH_MISMATCH:{key} expected={expected} actual={actual}"
                    )
                else:
                    print(f"OK_DOSSIER_HASH {key} {dossier_file} sha256={actual}")
        retrieval = str(source.get("retrieved_at_utc", ""))
        if retrieval and len(retrieval) < 10:
            errors.append(f"SOURCE_BAD_RETRIEVAL_TIME:{key}:{retrieval}")

    acquisitions = manifest.get("acquisitions", [])
    if not acquisitions:
        errors.append("MANIFEST_NO_ACQUISITIONS (typed BLOCKED_MISSING_PIN rows expected)")
    for index, item in enumerate(acquisitions):
        for field in ("id", "type", "cause", "exact_acquisition_step", "owner", "created_at_utc"):
            if not str(item.get(field, "")).strip():
                errors.append(f"ACQUISITION_MISSING_FIELD:{index}.{field}")

    if errors:
        for error in errors:
            print(f"FAIL {error}", file=sys.stderr)
        return 1

    print(
        "OFFLINE_PROVIDERS_WAVE1_BUNDLE_OK "
        f"sources={len(sources)} acquisitions={len(acquisitions)} "
        "(no network requests performed)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
