"""Executable fail-closed preflight for MEGA-PR D.

The preflight does not run soak, contact providers, sign, submit, or enable live.
It only evaluates evidence generated elsewhere and refuses readiness by default.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Mapping


SCHEMA = "mega-pr-d.release-soak-canary-preflight.v1"


class PrdError(ValueError):
    """Invalid PR D preflight evidence."""


class Blocker(StrEnum):
    SOAK_MISSING = "soak_missing"
    SOAK_TOO_SHORT = "soak_too_short"
    SYNTHETIC_SOAK = "synthetic_soak"
    SENDER_REACHABLE = "sender_reachable"
    RELEASE_ARTIFACT_MISSING = "release_artifact_missing"
    RELEASE_HARDENING_MISSING = "release_hardening_missing"
    SOURCE_WHEEL_PARITY_MISSING = "source_wheel_parity_missing"
    RESERVATION_LEAK = "reservation_leak"
    RECONCILIATION_BACKLOG = "reconciliation_backlog"
    CANARY_LIMIT_MISSING = "canary_limit_missing"
    CANARY_REVIEW_MISSING = "canary_review_missing"
    ROLLBACK_REHEARSAL_MISSING = "rollback_rehearsal_missing"
    LIVE_REQUESTED = "live_requested"


@dataclass(frozen=True, slots=True)
class SoakEvidence:
    duration_hours: int
    synthetic_rows: int
    sender_reachable: bool
    wheel_hash: str
    image_digest: str
    policy_hash: str
    reservation_leak_lamports: int = 0
    reconciliation_backlog: int = 0
    restart_recovery_proven: bool = False
    resource_limits_proven: bool = False

    def __post_init__(self) -> None:
        for field in (
            "duration_hours",
            "synthetic_rows",
            "reservation_leak_lamports",
            "reconciliation_backlog",
        ):
            _int(getattr(self, field), field)
        for field in ("wheel_hash", "image_digest", "policy_hash"):
            _text(getattr(self, field), field)


@dataclass(frozen=True, slots=True)
class ReleaseEvidence:
    wheel_hash: str
    image_digest: str
    sbom_hash: str
    provenance_hash: str
    source_wheel_parity: bool
    non_root: bool
    read_only_rootfs: bool
    caps_dropped: bool
    no_new_privileges: bool
    egress_allowlist: bool
    secrets_externalized: bool

    def __post_init__(self) -> None:
        for field in ("wheel_hash", "image_digest", "sbom_hash", "provenance_hash"):
            _text(getattr(self, field), field)


@dataclass(frozen=True, slots=True)
class CanaryPolicy:
    live_requested: bool
    sender_reachable: bool
    wallet_lamports: int
    max_notional_lamports: int
    max_transactions_per_day: int
    max_daily_loss_lamports: int
    signer_expiry_seconds: int
    second_reviewer: bool
    kill_switch_rehearsed: bool
    rollback_rehearsed: bool

    def __post_init__(self) -> None:
        for field in (
            "wallet_lamports",
            "max_notional_lamports",
            "max_transactions_per_day",
            "max_daily_loss_lamports",
            "signer_expiry_seconds",
        ):
            _int(getattr(self, field), field)


@dataclass(frozen=True, slots=True)
class PreflightReport:
    blockers: tuple[Blocker, ...]
    live_enabled: bool = False
    manual_review_required: bool = True

    @property
    def review_ready(self) -> bool:
        return not self.blockers

    def to_json(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "review_ready": self.review_ready,
            "blockers": [item.value for item in self.blockers],
            "live_enabled": self.live_enabled,
            "manual_review_required": self.manual_review_required,
        }


def evaluate_prd_preflight(
    *,
    soak: SoakEvidence | None,
    release: ReleaseEvidence | None,
    canary: CanaryPolicy | None,
    minimum_soak_hours: int = 72,
) -> PreflightReport:
    _int(minimum_soak_hours, "minimum_soak_hours", lower=1)
    blockers: list[Blocker] = []

    if soak is None:
        blockers.append(Blocker.SOAK_MISSING)
    else:
        if soak.duration_hours < minimum_soak_hours:
            blockers.append(Blocker.SOAK_TOO_SHORT)
        if soak.synthetic_rows:
            blockers.append(Blocker.SYNTHETIC_SOAK)
        if soak.sender_reachable:
            blockers.append(Blocker.SENDER_REACHABLE)
        if soak.reservation_leak_lamports:
            blockers.append(Blocker.RESERVATION_LEAK)
        if soak.reconciliation_backlog:
            blockers.append(Blocker.RECONCILIATION_BACKLOG)
        if not soak.restart_recovery_proven or not soak.resource_limits_proven:
            blockers.append(Blocker.SOAK_TOO_SHORT)

    if release is None:
        blockers.append(Blocker.RELEASE_ARTIFACT_MISSING)
    else:
        if soak and (
            release.wheel_hash != soak.wheel_hash
            or release.image_digest != soak.image_digest
        ):
            blockers.append(Blocker.RELEASE_ARTIFACT_MISSING)
        if not release.source_wheel_parity:
            blockers.append(Blocker.SOURCE_WHEEL_PARITY_MISSING)
        if not all(
            (
                release.non_root,
                release.read_only_rootfs,
                release.caps_dropped,
                release.no_new_privileges,
                release.egress_allowlist,
                release.secrets_externalized,
            )
        ):
            blockers.append(Blocker.RELEASE_HARDENING_MISSING)

    if canary is None:
        blockers.append(Blocker.CANARY_LIMIT_MISSING)
    else:
        if canary.live_requested:
            blockers.append(Blocker.LIVE_REQUESTED)
        if canary.sender_reachable:
            blockers.append(Blocker.SENDER_REACHABLE)
        if not all(
            (
                canary.wallet_lamports,
                canary.max_notional_lamports,
                canary.max_transactions_per_day,
                canary.max_daily_loss_lamports,
                canary.signer_expiry_seconds,
            )
        ):
            blockers.append(Blocker.CANARY_LIMIT_MISSING)
        if not canary.second_reviewer:
            blockers.append(Blocker.CANARY_REVIEW_MISSING)
        if not canary.kill_switch_rehearsed or not canary.rollback_rehearsed:
            blockers.append(Blocker.ROLLBACK_REHEARSAL_MISSING)

    return PreflightReport(tuple(dict.fromkeys(blockers)))


def default_blocked_preflight() -> PreflightReport:
    return evaluate_prd_preflight(soak=None, release=None, canary=None)


def report_to_json(report: PreflightReport) -> str:
    return json.dumps(report.to_json(), sort_keys=True, separators=(",", ":"))


def report_from_json(payload: Mapping[str, object]) -> PreflightReport:
    if payload.get("schema") != SCHEMA:
        raise PrdError("unsupported PR D preflight schema")
    blockers = tuple(Blocker(item) for item in payload.get("blockers", ()))
    return PreflightReport(blockers=blockers, live_enabled=False)


def _text(value: str, field: str) -> None:
    if not value.strip():
        raise PrdError(f"{field} is required")


def _int(value: int, field: str, *, lower: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PrdError(f"{field} must be integer")
    if value < lower:
        raise PrdError(f"{field} below minimum")


__all__ = [
    "Blocker",
    "CanaryPolicy",
    "PreflightReport",
    "PrdError",
    "ReleaseEvidence",
    "SCHEMA",
    "SoakEvidence",
    "default_blocked_preflight",
    "evaluate_prd_preflight",
    "report_from_json",
    "report_to_json",
]
