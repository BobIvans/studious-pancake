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


def _installed() -> dict[str, str]:
    return {"solders": "0.28.0", "aiolimiter": "1.1.0", "pytest": "9.0.2"}


def test_default_plan_has_mandatory_profiles_and_no_release_claim(tmp_path: Path):
    _write(tmp_path / "requirements.txt", "solders==0.28.0\naiolimiter==1.1.0\n")
    _write(tmp_path / "requirements-dev.txt", "pytest==9.0.2\n")
    _write(tmp_path / "pyproject.toml", 'dependencies = ["solders==0.28.0"]\n')

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
    _write(tmp_path / "pyproject.toml", 'dependencies = ["solders==0.28.0"]\n')
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
