from pathlib import Path
import json
import subprocess
import sys

from src.qualification_pr176 import (
    MANDATORY_PROFILES,
    build_default_qualification_plan,
    inspect_dependency_closure,
)


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_default_plan_has_mandatory_profiles_and_no_network(tmp_path: Path):
    _write(tmp_path / "requirements.txt", "solders==0.28.0\naiolimiter==1.1.0\n")
    _write(tmp_path / "requirements-dev.txt", "pytest==9.0.2\n")
    _write(tmp_path / "pyproject.toml", 'dependencies = ["solders==0.28.0"]\n')

    plan = build_default_qualification_plan(tmp_path)

    assert set(MANDATORY_PROFILES).issubset({profile.name for profile in plan.profiles})
    assert plan.dependency_closure.complete is True
    assert all(not profile.network_after_wheelhouse for profile in plan.profiles)
    assert all(profile.isolated_collection for profile in plan.profiles)


def test_dependency_closure_detects_missing_collection_packages(tmp_path: Path):
    _write(tmp_path / "requirements.txt", "solders==0.28.0\n")
    closure = inspect_dependency_closure(
        tmp_path,
        lock_paths=(tmp_path / "requirements.txt",),
        required_packages=("solders", "aiolimiter", "pytest"),
    )

    assert closure.complete is False
    assert closure.missing_packages == ("aiolimiter", "pytest")


def test_manifest_hash_changes_when_lock_changes(tmp_path: Path):
    _write(tmp_path / "requirements.txt", "solders==0.28.0\naiolimiter==1.1.0\n")
    _write(tmp_path / "requirements-dev.txt", "pytest==9.0.2\n")
    _write(tmp_path / "pyproject.toml", 'dependencies = ["solders==0.28.0"]\n')
    first = build_default_qualification_plan(tmp_path).to_manifest(
        source_digest="source",
        execution_mode="dry-run",
    )

    _write(
        tmp_path / "requirements.txt",
        "solders==0.28.0\naiolimiter==1.1.0\nrequests==2.33.0\n",
    )
    second = build_default_qualification_plan(tmp_path).to_manifest(
        source_digest="source",
        execution_mode="dry-run",
    )

    assert first["manifest_hash"] != second["manifest_hash"]
    assert first["release_claim_allowed"] is True


def test_script_dry_run_outputs_machine_readable_manifest():
    completed = subprocess.run(
        [sys.executable, "scripts/qualify_release.py"],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["schema_version"] == "pr176.hermetic-qualification.v1"
    assert payload["execution_mode"] == "dry-run"
    assert "core" in payload["mandatory_profiles"]
    assert payload["dependency_closure"]["complete"] is True
