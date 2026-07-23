#!/usr/bin/env python3
"""Run repository verification in a fresh isolated virtual environment."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import venv

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    "package-smoke-clean": (("{python}", "scripts/package_smoke.py"),),
    "test-collect-clean": (("{python}", "-m", "pytest", "--collect-only", "-q"),),
    "release-artifacts-clean": (("{python}", "-m", "build"), ("{python}", "scripts/verify_installed_artifact.py", "--json")),
    "verify-clean": (
        ("{python}", "-m", "compileall", "-q", "arb_bot.py", "src", "scripts", "tests"),
        ("{python}", "scripts/package_smoke.py"),
        ("{python}", "scripts/verify_repo.py", "--skip-live"),
        ("{python}", "-m", "pytest", "--collect-only", "-q"),
    ),
}


def command_plan(profile: str, python: str, bin_dir: str) -> tuple[tuple[str, ...], ...]:
    commands = tuple(tuple(part.replace("{python}", python) for part in command) for command in PROFILES[profile])
    return commands + ((str(Path(bin_dir) / "flashloan-bot"), "status", "--json"),)


def clean_environment(bin_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("VIRTUAL_ENV", None)
    env.update({"PYTHONNOUSERSITE": "1", "PAPER_TRADING_ONLY": "true", "LIVE_TRADING_ENABLED": "false", "JITO_ENABLED": "false", "KAMINO_LIQUIDATION_ENABLED": "false", "PATH": f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"})
    return env


def run(profile: str) -> int:
    with tempfile.TemporaryDirectory(prefix="mpr-close-23-") as temporary:
        workspace = Path(temporary)
        source = workspace / "source"
        environment = workspace / "venv"
        shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns(".git", ".venv", "venv", "build", "dist", "*.egg-info", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"))
        venv.EnvBuilder(with_pip=True, system_site_packages=False).create(environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        env = clean_environment(python.parent)
        bootstrap = ((str(python), "-m", "pip", "install", "--upgrade", "pip"), (str(python), "-m", "pip", "install", ".[dev]"))
        for command in bootstrap + command_plan(profile, str(python), str(python.parent)):
            print(f"$ {' '.join(command)}", flush=True)
            subprocess.run(command, cwd=source, env=env, check=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=tuple(PROFILES))
    return run(parser.parse_args(argv).profile)


if __name__ == "__main__":
    raise SystemExit(main())
