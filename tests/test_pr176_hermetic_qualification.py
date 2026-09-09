from pathlib import Path
import json
import subprocess
import sys

import pytest

from src.qualification_pr176 import (
    MANDATORY_PROFILES,
    build_default_qualification_plan,
    inspect_dependency_closure,
)


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _installed() -> dict[str, str]:
    return {"solders": "0.28.0", "aiolimiter": "1.1.0", "pytest": "9.0.2"}


def _pyproject(*requirements: str) -> str:
    values = ", ".join(json.dumps(value) for value in requirements)
    return f"[project]\ndependencies = [{values}]\n"


def test_default_plan_has_mandatory_profiles_and_no_release_claim(tmp_path: Path):
    _write(tmp_path / "requirements.txt", "solders==0.28.0\naiolimiter==1.1.0\n")
    _write(tmp_path / "requirements-dev.txt", "pytest==9.0.2\n")
    _write(tmp_path / "pyproject.toml", _pyproject("solders==0.28.0"))

    plan = build_default_qualification_plan(
        tmp_path,
        installed_distributions=_installed(),
        importable_packages=_installed(),
    )

    assert set(MANDATORY_PROFILES).issubset({profile.name for profile in plan.profiles})
    assert plan.dependency_closure.complete is True
    assert plan.release_claim_allowed is False
    assert all(not profile.network_after_wheelhouse for profile in plan.profiles)
    assert all(profile.isolated_collection for profile in plan.profiles)
    assert all(profile.command[0] == sys.executable for profile in plan.profiles)


def test_dependency_closure_uses_installed_environment_not_declaration(tmp_path: Path):
    _write(
        tmp_path / "requirements.txt",
        "solders==0.28.0\naiolimiter==1.1.0\npytest==9.0.2\n",
    )
    closure = inspect_dependency_closure(
        tmp_path,
        lock_paths=(tmp_path / "requirements.txt",),
        required_packages=("solders", "aiolimiter", "pytest"),
        installed_distributions={"pytest": "9.0.2", "aiolimiter": "1.1.0"},
        importable_packages=("pytest", "aiolimiter"),
    )

    assert closure.complete is False
    assert closure.missing_packages == ("solders",)
    assert closure.non_importable_packages == ("solders",)


def test_dependency_closure_detects_declared_but_not_importable(tmp_path: Path):
    _write(tmp_path / "requirements.txt", "solders==0.28.0\n")
    closure = inspect_dependency_closure(
        tmp_path,
        lock_paths=(tmp_path / "requirements.txt",),
        required_packages=("solders",),
        installed_distributions={"solders": "0.28.0"},
        importable_packages=(),
    )

    assert closure.complete is False
    assert closure.missing_packages == ()
    assert closure.non_importable_packages == ("solders",)


def test_manifest_hash_changes_when_lock_changes_but_plan_never_claims_release(
    tmp_path: Path,
):
    _write(tmp_path / "requirements.txt", "solders==0.28.0\naiolimiter==1.1.0\n")
    _write(tmp_path / "requirements-dev.txt", "pytest==9.0.2\n")
    _write(tmp_path / "pyproject.toml", _pyproject("solders==0.28.0"))
    first = build_default_qualification_plan(
        tmp_path,
        installed_distributions=_installed(),
        importable_packages=_installed(),
    ).to_manifest(source_digest="source", execution_mode="planned")

    _write(
        tmp_path / "requirements.txt",
        "solders==0.28.0\naiolimiter==1.1.0\nrequests==2.33.0\n",
    )
    second = build_default_qualification_plan(
        tmp_path,
        installed_distributions=_installed(),
        importable_packages=_installed(),
    ).to_manifest(source_digest="source", execution_mode="planned")

    assert first["manifest_hash"] != second["manifest_hash"]
    assert first["release_claim_allowed"] is False
    assert second["release_claim_allowed"] is False
    assert first["qualification_state"] == "planned_not_executed"


def test_pyproject_dependency_parser_ignores_metadata_scripts_and_tool_config(tmp_path: Path):
    _write(
        tmp_path / "pyproject.toml",
        """[build-system]
requires = ["setuptools==83.0.0", "wheel==0.47.0"]
[project]
name = "example"
description = "not a dependency"
dependencies = ["solders==0.28.0", "aiolimiter>=1.1"]
classifiers = ["Programming Language :: Python :: 3"]
[project.optional-dependencies]
dev = ["pytest==9.0.2"]
[project.scripts]
flashloan-bot = "src.cli_pr189:main"
[tool.black]
line-length = 88
""",
    )
    closure = inspect_dependency_closure(
        tmp_path,
        lock_paths=(tmp_path / "pyproject.toml",),
        required_packages=("solders", "aiolimiter", "pytest"),
        installed_distributions=_installed(),
        importable_packages=_installed(),
    )

    assert closure.complete is True
    assert set(closure.declared_packages) == {
        "aiolimiter",
        "pytest",
        "setuptools",
        "solders",
        "wheel",
    }
    assert "line-length-88" not in closure.declared_packages
    assert "flashloan-bot-src-cli-pr189-main" not in closure.declared_packages


def test_malformed_pyproject_dependency_field_fails_closed(tmp_path: Path):
    _write(tmp_path / "pyproject.toml", '[project]\ndependencies = "solders==0.28.0"\n')
    with pytest.raises(ValueError):
        inspect_dependency_closure(
            tmp_path,
            lock_paths=(tmp_path / "pyproject.toml",),
            required_packages=("solders",),
            installed_distributions={"solders": "0.28.0"},
            importable_packages=("solders",),
        )


def test_editable_requirement_is_rejected(tmp_path: Path):
    _write(tmp_path / "requirements.txt", "-e .\n")
    with pytest.raises(ValueError):
        inspect_dependency_closure(
            tmp_path,
            lock_paths=(tmp_path / "requirements.txt",),
            required_packages=("pytest",),
            installed_distributions={"pytest": "9.0.2"},
            importable_packages=("pytest",),
        )


def test_script_dry_run_outputs_non_release_plan():
    completed = subprocess.run(
        [sys.executable, "scripts/qualify_release.py"],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["schema_version"] == "pr186.qualification-plan.v1"
    assert payload["execution_mode"] == "planned"
    assert payload["qualification_state"] == "planned_not_executed"
    assert payload["release_claim_allowed"] is False
    assert payload["qualified"] is False
    assert "core" in payload["mandatory_profiles"]
