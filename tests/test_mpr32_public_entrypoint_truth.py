from __future__ import annotations

import json
from pathlib import Path

from scripts.verify_mpr32_public_entrypoint_truth import (
    Mpr32PublicEntrypointTruthEvidence,
    verify_mpr32_public_entrypoint_truth,
)

ROOT = Path(__file__).resolve().parents[1]
BASE_ENTRYPOINTS = {
    "flashloan-bot": "src.cli_pr189:main",
    "flashloan-bot-healthcheck": "src.container_runtime:healthcheck_main",
    "flashloan-checks": "src.automation_cli_pr189:main",
    "flashloan-contracts": "src.external_contracts.cli_pr189:main",
    "flashloan-release-evidence": "src.release_gate.materialized_evidence:main",
}


def _write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _production_surface_manifest(entrypoints: dict[str, str]) -> dict[str, object]:
    return {
        "schema_version": "pr194.production-surface.v1",
        "entrypoints": dict(entrypoints),
        "runtime": {
            "supported_entrypoint": "flashloan-bot",
            "sender_free": True,
            "live_trading_enabled": False,
        },
        "runtime_cutover": {
            "canonical_composition": {
                "console_entrypoint": "flashloan-bot",
            }
        },
    }


def _authority_map(*, console_script: str = "flashloan-bot", target: str = "src.cli_pr189:main") -> dict[str, object]:
    return {
        "schema_version": "pr01.authority-map.v1",
        "product_state": "not-production-ready",
        "supported_entrypoint": {
            "console_script": console_script,
            "owner_path": "src/cli_pr189.py",
            "target": target,
            "delegates_to": ["src/automation_cli_pr189.py", "src/cli.py"],
        },
    }


def _write_fixture_repo(
    root: Path,
    *,
    pyproject_entrypoints: dict[str, str] | None = None,
    manifest_entrypoints: dict[str, str] | None = None,
    authority_console_script: str = "flashloan-bot",
    authority_target: str = "src.cli_pr189:main",
    verify_repo_runs_gate: bool = True,
) -> None:
    pyproject_entrypoints = dict(pyproject_entrypoints or BASE_ENTRYPOINTS)
    manifest_entrypoints = dict(manifest_entrypoints or pyproject_entrypoints)

    project_scripts = "\n".join(
        f'{name} = "{target}"' for name, target in pyproject_entrypoints.items()
    )
    _write(
        root / "pyproject.toml",
        (
            "[build-system]\n"
            'requires = ["setuptools==83.0.0", "wheel==0.47.0"]\n'
            'build-backend = "setuptools.build_meta"\n\n'
            "[project]\n"
            'name = "studious-pancake-flashloan-bot"\n'
            'version = "0.0.0"\n'
            "[project.scripts]\n"
            f"{project_scripts}\n"
        ),
    )
    _write(
        root / "src/resources/production_surface_manifest.json",
        json.dumps(_production_surface_manifest(manifest_entrypoints), sort_keys=True),
    )
    authority_payload = json.dumps(
        _authority_map(
            console_script=authority_console_script,
            target=authority_target,
        ),
        sort_keys=True,
    )
    _write(root / "config/runtime_authority_map.json", authority_payload)
    _write(root / "src/resources/runtime_authority_map.json", authority_payload)
    verify_repo_text = (
        "python scripts/verify_mpr32_public_entrypoint_truth.py --json\n"
        if verify_repo_runs_gate
        else "python scripts/verify_repo.py\n"
    )
    _write(root / "scripts/verify_repo.py", verify_repo_text)


def test_mpr32_public_entrypoint_truth_accepts_current_checkout() -> None:
    evidence = verify_mpr32_public_entrypoint_truth(ROOT)

    assert isinstance(evidence, Mpr32PublicEntrypointTruthEvidence)
    assert evidence.accepted is True
    assert evidence.blockers == ()
    assert evidence.authority_resource_parity is True
    assert evidence.authority_supported_entrypoint == "flashloan-bot"
    assert evidence.authority_supported_target == "src.cli_pr189:main"
    assert evidence.console_scripts == tuple(sorted(BASE_ENTRYPOINTS))
    assert evidence.production_surface_entrypoints == tuple(sorted(BASE_ENTRYPOINTS))


def test_mpr32_public_entrypoint_truth_rejects_public_surface_set_drift(tmp_path: Path) -> None:
    manifest_entrypoints = dict(BASE_ENTRYPOINTS)
    manifest_entrypoints.pop("flashloan-release-evidence")
    _write_fixture_repo(tmp_path, manifest_entrypoints=manifest_entrypoints)

    evidence = verify_mpr32_public_entrypoint_truth(tmp_path)

    assert evidence.accepted is False
    assert "PUBLIC_ENTRYPOINT_SET_MISMATCH" in evidence.blockers
    assert "PUBLIC_ENTRYPOINT_TARGET_MISMATCH:flashloan-release-evidence" in evidence.blockers


def test_mpr32_public_entrypoint_truth_rejects_authority_supported_entrypoint_drift(tmp_path: Path) -> None:
    _write_fixture_repo(tmp_path, authority_console_script="flashloan-checks")

    evidence = verify_mpr32_public_entrypoint_truth(tmp_path)

    assert evidence.accepted is False
    assert "AUTHORITY_SUPPORTED_ENTRYPOINT_MISMATCH" in evidence.blockers


def test_mpr32_public_entrypoint_truth_rejects_missing_verify_repo_wiring(tmp_path: Path) -> None:
    _write_fixture_repo(tmp_path, verify_repo_runs_gate=False)

    evidence = verify_mpr32_public_entrypoint_truth(tmp_path)

    assert evidence.accepted is False
    assert "VERIFY_REPO_DOES_NOT_RUN_MPR32_PUBLIC_ENTRYPOINT_TRUTH" in evidence.blockers
