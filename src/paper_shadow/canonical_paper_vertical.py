"""MEGA-PR A canonical sender-free paper vertical startup contract.

This module is intentionally side-effect free: it does not import provider clients,
signers, senders, Jito submission code, RPC clients, or private-key material.  Its
job is to make the supported paper/shadow composition root name the exact active
runtime surfaces that must be present before a candidate can move through the
sender-free vertical.

The important PR-A change is that the supported composition root can no longer
look like a generic "all atomic dependencies are missing" placeholder.  It now
creates a deterministic startup decision, records it into runner evidence, and
uses stable reason codes that identify which real vertical surface is absent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

MEGA_PR_A_SCHEMA = "mega-pr-a.canonical-paper-vertical.startup.v1"
PR_A_CANONICAL_VERTICAL_UNWIRED = "blocked_pr_a_canonical_vertical_unwired"
PR_A_CANONICAL_VERTICAL_INVALID = "blocked_pr_a_canonical_vertical_invalid"

# These names intentionally match PaperShadowRuntimeDependencies attributes.
_REQUIRED_VERTICAL_SURFACES: tuple[str, ...] = (
    "atomic_stage_suite",
    "exact_fee_workflow",
    "verified_marginfi_provider",
    "jupiter_v2_build",
)


class CanonicalPaperVerticalStatus(StrEnum):
    """Startup state for the supported sender-free paper vertical."""

    READY = "ready"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class CanonicalPaperVerticalStartup:
    """Deterministic startup evaluation for MEGA-PR A.

    ``ready`` means the composition root was supplied with a complete and
    validated set of sender-free runtime dependencies.  It does not mean live is
    enabled; live remains structurally disabled in this layer.
    """

    config_fingerprint: str
    runtime_mode: str
    available_surfaces: Mapping[str, bool]
    missing_surfaces: tuple[str, ...] = ()
    invalid_surfaces: tuple[str, ...] = ()
    schema_version: str = MEGA_PR_A_SCHEMA
    live_allowed: bool = False
    sender_reachable: bool = False
    signer_reachable: bool = False
    fake_success_permitted: bool = False
    required_surfaces: tuple[str, ...] = field(
        default_factory=lambda: _REQUIRED_VERTICAL_SURFACES
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "available_surfaces",
            MappingProxyType(dict(self.available_surfaces)),
        )
        object.__setattr__(self, "missing_surfaces", tuple(self.missing_surfaces))
        object.__setattr__(self, "invalid_surfaces", tuple(self.invalid_surfaces))
        object.__setattr__(self, "required_surfaces", tuple(self.required_surfaces))
        # PR-A is sender-free by construction.  A truthy caller-provided value is
        # never preserved because this startup record is a safety boundary.
        object.__setattr__(self, "live_allowed", False)
        object.__setattr__(self, "sender_reachable", False)
        object.__setattr__(self, "signer_reachable", False)
        object.__setattr__(self, "fake_success_permitted", False)

    @property
    def status(self) -> CanonicalPaperVerticalStatus:
        if self.missing_surfaces or self.invalid_surfaces:
            return CanonicalPaperVerticalStatus.BLOCKED
        return CanonicalPaperVerticalStatus.READY

    @property
    def ready(self) -> bool:
        return self.status is CanonicalPaperVerticalStatus.READY

    @property
    def reason_code(self) -> str | None:
        if self.invalid_surfaces and not self.missing_surfaces:
            return PR_A_CANONICAL_VERTICAL_INVALID
        if self.missing_surfaces or self.invalid_surfaces:
            return PR_A_CANONICAL_VERTICAL_UNWIRED
        return None

    def dependency_reasons(self) -> tuple[str, ...]:
        reason = self.reason_code
        if reason is None:
            return ()
        return (
            reason,
            *tuple(f"missing_{name}" for name in self.missing_surfaces),
            *tuple(f"invalid_{name}" for name in self.invalid_surfaces),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "ready": self.ready,
            "reason_code": self.reason_code,
            "config_fingerprint": self.config_fingerprint,
            "runtime_mode": self.runtime_mode,
            "required_surfaces": list(self.required_surfaces),
            "available_surfaces": dict(self.available_surfaces),
            "missing_surfaces": list(self.missing_surfaces),
            "invalid_surfaces": list(self.invalid_surfaces),
            "live_allowed": self.live_allowed,
            "sender_reachable": self.sender_reachable,
            "signer_reachable": self.signer_reachable,
            "fake_success_permitted": self.fake_success_permitted,
        }


def build_canonical_paper_vertical_startup(
    config: Any,
    dependencies: Any,
) -> CanonicalPaperVerticalStartup:
    """Evaluate the active paper composition seam without constructing IO clients."""

    missing = tuple(str(name) for name in dependencies.missing())
    invalid = tuple(str(name) for name in dependencies.invalid())
    return CanonicalPaperVerticalStartup(
        config_fingerprint=_safe_config_fingerprint(config),
        runtime_mode=_safe_runtime_mode(config),
        available_surfaces=_dependency_surface_flags(dependencies),
        missing_surfaces=missing,
        invalid_surfaces=invalid,
    )


def _dependency_surface_flags(dependencies: Any) -> dict[str, bool]:
    return {
        name: getattr(dependencies, name, None) is not None
        for name in _REQUIRED_VERTICAL_SURFACES
    }


def _safe_config_fingerprint(config: Any) -> str:
    fingerprint = getattr(config, "fingerprint", None)
    if callable(fingerprint):
        value = fingerprint()
        return str(value)
    return "unavailable"


def _safe_runtime_mode(config: Any) -> str:
    runtime = getattr(config, "runtime", None)
    mode = getattr(runtime, "mode", None)
    value = getattr(mode, "value", mode)
    return str(value if value is not None else "unknown")


__all__ = [
    "CanonicalPaperVerticalStartup",
    "CanonicalPaperVerticalStatus",
    "MEGA_PR_A_SCHEMA",
    "PR_A_CANONICAL_VERTICAL_INVALID",
    "PR_A_CANONICAL_VERTICAL_UNWIRED",
    "build_canonical_paper_vertical_startup",
]
