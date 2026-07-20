"""Fail-closed Pump PR-065 promotion evidence guard.

PR-065 is an optional promotion track. It must not turn the existing Pump
shadow adapter into a claimed RPC-conformant or soak-verified runtime unless
there is explicit evidence that the prior vertical is stable, live RPC
conformance passed, and shadow soak was reviewed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Any

from .adapter import PumpContractManifest

DEFAULT_MIN_SHADOW_SOAK_MINUTES = 72 * 60
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class PumpPromotionStatus(StrEnum):
    """Fail-closed promotion states for Pump PR-065."""

    BLOCKED = "blocked"
    READY_FOR_SHADOW_SOAK = "ready_for_shadow_soak"
    SHADOW_SOAK_VERIFIED = "shadow_soak_verified"


@dataclass(frozen=True, slots=True)
class PumpPromotionPolicy:
    """Minimum evidence thresholds before Pump shadow-soak claims are accepted."""

    minimum_soak_minutes: int = DEFAULT_MIN_SHADOW_SOAK_MINUTES
    minimum_candidates: int = 1


@dataclass(frozen=True, slots=True)
class PumpPromotionEvidence:
    """Offline evidence record for Pump RPC conformance and shadow soak."""

    first_vertical_stable: bool = False
    pr064_release_ready: bool = False
    rpc_conformance_passed: bool = False
    rpc_programs_verified: int = 0
    rpc_account_samples: int = 0
    shadow_soak_minutes: int = 0
    shadow_soak_candidates: int = 0
    shadow_soak_replay_deterministic: bool = False
    unexplained_failures: int = 0
    evidence_package_sha256: str = ""
    human_review_accepted: bool = False


@dataclass(frozen=True, slots=True)
class PumpPromotionReport:
    """Machine-readable Pump promotion decision that never enables live sending."""

    schema_version: str
    status: PumpPromotionStatus
    reason_codes: tuple[str, ...]
    required_families: int
    shadow_soak_allowed: bool
    shadow_soak_verified: bool
    live_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "reason_codes": list(self.reason_codes),
            "required_families": self.required_families,
            "shadow_soak_allowed": self.shadow_soak_allowed,
            "shadow_soak_verified": self.shadow_soak_verified,
            "live_allowed": self.live_allowed,
        }


def _manifest_blockers(manifest: PumpContractManifest) -> list[str]:
    blockers = [
        f"manifest_shadow_error:{error}" for error in manifest.shadow_errors()
    ]
    if manifest.live_capability != "DENIED_SHADOW_ONLY":
        blockers.append("manifest_live_capability_must_remain_denied")
    return blockers


def _rpc_conformance_blockers(
    evidence: PumpPromotionEvidence,
    *,
    required_families: int,
) -> list[str]:
    blockers: list[str] = []
    if not evidence.first_vertical_stable:
        blockers.append("first_vertical_stable_required")
    if not evidence.pr064_release_ready:
        blockers.append("pr064_release_ready_required")
    if not evidence.rpc_conformance_passed:
        blockers.append("pump_rpc_conformance_required")
    if evidence.rpc_programs_verified < required_families:
        blockers.append("pump_rpc_programs_verified_required")
    if evidence.rpc_account_samples < required_families:
        blockers.append("pump_rpc_account_samples_required")
    return blockers


def _shadow_soak_blockers(
    evidence: PumpPromotionEvidence,
    policy: PumpPromotionPolicy,
) -> list[str]:
    blockers: list[str] = []
    if evidence.shadow_soak_minutes < policy.minimum_soak_minutes:
        blockers.append("pump_shadow_soak_minutes_below_threshold")
    if evidence.shadow_soak_candidates < policy.minimum_candidates:
        blockers.append("pump_shadow_soak_candidates_required")
    if not evidence.shadow_soak_replay_deterministic:
        blockers.append("pump_shadow_soak_replay_required")
    if evidence.unexplained_failures != 0:
        blockers.append("pump_shadow_soak_unexplained_failures_present")
    if not _HEX64.fullmatch(evidence.evidence_package_sha256):
        blockers.append("pump_shadow_soak_evidence_package_sha256_required")
    if not evidence.human_review_accepted:
        blockers.append("pump_shadow_soak_human_review_required")
    return blockers


def evaluate_pump_promotion(
    evidence: PumpPromotionEvidence,
    *,
    manifest: PumpContractManifest | None = None,
    policy: PumpPromotionPolicy | None = None,
) -> PumpPromotionReport:
    """Evaluate PR-065 Pump promotion evidence without opening live execution.

    A successful report means the read-only shadow soak evidence is acceptable.
    It deliberately does not grant live capability; canary/live enablement remains
    owned by the separate release and human-control gates.
    """

    manifest = manifest or PumpContractManifest.load()
    policy = policy or PumpPromotionPolicy()
    required_families = len(manifest.specs)

    blockers = _manifest_blockers(manifest) + _rpc_conformance_blockers(
        evidence,
        required_families=required_families,
    )
    if blockers:
        return PumpPromotionReport(
            schema_version="pr065.pump-promotion.v1",
            status=PumpPromotionStatus.BLOCKED,
            reason_codes=tuple(blockers),
            required_families=required_families,
            shadow_soak_allowed=False,
            shadow_soak_verified=False,
        )

    soak_blockers = _shadow_soak_blockers(evidence, policy)
    if soak_blockers:
        return PumpPromotionReport(
            schema_version="pr065.pump-promotion.v1",
            status=PumpPromotionStatus.READY_FOR_SHADOW_SOAK,
            reason_codes=tuple(soak_blockers),
            required_families=required_families,
            shadow_soak_allowed=True,
            shadow_soak_verified=False,
        )

    return PumpPromotionReport(
        schema_version="pr065.pump-promotion.v1",
        status=PumpPromotionStatus.SHADOW_SOAK_VERIFIED,
        reason_codes=(),
        required_families=required_families,
        shadow_soak_allowed=True,
        shadow_soak_verified=True,
    )
