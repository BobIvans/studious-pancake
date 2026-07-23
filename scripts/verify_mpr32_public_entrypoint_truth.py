#!/usr/bin/env python3
"""Verify the MPR-32 public entrypoint truth surface.

Offline and sender-free. The verifier checks that the installed public command
surface described by ``pyproject.toml``, ``production_surface_manifest.json`` and
``runtime_authority_map.json`` stays exact and fail-closed.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sys
import tomllib
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
SCHEMA_VERSION: Final = "mpr32.public-entrypoint-truth.v1"
PYPROJECT_PATH: Final = "pyproject.toml"
PRODUCTION_SURFACE_PATH: Final = "src/resources/production_surface_manifest.json"
AUTHORITY_MAP_PATH: Final = "config/runtime_authority_map.json"
PACKAGED_AUTHORITY_MAP_PATH: Final = "src/resources/runtime_authority_map.json"
SUPPORTED_ENTRYPOINT: Final = "flashloan-bot"
SUPPORTED_OWNER_PATH: Final = "src/cli_pr189.py"
SUPPORTED_TARGET: Final = "src.cli_pr189:main"
EVIDENCE_PATHS: Final[tuple[str, ...]] = (
    PYPROJECT_PATH,
    PRODUCTION_SURFACE_PATH,
    AUTHORITY_MAP_PATH,
    PACKAGED_AUTHORITY_MAP_PATH,
    "scripts/verify_repo.py",
)


class Mpr32PublicEntrypointTruthError(RuntimeError):
    """Raised when a required repository artifact is malformed."""


@dataclass(frozen=True, slots=True)
class Mpr32PublicEntrypointTruthEvidence:
    schema_version: str
    accepted: bool
    blockers: tuple[str, ...]
    artifact_hashes: dict[str, str]
    console_scripts: tuple[str, ...]
    production_surface_entrypoints: tuple[str, ...]
    authority_supported_entrypoint: str | None
    authority_supported_target: str | None
    authority_resource_parity: bool

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["blockers"] = list(self.blockers)
        payload["console_scripts"] = list(self.console_scripts)
        payload["production_surface_entrypoints"] = list(self.production_surface_entrypoints)
        return payload


def _repo_file(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    resolved_root = root.resolve()
    if candidate == resolved_root or resolved_root not in candidate.parents:
        raise Mpr32PublicEntrypointTruthError(f"path escapes repository root: {relative}")
    return candidate


def _read_bytes(root: Path, relative: str) -> bytes:
    try:
        return _repo_file(root, relative).read_bytes()
    except FileNotFoundError as exc:
        raise Mpr32PublicEntrypointTruthError(f"required file is missing: {relative}") from exc


def _load_json(root: Path, relative: str) -> dict[str, Any]:
    try:
        value = json.loads(_read_bytes(root, relative).decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise Mpr32PublicEntrypointTruthError(f"invalid JSON in {relative}: {exc}") from exc
    if not isinstance(value, dict):
        raise Mpr32PublicEntrypointTruthError(f"{relative} must contain a JSON object")
    return value


def _load_pyproject(root: Path) -> dict[str, Any]:
    try:
        value = tomllib.loads(_read_bytes(root, PYPROJECT_PATH).decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise Mpr32PublicEntrypointTruthError(f"invalid pyproject.toml: {exc}") from exc
    if not isinstance(value, dict):
        raise Mpr32PublicEntrypointTruthError("pyproject.toml must decode to an object")
    return value


def _require(condition: bool, blockers: list[str], code: str) -> None:
    if not condition:
        blockers.append(code)


def _as_dict(value: object, blockers: list[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        blockers.append(code)
        return {}
    return value


def _project_scripts(pyproject: dict[str, Any], blockers: list[str]) -> dict[str, str]:
    project = _as_dict(pyproject.get("project"), blockers, "PYPROJECT_PROJECT_SECTION_MISSING")
    scripts = _as_dict(project.get("scripts"), blockers, "PYPROJECT_SCRIPTS_MISSING")
    return {str(key): str(value) for key, value in scripts.items()}


def _production_surface_entrypoints(root: Path, blockers: list[str]) -> tuple[dict[str, str], dict[str, Any]]:
    manifest = _load_json(root, PRODUCTION_SURFACE_PATH)
    entrypoints = _as_dict(
        manifest.get("entrypoints"),
        blockers,
        "PRODUCTION_SURFACE_ENTRYPOINTS_MISSING",
    )
    return {str(key): str(value) for key, value in entrypoints.items()}, manifest


def _authority_map_supported_entrypoint(root: Path, blockers: list[str]) -> tuple[dict[str, Any], bool]:
    authority_raw = _read_bytes(root, AUTHORITY_MAP_PATH)
    packaged_raw = _read_bytes(root, PACKAGED_AUTHORITY_MAP_PATH)
    parity = authority_raw == packaged_raw
    _require(parity, blockers, "AUTHORITY_MAP_RESOURCE_DRIFT")
    authority_map = _load_json(root, AUTHORITY_MAP_PATH)
    supported = _as_dict(
        authority_map.get("supported_entrypoint"),
        blockers,
        "AUTHORITY_MAP_SUPPORTED_ENTRYPOINT_MISSING",
    )
    return supported, parity


def verify_mpr32_public_entrypoint_truth(
    root: str | Path = ROOT,
) -> Mpr32PublicEntrypointTruthEvidence:
    repo_root = Path(root).resolve()
    blockers: list[str] = []
    artifact_hashes: dict[str, str] = {}
    for relative in EVIDENCE_PATHS:
        try:
            artifact_hashes[relative] = hashlib.sha256(_read_bytes(repo_root, relative)).hexdigest()
        except Mpr32PublicEntrypointTruthError:
            blockers.append(f"MISSING:{relative}")

    pyproject = _load_pyproject(repo_root)
    scripts = _project_scripts(pyproject, blockers)
    surface_entrypoints, manifest = _production_surface_entrypoints(repo_root, blockers)
    authority_supported, parity = _authority_map_supported_entrypoint(repo_root, blockers)

    pyproject_names = set(scripts)
    surface_names = set(surface_entrypoints)
    _require(pyproject_names == surface_names, blockers, "PUBLIC_ENTRYPOINT_SET_MISMATCH")

    for name in sorted(pyproject_names | surface_names):
        _require(
            scripts.get(name) == surface_entrypoints.get(name),
            blockers,
            f"PUBLIC_ENTRYPOINT_TARGET_MISMATCH:{name}",
        )

    supported_console = authority_supported.get("console_script")
    supported_target = authority_supported.get("target")
    supported_owner_path = authority_supported.get("owner_path")

    _require(
        supported_console == SUPPORTED_ENTRYPOINT,
        blockers,
        "AUTHORITY_SUPPORTED_ENTRYPOINT_MISMATCH",
    )
    _require(
        supported_target == scripts.get(SUPPORTED_ENTRYPOINT),
        blockers,
        "AUTHORITY_SUPPORTED_TARGET_MISMATCH",
    )
    _require(
        supported_target == SUPPORTED_TARGET,
        blockers,
        "SUPPORTED_ENTRYPOINT_TARGET_DRIFT",
    )
    _require(
        supported_owner_path == SUPPORTED_OWNER_PATH,
        blockers,
        "AUTHORITY_SUPPORTED_OWNER_PATH_MISMATCH",
    )

    runtime = _as_dict(
        manifest.get("runtime"),
        blockers,
        "PRODUCTION_SURFACE_RUNTIME_SECTION_MISSING",
    )
    _require(
        runtime.get("supported_entrypoint") == SUPPORTED_ENTRYPOINT,
        blockers,
        "PRODUCTION_SURFACE_SUPPORTED_ENTRYPOINT_MISMATCH",
    )
    runtime_cutover = _as_dict(
        manifest.get("runtime_cutover"),
        blockers,
        "PRODUCTION_SURFACE_RUNTIME_CUTOVER_SECTION_MISSING",
    )
    canonical_composition = _as_dict(
        runtime_cutover.get("canonical_composition"),
        blockers,
        "PRODUCTION_SURFACE_CANONICAL_COMPOSITION_MISSING",
    )
    _require(
        canonical_composition.get("console_entrypoint") == SUPPORTED_ENTRYPOINT,
        blockers,
        "PRODUCTION_SURFACE_CANONICAL_CONSOLE_ENTRYPOINT_MISMATCH",
    )

    verify_repo_text = _read_bytes(repo_root, "scripts/verify_repo.py").decode("utf-8")
    _require(
        "scripts/verify_mpr32_public_entrypoint_truth.py" in verify_repo_text,
        blockers,
        "VERIFY_REPO_DOES_NOT_RUN_MPR32_PUBLIC_ENTRYPOINT_TRUTH",
    )

    unique_blockers = tuple(dict.fromkeys(blockers))
    return Mpr32PublicEntrypointTruthEvidence(
        schema_version=SCHEMA_VERSION,
        accepted=not unique_blockers,
        blockers=unique_blockers,
        artifact_hashes=artifact_hashes,
        console_scripts=tuple(sorted(scripts)),
        production_surface_entrypoints=tuple(sorted(surface_entrypoints)),
        authority_supported_entrypoint=(
            str(supported_console) if isinstance(supported_console, str) else None
        ),
        authority_supported_target=(
            str(supported_target) if isinstance(supported_target, str) else None
        ),
        authority_resource_parity=parity,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT), help="Repository root to verify.")
    parser.add_argument("--json", action="store_true", help="Print evidence as JSON.")
    args = parser.parse_args(argv)

    evidence = verify_mpr32_public_entrypoint_truth(args.root)
    if args.json:
        print(json.dumps(evidence.to_dict(), sort_keys=True, indent=2))
    elif evidence.accepted:
        print("MPR-32 public entrypoint truth verification passed.")
    else:
        print("MPR-32 public entrypoint truth verification failed:", file=sys.stderr)
        for blocker in evidence.blockers:
            print(f"- {blocker}", file=sys.stderr)
    return 0 if evidence.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
