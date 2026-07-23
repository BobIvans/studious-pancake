"""NEW-MEGA-PR-01 architectural retirement gate for legacy authorities.

The gate is side-effect free: it inspects explicit importability evidence and
returns blockers instead of importing legacy runtime modules. Production release
gates can consume this report before allowing a canonical paper/runtime
promotion.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import importlib.util
from typing import Iterable

RETIREMENT_GATE_SCHEMA = "new-mega-pr-01.legacy-retirement-gate.v1"

RETIRED_AUTHORITY_MODULES: tuple[str, ...] = (
    "src.strategy.runtime",
    "src.durability.unified_authority_pr02",
    "src.submission.live_permit",
    "src.live_boundary.mega_pr03_live_authorization_gate",
)


class RetirementState(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class RetiredAuthorityEvidence:
    module: str
    importable: bool
    production_packaged: bool = True
    direct_invocation_blocked: bool = False

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.importable and self.production_packaged:
            blockers.append(f"retired_authority_importable:{self.module}")
        if self.production_packaged and not self.direct_invocation_blocked:
            blockers.append(f"retired_authority_direct_invocation_not_blocked:{self.module}")
        return tuple(blockers)

    def to_dict(self) -> dict[str, object]:
        return {
            "module": self.module,
            "importable": self.importable,
            "production_packaged": self.production_packaged,
            "direct_invocation_blocked": self.direct_invocation_blocked,
            "blockers": list(self.blockers()),
        }


@dataclass(frozen=True, slots=True)
class RetirementGateReport:
    evidence: tuple[RetiredAuthorityEvidence, ...]
    schema_version: str = RETIREMENT_GATE_SCHEMA
    live_enabled: bool = False
    signer_loaded: bool = False
    sender_loaded: bool = False

    @property
    def blockers(self) -> tuple[str, ...]:
        rows: list[str] = []
        for item in self.evidence:
            rows.extend(item.blockers())
        return tuple(dict.fromkeys(rows))

    @property
    def state(self) -> RetirementState:
        return RetirementState.BLOCKED if self.blockers else RetirementState.READY

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "state": self.state.value,
            "blockers": list(self.blockers),
            "evidence": [item.to_dict() for item in self.evidence],
            "safety": {
                "live_enabled": self.live_enabled,
                "signer_loaded": self.signer_loaded,
                "sender_loaded": self.sender_loaded,
            },
        }


def collect_importability_evidence(
    modules: Iterable[str] = RETIRED_AUTHORITY_MODULES,
) -> tuple[RetiredAuthorityEvidence, ...]:
    """Collect importability without importing legacy modules."""

    return tuple(
        RetiredAuthorityEvidence(
            module=module,
            importable=importlib.util.find_spec(module) is not None,
            production_packaged=True,
            direct_invocation_blocked=False,
        )
        for module in modules
    )


def evaluate_legacy_retirement(
    evidence: Iterable[RetiredAuthorityEvidence] | None = None,
) -> RetirementGateReport:
    return RetirementGateReport(
        tuple(evidence) if evidence is not None else collect_importability_evidence()
    )


__all__ = [
    "RETIRED_AUTHORITY_MODULES",
    "RETIREMENT_GATE_SCHEMA",
    "RetiredAuthorityEvidence",
    "RetirementGateReport",
    "RetirementState",
    "collect_importability_evidence",
    "evaluate_legacy_retirement",
]
