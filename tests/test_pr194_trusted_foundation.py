from __future__ import annotations

import json
from pathlib import Path

from scripts.verify_pr194_trusted_foundation import (
    TrustedFoundationEvidence,
    verify_pr194_foundation,
)

ROOT = Path(__file__).resolve().parents[1]


def _capability_payload(*, live_available: bool = False) -> dict[str, object]:
    return {
        "schema_version": "pr023.capabilities.v1",
        "product_state": "not-production-ready",
        "supported_entrypoint": "flashloan-bot",
        "default_command": "run --mode shadow",
        "runtime_modes": {
            "disabled": {"available": True},
            "paper": {"available": True},
            "shadow": {"available": True},
            "live": {"available": live_available},
        },
        "components": [
            {
                "id": "runtime.launcher",
                "kind": "runtime",
                "path": "src/cli.py",
                "capability": "implemented",
                "active_in_supported_entrypoint": True,
                "quarantined": False,
                "allowed_modes": ["disabled", "shadow"],
                "reason": "fixture",
            }
        ],
    }


def _production_surface_manifest() -> dict[str, object]:
    return {
        "schema_version": "pr194.production-surface.v1",
        "required_wheel_members": [
            "src/resources/capabilities.json",
            "src/resources/production_surface_manifest.json",
        ],
        "entrypoints": {
            "flashloan-bot": "src.cli_pr189:main",
            "flashloan-bot-healthcheck": "src.container_runtime:healthcheck_main",
        },
        "forbidden": {
            "package_prefixes": [
                "src/execution/senders/",
                "src/ingest/",
            ]
        },
    }


def _write_fixture_repo(
    root: Path,
    *,
    live_available: bool = False,
    drift_capability_resource: bool = False,
) -> None:
    (root / "config").mkdir(parents=True)
    (root / "src/resources").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)

    capability = _capability_payload(live_available=live_available)
    packaged = _capability_payload(live_available=live_available)
    if drift_capability_resource:
        packaged["default_command"] = "run --mode disabled"
    (root / "config/capabilities.json").write_text(
        json.dumps(capability, sort_keys=True),
        encoding="utf-8",
    )
    (root / "src/resources/capabilities.json").write_text(
        json.dumps(packaged, sort_keys=True),
        encoding="utf-8",
    )
    (root / "src/resources/production_surface_manifest.json").write_text(
        json.dumps(_production_surface_manifest(), sort_keys=True),
        encoding="utf-8",
    )
    (root / "src/production_surface.py").write_text(
        """
def required_wheel_members():
    return ("src/resources/capabilities.json", "src/resources/production_surface_manifest.json")


def required_entrypoints():
    return {"flashloan-bot": "src.cli_pr189:main"}


def forbidden_wheel_members():
    return ("src/execution/senders/", "src/ingest/")


def image_forbidden_imports():
    return ("src.execution.senders", "src.ingest")
""".lstrip(),
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        """
[build-system]
requires = ["setuptools==83.0.0", "wheel==0.47.0"]
build-backend = "setuptools.build_meta"

[project]
name = "studious-pancake-flashloan-bot"
version = "0.0.0"
[project.scripts]
flashloan-bot = "src.cli_pr189:main"
flashloan-bot-healthcheck = "src.container_runtime:healthcheck_main"

[tool.setuptools]
py-modules = ["arb_bot"]
[tool.setuptools.packages.find]
include = ["src*"]
exclude = ["src.ingest*", "src.execution.senders*"]
[tool.setuptools.package-data]
"src.resources" = ["*.json"]
""".lstrip(),
        encoding="utf-8",
    )
    (root / "scripts/package_smoke.py").write_text(
        """
from src.production_surface import (
    forbidden_wheel_members,
    required_entrypoints,
    required_wheel_members,
)


def assert_no_forbidden_wheel_members():
    return tuple(forbidden_wheel_members())


def assert_required_surface():
    return tuple(required_wheel_members()), dict(required_entrypoints())
""".lstrip(),
        encoding="utf-8",
    )
    (root / "scripts/verify_repo.py").write_text(
        "COMMAND = ['scripts/verify_pr194_trusted_foundation.py']\n",
        encoding="utf-8",
    )
    (root / "config/format_targets.txt").write_text(
        "\n".join(
            (
                "scripts/verify_pr194_trusted_foundation.py",
                "tests/test_pr194_trusted_foundation.py",
            )
        )
        + "\n",
        encoding="utf-8",
    )


def test_pr194_trusted_foundation_accepts_current_checkout() -> None:
    evidence = verify_pr194_foundation(ROOT)

    assert isinstance(evidence, TrustedFoundationEvidence)
    assert evidence.accepted is True
    assert evidence.blockers == ()
    assert evidence.live_denied is True
    assert evidence.sender_package_excluded is True
    assert evidence.resource_parity is True
    assert evidence.artifact_hashes["config/capabilities.json"] == (
        evidence.artifact_hashes["src/resources/capabilities.json"]
    )
    assert "flashloan-bot" in evidence.console_scripts


def test_pr194_trusted_foundation_rejects_live_capability(tmp_path: Path) -> None:
    _write_fixture_repo(tmp_path, live_available=True)

    evidence = verify_pr194_foundation(tmp_path)

    assert evidence.accepted is False
    assert "CAPABILITY_LIVE_NOT_HARD_DENIED" in evidence.blockers


def test_pr194_trusted_foundation_rejects_resource_drift(tmp_path: Path) -> None:
    _write_fixture_repo(tmp_path, drift_capability_resource=True)

    evidence = verify_pr194_foundation(tmp_path)

    assert evidence.accepted is False
    assert "CAPABILITY_RESOURCE_DRIFT" in evidence.blockers
    assert evidence.canonical_capability_sha256 is None
