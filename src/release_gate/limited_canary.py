"""PR-081 limited canary release evidence gate.

This is an offline review gate. It never enables live mode, imports a sender,
signs, submits, polls, resends, or mutates runtime state.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import re
from typing import Any

from src.shadow_soak.real_soak import RealShadowSoakReadiness, RealShadowSoakState

CANARY_RELEASE_SCHEMA_VERSION = "pr081.limited-canary-package.v1"
CANARY_RELEASE_RESULT_SCHEMA_VERSION = "pr081.limited-canary-readiness.v1"
PR078_SECURITY_EVIDENCE_NAME = "pr078.security-sbom-chaos-evidence"
PR080_SENDER_CONFORMANCE_NAME = "pr080.sender-conformance-evidence"
REQUIRED_ENABLEMENT_STEPS = (
    "release-owner-signoff",
    "security-owner-signoff",
    "operator-arm-command",
)
REQUIRED_SENDER_CONTROLS = (
    "exact_message_permit_enforced",
    "fake_ack_rejected",
    "unknown_restart_idempotent",
    "no_resend_under_ambiguity",
    "live_gate_closed_by_default",
    "one_outstanding_submission_enforced",
)
REQUIRED_LATCHES = (
    "loss-limit",
    "failure-limit",
    "stale-data",
    "ambiguity",
    "manual-kill-switch",
    "indeterminate-outcome",
)
REQUIRED_MANIFEST_HASHES = (
    "config_fingerprint_sha256",
    "contract_pins_sha256",
    "sbom_sha256",
    "image_digest_sha256",
    "image_signature_sha256",
    "pr078_security_evidence_sha256",
    "pr079_evidence_sha256",
    "pr080_sender_conformance_sha256",
    "rollback_plan_sha256",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class LimitedCanaryError(ValueError):
    """Raised when PR-081 evidence is malformed."""


class LimitedCanaryState(StrEnum):
    BLOCKED = "blocked"
    READY_FOR_MANUAL_CANARY_REVIEW = "ready-for-manual-canary-review"


def _sha256(value: str, field: str) -> str:
    lowered = str(value).lower()
    if not _SHA256_RE.fullmatch(lowered) or lowered == "0" * 64:
        raise LimitedCanaryError(f"{field} must be a non-placeholder sha256")
    return lowered


def _git_sha(value: str, field: str) -> str:
    lowered = str(value).lower()
    if not _GIT_SHA_RE.fullmatch(lowered) or lowered == "0" * 40:
        raise LimitedCanaryError(f"{field} must be a non-placeholder git SHA")
    return lowered


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise LimitedCanaryError(f"{field} must be timezone-aware")


def _positive(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LimitedCanaryError(f"{field} must be a positive integer")
    return value


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    name: str
    sha256: str
    source_commit: str
    passed: bool
    human_reviewed: bool
    reviewer: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise LimitedCanaryError("evidence.name is required")
        object.__setattr__(self, "sha256", _sha256(self.sha256, "evidence.sha256"))
        object.__setattr__(
            self,
            "source_commit",
            _git_sha(self.source_commit, "evidence.source_commit"),
        )
        if not isinstance(self.passed, bool) or not isinstance(
            self.human_reviewed, bool
        ):
            raise LimitedCanaryError("evidence flags must be boolean")
        if self.human_reviewed and not self.reviewer.strip():
            raise LimitedCanaryError("reviewed evidence must include reviewer")


@dataclass(frozen=True, slots=True)
class LimitedCanaryPackage:
    real_soak: RealShadowSoakReadiness
    pr078_security: EvidenceRef
    pr080_sender: EvidenceRef
    sender_controls: Mapping[str, bool]
    enablement_steps: Mapping[str, datetime]
    allowlist: Sequence[Mapping[str, Any]]
    limits: Mapping[str, int]
    latches: Mapping[str, Mapping[str, bool]]
    manifest: Mapping[str, str]
    assembled_at: datetime
    assembled_by: str
    default_live_enabled: bool
    manual_kill_switch_armed: bool
    post_trade_reconciliation_required: bool
    indeterminate_outcome_open: bool
    rollback_requires_code_change: bool
    schema_version: str = CANARY_RELEASE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CANARY_RELEASE_SCHEMA_VERSION:
            raise LimitedCanaryError("unsupported PR-081 package schema")
        _aware(self.assembled_at, "assembled_at")
        if not self.assembled_by.strip() or not self.allowlist:
            raise LimitedCanaryError("assembled_by and allowlist are required")
        _git_sha(self.manifest.get("code_commit", ""), "manifest.code_commit")
        for key in REQUIRED_MANIFEST_HASHES:
            _sha256(self.manifest.get(key, ""), f"manifest.{key}")


@dataclass(frozen=True, slots=True)
class LimitedCanaryReadiness:
    state: LimitedCanaryState
    manual_canary_review_ready: bool
    default_live_enabled: bool
    runtime_live_enabled: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    max_exposure_lamports: int
    max_outstanding_submissions: int
    schema_version: str = CANARY_RELEASE_RESULT_SCHEMA_VERSION


def evaluate_limited_canary(package: LimitedCanaryPackage) -> LimitedCanaryReadiness:
    blockers: list[str] = []
    warnings: list[str] = []

    def block(condition: bool, reason: str) -> None:
        if not condition:
            blockers.append(reason)

    block(
        package.real_soak.state == RealShadowSoakState.READY_FOR_RELEASE_EVIDENCE,
        "PR079_REAL_SOAK_NOT_RELEASE_READY",
    )
    block(package.real_soak.release_evidence_ready, "PR079_REAL_SOAK_BLOCKED")
    block(
        package.manifest["pr079_evidence_sha256"] == package.real_soak.package_sha256,
        "PR079_EVIDENCE_HASH_MISMATCH",
    )
    block(
        package.pr078_security.name == PR078_SECURITY_EVIDENCE_NAME,
        "PR078_WRONG_EVIDENCE_NAME",
    )
    block(package.pr078_security.passed, "PR078_SECURITY_EVIDENCE_BLOCKED")
    block(package.pr078_security.human_reviewed, "PR078_SECURITY_EVIDENCE_NOT_REVIEWED")
    block(
        package.manifest["pr078_security_evidence_sha256"]
        == package.pr078_security.sha256,
        "PR078_EVIDENCE_HASH_MISMATCH",
    )
    block(
        package.pr080_sender.name == PR080_SENDER_CONFORMANCE_NAME,
        "PR080_WRONG_EVIDENCE_NAME",
    )
    block(package.pr080_sender.passed, "PR080_SENDER_CONFORMANCE_BLOCKED")
    block(package.pr080_sender.human_reviewed, "PR080_SENDER_CONFORMANCE_NOT_REVIEWED")
    block(
        package.manifest["pr080_sender_conformance_sha256"]
        == package.pr080_sender.sha256,
        "PR080_EVIDENCE_HASH_MISMATCH",
    )
    for control in REQUIRED_SENDER_CONTROLS:
        block(
            package.sender_controls.get(control) is True,
            f"PR080_CONTROL_MISSING:{control}",
        )
    for step in REQUIRED_ENABLEMENT_STEPS:
        approved_at = package.enablement_steps.get(step)
        block(approved_at is not None, f"ENABLEMENT_STEP_MISSING:{step}")
        if approved_at is not None:
            _aware(approved_at, f"enablement.{step}")
            block(
                approved_at <= package.assembled_at,
                f"ENABLEMENT_STEP_AFTER_ASSEMBLY:{step}",
            )
    for latch_name in REQUIRED_LATCHES:
        latch = package.latches.get(latch_name)
        if latch is None:
            blockers.append(f"LATCH_MISSING:{latch_name}")
            continue
        block(latch.get("armed") is True, f"LATCH_NOT_ARMED:{latch_name}")
        block(latch.get("tested") is True, f"LATCH_NOT_TESTED:{latch_name}")
        block(
            latch.get("blocks_on_trigger") is True, f"LATCH_DOES_NOT_BLOCK:{latch_name}"
        )

    max_exposure = _positive(
        package.limits.get("max_exposure_lamports"), "limits.max_exposure_lamports"
    )
    max_outstanding = _positive(
        package.limits.get("max_outstanding_submissions"),
        "limits.max_outstanding_submissions",
    )
    protected_reserve = _positive(
        package.limits.get("protected_reserve_lamports"),
        "limits.protected_reserve_lamports",
    )
    block(max_outstanding == 1, "CANARY_REQUIRES_ONE_OUTSTANDING_SUBMISSION")
    for entry in package.allowlist:
        pair = str(entry.get("pair", ""))
        provider = str(entry.get("provider", ""))
        program_id = str(entry.get("program_id", ""))
        block(bool(pair), "ALLOWLIST_PAIR_MISSING")
        block(bool(provider), f"ALLOWLIST_PROVIDER_MISSING:{pair}")
        block(bool(program_id), f"ALLOWLIST_PROGRAM_MISSING:{pair}:{provider}")
        block(
            entry.get("reviewed") is True,
            f"ALLOWLIST_NOT_REVIEWED:{pair}:{provider}:{program_id}",
        )
        block(
            _positive(
                entry.get("max_exposure_lamports"), "allowlist.max_exposure_lamports"
            )
            <= max_exposure,
            f"ALLOWLIST_EXPOSURE_EXCEEDS_LIMIT:{pair}:{provider}:{program_id}",
        )
        block(
            _positive(
                entry.get("protected_reserve_lamports"),
                "allowlist.protected_reserve_lamports",
            )
            >= protected_reserve,
            f"ALLOWLIST_PROTECTED_RESERVE_TOO_LOW:{pair}:{provider}:{program_id}",
        )

    block(not package.default_live_enabled, "DEFAULT_LIVE_ENABLED")
    block(package.manual_kill_switch_armed, "MANUAL_KILL_SWITCH_NOT_ARMED")
    block(
        package.post_trade_reconciliation_required,
        "POST_TRADE_RECONCILIATION_NOT_REQUIRED",
    )
    block(not package.indeterminate_outcome_open, "INDETERMINATE_OUTCOME_OPEN")
    block(
        not package.rollback_requires_code_change,
        "ROLLBACK_TO_SHADOW_REQUIRES_CODE_CHANGE",
    )
    if package.limits.get("max_loss_lamports", 0) > max_exposure:
        warnings.append("LOSS_LIMIT_EXCEEDS_MAX_EXPOSURE_REVIEW_REQUIRED")

    unique_blockers = tuple(dict.fromkeys(blockers))
    ready = not unique_blockers
    return LimitedCanaryReadiness(
        state=(
            LimitedCanaryState.READY_FOR_MANUAL_CANARY_REVIEW
            if ready
            else LimitedCanaryState.BLOCKED
        ),
        manual_canary_review_ready=ready,
        default_live_enabled=False,
        runtime_live_enabled=False,
        blockers=unique_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
        max_exposure_lamports=max_exposure,
        max_outstanding_submissions=max_outstanding,
    )


__all__ = [
    "CANARY_RELEASE_RESULT_SCHEMA_VERSION",
    "CANARY_RELEASE_SCHEMA_VERSION",
    "PR078_SECURITY_EVIDENCE_NAME",
    "PR080_SENDER_CONFORMANCE_NAME",
    "REQUIRED_ENABLEMENT_STEPS",
    "REQUIRED_LATCHES",
    "REQUIRED_MANIFEST_HASHES",
    "REQUIRED_SENDER_CONTROLS",
    "EvidenceRef",
    "LimitedCanaryError",
    "LimitedCanaryPackage",
    "LimitedCanaryReadiness",
    "LimitedCanaryState",
    "evaluate_limited_canary",
]
