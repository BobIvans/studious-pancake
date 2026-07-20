"""PR-067 Kamino lending/liquidation conformance evidence gate.

This module is deliberately sender-free and planner-neutral. It validates the
evidence required before a Kamino market/asset combination may be promoted from
fail-closed fixture status into shadow-only liquidation planning.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum, StrEnum
import hashlib
import json
import re
from typing import Any

from src.config.chain_registry import ChainRegistryError, validate_pubkey
from src.lending.kamino import KaminoRegistryError, KaminoSupportedCombination

SCHEMA_VERSION = "pr067.kamino-lending-conformance.v1"
RESULT_SCHEMA_VERSION = "pr067.kamino-lending-conformance-result.v1"
MINIMUM_SHADOW_SOAK_SECONDS = 72 * 60 * 60

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class KaminoConformanceError(ValueError):
    """Raised when a PR-067 conformance evidence object is malformed."""


class KaminoConformanceArtifactKind(StrEnum):
    IDL = "idl"
    RPC_ACCOUNT_FIXTURES = "rpc-account-fixtures"
    INSTRUCTION_GOLDEN_VECTORS = "instruction-golden-vectors"
    HEALTH_ORACLE_REPORT = "health-oracle-report"
    PLANNER_REPLAY = "planner-replay"
    SHADOW_SOAK_REPORT = "shadow-soak-report"
    HUMAN_REVIEW = "human-review"


class KaminoAccountVectorKind(StrEnum):
    MARKET = "market"
    RESERVE = "reserve"
    OBLIGATION = "obligation"
    ORACLE = "oracle"


def _require_non_empty(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        message = f"{field} must be a non-empty string"
        raise KaminoConformanceError(message)
    return value.strip()


def _require_bool(value: bool, *, field: str) -> bool:
    if not isinstance(value, bool):
        message = f"{field} must be boolean"
        raise KaminoConformanceError(message)
    return value


def _require_non_negative_int(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        message = f"{field} must be a non-negative integer"
        raise KaminoConformanceError(message)
    return value


def _require_positive_int(value: int, *, field: str) -> int:
    checked = _require_non_negative_int(value, field=field)
    if checked == 0:
        message = f"{field} must be positive"
        raise KaminoConformanceError(message)
    return checked


def _require_bps(value: int, *, field: str) -> int:
    checked = _require_non_negative_int(value, field=field)
    if checked > 10_000:
        message = f"{field} must be <= 10000 bps"
        raise KaminoConformanceError(message)
    return checked


def _require_sha256(value: str, *, field: str) -> str:
    lowered = str(value).lower()
    if not _SHA256_RE.fullmatch(lowered) or lowered == "0" * 64:
        message = f"{field} must be a non-placeholder sha256 digest"
        raise KaminoConformanceError(message)
    return lowered


def _require_git_sha(value: str, *, field: str) -> str:
    lowered = str(value).lower()
    if not _GIT_SHA_RE.fullmatch(lowered) or lowered == "0" * 40:
        message = f"{field} must be a non-placeholder git SHA"
        raise KaminoConformanceError(message)
    return lowered


def _require_pubkey(value: str, *, field: str) -> str:
    try:
        return validate_pubkey(str(value), field=field)
    except ChainRegistryError as exc:
        raise KaminoConformanceError(str(exc)) from exc


def _require_relative_path(value: str, *, field: str) -> str:
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    has_bad_part = any(part in {"", ".", ".."} for part in parts)
    if not value or normalized.startswith(("/", "~")) or has_bad_part:
        message = f"{field} must be a normalized repository-relative path"
        raise KaminoConformanceError(message)
    return normalized


def _require_timezone(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        message = f"{field} must be timezone-aware"
        raise KaminoConformanceError(message)
    return value


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        result: dict[str, Any] = {}
        for item in fields(value):
            result[item.name] = _jsonable(getattr(value, item.name))
        return result
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def stable_json(payload: Any) -> str:
    return json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"))


def sha256_payload(payload: Any) -> str:
    payload_bytes = stable_json(payload).encode("utf-8")
    return hashlib.sha256(payload_bytes).hexdigest()


@dataclass(frozen=True, slots=True)
class KaminoConformanceArtifact:
    path: str
    sha256: str
    kind: KaminoConformanceArtifactKind

    def __post_init__(self) -> None:
        path = _require_relative_path(self.path, field="artifact.path")
        sha256 = _require_sha256(self.sha256, field="artifact.sha256")
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "sha256", sha256)


@dataclass(frozen=True, slots=True)
class KaminoRpcAccountVector:
    account_address: str
    owner_program_id: str
    account_kind: KaminoAccountVectorKind
    data_sha256: str
    decoded_fields_sha256: str
    slot: int

    def __post_init__(self) -> None:
        account = _require_pubkey(self.account_address, field="account_address")
        owner = _require_pubkey(self.owner_program_id, field="owner_program_id")
        data_sha = _require_sha256(self.data_sha256, field="data_sha256")
        decoded_sha = _require_sha256(
            self.decoded_fields_sha256,
            field="decoded_fields_sha256",
        )
        _require_positive_int(self.slot, field="slot")
        object.__setattr__(self, "account_address", account)
        object.__setattr__(self, "owner_program_id", owner)
        object.__setattr__(self, "data_sha256", data_sha)
        object.__setattr__(self, "decoded_fields_sha256", decoded_sha)


@dataclass(frozen=True, slots=True)
class KaminoInstructionGoldenVector:
    instruction_name: str
    program_id: str
    account_metas_sha256: str
    data_sha256: str
    account_count: int
    writable_count: int
    signer_count: int
    sdk_fixture_sha256: str

    def __post_init__(self) -> None:
        instruction = _require_non_empty(
            self.instruction_name,
            field="instruction_name",
        )
        program_id = _require_pubkey(self.program_id, field="program_id")
        object.__setattr__(self, "instruction_name", instruction)
        object.__setattr__(self, "program_id", program_id)
        for name in ("account_metas_sha256", "data_sha256", "sdk_fixture_sha256"):
            digest = _require_sha256(getattr(self, name), field=name)
            object.__setattr__(self, name, digest)
        _require_positive_int(self.account_count, field="account_count")
        _require_non_negative_int(self.writable_count, field="writable_count")
        _require_non_negative_int(self.signer_count, field="signer_count")
        if self.writable_count > self.account_count:
            raise KaminoConformanceError("writable_count cannot exceed account_count")
        if self.signer_count > self.account_count:
            raise KaminoConformanceError("signer_count cannot exceed account_count")


@dataclass(frozen=True, slots=True)
class KaminoHealthOracleMathEvidence:
    sample_count: int
    max_health_factor_error_bps: int
    max_price_staleness_slots: int
    liquidation_threshold_bps: int
    oracle_sources: tuple[str, ...]
    passed: bool

    def __post_init__(self) -> None:
        _require_positive_int(self.sample_count, field="sample_count")
        _require_bps(
            self.max_health_factor_error_bps,
            field="max_health_factor_error_bps",
        )
        _require_non_negative_int(
            self.max_price_staleness_slots,
            field="max_price_staleness_slots",
        )
        _require_bps(self.liquidation_threshold_bps, field="liquidation_threshold_bps")
        empty_source = any(not source.strip() for source in self.oracle_sources)
        if not self.oracle_sources or empty_source:
            raise KaminoConformanceError("oracle_sources cannot be empty")
        if len(self.oracle_sources) != len(set(self.oracle_sources)):
            raise KaminoConformanceError("oracle_sources must be unique")
        _require_bool(self.passed, field="passed")


@dataclass(frozen=True, slots=True)
class KaminoPlannerReplayEvidence:
    replay_cases: int
    accepted_cases: int
    rejected_cases: int
    mismatch_count: int
    deterministic_replay_passed: bool
    corpus_sha256: str

    def __post_init__(self) -> None:
        count_fields = (
            "replay_cases",
            "accepted_cases",
            "rejected_cases",
            "mismatch_count",
        )
        for name in count_fields:
            _require_non_negative_int(getattr(self, name), field=name)
        if self.replay_cases == 0:
            raise KaminoConformanceError("replay_cases must be positive")
        if self.accepted_cases + self.rejected_cases != self.replay_cases:
            message = "accepted and rejected cases must sum to replay_cases"
            raise KaminoConformanceError(message)
        _require_bool(
            self.deterministic_replay_passed,
            field="deterministic_replay_passed",
        )
        corpus_sha = _require_sha256(self.corpus_sha256, field="corpus_sha256")
        object.__setattr__(self, "corpus_sha256", corpus_sha)


@dataclass(frozen=True, slots=True)
class KaminoShadowSoakReference:
    run_id: str
    duration_seconds: int
    evidence_sha256: str
    passed: bool
    human_reviewed: bool

    def __post_init__(self) -> None:
        run_id = _require_non_empty(self.run_id, field="run_id")
        evidence_sha = _require_sha256(
            self.evidence_sha256,
            field="evidence_sha256",
        )
        _require_positive_int(self.duration_seconds, field="duration_seconds")
        _require_bool(self.passed, field="passed")
        _require_bool(self.human_reviewed, field="human_reviewed")
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "evidence_sha256", evidence_sha)


@dataclass(frozen=True, slots=True)
class KaminoConformanceThresholds:
    min_rpc_vectors: int = 4
    min_instruction_vectors: int = 2
    min_health_oracle_samples: int = 1
    max_health_factor_error_bps: int = 1
    max_price_staleness_slots: int = 10
    min_planner_replay_cases: int = 1
    max_planner_mismatches: int = 0
    min_shadow_soak_seconds: int = MINIMUM_SHADOW_SOAK_SECONDS
    require_human_review: bool = True
    require_signed_bundle: bool = True
    required_artifact_kinds: tuple[KaminoConformanceArtifactKind, ...] = (
        KaminoConformanceArtifactKind.IDL,
        KaminoConformanceArtifactKind.RPC_ACCOUNT_FIXTURES,
        KaminoConformanceArtifactKind.INSTRUCTION_GOLDEN_VECTORS,
        KaminoConformanceArtifactKind.HEALTH_ORACLE_REPORT,
        KaminoConformanceArtifactKind.PLANNER_REPLAY,
        KaminoConformanceArtifactKind.SHADOW_SOAK_REPORT,
        KaminoConformanceArtifactKind.HUMAN_REVIEW,
    )
    required_account_kinds: tuple[KaminoAccountVectorKind, ...] = (
        KaminoAccountVectorKind.MARKET,
        KaminoAccountVectorKind.RESERVE,
        KaminoAccountVectorKind.OBLIGATION,
        KaminoAccountVectorKind.ORACLE,
    )

    def __post_init__(self) -> None:
        positive_fields = (
            "min_rpc_vectors",
            "min_instruction_vectors",
            "min_health_oracle_samples",
            "min_planner_replay_cases",
            "min_shadow_soak_seconds",
        )
        for name in positive_fields:
            _require_positive_int(getattr(self, name), field=name)
        _require_bps(
            self.max_health_factor_error_bps,
            field="max_health_factor_error_bps",
        )
        _require_non_negative_int(
            self.max_price_staleness_slots,
            field="max_price_staleness_slots",
        )
        _require_non_negative_int(
            self.max_planner_mismatches,
            field="max_planner_mismatches",
        )
        _require_bool(self.require_human_review, field="require_human_review")
        _require_bool(self.require_signed_bundle, field="require_signed_bundle")
        if not self.required_artifact_kinds:
            raise KaminoConformanceError("required_artifact_kinds cannot be empty")
        if not self.required_account_kinds:
            raise KaminoConformanceError("required_account_kinds cannot be empty")


@dataclass(frozen=True, slots=True)
class KaminoConformanceEvidence:
    combination: KaminoSupportedCombination
    code_commit: str
    artifacts: tuple[KaminoConformanceArtifact, ...]
    rpc_account_vectors: tuple[KaminoRpcAccountVector, ...]
    instruction_vectors: tuple[KaminoInstructionGoldenVector, ...]
    health_oracle_math: KaminoHealthOracleMathEvidence
    planner_replay: KaminoPlannerReplayEvidence
    shadow_soak: KaminoShadowSoakReference
    operator: str
    reviewer: str
    reviewed_at: datetime
    signed_by: str
    signature_reference: str
    schema_version: str = SCHEMA_VERSION
    notes: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise KaminoConformanceError("unsupported PR-067 evidence schema")
        if not isinstance(self.combination, KaminoSupportedCombination):
            message = "combination must be KaminoSupportedCombination"
            raise KaminoConformanceError(message)
        try:
            self.combination.validated()
        except KaminoRegistryError as exc:
            raise KaminoConformanceError(str(exc)) from exc
        code_commit = _require_git_sha(self.code_commit, field="code_commit")
        object.__setattr__(self, "code_commit", code_commit)
        if not self.artifacts:
            raise KaminoConformanceError("at least one artifact is required")
        artifact_paths = [artifact.path for artifact in self.artifacts]
        if len(artifact_paths) != len(set(artifact_paths)):
            raise KaminoConformanceError("artifact paths must be unique")
        artifact_kinds = [artifact.kind for artifact in self.artifacts]
        if len(artifact_kinds) != len(set(artifact_kinds)):
            raise KaminoConformanceError("artifact kinds must be unique")
        if not self.rpc_account_vectors:
            raise KaminoConformanceError("rpc_account_vectors cannot be empty")
        if not self.instruction_vectors:
            raise KaminoConformanceError("instruction_vectors cannot be empty")
        _require_non_empty(self.operator, field="operator")
        _require_non_empty(self.reviewer, field="reviewer")
        _require_timezone(self.reviewed_at, field="reviewed_at")
        _require_non_empty(self.signed_by, field="signed_by")
        _require_relative_path(self.signature_reference, field="signature_reference")

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)

    @property
    def evidence_sha256(self) -> str:
        return sha256_payload(self.to_dict())


@dataclass(frozen=True, slots=True)
class KaminoConformanceEvaluation:
    schema_version: str
    combination_id: str
    conformance_ready: bool
    live_execution_allowed: bool
    state: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    evidence_sha256: str
    checks_evaluated: int
    metrics_summary: Mapping[str, int]

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def evaluate_kamino_conformance(
    evidence: KaminoConformanceEvidence,
    thresholds: KaminoConformanceThresholds | None = None,
) -> KaminoConformanceEvaluation:
    """Validate a Kamino conformance package without enabling execution."""

    policy = thresholds or KaminoConformanceThresholds()
    blockers: list[str] = []
    warnings: list[str] = []
    checks = 0

    def check(condition: bool, reason: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            blockers.append(reason)

    combination = evidence.combination
    program_id = combination.lending_program_id
    artifact_kinds = {artifact.kind for artifact in evidence.artifacts}
    rpc_kinds = {vector.account_kind for vector in evidence.rpc_account_vectors}

    check(combination.verified, "KAMINO_COMBINATION_NOT_VERIFIED")
    check(
        artifact_kinds == set(policy.required_artifact_kinds),
        "REQUIRED_ARTIFACTS_MISSING",
    )
    check(
        len(evidence.rpc_account_vectors) >= policy.min_rpc_vectors,
        "INSUFFICIENT_RPC_GOLDEN_ACCOUNT_VECTORS",
    )
    check(
        set(policy.required_account_kinds).issubset(rpc_kinds),
        "REQUIRED_ACCOUNT_VECTOR_KINDS_MISSING",
    )

    non_oracle_vectors = (
        vector
        for vector in evidence.rpc_account_vectors
        if vector.account_kind is not KaminoAccountVectorKind.ORACLE
    )
    owners_match = all(
        vector.owner_program_id == program_id for vector in non_oracle_vectors
    )
    check(owners_match, "KAMINO_ACCOUNT_OWNER_MISMATCH")
    check(
        len(evidence.instruction_vectors) >= policy.min_instruction_vectors,
        "INSUFFICIENT_INSTRUCTION_GOLDEN_VECTORS",
    )
    instruction_programs_match = all(
        vector.program_id == program_id for vector in evidence.instruction_vectors
    )
    check(instruction_programs_match, "INSTRUCTION_PROGRAM_MISMATCH")

    health = evidence.health_oracle_math
    check(health.passed, "HEALTH_ORACLE_MATH_NOT_PASSED")
    check(
        health.sample_count >= policy.min_health_oracle_samples,
        "INSUFFICIENT_HEALTH_ORACLE_SAMPLES",
    )
    check(
        health.max_health_factor_error_bps <= policy.max_health_factor_error_bps,
        "HEALTH_FACTOR_ERROR_TOO_HIGH",
    )
    check(
        health.max_price_staleness_slots <= policy.max_price_staleness_slots,
        "PRICE_STALENESS_TOO_HIGH",
    )

    replay = evidence.planner_replay
    check(
        replay.replay_cases >= policy.min_planner_replay_cases,
        "INSUFFICIENT_PLANNER_REPLAY_CASES",
    )
    check(
        replay.mismatch_count <= policy.max_planner_mismatches,
        "PLANNER_REPLAY_MISMATCHES",
    )
    check(replay.deterministic_replay_passed, "PLANNER_REPLAY_NOT_DETERMINISTIC")

    soak = evidence.shadow_soak
    check(soak.passed, "SHADOW_SOAK_NOT_PASSED")
    check(
        soak.duration_seconds >= policy.min_shadow_soak_seconds,
        "SHADOW_SOAK_DURATION_TOO_SHORT",
    )
    if policy.require_human_review:
        check(soak.human_reviewed, "SHADOW_SOAK_NOT_HUMAN_REVIEWED")
        check(bool(evidence.reviewer.strip()), "CONFORMANCE_NOT_HUMAN_REVIEWED")
    if policy.require_signed_bundle:
        check(bool(evidence.signed_by.strip()), "CONFORMANCE_BUNDLE_NOT_SIGNED")
        check(
            bool(evidence.signature_reference.strip()),
            "CONFORMANCE_SIGNATURE_REFERENCE_MISSING",
        )

    vector_accounts = {
        vector.account_address for vector in evidence.rpc_account_vectors
    }
    check(
        combination.market_address in vector_accounts,
        "MARKET_ACCOUNT_VECTOR_MISSING",
    )
    check(
        combination.collateral_reserve in vector_accounts,
        "COLLATERAL_RESERVE_VECTOR_MISSING",
    )
    check(combination.debt_reserve in vector_accounts, "DEBT_RESERVE_VECTOR_MISSING")
    check(
        combination.collateral_oracle in vector_accounts
        or combination.debt_oracle in vector_accounts,
        "ORACLE_VECTOR_MISSING",
    )

    if combination.provenance.sdk_package != "@kamino-finance/klend-sdk":
        blockers.append("KAMINO_SDK_PROVENANCE_MISMATCH")
    if combination.provenance.source_url.startswith("https://github.com/"):
        warnings.append("GITHUB_SOURCE_PIN_REQUIRES_RELEASE_TAG_OR_COMMIT_REVIEW")

    unique_blockers = tuple(dict.fromkeys(blockers))
    conformance_ready = not unique_blockers
    return KaminoConformanceEvaluation(
        schema_version=RESULT_SCHEMA_VERSION,
        combination_id=combination.combination_id,
        conformance_ready=conformance_ready,
        live_execution_allowed=False,
        state="shadow-conformance-ready" if conformance_ready else "blocked",
        blockers=unique_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
        evidence_sha256=evidence.evidence_sha256,
        checks_evaluated=checks,
        metrics_summary={
            "rpc_account_vectors": len(evidence.rpc_account_vectors),
            "instruction_vectors": len(evidence.instruction_vectors),
            "health_oracle_samples": health.sample_count,
            "planner_replay_cases": replay.replay_cases,
            "shadow_soak_seconds": soak.duration_seconds,
        },
    )
