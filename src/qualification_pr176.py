"""PR-176/PR-186 hermetic qualification plan contract.

The plan is descriptive only. Dependency closure is based on the selected
interpreter's installed distributions and import probes, not arbitrary package-
looking strings found in project metadata. Only an executed PR-186 verdict may
authorize a release claim.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib import metadata, util
import json
import platform
from pathlib import Path
import re
import sys
import tomllib
from typing import Any, Iterable, Mapping, Sequence

PR176_SCHEMA = "pr176.hermetic-qualification.v2"
MANDATORY_PROFILES = ("core", "paper")
REQUIRED_COLLECTION_PACKAGES = ("aiolimiter", "pytest", "solders")
_REQUIREMENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
_NORMALISE_RUN = re.compile(r"[-_.]+")


@dataclass(frozen=True, slots=True)
class QualificationProfile:
    name: str
    command: tuple[str, ...]
    mandatory: bool
    purpose: str
    required_packages: tuple[str, ...] = ()
    isolated_collection: bool = True
    network_after_wheelhouse: bool = False
    hidden_skips_allowed: bool = False

    def __post_init__(self) -> None:
        if not self.name or not self.command or not self.purpose:
            raise ValueError("qualification profile needs name, command and purpose")
        if self.mandatory and self.hidden_skips_allowed:
            raise ValueError(f"{self.name} mandatory profile cannot hide skips")
        if self.network_after_wheelhouse:
            raise ValueError(f"{self.name} cannot use network after wheelhouse")
        object.__setattr__(self, "command", tuple(self.command))
        object.__setattr__(
            self,
            "required_packages",
            tuple(sorted(set(map(normalise_package_name, self.required_packages)))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": list(self.command),
            "mandatory": self.mandatory,
            "purpose": self.purpose,
            "required_packages": list(self.required_packages),
            "isolated_collection": self.isolated_collection,
            "network_after_wheelhouse": self.network_after_wheelhouse,
            "hidden_skips_allowed": self.hidden_skips_allowed,
        }


@dataclass(frozen=True, slots=True)
class DependencyClosure:
    lock_hashes: Mapping[str, str]
    required_packages: tuple[str, ...]
    present_packages: tuple[str, ...]
    missing_packages: tuple[str, ...]
    global_site_packages: bool = False
    declared_packages: tuple[str, ...] = ()
    undeclared_packages: tuple[str, ...] = ()
    installed_versions: Mapping[str, str] = None  # type: ignore[assignment]
    importable_packages: tuple[str, ...] = ()
    non_importable_packages: tuple[str, ...] = ()
    interpreter_executable: str = sys.executable

    def __post_init__(self) -> None:
        if self.installed_versions is None:
            object.__setattr__(self, "installed_versions", {})
        object.__setattr__(self, "installed_versions", dict(self.installed_versions))

    @property
    def complete(self) -> bool:
        return bool(
            not self.missing_packages
            and not self.undeclared_packages
            and not self.non_importable_packages
            and not self.global_site_packages
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "lock_hashes": dict(sorted(self.lock_hashes.items())),
            "required_packages": list(self.required_packages),
            "declared_packages": list(self.declared_packages),
            "undeclared_packages": list(self.undeclared_packages),
            "present_packages": list(self.present_packages),
            "missing_packages": list(self.missing_packages),
            "installed_versions": dict(sorted(self.installed_versions.items())),
            "importable_packages": list(self.importable_packages),
            "non_importable_packages": list(self.non_importable_packages),
            "global_site_packages": self.global_site_packages,
            "interpreter_executable": self.interpreter_executable,
            "evidence_kind": "installed-distribution-and-import-probe",
        }


@dataclass(frozen=True, slots=True)
class QualificationPlan:
    profiles: tuple[QualificationProfile, ...]
    dependency_closure: DependencyClosure
    schema_version: str = PR176_SCHEMA
    python_requirement: str = ">=3.13,<3.14"
    clean_checkout_required: bool = True
    editable_install_allowed: bool = False
    source_wheel_parity_required: bool = True
    signed_manifest_required: bool = True
    repeated_clean_run_required: bool = True

    def __post_init__(self) -> None:
        names = [profile.name for profile in self.profiles]
        if len(names) != len(set(names)):
            raise ValueError("duplicate qualification profile")
        missing = sorted(set(MANDATORY_PROFILES).difference(names))
        if missing:
            raise ValueError(f"missing mandatory profiles: {missing}")
        if self.editable_install_allowed:
            raise ValueError("editable installation leakage is forbidden")

    @property
    def mandatory_profiles(self) -> tuple[str, ...]:
        return tuple(profile.name for profile in self.profiles if profile.mandatory)

    @property
    def release_claim_allowed(self) -> bool:
        """Plans never authorize release claims; retained for safe compatibility."""
        return False

    def to_manifest(self, *, source_digest: str, execution_mode: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "execution_mode": execution_mode,
            "qualification_state": "planned_not_executed",
            "python_requirement": self.python_requirement,
            "python_version": ".".join(map(str, sys.version_info[:3])),
            "interpreter_executable": str(Path(sys.executable).resolve()),
            "platform": {
                "system": platform.system(),
                "machine": platform.machine(),
                "python": platform.python_implementation(),
            },
            "source_digest": source_digest,
            "clean_checkout_required": self.clean_checkout_required,
            "editable_install_allowed": self.editable_install_allowed,
            "source_wheel_parity_required": self.source_wheel_parity_required,
            "signed_manifest_required": self.signed_manifest_required,
            "repeated_clean_run_required": self.repeated_clean_run_required,
            "mandatory_profiles": list(self.mandatory_profiles),
            "dependency_closure": self.dependency_closure.to_dict(),
            "profiles": [profile.to_dict() for profile in self.profiles],
            "release_claim_allowed": False,
            "qualified": False,
        }
        payload["manifest_hash"] = canonical_hash(payload)
        return payload


def build_default_qualification_plan(
    root: Path,
    *,
    installed_distributions: Mapping[str, str] | None = None,
    importable_packages: Iterable[str] | None = None,
    global_site_packages: bool = False,
    interpreter_executable: str | None = None,
) -> QualificationPlan:
    closure = inspect_dependency_closure(
        root,
        lock_paths=(
            root / "requirements.txt",
            root / "requirements-dev.txt",
            root / "pyproject.toml",
        ),
        required_packages=REQUIRED_COLLECTION_PACKAGES,
        installed_distributions=installed_distributions,
        importable_packages=importable_packages,
        global_site_packages=global_site_packages,
        interpreter_executable=interpreter_executable,
    )
    python = interpreter_executable or sys.executable
    return QualificationPlan(
        dependency_closure=closure,
        profiles=(
            QualificationProfile(
                "core",
                (python, "scripts/verify_repo.py", "--skip-dependency-audit"),
                True,
                "core package, quality, security and offline tests",
                REQUIRED_COLLECTION_PACKAGES,
            ),
            QualificationProfile(
                "paper",
                (
                    python,
                    "-m",
                    "pytest",
                    "-m",
                    "not live and not manual",
                    "--disable-socket",
                    "--allow-unix-socket",
                    "-q",
                ),
                True,
                "sender-free paper/runtime qualification",
                REQUIRED_COLLECTION_PACKAGES,
            ),
            QualificationProfile(
                "live-gated",
                (python, "-m", "pytest", "-m", "live_gated", "--disable-socket", "-q"),
                False,
                "gated live-control tests without submission",
                ("pytest",),
                hidden_skips_allowed=True,
            ),
            QualificationProfile(
                "plugins",
                (python, "-m", "pytest", "tests/plugins", "-q"),
                False,
                "optional plugin qualification isolated from core",
                ("pytest",),
                hidden_skips_allowed=True,
            ),
            QualificationProfile(
                "legacy-quarantine",
                (python, "-m", "pytest", "tests/legacy", "-q"),
                False,
                "legacy quarantine regression only",
                ("pytest",),
                hidden_skips_allowed=True,
            ),
            QualificationProfile(
                "all-development",
                (python, "-m", "pytest", "-q"),
                False,
                "developer full suite, not release green by itself",
                REQUIRED_COLLECTION_PACKAGES,
                hidden_skips_allowed=True,
            ),
        ),
    )


def inspect_dependency_closure(
    root: Path,
    *,
    lock_paths: Sequence[Path],
    required_packages: Iterable[str],
    global_site_packages: bool = False,
    installed_distributions: Mapping[str, str] | None = None,
    importable_packages: Iterable[str] | None = None,
    interpreter_executable: str | None = None,
) -> DependencyClosure:
    lock_hashes: dict[str, str] = {}
    declared: set[str] = set()
    for path in lock_paths:
        key = _relative_name(root, path)
        if not path.exists():
            lock_hashes[key] = "missing"
            continue
        raw = path.read_bytes()
        lock_hashes[key] = hashlib.sha256(raw).hexdigest()
        if path.name == "pyproject.toml":
            declared.update(parse_pyproject_requirement_names(raw))
        else:
            declared.update(parse_requirement_names(raw.decode("utf-8")))

    required = tuple(sorted(set(map(normalise_package_name, required_packages))))
    versions = (
        _installed_versions(required)
        if installed_distributions is None
        else {
            normalise_package_name(name): str(version)
            for name, version in installed_distributions.items()
        }
    )
    importable = (
        _importable_packages(required, root=root)
        if importable_packages is None
        else set(map(normalise_package_name, importable_packages))
    )
    present = set(required).intersection(versions)
    missing = set(required).difference(present)
    undeclared = set(required).difference(declared)
    non_importable = set(required).difference(importable)
    return DependencyClosure(
        lock_hashes=lock_hashes,
        required_packages=required,
        declared_packages=tuple(sorted(declared)),
        undeclared_packages=tuple(sorted(undeclared)),
        present_packages=tuple(sorted(present)),
        missing_packages=tuple(sorted(missing)),
        installed_versions={name: versions[name] for name in sorted(present)},
        importable_packages=tuple(sorted(set(required).intersection(importable))),
        non_importable_packages=tuple(sorted(non_importable)),
        global_site_packages=global_site_packages,
        interpreter_executable=str(Path(interpreter_executable or sys.executable).resolve()),
    )


def _installed_versions(required: Sequence[str]) -> dict[str, str]:
    output: dict[str, str] = {}
    for name in required:
        try:
            output[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return output


def _importable_packages(required: Sequence[str], *, root: Path | None = None) -> set[str]:
    output: set[str] = set()
    resolved_root = root.resolve() if root is not None else None
    for name in required:
        module_name = name.replace("-", "_")
        try:
            found = util.find_spec(module_name)
        except (ImportError, AttributeError, ValueError):
            found = None
        if found is None:
            continue
        origin = getattr(found, "origin", None)
        if resolved_root is not None and origin not in (None, "built-in", "frozen"):
            try:
                Path(origin).resolve().relative_to(resolved_root)
            except (OSError, ValueError):
                pass
            else:
                continue
        output.add(name)
    return output


def canonical_hash(value: Mapping[str, Any]) -> str:
    data = dict(value)
    data.pop("manifest_hash", None)
    data.pop("run_hash", None)
    data.pop("verdict_hash", None)
    return hashlib.sha256(
        json.dumps(
            data,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_pyproject_requirement_names(raw: bytes) -> set[str]:
    """Return only dependency declarations from a standards-parsed pyproject.

    Project metadata, scripts, package discovery and tool configuration are
    deliberately ignored. Malformed TOML or malformed dependency entries fail
    closed with ValueError/TOMLDecodeError.
    """

    document = tomllib.loads(raw.decode("utf-8"))
    names: set[str] = set()
    project = document.get("project", {})
    if project is not None and not isinstance(project, dict):
        raise ValueError("pyproject [project] must be a table")
    if isinstance(project, dict):
        names.update(_parse_requirement_array(project.get("dependencies", []), "project.dependencies"))
        optional = project.get("optional-dependencies", {})
        if optional is not None and not isinstance(optional, dict):
            raise ValueError("project.optional-dependencies must be a table")
        if isinstance(optional, dict):
            for group, values in optional.items():
                names.update(_parse_requirement_array(values, f"project.optional-dependencies.{group}"))
    build = document.get("build-system", {})
    if build is not None and not isinstance(build, dict):
        raise ValueError("pyproject [build-system] must be a table")
    if isinstance(build, dict):
        names.update(_parse_requirement_array(build.get("requires", []), "build-system.requires"))
    return names


def _parse_requirement_array(value: object, field: str) -> set[str]:
    if value is None:
        return set()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be an array of requirement strings")
    return {parse_requirement_name(item) for item in value}


def parse_requirement_names(text: str) -> set[str]:
    """Parse a strict requirements-file subset and fail closed on ambiguity."""

    names: set[str] = set()
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("-e", "--editable")):
            raise ValueError(f"editable requirement forbidden at line {line_no}")
        if line.startswith("-"):
            raise ValueError(f"unsupported requirements directive at line {line_no}: {line}")
        if " #" in line:
            line = line.split(" #", 1)[0].rstrip()
        try:
            names.add(parse_requirement_name(line))
        except ValueError as exc:
            raise ValueError(f"invalid requirement at line {line_no}: {exc}") from exc
    return names


def parse_requirement_name(requirement: str) -> str:
    value = requirement.strip()
    if not value or " @ " in value or value.startswith(("git+", "http://", "https://", "file:")):
        raise ValueError(f"unsupported requirement syntax: {requirement!r}")
    match = _REQUIREMENT_NAME.match(value)
    if match is None:
        raise ValueError(f"missing distribution name: {requirement!r}")
    name = match.group(0)
    remainder = value[match.end():]
    if remainder.startswith("["):
        end = remainder.find("]")
        if end < 0:
            raise ValueError(f"unterminated extras: {requirement!r}")
        extras = remainder[1:end]
        if not extras or any(not part.strip() for part in extras.split(",")):
            raise ValueError(f"invalid extras: {requirement!r}")
        remainder = remainder[end + 1 :]
    remainder = remainder.strip()
    if remainder and remainder[0] not in "<>=!~;":
        raise ValueError(f"unsupported requirement suffix: {requirement!r}")
    return normalise_package_name(name)


def normalise_package_name(name: str) -> str:
    return _NORMALISE_RUN.sub("-", name.strip().lower())


def _relative_name(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name
