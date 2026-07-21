"""PR-088 MarginFi protocol conformance evidence gate.

This module does not assemble, sign or submit transactions.  It defines the
complete evidence boundary required before the already verified MarginFi binary
can be treated as shadow-execution-capable by a sender-free paper runtime.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum, StrEnum
import hashlib
import json
import re
from typing import Any

from src.config.chain_registry import (
    ChainRegistryError,
    TOKEN_2022_PROGRAM_ADDRESS,
    TOKEN_PROGRAM_ADDRESS,
    validate_pubkey,
)
from src.providers.marginfi.deployment_conformance import (
    EXPECTED_MAIN_GROUP,
    EXPECTED_PROGRAM_ID,
    EXPECTED_VERIFIED_BUILD_HASH,
    PINNED_SOURCE_COMMIT,
)

SCHEMA_VERSION = "pr088.marginfi-protocol-conformance.v1"
RESULT_SCHEMA_VERSION = "pr088.marginfi-protocol-conformance-result.v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

_REQUIRED_FLASHLOAN_INSTRUCTIONS = (
    "lending_account_start_flashloan",
    "lending_account_borrow",
    "lending_account_repay",
    "lending_account_end_flashloan",
)


class MarginfiProtocolConformanceError(ValueError):
    """Raised when a PR-088 conformance evidence object is malformed."""


class MarginfiProtocolArtifactKind(StrEnum):
    """Repository-pinned artifacts required for MarginFi shadow conformance."""

    IDL = "idl"
    ACCOUNT_LAYOUTS = "account-layouts"
    SDK_ACCOUNT_VECTORS = "sdk-account-vectors"
    SDK_INSTRUCTION_VECTORS = "sdk-instruction-vectors"
    READONLY_RPC_EVIDENCE = "readonly-rpc-evidence"
    FLASHLOAN_META_PROOF = "flashloan-meta-proof"
    TOKEN_2022_PROOF = "token-2022-proof"
    REPAYMENT_MATH_PROOF = "repayment-math-proof"
    HUMAN_REVIEW = "human-review"


class MarginfiAccountVectorKind(StrEnum):
    GROUP = "group"
    BANK = "bank"
    MINT = "mint"
    LIQUIDITY_VAULT = "liquidity-vault"
    ORACLE = "oracle"
    MARGIN_ACCOUNT = "margin-account"


@dataclass(frozen=True, slots=True)
class MarginfiProtocolArtifact:
    path: str
    sha256: str
    kind: MarginfiProtocolArtifactKind
    produced_by: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "path",
            _require_relative_path(self.path, field="artifact.path"),
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
class MarginfiAccountVector:
    account_address: str
    owner_program_id: str
    account_kind: MarginfiAccountVectorKind
    data_sha256: str
    decoded_fields_sha256: str
    slot: int
    min_context_slot: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "account_address",
            _require_pubkey(self.account_address, field="account_address"),
        )
        object.__setattr__(
            self,
            "owner_program_id",
            _require_pubkey(self.owner_program_id, field="owner_program_id"),
        )
        object.__setattr__(
            self,
            "data_sha256",
            _require_sha256(self.data_sha256, field="data_sha256"),
        )
        object.__setattr__(
            self,
            "decoded_fields_sha256",
            _require_sha256(
                self.decoded_fields_sha256,
                field="decoded_fields_sha256",
            ),
        )
        _require_positive_int(self.slot, field="slot")
        _require_positive_int(self.min_context_slot, field="min_context_slot")
        if self.slot < self.min_context_slot:
            message = "slot cannot be lower than min_context_slot"
            raise MarginfiProtocolConformanceError(message)


@dataclass(frozen=True, slots=True)
class MarginfiInstructionVector:
    instruction_name: str
    program_id: str
    account_metas_sha256: str
    data_sha256: str
    sdk_fixture_sha256: str
    account_count: int
    writable_count: int
    signer_count: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "instruction_name",
            _require_non_empty(self.instruction_name, field="instruction_name"),
        )
        object.__setattr__(
            self,
            "program_id",
            _require_pubkey(self.program_id, field="program_id"),
        )
        for name in ("account_metas_sha256", "data_sha256", "sdk_fixture_sha256"):
            object.__setattr__(
                self,
                name,
                _require_sha256(getattr(self, name), field=name),
            )
        _require_positive_int(self.account_count, field="account_count")
        _require_non_negative_int(self.writable_count, field="writable_count")
        _require_non_negative_int(self.signer_count, field="signer_count")
        if self.writable_count > self.account_count:
            message = "writable_count cannot exceed account_count"
            raise MarginfiProtocolConformanceError(message)
        if self.signer_count > self.account_count:
            message = "signer_count cannot exceed account_count"
            raise MarginfiProtocolConformanceError(message)


@dataclass(frozen=True, slots=True)
class MarginfiReadonlyRpcEvidence:
    evidence_sha256: str
    min_context_slot: int
    program_executable_verified: bool
    group_relationships_verified: bool
    bank_relationships_verified: bool
    oracle_relationships_verified: bool
    fee_pause_config_verified: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_sha256",
            _require_sha256(self.evidence_sha256, field="rpc.evidence_sha256"),
        )
        _require_positive_int(self.min_context_slot, field="rpc.min_context_slot")
        for name in (
            "program_executable_verified",
            "group_relationships_verified",
            "bank_relationships_verified",
            "oracle_relationships_verified",
            "fee_pause_config_verified",
        ):
            _require_bool(getattr(self, name), field=f"rpc.{name}")


@dataclass(frozen=True, slots=True)
class MarginfiFlashloanMetaEvidence:
    start_end_index_bound: bool
    start_requires_instructions_sysvar: bool
    start_and_end_same_marginfi_account: bool
    signer_matches_marginfi_authority: bool
    borrow_repay_bank_order_verified: bool
    account_meta_order_verified: bool
    no_cpi_end_flashloan: bool

    def __post_init__(self) -> None:
        for name in (
            "start_end_index_bound",
            "start_requires_instructions_sysvar",
            "start_and_end_same_marginfi_account",
            "signer_matches_marginfi_authority",
            "borrow_repay_bank_order_verified",
            "account_meta_order_verified",
            "no_cpi_end_flashloan",
        ):
            _require_bool(getattr(self, name), field=f"flashloan.{name}")


@dataclass(frozen=True, slots=True)
class MarginfiToken2022Evidence:
    token_program_paths_verified: bool
    token_2022_program_paths_verified: bool
    mint_owner_matches_token_program: bool
    vault_owner_matches_token_program: bool
    token_2022_sample_count: int

    def __post_init__(self) -> None:
        for name in (
            "token_program_paths_verified",
            "token_2022_program_paths_verified",
            "mint_owner_matches_token_program",
            "vault_owner_matches_token_program",
        ):
            _require_bool(getattr(self, name), field=f"token_2022.{name}")
        _require_non_negative_int(
            self.token_2022_sample_count,
            field="token_2022.token_2022_sample_count",
        )


@dataclass(frozen=True, slots=True)
class MarginfiRepaymentMathEvidence:
    sample_count: int
    max_liability_share_error_bps: int
    max_repayment_error_bps: int
    fee_model_verified: bool
    health_after_flashloan_verified: bool

    def __post_init__(self) -> None:
        _require_positive_int(self.sample_count, field="repayment.sample_count")
        _require_bps(
            self.max_liability_share_error_bps,
            field="repayment.max_liability_share_error_bps",
        )
        _require_bps(
            self.max_repayment_error_bps,
            field="repayment.max_repayment_error_bps",
        )
        _require_bool(self.fee_model_verified, field="repayment.fee_model_verified")
        _require_bool(
            self.health_after_flashloan_verified,
            field="repayment.health_after_flashloan_verified",
        )


@dataclass(frozen=True, slots=True)
class MarginfiHumanReviewEvidence:
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
                _require_non_empty(getattr(self, name), field=f"human_review.{name}"),
            )
        _require_timezone(self.reviewed_at, field="human_review.reviewed_at")
        object.__setattr__(
            self,
            "signature_reference",
            _require_relative_path(
                self.signature_reference,
                field="human_review.signature_reference",
            ),
        )


@dataclass(frozen=True, slots=True)
class MarginfiProtocolConformanceThresholds:
    min_account_vectors: int = 5
    min_instruction_vectors: int = 4
    min_repayment_samples: int = 1
    max_repayment_error_bps: int = 1
    max_liability_share_error_bps: int = 1
    required_artifact_kinds: tuple[MarginfiProtocolArtifactKind, ...] = (
        MarginfiProtocolArtifactKind.IDL,
        MarginfiProtocolArtifactKind.ACCOUNT_LAYOUTS,
        MarginfiProtocolArtifactKind.SDK_ACCOUNT_VECTORS,
        MarginfiProtocolArtifactKind.SDK_INSTRUCTION_VECTORS,
        MarginfiProtocolArtifactKind.READONLY_RPC_EVIDENCE,
        MarginfiProtocolArtifactKind.FLASHLOAN_META_PROOF,
        MarginfiProtocolArtifactKind.TOKEN_2022_PROOF,
        MarginfiProtocolArtifactKind.REPAYMENT_MATH_PROOF,
        MarginfiProtocolArtifactKind.HUMAN_REVIEW,
    )
    required_account_kinds: tuple[MarginfiAccountVectorKind, ...] = (
        MarginfiAccountVectorKind.GROUP,
        MarginfiAccountVectorKind.BANK,
        MarginfiAccountVectorKind.MINT,
        MarginfiAccountVectorKind.LIQUIDITY_VAULT,
        MarginfiAccountVectorKind.ORACLE,
    )
    required_instruction_names: tuple[str, ...] = _REQUIRED_FLASHLOAN_INSTRUCTIONS

    def __post_init__(self) -> None:
        _require_positive_int(self.min_account_vectors, field="min_account_vectors")
        _require_positive_int(
            self.min_instruction_vectors,
            field="min_instruction_vectors",
        )
        _require_positive_int(self.min_repayment_samples, field="min_repayment_samples")
        _require_bps(self.max_repayment_error_bps, field="max_repayment_error_bps")
        _require_bps(
            self.max_liability_share_error_bps,
            field="max_liability_share_error_bps",
        )
        if not self.required_artifact_kinds:
            raise MarginfiProtocolConformanceError(
                "required_artifact_kinds cannot be empty"
            )
        if not self.required_account_kinds:
            raise MarginfiProtocolConformanceError(
                "required_account_kinds cannot be empty"
            )
        if not self.required_instruction_names:
            raise MarginfiProtocolConformanceError(
                "required_instruction_names cannot be empty"
            )


@dataclass(frozen=True, slots=True)
class MarginfiProtocolConformanceEvidence:
    source_commit: str
    verified_build_hash_sha256: str
    program_id: str
    main_group: str
    artifacts: tuple[MarginfiProtocolArtifact, ...]
    account_vectors: tuple[MarginfiAccountVector, ...]
    instruction_vectors: tuple[MarginfiInstructionVector, ...]
    rpc_evidence: MarginfiReadonlyRpcEvidence
    flashloan_metas: MarginfiFlashloanMetaEvidence
    token_2022: MarginfiToken2022Evidence
    repayment_math: MarginfiRepaymentMathEvidence
    human_review: MarginfiHumanReviewEvidence
    official_sources: tuple[str, ...]
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise MarginfiProtocolConformanceError(
                "unsupported PR-088 protocol evidence schema"
            )
        object.__setattr__(
            self,
            "source_commit",
            _require_git_sha(self.source_commit, field="source_commit"),
        )
        object.__setattr__(
            self,
            "verified_build_hash_sha256",
            _require_sha256(
                self.verified_build_hash_sha256,
                field="verified_build_hash_sha256",
            ),
        )
        object.__setattr__(
            self,
            "program_id",
            _require_pubkey(self.program_id, field="program_id"),
        )
        object.__setattr__(
            self,
            "main_group",
            _require_pubkey(self.main_group, field="main_group"),
        )
        if not self.artifacts:
            raise MarginfiProtocolConformanceError("artifacts cannot be empty")
        if not self.account_vectors:
            raise MarginfiProtocolConformanceError("account_vectors cannot be empty")
        if not self.instruction_vectors:
            raise MarginfiProtocolConformanceError(
                "instruction_vectors cannot be empty"
            )
        artifact_paths = [artifact.path for artifact in self.artifacts]
        if len(artifact_paths) != len(set(artifact_paths)):
            raise MarginfiProtocolConformanceError("artifact paths must be unique")
        artifact_kinds = [artifact.kind for artifact in self.artifacts]
        if len(artifact_kinds) != len(set(artifact_kinds)):
            raise MarginfiProtocolConformanceError("artifact kinds must be unique")
        account_addresses = [vector.account_address for vector in self.account_vectors]
        if len(account_addresses) != len(set(account_addresses)):
            raise MarginfiProtocolConformanceError(
                "account vector addresses must be unique"
            )
        if any(not source.strip() for source in self.official_sources):
            raise MarginfiProtocolConformanceError(
                "official_sources cannot contain empty values"
            )
        if len(self.official_sources) != len(set(self.official_sources)):
            raise MarginfiProtocolConformanceError("official_sources must be unique")

    @property
    def evidence_sha256(self) -> str:
        return sha256_payload(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class MarginfiProtocolConformanceEvaluation:
    schema_version: str
    shadow_execution_capable: bool
    live_execution_allowed: bool
    state: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    evidence_sha256: str
    checks_evaluated: int
    metrics_summary: Mapping[str, int | str]

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def evaluate_marginfi_protocol_conformance(
    evidence: MarginfiProtocolConformanceEvidence,
    thresholds: MarginfiProtocolConformanceThresholds | None = None,
) -> MarginfiProtocolConformanceEvaluation:
    """Validate PR-088 MarginFi protocol evidence without enabling live mode."""

    policy = thresholds or MarginfiProtocolConformanceThresholds()
    blockers: list[str] = []
    warnings: list[str] = []
    checks = 0

    def check(condition: bool, reason: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            blockers.append(reason)

    artifact_kinds = {artifact.kind for artifact in evidence.artifacts}
    account_kinds = {vector.account_kind for vector in evidence.account_vectors}
    instruction_names = {
        vector.instruction_name for vector in evidence.instruction_vectors
    }

    check(evidence.source_commit == PINNED_SOURCE_COMMIT, "SOURCE_COMMIT_MISMATCH")
    check(
        evidence.verified_build_hash_sha256 == EXPECTED_VERIFIED_BUILD_HASH,
        "VERIFIED_BUILD_HASH_MISMATCH",
    )
    check(evidence.program_id == EXPECTED_PROGRAM_ID, "PROGRAM_ID_MISMATCH")
    check(evidence.main_group == EXPECTED_MAIN_GROUP, "MAIN_GROUP_MISMATCH")
    check(
        artifact_kinds == set(policy.required_artifact_kinds),
        "REQUIRED_ARTIFACTS_MISSING",
    )
    check(
        len(evidence.account_vectors) >= policy.min_account_vectors,
        "INSUFFICIENT_ACCOUNT_VECTORS",
    )
    check(
        set(policy.required_account_kinds).issubset(account_kinds),
        "REQUIRED_ACCOUNT_VECTOR_KINDS_MISSING",
    )

    group_vectors = [
        vector
        for vector in evidence.account_vectors
        if vector.account_kind is MarginfiAccountVectorKind.GROUP
    ]
    check(
        any(vector.account_address == EXPECTED_MAIN_GROUP for vector in group_vectors),
        "MAIN_GROUP_VECTOR_MISSING",
    )
    owned_by_marginfi = all(
        vector.owner_program_id == EXPECTED_PROGRAM_ID
        for vector in evidence.account_vectors
        if vector.account_kind
        in {
            MarginfiAccountVectorKind.GROUP,
            MarginfiAccountVectorKind.BANK,
            MarginfiAccountVectorKind.MARGIN_ACCOUNT,
        }
    )
    check(owned_by_marginfi, "MARGINFI_ACCOUNT_OWNER_MISMATCH")

    token_programs = {TOKEN_PROGRAM_ADDRESS, TOKEN_2022_PROGRAM_ADDRESS}
    token_account_owners = all(
        vector.owner_program_id in token_programs
        for vector in evidence.account_vectors
        if vector.account_kind
        in {
            MarginfiAccountVectorKind.MINT,
            MarginfiAccountVectorKind.LIQUIDITY_VAULT,
        }
    )
    check(token_account_owners, "TOKEN_ACCOUNT_OWNER_MISMATCH")

    min_vector_slot = min(
        vector.min_context_slot for vector in evidence.account_vectors
    )
    check(
        min_vector_slot >= evidence.rpc_evidence.min_context_slot,
        "ACCOUNT_VECTOR_CONTEXT_SLOT_STALE",
    )
    check(
        len(evidence.instruction_vectors) >= policy.min_instruction_vectors,
        "INSUFFICIENT_INSTRUCTION_VECTORS",
    )
    check(
        set(policy.required_instruction_names).issubset(instruction_names),
        "REQUIRED_FLASHLOAN_INSTRUCTIONS_MISSING",
    )
    instruction_programs_match = all(
        vector.program_id == EXPECTED_PROGRAM_ID
        for vector in evidence.instruction_vectors
    )
    check(instruction_programs_match, "INSTRUCTION_PROGRAM_MISMATCH")

    rpc = evidence.rpc_evidence
    check(rpc.program_executable_verified, "RPC_PROGRAM_UNVERIFIED")
    check(rpc.group_relationships_verified, "RPC_GROUP_RELATIONSHIPS_UNVERIFIED")
    check(rpc.bank_relationships_verified, "RPC_BANK_RELATIONSHIPS_UNVERIFIED")
    check(rpc.oracle_relationships_verified, "RPC_ORACLE_RELATIONSHIPS_UNVERIFIED")
    check(rpc.fee_pause_config_verified, "RPC_FEE_PAUSE_CONFIG_UNVERIFIED")

    flashloan = evidence.flashloan_metas
    check(flashloan.start_end_index_bound, "FLASHLOAN_END_INDEX_UNVERIFIED")
    check(
        flashloan.start_requires_instructions_sysvar,
        "FLASHLOAN_INSTRUCTIONS_SYSVAR_MISSING",
    )
    check(
        flashloan.start_and_end_same_marginfi_account,
        "FLASHLOAN_ACCOUNT_PAIR_UNVERIFIED",
    )
    check(
        flashloan.signer_matches_marginfi_authority,
        "FLASHLOAN_SIGNER_AUTHORITY_UNVERIFIED",
    )
    check(
        flashloan.borrow_repay_bank_order_verified,
        "FLASHLOAN_BORROW_REPAY_ORDER_UNVERIFIED",
    )
    check(
        flashloan.account_meta_order_verified,
        "FLASHLOAN_ACCOUNT_META_ORDER_UNVERIFIED",
    )
    check(flashloan.no_cpi_end_flashloan, "FLASHLOAN_END_CPI_GUARD_UNVERIFIED")

    token_2022 = evidence.token_2022
    check(token_2022.token_program_paths_verified, "TOKEN_PROGRAM_PATHS_UNVERIFIED")
    check(
        token_2022.token_2022_program_paths_verified,
        "TOKEN_2022_PATHS_UNVERIFIED",
    )
    check(
        token_2022.mint_owner_matches_token_program,
        "TOKEN_MINT_OWNER_UNVERIFIED",
    )
    check(
        token_2022.vault_owner_matches_token_program,
        "TOKEN_VAULT_OWNER_UNVERIFIED",
    )

    repayment = evidence.repayment_math
    check(
        repayment.sample_count >= policy.min_repayment_samples,
        "INSUFFICIENT_REPAYMENT_SAMPLES",
    )
    check(
        repayment.max_liability_share_error_bps
        <= policy.max_liability_share_error_bps,
        "LIABILITY_SHARE_ERROR_TOO_HIGH",
    )
    check(
        repayment.max_repayment_error_bps <= policy.max_repayment_error_bps,
        "REPAYMENT_ERROR_TOO_HIGH",
    )
    check(repayment.fee_model_verified, "REPAYMENT_FEE_MODEL_UNVERIFIED")
    check(
        repayment.health_after_flashloan_verified,
        "REPAYMENT_HEALTH_CHECK_UNVERIFIED",
    )

    review = evidence.human_review
    check(bool(review.reviewer.strip()), "HUMAN_REVIEW_MISSING")
    check(bool(review.signed_by.strip()), "CONFORMANCE_BUNDLE_NOT_SIGNED")
    check(
        bool(review.signature_reference.strip()),
        "CONFORMANCE_SIGNATURE_REFERENCE_MISSING",
    )

    if "https://docs.marginfi.com/mfi-v2" not in evidence.official_sources:
        warnings.append("MARGINFI_PROGRAM_DOC_SOURCE_NOT_REFERENCED")
    if "https://docs.marginfi.com/ts-sdk" not in evidence.official_sources:
        warnings.append("MARGINFI_SDK_DOC_SOURCE_NOT_REFERENCED")
    if (
        "https://solana.com/docs/programs/verified-builds"
        not in evidence.official_sources
    ):
        warnings.append("SOLANA_VERIFIED_BUILD_SOURCE_NOT_REFERENCED")

    unique_blockers = tuple(dict.fromkeys(blockers))
    shadow_ready = not unique_blockers
    return MarginfiProtocolConformanceEvaluation(
        schema_version=RESULT_SCHEMA_VERSION,
        shadow_execution_capable=shadow_ready,
        live_execution_allowed=False,
        state="shadow-execution-capable" if shadow_ready else "blocked",
        blockers=unique_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
        evidence_sha256=evidence.evidence_sha256,
        checks_evaluated=checks,
        metrics_summary={
            "source_commit": evidence.source_commit,
            "program_id": evidence.program_id,
            "main_group": evidence.main_group,
            "account_vectors": len(evidence.account_vectors),
            "instruction_vectors": len(evidence.instruction_vectors),
            "repayment_samples": repayment.sample_count,
            "token_2022_samples": token_2022.token_2022_sample_count,
        },
    )


def assert_marginfi_protocol_conformance(
    evidence: MarginfiProtocolConformanceEvidence,
    thresholds: MarginfiProtocolConformanceThresholds | None = None,
) -> MarginfiProtocolConformanceEvaluation:
    """Return shadow-capable evidence or fail closed with stable blocker codes."""

    evaluation = evaluate_marginfi_protocol_conformance(evidence, thresholds)
    if not evaluation.shadow_execution_capable:
        blockers = ",".join(evaluation.blockers)
        raise MarginfiProtocolConformanceError(
            f"PR088_MARGINFI_PROTOCOL_BLOCKED:{blockers}"
        )
    return evaluation


def _require_non_empty(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MarginfiProtocolConformanceError(f"{field} must be a non-empty string")
    return value.strip()


def _require_bool(value: bool, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise MarginfiProtocolConformanceError(f"{field} must be boolean")
    return value


def _require_non_negative_int(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MarginfiProtocolConformanceError(
            f"{field} must be a non-negative integer"
        )
    return value


def _require_positive_int(value: int, *, field: str) -> int:
    checked = _require_non_negative_int(value, field=field)
    if checked == 0:
        raise MarginfiProtocolConformanceError(f"{field} must be positive")
    return checked


def _require_bps(value: int, *, field: str) -> int:
    checked = _require_non_negative_int(value, field=field)
    if checked > 10_000:
        raise MarginfiProtocolConformanceError(f"{field} must be <= 10000 bps")
    return checked


def _require_sha256(value: str, *, field: str) -> str:
    lowered = str(value).lower()
    if not _SHA256_RE.fullmatch(lowered):
        raise MarginfiProtocolConformanceError(
            f"{field} must be a sha256 hex digest"
        )
    if lowered == "0" * 64 or len(set(lowered)) == 1:
        raise MarginfiProtocolConformanceError(
            f"{field} must be a non-placeholder sha256 digest"
        )
    return lowered


def _require_git_sha(value: str, *, field: str) -> str:
    lowered = str(value).lower()
    if not _GIT_SHA_RE.fullmatch(lowered) or lowered == "0" * 40:
        raise MarginfiProtocolConformanceError(
            f"{field} must be a non-placeholder git SHA"
        )
    return lowered


def _require_pubkey(value: str, *, field: str) -> str:
    try:
        return validate_pubkey(str(value), field=field)
    except ChainRegistryError as exc:
        raise MarginfiProtocolConformanceError(str(exc)) from exc


def _require_relative_path(value: str, *, field: str) -> str:
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    has_bad_part = any(part in {"", ".", ".."} for part in parts)
    if not value or normalized.startswith(("/", "~")) or has_bad_part:
        raise MarginfiProtocolConformanceError(
            f"{field} must be a normalized repository-relative path"
        )
    return normalized


def _require_timezone(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MarginfiProtocolConformanceError(f"{field} must be timezone-aware")
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
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_jsonable(item) for item in value]
    return value


def stable_json(payload: Any) -> str:
    return json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"))


def sha256_payload(payload: Any) -> str:
    return hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()
