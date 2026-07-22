"""PR-142 paper/live readiness evidence gate.

This module is an additive, side-effect-free contract that prevents review
reports from calling the bot paper-ready or live-canary-ready unless the
required upstream safety evidence is present, reviewed, fresh, and non-live.

It does not call providers, RPC, Jito, signers, senders, or runtime execution
paths. It only evaluates explicit evidence descriptors supplied by operators
or release tooling.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping, Sequence


class ReadinessMode(StrEnum):
    PAPER = "paper"
    LIVE_CANARY = "live_canary"


class EvidenceStatus(StrEnum):
    PRESENT = "present"
    MISSING = "missing"
    STALE = "stale"
    FAILED = "failed"
    UNREVIEWED = "unreviewed"
    LIVE_ENABLED = "live_enabled"


class ReadinessDecision(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class ReadinessReason(StrEnum):
    MISSING_EVIDENCE = "missing_evidence"
    STALE_EVIDENCE = "stale_evidence"
    FAILED_EVIDENCE = "failed_evidence"
    UNREVIEWED_EVIDENCE = "unreviewed_evidence"
    LIVE_ENABLED_BEFORE_GATE = "live_enabled_before_gate"
    PLACEHOLDER_HASH = "placeholder_hash"


PAPER_REQUIRED_GATES: tuple[str, ...] = (
    "pr128_compute_fee_finalization",
    "pr129_blockhash_alt_fork_revalidation",
    "pr131_ata_wsol_rent_lifecycle",
    "pr132_observability_integrity",
    "pr137_cpi_call_graph",
    "pr140_data_lineage",
)

LIVE_CANARY_REQUIRED_GATES: tuple[str, ...] = (
    *PAPER_REQUIRED_GATES,
    "pr130_jito_unbundling_protection",
    "pr133_hermetic_artifacts",
    "pr134_production_sandbox",
    "pr136_rooted_independent_rpc",
    "pr138_finalized_settlement",
    "pr139_scheduled_drift",
    "pr105_actual_shadow_soak_72h",
    "isolated_signer_review",
    "reviewed_release_package",
)


@dataclass(frozen=True, slots=True)
class ReadinessEvidence:
    gate: str
    status: EvidenceStatus
    evidence_hash: str
    reviewed_by_human: bool
    observed_at_slot: int | None = None
    max_age_slots: int | None = None
    live_enabled: bool = False
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.gate:
            raise ValueError("gate must be non-empty")
        if self.observed_at_slot is not None and self.observed_at_slot < 0:
            raise ValueError("observed_at_slot must be non-negative")
        if self.max_age_slots is not None and self.max_age_slots < 0:
            raise ValueError("max_age_slots must be non-negative")


@dataclass(frozen=True, slots=True)
class ReadinessFailure:
    gate: str
    reason: ReadinessReason
    detail: str


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    mode: ReadinessMode
    decision: ReadinessDecision
    failures: tuple[ReadinessFailure, ...]
    evidence_hash: str
    required_gates: tuple[str, ...]
    observed_gates: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.decision is ReadinessDecision.READY

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "decision": self.decision.value,
            "ready": self.ready,
            "evidence_hash": self.evidence_hash,
            "required_gates": list(self.required_gates),
            "observed_gates": list(self.observed_gates),
            "failures": [
                {
                    "gate": failure.gate,
                    "reason": failure.reason.value,
                    "detail": failure.detail,
                }
                for failure in self.failures
            ],
        }


@dataclass(frozen=True, slots=True)
class ReadinessPolicy:
    mode: ReadinessMode
    current_slot: int | None = None
    allow_placeholder_hashes: bool = False
    required_gates: tuple[str, ...] | None = None
    optional_gates: tuple[str, ...] = field(default_factory=tuple)

    def resolved_required_gates(self) -> tuple[str, ...]:
        if self.required_gates is not None:
            return self.required_gates
        if self.mode is ReadinessMode.PAPER:
            return PAPER_REQUIRED_GATES
        return LIVE_CANARY_REQUIRED_GATES


_PLACEHOLDER_HASHES = frozenset(
    {
        "",
        "0",
        "0" * 64,
        "1" * 64,
        "deadbeef",
        "placeholder",
        "todo",
        "pending",
        "not_applicable",
    }
)


def evaluate_readiness(
    evidence: Sequence[ReadinessEvidence],
    policy: ReadinessPolicy,
) -> ReadinessReport:
    """Evaluate paper/live readiness from explicit upstream evidence."""

    by_gate = _dedupe_latest(evidence)
    failures: list[ReadinessFailure] = []
    required = policy.resolved_required_gates()

    for gate in required:
        item = by_gate.get(gate)
        if item is None:
            failures.append(
                ReadinessFailure(
                    gate,
                    ReadinessReason.MISSING_EVIDENCE,
                    "required readiness evidence is missing",
                )
            )
            continue
        failures.extend(_validate_item(item, policy))

    for item in by_gate.values():
        if item.live_enabled:
            failures.append(
                ReadinessFailure(
                    item.gate,
                    ReadinessReason.LIVE_ENABLED_BEFORE_GATE,
                    "readiness evidence must not enable live behavior",
                )
            )

    decision = ReadinessDecision.READY if not failures else ReadinessDecision.BLOCKED
    return ReadinessReport(
        mode=policy.mode,
        decision=decision,
        failures=tuple(failures),
        evidence_hash=_report_hash(evidence, policy, required),
        required_gates=required,
        observed_gates=tuple(sorted(by_gate)),
    )


def _dedupe_latest(
    evidence: Sequence[ReadinessEvidence],
) -> dict[str, ReadinessEvidence]:
    by_gate: dict[str, ReadinessEvidence] = {}
    for item in evidence:
        previous = by_gate.get(item.gate)
        if previous is None:
            by_gate[item.gate] = item
            continue
        previous_slot = -1 if previous.observed_at_slot is None else previous.observed_at_slot
        item_slot = -1 if item.observed_at_slot is None else item.observed_at_slot
        if item_slot >= previous_slot:
            by_gate[item.gate] = item
    return by_gate


def _validate_item(
    item: ReadinessEvidence,
    policy: ReadinessPolicy,
) -> tuple[ReadinessFailure, ...]:
    failures: list[ReadinessFailure] = []

    if item.status is EvidenceStatus.MISSING:
        failures.append(
            ReadinessFailure(
                item.gate,
                ReadinessReason.MISSING_EVIDENCE,
                "gate reported missing evidence",
            )
        )
    elif item.status is EvidenceStatus.STALE:
        failures.append(
            ReadinessFailure(
                item.gate,
                ReadinessReason.STALE_EVIDENCE,
                "gate reported stale evidence",
            )
        )
    elif item.status is EvidenceStatus.FAILED:
        failures.append(
            ReadinessFailure(
                item.gate,
                ReadinessReason.FAILED_EVIDENCE,
                "gate reported failed evidence",
            )
        )
    elif item.status is EvidenceStatus.UNREVIEWED:
        failures.append(
            ReadinessFailure(
                item.gate,
                ReadinessReason.UNREVIEWED_EVIDENCE,
                "gate evidence has not been reviewed",
            )
        )
    elif item.status is EvidenceStatus.LIVE_ENABLED:
        failures.append(
            ReadinessFailure(
                item.gate,
                ReadinessReason.LIVE_ENABLED_BEFORE_GATE,
                "gate attempts to enable live before readiness approval",
            )
        )

    if not item.reviewed_by_human:
        failures.append(
            ReadinessFailure(
                item.gate,
                ReadinessReason.UNREVIEWED_EVIDENCE,
                "human review is required for readiness evidence",
            )
        )

    if not policy.allow_placeholder_hashes and _looks_placeholder_hash(item.evidence_hash):
        failures.append(
            ReadinessFailure(
                item.gate,
                ReadinessReason.PLACEHOLDER_HASH,
                "evidence hash is missing or placeholder-shaped",
            )
        )

    if (
        policy.current_slot is not None
        and item.observed_at_slot is not None
        and item.max_age_slots is not None
        and policy.current_slot - item.observed_at_slot > item.max_age_slots
    ):
        failures.append(
            ReadinessFailure(
                item.gate,
                ReadinessReason.STALE_EVIDENCE,
                "evidence exceeded its slot freshness budget",
            )
        )

    return tuple(failures)


def _looks_placeholder_hash(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in _PLACEHOLDER_HASHES:
        return True
    if len(normalized) < 32:
        return True
    try:
        int(normalized, 16)
    except ValueError:
        return False
    return len(set(normalized)) == 1


def _report_hash(
    evidence: Sequence[ReadinessEvidence],
    policy: ReadinessPolicy,
    required: tuple[str, ...],
) -> str:
    payload = {
        "mode": policy.mode.value,
        "current_slot": policy.current_slot,
        "required_gates": list(required),
        "optional_gates": list(policy.optional_gates),
        "evidence": [
            {
                "gate": item.gate,
                "status": item.status.value,
                "evidence_hash": item.evidence_hash,
                "reviewed_by_human": item.reviewed_by_human,
                "observed_at_slot": item.observed_at_slot,
                "max_age_slots": item.max_age_slots,
                "live_enabled": item.live_enabled,
                "notes": list(item.notes),
            }
            for item in sorted(evidence, key=lambda row: row.gate)
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def release_claim(*, report: ReadinessReport, claim: str) -> Mapping[str, object]:
    """Return a stable claim payload that never overstates readiness."""

    allowed = report.ready
    if "live" in claim.lower() and report.mode is not ReadinessMode.LIVE_CANARY:
        allowed = False
    return {
        "claim": claim,
        "mode": report.mode.value,
        "allowed": allowed,
        "decision": report.decision.value,
        "evidence_hash": report.evidence_hash,
        "blockers": [failure.reason.value for failure in report.failures],
    }


__all__ = [
    "EvidenceStatus",
    "LIVE_CANARY_REQUIRED_GATES",
    "PAPER_REQUIRED_GATES",
    "ReadinessDecision",
    "ReadinessEvidence",
    "ReadinessFailure",
    "ReadinessMode",
    "ReadinessPolicy",
    "ReadinessReason",
    "ReadinessReport",
    "evaluate_readiness",
    "release_claim",
]
