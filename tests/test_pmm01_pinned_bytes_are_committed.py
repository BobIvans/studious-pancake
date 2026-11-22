"""PMM-01: byte-hash-pinned provenance must equal the committed blob bytes.

Regression for the PR #665 CI failures: ``core.autocrlf=true`` normalized the
committed blobs to LF while SHA256SUMS and scenario_manifest pin the produced
bytes, so every clean checkout (Linux CI included) failed
``vendor_mirror_sha256sums`` and ``results_digest_chain``.  The committed
blobs now carry the exact produced bytes (``-text`` attributes in
.gitattributes); this test re-derives both pins from git itself.
"""

import hashlib
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
MIRROR = "vendor/strategy-research/pmm-sim-cc4ae891"
SUMS = f"{MIRROR}/SHA256SUMS"
CSV = "research/pmm-sim-caller-profile/caller_profile_results.csv"
MANIFEST = "research/pmm-sim-caller-profile/scenario_manifest_v1.json"


def blob_sha256(path: str) -> str:
    raw = subprocess.check_output(["git", "-C", str(ROOT), "show", f"HEAD:{path}"])
    return hashlib.sha256(raw).hexdigest()


def test_committed_mirror_blobs_match_sha256_sums():
    entries = [
        line.split("  ", 1)
        for line in (ROOT / SUMS).read_text().splitlines()
        if line.strip()
    ]
    assert len(entries) >= 100
    for expected, relpath in entries:
        observed = blob_sha256(f"{MIRROR}/{relpath}")
        assert observed == expected, relpath


def test_committed_csv_blob_matches_scenario_manifest_receipt():
    import json

    manifest = json.loads((ROOT / MANIFEST).read_text())
    expected = manifest["results_csv_sha256"]
    observed = blob_sha256(CSV)
    assert observed == expected


def test_gitattributes_blocks_eol_conversion_for_pinned_paths():
    attrs = subprocess.check_output(
        [
            "git",
            "-C",
            str(ROOT),
            "check-attr",
            "text",
            "--",
            f"{MIRROR}/.gitignore",
            CSV,
        ],
        text=True,
    )
    assert "text: unspecified" not in attrs
    assert "text: unset" in attrs
