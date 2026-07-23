#!/usr/bin/env python3
"""PR-194 trusted build/package/CI foundation verifier.

The verifier is intentionally offline and sender-free. It checks that the
repository source, packaged resources, console entrypoints and production
surface contract still describe one fail-closed runtime artifact.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import fnmatch
import hashlib
import json
from pathlib import Path
import sys
import tomllib
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
SCHEMA_VERSION: Final = "pr194.trusted-foundation.v1"
CAPABILITY_RESOURCE: Final = "config/capabilities.json"
PACKAGED_CAPABILITY_RESOURCE: Final = "src/resources/capabilities.json"
PRODUCTION_SURFACE_MODULE: Final = "src/production_surface.py"
PRODUCTION_SURFACE_MANIFEST: Final = "src/resources/production_surface_manifest.json"
REQUIRED_CONSOLE_SCRIPTS: Final[dict[str, str]] = {
    "flashloan-bot": "src.cli_pr189:main",
    "flashloan-bot-healthcheck": "src.container_runtime:healthcheck_main",
}
REQUIRED_PACKAGE_EXCLUDES: Final[set[str]] = {
    "src.ingest*",
    "src.execution.senders*",
}
EVIDENCE_PATHS: Final[tuple[str, ...]] = (
    "pyproject.toml",
    "scripts/package_smoke.py",
    "scripts/verify_repo.py",
    CAPABILITY_RESOURCE,
    PACKAGED_CAPABILITY_RESOURCE,
    PRODUCTION_SURFACE_MODULE,
    PRODUCTION_SURFACE_MANIFEST,
)


class TrustedFoundationError(RuntimeError):
    """Trusted artifact foundation verification failed."""


@dataclass(frozen=True, slots=True)
class TrustedFoundationEvidence:
    schema_version: str
    accepted: bool
    blockers: tuple[str, ...]
    artifact_hashes: dict[str, str]
    canonical_capability_sha256: str | None
    package_name: str
    package_version: str
    console_scripts: tuple[str, ...]
    live_denied: bool
    sender_package_excluded: bool
    resource_parity: bool

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["blockers"] = list(self.blockers)
        value["console_scripts"] = list(self.console_scripts)
        return value


def _repo_file(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    root_resolved = root.resolve()
    if candidate == root_resolved or root_resolved not in candidate.parents:
        raise TrustedFoundationError(f"path escapes repository root: {relative}")
    return candidate


def _read_bytes(root: Path, relative: str) -> bytes:
    try:
        return _repo_file(root, relative).read_bytes()
    except FileNotFoundError as exc:
        raise TrustedFoundationError(f"required file is missing: {relative}") from exc


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_json(root: Path, relative: str) -> dict[str, Any]:
    try:
        value = json.loads(_read_bytes(root, relative).decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise TrustedFoundationError(f"invalid JSON in {relative}: {exc}") from exc
    if not isinstance(value, dict):
        raise TrustedFoundationError(f"{relative} must contain a JSON object")
    return value


def _load_pyproject(root: Path) -> dict[str, Any]:
    try:
        value = tomllib.loads(_read_bytes(root, "pyproject.toml").decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise TrustedFoundationError(f"invalid pyproject.toml: {exc}") from exc
    if not isinstance(value, dict):
        raise TrustedFoundationError("pyproject.toml must decode to an object")
    return value


def _as_dict(value: object, blockers: list[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        blockers.append(code)
        return {}
    return value


def _as_list(value: object, blockers: list[str], code: str) -> list[Any]:
    if not isinstance(value, list):
        blockers.append(code)
        return []
    return value


def _require(condition: bool, blockers: list[str], code: str) -> None:
    if not condition:
        blockers.append(code)


def _resource_pattern_covers(resources: set[str], filename: str) -> bool:
    return filename in resources or any(
        fnmatch.fnmatchcase(filename, pattern) for pattern in resources
    )


def _project_scripts(pyproject: dict[str, Any], blockers: list[str]) -> dict[str, str]:
    project = _as_dict(
        pyproject.get("project"),
        blockers,
        "PYPROJECT_PROJECT_SECTION_MISSING",
    )
    scripts = _as_dict(
        project.get("scripts"),
        blockers,
        "PYPROJECT_SCRIPTS_MISSING",
    )
    return {str(key): str(value) for key, value in scripts.items()}


def _setuptools_config(
    pyproject: dict[str, Any],
    blockers: list[str],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    tool = _as_dict(pyproject.get("tool"), blockers, "PYPROJECT_TOOL_SECTION_MISSING")
    setuptools = _as_dict(
        tool.get("setuptools"),
        blockers,
        "PYPROJECT_SETUPTOOLS_SECTION_MISSING",
    )
    packages = setuptools.get("packages")
    find = _as_dict(
        packages.get("find") if isinstance(packages, dict) else None,
        blockers,
        "PYPROJECT_PACKAGE_FIND_MISSING",
    )
    package_data = _as_dict(
        setuptools.get("package-data"),
        blockers,
        "PYPROJECT_PACKAGE_DATA_MISSING",
    )
    return setuptools, find, package_data


def _production_surface_contract_is_current(root: Path, blockers: list[str]) -> None:
    manifest = _load_json(root, PRODUCTION_SURFACE_MANIFEST)
    module_text = _read_bytes(root, PRODUCTION_SURFACE_MODULE).decode("utf-8")
    package_smoke = _read_bytes(root, "scripts/package_smoke.py").decode("utf-8")

    _require(
        manifest.get("schema_version") == "pr194.production-surface.v1",
        blockers,
        "PRODUCTION_SURFACE_SCHEMA_MISMATCH",
    )
    required_members = _as_list(
        manifest.get("required_wheel_members"),
        blockers,
        "PRODUCTION_SURFACE_REQUIRED_MEMBERS_MISSING",
    )
    required_member_set = {str(item) for item in required_members}
    _require(
        "src/resources/capabilities.json" in required_member_set,
        blockers,
        "PRODUCTION_SURFACE_CAPABILITY_MEMBER_MISSING",
    )
    _require(
        "src/resources/production_surface_manifest.json" in required_member_set,
        blockers,
        "PRODUCTION_SURFACE_MANIFEST_MEMBER_MISSING",
    )

    entrypoints = _as_dict(
        manifest.get("entrypoints"),
        blockers,
        "PRODUCTION_SURFACE_ENTRYPOINTS_MISSING",
    )
    for script_name, target in REQUIRED_CONSOLE_SCRIPTS.items():
        _require(
            entrypoints.get(script_name) == target,
            blockers,
            f"PRODUCTION_SURFACE_ENTRYPOINT_MISMATCH:{script_name}",
        )

    forbidden = _as_dict(
        manifest.get("forbidden"),
        blockers,
        "PRODUCTION_SURFACE_FORBIDDEN_SECTION_MISSING",
    )
    forbidden_prefixes = {
        str(item)
        for item in _as_list(
            forbidden.get("package_prefixes"),
            blockers,
            "PRODUCTION_SURFACE_FORBIDDEN_PREFIXES_MISSING",
        )
    }
    _require(
        "src/execution/senders/" in forbidden_prefixes,
        blockers,
        "PRODUCTION_SURFACE_SENDER_PREFIX_NOT_FORBIDDEN",
    )
    _require(
        "src/ingest/" in forbidden_prefixes,
        blockers,
        "PRODUCTION_SURFACE_INGEST_PREFIX_NOT_FORBIDDEN",
    )

    module_apis = (
        "required_wheel_members",
        "required_entrypoints",
        "forbidden_wheel_members",
        "image_forbidden_imports",
    )
    package_smoke_apis = (
        "required_wheel_members",
        "required_entrypoints",
        "forbidden_wheel_members",
        "assert_no_forbidden_wheel_members",
    )
    for expected in module_apis:
        _require(
            expected in module_text,
            blockers,
            f"PRODUCTION_SURFACE_API_MISSING:{expected}",
        )
    for expected in package_smoke_apis:
        _require(
            expected in package_smoke,
            blockers,
            f"PACKAGE_SMOKE_DOES_NOT_USE_PRODUCTION_SURFACE:{expected}",
        )


def verify_pr194_foundation(root: str | Path = ROOT) -> TrustedFoundationEvidence:
    """Return deterministic PR-194 trusted foundation evidence for *root*."""

    repo_root = Path(root).resolve()
    blockers: list[str] = []
    hashes: dict[str, str] = {}

    for relative in EVIDENCE_PATHS:
        try:
            hashes[relative] = _sha256(_read_bytes(repo_root, relative))
        except TrustedFoundationError:
            blockers.append(f"MISSING:{relative}")

    capability_raw = _read_bytes(repo_root, CAPABILITY_RESOURCE)
    packaged_capability_raw = _read_bytes(repo_root, PACKAGED_CAPABILITY_RESOURCE)
    resource_parity = capability_raw == packaged_capability_raw
    _require(resource_parity, blockers, "CAPABILITY_RESOURCE_DRIFT")

    capability = _load_json(repo_root, CAPABILITY_RESOURCE)
    runtime_modes = _as_dict(
        capability.get("runtime_modes"),
        blockers,
        "CAPABILITY_RUNTIME_MODES_MISSING",
    )
    live_mode = _as_dict(
        runtime_modes.get("live"),
        blockers,
        "CAPABILITY_LIVE_MODE_MISSING",
    )
    components = _as_list(
        capability.get("components"),
        blockers,
        "CAPABILITY_COMPONENTS_MISSING",
    )
    live_denied = live_mode.get("available") is False
    _require(live_denied, blockers, "CAPABILITY_LIVE_NOT_HARD_DENIED")
    _require(
        capability.get("product_state") == "not-production-ready",
        blockers,
        "CAPABILITY_PRODUCT_STATE_WEAKENED",
    )
    _require(
        capability.get("supported_entrypoint") == "flashloan-bot",
        blockers,
        "CAPABILITY_ENTRYPOINT_MISMATCH",
    )

    for component in components:
        if not isinstance(component, dict):
            blockers.append("CAPABILITY_COMPONENT_NOT_OBJECT")
            continue
        allowed_modes = component.get("allowed_modes")
        if isinstance(allowed_modes, list) and "live" in allowed_modes:
            blockers.append(f"CAPABILITY_COMPONENT_ALLOWS_LIVE:{component.get('id')}")

    pyproject = _load_pyproject(repo_root)
    build_system = _as_dict(
        pyproject.get("build-system"),
        blockers,
        "PYPROJECT_BUILD_SYSTEM_MISSING",
    )
    build_requires = {
        str(item)
        for item in _as_list(
            build_system.get("requires"),
            blockers,
            "PYPROJECT_BUILD_REQUIRES_MISSING",
        )
    }
    _require(
        bool(build_requires)
        and all("==" in requirement for requirement in build_requires),
        blockers,
        "PYPROJECT_BUILD_REQUIRES_NOT_PINNED",
    )

    project = _as_dict(
        pyproject.get("project"),
        blockers,
        "PYPROJECT_PROJECT_SECTION_MISSING",
    )
    scripts = _project_scripts(pyproject, blockers)
    for script_name, target in REQUIRED_CONSOLE_SCRIPTS.items():
        _require(
            scripts.get(script_name) == target,
            blockers,
            f"CONSOLE_SCRIPT_MISMATCH:{script_name}",
        )

    setuptools, find, package_data = _setuptools_config(pyproject, blockers)
    py_modules = {
        str(item)
        for item in _as_list(
            setuptools.get("py-modules"),
            blockers,
            "PYPROJECT_PY_MODULES_MISSING",
        )
    }
    _require("arb_bot" in py_modules, blockers, "PYPROJECT_ARB_BOT_MODULE_MISSING")

    included_packages = {
        str(item)
        for item in _as_list(
            find.get("include"),
            blockers,
            "PYPROJECT_PACKAGE_INCLUDE_MISSING",
        )
    }
    excluded_packages = {
        str(item)
        for item in _as_list(
            find.get("exclude"),
            blockers,
            "PYPROJECT_PACKAGE_EXCLUDE_MISSING",
        )
    }
    _require("src*" in included_packages, blockers, "PYPROJECT_SRC_PACKAGE_MISSING")
    sender_package_excluded = REQUIRED_PACKAGE_EXCLUDES.issubset(excluded_packages)
    _require(
        sender_package_excluded,
        blockers,
        "PYPROJECT_SENDER_OR_INGEST_PACKAGE_NOT_EXCLUDED",
    )

    resources = {
        str(item)
        for item in _as_list(
            package_data.get("src.resources"),
            blockers,
            "PYPROJECT_RESOURCE_PACKAGE_DATA_MISSING",
        )
    }
    _require(
        _resource_pattern_covers(resources, "capabilities.json"),
        blockers,
        "PYPROJECT_PACKAGED_CAPABILITY_RESOURCE_MISSING",
    )
    _require(
        _resource_pattern_covers(resources, "production_surface_manifest.json"),
        blockers,
        "PYPROJECT_PACKAGED_PRODUCTION_SURFACE_MANIFEST_MISSING",
    )

    verify_repo = _read_bytes(repo_root, "scripts/verify_repo.py").decode("utf-8")
    _require(
        "scripts/verify_pr194_trusted_foundation.py" in verify_repo,
        blockers,
        "VERIFY_REPO_DOES_NOT_RUN_PR194",
    )
    _production_surface_contract_is_current(repo_root, blockers)

    unique_blockers = tuple(dict.fromkeys(blockers))
    return TrustedFoundationEvidence(
        schema_version=SCHEMA_VERSION,
        accepted=not unique_blockers,
        blockers=unique_blockers,
        artifact_hashes=hashes,
        canonical_capability_sha256=(
            hashes.get(CAPABILITY_RESOURCE) if resource_parity else None
        ),
        package_name=str(project.get("name", "")),
        package_version=str(project.get("version", "")),
        console_scripts=tuple(sorted(scripts)),
        live_denied=live_denied,
        sender_package_excluded=sender_package_excluded,
        resource_parity=resource_parity,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT), help="Repository root to verify.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable PR-194 evidence JSON.",
    )
    args = parser.parse_args(argv)

    evidence = verify_pr194_foundation(args.root)
    if args.json:
        print(json.dumps(evidence.to_dict(), sort_keys=True, indent=2))
    elif evidence.accepted:
        print("PR-194 trusted foundation verification passed.")
    else:
        print("PR-194 trusted foundation verification failed:", file=sys.stderr)
        for blocker in evidence.blockers:
            print(f"- {blocker}", file=sys.stderr)
    return 0 if evidence.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
