"""MPR-NEXT-06 shadow soak, submission finality and promotion evidence gate.

This module is intentionally offline, deterministic and fail-closed. It does not
submit transactions, load private keys, poll providers or enable live trading.
It models the artifact-only boundary required before a final promotion decision
can even be reviewed: MPR-29 continuous non-synthetic paper/shadow soak,
MPR-30 default-off signer/Jito/finality evidence, and MPR-31 consumption of
signed immutable artifacts rather than arbitrary in-memory DTOs.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Any

SCHEMA_VERSION = "mpr-next-06.shadow-soak-final-promotion.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_GATE_ARTIFACTS = frozenset(
    {
        "MPR-25",
        "MPR-26",
        "MPR-27",
        "MPR-28",
        "MPR-29",
        "MPR-30",
    }
)

REQUIRED_RELEASE_ARTIFACTS = frozenset(
    {
        "source_digest",
        "wheel_digest",
        "image_digest",
        "sbom_digest",
        "config_digest",
        "policy_digest",
        "provider_contracts_digest",
        "soak_report_digest",
        "crash_drill_digest",
        "backup_restore_digest",
        "secret_drill_digest",
        "finalized_economic_reconciliation_digest",
    }
)

REQUIRED_JITO_STATES = (
    "created",
    "submitted",
    "landed",
    "finalized",
    "reconciled",
)


class MPRNext06State(str, Enum):
    REVIEW_READY = "review_ready_default_off"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class EvidenceArtifact:
    artifact_id: str
    sha256: str
    signed: bool
    reviewed: bool
    immutable: bool
    synthetic: bool = False
    path: str = ""

    def __post_init__(self) -> None:
        _text(self.artifact_id, "artifact_id")
        _sha(self.sha256, "sha256")
        _strict_bool(self.signed, "signed")
        _strict_bool(self.reviewed, "reviewed")
        _strict_bool(self.immutable, "immutable")
        _strict_bool(self.synthetic, "synthetic")
        if self.path:
            _text(self.path, "path")


@dataclass(frozen=True)
class MPR29ShadowSoakEvidence:
    continuous_hours: int
    non_synthetic_provider_evidence: bool
    deterministic_replay: bool
    data_lineage_separated: bool
    provider_drift_artifacts_signed: bool
    slo_baseline_artifacts_signed: bool
    backup_restore_artifacts_signed: bool
    crash_recovery_artifacts_signed: bool
    unresolved_p0_incidents: int
    unresolved_p1_incidents: int
    soak_report_hash: str

    def __post_init__(self) -> None:
        _strict_int(self.continuous_hours, "continuous_hours")
        _strict_int(self.unresolved_p0_incidents, "unresolved_p0_incidents")
        _strict_int(self.unresolved_p1_incidents, "unresolved_p1_incidents")
        if self.continuous_hours < 0:
            raise ValueError("continuous_hours must be non-negative")
        if self.unresolved_p0_incidents < 0 or self.unresolved_p1_incidents < 0:
            raise ValueError("incident counts must be non-negative")
        for name in (
            "non_synthetic_provider_evidence",
            "deterministic_replay",
            "data_lineage_separated",
            "provider_drift_artifacts_signed",
            "slo_baseline_artifacts_signed",
            "backup_restore_artifacts_signed",
            "crash_recovery_artifacts_signed",
        ):
            _strict_bool(getattr(self, name), name)
        _sha(self.soak_report_hash, "soak_report_hash")


@dataclass(frozen=True)
class MPR30SubmissionFinalityEvidence:
    default_off: bool
    exact_message_hash: str
    permit_hash: str
    isolated_signer_evidence_hash: str
    finalized_reconciliation_hash: str
    jito_lifecycle_states: tuple[str, ...]
    ack_or_bundle_id_used_as_profit: bool = False
    unrestricted_live_enabled: bool = False
    unknown_outcome_auto_resend_enabled: bool = False

    def __post_init__(self) -> None:
        for name in (
            "default_off",
            "ack_or_bundle_id_used_as_profit",
            "unrestricted_live_enabled",
            "unknown_outcome_auto_resend_enabled",
        ):
            _strict_bool(getattr(self, name), name)
        for field_name in (
            "exact_message_hash",
            "permit_hash",
            "isolated_signer_evidence_hash",
            "finalized_reconciliation_hash",
        ):
            _sha(getattr(self, field_name), field_name)
        if not isinstance(self.jito_lifecycle_states, tuple):
            raise ValueError("jito_lifecycle_states must be a tuple")
        for state in self.jito_lifecycle_states:
            _text(state, "jito_lifecycle_state")


@dataclass(frozen=True)
class MPRNext06PromotionEvidence:
    artifacts: tuple[EvidenceArtifact, ...]
    shadow_soak: MPR29ShadowSoakEvidence
    submission_finality: MPR30SubmissionFinalityEvidence
    mpr31_loads_only_immutable_artifacts: bool
    production_debt_closes_only_with_signed_artifacts: bool
    final_promotion_default_off: bool

    def __post_init__(self) -> None:
        if not isinstance(self.artifacts, tuple):
            raise ValueError("artifacts must be a tuple")
        for artifact in self.artifacts:
            if not isinstance(artifact, EvidenceArtifact):
                raise ValueError("artifacts must contain EvidenceArtifact items")
        for name in (
            "mpr31_loads_only_immutable_artifacts",
            "production_debt_closes_only_with_signed_artifacts",
            "final_promotion_default_off",
        ):
            _strict_bool(getattr(self, name), name)


@dataclass(frozen=True)
class MPRNext06Blocker:
    code: str
    message: str


@dataclass(frozen=True)
class MPRNext06Report:
    schema_version: str
    state: MPRNext06State
    accepted: bool
    blockers: tuple[MPRNext06Blocker, ...]
    evidence_hash: str
    missing_gate_artifacts: tuple[str, ...]
    missing_release_artifacts: tuple[str, ...]
    unrestricted_live_allowed: bool
    production_ready_claimed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state": self.state.value,
            "accepted": self.accepted,
            "blockers": [blocker.__dict__ for blocker in self.blockers],
            "evidence_hash": self.evidence_hash,
            "missing_gate_artifacts": list(self.missing_gate_artifacts),
            "missing_release_artifacts": list(self.missing_release_artifacts),
            "unrestricted_live_allowed": self.unrestricted_live_allowed,
            "production_ready_claimed": self.production_ready_claimed,
        }


def evaluate_mpr_next_06(
    evidence: MPRNext06PromotionEvidence,
) -> MPRNext06Report:
    """Evaluate the MPR-NEXT-06 default-off final-promotion evidence boundary."""
    blockers: list[MPRNext06Blocker] = []
    artifact_ids = {artifact.artifact_id for artifact in evidence.artifacts}
    missing_gate = tuple(sorted(REQUIRED_GATE_ARTIFACTS - artifact_ids))
    missing_release = tuple(sorted(REQUIRED_RELEASE_ARTIFACTS - artifact_ids))
    if missing_gate:
        _add(blockers, "MPRNEXT06_MISSING_GATE_ARTIFACTS", ", ".join(missing_gate))
    if missing_release:
        _add(
            blockers,
            "MPRNEXT06_MISSING_RELEASE_ARTIFACTS",
            ", ".join(missing_release),
        )
    _validate_artifacts(evidence.artifacts, blockers)
    _validate_mpr29(evidence.shadow_soak, blockers)
    _validate_mpr30(evidence.submission_finality, blockers)
    if evidence.mpr31_loads_only_immutable_artifacts is not True:
        _add(
            blockers,
            "MPRNEXT06_MPR31_ACCEPTS_MEMORY_DTO",
            "MPR-31 must load signed immutable artifacts, not arbitrary DTOs",
        )
    if evidence.production_debt_closes_only_with_signed_artifacts is not True:
        _add(
            blockers,
            "MPRNEXT06_DEBT_CLOSURE_WITHOUT_ARTIFACTS",
            "production debt closure must require signed immutable artifacts",
        )
    if evidence.final_promotion_default_off is not True:
        _add(
            blockers,
            "MPRNEXT06_FINAL_PROMOTION_NOT_DEFAULT_OFF",
            "final promotion evidence must keep live/default promotion off",
        )
    unique = tuple(_dedupe(blockers))
    accepted = not unique
    return MPRNext06Report(
        schema_version=SCHEMA_VERSION,
        state=MPRNext06State.REVIEW_READY if accepted else MPRNext06State.BLOCKED,
        accepted=accepted,
        blockers=unique,
        evidence_hash=_hash_dataclass(evidence),
        missing_gate_artifacts=missing_gate,
        missing_release_artifacts=missing_release,
        unrestricted_live_allowed=False,
        production_ready_claimed=False,
    )


def sample_review_ready_evidence() -> MPRNext06PromotionEvidence:
    """Return a deterministic fully-populated review-ready sample."""
    artifacts = tuple(
        EvidenceArtifact(
            artifact_id=artifact_id,
            sha256=_fixture_hash(artifact_id),
            signed=True,
            reviewed=True,
            immutable=True,
            path=f"release_artifacts/current/{artifact_id}.json",
        )
        for artifact_id in sorted(REQUIRED_GATE_ARTIFACTS | REQUIRED_RELEASE_ARTIFACTS)
    )
    return MPRNext06PromotionEvidence(
        artifacts=artifacts,
        shadow_soak=MPR29ShadowSoakEvidence(
            continuous_hours=72,
            non_synthetic_provider_evidence=True,
            deterministic_replay=True,
            data_lineage_separated=True,
            provider_drift_artifacts_signed=True,
            slo_baseline_artifacts_signed=True,
            backup_restore_artifacts_signed=True,
            crash_recovery_artifacts_signed=True,
            unresolved_p0_incidents=0,
            unresolved_p1_incidents=0,
            soak_report_hash=_fixture_hash("soak"),
        ),
        submission_finality=MPR30SubmissionFinalityEvidence(
            default_off=True,
            exact_message_hash=_fixture_hash("message"),
            permit_hash=_fixture_hash("permit"),
            isolated_signer_evidence_hash=_fixture_hash("signer"),
            finalized_reconciliation_hash=_fixture_hash("reconciliation"),
            jito_lifecycle_states=REQUIRED_JITO_STATES,
        ),
        mpr31_loads_only_immutable_artifacts=True,
        production_debt_closes_only_with_signed_artifacts=True,
        final_promotion_default_off=True,
    )


def _validate_artifacts(
    artifacts: tuple[EvidenceArtifact, ...], blockers: list[MPRNext06Blocker]
) -> None:
    seen: set[str] = set()
    for artifact in artifacts:
        if artifact.artifact_id in seen:
            _add(
                blockers,
                "MPRNEXT06_DUPLICATE_ARTIFACT",
                f"duplicate artifact: {artifact.artifact_id}",
            )
        seen.add(artifact.artifact_id)
        if artifact.signed is not True:
            _add(
                blockers,
                "MPRNEXT06_UNSIGNED_ARTIFACT",
                f"artifact is unsigned: {artifact.artifact_id}",
            )
        if artifact.reviewed is not True:
            _add(
                blockers,
                "MPRNEXT06_UNREVIEWED_ARTIFACT",
                f"artifact is unreviewed: {artifact.artifact_id}",
            )
        if artifact.immutable is not True:
            _add(
                blockers,
                "MPRNEXT06_MUTABLE_ARTIFACT",
                f"artifact is mutable: {artifact.artifact_id}",
            )
        if artifact.synthetic:
            _add(
                blockers,
                "MPRNEXT06_SYNTHETIC_ARTIFACT",
                f"artifact is synthetic: {artifact.artifact_id}",
            )


def _validate_mpr29(
    evidence: MPR29ShadowSoakEvidence, blockers: list[MPRNext06Blocker]
) -> None:
    if evidence.continuous_hours < 72:
        _add(
            blockers,
            "MPRNEXT06_SOAK_TOO_SHORT",
            "MPR-29 soak must cover at least 72 continuous hours",
        )
    for name in (
        "non_synthetic_provider_evidence",
        "deterministic_replay",
        "data_lineage_separated",
        "provider_drift_artifacts_signed",
        "slo_baseline_artifacts_signed",
        "backup_restore_artifacts_signed",
        "crash_recovery_artifacts_signed",
    ):
        if getattr(evidence, name) is not True:
            _add(
                blockers,
                "MPRNEXT06_MPR29_EVIDENCE_INCOMPLETE",
                f"{name} is required",
            )
    if evidence.unresolved_p0_incidents:
        _add(
            blockers,
            "MPRNEXT06_UNRESOLVED_P0_INCIDENTS",
            str(evidence.unresolved_p0_incidents),
        )
    if evidence.unresolved_p1_incidents:
        _add(
            blockers,
            "MPRNEXT06_UNRESOLVED_P1_INCIDENTS",
            str(evidence.unresolved_p1_incidents),
        )


def _validate_mpr30(
    evidence: MPR30SubmissionFinalityEvidence, blockers: list[MPRNext06Blocker]
) -> None:
    if evidence.default_off is not True:
        _add(
            blockers,
            "MPRNEXT06_MPR30_NOT_DEFAULT_OFF",
            "submission/finality evidence must remain default-off",
        )
    missing_states = [
        state for state in REQUIRED_JITO_STATES if state not in evidence.jito_lifecycle_states
    ]
    if missing_states:
        _add(
            blockers,
            "MPRNEXT06_JITO_LIFECYCLE_INCOMPLETE",
            ", ".join(missing_states),
        )
    if evidence.ack_or_bundle_id_used_as_profit:
        _add(
            blockers,
            "MPRNEXT06_ACK_USED_AS_PROFIT",
            "ACK or bundle id is transport evidence only",
        )
    if evidence.unrestricted_live_enabled:
        _add(
            blockers,
            "MPRNEXT06_UNRESTRICTED_LIVE_FORBIDDEN",
            "MPR-NEXT-06 must not enable unrestricted live",
        )
    if evidence.unknown_outcome_auto_resend_enabled:
        _add(
            blockers,
            "MPRNEXT06_UNKNOWN_OUTCOME_AUTO_RESEND",
            "unknown outcomes must remain frozen/manual review",
        )


def _add(blockers: list[MPRNext06Blocker], code: str, message: str) -> None:
    blockers.append(MPRNext06Blocker(code=code, message=message))


def _dedupe(blockers: Iterable[MPRNext06Blocker]) -> Iterable[MPRNext06Blocker]:
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        key = (blocker.code, blocker.message)
        if key not in seen:
            seen.add(key)
            yield blocker


def _strict_int(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be a strict integer")


def _strict_bool(value: bool, field_name: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a strict bool")


def _sha(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be sha256 hex")


def _text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")


def _hash_dataclass(value: object) -> str:
    encoded = json.dumps(
        _normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize(value: object) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _normalize(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple | list):
        return [_normalize(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in value.items()}
    return value


def _fixture_hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()
