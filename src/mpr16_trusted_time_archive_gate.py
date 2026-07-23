"""MPR-16 trusted time, anti-replay management and immutable archive gate.

Side-effect free acceptance boundary for V7 MPR-16. It never talks to host time
services, archive backends, RPC, signers or senders.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import math
import re
from typing import Iterable, Mapping, Sequence


SCHEMA_VERSION = "mpr16.trusted-time-management-archive-gate.v1"
REQUIRED_FINDINGS: tuple[str, ...] = tuple(f"F-{number}" for number in range(350, 361))
HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")


class MPR16GateState(str, Enum):
    READY_FOR_OPERATIONAL_CUTOVER_INTEGRATION = "ready_for_operational_cutover_integration"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class TimeQualificationEvidence:
    source_id: str
    source_status: str
    status_authenticated: bool
    host_timesync_attestation_hash: str
    policy_hash: str
    uncertainty_ns: int
    max_uncertainty_ns: int
    sample_count: int
    min_required_samples: int
    consecutive_consistent_samples: int
    first_sample_sensitive_operations_blocked: bool


@dataclass(frozen=True)
class ProcessGenerationEvidence:
    boot_id_hash: str
    process_incarnation_hash: str
    previous_generation: int
    current_generation: int
    durable_allocator_enabled: bool
    exclusive_startup_lease_acquired: bool
    cas_generation_allocated: bool


@dataclass(frozen=True)
class ManagementSnapshotEvidence:
    release_id: str
    policy_hash: str
    evidence_head_hash: str
    process_boot_id_hash: str
    runtime_generation: int
    heartbeat_sequence: int
    previous_accepted_sequence: int
    snapshot_hash: str
    previous_accepted_snapshot_hash: str
    mac_verified: bool
    readiness_cross_bound_to_outer_identity: bool
    evaluated_at_ns: int
    expires_at_ns: int
    trusted_now_ns: int
    durable_high_water_updated: bool


@dataclass(frozen=True)
class ArchiveLeaseEvidence:
    claim_id: str
    exporter_id: str
    lease_generation: int
    monotonic_deadline_ns: int
    trusted_utc_expires_at_ns: int
    renewable: bool
    cas_heartbeat_enabled: bool
    fence_validated_before_read: bool
    fence_validated_before_write: bool
    fence_validated_before_commit: bool
    stale_exporter_rejected_before_artifact_write: bool


@dataclass(frozen=True)
class RemoteArchiveReceipt:
    archive_name: str
    region: str
    object_version: str
    receipt_hash: str
    worm_locked: bool
    retention_until_ns: int


@dataclass(frozen=True)
class ArchiveDurabilityEvidence:
    archive_policy_hash: str
    mandatory_archive_names: tuple[str, ...]
    remote_receipts: tuple[RemoteArchiveReceipt, ...]
    append_only_ack_events: bool
    mutable_ack_upsert_disabled: bool
    conflicting_second_ack_quarantined: bool
    terminal_ack_immutable: bool
    deterministic_remote_fsm: bool
    local_committed_state_separate_from_authoritative: bool
    promotion_requires_remote_quorum: bool
    manifest_authoritative_only_after_remote_quorum: bool
    latest_projection_replay_derived: bool


@dataclass(frozen=True)
class MPR16OperationalEvidence:
    covered_findings: tuple[str, ...]
    release_artifact_hash: str
    time: TimeQualificationEvidence
    process_generation: ProcessGenerationEvidence
    management_snapshot: ManagementSnapshotEvidence
    archive_lease: ArchiveLeaseEvidence
    archive_durability: ArchiveDurabilityEvidence
    transaction_signer_requested: bool = False
    sender_requested: bool = False
    live_execution_requested: bool = False


@dataclass(frozen=True)
class MPR16Violation:
    code: str
    message: str


@dataclass(frozen=True)
class MPR16Report:
    schema_version: str
    state: MPR16GateState
    blockers: tuple[MPR16Violation, ...]
    evidence_hash: str
    required_findings: tuple[str, ...]
    transaction_signer_allowed: bool
    sender_allowed: bool
    live_execution_allowed: bool


def evaluate_mpr16_operational_evidence(evidence: MPR16OperationalEvidence) -> MPR16Report:
    blockers: list[MPR16Violation] = []
    _validate_covered_findings(evidence.covered_findings, blockers)
    _validate_hash("release_artifact_hash", evidence.release_artifact_hash, blockers)
    _validate_no_live_boundary(evidence, blockers)
    _validate_time(evidence.time, blockers)
    _validate_process_generation(evidence.process_generation, blockers)
    _validate_management_snapshot(evidence.management_snapshot, blockers)
    _validate_archive_lease(evidence.archive_lease, blockers)
    _validate_archive_durability(evidence.archive_durability, blockers)

    unique = tuple(_dedupe(blockers))
    state = (
        MPR16GateState.BLOCKED
        if unique
        else MPR16GateState.READY_FOR_OPERATIONAL_CUTOVER_INTEGRATION
    )
    return MPR16Report(
        schema_version=SCHEMA_VERSION,
        state=state,
        blockers=unique,
        evidence_hash=_stable_hash(evidence),
        required_findings=REQUIRED_FINDINGS,
        transaction_signer_allowed=False,
        sender_allowed=False,
        live_execution_allowed=False,
    )


def _validate_covered_findings(
    covered_findings: Sequence[str], blockers: list[MPR16Violation]
) -> None:
    covered = set(covered_findings)
    missing = [finding for finding in REQUIRED_FINDINGS if finding not in covered]
    if missing:
        _add(blockers, "MPR16_FINDINGS_MISSING", f"missing findings: {missing}")
    unknown = sorted(covered - set(REQUIRED_FINDINGS))
    if unknown:
        _add(blockers, "MPR16_UNKNOWN_FINDINGS", f"unknown findings: {unknown}")


def _validate_no_live_boundary(
    evidence: MPR16OperationalEvidence, blockers: list[MPR16Violation]
) -> None:
    if evidence.transaction_signer_requested:
        _add(blockers, "MPR16_SIGNER_REQUESTED", "MPR-16 gate cannot enable signing")
    if evidence.sender_requested:
        _add(blockers, "MPR16_SENDER_REQUESTED", "MPR-16 gate cannot enable sender submission")
    if evidence.live_execution_requested:
        _add(blockers, "MPR16_LIVE_REQUESTED", "MPR-16 gate cannot enable live execution")


def _validate_time(
    time_evidence: TimeQualificationEvidence, blockers: list[MPR16Violation]
) -> None:
    if not time_evidence.source_id:
        _add(blockers, "MPR16_TIME_SOURCE_MISSING", "time source id is required")
    if time_evidence.source_status != "SYNCHRONIZED":
        _add(blockers, "MPR16_TIME_NOT_SYNCHRONIZED", "time source must be synchronized")
    if not time_evidence.status_authenticated:
        _add(
            blockers,
            "MPR16_TIME_STATUS_UNAUTHENTICATED",
            "production time status must come from authenticated host-timesync evidence",
        )
    _validate_hash(
        "host_timesync_attestation_hash",
        time_evidence.host_timesync_attestation_hash,
        blockers,
    )
    _validate_hash("time_policy_hash", time_evidence.policy_hash, blockers)
    for field_name, value in asdict(time_evidence).items():
        if field_name.endswith("_ns") or field_name in {
            "sample_count",
            "min_required_samples",
            "consecutive_consistent_samples",
        }:
            if not _is_nonnegative_int(value):
                _add(blockers, "MPR16_BAD_TIME_FIELD", f"{field_name} must be a non-negative integer")
    if time_evidence.uncertainty_ns > time_evidence.max_uncertainty_ns:
        _add(
            blockers,
            "MPR16_TIME_UNCERTAINTY_TOO_HIGH",
            "sensitive operations require uncertainty within policy threshold",
        )
    if time_evidence.sample_count < time_evidence.min_required_samples:
        _add(
            blockers,
            "MPR16_TIME_SAMPLE_COUNT_TOO_LOW",
            "startup must collect enough authenticated time samples",
        )
    if time_evidence.consecutive_consistent_samples < time_evidence.min_required_samples:
        _add(
            blockers,
            "MPR16_TIME_CONSISTENCY_TOO_LOW",
            "startup must prove consecutive consistent time samples",
        )
    if not time_evidence.first_sample_sensitive_operations_blocked:
        _add(
            blockers,
            "MPR16_FIRST_SAMPLE_BYPASS",
            "first startup sample cannot authorize sensitive expiry decisions",
        )


def _validate_process_generation(
    generation: ProcessGenerationEvidence, blockers: list[MPR16Violation]
) -> None:
    _validate_hash("boot_id_hash", generation.boot_id_hash, blockers)
    _validate_hash("process_incarnation_hash", generation.process_incarnation_hash, blockers)
    for field_name in ("previous_generation", "current_generation"):
        if not _is_positive_int(getattr(generation, field_name)):
            _add(blockers, "MPR16_BAD_PROCESS_GENERATION", f"{field_name} must be positive integer")
    if generation.current_generation <= generation.previous_generation:
        _add(
            blockers,
            "MPR16_PROCESS_GENERATION_NOT_INCREASING",
            "each process incarnation must receive a strictly increasing durable generation",
        )
    if not generation.durable_allocator_enabled:
        _add(blockers, "MPR16_NO_DURABLE_GENERATION_ALLOCATOR", "process generation must be allocated durably")
    if not generation.exclusive_startup_lease_acquired:
        _add(blockers, "MPR16_NO_STARTUP_LEASE", "startup must acquire exclusive process lease")
    if not generation.cas_generation_allocated:
        _add(blockers, "MPR16_NO_CAS_GENERATION", "generation allocation must be CAS-protected")


def _validate_management_snapshot(
    snapshot: ManagementSnapshotEvidence, blockers: list[MPR16Violation]
) -> None:
    for field_name in (
        "policy_hash",
        "evidence_head_hash",
        "process_boot_id_hash",
        "snapshot_hash",
        "previous_accepted_snapshot_hash",
    ):
        _validate_hash(field_name, getattr(snapshot, field_name), blockers)
    if not snapshot.release_id:
        _add(blockers, "MPR16_RELEASE_ID_MISSING", "management snapshot must include release id")
    for field_name in (
        "runtime_generation",
        "heartbeat_sequence",
        "previous_accepted_sequence",
        "evaluated_at_ns",
        "expires_at_ns",
        "trusted_now_ns",
    ):
        if not _is_nonnegative_int(getattr(snapshot, field_name)):
            _add(blockers, "MPR16_BAD_SNAPSHOT_FIELD", f"{field_name} must be non-negative integer")
    if not snapshot.mac_verified:
        _add(blockers, "MPR16_SNAPSHOT_MAC_UNVERIFIED", "management snapshot MAC/signature must verify")
    if not snapshot.readiness_cross_bound_to_outer_identity:
        _add(
            blockers,
            "MPR16_READINESS_NOT_CROSS_BOUND",
            "readiness payload must be bound to release/generation/policy/evidence head",
        )
    if snapshot.heartbeat_sequence <= snapshot.previous_accepted_sequence:
        _add(
            blockers,
            "MPR16_SNAPSHOT_REPLAY",
            "snapshot heartbeat sequence must advance durable high-water state",
        )
    if snapshot.expires_at_ns <= snapshot.trusted_now_ns:
        _add(blockers, "MPR16_SNAPSHOT_STALE", "readiness snapshot must be fresh at trusted now")
    if snapshot.evaluated_at_ns > snapshot.trusted_now_ns:
        _add(blockers, "MPR16_SNAPSHOT_FROM_FUTURE", "readiness snapshot cannot be future-dated")
    if not snapshot.durable_high_water_updated:
        _add(
            blockers,
            "MPR16_HIGH_WATER_NOT_DURABLE",
            "accepted management snapshot must update durable anti-replay high-water state",
        )


def _validate_archive_lease(
    lease: ArchiveLeaseEvidence, blockers: list[MPR16Violation]
) -> None:
    if not lease.claim_id:
        _add(blockers, "MPR16_ARCHIVE_CLAIM_MISSING", "archive claim id is required")
    if not lease.exporter_id:
        _add(blockers, "MPR16_ARCHIVE_EXPORTER_MISSING", "archive exporter id is required")
    for field_name in (
        "lease_generation",
        "monotonic_deadline_ns",
        "trusted_utc_expires_at_ns",
    ):
        if not _is_positive_int(getattr(lease, field_name)):
            _add(blockers, "MPR16_BAD_ARCHIVE_LEASE_FIELD", f"{field_name} must be positive integer")
    if not lease.renewable:
        _add(blockers, "MPR16_ARCHIVE_LEASE_NOT_RENEWABLE", "archive leases must be renewable")
    if not lease.cas_heartbeat_enabled:
        _add(blockers, "MPR16_ARCHIVE_NO_CAS_HEARTBEAT", "archive lease heartbeat must be CAS-protected")
    if not lease.fence_validated_before_read:
        _add(blockers, "MPR16_ARCHIVE_READ_WITHOUT_FENCE", "lease fence must be checked before reading rows")
    if not lease.fence_validated_before_write:
        _add(blockers, "MPR16_ARCHIVE_WRITE_WITHOUT_FENCE", "lease fence must be checked before writing artifacts")
    if not lease.fence_validated_before_commit:
        _add(blockers, "MPR16_ARCHIVE_COMMIT_WITHOUT_FENCE", "lease fence must be checked before commit")
    if not lease.stale_exporter_rejected_before_artifact_write:
        _add(
            blockers,
            "MPR16_STALE_EXPORTER_CAN_WRITE",
            "stale exporter must be rejected before producing orphan artifacts",
        )


def _validate_archive_durability(
    archive: ArchiveDurabilityEvidence, blockers: list[MPR16Violation]
) -> None:
    _validate_hash("archive_policy_hash", archive.archive_policy_hash, blockers)
    mandatory = tuple(archive.mandatory_archive_names)
    if not mandatory:
        _add(blockers, "MPR16_NO_MANDATORY_ARCHIVES", "archive policy must require at least one backend")
    if len(set(mandatory)) != len(mandatory):
        _add(blockers, "MPR16_DUPLICATE_MANDATORY_ARCHIVE", "mandatory archive names must be unique")
    receipts_by_archive: dict[str, RemoteArchiveReceipt] = {}
    for receipt in archive.remote_receipts:
        if receipt.archive_name in receipts_by_archive:
            _add(blockers, "MPR16_DUPLICATE_REMOTE_RECEIPT", f"duplicate receipt for {receipt.archive_name}")
        receipts_by_archive[receipt.archive_name] = receipt
        _validate_receipt(receipt, blockers)

    missing_receipts = [name for name in mandatory if name not in receipts_by_archive]
    if missing_receipts:
        _add(
            blockers,
            "MPR16_REMOTE_QUORUM_INCOMPLETE",
            f"missing mandatory WORM receipts: {missing_receipts}",
        )
    if not archive.append_only_ack_events:
        _add(blockers, "MPR16_REMOTE_ACK_NOT_APPEND_ONLY", "remote ACKs must be append-only events")
    if not archive.mutable_ack_upsert_disabled:
        _add(blockers, "MPR16_MUTABLE_REMOTE_ACK", "remote ACK UPSERT/overwrite must be disabled")
    if not archive.conflicting_second_ack_quarantined:
        _add(blockers, "MPR16_CONFLICTING_ACK_NOT_QUARANTINED", "conflicting second ACK must be quarantined")
    if not archive.terminal_ack_immutable:
        _add(blockers, "MPR16_TERMINAL_ACK_MUTABLE", "terminal ACK state must be immutable")
    if not archive.deterministic_remote_fsm:
        _add(blockers, "MPR16_REMOTE_FSM_MISSING", "archive remote state must be a deterministic FSM")
    if not archive.local_committed_state_separate_from_authoritative:
        _add(
            blockers,
            "MPR16_LOCAL_REMOTE_STATE_COLLAPSED",
            "local committed and authoritative remote-durable states must be distinct",
        )
    if not archive.promotion_requires_remote_quorum:
        _add(blockers, "MPR16_PROMOTION_WITHOUT_REMOTE_QUORUM", "promotion must require mandatory remote quorum")
    if not archive.manifest_authoritative_only_after_remote_quorum:
        _add(
            blockers,
            "MPR16_MANIFEST_AUTHORITATIVE_TOO_EARLY",
            "manifest cannot become authoritative before mandatory remote ACKs",
        )
    if not archive.latest_projection_replay_derived:
        _add(blockers, "MPR16_REMOTE_PROJECTION_NOT_REPLAY_DERIVED", "latest remote projection must be replay-derived")


def _validate_receipt(receipt: RemoteArchiveReceipt, blockers: list[MPR16Violation]) -> None:
    if not receipt.archive_name:
        _add(blockers, "MPR16_RECEIPT_ARCHIVE_MISSING", "receipt archive name is required")
    if not receipt.region:
        _add(blockers, "MPR16_RECEIPT_REGION_MISSING", "receipt region is required")
    if not receipt.object_version:
        _add(blockers, "MPR16_RECEIPT_VERSION_MISSING", "receipt object version is required")
    _validate_hash(f"receipt_hash:{receipt.archive_name}", receipt.receipt_hash, blockers)
    if not receipt.worm_locked:
        _add(blockers, "MPR16_RECEIPT_NOT_WORM_LOCKED", f"{receipt.archive_name} receipt lacks WORM lock")
    if not _is_positive_int(receipt.retention_until_ns):
        _add(blockers, "MPR16_BAD_RECEIPT_RETENTION", f"{receipt.archive_name} retention must be positive")


def _validate_hash(name: str, value: str, blockers: list[MPR16Violation]) -> None:
    if not _is_strict_sha256(value):
        _add(blockers, "MPR16_BAD_HASH", f"{name} is not a strict sha256 hash")


def _is_strict_sha256(value: str) -> bool:
    if not isinstance(value, str) or HEX_64_RE.match(value) is None:
        return False
    return value not in {"0" * 64, "f" * 64}


def _is_nonnegative_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0


def _is_positive_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def _stable_hash(value: object) -> str:
    payload = json.dumps(_to_jsonable(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _to_jsonable(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _to_jsonable(val) for key, val in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_jsonable(val) for key, val in value.items()}
    if isinstance(value, float) and not math.isfinite(value):
        return "<non-finite>"
    return value


def _add(blockers: list[MPR16Violation], code: str, message: str) -> None:
    blockers.append(MPR16Violation(code=code, message=message))


def _dedupe(blockers: Iterable[MPR16Violation]) -> Iterable[MPR16Violation]:
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        identity = (blocker.code, blocker.message)
        if identity not in seen:
            seen.add(identity)
            yield blocker
