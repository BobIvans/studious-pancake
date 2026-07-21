"""Machine-readable runtime capability contract introduced by PR-023."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum
from importlib import resources
from pathlib import Path
from typing import Any, Iterable


class CapabilityContractError(ValueError):
    """The capability registry is missing, malformed, or inconsistent."""


class CapabilityState(str, Enum):
    IMPLEMENTED = "implemented"
    FIXTURE_ONLY = "fixture-only"
    SHADOW_READY = "shadow-ready"
    LIVE_READY = "live-ready"
    DISABLED = "disabled"


_ALLOWED_STRATEGY_MODES = frozenset({"disabled", "shadow", "live"})


@dataclass(frozen=True, slots=True)
class ComponentCapability:
    id: str
    kind: str
    path: str
    capability: CapabilityState
    active_in_supported_entrypoint: bool
    quarantined: bool
    allowed_modes: tuple[str, ...]
    reason: str
    registry_name: str | None = None
    required_in_installed_package: bool = True

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ComponentCapability":
        required = {
            "id",
            "kind",
            "path",
            "capability",
            "active_in_supported_entrypoint",
            "quarantined",
            "allowed_modes",
            "reason",
        }
        missing = sorted(required - raw.keys())
        if missing:
            raise CapabilityContractError(
                f"capability component is missing fields {missing}: {raw.get('id', '<unknown>')}"
            )
        try:
            state = CapabilityState(str(raw["capability"]))
        except ValueError as exc:
            raise CapabilityContractError(
                f"unknown capability state for {raw.get('id', '<unknown>')}: {raw.get('capability')!r}"
            ) from exc
        modes = tuple(str(mode) for mode in raw["allowed_modes"])
        invalid_modes = sorted(set(modes) - _ALLOWED_STRATEGY_MODES)
        if invalid_modes:
            raise CapabilityContractError(
                f"invalid allowed_modes for {raw['id']}: {invalid_modes}"
            )
        if not modes:
            raise CapabilityContractError(
                f"allowed_modes must not be empty: {raw['id']}"
            )
        if raw["quarantined"] and modes != ("disabled",):
            raise CapabilityContractError(
                f"quarantined component may only allow disabled mode: {raw['id']}"
            )
        return cls(
            id=str(raw["id"]),
            kind=str(raw["kind"]),
            path=str(raw["path"]),
            capability=state,
            active_in_supported_entrypoint=bool(raw["active_in_supported_entrypoint"]),
            quarantined=bool(raw["quarantined"]),
            allowed_modes=modes,
            reason=str(raw["reason"]),
            registry_name=(
                str(raw["registry_name"])
                if raw.get("registry_name") is not None
                else None
            ),
            required_in_installed_package=bool(
                raw.get("required_in_installed_package", True)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["capability"] = self.capability.value
        value["allowed_modes"] = list(self.allowed_modes)
        return value


@dataclass(frozen=True, slots=True)
class CapabilityMatrix:
    schema_version: str
    product_state: str
    supported_entrypoint: str
    default_command: str
    runtime_modes: dict[str, dict[str, Any]]
    components: tuple[ComponentCapability, ...]
    source_path: Path
    root_path: Path
    installed_package: bool

    @classmethod
    def _from_raw(
        cls,
        raw: Any,
        *,
        source_path: Path,
        root_path: Path,
        installed_package: bool,
    ) -> "CapabilityMatrix":
        if not isinstance(raw, dict):
            raise CapabilityContractError("capability matrix root must be an object")
        components_raw = raw.get("components")
        if not isinstance(components_raw, list):
            raise CapabilityContractError("capability matrix components must be a list")
        components = tuple(
            ComponentCapability.from_dict(item) for item in components_raw
        )
        ids = [item.id for item in components]
        if len(ids) != len(set(ids)):
            raise CapabilityContractError(
                "capability matrix contains duplicate component ids"
            )
        registry_names = [
            item.registry_name for item in components if item.registry_name is not None
        ]
        if len(registry_names) != len(set(registry_names)):
            raise CapabilityContractError(
                "capability matrix contains duplicate registry_name values"
            )
        runtime_modes = raw.get("runtime_modes")
        if not isinstance(runtime_modes, dict):
            raise CapabilityContractError("runtime_modes must be an object")
        expected_modes = {"disabled", "paper", "shadow", "live"}
        if set(runtime_modes) != expected_modes:
            raise CapabilityContractError(
                f"runtime_modes must be exactly {sorted(expected_modes)}"
            )
        return cls(
            schema_version=str(raw.get("schema_version", "")),
            product_state=str(raw.get("product_state", "")),
            supported_entrypoint=str(raw.get("supported_entrypoint", "")),
            default_command=str(raw.get("default_command", "")),
            runtime_modes=runtime_modes,
            components=components,
            source_path=source_path,
            root_path=root_path.resolve(),
            installed_package=installed_package,
        )

    @classmethod
    def load(
        cls, path: str | Path, *, root: str | Path | None = None
    ) -> "CapabilityMatrix":
        source = Path(path).resolve()
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise CapabilityContractError(
                f"capability matrix not found: {source}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise CapabilityContractError(
                f"invalid capability matrix JSON: {source}: {exc}"
            ) from exc
        inferred_root = (
            Path(root).resolve() if root is not None else source.parent.parent
        )
        return cls._from_raw(
            raw,
            source_path=source,
            root_path=inferred_root,
            installed_package=False,
        )

    @classmethod
    def load_default(cls) -> "CapabilityMatrix":
        root = Path(__file__).resolve().parents[1]
        repository_registry = root / "config" / "capabilities.json"
        if repository_registry.is_file():
            return cls.load(repository_registry, root=root)
        try:
            package_registry = resources.files("src.resources").joinpath(
                "capabilities.json"
            )
            raw = json.loads(package_registry.read_text(encoding="utf-8"))
        except (FileNotFoundError, ModuleNotFoundError, json.JSONDecodeError) as exc:
            raise CapabilityContractError(
                "installed capability matrix is missing or malformed"
            ) from exc
        source = root / "src" / "resources" / "capabilities.json"
        return cls._from_raw(
            raw,
            source_path=source,
            root_path=root,
            installed_package=True,
        )

    def strategy(self, registry_name: str) -> ComponentCapability:
        for component in self.components:
            if component.registry_name == registry_name:
                return component
        raise CapabilityContractError(
            f"strategy is not declared in capability matrix: {registry_name}"
        )

    def validate_paths(self, root: str | Path | None = None) -> tuple[str, ...]:
        repo_root = Path(root).resolve() if root is not None else self.root_path
        errors = []
        for component in self.components:
            if self.installed_package and (
                component.quarantined or not component.required_in_installed_package
            ):
                continue
            if not (repo_root / component.path).exists():
                errors.append(
                    f"missing component path: {component.id}: {component.path}"
                )
        return tuple(errors)

    def validate_strategy_registry(self, strategies: Iterable[Any]) -> tuple[str, ...]:
        registered = {str(strategy.name): strategy for strategy in strategies}
        declared = {
            component.registry_name: component
            for component in self.components
            if component.kind == "strategy" and component.registry_name is not None
        }
        errors: list[str] = []
        for missing in sorted(set(registered) - set(declared)):
            errors.append(
                f"registered strategy missing from capability matrix: {missing}"
            )
        for stale in sorted(set(declared) - set(registered)):
            errors.append(f"capability matrix strategy is not registered: {stale}")
        for name in sorted(set(registered) & set(declared)):
            mode = str(registered[name].mode.value)
            capability = declared[name]
            if mode not in capability.allowed_modes:
                errors.append(
                    f"strategy mode forbidden by capability contract: {name}={mode}; "
                    f"allowed={','.join(capability.allowed_modes)}"
                )
            if capability.quarantined and mode != "disabled":
                errors.append(f"quarantined strategy is enabled: {name}={mode}")
        return tuple(errors)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "product_state": self.product_state,
            "supported_entrypoint": self.supported_entrypoint,
            "default_command": self.default_command,
            "runtime_modes": self.runtime_modes,
            "components": [component.to_dict() for component in self.components],
        }
