"""MEGA-PR A1 canonical sender-free paper vertical preflight.

A1 is an active CLI-visible seam for the canonical paper vertical. It does not
construct providers, RPC clients, signers, senders or transactions. Its job is to
make the supported paper runtime's missing integration surfaces explicit before
operators or CI try to run a sender-free paper cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

PR_A1_SCHEMA = "mega-pr-a1.paper-vertical-preflight.v1"
PR_A1_READY = "pr_a1_canonical_paper_vertical_ready"
PR_A1_UNWIRED = "blocked_pr_a1_canonical_paper_vertical_unwired"
PR_A1_INVALID = "blocked_pr_a1_canonical_paper_vertical_invalid"

REQUIRED_A1_SURFACES: tuple[str, ...] = (
    "atomic_stage_suite",
    "exact_fee_workflow",
    "verified_marginfi_provider",
    "jupiter_v2_build",
)


class PaperVerticalPreflightState(StrEnum):
    """A1 preflight state for the active sender-free paper path."""

    READY = "ready"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class PaperVerticalPreflight:
    """Deterministic evidence for the active paper-vertical dependency seam."""

    config_fingerprint: str
    runtime_mode: str
    available_surfaces: Mapping[str, bool]
    missing_surfaces: tuple[str, ...] = ()
    invalid_surfaces: tuple[str, ...] = ()
    schema_version: str = PR_A1_SCHEMA
    required_surfaces: tuple[str, ...] = field(default_factory=lambda: REQUIRED_A1_SURFACES)
    live_enabled: bool = False
    signer_reachable: bool = False
    sender_reachable: bool = False
    private_key_loading: bool = False
    fake_success_permitted: bool = False
    network_io_performed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "available_surfaces",
            MappingProxyType(dict(self.available_surfaces)),
        )
        object.__setattr__(self, "missing_surfaces", tuple(self.missing_surfaces))
        object.__setattr__(self, "invalid_surfaces", tuple(self.invalid_surfaces))
        object.__setattr__(self, "required_surfaces", tuple(self.required_surfaces))
        object.__setattr__(self, "live_enabled", False)
        object.__setattr__(self, "signer_reachable", False)
        object.__setattr__(self, "sender_reachable", False)
        object.__setattr__(self, "private_key_loading", False)
        object.__setattr__(self, "fake_success_permitted", False)
        object.__setattr__(self, "network_io_performed", False)

    @property
    def state(self) -> PaperVerticalPreflightState:
        if self.missing_surfaces or self.invalid_surfaces:
            return PaperVerticalPreflightState.BLOCKED
        return PaperVerticalPreflightState.READY

    @property
    def ready(self) -> bool:
        return self.state is PaperVerticalPreflightState.READY

    @property
    def reason_code(self) -> str:
        if self.invalid_surfaces and not self.missing_surfaces:
            return PR_A1_INVALID
        if self.missing_surfaces or self.invalid_surfaces:
            return PR_A1_UNWIRED
        return PR_A1_READY

    def dependency_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = [self.reason_code]
        reasons.extend(f"missing_{name}" for name in self.missing_surfaces)
        reasons.extend(f"invalid_{name}" for name in self.invalid_surfaces)
        return tuple(dict.fromkeys(reasons))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state": self.state.value,
            "ready": self.ready,
            "reason_code": self.reason_code,
            "config_fingerprint": self.config_fingerprint,
            "runtime_mode": self.runtime_mode,
            "required_surfaces": list(self.required_surfaces),
            "available_surfaces": dict(self.available_surfaces),
            "missing_surfaces": list(self.missing_surfaces),
            "invalid_surfaces": list(self.invalid_surfaces),
            "dependency_reasons": list(self.dependency_reasons()),
            "safety": {
                "live_enabled": self.live_enabled,
                "signer_reachable": self.signer_reachable,
                "sender_reachable": self.sender_reachable,
                "private_key_loading": self.private_key_loading,
                "fake_success_permitted": self.fake_success_permitted,
                "network_io_performed": self.network_io_performed,
            },
        }


def evaluate_paper_vertical_a1(
    config: Any,
    dependencies: Any,
) -> PaperVerticalPreflight:
    """Evaluate the current supported paper vertical without side effects."""

    missing = _string_tuple(dependencies.missing())
    invalid = _string_tuple(dependencies.invalid())
    return PaperVerticalPreflight(
        config_fingerprint=_safe_config_fingerprint(config),
        runtime_mode=_safe_runtime_mode(config),
        available_surfaces=_surface_flags(dependencies),
        missing_surfaces=missing,
        invalid_surfaces=invalid,
    )


def _surface_flags(dependencies: Any) -> dict[str, bool]:
    return {
        name: getattr(dependencies, name, None) is not None
        for name in REQUIRED_A1_SURFACES
    }


def _safe_config_fingerprint(config: Any) -> str:
    fingerprint = getattr(config, "fingerprint", None)
    if callable(fingerprint):
        return str(fingerprint())
    return "unavailable"


def _safe_runtime_mode(config: Any) -> str:
    runtime = getattr(config, "runtime", None)
    mode = getattr(runtime, "mode", None)
    value = getattr(mode, "value", mode)
    return str(value if value is not None else "unknown")


def _string_tuple(values: object) -> tuple[str, ...]:
    if values is None:
        return ()
    return tuple(str(value) for value in values)


__all__ = [
    "PR_A1_INVALID",
    "PR_A1_READY",
    "PR_A1_SCHEMA",
    "PR_A1_UNWIRED",
    "PaperVerticalPreflight",
    "PaperVerticalPreflightState",
    "REQUIRED_A1_SURFACES",
    "evaluate_paper_vertical_a1",
]
