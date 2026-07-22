"""MEGA-PR D2 real soak and release artifact bundling.

This module is an active, offline evidence-bundle producer for real sender-free
soak and release-candidate artifacts.  It hashes actual files supplied by the
operator/CI job and fails closed for synthetic soak claims, missing artifacts,
sender/submission evidence, unreconciled terminal gaps, reservation leaks and
non-pinned release identities.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

D2_SCHEMA_VERSION = "mega-pr-d2.real-soak-release-artifacts.v1"
D2_MIN_REVIEWED_SOAK_SECONDS = 72 * 60 * 60

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_DIGEST_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SECRET_MARKERS = (
    "authorization:",
    "bearer ",
    "api_key",
    "auth_header",
    "private_key",
    "secret_key",
    "x-api-key",
)


class D2ArtifactKind(StrEnum):
    WHEEL = "wheel"
    WHEELHOUSE = "wheelhouse"
    IMAGE_DIGEST = "image-digest"
    SBOM = "sbom"
    DEPENDENCY_GRAPH = "dependency-graph"
    PROVENANCE = "provenance"
    SOURCE_WHEEL_PARITY = "source-wheel-parity"
    POLICY_BUNDLE = "policy-bundle"
    PROVIDER_CONTRACTS = "provider-contracts"
    SOAK_SUMMARY = "soak-summary"
    SOAK_EVENTS = "soak-events"
    RESOURCE_METRICS = "resource-metrics"
    RESTART_RECOVERY = "restart-recovery"


class D2Readiness(StrEnum):
    READY_FOR_REVIEW = "ready-for-review"
    BLOCKED = "blocked"


_REQUIRED_RELEASE_KINDS = (
    D2ArtifactKind.WHEEL,
    D2ArtifactKind.WHEELHOUSE,
    D2ArtifactKind.IMAGE_DIGEST,
    D2ArtifactKind.SBOM,
    D2ArtifactKind.DEPENDENCY_GRAPH,
    D2ArtifactKind.PROVENANCE,
    D2ArtifactKind.SOURCE_WHEEL_PARITY,
    D2ArtifactKind.POLICY_BUNDLE,
    D2ArtifactKind.PROVIDER_CONTRACTS,
)
_REQUIRED_SOAK_KINDS = (
    D2ArtifactKind.SOAK_SUMMARY,
    D2ArtifactKind.SOAK_EVENTS,
    D2ArtifactKind.RESOURCE_METRICS,
    D2ArtifactKind.RESTART_RECOVERY,
)


@dataclass(frozen=True, slots=True)
class D2Artifact:
    kind: D2ArtifactKind
    uri: str
    sha256: str
    size_bytes: int
    produced_by: str
    media_type: str = "application/octet-stream"

    def __post_init__(self) -> None:
        _require_sha256("artifact.sha256", self.sha256)
        if self.size_bytes <= 0:
            raise ValueError("artifact size_bytes must be positive")
        _require_safe_text("artifact.uri", self.uri)
        _require_safe_text("artifact.produced_by", self.produced_by)
        _require_safe_text("artifact.media_type", self.media_type)
        if not self.produced_by.strip():
            raise ValueError("artifact produced_by is required")

    @classmethod
    def from_path(
        cls,
        *,
        kind: D2ArtifactKind,
        path: Path,
        produced_by: str,
        media_type: str = "application/octet-stream",
    ) -> "D2Artifact":
        if not path.is_file():
            raise ValueError(f"artifact path is not a file: {path}")
        data = path.read_bytes()
        return cls(
            kind=kind,
            uri=f"file:{path}",
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            produced_by=produced_by,
            media_type=media_type,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["kind"] = self.kind.value
        return payload


@dataclass(frozen=True, slots=True)
class D2ReleaseIdentity:
    source_commit: str
    release_digest: str
    policy_bundle_sha256: str
    image_digest: str
    wheel_sha256: str
    build_twice_comparison_sha256: str
    docker_base_digest: str
    action_full_sha_review_sha256: str

    def __post_init__(self) -> None:
        if not _COMMIT_RE.fullmatch(self.source_commit) or self.source_commit == "0" * 40:
            raise ValueError("source_commit must be a non-placeholder full git SHA")
        _require_release_digest("release_digest", self.release_digest)
        _require_release_digest("image_digest", self.image_digest)
        _require_release_digest("docker_base_digest", self.docker_base_digest)
        _require_sha256("policy_bundle_sha256", self.policy_bundle_sha256)
        _require_sha256("wheel_sha256", self.wheel_sha256)
        _require_sha256(
            "build_twice_comparison_sha256", self.build_twice_comparison_sha256
        )
        _require_sha256(
            "action_full_sha_review_sha256", self.action_full_sha_review_sha256
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class D2SoakEvidence:
    release_digest: str
    policy_bundle_sha256: str
    started_at: datetime
    finished_at: datetime
    reviewed_duration_seconds: int
    non_synthetic: bool
    pinned_wheel: bool
    pinned_image: bool
    pinned_policy: bool
    sender_imports_detected: bool
    signer_imports_detected: bool
    signatures_observed: int
    submissions_observed: int
    candidates_seen: int
    terminal_outcomes: Mapping[str, int]
    unreconciled_terminal_gaps: int
    reservation_leaks: int
    data_gaps: int
    restart_recovery_passed: bool
    cancellation_recovery_passed: bool
    resource_limits_passed: bool
    fixture_rows_excluded: bool

    def __post_init__(self) -> None:
        _require_release_digest("release_digest", self.release_digest)
        _require_sha256("policy_bundle_sha256", self.policy_bundle_sha256)
        _require_time("started_at", self.started_at)
        _require_time("finished_at", self.finished_at)
        if self.finished_at <= self.started_at:
            raise ValueError("finished_at must be after started_at")
        if self.reviewed_duration_seconds <= 0:
            raise ValueError("reviewed_duration_seconds must be positive")
        if self.signatures_observed < 0 or self.submissions_observed < 0:
            raise ValueError("observed signature/submission counts cannot be negative")
        if min(
            self.candidates_seen,
            self.unreconciled_terminal_gaps,
            self.reservation_leaks,
            self.data_gaps,
        ) < 0:
            raise ValueError("soak counters cannot be negative")

    @property
    def observed_duration_seconds(self) -> int:
        return int((self.finished_at - self.started_at).total_seconds())

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.observed_duration_seconds < self.reviewed_duration_seconds:
            blockers.append("SOAK_DURATION_BELOW_REVIEWED_DURATION")
        if self.reviewed_duration_seconds < D2_MIN_REVIEWED_SOAK_SECONDS:
            blockers.append("SOAK_REVIEWED_DURATION_TOO_SHORT_FOR_D2")
        if not self.non_synthetic:
            blockers.append("SOAK_SYNTHETIC_OR_FIXTURE_CONTAMINATED")
        if not self.fixture_rows_excluded:
            blockers.append("SOAK_FIXTURE_ROWS_NOT_EXCLUDED")
        if not self.pinned_wheel:
            blockers.append("SOAK_WHEEL_NOT_PINNED")
        if not self.pinned_image:
            blockers.append("SOAK_IMAGE_NOT_PINNED")
        if not self.pinned_policy:
            blockers.append("SOAK_POLICY_NOT_PINNED")
        if self.sender_imports_detected:
            blockers.append("SOAK_SENDER_IMPORT_REACHABLE")
        if self.signer_imports_detected:
            blockers.append("SOAK_SIGNER_IMPORT_REACHABLE")
        if self.signatures_observed:
            blockers.append("SOAK_SIGNATURES_OBSERVED")
        if self.submissions_observed:
            blockers.append("SOAK_SUBMISSIONS_OBSERVED")
        if self.unreconciled_terminal_gaps:
            blockers.append("SOAK_UNRECONCILED_TERMINAL_GAPS")
        if self.reservation_leaks:
            blockers.append("SOAK_RESERVATION_LEAKS")
        if self.data_gaps:
            blockers.append("SOAK_DATA_GAPS")
        if not self.restart_recovery_passed:
            blockers.append("SOAK_RESTART_RECOVERY_NOT_PROVEN")
        if not self.cancellation_recovery_passed:
            blockers.append("SOAK_CANCELLATION_RECOVERY_NOT_PROVEN")
        if not self.resource_limits_passed:
            blockers.append("SOAK_RESOURCE_LIMITS_NOT_PROVEN")
        if not self.terminal_outcomes:
            blockers.append("SOAK_TERMINAL_OUTCOMES_MISSING")
        return tuple(dict.fromkeys(blockers))

    def to_dict(self) -> dict[str, Any]:
        return {
            "release_digest": self.release_digest,
            "policy_bundle_sha256": self.policy_bundle_sha256,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "reviewed_duration_seconds": self.reviewed_duration_seconds,
            "observed_duration_seconds": self.observed_duration_seconds,
            "non_synthetic": self.non_synthetic,
            "pinned_wheel": self.pinned_wheel,
            "pinned_image": self.pinned_image,
            "pinned_policy": self.pinned_policy,
            "sender_imports_detected": self.sender_imports_detected,
            "signer_imports_detected": self.signer_imports_detected,
            "signatures_observed": self.signatures_observed,
            "submissions_observed": self.submissions_observed,
            "candidates_seen": self.candidates_seen,
            "terminal_outcomes": dict(sorted(self.terminal_outcomes.items())),
            "unreconciled_terminal_gaps": self.unreconciled_terminal_gaps,
            "reservation_leaks": self.reservation_leaks,
            "data_gaps": self.data_gaps,
            "restart_recovery_passed": self.restart_recovery_passed,
            "cancellation_recovery_passed": self.cancellation_recovery_passed,
            "resource_limits_passed": self.resource_limits_passed,
            "fixture_rows_excluded": self.fixture_rows_excluded,
            "blockers": list(self.blockers()),
        }


@dataclass(frozen=True, slots=True)
class D2ReleaseSoakBundle:
    release: D2ReleaseIdentity
    soak: D2SoakEvidence
    artifacts: tuple[D2Artifact, ...]
    generated_at: datetime
    generator: str = "mega-pr-d2-release-soak-bundler"
    schema_version: str = D2_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != D2_SCHEMA_VERSION:
            raise ValueError("unsupported D2 bundle schema")
        _require_time("generated_at", self.generated_at)
        _require_safe_text("generator", self.generator)
        if self.release.release_digest != self.soak.release_digest:
            raise ValueError("soak and release digest mismatch")
        if self.release.policy_bundle_sha256 != self.soak.policy_bundle_sha256:
            raise ValueError("soak and release policy mismatch")
        kinds = [artifact.kind for artifact in self.artifacts]
        if len(kinds) != len(set(kinds)):
            raise ValueError("duplicate D2 artifact kind")
        image_artifact = _artifact_by_kind(self.artifacts, D2ArtifactKind.IMAGE_DIGEST)
        if image_artifact is not None and not self.release.image_digest.endswith(
            image_artifact.sha256
        ):
            raise ValueError("image digest artifact does not match release identity")
        wheel_artifact = _artifact_by_kind(self.artifacts, D2ArtifactKind.WHEEL)
        if wheel_artifact is not None and wheel_artifact.sha256 != self.release.wheel_sha256:
            raise ValueError("wheel artifact does not match release identity")

    @property
    def bundle_hash(self) -> str:
        return _hash_json(self.to_dict(include_hash=False))

    def missing_artifact_kinds(self) -> tuple[str, ...]:
        present = {artifact.kind for artifact in self.artifacts}
        required = (*_REQUIRED_RELEASE_KINDS, *_REQUIRED_SOAK_KINDS)
        return tuple(kind.value for kind in required if kind not in present)

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        blockers.extend(f"MISSING_ARTIFACT:{kind}" for kind in self.missing_artifact_kinds())
        blockers.extend(self.soak.blockers())
        return tuple(dict.fromkeys(blockers))

    @property
    def readiness(self) -> D2Readiness:
        return D2Readiness.BLOCKED if self.blockers() else D2Readiness.READY_FOR_REVIEW

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "generator": self.generator,
            "generated_at": self.generated_at.isoformat(),
            "readiness": self.readiness.value,
            "release": self.release.to_dict(),
            "soak": self.soak.to_dict(),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "missing_artifact_kinds": list(self.missing_artifact_kinds()),
            "blockers": list(self.blockers()),
            "live_enabled": False,
            "canary_auto_enabled": False,
            "sender_reachable": False,
            "signer_reachable": False,
        }
        if include_hash:
            payload["bundle_hash"] = self.bundle_hash
        return payload


def bundle_from_manifest(data: Mapping[str, Any], *, base_dir: Path | None = None) -> D2ReleaseSoakBundle:
    """Build and validate a D2 bundle from a JSON-compatible manifest.

    Artifact entries may either provide an explicit ``sha256``/``size_bytes`` pair
    or a local ``path`` that is read and hashed by this producer.
    """

    release = D2ReleaseIdentity(**data["release"])
    soak = _soak_from_mapping(data["soak"])
    produced_by = str(data.get("produced_by", "operator-d2-evidence-job"))
    artifacts = tuple(
        _artifact_from_mapping(item, base_dir=base_dir, produced_by=produced_by)
        for item in data.get("artifacts", ())
    )
    generated_at = _parse_time(data.get("generated_at")) if data.get("generated_at") else datetime.now(timezone.utc)
    return D2ReleaseSoakBundle(
        release=release,
        soak=soak,
        artifacts=artifacts,
        generated_at=generated_at,
        generator=str(data.get("generator", "mega-pr-d2-release-soak-bundler")),
    )


def render_bundle_json(bundle: D2ReleaseSoakBundle) -> str:
    return json.dumps(bundle.to_dict(), indent=2, sort_keys=True) + "\n"


def _artifact_from_mapping(
    item: Mapping[str, Any],
    *,
    base_dir: Path | None,
    produced_by: str,
) -> D2Artifact:
    kind = D2ArtifactKind(str(item["kind"]))
    media_type = str(item.get("media_type", "application/octet-stream"))
    item_produced_by = str(item.get("produced_by", produced_by))
    if "path" in item:
        path = Path(str(item["path"]))
        if base_dir is not None and not path.is_absolute():
            path = base_dir / path
        return D2Artifact.from_path(
            kind=kind,
            path=path,
            produced_by=item_produced_by,
            media_type=media_type,
        )
    return D2Artifact(
        kind=kind,
        uri=str(item["uri"]),
        sha256=str(item["sha256"]),
        size_bytes=int(item["size_bytes"]),
        produced_by=item_produced_by,
        media_type=media_type,
    )


def _soak_from_mapping(data: Mapping[str, Any]) -> D2SoakEvidence:
    payload = dict(data)
    payload.pop("observed_duration_seconds", None)
    payload.pop("blockers", None)
    payload["started_at"] = _parse_time(payload["started_at"])
    payload["finished_at"] = _parse_time(payload["finished_at"])
    return D2SoakEvidence(**payload)


def _artifact_by_kind(
    artifacts: Sequence[D2Artifact], kind: D2ArtifactKind
) -> D2Artifact | None:
    for artifact in artifacts:
        if artifact.kind is kind:
            return artifact
    return None


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    _require_time("timestamp", parsed)
    return parsed


def _require_release_digest(field_name: str, value: str) -> None:
    if not _RELEASE_DIGEST_RE.fullmatch(value) or value.endswith("0" * 64):
        raise ValueError(f"{field_name} must be sha256-bound")


def _require_sha256(field_name: str, value: str) -> None:
    if not _SHA256_RE.fullmatch(value) or value == "0" * 64:
        raise ValueError(f"{field_name} must be a real lowercase sha256 digest")


def _require_time(field_name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_safe_text(field_name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} is required")
    lowered = value.lower()
    if any(marker in lowered for marker in _SECRET_MARKERS):
        raise ValueError(f"{field_name} must not contain secret-bearing text")


def _hash_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "D2Artifact",
    "D2ArtifactKind",
    "D2_MIN_REVIEWED_SOAK_SECONDS",
    "D2Readiness",
    "D2ReleaseIdentity",
    "D2ReleaseSoakBundle",
    "D2_SCHEMA_VERSION",
    "D2SoakEvidence",
    "bundle_from_manifest",
    "render_bundle_json",
]
