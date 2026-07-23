from __future__ import annotations

import json
from pathlib import Path

from src.production_surface import (
    forbidden_import_names,
    forbidden_wheel_members,
    forbidden_wheel_paths,
    forbidden_wheel_prefixes,
    image_forbidden_imports,
    load_manifest,
    required_entrypoints,
    required_wheel_members,
)

ROOT = Path(__file__).resolve().parents[1]


def test_pr194_manifest_is_single_surface_authority() -> None:
    manifest = load_manifest()

    assert manifest["schema_version"] == "pr194.production-surface.v1"
    assert manifest["product_state"] == "not-production-ready"
    assert "src/resources/production_surface_manifest.json" in required_wheel_members()
    assert required_entrypoints()["flashloan-bot"] == "src.cli_pr189:main"


def test_pr194_manifest_covers_legacy_and_live_forbidden_surface() -> None:
    assert forbidden_wheel_paths() >= {
        "src/legacy_arb_bot.py",
        "src/execution/live_control.py",
        "src/execution/shadow.py",
    }
    assert forbidden_wheel_prefixes() == (
        "src/ingest/",
        "src/execution/senders/",
    )
    assert set(forbidden_import_names()) >= {
        "src.legacy_arb_bot",
        "src.execution.live_control",
        "src.execution.shadow",
        "src.ingest",
        "src.execution.senders",
    }


def test_pr194_forbidden_member_detection_is_manifest_driven() -> None:
    names = {
        "src/cli.py",
        "src/legacy_arb_bot.py",
        "src/execution/senders/jito.py",
        "src/resources/production_surface_manifest.json",
    }

    assert forbidden_wheel_members(names) == [
        "src/execution/senders/jito.py",
        "src/legacy_arb_bot.py",
    ]


def test_pr194_docker_build_copies_setup_py_before_install() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert (
        "COPY requirements.txt pyproject.toml setup.py README.md arb_bot.py ./"
        in dockerfile
    )
    assert "pip install --no-deps --no-build-isolation ." in dockerfile


def test_pr194_package_and_image_smoke_use_manifest_authority() -> None:
    package_smoke = (ROOT / "scripts" / "package_smoke.py").read_text(encoding="utf-8")
    image_smoke = (ROOT / "scripts" / "image_smoke.sh").read_text(encoding="utf-8")
    setup_py = (ROOT / "setup.py").read_text(encoding="utf-8")

    assert "from src.production_surface import" in package_smoke
    assert "assert_no_forbidden_wheel_members(names)" in package_smoke
    assert "assert_forbidden_imports_unavailable()" in image_smoke
    assert "production_surface_manifest.json" in setup_py
    assert "FORBIDDEN_PRODUCTION_MODULES" not in setup_py
    assert "FORBIDDEN_WHEEL_PATHS" not in package_smoke


def test_pr194_image_forbidden_imports_remain_runtime_only() -> None:
    assert set(image_forbidden_imports()) == {
        "numpy",
        "pandas",
        "pyarrow",
        "sklearn",
        "pytest",
    }


def test_pr194_manifest_is_valid_json_resource() -> None:
    raw = ROOT.joinpath(
        "src",
        "resources",
        "production_surface_manifest.json",
    ).read_text(encoding="utf-8")

    assert json.loads(raw) == load_manifest()
