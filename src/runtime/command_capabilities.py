"""Command-specific dependency closure and fail-closed admission.

The manifest distinguishes safety authorities from ordinary features and
non-authoritative enhancements.  Nested import failures are never mistaken for
an intentionally absent optional top-level dependency.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
from importlib import import_module, resources
import json
from pathlib import Path
from typing import Any, Callable, Mapping

MANIFEST_SCHEMA = "mpr-rp-01.command-capabilities.v1"
REPORT_SCHEMA = "mpr-rp-01.command-admission.v1"


class DependencyClass(StrEnum):
    MANDATORY_SAFETY_AUTHORITY = "mandatory_safety_authority"
    MANDATORY_FEATURE = "mandatory_feature"
    OPTIONAL_NON_AUTHORITATIVE_ENHANCEMENT = "optional_non_authoritative_enhancement"
    FORBIDDEN = "forbidden"
    QUARANTINED_SOURCE_ONLY = "quarantined_source_only"


class DependencyReason(StrEnum):
    READY = "READY"
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    DEPENDENCY_BROKEN = "DEPENDENCY_BROKEN"
    SYMBOL_MISSING = "SYMBOL_MISSING"
    ABI_MISMATCH = "ABI_MISMATCH"
    AUTHORITY_UNAVAILABLE = "AUTHORITY_UNAVAILABLE"
    OPTIONAL_UNAVAILABLE = "OPTIONAL_UNAVAILABLE"
    FORBIDDEN_DEPENDENCY_LOADED = "FORBIDDEN_DEPENDENCY_LOADED"
    QUARANTINED = "QUARANTINED"


class CommandCapabilityError(ValueError):
    """The command capability manifest is malformed or inconsistent."""


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class DependencySpec:
    module: str
    dependency_class: DependencyClass
    symbol: str | None = None
    probe: str | None = None

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any]) -> "DependencySpec":
        module = str(raw.get("module", "")).strip()
        if not module:
            raise CommandCapabilityError("dependency module is required")
        try:
            kind = DependencyClass(str(raw.get("class", "")))
        except ValueError as exc:
            raise CommandCapabilityError(
                f"unknown dependency class for {module}: {raw.get('class')!r}"
            ) from exc
        symbol = raw.get("symbol")
        probe = raw.get("probe")
        return cls(
            module=module,
            dependency_class=kind,
            symbol=str(symbol) if symbol is not None else None,
            probe=str(probe) if probe is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["dependency_class"] = self.dependency_class.value
        return value


@dataclass(frozen=True, slots=True)
class DependencyProbeResult:
    module: str
    dependency_class: DependencyClass
    symbol: str | None
    reason: DependencyReason
    blocking: bool
    detail: str | None = None
    probe_evidence: Mapping[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "class": self.dependency_class.value,
            "symbol": self.symbol,
            "reason": self.reason.value,
            "blocking": self.blocking,
            "detail": self.detail,
            "probe_evidence": dict(self.probe_evidence or {}),
        }


@dataclass(frozen=True, slots=True)
class CommandAdmissionReport:
    schema_version: str
    command: str
    admitted: bool
    manifest_sha256: str
    closure_sha256: str
    blockers: tuple[str, ...]
    dependencies: tuple[DependencyProbeResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "command": self.command,
            "admitted": self.admitted,
            "manifest_sha256": self.manifest_sha256,
            "closure_sha256": self.closure_sha256,
            "blockers": list(self.blockers),
            "dependencies": [item.to_dict() for item in self.dependencies],
        }


@dataclass(frozen=True, slots=True)
class CommandCapabilityManifest:
    schema_version: str
    commands: Mapping[str, tuple[DependencySpec, ...]]
    manifest_sha256: str

    @classmethod
    def load(cls, path: str | Path | None = None) -> "CommandCapabilityManifest":
        if path is not None:
            raw_text = Path(path).read_text(encoding="utf-8")
        else:
            root = Path(__file__).resolve().parents[2]
            repository = root / "config" / "command_capabilities.json"
            if repository.is_file():
                raw_text = repository.read_text(encoding="utf-8")
            else:
                raw_text = resources.files("src.resources").joinpath(
                    "command_capabilities.json"
                ).read_text(encoding="utf-8")
        raw = json.loads(raw_text)
        if raw.get("schema_version") != MANIFEST_SCHEMA:
            raise CommandCapabilityError("command capability schema mismatch")
        commands_raw = raw.get("commands")
        if not isinstance(commands_raw, Mapping):
            raise CommandCapabilityError("commands must be an object")
        commands: dict[str, tuple[DependencySpec, ...]] = {}
        for name, payload in commands_raw.items():
            if not isinstance(payload, Mapping) or not isinstance(
                payload.get("dependencies"), list
            ):
                raise CommandCapabilityError(f"command dependencies malformed: {name}")
            dependencies = tuple(
                DependencySpec.from_raw(item) for item in payload["dependencies"]
            )
            keys = [(item.module, item.symbol) for item in dependencies]
            if len(keys) != len(set(keys)):
                raise CommandCapabilityError(f"duplicate dependency in command {name}")
            commands[str(name)] = dependencies
        return cls(
            schema_version=MANIFEST_SCHEMA,
            commands=commands,
            manifest_sha256=_canonical_hash(raw),
        )

    def evaluate(
        self,
        command: str,
        *,
        importer: Callable[[str], Any] = import_module,
    ) -> CommandAdmissionReport:
        try:
            dependencies = self.commands[command]
        except KeyError as exc:
            raise CommandCapabilityError(f"command is not declared: {command}") from exc
        results = tuple(
            _probe_dependency(item, importer=importer) for item in dependencies
        )
        blockers = tuple(
            f"{item.reason.value}:{item.module}"
            for item in results
            if item.blocking
        )
        closure = [item.to_dict() for item in results]
        return CommandAdmissionReport(
            schema_version=REPORT_SCHEMA,
            command=command,
            admitted=not blockers,
            manifest_sha256=self.manifest_sha256,
            closure_sha256=_canonical_hash(closure),
            blockers=blockers,
            dependencies=results,
        )


def _top_level_absence(requested: str, missing: str | None) -> bool:
    if not missing:
        return False
    return requested == missing or requested.startswith(f"{missing}.")


def _blocking(kind: DependencyClass) -> bool:
    return kind in {
        DependencyClass.MANDATORY_SAFETY_AUTHORITY,
        DependencyClass.MANDATORY_FEATURE,
    }


def _load_probe(reference: str, *, importer: Callable[[str], Any]) -> Callable[[], Any]:
    module_name, separator, symbol = reference.partition(":")
    if not separator or not module_name or not symbol:
        raise CommandCapabilityError(f"invalid probe reference: {reference}")
    module = importer(module_name)
    value = getattr(module, symbol, None)
    if not callable(value):
        raise CommandCapabilityError(f"probe is not callable: {reference}")
    return value


def _probe_dependency(
    spec: DependencySpec,
    *,
    importer: Callable[[str], Any],
) -> DependencyProbeResult:
    if spec.dependency_class is DependencyClass.QUARANTINED_SOURCE_ONLY:
        return DependencyProbeResult(
            module=spec.module,
            dependency_class=spec.dependency_class,
            symbol=spec.symbol,
            reason=DependencyReason.QUARANTINED,
            blocking=False,
        )
    try:
        module = importer(spec.module)
    except ModuleNotFoundError as exc:
        top_level = _top_level_absence(spec.module, exc.name)
        reason = (
            DependencyReason.DEPENDENCY_MISSING
            if top_level
            else DependencyReason.DEPENDENCY_BROKEN
        )
        if (
            spec.dependency_class
            is DependencyClass.OPTIONAL_NON_AUTHORITATIVE_ENHANCEMENT
        ):
            reason = DependencyReason.OPTIONAL_UNAVAILABLE
        if spec.dependency_class is DependencyClass.MANDATORY_SAFETY_AUTHORITY:
            reason = DependencyReason.AUTHORITY_UNAVAILABLE if top_level else reason
        return DependencyProbeResult(
            module=spec.module,
            dependency_class=spec.dependency_class,
            symbol=spec.symbol,
            reason=reason,
            blocking=_blocking(spec.dependency_class),
            detail=f"missing={exc.name}",
        )
    except ImportError as exc:
        reason = (
            DependencyReason.OPTIONAL_UNAVAILABLE
            if spec.dependency_class
            is DependencyClass.OPTIONAL_NON_AUTHORITATIVE_ENHANCEMENT
            else DependencyReason.DEPENDENCY_BROKEN
        )
        return DependencyProbeResult(
            module=spec.module,
            dependency_class=spec.dependency_class,
            symbol=spec.symbol,
            reason=reason,
            blocking=_blocking(spec.dependency_class),
            detail=type(exc).__name__,
        )

    if spec.dependency_class is DependencyClass.FORBIDDEN:
        return DependencyProbeResult(
            module=spec.module,
            dependency_class=spec.dependency_class,
            symbol=spec.symbol,
            reason=DependencyReason.FORBIDDEN_DEPENDENCY_LOADED,
            blocking=True,
        )
    if spec.symbol is not None and not hasattr(module, spec.symbol):
        return DependencyProbeResult(
            module=spec.module,
            dependency_class=spec.dependency_class,
            symbol=spec.symbol,
            reason=DependencyReason.SYMBOL_MISSING,
            blocking=_blocking(spec.dependency_class),
        )

    evidence: Mapping[str, str] | None = None
    if spec.probe is not None:
        try:
            raw = _load_probe(spec.probe, importer=importer)()
            evidence = {str(key): str(value) for key, value in dict(raw).items()}
        except Exception as exc:
            return DependencyProbeResult(
                module=spec.module,
                dependency_class=spec.dependency_class,
                symbol=spec.symbol,
                reason=DependencyReason.ABI_MISMATCH,
                blocking=_blocking(spec.dependency_class),
                detail=type(exc).__name__,
            )
    return DependencyProbeResult(
        module=spec.module,
        dependency_class=spec.dependency_class,
        symbol=spec.symbol,
        reason=DependencyReason.READY,
        blocking=False,
        probe_evidence=evidence,
    )
