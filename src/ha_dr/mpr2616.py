"""MPR-2616 executable single-active HA/DR and fenced failover boundary.

This module intentionally does not provide a production distributed lock.  It
models the fail-closed state machine, validates coordinator receipts, and gives
integration tests a linearizable sandbox coordinator.  Production qualification
remains BLOCKED_EXTERNAL_INFRASTRUCTURE until an approved strongly-consistent
cross-host backend materializes independently verifiable receipts.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import threading
from typing import Any, Iterable, Mapping, Protocol

SCHEMA = "mpr2616.executable-ha-dr.v1"
QUALIFICATION_SCHEMA = "mpr2616.ha-qualification.v1"
_SHA256_LEN = 64


class HaDrError(RuntimeError):
    """Base fail-closed HA/DR error."""


class StaleFenceError(HaDrError):
    """The caller no longer owns the current cross-host fence."""


class CoordinatorUnavailable(HaDrError):
    """The fencing coordinator cannot prove current ownership."""


class TakeoverConflict(HaDrError):
    """The requested takeover conflicts with durable coordinator state."""


class EvidenceBlocked(HaDrError):
    """Materialized HA/DR evidence is insufficient or inconsistent."""


class LeaderState(StrEnum):
    STANDBY_UNSYNCED = "standby_unsynced"
    STANDBY_RESTORING = "standby_restoring"
    STANDBY_VERIFIED = "standby_verified"
    TAKEOVER_REVIEW_PENDING = "takeover_review_pending"
    TAKEOVER_FENCING = "takeover_fencing"
    ACTIVE_DEFAULT_OFF = "active_default_off"
    ACTIVE_EFFECT_ELIGIBLE = "active_effect_eligible"
    SUSPENDED = "suspended"
    OLD_LEADER_FENCED = "old_leader_fenced"
    DR_BLOCKED = "dr_blocked"


class DispatchBoundary(StrEnum):
    NOT_ISSUED = "not_issued"
    DURABLE_MARKER_WRITTEN = "durable_marker_written"
    UNKNOWN = "unknown"
    FINALIZED = "finalized"


class QualificationVerdict(StrEnum):
    QUALIFIED_DEFAULT_OFF = "qualified_default_off"
    BLOCKED_EVIDENCE = "blocked_evidence"
    BLOCKED_EXTERNAL_INFRASTRUCTURE = "blocked_external_infrastructure"
    BLOCKED_EXTERNAL_SIGNER_RECOVERY = "blocked_external_signer_recovery"
    FAILED = "failed"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_digest(value: Any) -> str:
    return _sha256_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
    )


def _require_sha256(name: str, value: str) -> None:
    if len(value) != _SHA256_LEN or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"{name} must be a lowercase sha256 hex digest")


def _require_positive_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json_loads(payload: str | bytes) -> Any:
    """Parse JSON while rejecting duplicate keys and non-finite constants."""

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON value: {value}")

    return json.loads(
        payload,
        object_pairs_hook=_strict_pairs,
        parse_constant=reject_constant,
    )


@dataclass(frozen=True, slots=True)
class RuntimeIdentity:
    release_id: str
    release_generation: int
    source_commit: str
    tree_digest: str
    wheel_digest: str
    image_digest: str
    config_generation: int
    policy_generation: int
    runtime_authority_digest: str
    genesis_hash: str
    cluster: str
    wallet_scope: str
    instance_id: str
    boot_generation: int
    conformance_lease_digest: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "release_generation",
            "config_generation",
            "policy_generation",
            "boot_generation",
        ):
            _require_positive_int(name, getattr(self, name))
        for name in (
            "source_commit",
            "tree_digest",
            "wheel_digest",
            "image_digest",
            "runtime_authority_digest",
            "genesis_hash",
        ):
            _require_sha256(name, getattr(self, name))
        if self.conformance_lease_digest is not None:
            _require_sha256("conformance_lease_digest", self.conformance_lease_digest)
        for name in ("release_id", "cluster", "wallet_scope", "instance_id"):
            value = getattr(self, name)
            if not value or len(value) > 256:
                raise ValueError(f"{name} must be non-empty and bounded")

    @property
    def semantic_digest(self) -> str:
        return canonical_digest(asdict(self))


@dataclass(frozen=True, slots=True)
class FenceLease:
    backend_id: str
    scope_digest: str
    generation: int
    owner_digest: str
    lease_deadline_ns: int
    coordinator_receipt_digest: str

    def __post_init__(self) -> None:
        _require_positive_int("generation", self.generation)
        _require_positive_int("lease_deadline_ns", self.lease_deadline_ns)
        for name in ("scope_digest", "owner_digest", "coordinator_receipt_digest"):
            _require_sha256(name, getattr(self, name))
        if not self.backend_id or len(self.backend_id) > 128:
            raise ValueError("backend_id must be non-empty and bounded")


@dataclass(frozen=True, slots=True)
class CoordinatorCapabilities:
    backend_id: str
    cross_host: bool
    strongly_consistent: bool
    monotonic_generation: bool
    compare_and_swap: bool
    coordinator_native_expiry: bool
    survives_application_host_loss: bool
    sandbox_only: bool = False

    @property
    def production_eligible(self) -> bool:
        return all(
            (
                self.cross_host,
                self.strongly_consistent,
                self.monotonic_generation,
                self.compare_and_swap,
                self.coordinator_native_expiry,
                self.survives_application_host_loss,
                not self.sandbox_only,
            )
        )


class FencingBackend(Protocol):
    @property
    def capabilities(self) -> CoordinatorCapabilities: ...

    def current(self, scope_digest: str, *, now_ns: int) -> FenceLease | None: ...

    def acquire(
        self,
        scope_digest: str,
        owner_digest: str,
        *,
        expected_generation: int,
        lease_deadline_ns: int,
        now_ns: int,
    ) -> FenceLease: ...

    def assert_current(self, lease: FenceLease, *, now_ns: int) -> None: ...


class LinearizableMemoryFencingBackend:
    """Process-local deterministic coordinator for integration tests only.

    It is deliberately marked ``sandbox_only`` and can never satisfy production
    cross-host qualification.  The lock gives the test harness a linearizable
    CAS model without pretending that an in-memory mutex survives host loss.
    """

    def __init__(self, backend_id: str = "mpr2616-sandbox-memory") -> None:
        self._lock = threading.Lock()
        self._records: dict[str, FenceLease] = {}
        self._backend_id = backend_id

    @property
    def capabilities(self) -> CoordinatorCapabilities:
        return CoordinatorCapabilities(
            backend_id=self._backend_id,
            cross_host=False,
            strongly_consistent=True,
            monotonic_generation=True,
            compare_and_swap=True,
            coordinator_native_expiry=True,
            survives_application_host_loss=False,
            sandbox_only=True,
        )

    def current(self, scope_digest: str, *, now_ns: int) -> FenceLease | None:
        with self._lock:
            lease = self._records.get(scope_digest)
            if lease is None or lease.lease_deadline_ns <= now_ns:
                return None
            return lease

    def acquire(
        self,
        scope_digest: str,
        owner_digest: str,
        *,
        expected_generation: int,
        lease_deadline_ns: int,
        now_ns: int,
    ) -> FenceLease:
        _require_sha256("scope_digest", scope_digest)
        _require_sha256("owner_digest", owner_digest)
        if isinstance(expected_generation, bool) or expected_generation < 0:
            raise ValueError("expected_generation must be a non-negative integer")
        if lease_deadline_ns <= now_ns:
            raise ValueError("lease_deadline_ns must be in the future")
        with self._lock:
            current = self._records.get(scope_digest)
            visible_generation = 0
            if current is not None:
                visible_generation = current.generation
                if current.lease_deadline_ns <= now_ns:
                    pass
            if visible_generation != expected_generation:
                raise TakeoverConflict("fencing generation changed")
            generation = visible_generation + 1
            receipt = canonical_digest(
                {
                    "backend_id": self._backend_id,
                    "scope_digest": scope_digest,
                    "generation": generation,
                    "owner_digest": owner_digest,
                    "lease_deadline_ns": lease_deadline_ns,
                }
            )
            lease = FenceLease(
                backend_id=self._backend_id,
                scope_digest=scope_digest,
                generation=generation,
                owner_digest=owner_digest,
                lease_deadline_ns=lease_deadline_ns,
                coordinator_receipt_digest=receipt,
            )
            self._records[scope_digest] = lease
            return lease

    def assert_current(self, lease: FenceLease, *, now_ns: int) -> None:
        with self._lock:
            current = self._records.get(lease.scope_digest)
            if current is None:
                raise StaleFenceError("no active fence")
            if current != lease:
                raise StaleFenceError("stale fencing generation")
            if lease.lease_deadline_ns <= now_ns:
                raise StaleFenceError("fencing lease expired")


@dataclass(frozen=True, slots=True)
class RestoreEvidence:
    release_generation: int
    backup_artifact_digest: str
    object_receipt_digest: str | None
    wal_included: bool
    integrity_ok: bool
    critical_state_before_digest: str
    critical_state_after_digest: str
    consumed_permits_preserved: bool
    unknown_holds_preserved: bool
    risk_counters_not_decreased: bool
    suspension_preserved: bool
    fence_generation_not_decreased: bool
    committed_ns: int
    restored_ns: int

    def __post_init__(self) -> None:
        _require_positive_int("release_generation", self.release_generation)
        for name in (
            "backup_artifact_digest",
            "critical_state_before_digest",
            "critical_state_after_digest",
        ):
            _require_sha256(name, getattr(self, name))
        if self.object_receipt_digest is not None:
            _require_sha256("object_receipt_digest", self.object_receipt_digest)
        for name in ("committed_ns", "restored_ns"):
            _require_positive_int(name, getattr(self, name))
        if self.restored_ns < self.committed_ns:
            raise ValueError("restored_ns cannot precede committed_ns")

    @property
    def rpo_seconds(self) -> int:
        return (self.restored_ns - self.committed_ns) // 1_000_000_000

    @property
    def safe_for_takeover(self) -> bool:
        return all(
            (
                self.wal_included,
                self.integrity_ok,
                self.critical_state_before_digest == self.critical_state_after_digest,
                self.consumed_permits_preserved,
                self.unknown_holds_preserved,
                self.risk_counters_not_decreased,
                self.suspension_preserved,
                self.fence_generation_not_decreased,
                self.object_receipt_digest is not None,
            )
        )

    @property
    def semantic_digest(self) -> str:
        return canonical_digest(asdict(self))


@dataclass(frozen=True, slots=True)
class HumanTakeoverAuthorization:
    occurrence_id: str
    old_owner_digest: str
    proposed_owner_digest: str
    release_generation: int
    restore_evidence_digest: str
    conformance_evidence_digest: str | None
    expected_fence_generation: int
    action: str
    not_before_ns: int
    expires_ns: int
    canonical_authority_receipt_digest: str

    def __post_init__(self) -> None:
        for name in (
            "old_owner_digest",
            "proposed_owner_digest",
            "restore_evidence_digest",
            "canonical_authority_receipt_digest",
        ):
            _require_sha256(name, getattr(self, name))
        if self.conformance_evidence_digest is not None:
            _require_sha256("conformance_evidence_digest", self.conformance_evidence_digest)
        _require_positive_int("release_generation", self.release_generation)
        if isinstance(self.expected_fence_generation, bool) or self.expected_fence_generation < 0:
            raise ValueError("expected_fence_generation must be non-negative")
        if self.action not in {"failover", "failback"}:
            raise ValueError("action must be failover or failback")
        if self.expires_ns <= self.not_before_ns:
            raise ValueError("authorization expiry must follow not-before")
        if not self.occurrence_id:
            raise ValueError("occurrence_id is required")

    def assert_current(self, *, now_ns: int) -> None:
        if now_ns < self.not_before_ns:
            raise EvidenceBlocked("takeover authorization is not active yet")
        if now_ns >= self.expires_ns:
            raise EvidenceBlocked("takeover authorization expired")


@dataclass(frozen=True, slots=True)
class TakeoverResult:
    state: LeaderState
    lease: FenceLease
    live_enabled: bool = False
    automatic_scale_up: bool = False
    effect_eligible: bool = False


class FailoverController:
    """Fail-closed state machine around an injected fencing coordinator."""

    def __init__(self, backend: FencingBackend, *, require_conformance_lease: bool) -> None:
        capabilities = backend.capabilities
        if not capabilities.strongly_consistent or not capabilities.compare_and_swap:
            raise TypeError("backend does not provide linearizable CAS semantics")
        self._backend = backend
        self._require_conformance = require_conformance_lease

    @staticmethod
    def scope_digest(identity: RuntimeIdentity) -> str:
        return canonical_digest(
            {
                "release_id": identity.release_id,
                "cluster": identity.cluster,
                "genesis_hash": identity.genesis_hash,
                "wallet_scope": identity.wallet_scope,
            }
        )

    def takeover(
        self,
        *,
        old_owner_digest: str,
        standby: RuntimeIdentity,
        restore: RestoreEvidence,
        authorization: HumanTakeoverAuthorization,
        lease_deadline_ns: int,
        now_ns: int,
        conformance_current: bool,
    ) -> TakeoverResult:
        authorization.assert_current(now_ns=now_ns)
        if restore.release_generation != standby.release_generation:
            raise EvidenceBlocked("restore release generation mismatch")
        if not restore.safe_for_takeover:
            raise EvidenceBlocked("restore evidence is not safe for takeover")
        if authorization.release_generation != standby.release_generation:
            raise EvidenceBlocked("authorization release generation mismatch")
        if authorization.old_owner_digest != old_owner_digest:
            raise EvidenceBlocked("authorization old owner mismatch")
        if authorization.proposed_owner_digest != standby.semantic_digest:
            raise EvidenceBlocked("authorization proposed owner mismatch")
        if authorization.restore_evidence_digest != restore.semantic_digest:
            raise EvidenceBlocked("authorization restore evidence mismatch")
        if self._require_conformance:
            if not conformance_current or standby.conformance_lease_digest is None:
                raise EvidenceBlocked("current conformance lease required")
            if authorization.conformance_evidence_digest != standby.conformance_lease_digest:
                raise EvidenceBlocked("authorization conformance evidence mismatch")
        scope = self.scope_digest(standby)
        lease = self._backend.acquire(
            scope,
            standby.semantic_digest,
            expected_generation=authorization.expected_fence_generation,
            lease_deadline_ns=lease_deadline_ns,
            now_ns=now_ns,
        )
        return TakeoverResult(state=LeaderState.ACTIVE_DEFAULT_OFF, lease=lease)

    def assert_effect_adjacent_authority(
        self,
        *,
        lease: FenceLease,
        runtime: RuntimeIdentity,
        now_ns: int,
        fresh_one_shot_authorization: bool,
        conformance_current: bool,
        suspension_clear: bool,
    ) -> None:
        self._backend.assert_current(lease, now_ns=now_ns)
        if lease.owner_digest != runtime.semantic_digest:
            raise StaleFenceError("runtime identity does not own the fence")
        if self._require_conformance and not conformance_current:
            raise EvidenceBlocked("conformance sentinel/lease is not current")
        if not suspension_clear:
            raise EvidenceBlocked("canonical suspension remains active")
        if not fresh_one_shot_authorization:
            raise EvidenceBlocked("fresh one-shot effect authorization required")

    def assert_signer_or_sender_authority(self, **kwargs: Any) -> None:
        self.assert_effect_adjacent_authority(**kwargs)


@dataclass(frozen=True, slots=True)
class UnknownEffectRecovery:
    dispatch_boundary: DispatchBoundary
    resend_allowed: bool
    capital_quarantined: bool
    requires_exact_identity_query: bool
    requires_human_incident_if_unresolved: bool


def recover_after_host_loss(boundary: DispatchBoundary) -> UnknownEffectRecovery:
    if boundary in {DispatchBoundary.DURABLE_MARKER_WRITTEN, DispatchBoundary.UNKNOWN}:
        return UnknownEffectRecovery(
            dispatch_boundary=boundary,
            resend_allowed=False,
            capital_quarantined=True,
            requires_exact_identity_query=True,
            requires_human_incident_if_unresolved=True,
        )
    if boundary is DispatchBoundary.NOT_ISSUED:
        return UnknownEffectRecovery(
            dispatch_boundary=boundary,
            resend_allowed=False,
            capital_quarantined=False,
            requires_exact_identity_query=False,
            requires_human_incident_if_unresolved=False,
        )
    return UnknownEffectRecovery(
        dispatch_boundary=boundary,
        resend_allowed=False,
        capital_quarantined=False,
        requires_exact_identity_query=False,
        requires_human_incident_if_unresolved=False,
    )


@dataclass(frozen=True, slots=True)
class CampaignEvent:
    event: str
    monotonic_ns: int
    fence_generation: int
    owner_digest: str
    effect_eligible: bool

    def __post_init__(self) -> None:
        _require_positive_int("monotonic_ns", self.monotonic_ns)
        if isinstance(self.fence_generation, bool) or self.fence_generation < 0:
            raise ValueError("fence_generation must be non-negative")
        _require_sha256("owner_digest", self.owner_digest)
        if not self.event:
            raise ValueError("campaign event name required")


@dataclass(frozen=True, slots=True)
class CampaignEvidence:
    campaign_id: str
    drill: str
    release_id: str
    release_generation: int
    raw_artifact_sha256: str
    before_state_digest: str
    after_state_digest: str
    fault_injection_digest: str
    events: tuple[CampaignEvent, ...]
    committed_state_ns: int
    recovered_state_ns: int
    outage_started_ns: int
    service_restored_ns: int
    result: str

    def __post_init__(self) -> None:
        for name in (
            "raw_artifact_sha256",
            "before_state_digest",
            "after_state_digest",
            "fault_injection_digest",
        ):
            _require_sha256(name, getattr(self, name))
        _require_positive_int("release_generation", self.release_generation)
        for name in (
            "committed_state_ns",
            "recovered_state_ns",
            "outage_started_ns",
            "service_restored_ns",
        ):
            _require_positive_int(name, getattr(self, name))
        if self.recovered_state_ns < self.committed_state_ns:
            raise ValueError("recovered state time precedes committed state")
        if self.service_restored_ns < self.outage_started_ns:
            raise ValueError("service restored time precedes outage")
        if self.result not in {"PASS", "BLOCKED", "FAILED"}:
            raise ValueError("campaign result must be PASS/BLOCKED/FAILED")
        if not self.campaign_id or not self.drill or not self.release_id:
            raise ValueError("campaign identity fields are required")

    @property
    def rpo_seconds(self) -> int:
        return (self.recovered_state_ns - self.committed_state_ns) // 1_000_000_000

    @property
    def rto_seconds(self) -> int:
        return (self.service_restored_ns - self.outage_started_ns) // 1_000_000_000

    @property
    def semantic_digest(self) -> str:
        return canonical_digest(
            {
                **asdict(self),
                "events": [asdict(event) for event in self.events],
            }
        )

    @property
    def dual_active_observed(self) -> bool:
        effect_events = [event for event in self.events if event.effect_eligible]
        by_time: dict[int, set[tuple[int, str]]] = {}
        for event in effect_events:
            by_time.setdefault(event.monotonic_ns, set()).add(
                (event.fence_generation, event.owner_digest)
            )
        return any(len(owners) > 1 for owners in by_time.values())

    @property
    def generations_monotonic(self) -> bool:
        generations = [event.fence_generation for event in self.events]
        return generations == sorted(generations)


@dataclass(frozen=True, slots=True)
class QualificationInput:
    release_id: str
    release_generation: int
    ha_policy_generation: int
    coordinator: CoordinatorCapabilities | None
    campaigns: tuple[CampaignEvidence, ...]
    required_drills: frozenset[str]
    rpo_target_seconds: int
    rto_target_seconds: int
    signer_recovery_proven: bool
    provider_failover_proven: bool
    object_store_receipt_proven: bool
    unresolved_unknown_effects: int
    legacy_pr165_review_ready: bool

    def __post_init__(self) -> None:
        for name in ("release_generation", "ha_policy_generation"):
            _require_positive_int(name, getattr(self, name))
        for name in ("rpo_target_seconds", "rto_target_seconds", "unresolved_unknown_effects"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class HaQualification:
    schema_version: str
    verdict: QualificationVerdict
    release_id: str
    release_generation: int
    ha_policy_generation: int
    fencing_backend_id: str | None
    campaign_digests: tuple[str, ...]
    derived_rpo_seconds: int | None
    derived_rto_seconds: int | None
    dual_active_verdict: str
    blockers: tuple[str, ...]
    executable_ha_qualified: bool
    live_enabled: bool = False
    automatic_scale_up: bool = False

    @property
    def semantic_digest(self) -> str:
        return canonical_digest(asdict(self))


def evaluate_ha_qualification(value: QualificationInput) -> HaQualification:
    blockers: list[str] = []
    coordinator = value.coordinator
    if coordinator is None or not coordinator.production_eligible:
        blockers.append("BLOCKED_EXTERNAL_INFRASTRUCTURE")
    if not value.campaigns:
        blockers.append("RAW_CAMPAIGN_EVIDENCE_MISSING")
    observed_drills = {
        campaign.drill for campaign in value.campaigns if campaign.result == "PASS"
    }
    for drill in sorted(value.required_drills - observed_drills):
        blockers.append(f"REQUIRED_DRILL_NOT_PROVEN:{drill}")
    campaign_digests: list[str] = []
    rpo_values: list[int] = []
    rto_values: list[int] = []
    dual_active = False
    for campaign in value.campaigns:
        campaign_digests.append(campaign.semantic_digest)
        if (
            campaign.release_id != value.release_id
            or campaign.release_generation != value.release_generation
        ):
            blockers.append(f"CAMPAIGN_RELEASE_MISMATCH:{campaign.campaign_id}")
        if campaign.result != "PASS":
            blockers.append(f"CAMPAIGN_NOT_PASS:{campaign.campaign_id}")
        if campaign.before_state_digest != campaign.after_state_digest:
            blockers.append(f"STATE_SEMANTIC_MISMATCH:{campaign.campaign_id}")
        if not campaign.generations_monotonic:
            blockers.append(f"FENCE_GENERATION_REGRESSION:{campaign.campaign_id}")
        if campaign.dual_active_observed:
            blockers.append(f"DUAL_ACTIVE_OBSERVED:{campaign.campaign_id}")
            dual_active = True
        rpo_values.append(campaign.rpo_seconds)
        rto_values.append(campaign.rto_seconds)
    derived_rpo = max(rpo_values) if rpo_values else None
    derived_rto = max(rto_values) if rto_values else None
    if derived_rpo is not None and derived_rpo > value.rpo_target_seconds:
        blockers.append("RPO_TARGET_EXCEEDED")
    if derived_rto is not None and derived_rto > value.rto_target_seconds:
        blockers.append("RTO_TARGET_EXCEEDED")
    if not value.signer_recovery_proven:
        blockers.append("BLOCKED_EXTERNAL_SIGNER_RECOVERY")
    if not value.provider_failover_proven:
        blockers.append("PROVIDER_FAILOVER_NOT_PROVEN")
    if not value.object_store_receipt_proven:
        blockers.append("OBJECT_STORE_RECEIPT_NOT_PROVEN")
    if value.unresolved_unknown_effects:
        blockers.append("UNRESOLVED_UNKNOWN_EFFECTS")
    if value.legacy_pr165_review_ready and not value.campaigns:
        blockers.append("PR165_SHAPE_ONLY_NOT_EXECUTABLE_PROOF")
    unique_blockers = tuple(sorted(set(blockers)))
    if not unique_blockers:
        verdict = QualificationVerdict.QUALIFIED_DEFAULT_OFF
    elif "BLOCKED_EXTERNAL_INFRASTRUCTURE" in unique_blockers:
        verdict = QualificationVerdict.BLOCKED_EXTERNAL_INFRASTRUCTURE
    elif "BLOCKED_EXTERNAL_SIGNER_RECOVERY" in unique_blockers:
        verdict = QualificationVerdict.BLOCKED_EXTERNAL_SIGNER_RECOVERY
    elif any(item.startswith("DUAL_ACTIVE_OBSERVED:") for item in unique_blockers):
        verdict = QualificationVerdict.FAILED
    else:
        verdict = QualificationVerdict.BLOCKED_EVIDENCE
    return HaQualification(
        schema_version=QUALIFICATION_SCHEMA,
        verdict=verdict,
        release_id=value.release_id,
        release_generation=value.release_generation,
        ha_policy_generation=value.ha_policy_generation,
        fencing_backend_id=coordinator.backend_id if coordinator else None,
        campaign_digests=tuple(campaign_digests),
        derived_rpo_seconds=derived_rpo,
        derived_rto_seconds=derived_rto,
        dual_active_verdict="FAILED" if dual_active else "NO_DUAL_ACTIVE_OBSERVED",
        blockers=unique_blockers,
        executable_ha_qualified=not unique_blockers,
    )


def verify_campaign_set_unique(campaigns: Iterable[CampaignEvidence]) -> None:
    seen: dict[str, str] = {}
    for campaign in campaigns:
        digest = campaign.semantic_digest
        previous = seen.get(campaign.campaign_id)
        if previous is None:
            seen[campaign.campaign_id] = digest
        elif previous != digest:
            raise EvidenceBlocked("duplicate campaign id with different semantics")


def verify_takeover_request_identity(
    request_id: str,
    semantic_payload: Mapping[str, Any],
    durable_seen: Mapping[str, str],
) -> str:
    """Return stable digest or reject same takeover id with semantic drift."""
    if not request_id:
        raise ValueError("request_id is required")
    digest = canonical_digest(dict(semantic_payload))
    existing = durable_seen.get(request_id)
    if existing is not None and existing != digest:
        raise TakeoverConflict("takeover request id reused with different semantics")
    return digest
