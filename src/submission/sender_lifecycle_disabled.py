"""PR-093 canonical sender lifecycle evidence gate, still disabled.

This module consumes review evidence for the canonical sender lifecycle after the
PR-080 admission boundary.  It is intentionally an offline package evaluator: it
does not build a sender, does not sign, does not submit, does not poll, and keeps
all supported runtime commands unable to submit transactions.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import re
from typing import Any

from .lifecycle_integration import CANONICAL_SUBMISSION_OUTBOX_TOPIC
from .permit_bound import SubmissionState, TransportKind

SENDER_LIFECYCLE_SCHEMA_VERSION = "pr093.sender-lifecycle-disabled-package.v1"
SENDER_LIFECYCLE_RESULT_SCHEMA_VERSION = "pr093.sender-lifecycle-disabled.v1"
PR093_COMPILE_TIME_SUBMISSION_ENABLED = False
PR093_SUPPORTED_COMMAND_SUBMISSION_ENABLED = False
CANONICAL_SENDER_OWNER = "src.submission.permit_bound.Sender"

REQUIRED_PR093_EVIDENCE = (
    "pr086.protocol-aware-rpc-jito-transport",
    "pr087.production-package-boundary",
    "pr091.security-signer-boundary",
    "pr092.real-shadow-soak",
)

REQUIRED_LIFECYCLE_CONTROLS = (
    "permit_bound_exact_message",
    "exactly_one_jito_tip",
    "ack_not_landing_proof",
    "status_polling_can_prove_landing",
    "failed_expired_unknown_reconcile",
    "durable_ambiguity_no_resend",
    "outbox_persistence_integrated",
    "signer_boundary_isolated",
    "compile_config_hard_deny",
)

REQUIRED_STATUS_OUTCOMES = (
    SubmissionState.ACCEPTED.value,
    SubmissionState.LANDED.value,
    SubmissionState.FAILED.value,
    SubmissionState.EXPIRED.value,
    SubmissionState.UNKNOWN.value,
)

REQUIRED_TRANSPORTS = (
    TransportKind.RPC.value,
    TransportKind.JITO_SINGLE.value,
    TransportKind.JITO_BUNDLE.value,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class SenderLifecycleDisabledError(ValueError):
    """Raised when PR-093 evidence is malformed."""


class SenderLifecycleDisabledState(StrEnum):
    """Fail-closed PR-093 readiness state."""

    BLOCKED = "blocked"
    READY_DISABLED_FOR_REVIEW = "ready-disabled-for-review"


def _sha256(value: str, field: str) -> str:
    lowered = str(value).lower()
    if not _SHA256_RE.fullmatch(lowered) or lowered == "0" * 64:
        raise SenderLifecycleDisabledError(f"{field} must be a non-placeholder sha256")
    return lowered


def _git_sha(value: str, field: str) -> str:
    lowered = str(value).lower()
    if not _GIT_SHA_RE.fullmatch(lowered) or lowered == "0" * 40:
        raise SenderLifecycleDisabledError(f"{field} must be a non-placeholder git SHA")
    return lowered


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SenderLifecycleDisabledError(f"{field} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class SenderLifecycleEvidenceRef:
    """Digest-pinned upstream evidence consumed by PR-093."""

    name: str
    sha256: str
    source_commit: str
    passed: bool
    human_reviewed: bool
    reviewer: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise SenderLifecycleDisabledError("evidence.name is required")
        object.__setattr__(self, "sha256", _sha256(self.sha256, "evidence.sha256"))
        object.__setattr__(
            self,
            "source_commit",
            _git_sha(self.source_commit, "evidence.source_commit"),
        )
        if not isinstance(self.passed, bool) or not isinstance(
            self.human_reviewed, bool
        ):
            raise SenderLifecycleDisabledError("evidence flags must be boolean")
        if self.human_reviewed and not self.reviewer.strip():
            raise SenderLifecycleDisabledError(
                "reviewed evidence must include reviewer"
            )


@dataclass(frozen=True, slots=True)
class CanonicalSenderLifecycleDisabledPackage:
    """Review package proving sender integration is present but not executable."""

    evidence: tuple[SenderLifecycleEvidenceRef, ...]
    lifecycle_controls: Mapping[str, bool]
    status_outcomes: Mapping[str, bool]
    transport_contracts: Mapping[str, bool]
    sender_owner: str
    outbox_topic: str
    assembled_at: datetime
    assembled_by: str
    compile_time_submission_enabled: bool
    config_submission_enabled: bool
    supported_command_submission_enabled: bool
    automatic_resend_enabled: bool
    signer_boundary_reviewed: bool
    schema_version: str = SENDER_LIFECYCLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SENDER_LIFECYCLE_SCHEMA_VERSION:
            raise SenderLifecycleDisabledError("unsupported PR-093 package schema")
        _aware(self.assembled_at, "assembled_at")
        if not self.assembled_by.strip():
            raise SenderLifecycleDisabledError("assembled_by is required")
        names = [item.name for item in self.evidence]
        if len(names) != len(set(names)):
            raise SenderLifecycleDisabledError("evidence names must be unique")


@dataclass(frozen=True, slots=True)
class CanonicalSenderLifecycleDisabledReadiness:
    """PR-093 result: reviewable sender lifecycle, runtime still disabled."""

    state: SenderLifecycleDisabledState
    sender_lifecycle_review_ready: bool
    live_allowed: bool
    runtime_submission_enabled: bool
    supported_command_can_submit: bool
    automatic_resend_enabled: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    schema_version: str = SENDER_LIFECYCLE_RESULT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state": self.state.value,
            "sender_lifecycle_review_ready": self.sender_lifecycle_review_ready,
            "live_allowed": self.live_allowed,
            "runtime_submission_enabled": self.runtime_submission_enabled,
            "supported_command_can_submit": self.supported_command_can_submit,
            "automatic_resend_enabled": self.automatic_resend_enabled,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }


def evaluate_canonical_sender_lifecycle_disabled(
    package: CanonicalSenderLifecycleDisabledPackage,
) -> CanonicalSenderLifecycleDisabledReadiness:
    """Evaluate PR-093 evidence without enabling any submission path."""

    blockers: list[str] = []
    warnings: list[str] = []

    def block(condition: bool, reason: str) -> None:
        if not condition:
            blockers.append(reason)

    evidence_by_name = {item.name: item for item in package.evidence}
    for name in REQUIRED_PR093_EVIDENCE:
        item = evidence_by_name.get(name)
        if item is None:
            blockers.append(f"EVIDENCE_MISSING:{name}")
            continue
        block(item.passed, f"EVIDENCE_NOT_PASSED:{name}")
        block(item.human_reviewed, f"EVIDENCE_NOT_REVIEWED:{name}")

    for control in REQUIRED_LIFECYCLE_CONTROLS:
        block(
            package.lifecycle_controls.get(control) is True,
            f"LIFECYCLE_CONTROL_MISSING:{control}",
        )

    for outcome in REQUIRED_STATUS_OUTCOMES:
        block(
            package.status_outcomes.get(outcome) is True,
            f"STATUS_OUTCOME_NOT_COVERED:{outcome}",
        )

    for transport in REQUIRED_TRANSPORTS:
        block(
            package.transport_contracts.get(transport) is True,
            f"TRANSPORT_CONTRACT_NOT_COVERED:{transport}",
        )

    block(
        package.sender_owner == CANONICAL_SENDER_OWNER,
        "CANONICAL_SENDER_OWNER_MISMATCH",
    )
    block(
        package.outbox_topic == CANONICAL_SUBMISSION_OUTBOX_TOPIC,
        "CANONICAL_OUTBOX_TOPIC_MISMATCH",
    )
    block(
        not PR093_COMPILE_TIME_SUBMISSION_ENABLED,
        "PR093_COMPILE_TIME_CONSTANT_ENABLED",
    )
    block(
        not PR093_SUPPORTED_COMMAND_SUBMISSION_ENABLED,
        "PR093_SUPPORTED_COMMAND_CONSTANT_ENABLED",
    )
    block(
        not package.compile_time_submission_enabled,
        "COMPILE_TIME_SUBMISSION_ENABLED",
    )
    block(not package.config_submission_enabled, "CONFIG_SUBMISSION_ENABLED")
    block(
        not package.supported_command_submission_enabled,
        "SUPPORTED_COMMAND_CAN_SUBMIT",
    )
    block(not package.automatic_resend_enabled, "AUTOMATIC_RESEND_ENABLED")
    block(package.signer_boundary_reviewed, "SIGNER_BOUNDARY_NOT_REVIEWED")

    if package.transport_contracts.get(TransportKind.JITO_SINGLE.value) is True:
        block(
            package.lifecycle_controls.get("exactly_one_jito_tip") is True,
            "JITO_SINGLE_WITHOUT_EXACT_TIP_CONTROL",
        )
    if package.transport_contracts.get(TransportKind.JITO_BUNDLE.value) is True:
        block(
            package.lifecycle_controls.get("exactly_one_jito_tip") is True,
            "JITO_BUNDLE_WITHOUT_EXACT_TIP_CONTROL",
        )

    if package.lifecycle_controls.get("compile_config_hard_deny") is not True:
        warnings.append("compile/config hard deny evidence should be reviewed first")

    unique_blockers = tuple(dict.fromkeys(blockers))
    ready = not unique_blockers
    return CanonicalSenderLifecycleDisabledReadiness(
        state=(
            SenderLifecycleDisabledState.READY_DISABLED_FOR_REVIEW
            if ready
            else SenderLifecycleDisabledState.BLOCKED
        ),
        sender_lifecycle_review_ready=ready,
        live_allowed=False,
        runtime_submission_enabled=False,
        supported_command_can_submit=False,
        automatic_resend_enabled=False,
        blockers=unique_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
    )


__all__ = [
    "CANONICAL_SENDER_OWNER",
    "PR093_COMPILE_TIME_SUBMISSION_ENABLED",
    "PR093_SUPPORTED_COMMAND_SUBMISSION_ENABLED",
    "REQUIRED_LIFECYCLE_CONTROLS",
    "REQUIRED_PR093_EVIDENCE",
    "REQUIRED_STATUS_OUTCOMES",
    "REQUIRED_TRANSPORTS",
    "SENDER_LIFECYCLE_RESULT_SCHEMA_VERSION",
    "SENDER_LIFECYCLE_SCHEMA_VERSION",
    "CanonicalSenderLifecycleDisabledPackage",
    "CanonicalSenderLifecycleDisabledReadiness",
    "SenderLifecycleDisabledError",
    "SenderLifecycleDisabledState",
    "SenderLifecycleEvidenceRef",
    "evaluate_canonical_sender_lifecycle_disabled",
]
