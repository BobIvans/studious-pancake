from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from src import automation_cli_pr189
from src.cli_contract_pr189 import CommandExitCode

ROOT = Path(__file__).resolve().parents[1]


def test_pr213_authority_validator_bootstraps_from_clean_checkout(
    tmp_path: Path,
) -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "validate_authority_map.py"),
            "--root",
            str(ROOT),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["schema_version"] == "pr01.authority-validation.v1"
    assert payload["valid"] is True


def test_pr213_root_wrapper_and_installed_target_route_help_equally() -> None:
    root = subprocess.run(
        [sys.executable, str(ROOT / "arb_bot.py"), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    installed = subprocess.run(
        [sys.executable, "-m", "src.cli_pr189", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert root.returncode == installed.returncode == 0
    assert root.stderr == installed.stderr == ""
    assert "status" in root.stdout
    assert "status" in installed.stdout
    assert "capabilities" in root.stdout
    assert "capabilities" in installed.stdout


def test_pr213_automation_cli_dependency_failure_is_structured(
    monkeypatch,
    capsys,
) -> None:
    def unavailable(*_args, **_kwargs):
        raise ModuleNotFoundError("No module named 'solders'", name="solders")

    monkeypatch.setattr(automation_cli_pr189, "evaluate_paper_vertical", unavailable)

    exit_code = automation_cli_pr189.main(["paper-vertical", "inspect"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == int(CommandExitCode.DEPENDENCY_UNAVAILABLE)
    assert payload["schema_version"] == "pr189.command-result.v1"
    assert payload["verdict"] == "unavailable"
    assert payload["reason_codes"] == ["PR189_DEPENDENCY_UNAVAILABLE"]
    assert payload["details"] == {
        "dependency": "solders",
        "error_type": "ModuleNotFoundError",
    }
