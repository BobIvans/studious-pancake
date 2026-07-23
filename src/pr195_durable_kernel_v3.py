"""PR-195 V3 durable runtime kernel acceptance contract.

This module is intentionally sender-free and offline.  It does not perform any
webhook, wallet, RPC, signer or submission side effect.  It gives PR-195 a
single typed contract for the hidden failure modes found in the V3 audit:
durable-before-ACK intake, atomic wallet reservations, serialized lifecycle
writes, outbox/DLQ ownership, safe restore and event-replay integrity.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
import hashlib
import json
from typing import Mapping, Self

SCHEMA_VERSION = "pr195.durable-kernel-v3.v1"


class PR195DurableKernelError(ValueError):
    """Raised when a PR-195 durable-kernel claim is malformed."""


@dataclass(frozen=True, slots=True)
class PR195Requirement:
    """One reviewable PR-195 invariant required before runtime promotion."""

    requirement_id: str
    finding_ids: tuple[str, ...]
    description: str
    required_claim_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PR195DurableKernelClaim:
    """Boolean evidence claim for the PR-195 durable kernel boundary."""

    one_database_authority: bool = False
    webhook_ack_after_durable_commit: bool = False
    webhook_schema_validated_before_ack: bool = False
    webhook_shutdown_drains_or_requeues: bool = False
    chain_identity_excludes_payload_hash: bool = False
    capital_reservation_serializable: bool = False
    wallet_revision_fencing: bool = False
    negative_headroom_latches: bool = False
    lifecycle_writes_serialized: bool = False
    submission_intent_checks_rowcount: bool = False
    monotonic_lease_renewal: bool = False
    outbox_has_retry_ceiling_and_dlq: bool = False
    restore_uses_validate_then_atomic_rename: bool = False
    integrity_replays_event_projection: bool = False
    submission_receipts_unique_per_attempt: bool = False
    restore_requires_authenticated_manifest: bool = False
    evidence_refs: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> Self:
        """Build a strictly validated claim from JSON-like input."""

        allowed = {field.name for field in fields(cls)}
        unknown = sorted(set(payload).difference(allowed))
        if unknown:
            raise PR195DurableKernelError(
                "unknown PR-195 durable-kernel claim fields: " + ", ".join(unknown)
            )

        values: dict[str, object] = {}
        for field in fields(cls):
            raw = payload.get(field.name, getattr(cls(), field.name))
            if field.name == "evidence_refs":
                values[field.name] = _string_tuple(raw, field=field.name)
            elif not isinstance(raw, bool):
                raise PR195DurableKernelError(
                    f"claim field {field.name!r} must be boolean"
                )
            else:
                values[field.name] = raw
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class PR195RequirementResult:
    """Evaluation result for one PR-195 requirement."""

    requirement_id: str
    finding_ids: tuple[str, ...]
    satisfied: bool
    missing_claim_fields: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "requirement_id": self.requirement_id,
            "finding_ids": list(self.finding_ids),
            "satisfied": self.satisfied,
            "missing_claim_fields": list(self.missing_claim_fields),
        }


@dataclass(frozen=True, slots=True)
class PR195DurableKernelReport:
    """Deterministic offline evidence for the PR-195 durable kernel gate."""

    schema_version: str
    ready: bool
    reason_codes: tuple[str, ...]
    requirement_results: tuple[PR195RequirementResult, ...]
    claim_hash: str
    live_enabled: bool = False
    sender_or_signer_enabled: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "ready": self.ready,
            "reason_codes": list(self.reason_codes),
            "live_enabled": self.live_enabled,
            "sender_or_signer_enabled": self.sender_or_signer_enabled,
            "claim_hash": self.claim_hash,
            "requirement_results": [
                item.to_dict() for item in self.requirement_results
            ],
        }

    def to_json(self) -> str:
        """Serialize the report deterministically for CI artifacts."""

        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


REQUIREMENTS: tuple[PR195Requirement, ...] = (
    PR195Requirement(
        requirement_id="DURABLE_BEFORE_ACK_WEBHOOK_INTAKE",
        finding_ids=(
            "F-140",
            "F-141",
            "F-142",
            "F-143",
            "F-145",
            "F-146",
            "F-147",
        ),
        description="Webhook intake cannot acknowledge before durable receipt.",
        required_claim_fields=(
            "webhook_ack_after_durable_commit",
            "webhook_schema_validated_before_ack",
            "webhook_shutdown_drains_or_requeues",
        ),
    ),
    PR195Requirement(
        requirement_id="IMMUTABLE_CHAIN_EVENT_IDENTITY",
        finding_ids=("F-148",),
        description="Exactly-once webhook identity excludes mutable payload hash.",
        required_claim_fields=("chain_identity_excludes_payload_hash",),
    ),
    PR195Requirement(
        requirement_id="ATOMIC_WALLET_CAPITAL_AUTHORITY",
        finding_ids=("F-149", "F-150", "F-151", "F-152"),
        description="Wallet reservations are serializable and latch on inconsistency.",
        required_claim_fields=(
            "one_database_authority",
            "capital_reservation_serializable",
            "wallet_revision_fencing",
            "negative_headroom_latches",
        ),
    ),
    PR195Requirement(
        requirement_id="SERIALIZED_LIFECYCLE_AND_LEASES",
        finding_ids=("F-153", "F-154", "F-155"),
        description="Lifecycle writes, revision checks and leases are fenced.",
        required_claim_fields=(
            "lifecycle_writes_serialized",
            "submission_intent_checks_rowcount",
            "monotonic_lease_renewal",
        ),
    ),
    PR195Requirement(
        requirement_id="OWNED_OUTBOX_RETRY_AND_DLQ",
        finding_ids=("F-156",),
        description="Outbox poison messages reach a typed DLQ instead of looping.",
        required_claim_fields=("outbox_has_retry_ceiling_and_dlq",),
    ),
    PR195Requirement(
        requirement_id="ATOMIC_AUTHENTICATED_RESTORE",
        finding_ids=("F-157", "F-160"),
        description="Restore validates a signed manifest before atomic promotion.",
        required_claim_fields=(
            "restore_uses_validate_then_atomic_rename",
            "restore_requires_authenticated_manifest",
        ),
    ),
    PR195Requirement(
        requirement_id="REPLAY_VERIFIED_MATERIALIZED_STATE",
        finding_ids=("F-158", "F-159"),
        description="Event replay reproduces state and receipt ownership exactly.",
        required_claim_fields=(
            "integrity_replays_event_projection",
            "submission_receipts_unique_per_attempt",
        ),
    ),
)


def evaluate_pr195_durable_kernel(
    claim: PR195DurableKernelClaim,
    *,
    live_enabled: bool = False,
    sender_or_signer_enabled: bool = False,
) -> PR195DurableKernelReport:
    """Evaluate the PR-195 V3 durable-kernel acceptance gate."""

    results: list[PR195RequirementResult] = []
    reason_codes: list[str] = []

    for requirement in REQUIREMENTS:
        missing = tuple(
            field_name
            for field_name in requirement.required_claim_fields
            if not bool(getattr(claim, field_name))
        )
        satisfied = not missing
        if not satisfied:
            reason_codes.append(f"{requirement.requirement_id}:MISSING_PROOF")
        results.append(
            PR195RequirementResult(
                requirement_id=requirement.requirement_id,
                finding_ids=requirement.finding_ids,
                satisfied=satisfied,
                missing_claim_fields=missing,
            )
        )

    if live_enabled:
        reason_codes.append("LIVE_ENABLEMENT_NOT_ALLOWED_IN_PR195")
    if sender_or_signer_enabled:
        reason_codes.append("SENDER_OR_SIGNER_NOT_ALLOWED_IN_PR195")

    ready = not reason_codes
    return PR195DurableKernelReport(
        schema_version=SCHEMA_VERSION,
        ready=ready,
        reason_codes=tuple(reason_codes),
        requirement_results=tuple(results),
        claim_hash=_claim_hash(claim),
        live_enabled=live_enabled,
        sender_or_signer_enabled=sender_or_signer_enabled,
    )


def complete_offline_claim(*, evidence_refs: tuple[str, ...]) -> PR195DurableKernelClaim:
    """Return a complete sender-free claim for focused tests and examples."""

    if not evidence_refs:
        raise PR195DurableKernelError("complete PR-195 claim requires evidence_refs")
    return PR195DurableKernelClaim(
        one_database_authority=True,
        webhook_ack_after_durable_commit=True,
        webhook_schema_validated_before_ack=True,
        webhook_shutdown_drains_or_requeues=True,
        chain_identity_excludes_payload_hash=True,
        capital_reservation_serializable=True,
        wallet_revision_fencing=True,
        negative_headroom_latches=True,
        lifecycle_writes_serialized=True,
        submission_intent_checks_rowcount=True,
        monotonic_lease_renewal=True,
        outbox_has_retry_ceiling_and_dlq=True,
        restore_uses_validate_then_atomic_rename=True,
        integrity_replays_event_projection=True,
        submission_receipts_unique_per_attempt=True,
        restore_requires_authenticated_manifest=True,
        evidence_refs=evidence_refs,
    )


def _claim_hash(claim: PR195DurableKernelClaim) -> str:
    payload = {
        field.name: list(value) if isinstance(value, tuple) else value
        for field in fields(claim)
        for value in (getattr(claim, field.name),)
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _string_tuple(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise PR195DurableKernelError(f"claim field {field!r} must be a string list")
    result = tuple(value)
    if not all(isinstance(item, str) and item for item in result):
        raise PR195DurableKernelError(f"claim field {field!r} must contain strings")
    return result


def report_from_mapping(payload: Mapping[str, object]) -> PR195DurableKernelReport:
    """Convenience entrypoint for JSON/YAML-driven CI checks."""

    return evaluate_pr195_durable_kernel(PR195DurableKernelClaim.from_mapping(payload))


def render_report_json(payload: Mapping[str, object]) -> str:
    """Render a deterministic PR-195 durable-kernel report from a mapping."""

    return report_from_mapping(payload).to_json()
