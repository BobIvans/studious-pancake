"""PR-095 Kamino real conformance promotion gate.

This module extends the PR-067 Kamino conformance schema with real-source,
real-artifact, and materialized-file checks required before a Kamino combination
may be considered reviewed for shadow-only use. It is deliberately sender-free
and always keeps live execution disabled.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum, StrEnum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping
from urllib.parse import urlparse

from src.lending.kamino_conformance import (
    MINIMUM_SHADOW_SOAK_SECONDS,
    KaminoConformanceEvidence,
    evaluate_kamino_conformance,
)

SCHEMA_VERSION = "pr095.kamino-real-conformance.v1"
RESULT_SCHEMA_VERSION = "pr095.kamino-real-conformance-result.v1"
REQUIRED_EVIDENCE_ROOT = "evidence/kamino/pr095"
KLEND_SOURCE_REPOSITORY = "https://github.com/Kamino-Finance/klend"
KLEND_SDK_REPOSITORY = "https://github.com/Kamino-Finance/klend-sdk"
KLEND_SDK_PACKAGE = "@kamino-finance/klend-sdk"
KAMINO_DEVELOPER_DOCS = "https://kamino.com/docs/build/developers/borrow"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class KaminoRealConformanceError(ValueError):
    """Raised when PR-095 real Kamino conformance evidence is malformed."""


class KaminoRealArtifactKind(StrEnum):
    KLEND_SOURCE_PIN = "klend-source-pin"
    KLEND_SDK_PIN = "klend-sdk-pin"
    DEPLOYMENT_PROGRAM = "deployment-program"
    IDL = "idl"
    SDK_ACCOUNT_VECTORS = "sdk-account-vectors"
    SDK_INSTRUCTION_VECTORS = "sdk-instruction-vectors"
    READONLY_RPC_MARKET = "readonly-rpc-market"
    READONLY_RPC_RESERVES = "readonly-rpc-reserves"
    READONLY_RPC_OBLIGATIONS = "readonly-rpc-obligations"
    ORACLE_HEALTH_FEE_PROOF = "oracle-health-fee-proof"
    COMMON_KERNEL = "common-kernel"
    SHADOW_SOAK = "shadow-soak"
    HUMAN_REVIEW = "human-review"
    SIGNATURE = "signature"


@dataclass(frozen=True, slots=True)
class KaminoRealSourcePins:
    klend_repository_url: str
    klend_commit: str
    klend_sdk_repository_url: str
    klend_sdk_commit: str
    sdk_package: str
    sdk_version: str
    developer_docs_url: str
    reviewed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "klend_repository_url",
            _require_exact_url(
                self.klend_repository_url,
                expected=KLEND_SOURCE_REPOSITORY,
                field="source.klend_repository_url",
            ),
        )
        object.__setattr__(
            self,
            "klend_sdk_repository_url",
            _require_exact_url(
                self.klend_sdk_repository_url,
                expected=KLEND_SDK_REPOSITORY,
                field="source.klend_sdk_repository_url",
            ),
        )
        object.__setattr__(
            self,
            "developer_docs_url",
            _require_exact_url(
                self.developer_docs_url,
                expected=KAMINO_DEVELOPER_DOCS,
                field="source.developer_docs_url",
            ),
        )
        object.__setattr__(
            self,
            "klend_commit",
            _require_git_sha(self.klend_commit, field="source.klend_commit"),
        )
        object.__setattr__(
            self,
            "klend_sdk_commit",
            _require_git_sha(
                self.klend_sdk_commit,
                field="source.klend_sdk_commit",
            ),
        )
        if self.klend_commit == self.klend_sdk_commit:
            raise KaminoRealConformanceError(
                "klend and klend-sdk commits must be independently pinned"
            )
        object.__setattr__(
            self,
            "sdk_package",
            _require_exact_string(
                self.sdk_package,
                expected=KLEND_SDK_PACKAGE,
                field="source.sdk_package",
            ),
        )
        object.__setattr__(
            self,
            "sdk_version",
            _require_non_empty(self.sdk_version, field="source.sdk_version"),
        )
        _require_timezone(self.reviewed_at, field="source.reviewed_at")


@dataclass(frozen=True, slots=True)
class KaminoRealArtifact:
    path: str
    sha256: str
    kind: KaminoRealArtifactKind
    produced_by: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "path",
            _require_pr095_path(self.path, field="artifact.path"),
        )
        object.__setattr__(
            self,
            "sha256",
            _require_sha256(self.sha256, field="artifact.sha256"),
        )
        object.__setattr__(
            self,
            "produced_by",
            _require_non_empty(self.produced_by, field="artifact.produced_by"),
        )


@dataclass(frozen=True, slots=True)
class KaminoRealRpcEvidence:
    market_vector_sha256: str
    reserve_vector_sha256: str
    obligation_vector_sha256: str
    oracle_vector_sha256: str
    read_only_rpc_bundle_sha256: str
    min_context_slot: int
    market_count: int
    reserve_count: int
    obligation_count: int
    oracle_count: int

    def __post_init__(self) -> None:
        for name in (
            "market_vector_sha256",
            "reserve_vector_sha256",
            "obligation_vector_sha256",
            "oracle_vector_sha256",
            "read_only_rpc_bundle_sha256",
        ):
            object.__setattr__(
                self,
                name,
                _require_sha256(getattr(self, name), field=f"rpc.{name}"),
            )
        for name in (
            "min_context_slot",
            "market_count",
            "reserve_count",
            "obligation_count",
            "oracle_count",
        ):
            _require_positive_int(getattr(self, name), field=f"rpc.{name}")


@dataclass(frozen=True, slots=True)
class KaminoRealMathEvidence:
    oracle_health_fee_sha256: str
    common_kernel_sha256: str
    sample_count: int
    max_health_error_bps: int
    max_fee_error_bps: int
    borrow_flashloan_path_verified: bool
    liquidation_path_verified: bool
    no_live_authority: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "oracle_health_fee_sha256",
            _require_sha256(
                self.oracle_health_fee_sha256,
                field="math.oracle_health_fee_sha256",
            ),
        )
        object.__setattr__(
            self,
            "common_kernel_sha256",
            _require_sha256(
                self.common_kernel_sha256,
                field="math.common_kernel_sha256",
            ),
        )
        _require_positive_int(self.sample_count, field="math.sample_count")
        _require_bps(self.max_health_error_bps, field="math.max_health_error_bps")
        _require_bps(self.max_fee_error_bps, field="math.max_fee_error_bps")
        for name in (
            "borrow_flashloan_path_verified",
            "liquidation_path_verified",
            "no_live_authority",
        ):
            _require_bool(getattr(self, name), field=f"math.{name}")


@dataclass(frozen=True, slots=True)
class KaminoRealShadowSoakEvidence:
    run_id: str
    duration_seconds: int
    evidence_sha256: str
    replay_corpus_sha256: str
    deterministic_replay_passed: bool
    human_reviewed: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "run_id",
            _require_non_empty(self.run_id, field="soak.run_id"),
        )
        object.__setattr__(
            self,
            "evidence_sha256",
            _require_sha256(self.evidence_sha256, field="soak.evidence_sha256"),
        )
        object.__setattr__(
            self,
            "replay_corpus_sha256",
            _require_sha256(
                self.replay_corpus_sha256,
                field="soak.replay_corpus_sha256",
            ),
        )
        _require_positive_int(self.duration_seconds, field="soak.duration_seconds")
        _require_bool(
            self.deterministic_replay_passed,
            field="soak.deterministic_replay_passed",
        )
        _require_bool(self.human_reviewed, field="soak.human_reviewed")


@dataclass(frozen=True, slots=True)
class KaminoRealReviewEvidence:
    operator: str
    reviewer: str
    reviewed_at: datetime
    signed_by: str
    signature_reference: str
    notes: str = ""

    def __post_init__(self) -> None:
        for name in ("operator", "reviewer", "signed_by"):
            object.__setattr__(
                self,
                name,
                _require_non_empty(getattr(self, name), field=f"review.{name}"),
            )
        _require_timezone(self.reviewed_at, field="review.reviewed_at")
        object.__setattr__(
            self,
            "signature_reference",
            _require_pr095_path(
                self.signature_reference,
                field="review.signature_reference",
            ),
        )


@dataclass(frozen=True, slots=True)
class KaminoRealConformancePackage:
    source_pins: KaminoRealSourcePins
    base_conformance: KaminoConformanceEvidence
    artifacts: tuple[KaminoRealArtifact, ...]
    deployment_program_hash_sha256: str
    idl_sha256: str
    sdk_account_vectors_sha256: str
    sdk_instruction_vectors_sha256: str
    rpc_evidence: KaminoRealRpcEvidence
    math_evidence: KaminoRealMathEvidence
    shadow_soak: KaminoRealShadowSoakEvidence
    review: KaminoRealReviewEvidence
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise KaminoRealConformanceError("unsupported PR-095 evidence schema")
        if not isinstance(self.base_conformance, KaminoConformanceEvidence):
            raise KaminoRealConformanceError(
                "base_conformance must be KaminoConformanceEvidence"
            )
        if not self.artifacts:
            raise KaminoRealConformanceError("artifacts cannot be empty")
        paths = [artifact.path for artifact in self.artifacts]
        if len(paths) != len(set(paths)):
            raise KaminoRealConformanceError("artifact paths must be unique")
        kinds = [artifact.kind for artifact in self.artifacts]
        if len(kinds) != len(set(kinds)):
            raise KaminoRealConformanceError("artifact kinds must be unique")
        for name in (
            "deployment_program_hash_sha256",
            "idl_sha256",
            "sdk_account_vectors_sha256",
            "sdk_instruction_vectors_sha256",
        ):
            object.__setattr__(
                self,
                name,
                _require_sha256(getattr(self, name), field=name),
            )

    @property
    def evidence_sha256(self) -> str:
        return sha256_payload(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class KaminoRealConformanceEvaluation:
    schema_version: str
    ready_for_shadow_review: bool
    live_execution_allowed: bool
    state: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    evidence_sha256: str
    checks_evaluated: int
    metrics_summary: Mapping[str, int | str]

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def evaluate_kamino_real_conformance(
    package: KaminoRealConformancePackage,
) -> KaminoRealConformanceEvaluation:
    """Evaluate PR-095 real Kamino conformance without enabling live mode."""

    blockers: list[str] = []
    warnings: list[str] = []
    checks = 0

    def check(condition: bool, reason: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            blockers.append(reason)

    base = evaluate_kamino_conformance(package.base_conformance)
    check(base.conformance_ready, "PR067_BASE_CONFORMANCE_NOT_READY")
    blockers.extend(f"PR067:{reason}" for reason in base.blockers)
    warnings.extend(f"PR067:{warning}" for warning in base.warnings)

    combination = package.base_conformance.combination
    provenance = combination.provenance
    artifact_kinds = {artifact.kind for artifact in package.artifacts}

    check(combination.verified, "KAMINO_COMBINATION_NOT_VERIFIED")
    check(
        provenance.sdk_package == KLEND_SDK_PACKAGE,
        "KAMINO_SDK_PACKAGE_MISMATCH",
    )
    check(
        provenance.source_url
        in {KLEND_SOURCE_REPOSITORY, KLEND_SDK_REPOSITORY, KAMINO_DEVELOPER_DOCS},
        "KAMINO_PROVENANCE_SOURCE_NOT_OFFICIAL",
    )
    check(
        provenance.idl_sha256.lower() == package.idl_sha256,
        "KAMINO_IDL_SHA_MISMATCH",
    )
    check(
        set(KaminoRealArtifactKind).issubset(artifact_kinds),
        "PR095_REQUIRED_ARTIFACTS_MISSING",
    )
    check(
        package.deployment_program_hash_sha256 != package.idl_sha256,
        "DEPLOYMENT_HASH_MUST_BE_DISTINCT_FROM_IDL_HASH",
    )
    check(
        package.sdk_account_vectors_sha256 != package.sdk_instruction_vectors_sha256,
        "SDK_ACCOUNT_AND_INSTRUCTION_VECTORS_COLLAPSED",
    )

    rpc = package.rpc_evidence
    check(rpc.market_count >= 1, "RPC_MARKET_VECTOR_MISSING")
    check(rpc.reserve_count >= 2, "RPC_RESERVE_VECTORS_MISSING")
    check(rpc.obligation_count >= 1, "RPC_OBLIGATION_VECTOR_MISSING")
    check(rpc.oracle_count >= 1, "RPC_ORACLE_VECTOR_MISSING")

    math = package.math_evidence
    check(math.borrow_flashloan_path_verified, "BORROW_FLASHLOAN_PATH_UNVERIFIED")
    check(math.liquidation_path_verified, "LIQUIDATION_PATH_UNVERIFIED")
    check(math.no_live_authority, "LIVE_AUTHORITY_PRESENT_IN_EVIDENCE")
    check(math.max_health_error_bps <= 1, "HEALTH_ERROR_TOO_HIGH")
    check(math.max_fee_error_bps <= 1, "FEE_ERROR_TOO_HIGH")
    check(math.sample_count >= 3, "INSUFFICIENT_MATH_SAMPLES")

    soak = package.shadow_soak
    check(
        soak.duration_seconds >= MINIMUM_SHADOW_SOAK_SECONDS,
        "SOAK_TOO_SHORT",
    )
    check(soak.deterministic_replay_passed, "SOAK_REPLAY_NOT_DETERMINISTIC")
    check(soak.human_reviewed, "SOAK_NOT_HUMAN_REVIEWED")

    ready = not blockers
    state = "ready-for-shadow-review" if ready else "blocked"
    metrics: dict[str, int | str] = {
        "artifact_count": len(package.artifacts),
        "checks_evaluated": checks,
        "combination_id": combination.combination_id,
        "market_count": rpc.market_count,
        "reserve_count": rpc.reserve_count,
    }
    return KaminoRealConformanceEvaluation(
        schema_version=RESULT_SCHEMA_VERSION,
        ready_for_shadow_review=ready,
        live_execution_allowed=False,
        state=state,
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(dict.fromkeys(warnings)),
        evidence_sha256=package.evidence_sha256,
        checks_evaluated=checks,
        metrics_summary=metrics,
    )


def assert_kamino_real_conformance(
    package: KaminoRealConformancePackage,
) -> KaminoRealConformanceEvaluation:
    result = evaluate_kamino_real_conformance(package)
    if result.ready_for_shadow_review:
        return result
    joined = ",".join(result.blockers)
    raise KaminoRealConformanceError(f"PR095_KAMINO_REAL_BLOCKED:{joined}")


def check_pr095_materialized_artifacts(
    package: KaminoRealConformancePackage,
    *,
    repository_root: Path,
) -> tuple[str, ...]:
    root = Path(repository_root)
    blockers: list[str] = []
    for artifact in package.artifacts:
        artifact_path = root / artifact.path
        if not artifact_path.is_file():
            blockers.append(f"ARTIFACT_MISSING:{artifact.path}")
            continue
        actual = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if actual != artifact.sha256:
            blockers.append(f"ARTIFACT_HASH_MISMATCH:{artifact.path}")
    return tuple(blockers)


def stable_json(payload: Any) -> str:
    return json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"))


def sha256_payload(payload: Any) -> str:
    return hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {
            field.name: _jsonable(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _require_non_empty(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KaminoRealConformanceError(f"{field} must be a non-empty string")
    return value.strip()


def _require_bool(value: bool, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise KaminoRealConformanceError(f"{field} must be boolean")
    return value


def _require_positive_int(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise KaminoRealConformanceError(f"{field} must be positive")
    return value


def _require_bps(value: int, *, field: str) -> int:
    checked = _require_positive_int(value, field=field)
    if checked > 10_000:
        raise KaminoRealConformanceError(f"{field} must be <= 10000 bps")
    return checked


def _require_sha256(value: str, *, field: str) -> str:
    lowered = str(value).lower()
    is_placeholder = len(set(lowered)) == 1
    if not _SHA256_RE.fullmatch(lowered) or is_placeholder:
        raise KaminoRealConformanceError(
            f"{field} must be a non-placeholder sha256 digest"
        )
    return lowered


def _require_git_sha(value: str, *, field: str) -> str:
    lowered = str(value).lower()
    is_placeholder = len(set(lowered)) == 1
    if not _GIT_SHA_RE.fullmatch(lowered) or is_placeholder:
        raise KaminoRealConformanceError(
            f"{field} must be a non-placeholder git SHA"
        )
    return lowered


def _require_timezone(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise KaminoRealConformanceError(f"{field} must be timezone-aware")
    return value


def _require_exact_string(value: str, *, expected: str, field: str) -> str:
    checked = _require_non_empty(value, field=field)
    if checked != expected:
        raise KaminoRealConformanceError(f"{field} must be {expected}")
    return checked


def _require_exact_url(value: str, *, expected: str, field: str) -> str:
    checked = _require_exact_string(value, expected=expected, field=field)
    parsed = urlparse(checked)
    if parsed.scheme != "https" or not parsed.netloc:
        raise KaminoRealConformanceError(f"{field} must be an HTTPS URL")
    return checked


def _require_pr095_path(value: str, *, field: str) -> str:
    normalized = _require_non_empty(value, field=field).replace("\\", "/")
    parts = normalized.split("/")
    has_bad_part = any(part in {"", ".", ".."} for part in parts)
    if normalized.startswith(("/", "~")) or has_bad_part:
        raise KaminoRealConformanceError(
            f"{field} must be a normalized repository-relative path"
        )
    if normalized != REQUIRED_EVIDENCE_ROOT and not normalized.startswith(
        f"{REQUIRED_EVIDENCE_ROOT}/"
    ):
        raise KaminoRealConformanceError(
            f"{field} must be under {REQUIRED_EVIDENCE_ROOT}"
        )
    return normalized
