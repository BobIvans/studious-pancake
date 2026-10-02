"""MPR-29 continuous installed paper/shadow soak evidence producer.

This module is offline and default-off. It validates evidence emitted by an
installed artifact paper/shadow soak, but it never opens live trading, signer
loading, sender transports, archive writes, or transaction submission.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any

MPR29_SCHEMA_VERSION = "mpr29.continuous-installed-paper-shadow-soak.v1"
MPR29_EVIDENCE_KIND = "continuous-paper-shadow-soak"
MPR29_ID = "MPR-29"
MIN_CYCLE_COUNT = 3
MIN_PROVIDER_SNAPSHOT_COUNT = 2
MAX_P95_LATENCY_MS = 2_500
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class MPR29Error(ValueError):
    """Raised when MPR-29 evidence is malformed before evaluation."""


class MPR29Status(StrEnum):
    """Terminal result of the default-off MPR-29 gate."""

    ACCEPTED = "ACCEPTED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class InstalledCommandSurfaceEvidence:
    """Installed artifact command surface consumed by the soak."""

    installed_wheel_sha256: str
    command_surface_sha256: str
    console_command: str
    source_checkout_used: bool
    installed_artifact_used: bool
    runtime_modes: tuple[str, ...]
    live_enabled: bool
    signer_loaded: bool
    sender_loaded: bool

    def __post_init__(self) -> None:
        _digest(self.installed_wheel_sha256, "installed_wheel_sha256")
        _digest(self.command_surface_sha256, "command_surface_sha256")
        _require_text(self.console_command, "console_command")
        _strict_bool(self.source_checkout_used, "source_checkout_used")
        _strict_bool(self.installed_artifact_used, "installed_artifact_used")
        _strict_bool(self.live_enabled, "live_enabled")
        _strict_bool(self.signer_loaded, "signer_loaded")
        _strict_bool(self.sender_loaded, "sender_loaded")
        _string_tuple(self.runtime_modes, "runtime_modes")


@dataclass(frozen=True, slots=True)
class ProviderSnapshotEvidence:
    """One non-synthetic provider snapshot captured during the soak."""

    provider: str
    endpoint_generation_sha256: str
    request_sha256: str
    response_sha256: str
    normalized_quote_sha256: str
    context_slot: int
    observed_at_unix_ns: int
    non_synthetic: bool
    replay_hash: str

    def __post_init__(self) -> None:
        _require_text(self.provider, "provider")
        _digest(self.endpoint_generation_sha256, "endpoint_generation_sha256")
        _digest(self.request_sha256, "request_sha256")
        _digest(self.response_sha256, "response_sha256")
        _digest(self.normalized_quote_sha256, "normalized_quote_sha256")
        _strict_positive_int(self.context_slot, "context_slot")
        _strict_positive_int(self.observed_at_unix_ns, "observed_at_unix_ns")
        _strict_bool(self.non_synthetic, "non_synthetic")
        _digest(self.replay_hash, "replay_hash")


@dataclass(frozen=True, slots=True)
class LifecycleOutcomeEvidence:
    """Durable paper/shadow lifecycle outcome from one installed cycle."""

    cycle_id: str
    mode: str
    status: str
    lifecycle_db_sha256: str
    replay_hash: str
    provider_snapshot_hash: str
    latency_ms: int
    finalized_settlement_observed: bool
    ready_for_next_cycle: bool
    sender_imported: bool
    submission_allowed: bool
    live_enabled: bool

    def __post_init__(self) -> None:
        _require_text(self.cycle_id, "cycle_id")
        _require_text(self.mode, "mode")
        _require_text(self.status, "status")
        _digest(self.lifecycle_db_sha256, "lifecycle_db_sha256")
        _digest(self.replay_hash, "replay_hash")
        _digest(self.provider_snapshot_hash, "provider_snapshot_hash")
        _strict_non_negative_int(self.latency_ms, "latency_ms")
        _strict_bool(self.finalized_settlement_observed, "finalized_settlement_observed")
        _strict_bool(self.ready_for_next_cycle, "ready_for_next_cycle")
        _strict_bool(self.sender_imported, "sender_imported")
        _strict_bool(self.submission_allowed, "submission_allowed")
        _strict_bool(self.live_enabled, "live_enabled")


@dataclass(frozen=True, slots=True)
class SloEvidence:
    """Latency and loss envelope for the short offline soak."""

    p50_latency_ms: int
    p95_latency_ms: int
    max_latency_ms: int
    data_loss_events: int
    provider_error_events: int
    reconciliation_gap_events: int
    queue_backlog_max: int

    def __post_init__(self) -> None:
        _strict_non_negative_int(self.p50_latency_ms, "p50_latency_ms")
        _strict_non_negative_int(self.p95_latency_ms, "p95_latency_ms")
        _strict_non_negative_int(self.max_latency_ms, "max_latency_ms")
        _strict_non_negative_int(self.data_loss_events, "data_loss_events")
        _strict_non_negative_int(self.provider_error_events, "provider_error_events")
        _strict_non_negative_int(
            self.reconciliation_gap_events,
            "reconciliation_gap_events",
        )
        _strict_non_negative_int(self.queue_backlog_max, "queue_backlog_max")


@dataclass(frozen=True, slots=True)
class DataLineageEvidence:
    """Proof that synthetic, recorded and finalized data cannot mix."""

    synthetic_namespace_sha256: str
    recorded_namespace_sha256: str
    finalized_namespace_sha256: str
    quarantine_policy_sha256: str
    synthetic_record_count: int
    finalized_record_count: int
    namespaces_disjoint: bool
    replay_separates_recorded_and_finalized: bool

    def __post_init__(self) -> None:
        _digest(self.synthetic_namespace_sha256, "synthetic_namespace_sha256")
        _digest(self.recorded_namespace_sha256, "recorded_namespace_sha256")
        _digest(self.finalized_namespace_sha256, "finalized_namespace_sha256")
        _digest(self.quarantine_policy_sha256, "quarantine_policy_sha256")
        _strict_non_negative_int(self.synthetic_record_count, "synthetic_record_count")
        _strict_non_negative_int(self.finalized_record_count, "finalized_record_count")
        _strict_bool(self.namespaces_disjoint, "namespaces_disjoint")
        _strict_bool(
            self.replay_separates_recorded_and_finalized,
            "replay_separates_recorded_and_finalized",
        )


@dataclass(frozen=True, slots=True)
class ContinuousShadowSoakBundle:
    """Evidence bundle produced by the installed paper/shadow soak."""

    schema_version: str
    command_surface: InstalledCommandSurfaceEvidence
    provider_snapshots: tuple[ProviderSnapshotEvidence, ...]
    lifecycle_outcomes: tuple[LifecycleOutcomeEvidence, ...]
    slo: SloEvidence
    lineage: DataLineageEvidence
    issued_at_ns: int
    expires_at_ns: int
    immutable_uri: str
    reviewer_digests: tuple[str, ...]
    long_soak_required: bool = True
    manual_or_scheduled_only: bool = True
    live_runtime_requested: bool = False

    def __post_init__(self) -> None:
        _require_text(self.schema_version, "schema_version")
        _strict_positive_int(self.issued_at_ns, "issued_at_ns")
        _strict_positive_int(self.expires_at_ns, "expires_at_ns")
        if self.issued_at_ns >= self.expires_at_ns:
            raise MPR29Error("MPR29_INVALID_EVIDENCE_TIME_WINDOW")
        _require_text(self.immutable_uri, "immutable_uri")
        _string_tuple(self.reviewer_digests, "reviewer_digests")
        for reviewer_digest in self.reviewer_digests:
            _digest(reviewer_digest, "reviewer_digest")
        if len(set(self.reviewer_digests)) != len(self.reviewer_digests):
            raise MPR29Error("MPR29_DUPLICATE_REVIEWER_DIGEST")
        _strict_bool(self.long_soak_required, "long_soak_required")
        _strict_bool(self.manual_or_scheduled_only, "manual_or_scheduled_only")
        _strict_bool(self.live_runtime_requested, "live_runtime_requested")
        object.__setattr__(self, "provider_snapshots", tuple(self.provider_snapshots))
        object.__setattr__(self, "lifecycle_outcomes", tuple(self.lifecycle_outcomes))


@dataclass(frozen=True, slots=True)
class MPR29Decision:
    """Default-off MPR-29 evidence decision."""

    status: MPR29Status
    reason_codes: tuple[str, ...]
    bundle_hash: str
    evidence_kind: str
    signed_artifact_digest: str
    live_enabled: bool = False
    signer_loaded: bool = False
    sender_loaded: bool = False

    @property
    def accepted(self) -> bool:
        return self.status is MPR29Status.ACCEPTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MPR29_SCHEMA_VERSION,
            "mpr_id": MPR29_ID,
            "status": self.status.value,
            "accepted": self.accepted,
            "reason_codes": list(self.reason_codes),
            "bundle_hash": self.bundle_hash,
            "evidence_kind": self.evidence_kind,
            "signed_artifact_digest": self.signed_artifact_digest,
            "live_enabled": self.live_enabled,
            "signer_loaded": self.signer_loaded,
            "sender_loaded": self.sender_loaded,
            "production_ready": False,
            "live_ready": False,
        }


def evaluate_mpr29_soak(bundle: ContinuousShadowSoakBundle) -> MPR29Decision:
    """Evaluate a continuous installed paper/shadow soak bundle."""

    reasons: list[str] = []
    command = bundle.command_surface

    if bundle.schema_version != MPR29_SCHEMA_VERSION:
        reasons.append("MPR29_SCHEMA_VERSION")
    if not command.installed_artifact_used:
        reasons.append("MPR29_INSTALLED_ARTIFACT_REQUIRED")
    if command.source_checkout_used:
        reasons.append("MPR29_SOURCE_CHECKOUT_NOT_ALLOWED")
    if command.live_enabled or command.signer_loaded or command.sender_loaded:
        reasons.append("MPR29_LIVE_SIGNER_OR_SENDER_FORBIDDEN")
    if "paper" not in command.runtime_modes or "shadow" not in command.runtime_modes:
        reasons.append("MPR29_PAPER_AND_SHADOW_MODES_REQUIRED")
    if "live" in command.runtime_modes:
        reasons.append("MPR29_LIVE_MODE_MUST_NOT_BE_ADVERTISED")

    snapshot_hashes = {snapshot.replay_hash for snapshot in bundle.provider_snapshots}
    providers = {snapshot.provider for snapshot in bundle.provider_snapshots}
    if len(bundle.provider_snapshots) < MIN_PROVIDER_SNAPSHOT_COUNT:
        reasons.append("MPR29_PROVIDER_SNAPSHOT_QUORUM_REQUIRED")
    if len(providers) < MIN_PROVIDER_SNAPSHOT_COUNT:
        reasons.append("MPR29_PROVIDER_DIVERSITY_REQUIRED")
    if any(not snapshot.non_synthetic for snapshot in bundle.provider_snapshots):
        reasons.append("MPR29_SYNTHETIC_PROVIDER_SNAPSHOT")
    if len(snapshot_hashes) != len(bundle.provider_snapshots):
        reasons.append("MPR29_DUPLICATE_PROVIDER_REPLAY_HASH")

    if len(bundle.lifecycle_outcomes) < MIN_CYCLE_COUNT:
        reasons.append("MPR29_MINIMUM_CYCLES_REQUIRED")
    lifecycle_modes = {outcome.mode for outcome in bundle.lifecycle_outcomes}
    if not {"paper", "shadow"} <= lifecycle_modes:
        reasons.append("MPR29_PAPER_AND_SHADOW_OUTCOMES_REQUIRED")
    if any(
        outcome.sender_imported or outcome.submission_allowed or outcome.live_enabled
        for outcome in bundle.lifecycle_outcomes
    ):
        reasons.append("MPR29_UNSAFE_LIFECYCLE_SURFACE")
    if any(not outcome.ready_for_next_cycle for outcome in bundle.lifecycle_outcomes):
        reasons.append("MPR29_CYCLE_NOT_READY")
    if any(not outcome.finalized_settlement_observed for outcome in bundle.lifecycle_outcomes):
        reasons.append("MPR29_FINALIZED_SETTLEMENT_NOT_OBSERVED")
    lifecycle_replays = {outcome.replay_hash for outcome in bundle.lifecycle_outcomes}
    if len(lifecycle_replays) != len(bundle.lifecycle_outcomes):
        reasons.append("MPR29_DUPLICATE_LIFECYCLE_REPLAY_HASH")
    if any(
        outcome.provider_snapshot_hash not in snapshot_hashes
        for outcome in bundle.lifecycle_outcomes
    ):
        reasons.append("MPR29_LIFECYCLE_PROVIDER_REPLAY_UNBOUND")

    if bundle.slo.p95_latency_ms > MAX_P95_LATENCY_MS:
        reasons.append("MPR29_P95_LATENCY_SLO_BREACH")
    if bundle.slo.data_loss_events:
        reasons.append("MPR29_DATA_LOSS_EVENTS")
    if bundle.slo.reconciliation_gap_events:
        reasons.append("MPR29_RECONCILIATION_GAP_EVENTS")

    if not bundle.lineage.namespaces_disjoint:
        reasons.append("MPR29_LINEAGE_NAMESPACES_NOT_DISJOINT")
    if bundle.lineage.synthetic_record_count:
        reasons.append("MPR29_SYNTHETIC_RECORDS_PRESENT")
    if not bundle.lineage.replay_separates_recorded_and_finalized:
        reasons.append("MPR29_LINEAGE_REPLAY_NOT_SEPARATED")
    if bundle.lineage.finalized_record_count < len(bundle.lifecycle_outcomes):
        reasons.append("MPR29_FINALIZED_RECORDS_INCOMPLETE")

    if not bundle.long_soak_required:
        reasons.append("MPR29_LONG_SOAK_REQUIREMENT_MISSING")
    if not bundle.manual_or_scheduled_only:
        reasons.append("MPR29_AUTOMATIC_PROMOTION_FORBIDDEN")
    if bundle.live_runtime_requested:
        reasons.append("MPR29_LIVE_RUNTIME_REQUEST_FORBIDDEN")

    status = MPR29Status.BLOCKED if reasons else MPR29Status.ACCEPTED
    bundle_hash = _hash_json(_public_payload(bundle) | {"schema": MPR29_SCHEMA_VERSION})
    artifact_digest = _hash_json(
        {
            "kind": MPR29_EVIDENCE_KIND,
            "bundle_hash": bundle_hash,
            "command_surface_sha256": command.command_surface_sha256,
            "installed_wheel_sha256": command.installed_wheel_sha256,
        }
    )
    if status is MPR29Status.ACCEPTED:
        reasons.append("MPR29_CONTINUOUS_SOAK_ACCEPTED_DEFAULT_OFF")

    return MPR29Decision(
        status=status,
        reason_codes=tuple(reasons),
        bundle_hash=bundle_hash,
        evidence_kind=MPR29_EVIDENCE_KIND,
        signed_artifact_digest=artifact_digest,
    )


def signed_artifact_payload(bundle: ContinuousShadowSoakBundle) -> dict[str, Any]:
    """Return an MPR-31-compatible upstream artifact payload for MPR-29."""

    decision = evaluate_mpr29_soak(bundle)
    return {
        "mpr_id": MPR29_ID,
        "kind": MPR29_EVIDENCE_KIND,
        "digest": decision.signed_artifact_digest,
        "signature_digest": _hash_json(
            {
                "schema": MPR29_SCHEMA_VERSION,
                "digest": decision.signed_artifact_digest,
                "reviewers": list(bundle.reviewer_digests),
            }
        ),
        "reviewer_digests": list(bundle.reviewer_digests),
        "issued_at_ns": bundle.issued_at_ns,
        "expires_at_ns": bundle.expires_at_ns,
        "size_bytes": len(_canonical_json(_public_payload(bundle)).encode("utf-8")),
        "immutable_uri": bundle.immutable_uri,
        "accepted_default_off": decision.accepted,
        "live_enabled": False,
        "signer_loaded": False,
        "sender_loaded": False,
    }


def bundle_from_mapping(payload: Mapping[str, Any]) -> ContinuousShadowSoakBundle:
    """Decode JSON evidence into a typed MPR-29 bundle."""

    command = dict(_mapping(payload.get("command_surface"), "command_surface"))
    command["runtime_modes"] = tuple(
        str(item) for item in _sequence(command.get("runtime_modes"), "runtime_modes")
    )
    return ContinuousShadowSoakBundle(
        schema_version=str(payload.get("schema_version", "")),
        command_surface=InstalledCommandSurfaceEvidence(**command),
        provider_snapshots=tuple(
            ProviderSnapshotEvidence(**_mapping(item, "provider_snapshots[]"))
            for item in _sequence(payload.get("provider_snapshots"), "provider_snapshots")
        ),
        lifecycle_outcomes=tuple(
            LifecycleOutcomeEvidence(**_mapping(item, "lifecycle_outcomes[]"))
            for item in _sequence(payload.get("lifecycle_outcomes"), "lifecycle_outcomes")
        ),
        slo=SloEvidence(**_mapping(payload.get("slo"), "slo")),
        lineage=DataLineageEvidence(**_mapping(payload.get("lineage"), "lineage")),
        issued_at_ns=_int(payload.get("issued_at_ns"), "issued_at_ns"),
        expires_at_ns=_int(payload.get("expires_at_ns"), "expires_at_ns"),
        immutable_uri=str(payload.get("immutable_uri", "")),
        reviewer_digests=tuple(
            str(item)
            for item in _sequence(payload.get("reviewer_digests"), "reviewer_digests")
        ),
        long_soak_required=_bool(payload.get("long_soak_required", True)),
        manual_or_scheduled_only=_bool(payload.get("manual_or_scheduled_only", True)),
        live_runtime_requested=_bool(payload.get("live_runtime_requested", False)),
    )


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MPR29Error(f"{name} must be an object")
    return value


def _sequence(value: Any, name: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise MPR29Error(f"{name} must be a sequence")
    return value


def _int(value: Any, name: str) -> int:
    if type(value) is not int:
        raise MPR29Error(f"{name} must be int")
    return value


def _bool(value: Any) -> bool:
    if type(value) is not bool:
        raise MPR29Error("boolean field must be bool")
    return value


def _public_payload(value: object) -> dict[str, Any]:
    if not is_dataclass(value):
        raise TypeError("expected dataclass payload")
    payload: dict[str, Any] = {}
    for field in fields(value):
        item = getattr(value, field.name)
        if is_dataclass(item):
            payload[field.name] = _public_payload(item)
        elif isinstance(item, tuple):
            payload[field.name] = [
                _public_payload(row) if is_dataclass(row) else row for row in item
            ]
        else:
            payload[field.name] = item
    return payload


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _hash_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _digest(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise MPR29Error(f"{name} must be a lowercase sha256 digest")


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise MPR29Error(f"{name} must be non-empty text")


def _string_tuple(value: tuple[str, ...], name: str) -> None:
    if not isinstance(value, tuple) or not value:
        raise MPR29Error(f"{name} must be a non-empty tuple")
    for item in value:
        _require_text(item, name)


def _strict_bool(value: bool, name: str) -> None:
    if type(value) is not bool:
        raise MPR29Error(f"{name} must be bool")


def _strict_non_negative_int(value: int, name: str) -> None:
    if type(value) is not int or value < 0:
        raise MPR29Error(f"{name} must be a non-negative integer")


def _strict_positive_int(value: int, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise MPR29Error(f"{name} must be a positive integer")


__all__ = [
    "ContinuousShadowSoakBundle",
    "DataLineageEvidence",
    "InstalledCommandSurfaceEvidence",
    "LifecycleOutcomeEvidence",
    "MIN_CYCLE_COUNT",
    "MIN_PROVIDER_SNAPSHOT_COUNT",
    "MPR29Decision",
    "MPR29Error",
    "MPR29Status",
    "MPR29_EVIDENCE_KIND",
    "MPR29_ID",
    "MPR29_SCHEMA_VERSION",
    "ProviderSnapshotEvidence",
    "SloEvidence",
    "bundle_from_mapping",
    "evaluate_mpr29_soak",
    "signed_artifact_payload",
]
