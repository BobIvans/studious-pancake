"""PR-176 hermetic qualification contract.

Pure, non-mutating model for release qualification profiles, dependency closure
and deterministic qualification manifests.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import platform
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping, Sequence

PR176_SCHEMA = "pr176.hermetic-qualification.v1"
MANDATORY_PROFILES = ("core", "paper")
REQUIRED_COLLECTION_PACKAGES = ("aiolimiter", "pytest", "solders")


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

    @property
    def complete(self) -> bool:
        return not self.missing_packages and not self.global_site_packages

    def to_dict(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "lock_hashes": dict(sorted(self.lock_hashes.items())),
            "required_packages": list(self.required_packages),
            "present_packages": list(self.present_packages),
            "missing_packages": list(self.missing_packages),
            "global_site_packages": self.global_site_packages,
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
        return self.dependency_closure.complete and all(
            profile.isolated_collection for profile in self.profiles
        )

    def to_manifest(self, *, source_digest: str, execution_mode: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "execution_mode": execution_mode,
            "python_requirement": self.python_requirement,
            "python_version": ".".join(map(str, sys.version_info[:3])),
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
            "release_claim_allowed": self.release_claim_allowed,
        }
        payload["manifest_hash"] = canonical_hash(payload)
        return payload


def build_default_qualification_plan(root: Path) -> QualificationPlan:
    closure = inspect_dependency_closure(
        root,
        lock_paths=(
            root / "requirements.txt",
            root / "requirements-dev.txt",
            root / "pyproject.toml",
        ),
        required_packages=REQUIRED_COLLECTION_PACKAGES,
    )
    return QualificationPlan(
        dependency_closure=closure,
        profiles=(
            QualificationProfile(
                "core",
                ("python", "scripts/verify_repo.py", "--skip-dependency-audit"),
                True,
                "core package, quality, security and offline tests",
                REQUIRED_COLLECTION_PACKAGES,
            ),
            QualificationProfile(
                "paper",
                (
                    "python",
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
                ("python", "-m", "pytest", "-m", "live_gated", "--disable-socket", "-q"),
                False,
                "gated live-control tests without submission",
                ("pytest",),
                hidden_skips_allowed=True,
            ),
            QualificationProfile(
                "plugins",
                ("python", "-m", "pytest", "tests/plugins", "-q"),
                False,
                "optional plugin qualification isolated from core",
                ("pytest",),
                hidden_skips_allowed=True,
            ),
            QualificationProfile(
                "legacy-quarantine",
                ("python", "-m", "pytest", "tests/legacy", "-q"),
                False,
                "legacy quarantine regression only",
                ("pytest",),
                hidden_skips_allowed=True,
            ),
            QualificationProfile(
                "all-development",
                ("python", "-m", "pytest", "-q"),
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
) -> DependencyClosure:
    lock_hashes: dict[str, str] = {}
    present: set[str] = set()
    for path in lock_paths:
        key = _relative_name(root, path)
        if not path.exists():
            lock_hashes[key] = "missing"
            continue
        text = path.read_text(encoding="utf-8")
        lock_hashes[key] = sha256_text(text)
        present.update(parse_requirement_names(text))
    required = tuple(sorted(set(map(normalise_package_name, required_packages))))
    return DependencyClosure(
        lock_hashes=lock_hashes,
        required_packages=required,
        present_packages=tuple(sorted(set(required).intersection(present))),
        missing_packages=tuple(sorted(set(required).difference(present))),
        global_site_packages=global_site_packages,
    )


def canonical_hash(value: Mapping[str, Any]) -> str:
    data = dict(value)
    data.pop("manifest_hash", None)
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_requirement_names(text: str) -> set[str]:
    names: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip().strip(",").strip('"').strip("'")
        if not line or line.startswith("#") or line.startswith("[") or line.startswith("-"):
            continue
        for sep in ("==", ">=", "<=", "~=", "!=", ">", "<", ";", "["):
            if sep in line:
                line = line.split(sep, 1)[0]
        names.add(normalise_package_name(line.strip()))
    return names


def normalise_package_name(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _relative_name(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name
