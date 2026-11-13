"""P0-3 canonical program-id registration and offline bundle integrity.

Pins the Meteora DLMM program-id defect fix (P0_BASELINE P0-3-04
WRONG_PROGRAM_ID_REGISTERED) to the offline vendor IDL snapshot and verifies
the bundle blob hashes still match VENDOR_SOURCE_MANIFEST.json.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from src.config.addresses import MONITORED_ADDRESSES
from src.providers.meteora_dlmm_native import METEORA_DLMM_PROGRAM_ID
from src.providers.raydium_clmm_native import RAYDIUM_CLMM_PROGRAM_ID

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFECT_DLMM_ID = "LBUZKhRxPF3XUpBCjp4YzTKgLLjggiJWUna9LZJRQD3"


def _idl_program_address() -> str:
    idl = json.loads(
        (
            REPO_ROOT
            / "docs/integrations/offline/solana-p0/vendor-reference/meteora/lb_clmm.idl.json"
        ).read_text(encoding="utf-8")
    )
    return idl["address"]


def _manifest_program_ids() -> dict[str, str]:
    manifest = json.loads(
        (
            REPO_ROOT / "docs/integrations/offline/solana-p0/SOURCE_MANIFEST.json"
        ).read_text(encoding="utf-8")
    )
    return {
        name: source["program_id_mainnet"]
        for name, source in manifest["sources"].items()
        if "program_id_mainnet" in source
    }


def test_addresses_registration_matches_pinned_idl():
    assert _idl_program_address() == METEORA_DLMM_PROGRAM_ID
    assert METEORA_DLMM_PROGRAM_ID in MONITORED_ADDRESSES
    assert DEFECT_DLMM_ID not in MONITORED_ADDRESSES
    entry = MONITORED_ADDRESSES[METEORA_DLMM_PROGRAM_ID]
    assert entry["name"] == "Meteora DLMM"
    assert entry["enabled"] is True


def test_addresses_registration_matches_pinned_manifest():
    manifest_ids = _manifest_program_ids()
    assert manifest_ids["meteora_dlmm"] == METEORA_DLMM_PROGRAM_ID
    assert manifest_ids["raydium_clmm_program"] == RAYDIUM_CLMM_PROGRAM_ID
    assert MONITORED_ADDRESSES[RAYDIUM_CLMM_PROGRAM_ID]["name"] == "Raydium CLMM"


def test_quarantined_ingest_stays_quarantined():
    quarantine = json.loads(
        (REPO_ROOT / "config/jupiter_endpoint_quarantine.json").read_text(
            encoding="utf-8"
        )
    )
    quarantined = [
        q["path"]
        for q in quarantine["quarantined_paths"]
        if q.get("boundary") == "package_prefix"
    ]
    assert "src/ingest/" in quarantined


def test_offline_vendor_bundle_integrity():
    verifier = (
        REPO_ROOT / "docs/integrations/offline/solana-p0/verify_offline_bundle.py"
    )
    result = subprocess.run(
        [sys.executable, str(verifier)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
