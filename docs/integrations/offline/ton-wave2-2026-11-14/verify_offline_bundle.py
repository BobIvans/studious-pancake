"""Zero-network verifier for the TON wave-2 offline dossier bundle.

Checks required files, recomputes SHA-256 over the mirrored official
specifications, cross-checks manifest pins/statuses, and prints audit digests.
Performs no network access and no live provider qualification.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import json
import sys

BUNDLE = Path(__file__).resolve().parent

REQUIRED_FILES = (
    "README.md",
    "SOURCE_MANIFEST.json",
    "TONCO_DISCOVERY_SURFACE.md",
    "OMNISTON_V1BETA8_VERIFY.md",
    "STONFI_SCHEMA_VERIFY_WAVE2.md",
    "TON_STATE_PROVIDERS_WAVE2.md",
    "TON_ATOMICITY_RESEARCH.md",
    "REPORT.md",
    "verify_offline_bundle.py",
    "vendor-reference/toncenter-v2/openapi.json",
    "vendor-reference/opentonapi/openapi.yml",
    "vendor-reference/opentonapi/LICENSE",
)

MIRRORED_SPECS = {
    "vendor-reference/toncenter-v2/openapi.json": "toncenter_v2_openapi_json",
    "vendor-reference/opentonapi/openapi.yml": "opentonapi_openapi_yml",
    "vendor-reference/opentonapi/LICENSE": "opentonapi_license",
}

ALLOWED_STATUSES = {
    "PINNED_CURRENT",
    "PINNED_STALE",
    "MISSING_PIN",
    "BLOCKED_MISSING_PIN",
    "BLOCKED_LIVE_CAPTURE_NOT_AUTHORIZED",
}


def main() -> int:
    failures: list[str] = []
    digests: dict[str, str] = {}

    for relative in REQUIRED_FILES:
        path = BUNDLE / relative
        if not path.is_file() or path.stat().st_size == 0:
            failures.append(f"missing or empty required file: {relative}")

    manifest_path = BUNDLE / "SOURCE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if manifest.get("wave_label") != "ton-wave2-2026-11-14":
        failures.append("manifest wave_label mismatch")
    if manifest.get("prepared_at_utc") != "2026-11-14":
        failures.append("manifest prepared_at_utc mismatch")
    if (
        manifest.get("repository_base_sha_audited")
        != "e2b65c0ceefdc6f9f99cdc0187ff23dc7815acc8"
    ):
        failures.append("manifest base SHA mismatch")

    sources = manifest.get("sources", {})
    expected_sources = {
        "tonco",
        "omniston",
        "stonfi_dex_rest",
        "toncenter",
        "tonapi",
        "ton_atomicity",
    }
    if set(sources) != expected_sources:
        failures.append(f"manifest sources mismatch: {sorted(sources)}")
    for name, source in sources.items():
        status = source.get("status")
        if status not in ALLOWED_STATUSES:
            failures.append(f"source {name} has untyped status {status!r}")
        if source.get("retrieved_at_utc") != "2026-11-14":
            failures.append(f"source {name} retrieval date is not 2026-11-14")
        if not source.get("canonical_urls"):
            failures.append(f"source {name} has no canonical URLs")

    for relative, manifest_key in MIRRORED_SPECS.items():
        path = BUNDLE / relative
        if not path.is_file():
            continue  # already reported as missing
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        digests[relative] = digest
        pinned = manifest.get("vendor_reference_manifest", {}).get(manifest_key, {})
        if pinned.get("sha256") != digest:
            failures.append(f"SHA-256 pin mismatch for {relative}")
        if pinned.get("bytes") not in (None, len(raw)):
            failures.append(f"byte-length pin mismatch for {relative}")
        blob = pinned.get("upstream_git_blob_sha1")
        if blob is not None:
            local_blob = hashlib.sha1(b"blob %d\x00" % len(raw) + raw).hexdigest()
            if blob != local_blob:
                failures.append(f"Git blob SHA-1 pin mismatch for {relative}")

    wave1 = BUNDLE.parent / "ton-wave1-2026-11-13" / "SOURCE_MANIFEST.json"
    if not wave1.is_file():
        failures.append("wave-1 baseline manifest not found next to the wave-2 bundle")

    print("ton-wave2 offline bundle verification")
    for relative, digest in sorted(digests.items()):
        print(f"  sha256 {digest}  {relative}")
    for name, source in sorted(sources.items()):
        print(f"  {source.get('status', 'UNSET'):<28} {name}")
    if failures:
        print("FAILURES:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("OK: all required files present, pins consistent, statuses typed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
