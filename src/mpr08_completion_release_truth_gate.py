"""MPR-08 completion ledger, package surface and release truth gate."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Iterable, Sequence


SCHEMA_VERSION = "mpr08.completion-release-truth-gate.v1"
LEDGER_SCHEMA_PREFIX = "mpr.completion-ledger.v"

COMPLETED_FOUNDATION_WORK: tuple[str, ...] = (
    "MPR-01",
    "MPR-02",
    "MPR-03",
    "MPR-04",
    "MPR-05",
    "MPR-06",
    "MPR-07",
)

POST_COMPLETION_WORK: tuple[str, ...] = (
    "MPR-08",
    "MPR-09",
    "MPR-10",
    "MPR-11",
    "MPR-12",
)

REQUIRED_INSTALLED_COMMANDS: tuple[str, ...] = (
    "flashloan-bot",
    "flashloan-bot-healthcheck",
    "flashloan-contracts",
    "flashloan-checks",
    "flashloan-release-evidence",
)

REQUIRED_MIRRORS: tuple[str, ...] = (
    "capabilities",
    "product-contract",
    "external-contracts",
    "production-surface",
)

MAX_ARTIFACT_COUNT = 32
MAX_SINGLE_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_TOTAL_ARTIFACT_BYTES = 512 * 1024 * 1024

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
WORK_ID_RE = re.compile(r"^MPR-[0-9]{2}$")


class MPR08GateState(str, Enum):
    READY_FOR_COMPLETION_RELEASE_TRUTH = "ready_for_completion_release_truth"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class WorkPackageEvidence:
    work_id: str
    status: str
    source_commit: str
    generation: int
    migration_hash: str | None = None
    supersedes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReleaseMirrorEvidence:
    name: str
    schema_version: str
    generation: int
    ledger_digest: str
    release_model_digest: str
    work_ids: tuple[str, ...]


@dataclass(frozen=True)
class InstalledCommandEvidence:
    name: str
    entrypoint: str
    manifest_listed: bool
    no_network_smoke_passed: bool
    policy_smoke_passed: bool


@dataclass(frozen=True)
class ArtifactEvidence:
    name: str
    digest: str
    source_commit: str
    source_tree_hash: str
    size_bytes: int
    bounded_hashing_used: bool


@dataclass(frozen=True)
class SignerTrustEvidence:
    key_id: str
    public_key_hash: str
    not_before_unix_ns: int
    not_after_unix_ns: int
    revoked: bool = False


@dataclass(frozen=True)
class BuildProvenanceEvidence:
    source_commit: str
    git_head_commit: str
    source_tree_hash: str
    clean_tree: bool
    wheel_source_commit: str
    image_source_commit: str
    builder_base_image_digest: str
    dependency_lock_hash: str
    dependencies_hash_locked: bool
    offline_wheelhouse_used: bool
    reproducible_build_verified: bool


@dataclass(frozen=True)
class MPR08CompletionReleaseEvidence:
    ledger_schema_version: str
    ledger_digest: str
    release_model_digest: str
    work_packages: tuple[WorkPackageEvidence, ...]
    mirrors: tuple[ReleaseMirrorEvidence, ...]
    installed_commands: tuple[InstalledCommandEvidence, ...]
    artifacts: tuple[ArtifactEvidence, ...]
    signer_trust: tuple[SignerTrustEvidence, ...]
    selected_release_signer_key_id: str
    produced_at_unix_ns: int
    verified_at_unix_ns: int
    max_attestation_age_ns: int
    deployment_nonce: str
    consumed_deployment_nonces: tuple[str, ...]
    build: BuildProvenanceEvidence
    transaction_signer_requested: bool = False
    sender_requested: bool = False
    live_execution_requested: bool = False


@dataclass(frozen=True)
class MPR08Violation:
    code: str
    message: str


@dataclass(frozen=True)
class MPR08CompletionReleaseReport:
    schema_version: str
    state: MPR08GateState
    blockers: tuple[MPR08Violation, ...]
    evidence_hash: str
    required_completed_work: tuple[str, ...]
    required_installed_commands: tuple[str, ...]
    transaction_signer_allowed: bool
    sender_allowed: bool
    live_execution_allowed: bool


def evaluate_mpr08_completion_release_truth(
    evidence: MPR08CompletionReleaseEvidence,
) -> MPR08CompletionReleaseReport:
    blockers: list[MPR08Violation] = []

    _validate_no_runtime_enablement(evidence, blockers)
    _validate_ledger(evidence, blockers)
    _validate_mirrors(evidence, blockers)
    _validate_commands(evidence, blockers)
    _validate_artifacts(evidence, blockers)
    _validate_build_provenance(evidence, blockers)
    _validate_release_trust(evidence, blockers)
    _validate_freshness(evidence, blockers)

    unique = tuple(_dedupe(blockers))
    state = (
        MPR08GateState.BLOCKED
        if unique
        else MPR08GateState.READY_FOR_COMPLETION_RELEASE_TRUTH
    )
    return MPR08CompletionReleaseReport(
        schema_version=SCHEMA_VERSION,
        state=state,
        blockers=unique,
        evidence_hash=_stable_hash(evidence),
        required_completed_work=COMPLETED_FOUNDATION_WORK,
        required_installed_commands=REQUIRED_INSTALLED_COMMANDS,
        transaction_signer_allowed=False,
        sender_allowed=False,
        live_execution_allowed=False,
    )


def _validate_no_runtime_enablement(
    evidence: MPR08CompletionReleaseEvidence,
    blockers: list[MPR08Violation],
) -> None:
    if evidence.transaction_signer_requested:
        _add(
            blockers,
            "MPR08_TRANSACTION_SIGNER_REQUESTED",
            "MPR-08 cannot enable transaction signing",
        )
    if evidence.sender_requested:
        _add(blockers, "MPR08_SENDER_REQUESTED", "MPR-08 cannot enable sender submission")
    if evidence.live_execution_requested:
        _add(blockers, "MPR08_LIVE_REQUESTED", "MPR-08 cannot enable live execution")


def _validate_ledger(
    evidence: MPR08CompletionReleaseEvidence,
    blockers: list[MPR08Violation],
) -> None:
    if not evidence.ledger_schema_version.startswith(LEDGER_SCHEMA_PREFIX):
        _add(
            blockers,
            "MPR08_BAD_LEDGER_SCHEMA",
            "completion ledger must use the versioned MPR schema",
        )
    if not _is_strict_sha256(evidence.ledger_digest):
        _add(blockers, "MPR08_BAD_LEDGER_DIGEST", "ledger digest must be strict sha256")
    if not _is_strict_sha256(evidence.release_model_digest):
        _add(
            blockers,
            "MPR08_BAD_RELEASE_MODEL_DIGEST",
            "release model digest must be strict sha256",
        )

    packages_by_id = {item.work_id: item for item in evidence.work_packages}
    if len(packages_by_id) != len(evidence.work_packages):
        _add(blockers, "MPR08_DUPLICATE_WORK_ID", "completion ledger contains duplicate work IDs")

    for work_id in COMPLETED_FOUNDATION_WORK:
        item = packages_by_id.get(work_id)
        if item is None:
            _add(blockers, "MPR08_FOUNDATION_WORK_MISSING", f"{work_id} is absent from completion ledger")
        elif item.status != "completed":
            _add(blockers, "MPR08_FOUNDATION_WORK_NOT_COMPLETED", f"{work_id} must be completed")

    active = packages_by_id.get("MPR-08")
    if active is None:
        _add(blockers, "MPR08_ACTIVE_WORK_MISSING", "MPR-08 must be represented in the ledger")
    elif active.status not in {"active", "completed"}:
        _add(blockers, "MPR08_ACTIVE_WORK_BAD_STATUS", "MPR-08 must be active or completed")

    for work_id in POST_COMPLETION_WORK[1:]:
        item = packages_by_id.get(work_id)
        if item is None:
            _add(blockers, "MPR08_FUTURE_WORK_MISSING", f"{work_id} must be represented as planned")
        elif item.status not in {"planned", "active", "completed"}:
            _add(blockers, "MPR08_FUTURE_WORK_BAD_STATUS", f"{work_id} has invalid status {item.status!r}")

    for item in evidence.work_packages:
        _validate_work_package(item, evidence.build.source_commit, blockers)


def _validate_work_package(
    item: WorkPackageEvidence,
    source_commit: str,
    blockers: list[MPR08Violation],
) -> None:
    if not item.work_id:
        _add(blockers, "MPR08_EMPTY_WORK_ID", "work package ID cannot be empty")
    if WORK_ID_RE.match(item.work_id) is None and item.migration_hash is None:
        _add(
            blockers,
            "MPR08_UNKNOWN_WORK_WITHOUT_MIGRATION",
            f"{item.work_id} needs signed schema migration",
        )
    if item.migration_hash is not None and not _is_strict_sha256(item.migration_hash):
        _add(blockers, "MPR08_BAD_WORK_MIGRATION_HASH", f"{item.work_id} migration hash is invalid")
    if item.status not in {"completed", "active", "planned", "superseded"}:
        _add(blockers, "MPR08_BAD_WORK_STATUS", f"{item.work_id} status is invalid")
    if not _is_commit(item.source_commit):
        _add(blockers, "MPR08_BAD_WORK_SOURCE_COMMIT", f"{item.work_id} source commit is invalid")
    if item.source_commit != source_commit:
        _add(
            blockers,
            "MPR08_WORK_SOURCE_COMMIT_MISMATCH",
            f"{item.work_id} source commit differs from build source",
        )
    if not _is_positive_int(item.generation):
        _add(blockers, "MPR08_BAD_WORK_GENERATION", f"{item.work_id} generation must be positive")


def _validate_mirrors(
    evidence: MPR08CompletionReleaseEvidence,
    blockers: list[MPR08Violation],
) -> None:
    mirror_by_name = {mirror.name: mirror for mirror in evidence.mirrors}
    if len(mirror_by_name) != len(evidence.mirrors):
        _add(blockers, "MPR08_DUPLICATE_MIRROR", "release mirrors contain duplicate names")
    for required_name in REQUIRED_MIRRORS:
        if required_name not in mirror_by_name:
            _add(blockers, "MPR08_REQUIRED_MIRROR_MISSING", f"{required_name} mirror is missing")

    ledger_work_ids = tuple(sorted(item.work_id for item in evidence.work_packages))
    for mirror in evidence.mirrors:
        if not mirror.schema_version.startswith("mpr08.release-mirror."):
            _add(blockers, "MPR08_BAD_MIRROR_SCHEMA", f"{mirror.name} has unsupported schema")
        if mirror.ledger_digest != evidence.ledger_digest:
            _add(
                blockers,
                "MPR08_MIRROR_LEDGER_DIGEST_MISMATCH",
                f"{mirror.name} does not match ledger digest",
            )
        if mirror.release_model_digest != evidence.release_model_digest:
            _add(
                blockers,
                "MPR08_MIRROR_RELEASE_MODEL_MISMATCH",
                f"{mirror.name} does not match release model digest",
            )
        if tuple(sorted(mirror.work_ids)) != ledger_work_ids:
            _add(blockers, "MPR08_MIRROR_WORK_SET_MISMATCH", f"{mirror.name} work IDs differ from ledger")
        if not _is_positive_int(mirror.generation):
            _add(blockers, "MPR08_BAD_MIRROR_GENERATION", f"{mirror.name} generation must be positive")


def _validate_commands(
    evidence: MPR08CompletionReleaseEvidence,
    blockers: list[MPR08Violation],
) -> None:
    observed = tuple(sorted(command.name for command in evidence.installed_commands))
    required = tuple(sorted(REQUIRED_INSTALLED_COMMANDS))
    if observed != required:
        _add(
            blockers,
            "MPR08_INSTALLED_COMMAND_SET_MISMATCH",
            f"installed commands must equal {required!r}, got {observed!r}",
        )

    seen: set[str] = set()
    for command in evidence.installed_commands:
        if command.name in seen:
            _add(blockers, "MPR08_DUPLICATE_COMMAND", f"duplicate installed command {command.name}")
        seen.add(command.name)
        if not command.entrypoint:
            _add(blockers, "MPR08_COMMAND_ENTRYPOINT_MISSING", f"{command.name} entrypoint is empty")
        if not command.manifest_listed:
            _add(blockers, "MPR08_COMMAND_NOT_MANIFESTED", f"{command.name} is outside production-surface manifest")
        if not command.no_network_smoke_passed:
            _add(blockers, "MPR08_COMMAND_NO_NETWORK_SMOKE_MISSING", f"{command.name} lacks clean no-network smoke")
        if not command.policy_smoke_passed:
            _add(blockers, "MPR08_COMMAND_POLICY_SMOKE_MISSING", f"{command.name} lacks policy smoke")


def _validate_artifacts(
    evidence: MPR08CompletionReleaseEvidence,
    blockers: list[MPR08Violation],
) -> None:
    if len(evidence.artifacts) > MAX_ARTIFACT_COUNT:
        _add(blockers, "MPR08_TOO_MANY_ARTIFACTS", "release artifact count exceeds bounded verifier policy")
    total_size = 0
    seen_names: set[str] = set()
    for artifact in evidence.artifacts:
        if artifact.name in seen_names:
            _add(blockers, "MPR08_DUPLICATE_ARTIFACT", f"duplicate artifact {artifact.name}")
        seen_names.add(artifact.name)
        if not artifact.name:
            _add(blockers, "MPR08_ARTIFACT_NAME_MISSING", "artifact name cannot be empty")
        if not _is_strict_sha256(artifact.digest):
            _add(blockers, "MPR08_BAD_ARTIFACT_DIGEST", f"{artifact.name} digest is invalid")
        if artifact.source_commit != evidence.build.source_commit:
            _add(blockers, "MPR08_ARTIFACT_SOURCE_MISMATCH", f"{artifact.name} source commit differs from build")
        if artifact.source_tree_hash != evidence.build.source_tree_hash:
            _add(blockers, "MPR08_ARTIFACT_TREE_MISMATCH", f"{artifact.name} tree hash differs from build")
        if not _is_positive_int(artifact.size_bytes):
            _add(blockers, "MPR08_BAD_ARTIFACT_SIZE", f"{artifact.name} size must be positive")
        elif artifact.size_bytes > MAX_SINGLE_ARTIFACT_BYTES:
            _add(blockers, "MPR08_ARTIFACT_TOO_LARGE", f"{artifact.name} exceeds per-artifact limit")
        total_size += max(artifact.size_bytes, 0)
        if not artifact.bounded_hashing_used:
            _add(blockers, "MPR08_UNBOUNDED_HASHING", f"{artifact.name} must be hashed through bounded streaming")
    if total_size > MAX_TOTAL_ARTIFACT_BYTES:
        _add(blockers, "MPR08_ARTIFACT_TOTAL_TOO_LARGE", "release artifact set exceeds aggregate verifier limit")


def _validate_build_provenance(
    evidence: MPR08CompletionReleaseEvidence,
    blockers: list[MPR08Violation],
) -> None:
    build = evidence.build
    for field_name, value in (
        ("source_commit", build.source_commit),
        ("git_head_commit", build.git_head_commit),
        ("wheel_source_commit", build.wheel_source_commit),
        ("image_source_commit", build.image_source_commit),
    ):
        if not _is_commit(value):
            _add(blockers, "MPR08_BAD_BUILD_COMMIT", f"{field_name} is not a commit SHA")
    if build.source_commit != build.git_head_commit:
        _add(blockers, "MPR08_SOURCE_COMMIT_NOT_GIT_HEAD", "source commit must come from clean Git HEAD")
    if build.source_commit != build.wheel_source_commit:
        _add(blockers, "MPR08_WHEEL_SOURCE_MISMATCH", "wheel metadata must bind to source commit")
    if build.source_commit != build.image_source_commit:
        _add(blockers, "MPR08_IMAGE_SOURCE_MISMATCH", "image metadata must bind to source commit")
    if not _is_strict_sha256(build.source_tree_hash):
        _add(blockers, "MPR08_BAD_SOURCE_TREE_HASH", "source tree hash must be strict sha256")
    if not build.clean_tree:
        _add(blockers, "MPR08_DIRTY_SOURCE_TREE", "release truth must be produced from a clean tree")
    builder_digest = build.builder_base_image_digest.removeprefix("sha256:")
    if not build.builder_base_image_digest.startswith("sha256:") or not _is_strict_sha256(builder_digest):
        _add(blockers, "MPR08_BUILDER_BASE_NOT_DIGEST_PINNED", "builder base image must be digest pinned")
    if not _is_strict_sha256(build.dependency_lock_hash):
        _add(blockers, "MPR08_BAD_DEPENDENCY_LOCK_HASH", "dependency lock hash is invalid")
    if not build.dependencies_hash_locked:
        _add(blockers, "MPR08_DEPENDENCIES_NOT_HASH_LOCKED", "dependencies must be hash locked")
    if not build.offline_wheelhouse_used:
        _add(blockers, "MPR08_OFFLINE_WHEELHOUSE_MISSING", "release build must use an approved offline wheelhouse")
    if not build.reproducible_build_verified:
        _add(blockers, "MPR08_REPRODUCIBLE_BUILD_NOT_VERIFIED", "reproducible build verification is required")


def _validate_release_trust(
    evidence: MPR08CompletionReleaseEvidence,
    blockers: list[MPR08Violation],
) -> None:
    if not evidence.signer_trust:
        _add(blockers, "MPR08_TRUST_REGISTRY_EMPTY", "release signer trust registry cannot be empty")
    trust_by_key_id = {item.key_id: item for item in evidence.signer_trust}
    if len(trust_by_key_id) != len(evidence.signer_trust):
        _add(blockers, "MPR08_DUPLICATE_TRUST_KEY", "trust registry contains duplicate key IDs")
    selected = trust_by_key_id.get(evidence.selected_release_signer_key_id)
    if selected is None:
        _add(blockers, "MPR08_UNREGISTERED_RELEASE_SIGNER", "release signer must be resolved from trusted policy registry")
        return
    if selected.revoked:
        _add(blockers, "MPR08_RELEASE_SIGNER_REVOKED", "selected release signer is revoked")
    if not _is_strict_sha256(selected.public_key_hash):
        _add(blockers, "MPR08_BAD_RELEASE_SIGNER_HASH", "selected release signer public key hash is invalid")
    if evidence.produced_at_unix_ns < selected.not_before_unix_ns:
        _add(blockers, "MPR08_RELEASE_SIGNER_NOT_YET_VALID", "attestation predates signer validity")
    if evidence.produced_at_unix_ns >= selected.not_after_unix_ns:
        _add(blockers, "MPR08_RELEASE_SIGNER_EXPIRED", "attestation is after signer expiry")


def _validate_freshness(
    evidence: MPR08CompletionReleaseEvidence,
    blockers: list[MPR08Violation],
) -> None:
    if not _is_nonnegative_int(evidence.produced_at_unix_ns):
        _add(blockers, "MPR08_BAD_PRODUCED_AT", "produced_at must be non-negative integer")
    if not _is_nonnegative_int(evidence.verified_at_unix_ns):
        _add(blockers, "MPR08_BAD_VERIFIED_AT", "verified_at must be non-negative integer")
    if not _is_positive_int(evidence.max_attestation_age_ns):
        _add(blockers, "MPR08_BAD_MAX_ATTESTATION_AGE", "max attestation age must be positive")
    if evidence.produced_at_unix_ns > evidence.verified_at_unix_ns:
        _add(blockers, "MPR08_FUTURE_ATTESTATION", "attestation cannot be produced in the future")
    if evidence.verified_at_unix_ns - evidence.produced_at_unix_ns > evidence.max_attestation_age_ns:
        _add(blockers, "MPR08_STALE_ATTESTATION", "attestation exceeds maximum allowed age")
    if not evidence.deployment_nonce:
        _add(blockers, "MPR08_DEPLOYMENT_NONCE_MISSING", "deployment nonce is required")
    if evidence.deployment_nonce in set(evidence.consumed_deployment_nonces):
        _add(blockers, "MPR08_REPLAYED_DEPLOYMENT_NONCE", "deployment nonce was already consumed")


def _is_strict_sha256(value: str) -> bool:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        return False
    return value not in {"0" * 64, "f" * 64}


def _is_commit(value: str) -> bool:
    return isinstance(value, str) and COMMIT_RE.fullmatch(value) is not None


def _is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _stable_hash(value: object) -> str:
    payload = json.dumps(_to_jsonable(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _to_jsonable(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return _to_jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_jsonable(val) for key, val in value.items()}
    return value


def _add(blockers: list[MPR08Violation], code: str, message: str) -> None:
    blockers.append(MPR08Violation(code=code, message=message))


def _dedupe(blockers: Iterable[MPR08Violation]) -> Iterable[MPR08Violation]:
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        identity = (blocker.code, blocker.message)
        if identity not in seen:
            seen.add(identity)
            yield blocker
