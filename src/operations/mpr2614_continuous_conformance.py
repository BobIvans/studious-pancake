"""MPR-2614 continuous production-conformance sentinel.

This module is a post-release, fail-closed consumer.  It does not create a
release authority, signer, sender, canary authority, economic ledger, provider
governance authority, or human-approval authority.  A positive decision is a
bounded monotonic lease only; it never enables live execution.

MPR-2614 consumes the accepted-release/operating-envelope contracts introduced
by MPR-2613 and treats PR-201 readiness/deployment objects as observations, not
permission authorities.  This deliberately closes the post-release false
positives where an arbitrarily old or wrong-generation PR-201 snapshot could
look operator-ready.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import re

from .mpr2613_guarded_operations import AcceptedReleaseIdentity, OperatingEnvelope
from .pr201_observability_readiness import (
    DeploymentHardeningSnapshot,
    ManagementReadinessSnapshot,
)

SCHEMA_VERSION = "mpr2614.continuous-production-conformance.v1"
LEASE_SCHEMA_VERSION = "mpr2614.runtime-conformance-lease.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_RE = re.compile(r"^[a-z0-9._/-]+@sha256:([0-9a-f]{64})$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class ConformanceError(ValueError):
    """Malformed conformance evidence or policy."""


@dataclass(frozen=True, slots=True)
class ReleaseConformancePin:
    """Immutable post-release pin derived from accepted release evidence.

    ``release`` is the MPR-2613 adapter for the accepted MPR-2612 decision.
    Extra digests retain identities that PR-201 needs for exact runtime binding
    but that are not all represented in ``AcceptedReleaseIdentity`` itself.
    """

    release: AcceptedReleaseIdentity
    release_generation: int
    source_commit: str
    runtime_image_digest: str
    contract_evidence_hash: str
    qualification_digest: str
    runtime_authority_digest: str
    production_surface_digest: str
    platform_matrix_digest: str
    provider_deployment_digest: str
    receipt_digest: str
    receipt_verified: bool

    def __post_init__(self) -> None:
        _positive_int(self.release_generation, "release_generation")
        for name in (
            "source_commit",
            "contract_evidence_hash",
            "qualification_digest",
            "runtime_authority_digest",
            "production_surface_digest",
            "platform_matrix_digest",
            "provider_deployment_digest",
            "receipt_digest",
        ):
            _sha256(getattr(self, name), name)
        image_hash = _image_hash(self.runtime_image_digest)
        if image_hash != self.release.image_hash:
            raise ConformanceError("MPR2614_PIN_IMAGE_RELEASE_MISMATCH")
        if type(self.receipt_verified) is not bool:
            raise ConformanceError("MPR2614_RECEIPT_VERIFIED_MUST_BE_BOOL")

    @property
    def semantic_digest(self) -> str:
        return _hash_json(
            {
                "schema_version": SCHEMA_VERSION,
                "release": asdict(self.release),
                "release_generation": self.release_generation,
                "source_commit": self.source_commit,
                "runtime_image_digest": self.runtime_image_digest,
                "contract_evidence_hash": self.contract_evidence_hash,
                "qualification_digest": self.qualification_digest,
                "runtime_authority_digest": self.runtime_authority_digest,
                "production_surface_digest": self.production_surface_digest,
                "platform_matrix_digest": self.platform_matrix_digest,
                "provider_deployment_digest": self.provider_deployment_digest,
                "receipt_digest": self.receipt_digest,
                "receipt_verified": self.receipt_verified,
            }
        )


@dataclass(frozen=True, slots=True)
class ConformancePolicy:
    max_snapshot_age_ms: int
    max_future_skew_ms: int
    lease_ttl_ns: int

    def __post_init__(self) -> None:
        _positive_int(self.max_snapshot_age_ms, "max_snapshot_age_ms")
        _nonnegative_int(self.max_future_skew_ms, "max_future_skew_ms")
        _positive_int(self.lease_ttl_ns, "lease_ttl_ns")


@dataclass(frozen=True, slots=True)
class RuntimeConformanceObservation:
    process_id: str
    boot_generation: int
    monotonic_observed_ns: int
    readiness: ManagementReadinessSnapshot
    deployment: DeploymentHardeningSnapshot
    cluster_genesis_hash: str
    provider_set_hash: str
    signer_generation_hash: str
    submission_generation_hash: str
    provider_deployment_digest: str
    unresolved_economic_ambiguity: bool = False
    hard_latch_active: bool = False
    critical_slo_breach: bool = False
    data_loss_detected: bool = False

    def __post_init__(self) -> None:
        _safe_id(self.process_id, "process_id")
        _positive_int(self.boot_generation, "boot_generation")
        _nonnegative_int(self.monotonic_observed_ns, "monotonic_observed_ns")
        for name in (
            "cluster_genesis_hash",
            "provider_set_hash",
            "signer_generation_hash",
            "submission_generation_hash",
            "provider_deployment_digest",
        ):
            _sha256(getattr(self, name), name)
        for name in (
            "unresolved_economic_ambiguity",
            "hard_latch_active",
            "critical_slo_breach",
            "data_loss_detected",
        ):
            if type(getattr(self, name)) is not bool:
                raise ConformanceError(f"MPR2614_INVALID_{name.upper()}")

    @property
    def semantic_digest(self) -> str:
        return _hash_json(
            {
                "schema_version": SCHEMA_VERSION,
                "process_id": self.process_id,
                "boot_generation": self.boot_generation,
                "monotonic_observed_ns": self.monotonic_observed_ns,
                "readiness": {
                    "run_id": self.readiness.run_id,
                    "source_commit": self.readiness.source_commit,
                    "image_digest": self.readiness.image_digest,
                    "config_hash": self.readiness.config_hash,
                    "contract_evidence_hash": self.readiness.contract_evidence_hash,
                    "observed_at_ms": self.readiness.observed_at_ms,
                    "report": self.readiness.evaluate(),
                },
                "deployment": self.deployment.evaluate(),
                "cluster_genesis_hash": self.cluster_genesis_hash,
                "provider_set_hash": self.provider_set_hash,
                "signer_generation_hash": self.signer_generation_hash,
                "submission_generation_hash": self.submission_generation_hash,
                "provider_deployment_digest": self.provider_deployment_digest,
                "unresolved_economic_ambiguity": self.unresolved_economic_ambiguity,
                "hard_latch_active": self.hard_latch_active,
                "critical_slo_breach": self.critical_slo_breach,
                "data_loss_detected": self.data_loss_detected,
            }
        )


@dataclass(frozen=True, slots=True)
class RuntimeConformanceLease:
    release_generation: int
    release_decision_hash: str
    release_pin_digest: str
    operating_envelope_hash: str
    process_id: str
    boot_generation: int
    observation_digest: str
    issued_monotonic_ns: int
    expires_monotonic_ns: int
    schema_version: str = LEASE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != LEASE_SCHEMA_VERSION:
            raise ConformanceError("MPR2614_UNSUPPORTED_LEASE_SCHEMA")
        _positive_int(self.release_generation, "release_generation")
        for name in (
            "release_decision_hash",
            "release_pin_digest",
            "operating_envelope_hash",
            "observation_digest",
        ):
            _sha256(getattr(self, name), name)
        _safe_id(self.process_id, "process_id")
        _positive_int(self.boot_generation, "boot_generation")
        _nonnegative_int(self.issued_monotonic_ns, "issued_monotonic_ns")
        _positive_int(self.expires_monotonic_ns, "expires_monotonic_ns")
        if self.expires_monotonic_ns <= self.issued_monotonic_ns:
            raise ConformanceError("MPR2614_INVALID_LEASE_WINDOW")

    @property
    def semantic_digest(self) -> str:
        return _hash_json(asdict(self))

    def valid_for(
        self,
        *,
        monotonic_now_ns: int,
        release_generation: int,
        release_decision_hash: str,
        process_id: str,
        boot_generation: int,
        hard_latch_active: bool,
    ) -> bool:
        _nonnegative_int(monotonic_now_ns, "monotonic_now_ns")
        if type(hard_latch_active) is not bool:
            return False
        return (
            not hard_latch_active
            and monotonic_now_ns < self.expires_monotonic_ns
            and release_generation == self.release_generation
            and release_decision_hash == self.release_decision_hash
            and process_id == self.process_id
            and boot_generation == self.boot_generation
        )


@dataclass(frozen=True, slots=True)
class ConformanceDecision:
    healthy: bool
    reason_codes: tuple[str, ...]
    lease: RuntimeConformanceLease | None
    suspension_required: bool
    release_generation: int
    observation_digest: str
    live_enabled: bool = False
    signer_allowed: bool = False
    submission_allowed: bool = False
    automatic_rearm_allowed: bool = False


def evaluate_runtime_conformance(
    *,
    pin: ReleaseConformancePin,
    envelope: OperatingEnvelope,
    observation: RuntimeConformanceObservation,
    policy: ConformancePolicy,
    trusted_now_ms: int,
    monotonic_now_ns: int,
    sticky_suspension_active: bool = False,
) -> ConformanceDecision:
    """Evaluate one observation and optionally issue a bounded monotonic lease.

    Wall time is used only to prove freshness of externally timestamped evidence.
    Lease lifetime is monotonic so wall-clock rollback cannot extend authority.
    A sticky suspension blocks positive refresh; recovery must be performed by the
    existing human/release authorities, never by a later green heartbeat.
    """

    _nonnegative_int(trusted_now_ms, "trusted_now_ms")
    _nonnegative_int(monotonic_now_ns, "monotonic_now_ns")
    if type(sticky_suspension_active) is not bool:
        raise ConformanceError("MPR2614_INVALID_STICKY_SUSPENSION")

    reasons: list[str] = []
    readiness_report = observation.readiness.evaluate()
    deployment_report = observation.deployment.evaluate()
    reasons.extend(str(value) for value in readiness_report.get("blockers", ()))
    reasons.extend(str(value) for value in deployment_report.get("blockers", ()))

    if not pin.receipt_verified or not pin.release.accepted:
        reasons.append("MPR2614_RELEASE_RECEIPT_NOT_VERIFIED")
    if sticky_suspension_active:
        reasons.append("MPR2614_STICKY_SUSPENSION_ACTIVE")

    observed_at = observation.readiness.observed_at_ms
    if observed_at > trusted_now_ms + policy.max_future_skew_ms:
        reasons.append("MPR2614_READINESS_FUTURE_DATED")
    elif trusted_now_ms - observed_at > policy.max_snapshot_age_ms:
        reasons.append("MPR2614_READINESS_STALE")

    if observation.monotonic_observed_ns > monotonic_now_ns:
        reasons.append("MPR2614_MONOTONIC_OBSERVATION_FROM_FUTURE")

    if observation.readiness.source_commit != pin.source_commit:
        reasons.append("MPR2614_RELEASE_SOURCE_DRIFT")
    if observation.readiness.image_digest != pin.runtime_image_digest:
        reasons.append("MPR2614_RELEASE_IMAGE_DRIFT")
    if observation.deployment.image_digest != pin.runtime_image_digest:
        reasons.append("MPR2614_DEPLOYMENT_IMAGE_DRIFT")
    if observation.readiness.config_hash != pin.release.config_hash:
        reasons.append("MPR2614_RELEASE_CONFIG_DRIFT")
    if observation.readiness.contract_evidence_hash != pin.contract_evidence_hash:
        reasons.append("MPR2614_RELEASE_CONTRACT_EVIDENCE_DRIFT")
    if observation.provider_deployment_digest != pin.provider_deployment_digest:
        reasons.append("MPR2614_PROVIDER_DEPLOYMENT_DRIFT")

    if envelope.release != pin.release:
        reasons.append("MPR2614_OPERATING_RELEASE_DRIFT")
    if envelope.cluster_genesis_hash != observation.cluster_genesis_hash:
        reasons.append("MPR2614_CLUSTER_GENESIS_DRIFT")
    if envelope.provider_set_hash != observation.provider_set_hash:
        reasons.append("MPR2614_PROVIDER_GENERATION_DRIFT")
    if envelope.signer_generation_hash != observation.signer_generation_hash:
        reasons.append("MPR2614_SIGNER_GENERATION_DRIFT")
    if envelope.submission_generation_hash != observation.submission_generation_hash:
        reasons.append("MPR2614_SUBMISSION_GENERATION_DRIFT")

    if observation.unresolved_economic_ambiguity:
        reasons.append("MPR2614_UNRESOLVED_ECONOMIC_AMBIGUITY")
    if observation.hard_latch_active:
        reasons.append("MPR2614_HARD_LATCH_ACTIVE")
    if observation.critical_slo_breach:
        reasons.append("MPR2614_CRITICAL_SLO_BREACH")
    if observation.data_loss_detected:
        reasons.append("MPR2614_DATA_LOSS_DETECTED")

    try:
        release_expiry_ms = int(_parse_utc(pin.release.expires_at_utc).timestamp() * 1000)
    except (ValueError, OverflowError) as exc:
        raise ConformanceError("MPR2614_INVALID_RELEASE_EXPIRY") from exc
    if trusted_now_ms >= release_expiry_ms:
        reasons.append("MPR2614_ACCEPTED_RELEASE_EXPIRED")

    reasons = sorted(set(reasons))
    lease: RuntimeConformanceLease | None = None
    if not reasons:
        lease = RuntimeConformanceLease(
            release_generation=pin.release_generation,
            release_decision_hash=pin.release.release_decision_hash,
            release_pin_digest=pin.semantic_digest,
            operating_envelope_hash=envelope.envelope_hash,
            process_id=observation.process_id,
            boot_generation=observation.boot_generation,
            observation_digest=observation.semantic_digest,
            issued_monotonic_ns=monotonic_now_ns,
            expires_monotonic_ns=monotonic_now_ns + policy.lease_ttl_ns,
        )

    return ConformanceDecision(
        healthy=lease is not None,
        reason_codes=tuple(reasons),
        lease=lease,
        suspension_required=bool(reasons),
        release_generation=pin.release_generation,
        observation_digest=observation.semantic_digest,
        live_enabled=False,
        signer_allowed=False,
        submission_allowed=False,
        automatic_rearm_allowed=False,
    )


def _image_hash(value: str) -> str:
    if not isinstance(value, str):
        raise ConformanceError("MPR2614_INVALID_RUNTIME_IMAGE_DIGEST")
    match = _IMAGE_RE.fullmatch(value)
    if not match:
        raise ConformanceError("MPR2614_INVALID_RUNTIME_IMAGE_DIGEST")
    return match.group(1)


def _parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("UTC timestamp must end in Z")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo != timezone.utc:
        raise ValueError("timestamp must be UTC")
    return parsed


def _sha256(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ConformanceError(f"MPR2614_INVALID_{name.upper()}")


def _safe_id(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ConformanceError(f"MPR2614_INVALID_{name.upper()}")


def _positive_int(value: int, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ConformanceError(f"MPR2614_INVALID_{name.upper()}")


def _nonnegative_int(value: int, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ConformanceError(f"MPR2614_INVALID_{name.upper()}")


def _hash_json(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ConformanceDecision",
    "ConformanceError",
    "ConformancePolicy",
    "LEASE_SCHEMA_VERSION",
    "ReleaseConformancePin",
    "RuntimeConformanceLease",
    "RuntimeConformanceObservation",
    "SCHEMA_VERSION",
    "evaluate_runtime_conformance",
]
