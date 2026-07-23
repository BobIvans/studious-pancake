from __future__ import annotations

from pathlib import Path

from scripts.hermetic_runtime import PROFILES, clean_environment, command_plan


def test_all_required_hermetic_profiles_exist() -> None:
    assert set(PROFILES) == {
        "verify-clean",
        "package-smoke-clean",
        "test-collect-clean",
        "release-artifacts-clean",
    }


def test_verify_plan_uses_canonical_installed_entrypoint() -> None:
    plan = command_plan("verify-clean", "/clean/bin/python", "/clean/bin")
    assert plan[-1] == ("/clean/bin/flashloan-bot", "status", "--json")
    assert ("/clean/bin/python", "scripts/package_smoke.py") in plan
    assert ("/clean/bin/python", "-m", "pytest", "--collect-only", "-q") in plan


def test_release_plan_builds_artifacts_inside_clean_environment() -> None:
    plan = command_plan("release-artifacts-clean", "/clean/bin/python", "/clean/bin")
    assert plan[0] == ("/clean/bin/python", "-m", "build")
    assert plan[1] == (
        "/clean/bin/python",
        "scripts/verify_installed_artifact.py",
        "--json",
    )


def test_clean_environment_removes_source_and_parent_venv(monkeypatch) -> None:
    monkeypatch.setenv("PYTHONPATH", "/source-checkout")
    monkeypatch.setenv("VIRTUAL_ENV", "/opt/pyvenv")
    environment = clean_environment(Path("/clean/bin"))
    assert "PYTHONPATH" not in environment
    assert "VIRTUAL_ENV" not in environment
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert environment["LIVE_TRADING_ENABLED"] == "false"
    assert environment["JITO_ENABLED"] == "false"


def test_no_profile_invokes_source_wrapper_as_product_root() -> None:
    for profile in PROFILES:
        plan = command_plan(profile, "/clean/bin/python", "/clean/bin")
        assert all("arb_bot.py" not in command[:2] for command in plan)
