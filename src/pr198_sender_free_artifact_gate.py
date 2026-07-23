"""PR-198 sender-free installed-artifact import gate.

This module validates already-materialized wheel/container evidence for the
PR-198 sender-free runtime boundary. It is deliberately offline: it does not
import wallets, signers, RPC clients, Jito, provider transports, or sender code.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Mapping, Sequence

SCHEMA_VERSION = "pr198.sender-free-artifact-gate.v1"
PRODUCT_ID = "studious-pancake.pr198.sender-free-artifact-gate"

REQUIRED_ENTRYPOINTS: tuple[str, ...] = (
    "flashloan-bot",
    "flashloan-checks",
)

FORBIDDEN_MODULE_PREFIXES: tuple[str, ...] = (
    "src.execution.senders",
    "src.execution.live_submit",
    "src.execution.jito_submit",
    "src.signer",
    "src.wallet_signer",
    "src.live_sender",
)

FORBIDDEN_CAPABILITIES: tuple[str, ...] = (
    "live_trading_enabled",
    "sender_enabled",
    "signer_enabled",
    "jito_submission_enabled",
    "rpc_submission_enabled",
    "private_key_materialized",
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PR198ArtifactGateState(StrEnum):
    """Final sender-free artifact verdict."""

    READY_FOR_SENDER_FREE_RUNTIME = "ready-for-sender-free-runtime"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ImportEdge:
    """One normalized module import edge from installed-artifact evidence."""

    importer: str
    imported: str

    def __post_init__(self) -> None:
        _module_name(self.importer, "importer")
        _module_name(self.imported, "imported")

    def to_dict(self) -> dict[str, str]:
        return {"importer": self.importer, "imported": self.imported}


@dataclass(frozen=True, slots=True)
class InstalledArtifactEvidence:
    """Evidence extracted from the installed wheel/container, not checkout only."""

    wheel_sha256: str
    image_sha256: str
    entrypoints: Mapping[str, str]
    installed_modules: Sequence[str]
    reachable_modules: Sequence[str]
    import_edges: Sequence[ImportEdge]
    capabilities: Mapping[str, bool]
    source_tree_only: bool = False

    def __post_init__(self) -> None:
        _sha256(self.wheel_sha256, "wheel_sha256")
        _sha256(self.image_sha256, "image_sha256")
        if self.source_tree_only:
            raise ValueError("PR-198 artifact evidence must come from installed output")
        if not self.entrypoints:
            raise ValueError("entrypoints must not be empty")
        for name, target in self.entrypoints.items():
            _identifier(name, f"entrypoint:{name}")
            _module_name(target.split(":", 1)[0], f"entrypoint-target:{name}")
        _module_sequence(self.installed_modules, "installed_modules")
        _module_sequence(self.reachable_modules, "reachable_modules")
        for key, value in self.capabilities.items():
            _identifier(key, f"capability:{key}")
            if not isinstance(value, bool):
                raise TypeError(f"capability {key} must be boolean")


@dataclass(frozen=True, slots=True)
class ArtifactGateViolation:
    """One deterministic PR-198 artifact-gate violation."""

    code: str
    subject: str
    detail: str

    def __post_init__(self) -> None:
        _identifier(self.code, "violation.code")
        if not self.subject:
            raise ValueError("violation subject must not be empty")
        if not self.detail:
            raise ValueError("violation detail must not be empty")

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class PR198ArtifactGateReport:
    """Deterministic report consumed by PR-198 release evidence."""

    schema_version: str
    product_id: str
    state: PR198ArtifactGateState
    evidence_hash: str
    violations: tuple[ArtifactGateViolation, ...]
    live_execution_allowed: bool = False
    signer_allowed: bool = False
    sender_import_allowed: bool = False

    @property
    def ready(self) -> bool:
        return self.state is PR198ArtifactGateState.READY_FOR_SENDER_FREE_RUNTIME

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "product_id": self.product_id,
            "state": self.state.value,
            "ready": self.ready,
            "evidence_hash": self.evidence_hash,
            "violation_count": len(self.violations),
            "violations": [violation.to_dict() for violation in self.violations],
            "safety_boundary": {
                "live_execution_allowed": self.live_execution_allowed,
                "signer_allowed": self.signer_allowed,
                "sender_import_allowed": self.sender_import_allowed,
            },
        }


def evaluate_sender_free_artifact(
    evidence: InstalledArtifactEvidence,
) -> PR198ArtifactGateReport:
    """Return a fail-closed sender-free installed-artifact verdict."""

    violations: list[ArtifactGateViolation] = []

    missing_entrypoints = [
        name for name in REQUIRED_ENTRYPOINTS if name not in evidence.entrypoints
    ]
    for entrypoint in missing_entrypoints:
        violations.append(
            ArtifactGateViolation(
                code="missing_required_entrypoint",
                subject=entrypoint,
                detail="installed artifact is missing a PR-198 required entrypoint",
            )
        )

    installed = tuple(sorted(set(evidence.installed_modules)))
    reachable = tuple(sorted(set(evidence.reachable_modules)))
    for module_name in installed:
        if _is_forbidden_module(module_name):
            violations.append(
                ArtifactGateViolation(
                    code="forbidden_module_installed",
                    subject=module_name,
                    detail="sender/signer/live module is present in installed artifact",
                )
            )

    reachable_set = set(reachable)
    for module_name in reachable:
        if _is_forbidden_module(module_name):
            violations.append(
                ArtifactGateViolation(
                    code="forbidden_module_reachable",
                    subject=module_name,
                    detail="sender/signer/live module is reachable from runtime surface",
                )
            )

    for edge in evidence.import_edges:
        if edge.importer in reachable_set and _is_forbidden_module(edge.imported):
            violations.append(
                ArtifactGateViolation(
                    code="forbidden_import_edge",
                    subject=f"{edge.importer}->{edge.imported}",
                    detail="reachable runtime module imports forbidden sender/signer surface",
                )
            )

    for capability in FORBIDDEN_CAPABILITIES:
        if evidence.capabilities.get(capability, False):
            violations.append(
                ArtifactGateViolation(
                    code="forbidden_capability_enabled",
                    subject=capability,
                    detail="PR-198 sender-free artifact cannot expose live/signer/sender capability",
                )
            )

    ordered_violations = tuple(
        sorted(violations, key=lambda item: (item.code, item.subject, item.detail))
    )
    return PR198ArtifactGateReport(
        schema_version=SCHEMA_VERSION,
        product_id=PRODUCT_ID,
        state=(
            PR198ArtifactGateState.BLOCKED
            if ordered_violations
            else PR198ArtifactGateState.READY_FOR_SENDER_FREE_RUNTIME
        ),
        evidence_hash=_evidence_hash(evidence),
        violations=ordered_violations,
    )


def _evidence_hash(evidence: InstalledArtifactEvidence) -> str:
    payload = {
        "domain": "studious-pancake/pr198/sender-free-artifact-gate",
        "wheel_sha256": evidence.wheel_sha256,
        "image_sha256": evidence.image_sha256,
        "entrypoints": dict(sorted(evidence.entrypoints.items())),
        "installed_modules": sorted(set(evidence.installed_modules)),
        "reachable_modules": sorted(set(evidence.reachable_modules)),
        "import_edges": [
            edge.to_dict()
            for edge in sorted(
                evidence.import_edges,
                key=lambda item: (item.importer, item.imported),
            )
        ],
        "capabilities": dict(sorted(evidence.capabilities.items())),
        "source_tree_only": evidence.source_tree_only,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _is_forbidden_module(module_name: str) -> bool:
    return any(
        module_name == prefix or module_name.startswith(prefix + ".")
        for prefix in FORBIDDEN_MODULE_PREFIXES
    )


def _identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a stable identifier")
    return value


def _module_name(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _MODULE_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a Python module name")
    return value


def _module_sequence(values: Sequence[str], field_name: str) -> None:
    if not values:
        raise ValueError(f"{field_name} must not be empty")
    for value in values:
        _module_name(value, field_name)


def _sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")
    return value
