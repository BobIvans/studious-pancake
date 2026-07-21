"""PR-106 canonical sender lifecycle integration gate, still disabled.

This module is a review/evidence boundary on top of PR-080 and PR-093. It never
constructs a live sender, never imports signer implementations, never sends RPC
or Jito requests, and never turns a supported command into a submission path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Any

from .lifecycle_integration import CANONICAL_SUBMISSION_OUTBOX_TOPIC
from .sender_lifecycle_disabled import (
    CANONICAL_SENDER_OWNER,
    CanonicalSenderLifecycleDisabledReadiness,
)

PR106_SCHEMA_VERSION = "pr106.canonical-sender-lifecycle-disabled.v1"
PR106_RESULT_SCHEMA_VERSION = "pr106.canonical-sender-lifecycle-result.v1"
PR106_COMPILE_TIME_LIVE_ENABLED = False
PR106_SUPPORTED_COMMAND_SUBMISSION_ENABLED = False

REQUIRED_PR106_UPSTREAM_EVIDENCE: tuple[str, ...] = (
    "pr104.security-sbom-provenance-chaos-package",
    "pr105.real-shadow-soak-harness-72h",
    "pr093.sender-lifecycle-disabled-review",
)

REQUIRED_PR106_LIFECYCLE_CONTROLS: tuple[str, ...] = (
    "one_canonical_sender_protocol",
    "evidence_bound_rpc_jito_transports",
    "exact_permit_message_payload_identity",
    "isolated_signer_boundary",
    "exactly_one_jito_tip",
    "ack_not_landing_proof",
    "signature_and_bundle_status_polling",
    "durable_unknown_state",
    "no_resend_under_ambiguity",
    "lifecycle_outbox_recovery",
    "compile_config_hard_deny",
    "supported_commands_live_disabled",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class PR106CanonicalSenderLifecycleError(ValueError):
    """Raised when PR-106 sender lifecycle evidence is malformed."""


class PR106CanonicalSenderLifecycleState(StrEnum):
    """Fail-closed PR-106 sender lifecycle state."""

    BLOCKED = "blocked"
    READY_DISABLED_FOR_REVIEW = "ready-disabled-for-review"


@dataclass(frozen=True, slots=True)
class PR106UpstreamEvidenceRef:
    """Digest-pinned upstream evidence required before PR-106 can pass."""

    name: str
    sha256: str
    source_commit: str
    passed: bool
    human_reviewed: bool
    reviewer: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise PR106CanonicalSenderLifecycleError(
                "upstream evidence name required",
            )
        object.__setattr__(
            self,
            "sha256",
            _require_sha256(self.sha256, "sha256"),
        )
        object.__setattr__(
            self,
            "source_commit",
            _require_git_sha(self.source_commit, "source_commit"),
        )
        if not isinstance(self.passed, bool):
            raise PR106CanonicalSenderLifecycleError("passed must be boolean")
        if not isinstance(self.human_reviewed, bool):
            raise PR106CanonicalSenderLifecycleError(
                "human_reviewed must be boolean",
            )
        if self.human_reviewed and not self.reviewer.strip():
            raise PR106CanonicalSenderLifecycleError(
                "reviewed evidence must include reviewer",
            )


@dataclass(frozen=True, slots=True)
class PR106CanonicalSenderLifecyclePackage:
    """Review package for canonical sender lifecycle while submission is disabled."""

    upstream_evidence: tuple[PR106UpstreamEvidenceRef, ...]
    pr093_readiness: CanonicalSenderLifecycleDisabledReadiness
    lifecycle_controls: Mapping[str, bool]
    sender_owner: str
    outbox_topic: str
    compile_time_live_enabled: bool
    config_live_enabled: bool
    supported_command_submission_enabled: bool
    automatic_resend_enabled: bool
    signer_import_path: str | None = None
    schema_version: str = PR106_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PR106_SCHEMA_VERSION:
            raise PR106CanonicalSenderLifecycleError(
                "unsupported PR-106 package schema",
            )
        if not isinstance(
            self.pr093_readiness,
            CanonicalSenderLifecycleDisabledReadiness,
        ):
            raise PR106CanonicalSenderLifecycleError(
                "pr093_readiness must be CanonicalSenderLifecycleDisabledReadiness",
            )
        names = [item.name for item in self.upstream_evidence]
        if len(names) != len(set(names)):
            raise PR106CanonicalSenderLifecycleError(
                "upstream evidence names must be unique",
            )
        for field_name in (
            "compile_time_live_enabled",
            "config_live_enabled",
            "supported_command_submission_enabled",
            "automatic_resend_enabled",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise PR106CanonicalSenderLifecycleError(
                    f"{field_name} must be boolean",
                )
        for name, value in self.lifecycle_controls.items():
            if value is not True and value is not False:
                raise PR106CanonicalSenderLifecycleError(
                    f"lifecycle control must be boolean: {name}",
                )


@dataclass(frozen=True, slots=True)
class PR106CanonicalSenderLifecycleReadiness:
    """PR-106 result: canonical lifecycle reviewable, live still impossible."""

    state: PR106CanonicalSenderLifecycleState
    lifecycle_review_ready: bool
    live_allowed: bool
    runtime_submission_enabled: bool
    supported_command_can_submit: bool
    automatic_resend_enabled: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    schema_version: str = PR106_RESULT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state": self.state.value,
            "lifecycle_review_ready": self.lifecycle_review_ready,
            "live_allowed": self.live_allowed,
            "runtime_submission_enabled": self.runtime_submission_enabled,
            "supported_command_can_submit": self.supported_command_can_submit,
            "automatic_resend_enabled": self.automatic_resend_enabled,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }


def evaluate_pr106_canonical_sender_lifecycle(
    package: PR106CanonicalSenderLifecyclePackage,
) -> PR106CanonicalSenderLifecycleReadiness:
    """Evaluate PR-106 evidence without enabling any live submission path."""

    blockers: list[str] = []
    warnings: list[str] = []

    def block(condition: bool, reason: str) -> None:
        if not condition:
            blockers.append(reason)

    upstream_by_name = {item.name: item for item in package.upstream_evidence}
    for name in REQUIRED_PR106_UPSTREAM_EVIDENCE:
        evidence = upstream_by_name.get(name)
        if evidence is None:
            blockers.append(f"UPSTREAM_EVIDENCE_MISSING:{name}")
            continue
        block(evidence.passed, f"UPSTREAM_EVIDENCE_NOT_PASSED:{name}")
        block(
            evidence.human_reviewed,
            f"UPSTREAM_EVIDENCE_NOT_REVIEWED:{name}",
        )

    pr093 = package.pr093_readiness
    block(pr093.sender_lifecycle_review_ready, "PR093_LIFECYCLE_NOT_REVIEW_READY")
    block(not pr093.live_allowed, "PR093_LIVE_ALLOWED")
    block(not pr093.runtime_submission_enabled, "PR093_RUNTIME_SUBMISSION_ENABLED")
    block(
        not pr093.supported_command_can_submit,
        "PR093_SUPPORTED_COMMAND_CAN_SUBMIT",
    )
    block(not pr093.automatic_resend_enabled, "PR093_AUTOMATIC_RESEND_ENABLED")
    for reason in pr093.blockers:
        blockers.append(f"PR093:{reason}")

    for control in REQUIRED_PR106_LIFECYCLE_CONTROLS:
        block(
            package.lifecycle_controls.get(control) is True,
            f"PR106_LIFECYCLE_CONTROL_MISSING:{control}",
        )

    block(
        package.sender_owner == CANONICAL_SENDER_OWNER,
        "CANONICAL_SENDER_OWNER_MISMATCH",
    )
    block(
        package.outbox_topic == CANONICAL_SUBMISSION_OUTBOX_TOPIC,
        "CANONICAL_OUTBOX_TOPIC_MISMATCH",
    )
    block(not PR106_COMPILE_TIME_LIVE_ENABLED, "PR106_COMPILE_TIME_CONSTANT_ENABLED")
    block(
        not PR106_SUPPORTED_COMMAND_SUBMISSION_ENABLED,
        "PR106_SUPPORTED_COMMAND_CONSTANT_ENABLED",
    )
    block(not package.compile_time_live_enabled, "COMPILE_TIME_LIVE_ENABLED")
    block(not package.config_live_enabled, "CONFIG_LIVE_ENABLED")
    block(
        not package.supported_command_submission_enabled,
        "SUPPORTED_COMMAND_CAN_SUBMIT",
    )
    block(not package.automatic_resend_enabled, "AUTOMATIC_RESEND_ENABLED")
    block(package.signer_import_path is None, "SIGNER_IMPORT_PATH_PRESENT")

    if package.lifecycle_controls.get("ack_not_landing_proof") is not True:
        warnings.append("transport ack must stay below landed state")
    if package.lifecycle_controls.get("no_resend_under_ambiguity") is not True:
        warnings.append("ambiguous outcomes must reconcile without resend")

    unique_blockers = tuple(dict.fromkeys(blockers))
    ready = not unique_blockers
    return PR106CanonicalSenderLifecycleReadiness(
        state=(
            PR106CanonicalSenderLifecycleState.READY_DISABLED_FOR_REVIEW
            if ready
            else PR106CanonicalSenderLifecycleState.BLOCKED
        ),
        lifecycle_review_ready=ready,
        live_allowed=False,
        runtime_submission_enabled=False,
        supported_command_can_submit=False,
        automatic_resend_enabled=False,
        blockers=unique_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _require_sha256(value: str, field: str) -> str:
    lowered = str(value).lower()
    if not _SHA256_RE.fullmatch(lowered) or lowered == "0" * 64:
        raise PR106CanonicalSenderLifecycleError(
            f"{field} must be a non-placeholder sha256",
        )
    return lowered


def _require_git_sha(value: str, field: str) -> str:
    lowered = str(value).lower()
    if not _GIT_SHA_RE.fullmatch(lowered) or lowered == "0" * 40:
        raise PR106CanonicalSenderLifecycleError(
            f"{field} must be a non-placeholder git SHA",
        )
    return lowered


__all__ = [
    "PR106_COMPILE_TIME_LIVE_ENABLED",
    "PR106_RESULT_SCHEMA_VERSION",
    "PR106_SCHEMA_VERSION",
    "PR106_SUPPORTED_COMMAND_SUBMISSION_ENABLED",
    "REQUIRED_PR106_LIFECYCLE_CONTROLS",
    "REQUIRED_PR106_UPSTREAM_EVIDENCE",
    "PR106CanonicalSenderLifecycleError",
    "PR106CanonicalSenderLifecyclePackage",
    "PR106CanonicalSenderLifecycleReadiness",
    "PR106CanonicalSenderLifecycleState",
    "PR106UpstreamEvidenceRef",
    "evaluate_pr106_canonical_sender_lifecycle",
]
