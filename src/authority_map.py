"""PR-01 machine-readable repository authority and queue contract."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
import json
from pathlib import Path
import tomllib
from typing import Any, Mapping

SCHEMA_VERSION = "pr01.authority-map.v1"
_ALLOWED_AUTHORITY_STATUSES = frozenset(
    {"active", "blocked", "diagnostic-only", "quarantined"}
)
_ALLOWED_QUEUE_STATUSES = frozenset({"candidate", "diagnostic-only", "superseded"})
_EXPECTED_ROADMAP = tuple(f"PR-{index:02d}" for index in range(1, 11))


class AuthorityMapError(ValueError):
    """Raised when repository authority declarations are malformed or inconsistent."""


@dataclass(frozen=True, slots=True)
class SupportedEntrypoint:
    console_script: str
    target: str
    owner_path: str
    delegates_to: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SupportedEntrypoint":
        return cls(
            console_script=_required_text(raw, "console_script"),
            target=_required_text(raw, "target"),
            owner_path=_required_text(raw, "owner_path"),
            delegates_to=_text_tuple(raw, "delegates_to"),
        )


@dataclass(frozen=True, slots=True)
class AuthorityRecord:
    concern: str
    owner_path: str
    status: str
    rationale: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "AuthorityRecord":
        status = _required_text(raw, "status")
        if status not in _ALLOWED_AUTHORITY_STATUSES:
            raise AuthorityMapError(f"unsupported authority status: {status}")
        return cls(
            concern=_required_text(raw, "concern"),
            owner_path=_required_text(raw, "owner_path"),
            status=status,
            rationale=_required_text(raw, "rationale"),
        )


@dataclass(frozen=True, slots=True)
class RoadmapVertical:
    roadmap_pr: str
    name: str
    active_branches: tuple[str, ...]
    hard_disabled: bool

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "RoadmapVertical":
        active_branches = _text_tuple(raw, "active_branches")
        if len(active_branches) > 1:
            raise AuthorityMapError(
                f"{raw.get('roadmap_pr', '<unknown>')} has multiple active branches"
            )
        return cls(
            roadmap_pr=_required_text(raw, "roadmap_pr"),
            name=_required_text(raw, "name"),
            active_branches=active_branches,
            hard_disabled=_required_bool(raw, "hard_disabled"),
        )


@dataclass(frozen=True, slots=True)
class QueueEntry:
    github_pr: int
    branch: str
    destinations: tuple[str, ...]
    disposition: str
    authority_status: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "QueueEntry":
        github_pr = raw.get("github_pr")
        if (
            not isinstance(github_pr, int)
            or isinstance(github_pr, bool)
            or github_pr < 1
        ):
            raise AuthorityMapError("github_pr must be a positive integer")
        authority_status = _required_text(raw, "authority_status")
        if authority_status not in _ALLOWED_QUEUE_STATUSES:
            raise AuthorityMapError(
                f"unsupported queue authority_status: {authority_status}"
            )
        destinations = _text_tuple(raw, "destinations")
        if not destinations:
            raise AuthorityMapError(f"PR #{github_pr} has no numeric destination")
        invalid = sorted(
            destination
            for destination in destinations
            if destination not in _EXPECTED_ROADMAP and destination != "DEFERRED"
        )
        if invalid:
            raise AuthorityMapError(
                f"PR #{github_pr} has invalid destinations: {invalid}"
            )
        return cls(
            github_pr=github_pr,
            branch=_required_text(raw, "branch"),
            destinations=destinations,
            disposition=_required_text(raw, "disposition"),
            authority_status=authority_status,
        )


@dataclass(frozen=True, slots=True)
class AuthorityMap:
    schema_version: str
    roadmap_task: str
    product_state: str
    supported_entrypoint: SupportedEntrypoint
    authorities: tuple[AuthorityRecord, ...]
    lifecycle_stores: tuple[Mapping[str, Any], ...]
    evidence_schemas: tuple[Mapping[str, Any], ...]
    verticals: tuple[RoadmapVertical, ...]
    superseded_implementations: tuple[Mapping[str, Any], ...]
    open_pr_queue: tuple[QueueEntry, ...]
    raw: Mapping[str, Any]
    source_path: Path
    installed_package: bool

    @classmethod
    def _from_raw(
        cls,
        raw: Any,
        *,
        source_path: Path,
        installed_package: bool,
    ) -> "AuthorityMap":
        if not isinstance(raw, dict):
            raise AuthorityMapError("authority map root must be an object")
        schema_version = _required_text(raw, "schema_version")
        if schema_version != SCHEMA_VERSION:
            raise AuthorityMapError(
                f"unsupported authority map schema: {schema_version}"
            )
        authorities = tuple(
            AuthorityRecord.from_dict(item) for item in _object_list(raw, "authorities")
        )
        verticals = tuple(
            RoadmapVertical.from_dict(item) for item in _object_list(raw, "verticals")
        )
        queue = tuple(
            QueueEntry.from_dict(item) for item in _object_list(raw, "open_pr_queue")
        )
        _ensure_unique(
            (record.concern for record in authorities),
            "authority concern",
        )
        _ensure_unique(
            (vertical.roadmap_pr for vertical in verticals),
            "roadmap PR",
        )
        if tuple(vertical.roadmap_pr for vertical in verticals) != _EXPECTED_ROADMAP:
            raise AuthorityMapError(
                "verticals must declare PR-01 through PR-10 in dependency order"
            )
        _ensure_unique(
            (branch for vertical in verticals for branch in vertical.active_branches),
            "active branch",
        )
        _ensure_unique((entry.github_pr for entry in queue), "GitHub PR")
        _ensure_unique((entry.branch for entry in queue), "queue branch")
        for vertical in verticals[7:]:
            if not vertical.hard_disabled:
                raise AuthorityMapError(
                    f"{vertical.roadmap_pr} must remain hard-disabled"
                )
        active_owner_paths = {
            record.owner_path
            for record in authorities
            if record.status in {"active", "blocked"}
        }
        superseded = tuple(_object_list(raw, "superseded_implementations"))
        for item in superseded:
            path = _required_text(item, "path")
            if path in active_owner_paths:
                raise AuthorityMapError(
                    f"superseded implementation is also an active owner: {path}"
                )
        return cls(
            schema_version=schema_version,
            roadmap_task=_required_text(raw, "roadmap_task"),
            product_state=_required_text(raw, "product_state"),
            supported_entrypoint=SupportedEntrypoint.from_dict(
                _required_object(raw, "supported_entrypoint")
            ),
            authorities=authorities,
            lifecycle_stores=tuple(_object_list(raw, "lifecycle_stores")),
            evidence_schemas=tuple(_object_list(raw, "evidence_schemas")),
            verticals=verticals,
            superseded_implementations=superseded,
            open_pr_queue=queue,
            raw=raw,
            source_path=source_path,
            installed_package=installed_package,
        )

    @classmethod
    def load(cls, path: str | Path) -> "AuthorityMap":
        source = Path(path).resolve()
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise AuthorityMapError(f"authority map not found: {source}") from exc
        except json.JSONDecodeError as exc:
            raise AuthorityMapError(f"invalid authority map JSON: {source}") from exc
        return cls._from_raw(raw, source_path=source, installed_package=False)

    @classmethod
    def load_default(cls) -> "AuthorityMap":
        root = Path(__file__).resolve().parents[1]
        repository_map = root / "config" / "runtime_authority_map.json"
        if repository_map.is_file():
            return cls.load(repository_map)
        try:
            package_map = resources.files("src.resources").joinpath(
                "runtime_authority_map.json"
            )
            raw = json.loads(package_map.read_text(encoding="utf-8"))
        except (FileNotFoundError, ModuleNotFoundError, json.JSONDecodeError) as exc:
            raise AuthorityMapError(
                "installed runtime authority map is missing or malformed"
            ) from exc
        source = root / "src" / "resources" / "runtime_authority_map.json"
        return cls._from_raw(raw, source_path=source, installed_package=True)

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.raw))

    def validate_repository(self, root: str | Path) -> tuple[str, ...]:
        repository = Path(root).resolve()
        errors: list[str] = []
        for record in self.authorities:
            if not (repository / record.owner_path).exists():
                errors.append(
                    f"missing authority owner: {record.concern}: {record.owner_path}"
                )
        for item in self.lifecycle_stores:
            owner_path = _required_text(item, "owner_path")
            if not (repository / owner_path).exists():
                errors.append(f"missing lifecycle store owner: {owner_path}")
        for item in self.evidence_schemas:
            owner_path = _required_text(item, "owner_path")
            if not (repository / owner_path).exists():
                errors.append(f"missing evidence schema owner: {owner_path}")
            mirror = item.get("packaged_mirror")
            if mirror is not None and not (repository / str(mirror)).is_file():
                errors.append(f"missing evidence schema mirror: {mirror}")
        for item in self.superseded_implementations:
            path = _required_text(item, "path")
            if not (repository / path).exists():
                errors.append(f"missing declared superseded path: {path}")
        errors.extend(self._validate_entrypoint(repository))
        errors.extend(self._validate_mirrors(repository))
        return tuple(errors)

    def _validate_entrypoint(self, repository: Path) -> list[str]:
        errors: list[str] = []
        pyproject = repository / "pyproject.toml"
        try:
            with pyproject.open("rb") as handle:
                project = tomllib.load(handle)["project"]
            actual_target = project["scripts"][self.supported_entrypoint.console_script]
        except (FileNotFoundError, KeyError, tomllib.TOMLDecodeError):
            return ["pyproject does not expose the declared supported entrypoint"]
        if actual_target != self.supported_entrypoint.target:
            errors.append(
                "entrypoint target mismatch: "
                f"{actual_target!r} != {self.supported_entrypoint.target!r}"
            )
        capability_path = repository / "config" / "capabilities.json"
        try:
            capability = json.loads(capability_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            errors.append("capability registry is missing or malformed")
            return errors
        if capability.get("supported_entrypoint") != (
            self.supported_entrypoint.console_script
        ):
            errors.append("capability registry supported_entrypoint mismatch")
        launcher = next(
            (
                item
                for item in capability.get("components", [])
                if item.get("id") == "runtime.launcher"
            ),
            None,
        )
        allowed_paths = {
            self.supported_entrypoint.owner_path,
            *self.supported_entrypoint.delegates_to,
        }
        if not isinstance(launcher, dict) or launcher.get("path") not in allowed_paths:
            errors.append("capability runtime.launcher is outside the declared chain")
        return errors

    def _validate_mirrors(self, repository: Path) -> list[str]:
        errors: list[str] = []
        pairs = (
            (
                repository / "config" / "runtime_authority_map.json",
                repository / "src" / "resources" / "runtime_authority_map.json",
                "authority map",
            ),
            (
                repository / "config" / "capabilities.json",
                repository / "src" / "resources" / "capabilities.json",
                "capability registry",
            ),
        )
        for source, mirror, label in pairs:
            try:
                source_payload = json.loads(source.read_text(encoding="utf-8"))
                mirror_payload = json.loads(mirror.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                errors.append(f"{label} source or packaged mirror is invalid")
                continue
            if source_payload != mirror_payload:
                errors.append(f"{label} source and packaged mirror differ")
        return errors


def _required_object(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise AuthorityMapError(f"{key} must be an object")
    return value


def _object_list(raw: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    value = raw.get(key)
    if not isinstance(value, list):
        raise AuthorityMapError(f"{key} must be a list")
    if not all(isinstance(item, dict) for item in value):
        raise AuthorityMapError(f"{key} entries must be objects")
    return value


def _required_text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AuthorityMapError(f"{key} must be a non-empty string")
    return value


def _required_bool(raw: Mapping[str, Any], key: str) -> bool:
    value = raw.get(key)
    if not isinstance(value, bool):
        raise AuthorityMapError(f"{key} must be a boolean")
    return value


def _text_tuple(raw: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = raw.get(key)
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise AuthorityMapError(f"{key} must be a list of non-empty strings")
    return tuple(value)


def _ensure_unique(values: Any, label: str) -> None:
    materialized = list(values)
    if len(materialized) != len(set(materialized)):
        raise AuthorityMapError(f"duplicate {label} declaration")


__all__ = [
    "AuthorityMap",
    "AuthorityMapError",
    "AuthorityRecord",
    "QueueEntry",
    "RoadmapVertical",
    "SCHEMA_VERSION",
    "SupportedEntrypoint",
]
