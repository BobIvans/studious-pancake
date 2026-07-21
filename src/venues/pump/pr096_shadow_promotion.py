"""PR-096 Pump real shadow-promotion evidence gate.

This module is intentionally read-only.  It does not discover opportunities,
compile transactions, sign, submit, or enable live/canary execution.  PR-096
only accepts a materialized, human-reviewed Pump shadow-promotion package after
current official source, IDL, RPC fixture, exact simulation, reconciliation and
separate soak evidence are present.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum, StrEnum
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from src.shadow_soak.evidence import (
    MINIMUM_SOAK_SECONDS,
    ShadowSoakError,
    ShadowSoakEvidence,
    ShadowSoakThresholds,
    SoakEnvironment,
    evaluate_shadow_soak,
)

from .adapter import PumpContractManifest
from .models import PumpFamily

PR096_PUMP_SCHEMA_VERSION = "pr096.pump-real-shadow-promotion.v1"
PR096_PUMP_RESULT_SCHEMA_VERSION = "pr096.pump-real-shadow-promotion-result.v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_URI_PREFIXES = ("https://", "s3://", "gs://")
_FORBIDDEN_PATH_PARTS = {
    "",
    ".",
    "..",
    "fixture",
    "fixtures",
    "testdata",
    "tmp",
    "temp",
}


class PumpPR096State(StrEnum):
    """Manual-review state for Pump PR-096."""

    BLOCKED = "blocked"
    READY_FOR_MANUAL_SHADOW_REVIEW = "ready-for-manual-shadow-review"


class PumpPR096ArtifactKind(StrEnum):
    """Materialized artifacts required before Pump PR-096 can pass."""

    OFFICIAL_SOURCE = "official-source"
    IDL = "idl"
    LAYOUT_VECTOR = "layout-vector"
    DISCRIMINATOR_VECTOR = "discriminator-vector"
    RPC_FIXTURE = "rpc-fixture"
    TOKEN_POLICY = "token-policy"
    EXACT_SIMULATION = "exact-simulation"
    RECONCILIATION = "reconciliation"
    SEPARATE_SOAK_BUNDLE = "separate-soak-bundle"
    OPERATOR_REVIEW = "operator-review"


REQUIRED_PUMP_PR096_ARTIFACTS: tuple[PumpPR096ArtifactKind, ...] = (
    PumpPR096ArtifactKind.OFFICIAL_SOURCE,
    PumpPR096ArtifactKind.IDL,
    PumpPR096ArtifactKind.LAYOUT_VECTOR,
    PumpPR096ArtifactKind.DISCRIMINATOR_VECTOR,
    PumpPR096ArtifactKind.RPC_FIXTURE,
    PumpPR096ArtifactKind.TOKEN_POLICY,
    PumpPR096ArtifactKind.EXACT_SIMULATION,
    PumpPR096ArtifactKind.RECONCILIATION,
    PumpPR096ArtifactKind.SEPARATE_SOAK_BUNDLE,
    PumpPR096ArtifactKind.OPERATOR_REVIEW,
)


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ShadowSoakError(f"{field} must be timezone-aware")


def _sha256(value: str, field: str) -> str:
    lowered = value.lower()
    if not _SHA256_RE.fullmatch(lowered) or lowered == "0" * 64:
        raise ShadowSoakError(f"{field} must be a non-placeholder sha256")
    if len(set(lowered)) < 8:
        raise ShadowSoakError(f"{field} must not be a low-entropy fixture sha256")
    return lowered


def _git_sha(value: str, field: str) -> str:
    lowered = value.lower()
    if not _GIT_SHA_RE.fullmatch(lowered) or lowered == "0" * 40:
        raise ShadowSoakError(f"{field} must be a non-placeholder git SHA")
    if len(set(lowered)) < 8:
        raise ShadowSoakError(f"{field} must not be a low-entropy fixture git SHA")
    return lowered


def _relative_path_or_uri(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ShadowSoakError(f"{field} is required")
    if cleaned.startswith(_URI_PREFIXES):
        return cleaned
    normalized = cleaned.replace("\\", "/")
    parts = normalized.split("/")
    if normalized.startswith(("/", "~")) or any(
        part.lower() in _FORBIDDEN_PATH_PARTS for part in parts
    ):
        raise ShadowSoakError(
            f"{field} must be a normalized non-fixture relative path or URI"
        )
    return normalized


def _is_uri(value: str) -> bool:
    return value.startswith(_URI_PREFIXES)


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {
            item.name: _jsonable(getattr(value, item.name)) for item in fields(value)
        }
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _stable_json(payload: Any) -> str:
    return json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"))


def _sha256_payload(payload: Any) -> str:
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PumpPR096ArtifactPin:
    """Digest-pinned artifact file or immutable storage object."""

    kind: PumpPR096ArtifactKind
    path: str
    sha256: str
    size_bytes: int
    produced_at: datetime
    producer: str
    family: PumpFamily | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PumpPR096ArtifactKind):
            object.__setattr__(self, "kind", PumpPR096ArtifactKind(str(self.kind)))
        if self.family is not None and not isinstance(self.family, PumpFamily):
            object.__setattr__(self, "family", PumpFamily(str(self.family)))
        object.__setattr__(self, "path", _relative_path_or_uri(self.path, "path"))
        object.__setattr__(self, "sha256", _sha256(self.sha256, "sha256"))
        if isinstance(self.size_bytes, bool) or self.size_bytes <= 0:
            raise ShadowSoakError("size_bytes must be a positive integer")
        _aware(self.produced_at, "produced_at")
        if not self.producer.strip():
            raise ShadowSoakError("producer is required")


@dataclass(frozen=True, slots=True)
class PumpPR096FamilyEvidence:
    """Per-family Pump source, IDL, RPC, Token and reconciliation proof."""

    family: PumpFamily
    official_source_url: str
    official_source_commit: str
    idl_sha256: str
    layout_vector_sha256: str
    discriminator_vector_sha256: str
    rpc_fixture_sha256: str
    exact_simulation_sha256: str
    reconciliation_sha256: str
    token_program_verified: bool
    token_2022_policy_verified: bool
    human_reviewed: bool
    reviewer: str

    def __post_init__(self) -> None:
        if not isinstance(self.family, PumpFamily):
            object.__setattr__(self, "family", PumpFamily(str(self.family)))
        object.__setattr__(
            self,
            "official_source_url",
            _relative_path_or_uri(self.official_source_url, "official_source_url"),
        )
        object.__setattr__(
            self,
            "official_source_commit",
            _git_sha(self.official_source_commit, "official_source_commit"),
        )
        for name in (
            "idl_sha256",
            "layout_vector_sha256",
            "discriminator_vector_sha256",
            "rpc_fixture_sha256",
            "exact_simulation_sha256",
            "reconciliation_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        for name in (
            "token_program_verified",
            "token_2022_policy_verified",
            "human_reviewed",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ShadowSoakError(f"{name} must be boolean")
        if self.human_reviewed and not self.reviewer.strip():
            raise ShadowSoakError("reviewed Pump family evidence requires reviewer")


@dataclass(frozen=True, slots=True)
class PumpPR096PromotionPackage:
    """Complete Pump PR-096 package for manual shadow-promotion review."""

    run_id: str
    release_candidate_commit: str
    families: tuple[PumpPR096FamilyEvidence, ...]
    artifacts: tuple[PumpPR096ArtifactPin, ...]
    soak: ShadowSoakEvidence
    assembled_at: datetime
    assembled_by: str
    reviewed_by: str
    separate_soak_from_core_runtime: bool
    deterministic_replay_verified: bool
    no_sender_imports_observed: bool
    sender_endpoints_enabled: bool
    live_submissions_observed: int
    schema_version: str = PR096_PUMP_SCHEMA_VERSION
    notes: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != PR096_PUMP_SCHEMA_VERSION:
            raise ShadowSoakError("unsupported Pump PR-096 schema")
        if not self.run_id.strip():
            raise ShadowSoakError("run_id is required")
        if self.run_id != self.soak.run_id:
            raise ShadowSoakError("package.run_id must match soak.run_id")
        object.__setattr__(
            self,
            "release_candidate_commit",
            _git_sha(self.release_candidate_commit, "release_candidate_commit"),
        )
        if self.release_candidate_commit != self.soak.code_commit:
            raise ShadowSoakError(
                "release candidate commit must match soak code_commit"
            )
        if not self.families:
            raise ShadowSoakError("at least one Pump family evidence item is required")
        family_ids = [item.family for item in self.families]
        if len(family_ids) != len(set(family_ids)):
            raise ShadowSoakError("Pump family evidence must be unique")
        if not self.artifacts:
            raise ShadowSoakError("Pump PR-096 artifacts are required")
        artifact_keys = [(item.kind, item.family) for item in self.artifacts]
        if len(artifact_keys) != len(set(artifact_keys)):
            raise ShadowSoakError("Pump PR-096 artifact pins must be unique")
        _aware(self.assembled_at, "assembled_at")
        if self.assembled_at < self.soak.reviewed_at:
            raise ShadowSoakError("assembled_at cannot be before soak review")
        if not self.assembled_by.strip():
            raise ShadowSoakError("assembled_by is required")
        if not self.reviewed_by.strip():
            raise ShadowSoakError("reviewed_by is required")
        for name in (
            "separate_soak_from_core_runtime",
            "deterministic_replay_verified",
            "no_sender_imports_observed",
            "sender_endpoints_enabled",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ShadowSoakError(f"{name} must be boolean")
        if (
            isinstance(self.live_submissions_observed, bool)
            or self.live_submissions_observed < 0
        ):
            raise ShadowSoakError("live_submissions_observed must be non-negative int")

    @property
    def package_sha256(self) -> str:
        return _sha256_payload(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class PumpPR096ArtifactCheck:
    """Local materialization/hash result for Pump PR-096 artifacts."""

    checked: bool
    checked_paths: tuple[str, ...]
    missing_paths: tuple[str, ...]
    hash_mismatches: tuple[str, ...]
    size_mismatches: tuple[str, ...]
    unsupported_uris: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return (
            self.checked
            and not self.missing_paths
            and not self.hash_mismatches
            and not self.size_mismatches
            and not self.unsupported_uris
        )

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class PumpPR096PromotionReport:
    """Fail-closed PR-096 decision that never enables live execution."""

    run_id: str
    state: PumpPR096State
    shadow_promotion_ready: bool
    live_allowed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    required_families: int
    package_sha256: str
    soak_evidence_sha256: str
    duration_seconds: int
    candidates_seen: int
    artifact_check: PumpPR096ArtifactCheck
    schema_version: str = PR096_PUMP_RESULT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def check_pump_pr096_materialized_artifacts(
    package: PumpPR096PromotionPackage,
    artifact_root: Path | None,
) -> PumpPR096ArtifactCheck:
    """Hash PR-096 artifact files under ``artifact_root``.

    Passing ``None`` fails closed.  Remote URIs can be kept for provenance in
    external records, but this gate only passes after artifact bytes are locally
    materialized and hashed.
    """

    if artifact_root is None:
        return PumpPR096ArtifactCheck(
            checked=False,
            checked_paths=(),
            missing_paths=(),
            hash_mismatches=(),
            size_mismatches=(),
            unsupported_uris=(),
        )

    root = artifact_root.resolve()
    checked_paths: list[str] = []
    missing_paths: list[str] = []
    hash_mismatches: list[str] = []
    size_mismatches: list[str] = []
    unsupported_uris: list[str] = []

    for artifact in package.artifacts:
        if _is_uri(artifact.path):
            unsupported_uris.append(artifact.path)
            continue
        candidate = (root / artifact.path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            missing_paths.append(artifact.path)
            continue
        if not candidate.is_file():
            missing_paths.append(artifact.path)
            continue
        payload = candidate.read_bytes()
        checked_paths.append(artifact.path)
        if hashlib.sha256(payload).hexdigest() != artifact.sha256:
            hash_mismatches.append(artifact.path)
        if len(payload) != artifact.size_bytes:
            size_mismatches.append(artifact.path)

    return PumpPR096ArtifactCheck(
        checked=True,
        checked_paths=tuple(checked_paths),
        missing_paths=tuple(missing_paths),
        hash_mismatches=tuple(hash_mismatches),
        size_mismatches=tuple(size_mismatches),
        unsupported_uris=tuple(unsupported_uris),
    )


def evaluate_pump_pr096_shadow_promotion(
    package: PumpPR096PromotionPackage,
    *,
    manifest: PumpContractManifest | None = None,
    artifact_root: Path | None = None,
    thresholds: ShadowSoakThresholds | None = None,
) -> PumpPR096PromotionReport:
    """Evaluate Pump PR-096 evidence without enabling sender/live execution."""

    manifest = manifest or PumpContractManifest.load()
    policy = thresholds or ShadowSoakThresholds(
        min_duration_seconds=MINIMUM_SOAK_SECONDS,
        min_candidates_seen=1,
        min_reconciled_outcomes=1,
    )
    fresh_soak = evaluate_shadow_soak(package.soak, policy)
    artifact_check = check_pump_pr096_materialized_artifacts(package, artifact_root)
    blockers: list[str] = []
    warnings: list[str] = list(fresh_soak.warnings)

    def block(condition: bool, reason: str) -> None:
        if not condition:
            blockers.append(reason)

    manifest_errors = manifest.shadow_errors()
    for error in manifest_errors:
        blockers.append(f"MANIFEST_SHADOW_ERROR:{error}")
    block(
        manifest.live_capability == "DENIED_SHADOW_ONLY",
        "MANIFEST_LIVE_CAPABILITY_MUST_REMAIN_DENIED",
    )
    block(
        package.soak.environment
        in {SoakEnvironment.SHADOW, SoakEnvironment.MAINNET_READ_ONLY},
        "PUMP_PR096_RECORDED_FIXTURE_NOT_ALLOWED",
    )
    block(fresh_soak.promotion_ready, "PUMP_PR096_SOAK_EVALUATION_BLOCKED")
    for reason in fresh_soak.blockers:
        blockers.append(f"SOAK:{reason}")

    expected_families = {spec.family for spec in manifest.specs}
    evidence_by_family = {item.family: item for item in package.families}
    for family in expected_families:
        evidence = evidence_by_family.get(family)
        if evidence is None:
            blockers.append(f"PUMP_FAMILY_EVIDENCE_MISSING:{family.value}")
            continue
        block(
            evidence.token_program_verified,
            f"PUMP_TOKEN_PROGRAM_NOT_VERIFIED:{family.value}",
        )
        block(
            evidence.token_2022_policy_verified,
            f"PUMP_TOKEN_2022_POLICY_NOT_VERIFIED:{family.value}",
        )
        block(evidence.human_reviewed, f"PUMP_FAMILY_NOT_REVIEWED:{family.value}")

    extra_families = set(evidence_by_family) - expected_families
    for family in sorted(extra_families, key=lambda item: item.value):
        blockers.append(f"PUMP_UNKNOWN_FAMILY_EVIDENCE:{family.value}")

    artifact_keys = {(item.kind, item.family) for item in package.artifacts}
    for kind in REQUIRED_PUMP_PR096_ARTIFACTS:
        block((kind, None) in artifact_keys, f"PUMP_ARTIFACT_MISSING:{kind.value}")
    for family in expected_families:
        for kind in (
            PumpPR096ArtifactKind.IDL,
            PumpPR096ArtifactKind.LAYOUT_VECTOR,
            PumpPR096ArtifactKind.DISCRIMINATOR_VECTOR,
            PumpPR096ArtifactKind.RPC_FIXTURE,
            PumpPR096ArtifactKind.EXACT_SIMULATION,
            PumpPR096ArtifactKind.RECONCILIATION,
        ):
            block(
                (kind, family) in artifact_keys,
                f"PUMP_FAMILY_ARTIFACT_MISSING:{family.value}:{kind.value}",
            )

    block(artifact_check.checked, "PUMP_PR096_MATERIALIZED_ARTIFACT_CHECK_NOT_RUN")
    for path in artifact_check.unsupported_uris:
        blockers.append(f"PUMP_PR096_ARTIFACT_URI_NOT_MATERIALIZED:{path}")
    for path in artifact_check.missing_paths:
        blockers.append(f"PUMP_PR096_ARTIFACT_FILE_MISSING:{path}")
    for path in artifact_check.hash_mismatches:
        blockers.append(f"PUMP_PR096_ARTIFACT_HASH_MISMATCH:{path}")
    for path in artifact_check.size_mismatches:
        blockers.append(f"PUMP_PR096_ARTIFACT_SIZE_MISMATCH:{path}")

    block(package.separate_soak_from_core_runtime, "PUMP_PR096_SEPARATE_SOAK_REQUIRED")
    block(
        package.deterministic_replay_verified,
        "PUMP_PR096_DETERMINISTIC_REPLAY_NOT_VERIFIED",
    )
    block(
        package.no_sender_imports_observed,
        "PUMP_PR096_SENDER_IMPORT_OBSERVED",
    )
    block(
        not package.sender_endpoints_enabled,
        "PUMP_PR096_SENDER_ENDPOINT_ENABLED",
    )
    block(
        package.live_submissions_observed == 0,
        "PUMP_PR096_LIVE_SUBMISSIONS_OBSERVED",
    )

    unique_blockers = tuple(dict.fromkeys(blockers))
    ready = not unique_blockers
    return PumpPR096PromotionReport(
        run_id=package.run_id,
        state=(
            PumpPR096State.READY_FOR_MANUAL_SHADOW_REVIEW
            if ready
            else PumpPR096State.BLOCKED
        ),
        shadow_promotion_ready=ready,
        live_allowed=False,
        blockers=unique_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
        required_families=len(expected_families),
        package_sha256=package.package_sha256,
        soak_evidence_sha256=package.soak.evidence_sha256,
        duration_seconds=package.soak.duration_seconds,
        candidates_seen=package.soak.metrics.candidates_seen,
        artifact_check=artifact_check,
    )


__all__ = [
    "PR096_PUMP_RESULT_SCHEMA_VERSION",
    "PR096_PUMP_SCHEMA_VERSION",
    "REQUIRED_PUMP_PR096_ARTIFACTS",
    "PumpPR096ArtifactCheck",
    "PumpPR096ArtifactKind",
    "PumpPR096ArtifactPin",
    "PumpPR096FamilyEvidence",
    "PumpPR096PromotionPackage",
    "PumpPR096PromotionReport",
    "PumpPR096State",
    "check_pump_pr096_materialized_artifacts",
    "evaluate_pump_pr096_shadow_promotion",
]
