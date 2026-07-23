"""PR-200 reproducible production sandbox and cutover policy.

This module is deliberately offline and sender-free.  It validates a proposed
production deployment manifest before any cutover automation can trust it.  It
never reads secrets, signs transactions, opens sockets or enables live trading.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Mapping
from urllib.parse import urlparse

PR200_SCHEMA_VERSION = "pr200.production-sandbox.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MUTABLE_TAGS = {"latest", "stable", "main", "master", "dev", "test"}
_ALLOWED_SERVICE_ROLES = {"runtime", "signer", "egress-gateway", "observer"}
_REQUIRED_ARTIFACT_HASHES = (
    "source_commit_sha",
    "wheel_sha256",
    "runtime_image_digest",
    "sbom_sha256",
    "config_generation_hash",
    "protocol_registry_hash",
)


class PR200SandboxError(ValueError):
    """Raised when the PR-200 sandbox manifest is malformed."""


class DiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class SandboxDiagnostic:
    code: str
    severity: DiagnosticSeverity
    message: str
    path: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "path": self.path,
        }


@dataclass(frozen=True, slots=True)
class ImageReference:
    value: str
    digest: str

    @classmethod
    def parse(cls, value: object, *, path: str) -> "ImageReference":
        text = _non_empty(value, field=path)
        if "@sha256:" not in text:
            raise PR200SandboxError(
                f"{path} must be pinned by immutable sha256 digest"
            )
        prefix, digest = text.rsplit("@sha256:", 1)
        if not prefix or not _SHA256_RE.fullmatch(digest.lower()):
            raise PR200SandboxError(f"{path} has an invalid sha256 image digest")
        tag = prefix.rsplit(":", 1)[-1] if ":" in prefix.rsplit("/", 1)[-1] else ""
        if tag in _MUTABLE_TAGS:
            raise PR200SandboxError(f"{path} uses mutable tag {tag!r}")
        return cls(text, digest.lower())


@dataclass(frozen=True, slots=True)
class EgressPolicy:
    deny_by_default: bool
    allowed_origins: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "EgressPolicy":
        return cls(
            deny_by_default=_bool(raw.get("deny_by_default"), "egress.deny_by_default"),
            allowed_origins=tuple(
                _origin(item, path=f"egress.allowed_origins[{index}]")
                for index, item in enumerate(raw.get("allowed_origins", ()))
            ),
        )

    def validate(self) -> tuple[SandboxDiagnostic, ...]:
        diagnostics: list[SandboxDiagnostic] = []
        if not self.deny_by_default:
            diagnostics.append(
                SandboxDiagnostic(
                    "EGRESS_NOT_DENY_BY_DEFAULT",
                    DiagnosticSeverity.ERROR,
                    "production egress must be deny-by-default",
                    "egress.deny_by_default",
                )
            )
        if not self.allowed_origins:
            diagnostics.append(
                SandboxDiagnostic(
                    "EGRESS_ALLOWLIST_EMPTY",
                    DiagnosticSeverity.ERROR,
                    "production egress requires an explicit allowlist",
                    "egress.allowed_origins",
                )
            )
        return tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class ServiceSandbox:
    name: str
    role: str
    image: ImageReference
    read_only_root: bool
    no_new_privileges: bool
    cap_drop_all: bool
    arbitrary_internet: bool
    can_read_signer_key: bool
    secret_sources: tuple[str, ...]
    networks: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], *, index: int) -> "ServiceSandbox":
        path = f"services[{index}]"
        role = _non_empty(raw.get("role"), field=f"{path}.role")
        if role not in _ALLOWED_SERVICE_ROLES:
            raise PR200SandboxError(f"{path}.role is unsupported: {role}")
        return cls(
            name=_non_empty(raw.get("name"), field=f"{path}.name"),
            role=role,
            image=ImageReference.parse(raw.get("image"), path=f"{path}.image"),
            read_only_root=_bool(raw.get("read_only_root"), f"{path}.read_only_root"),
            no_new_privileges=_bool(
                raw.get("no_new_privileges"), f"{path}.no_new_privileges"
            ),
            cap_drop_all=_bool(raw.get("cap_drop_all"), f"{path}.cap_drop_all"),
            arbitrary_internet=_bool(
                raw.get("arbitrary_internet"), f"{path}.arbitrary_internet"
            ),
            can_read_signer_key=_bool(
                raw.get("can_read_signer_key"), f"{path}.can_read_signer_key"
            ),
            secret_sources=tuple(
                _non_empty(item, field=f"{path}.secret_sources[{item_index}]")
                for item_index, item in enumerate(raw.get("secret_sources", ()))
            ),
            networks=tuple(
                _non_empty(item, field=f"{path}.networks[{item_index}]")
                for item_index, item in enumerate(raw.get("networks", ()))
            ),
        )

    def validate(self) -> tuple[SandboxDiagnostic, ...]:
        diagnostics: list[SandboxDiagnostic] = []
        service_path = f"services.{self.name}"
        if not self.read_only_root:
            diagnostics.append(
                SandboxDiagnostic(
                    "SERVICE_ROOT_WRITABLE",
                    DiagnosticSeverity.ERROR,
                    "service root filesystem must be read-only",
                    f"{service_path}.read_only_root",
                )
            )
        if not self.no_new_privileges:
            diagnostics.append(
                SandboxDiagnostic(
                    "SERVICE_CAN_GAIN_PRIVILEGES",
                    DiagnosticSeverity.ERROR,
                    "service must run with no-new-privileges",
                    f"{service_path}.no_new_privileges",
                )
            )
        if not self.cap_drop_all:
            diagnostics.append(
                SandboxDiagnostic(
                    "SERVICE_CAPABILITIES_NOT_DROPPED",
                    DiagnosticSeverity.ERROR,
                    "service must drop ambient Linux capabilities",
                    f"{service_path}.cap_drop_all",
                )
            )
        if self.role == "runtime" and self.can_read_signer_key:
            diagnostics.append(
                SandboxDiagnostic(
                    "RUNTIME_CAN_READ_SIGNER_KEY",
                    DiagnosticSeverity.ERROR,
                    "runtime service must not read signer key material",
                    f"{service_path}.can_read_signer_key",
                )
            )
        if self.role == "signer" and self.arbitrary_internet:
            diagnostics.append(
                SandboxDiagnostic(
                    "SIGNER_HAS_ARBITRARY_INTERNET",
                    DiagnosticSeverity.ERROR,
                    "signer service must not have arbitrary internet egress",
                    f"{service_path}.arbitrary_internet",
                )
            )
        for source in self.secret_sources:
            lowered = source.lower()
            if "example" in lowered or "placeholder" in lowered or lowered.endswith(".sample"):
                diagnostics.append(
                    SandboxDiagnostic(
                        "EXAMPLE_SECRET_SOURCE",
                        DiagnosticSeverity.ERROR,
                        "example or placeholder secret source is forbidden",
                        f"{service_path}.secret_sources",
                    )
                )
        return tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class ProductionSandboxManifest:
    schema_version: str
    artifact_hashes: Mapping[str, str]
    egress: EgressPolicy
    services: tuple[ServiceSandbox, ...]
    active_submitters: int
    live_enabled: bool
    signer_key_exportable: bool
    signed_release_pointer: bool
    rollback_rehearsed: bool
    outstanding_attempts_reconciled: bool
    raw: Mapping[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ProductionSandboxManifest":
        if not isinstance(raw, Mapping):
            raise PR200SandboxError("manifest root must be an object")
        schema = _non_empty(raw.get("schema_version"), field="schema_version")
        if schema != PR200_SCHEMA_VERSION:
            raise PR200SandboxError("unsupported PR-200 sandbox schema")
        artifacts = raw.get("artifact_hashes", {})
        if not isinstance(artifacts, Mapping):
            raise PR200SandboxError("artifact_hashes must be an object")
        egress = raw.get("egress", {})
        if not isinstance(egress, Mapping):
            raise PR200SandboxError("egress must be an object")
        services = raw.get("services", ())
        if not isinstance(services, list):
            raise PR200SandboxError("services must be a list")
        return cls(
            schema_version=schema,
            artifact_hashes={str(key): str(value) for key, value in artifacts.items()},
            egress=EgressPolicy.from_dict(egress),
            services=tuple(
                ServiceSandbox.from_dict(item, index=index)
                for index, item in enumerate(services)
            ),
            active_submitters=_int(raw.get("active_submitters"), "active_submitters"),
            live_enabled=_bool(raw.get("live_enabled"), "live_enabled"),
            signer_key_exportable=_bool(
                raw.get("signer_key_exportable"), "signer_key_exportable"
            ),
            signed_release_pointer=_bool(
                raw.get("signed_release_pointer"), "signed_release_pointer"
            ),
            rollback_rehearsed=_bool(
                raw.get("rollback_rehearsed"), "rollback_rehearsed"
            ),
            outstanding_attempts_reconciled=_bool(
                raw.get("outstanding_attempts_reconciled"),
                "outstanding_attempts_reconciled",
            ),
            raw=dict(raw),
        )

    def manifest_hash(self) -> str:
        encoded = json.dumps(
            self.raw,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def validate(self) -> tuple[SandboxDiagnostic, ...]:
        diagnostics: list[SandboxDiagnostic] = []
        diagnostics.extend(self._validate_artifacts())
        diagnostics.extend(self.egress.validate())
        roles = {service.role for service in self.services}
        if "runtime" not in roles:
            diagnostics.append(
                SandboxDiagnostic(
                    "RUNTIME_SERVICE_MISSING",
                    DiagnosticSeverity.ERROR,
                    "production sandbox requires a runtime service",
                    "services",
                )
            )
        if "signer" not in roles:
            diagnostics.append(
                SandboxDiagnostic(
                    "SIGNER_SERVICE_MISSING",
                    DiagnosticSeverity.ERROR,
                    "production sandbox requires an isolated signer service",
                    "services",
                )
            )
        for service in self.services:
            diagnostics.extend(service.validate())
        if self.active_submitters != 1:
            diagnostics.append(
                SandboxDiagnostic(
                    "ACTIVE_SUBMITTER_FENCE_INVALID",
                    DiagnosticSeverity.ERROR,
                    "exactly one active submitter must be fenced at deployment layer",
                    "active_submitters",
                )
            )
        if self.live_enabled:
            diagnostics.append(
                SandboxDiagnostic(
                    "LIVE_ENABLEMENT_OUT_OF_SCOPE",
                    DiagnosticSeverity.ERROR,
                    "this PR-200 foundation validates cutover but does not enable live",
                    "live_enabled",
                )
            )
        if self.signer_key_exportable:
            diagnostics.append(
                SandboxDiagnostic(
                    "SIGNER_KEY_EXPORTABLE",
                    DiagnosticSeverity.ERROR,
                    "signer key material must not be exportable to runtime artifacts",
                    "signer_key_exportable",
                )
            )
        if not self.signed_release_pointer:
            diagnostics.append(
                SandboxDiagnostic(
                    "UNSIGNED_RELEASE_POINTER",
                    DiagnosticSeverity.ERROR,
                    "release/cutover pointer must be signed",
                    "signed_release_pointer",
                )
            )
        if not self.rollback_rehearsed:
            diagnostics.append(
                SandboxDiagnostic(
                    "ROLLBACK_NOT_REHEARSED",
                    DiagnosticSeverity.ERROR,
                    "rollback procedure must be rehearsed before cutover",
                    "rollback_rehearsed",
                )
            )
        if not self.outstanding_attempts_reconciled:
            diagnostics.append(
                SandboxDiagnostic(
                    "OUTSTANDING_ATTEMPTS_NOT_RECONCILED",
                    DiagnosticSeverity.ERROR,
                    "outstanding attempts must be reconciled before data rollback",
                    "outstanding_attempts_reconciled",
                )
            )
        return tuple(diagnostics)

    def _validate_artifacts(self) -> tuple[SandboxDiagnostic, ...]:
        diagnostics: list[SandboxDiagnostic] = []
        for name in _REQUIRED_ARTIFACT_HASHES:
            value = self.artifact_hashes.get(name)
            if value is None:
                diagnostics.append(
                    SandboxDiagnostic(
                        "ARTIFACT_HASH_MISSING",
                        DiagnosticSeverity.ERROR,
                        f"required artifact hash {name!r} is missing",
                        f"artifact_hashes.{name}",
                    )
                )
                continue
            if not _SHA256_RE.fullmatch(value.lower()):
                diagnostics.append(
                    SandboxDiagnostic(
                        "ARTIFACT_HASH_INVALID",
                        DiagnosticSeverity.ERROR,
                        f"artifact hash {name!r} must be sha256 hex",
                        f"artifact_hashes.{name}",
                    )
                )
        return tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class ProductionSandboxReport:
    schema_version: str
    ok: bool
    manifest_hash: str
    diagnostics: tuple[SandboxDiagnostic, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "manifest_hash": self.manifest_hash,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


def validate_production_sandbox_manifest(
    manifest: Mapping[str, Any],
) -> ProductionSandboxReport:
    parsed = ProductionSandboxManifest.from_dict(manifest)
    diagnostics = parsed.validate()
    return ProductionSandboxReport(
        schema_version=parsed.schema_version,
        ok=not any(item.severity is DiagnosticSeverity.ERROR for item in diagnostics),
        manifest_hash=parsed.manifest_hash(),
        diagnostics=diagnostics,
    )


def live_capability_allowed() -> bool:
    """PR-200 foundation is still a validator and never opens live capability."""

    return False


def _origin(value: object, *, path: str) -> str:
    text = _non_empty(value, field=path).rstrip("/")
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
        raise PR200SandboxError(f"{path} must be an HTTPS origin without path")
    return text


def _bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise PR200SandboxError(f"{field} must be boolean")
    return value


def _int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PR200SandboxError(f"{field} must be an integer")
    return value


def _non_empty(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PR200SandboxError(f"{field} must be a non-empty string")
    return value.strip()


__all__ = [
    "DiagnosticSeverity",
    "EgressPolicy",
    "ImageReference",
    "PR200_SCHEMA_VERSION",
    "PR200SandboxError",
    "ProductionSandboxManifest",
    "ProductionSandboxReport",
    "SandboxDiagnostic",
    "ServiceSandbox",
    "live_capability_allowed",
    "validate_production_sandbox_manifest",
]
