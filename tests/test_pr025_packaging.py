from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import tomllib

import pytest

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[A-Za-z0-9_,.-]+\])?==([^\s;]+)(.*)$")


def _canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _pins(path: Path) -> set[str]:
    return set(_pin_map(path))


def _pin_map(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        match = PIN_RE.match(line)
        if match is None:
            raise AssertionError(f"non-exact requirement in {path.name}: {line}")
        name, version, suffix = match.groups()
        pins[_canonical_name(name)] = f"{name}=={version}{suffix}"
    return pins


def _project_direct_pins() -> dict[str, str]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    values: list[str] = list(project["dependencies"])
    for entries in project["optional-dependencies"].values():
        values.extend(entries)

    direct: dict[str, str] = {}
    for value in values:
        match = PIN_RE.match(value)
        assert match is not None, f"non-exact direct project dependency: {value}"
        name, version, suffix = match.groups()
        direct[_canonical_name(name)] = f"{name}=={version}{suffix}"
    return direct


def test_pyproject_is_the_single_typed_package_contract():
    with (ROOT / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    project = data["project"]
    assert project["requires-python"] == ">=3.13,<3.14"
    assert project["scripts"] == {
        "flashloan-bot": "src.cli:main",
        "flashloan-bot-healthcheck": "src.container_runtime:healthcheck_main",
        "flashloan-contracts": "src.external_contracts.cli:main",
        "flashloan-release-evidence": "src.release_gate.materialized_evidence:main",
    }
    assert set(project["optional-dependencies"]) == {"analytics", "service", "dev"}
    assert not (ROOT / "requirements.in").exists()
    assert not (ROOT / "requirements-dev.in").exists()


def test_runtime_lock_excludes_dev_analytics_and_service_toolchains():
    runtime = _pins(ROOT / "requirements.txt")
    forbidden = {
        "bandit",
        "black",
        "duckdb",
        "fastapi",
        "matplotlib",
        "mypy",
        "numpy",
        "pandas",
        "pip-audit",
        "pyarrow",
        "pytest",
        "scikit-learn",
        "scipy",
        "seaborn",
        "uvicorn",
    }
    assert runtime.isdisjoint(forbidden)


def test_optional_lock_profiles_are_explicit_and_hashed():
    analytics = _pins(ROOT / "requirements-analytics.txt")
    development = _pins(ROOT / "requirements-dev.txt")
    assert {"duckdb", "numpy", "pandas", "pyarrow", "scikit-learn"} <= analytics
    assert {
        "bandit",
        "black",
        "fastapi",
        "mypy",
        "pip-audit",
        "pytest",
        "types-pyyaml",
        "uv",
    } <= development

    manifest = json.loads(
        (ROOT / "config/requirements-lock.json").read_text(encoding="utf-8")
    )
    assert manifest["python"] == "3.13"
    assert manifest["resolver"] == {"name": "uv", "version": "0.10.0"}
    for filename, details in manifest["locks"].items():
        digest = hashlib.sha256((ROOT / filename).read_bytes()).hexdigest()
        assert digest == details["sha256"]


def test_development_lock_is_exact_and_honors_direct_pins():
    development = _pin_map(ROOT / "requirements-dev.txt")
    direct = _project_direct_pins()
    assert development["uv"] == direct["uv"]
    assert development["types-pyyaml"] == direct["types-pyyaml"]


def test_repository_and_packaged_capability_registries_match():
    repository = json.loads(
        (ROOT / "config/capabilities.json").read_text(encoding="utf-8")
    )
    packaged = json.loads(
        (ROOT / "src/resources/capabilities.json").read_text(encoding="utf-8")
    )
    assert repository == packaged
    assert repository["supported_entrypoint"] == "flashloan-bot"
    assert repository["components"][0]["path"] == "src/cli.py"


def test_dockerfile_is_multistage_non_root_and_uses_health_probe():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.count("FROM ${PYTHON_IMAGE}") == 2
    assert "python:3.13.13-slim-bookworm" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert 'CMD ["flashloan-bot-healthcheck", "--url", ' in dockerfile
    assert '"http://127.0.0.1:8080/health"]' in dockerfile
    assert "FLASHLOAN_HEALTH_URL=http://127.0.0.1:8080/health" in dockerfile
    assert 'ENTRYPOINT ["flashloan-bot"]' in dockerfile
    assert 'CMD ["container"]' in dockerfile
    assert "localhost:3000/health" not in dockerfile
    assert "curl" not in dockerfile
    assert "requirements-dev.txt" not in dockerfile


def test_legacy_root_entrypoint_is_only_a_compatibility_wrapper():
    tree = ast.parse((ROOT / "arb_bot.py").read_text(encoding="utf-8"))
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    cli_imports = [node for node in imports if node.module == "src.cli"]
    assert len(cli_imports) == 1
    assert len((ROOT / "arb_bot.py").read_text(encoding="utf-8").splitlines()) < 30
