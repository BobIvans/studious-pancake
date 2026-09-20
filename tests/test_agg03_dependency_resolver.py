from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config.runtime import load_runtime_config
from src.execution.agg03_financing_decoder import decoder_artifact_sha256
from src.lending.jupiter_lend import JUPITER_LEND_FLASHLOAN_PROGRAM_ID
from src.lending.slumlord import SLUMLORD_PROGRAM_ID
from src.runtime.core_v1_dependency_resolver import (
    MANIFEST_ENV,
    resolve_installed_core_v1_dependencies,
)
from src.runtime.core_v1_composition import build_core_v1_composition
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
            "qualified": True,
        },
        "rent": {
            "lender_id": "slumlord",
            "program_id": str(SLUMLORD_PROGRAM_ID),
            "deployment_generation": 1,
            "evidence_sha256": SHA_B,
            "decoder_identity": "slumlord-decoder-v1",
            "decoder_generation": 1,
            "qualified": True,
        },
        "release_id": "agg03-installed-profile-v1",
        "policy_bundle_hash": SHA_C,
        "repayment_decoder": {
            "artifact_sha256": decoder_artifact_sha256(),
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


def test_valid_manifest_reaches_static_installed_dependencies(tmp_path: Path) -> None:
    path = _write(tmp_path, _manifest())
    config = load_runtime_config(
        cli_overrides={
            "runtime.mode": "paper",
            "providers.jupiter.enabled": True,
        }
    )
    resolution = resolve_installed_core_v1_dependencies(
        _profile(),
        {MANIFEST_ENV: str(path)},
        config=config,
    )
    assert resolution.dependencies is not None
    assert resolution.blocker == "CORE_V1_PROVIDER_DRAFT_SOURCE_EXTERNAL"
    assert resolution.dependencies.financing_port is not None
    assert resolution.dependencies.rent_financing_port is not None
    assert resolution.dependencies.financing_repayment_decoder is not None
    assert resolution.manifest_sha256 is not None
    assert len(resolution.manifest_sha256) == 64


def test_static_resolver_builds_canonical_installed_composition(
    tmp_path: Path,
) -> None:
    config = load_runtime_config(
        cli_overrides={
            "runtime.mode": "paper",
            "providers.jupiter.enabled": True,
        }
    )
    profile = CoreV1ReleaseProfile(
        profile_id="core-jupiter-lend-jupiter-v1",
        strategy="circular_arbitrage",
        lender="jupiter-lend",
        router="jupiter",
        cluster=config.cluster.name,
        genesis_hash=config.cluster.genesis_hash,
        transport="rpc",
        profile_generation=1,
    )
    path = _write(tmp_path, _manifest())
    resolution = resolve_installed_core_v1_dependencies(
        profile,
        {MANIFEST_ENV: str(path)},
        config=config,
    )
    assert resolution.dependencies is not None
    composition = build_core_v1_composition(
        config,
        db_path=tmp_path / "generic.sqlite3",
        profile=profile,
        dependencies=resolution.dependencies,
        external_blocker=resolution.blocker,
    )
    try:
        assert composition.admitted is True
        assert composition.planner is not None
        assert composition.vertical is not None
        assert composition.orchestrator is not None
        assert composition.capital.store is composition.authority.lifecycle
    finally:
        composition.close()


def test_decoder_artifact_mismatch_is_rejected(tmp_path: Path) -> None:
    payload = _manifest()
    decoder = dict(payload["repayment_decoder"])
    decoder["artifact_sha256"] = SHA_A
    payload["repayment_decoder"] = decoder
    path = _write(tmp_path, payload)
    config = load_runtime_config(
        cli_overrides={
            "runtime.mode": "paper",
            "providers.jupiter.enabled": True,
        }
    )
    with pytest.raises(ValueError, match="DECODER_ARTIFACT_MISMATCH"):
        resolve_installed_core_v1_dependencies(
            _profile(),
            {MANIFEST_ENV: str(path)},
            config=config,
        )


def test_unqualified_primary_deployment_stays_blocked(tmp_path: Path) -> None:
    payload = _manifest()
    primary = dict(payload["primary"])
    primary["qualified"] = False
    payload["primary"] = primary
    path = _write(tmp_path, payload)
    resolution = resolve_installed_core_v1_dependencies(
        _profile(),
        {MANIFEST_ENV: str(path)},
    )
    assert (
        resolution.blocker
        == "CORE_V1_PRIMARY_FINANCING_DEPLOYMENT_NOT_QUALIFIED"
    )


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
