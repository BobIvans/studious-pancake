from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.lending.jupiter_lend import JUPITER_LEND_FLASHLOAN_PROGRAM_ID
from src.lending.slumlord import SLUMLORD_PROGRAM_ID
from src.runtime.core_v1_dependency_resolver import (
    MANIFEST_ENV,
    resolve_installed_core_v1_dependencies,
)
from src.runtime.core_v1_materializer import CoreV1ReleaseProfile

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _profile() -> CoreV1ReleaseProfile:
    return CoreV1ReleaseProfile(
        profile_id="core-jupiter-lend-jupiter-v1",
        strategy="circular_arbitrage",
        lender="jupiter-lend",
        router="jupiter",
        cluster="mainnet-beta",
        genesis_hash="genesis",
        transport="rpc",
        profile_generation=1,
    )


def _manifest(*, primary_program: str | None = None) -> dict[str, object]:
    return {
        "schema_version": "core-v1.financing-evidence-manifest.v1",
        "profile_id": "core-jupiter-lend-jupiter-v1",
        "profile_generation": 1,
        "primary": {
            "lender_id": "jupiter-lend",
            "program_id": primary_program or str(JUPITER_LEND_FLASHLOAN_PROGRAM_ID),
            "deployment_generation": 1,
            "evidence_sha256": SHA_A,
            "decoder_identity": "jupiter-lend-decoder-v1",
            "decoder_generation": 1,
        },
        "rent": {
            "lender_id": "slumlord",
            "program_id": str(SLUMLORD_PROGRAM_ID),
            "deployment_generation": 1,
            "evidence_sha256": SHA_B,
            "decoder_identity": "slumlord-decoder-v1",
            "decoder_generation": 1,
        },
        "repayment_decoder": {
            "artifact_sha256": SHA_C,
            "qualified": True,
        },
    }


def _write(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "financing-evidence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_installed_generic_profile_requires_evidence_manifest() -> None:
    resolution = resolve_installed_core_v1_dependencies(_profile(), {})
    assert resolution.dependencies is None
    assert resolution.blocker == "CORE_V1_FINANCING_EVIDENCE_MANIFEST_REQUIRED"


def test_manifest_rejects_wrong_primary_program(tmp_path: Path) -> None:
    path = _write(tmp_path, _manifest(primary_program=str(SLUMLORD_PROGRAM_ID)))
    with pytest.raises(ValueError, match="PRIMARY_FINANCING_IDENTITY_MISMATCH"):
        resolve_installed_core_v1_dependencies(
            _profile(),
            {MANIFEST_ENV: str(path)},
        )


def test_valid_manifest_reaches_explicit_static_decoder_blocker(tmp_path: Path) -> None:
    path = _write(tmp_path, _manifest())
    resolution = resolve_installed_core_v1_dependencies(
        _profile(),
        {MANIFEST_ENV: str(path)},
    )
    assert resolution.dependencies is None
    assert (
        resolution.blocker
        == "CORE_V1_FINANCING_REPAYMENT_DECODER_IMPLEMENTATION_REQUIRED"
    )
    assert resolution.manifest_sha256 is not None
    assert len(resolution.manifest_sha256) == 64


def test_unqualified_decoder_evidence_stays_blocked(tmp_path: Path) -> None:
    payload = _manifest()
    decoder = dict(payload["repayment_decoder"])
    decoder["qualified"] = False
    payload["repayment_decoder"] = decoder
    path = _write(tmp_path, payload)
    resolution = resolve_installed_core_v1_dependencies(
        _profile(),
        {MANIFEST_ENV: str(path)},
    )
    assert (
        resolution.blocker
        == "CORE_V1_FINANCING_REPAYMENT_DECODER_NOT_QUALIFIED"
    )
