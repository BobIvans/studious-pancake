"""AGG-01 qualification baseline and verified-reuse admission contracts.

The module is offline and effect-free. It records the current checkout,
installed entrypoint reachability, evidence levels, AGG-01 NF coverage, and
upstream provenance/reuse decisions. Git/network/merge effects remain owned by
the coding agent and are represented here only by immutable receipts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
import sys
import tomllib
from typing import Iterable, Sequence

AGG01_SCHEMA = "agg01.foundation.v1"
AGG01_REQUIRED_NF = tuple(
    [f"NF-{n:03d}" for n in range(1, 12)]
    + ["NF-016"]
    + [f"NF-{n:03d}" for n in range(17, 31)]
    + ["NF-096", "NF-111"]
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class Agg01ContractError(ValueError):
    pass


class EvidenceLevel(StrEnum):
    STATIC_OBSERVED = "STATIC_OBSERVED"
    TESTED_OFFLINE = "TESTED_OFFLINE"
    NETWORK_READ = "NETWORK_READ"
    EXACT_SIMULATED = "EXACT_SIMULATED"
    OBSERVED_LANDED = "OBSERVED_LANDED"
    FINALIZED = "FINALIZED"
    RESEARCH_HYPOTHESIS = "RESEARCH_HYPOTHESIS"
    UNKNOWN = "UNKNOWN"


class ImplementationStatus(StrEnum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    IMPLEMENTED_OFFLINE = "IMPLEMENTED_OFFLINE"
    MERGED_CODE = "MERGED_CODE"
    BLOCKED = "BLOCKED"


class IntegrationDecision(StrEnum):
    REUSE = "reuse"
    REPAIR = "repair"
    INTEGRATE = "integrate"
    NEW = "new"
    RESEARCH = "research"
    PAUSED = "paused"


class ScopeDisposition(StrEnum):
    REQUIRED = "REQUIRED"
    RESEARCH = "RESEARCH"
    DEFERRED = "DEFERRED"
    REJECTED_WITH_EVIDENCE = "REJECTED_WITH_EVIDENCE"


class BoundaryMode(StrEnum):
    PORT_DIFF = "PORT+DIFF"
    WRAP = "WRAP"
    TOOL = "TOOL"
    REIMPLEMENT = "REIMPLEMENT"


def _text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Agg01ContractError(f"{label} is required")
    return value


def _sha(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise Agg01ContractError(f"{label} must be lowercase sha256")
    return value


def _git_sha(value: str, label: str) -> str:
    if not isinstance(value, str) or not _GIT_SHA.fullmatch(value):
        raise Agg01ContractError(f"{label} must be full lowercase git sha")
    return value


def _safe_path(value: str) -> str:
    normalized = _text(value, "path").replace("\\", "/")
    path = Path(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise Agg01ContractError("path must be repository-relative")
    return normalized


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class TypedFailure:
    code: str
    stage: str
    retryable: bool
    dependency_ids: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        _text(self.code, "code")
        _text(self.stage, "stage")
        if type(self.retryable) is not bool:
            raise Agg01ContractError("retryable must be bool")


@dataclass(frozen=True, slots=True)
class CampaignManifest:
    campaign_id: str
    repo_full_name: str
    repo_commit: str
    spec_version: str
    requested_scope: tuple[str, ...]
    effect_policy: str
    started_at_utc: str
    slumlord_required: bool = True
    marginfi_paused: bool = True

    def __post_init__(self) -> None:
        _text(self.campaign_id, "campaign_id")
        _text(self.repo_full_name, "repo_full_name")
        _git_sha(self.repo_commit, "repo_commit")
        _text(self.spec_version, "spec_version")
        if not self.requested_scope:
            raise Agg01ContractError("requested_scope must not be empty")
        if not self.slumlord_required or not self.marginfi_paused:
            raise Agg01ContractError("AGG-01 scope policy mismatch")
        parsed = datetime.fromisoformat(self.started_at_utc)
        if parsed.tzinfo is None:
            raise Agg01ContractError("started_at_utc must be timezone-aware")


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    evidence_id: str
    level: EvidenceLevel
    sha256: str
    source: str
    generation: int

    def __post_init__(self) -> None:
        _text(self.evidence_id, "evidence_id")
        _sha(self.sha256, "sha256")
        _text(self.source, "source")
        if type(self.generation) is not int or self.generation < 1:
            raise Agg01ContractError("generation must be positive integer")


@dataclass(frozen=True, slots=True)
class EvidenceIndex:
    campaign_id: str
    records: tuple[EvidenceRecord, ...] = ()

    def add(self, record: EvidenceRecord) -> "EvidenceIndex":
        if record.evidence_id in {item.evidence_id for item in self.records}:
            raise Agg01ContractError("duplicate evidence_id")
        return EvidenceIndex(self.campaign_id, (*self.records, record))


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    repo_commit: str
    base_commit: str
    dirty_paths: tuple[str, ...]
    file_manifest: tuple[tuple[str, str], ...]
    archive_sha256: str | None = None

    def __post_init__(self) -> None:
        _git_sha(self.repo_commit, "repo_commit")
        _git_sha(self.base_commit, "base_commit")
        paths = [path for path, _ in self.file_manifest]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise Agg01ContractError("manifest must be sorted and unique")
        for path, digest in self.file_manifest:
            _safe_path(path)
            _sha(digest, path)
        if self.archive_sha256 is not None:
            _sha(self.archive_sha256, "archive_sha256")

    @property
    def digest(self) -> str:
        return _digest(
            {
                "repo_commit": self.repo_commit,
                "base_commit": self.base_commit,
                "dirty_paths": self.dirty_paths,
                "file_manifest": self.file_manifest,
                "archive_sha256": self.archive_sha256,
            }
        )


@dataclass(frozen=True, slots=True)
class CoverageRow:
    nf_id: str
    owner: str
    decision: IntegrationDecision
    implementation_status: ImplementationStatus
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.nf_id not in AGG01_REQUIRED_NF:
            raise Agg01ContractError("NF outside AGG-01")
        _text(self.owner, "owner")


@dataclass(frozen=True, slots=True)
class CoverageMatrix:
    rows: tuple[CoverageRow, ...]

    @property
    def missing(self) -> tuple[str, ...]:
        ids = [row.nf_id for row in self.rows]
        if len(ids) != len(set(ids)):
            raise Agg01ContractError("duplicate coverage row")
        observed = set(ids)
        return tuple(nf for nf in AGG01_REQUIRED_NF if nf not in observed)


@dataclass(frozen=True, slots=True)
class EntrypointTrace:
    console_script: str
    module: str
    function: str
    runtime_owner: str
    composition_owner: str
    installed_reachable: bool


@dataclass(frozen=True, slots=True)
class EnvironmentManifest:
    python_version: str
    pyproject_sha256: str
    lock_hashes: tuple[tuple[str, str], ...]
    supported: bool


@dataclass(frozen=True, slots=True)
class CommandResult:
    command: str
    exit_code: int
    passed: int | None = None
    failed: int | None = None
    skipped: int | None = None


@dataclass(frozen=True, slots=True)
class CampaignBaseline:
    campaign_id: str
    snapshot_digest: str
    installed_checks: tuple[CommandResult, ...]
    offline_checks: tuple[CommandResult, ...]
    first_blocking_stage: str | None


@dataclass(frozen=True, slots=True)
class QualificationWorkItem:
    nf_id: str
    owner: str
    disposition: ScopeDisposition
    blocker: str | None


@dataclass(frozen=True, slots=True)
class QualificationWorkQueue:
    items: tuple[QualificationWorkItem, ...]


@dataclass(frozen=True, slots=True)
class UpstreamPin:
    repository: str
    commit: str
    path: str
    symbol: str
    blob_sha: str | None
    artifact_sha256: str | None

    def __post_init__(self) -> None:
        _text(self.repository, "repository")
        _git_sha(self.commit, "commit")
        _safe_path(self.path)
        _text(self.symbol, "symbol")
        if self.artifact_sha256 is not None:
            _sha(self.artifact_sha256, "artifact_sha256")

    @property
    def identity_digest(self) -> str:
        return _digest(
            {
                "repository": self.repository,
                "commit": self.commit,
                "path": self.path,
                "symbol": self.symbol,
                "blob_sha": self.blob_sha,
                "artifact_sha256": self.artifact_sha256,
            }
        )


@dataclass(frozen=True, slots=True)
class LicenseDecision:
    permitted: bool
    spdx: str | None
    notice_required: bool
    notice_sha256: str | None

    def __post_init__(self) -> None:
        if self.permitted and not self.spdx:
            raise Agg01ContractError("permitted license needs SPDX identity")
        if self.notice_sha256 is not None:
            _sha(self.notice_sha256, "notice_sha256")


@dataclass(frozen=True, slots=True)
class ConformanceVector:
    vector_id: str
    input_sha256: str
    expected_sha256: str

    def __post_init__(self) -> None:
        _text(self.vector_id, "vector_id")
        _sha(self.input_sha256, "input_sha256")
        _sha(self.expected_sha256, "expected_sha256")


@dataclass(frozen=True, slots=True)
class VectorSet:
    vectors: tuple[ConformanceVector, ...]

    @property
    def digest(self) -> str:
        if not self.vectors:
            raise Agg01ContractError("at least one conformance vector is required")
        return _digest(
            tuple(
                (v.vector_id, v.input_sha256, v.expected_sha256)
                for v in self.vectors
            )
        )


@dataclass(frozen=True, slots=True)
class SupplyChainReview:
    build_hooks_reviewed: bool
    hidden_network_effects: bool
    secret_loading: bool
    unknown_binaries: bool

    @property
    def safe(self) -> bool:
        return (
            self.build_hooks_reviewed
            and not self.hidden_network_effects
            and not self.secret_loading
            and not self.unknown_binaries
        )


@dataclass(frozen=True, slots=True)
class BoundaryADR:
    mode: BoundaryMode
    unsigned_only: bool
    signing_allowed: bool
    sending_allowed: bool

    def __post_init__(self) -> None:
        if not self.unsigned_only or self.signing_allowed or self.sending_allowed:
            raise Agg01ContractError("AGG-01 boundary must remain unsigned")


@dataclass(frozen=True, slots=True)
class AdapterContract:
    contract_id: str
    required_state: tuple[str, ...]
    outputs: tuple[str, ...]
    pure_math: bool
    hidden_network_allowed: bool
    version: int

    def __post_init__(self) -> None:
        _text(self.contract_id, "contract_id")
        if self.hidden_network_allowed:
            raise Agg01ContractError("hidden network is forbidden")
        if type(self.version) is not int or self.version < 1:
            raise Agg01ContractError("version must be positive integer")


@dataclass(frozen=True, slots=True)
class DifferentialCase:
    vector_id: str
    local_sha256: str
    expected_sha256: str


@dataclass(frozen=True, slots=True)
class DifferentialReport:
    cases: tuple[DifferentialCase, ...]

    @property
    def passed(self) -> bool:
        return bool(self.cases) and all(
            case.local_sha256 == case.expected_sha256 for case in self.cases
        )


@dataclass(frozen=True, slots=True)
class ReuseAdmission:
    upstream: UpstreamPin
    license: LicenseDecision
    vectors: VectorSet
    supply_chain: SupplyChainReview
    boundary: BoundaryADR
    adapter: AdapterContract
    admission_digest: str

    def __post_init__(self) -> None:
        if not self.license.permitted:
            raise Agg01ContractError("reuse requires permitted license")
        if not self.supply_chain.safe:
            raise Agg01ContractError("reuse requires safe supply chain")
        _sha(self.admission_digest, "admission_digest")


@dataclass(frozen=True, slots=True)
class DriftEvent:
    old_identity: str
    new_identity: str | None
    source_reachable: bool
    requalification_required: bool


@dataclass(frozen=True, slots=True)
class MergeReceipt:
    base_sha: str
    head_sha: str
    merge_sha: str
    required_checks_passed: bool

    def __post_init__(self) -> None:
        for value, label in (
            (self.base_sha, "base_sha"),
            (self.head_sha, "head_sha"),
            (self.merge_sha, "merge_sha"),
        ):
            _git_sha(value, label)
        if not self.required_checks_passed:
            raise Agg01ContractError("merge receipt requires passed checks")


def open_campaign(
    *,
    repo_full_name: str,
    repo_commit: str,
    spec_version: str,
    requested_scope: Sequence[str],
    effect_policy: str,
    campaign_id: str | None = None,
) -> tuple[CampaignManifest, EvidenceIndex]:
    started = datetime.now(timezone.utc).isoformat()
    cid = campaign_id or f"agg01-{repo_commit[:12]}"
    manifest = CampaignManifest(
        cid,
        repo_full_name,
        repo_commit,
        spec_version,
        tuple(requested_scope),
        effect_policy,
        started,
    )
    return manifest, EvidenceIndex(cid)


def freeze_snapshot(
    repo_root: str | Path,
    *,
    repo_commit: str,
    base_commit: str,
    dirty_paths: Sequence[str] = (),
    archive_sha256: str | None = None,
) -> SourceSnapshot:
    root = Path(repo_root).resolve()
    manifest: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.parts or ".venv" in path.parts:
            continue
        if path.is_symlink():
            raise Agg01ContractError("snapshot rejects symlink")
        rel = path.relative_to(root).as_posix()
        manifest.append((rel, hashlib.sha256(path.read_bytes()).hexdigest()))
    return SourceSnapshot(
        repo_commit,
        base_commit,
        tuple(dirty_paths),
        tuple(manifest),
        archive_sha256,
    )


def map_entrypoints(repo_root: str | Path) -> EntrypointTrace:
    root = Path(repo_root)
    pyproject = tomllib.loads(
        (root / "pyproject.toml").read_text(encoding="utf-8")
    )
    script = str(pyproject["project"]["scripts"]["flashloan-bot"])
    runtime = (root / "src/runtime/runtime_entrypoint.py").read_text(
        encoding="utf-8"
    )
    return EntrypointTrace(
        "flashloan-bot",
        script.split(":", 1)[0],
        script.split(":", 1)[1],
        "src.runtime.runtime_entrypoint",
        "src.runtime.core_v1_composition.build_core_v1_composition",
        "build_core_v1_composition" in runtime,
    )


def build_hermetic_environment(repo_root: str | Path) -> EnvironmentManifest:
    root = Path(repo_root)
    pyproject = root / "pyproject.toml"
    raw = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    requires = str(raw["project"]["requires-python"])
    locks: list[tuple[str, str]] = []
    for name in ("requirements.txt", "requirements-dev.txt"):
        path = root / name
        if path.is_file():
            locks.append((name, hashlib.sha256(path.read_bytes()).hexdigest()))
    return EnvironmentManifest(
        ".".join(map(str, sys.version_info[:3])),
        hashlib.sha256(pyproject.read_bytes()).hexdigest(),
        tuple(locks),
        sys.version_info[:2] == (3, 13)
        and ">=3.13" in requires
        and "<3.14" in requires,
    )


def classify_evidence(
    evidence_id: str,
    level: EvidenceLevel,
    sha256: str,
    source: str,
    generation: int,
) -> EvidenceRecord:
    return EvidenceRecord(evidence_id, level, sha256, source, generation)


def reconcile_scope(rows: Iterable[CoverageRow]) -> CoverageMatrix:
    return CoverageMatrix(tuple(rows))


def close_baseline_map(rows: Sequence[CoverageRow]) -> QualificationWorkQueue:
    matrix = CoverageMatrix(tuple(rows))
    items = [
        QualificationWorkItem(
            row.nf_id,
            row.owner,
            ScopeDisposition.RESEARCH
            if row.decision is IntegrationDecision.RESEARCH
            else ScopeDisposition.REQUIRED,
            "MISSING_IMPLEMENTATION_EVIDENCE"
            if row.implementation_status is ImplementationStatus.BLOCKED
            else None,
        )
        for row in matrix.rows
    ]
    items.extend(
        QualificationWorkItem(
            nf_id,
            "unassigned",
            ScopeDisposition.REQUIRED,
            "MISSING_COVERAGE_ROW",
        )
        for nf_id in matrix.missing
    )
    return QualificationWorkQueue(tuple(items))


def record_campaign_baseline(
    campaign_id: str,
    snapshot: SourceSnapshot,
    installed_checks: Sequence[CommandResult],
    offline_checks: Sequence[CommandResult],
    first_blocking_stage: str | None,
) -> CampaignBaseline:
    return CampaignBaseline(
        campaign_id,
        snapshot.digest,
        tuple(installed_checks),
        tuple(offline_checks),
        first_blocking_stage,
    )


def run_differential_tests(
    cases: Sequence[DifferentialCase],
) -> DifferentialReport:
    report = DifferentialReport(tuple(cases))
    if not report.passed:
        raise Agg01ContractError("differential conformance mismatch")
    return report


def build_reuse_admission(
    *,
    upstream: UpstreamPin,
    license: LicenseDecision,
    vectors: VectorSet,
    supply_chain: SupplyChainReview,
    boundary: BoundaryADR,
    adapter: AdapterContract,
) -> ReuseAdmission:
    digest = _digest(
        {
            "upstream": upstream.identity_digest,
            "license": license,
            "vectors": vectors.digest,
            "supply_chain": supply_chain,
            "boundary": boundary,
            "adapter": adapter,
        }
    )
    return ReuseAdmission(
        upstream, license, vectors, supply_chain, boundary, adapter, digest
    )


def monitor_upstream_drift(old: UpstreamPin, new: UpstreamPin | None) -> DriftEvent:
    if new is None:
        return DriftEvent(old.identity_digest, None, False, True)
    changed = old.identity_digest != new.identity_digest
    return DriftEvent(old.identity_digest, new.identity_digest, True, changed)


__all__ = [
    "AGG01_REQUIRED_NF",
    "AdapterContract",
    "Agg01ContractError",
    "BoundaryADR",
    "BoundaryMode",
    "CampaignBaseline",
    "CampaignManifest",
    "CommandResult",
    "ConformanceVector",
    "CoverageMatrix",
    "CoverageRow",
    "DifferentialCase",
    "DifferentialReport",
    "DriftEvent",
    "EntrypointTrace",
    "EnvironmentManifest",
    "EvidenceIndex",
    "EvidenceLevel",
    "EvidenceRecord",
    "ImplementationStatus",
    "IntegrationDecision",
    "LicenseDecision",
    "MergeReceipt",
    "QualificationWorkItem",
    "QualificationWorkQueue",
    "ReuseAdmission",
    "ScopeDisposition",
    "SourceSnapshot",
    "SupplyChainReview",
    "TypedFailure",
    "UpstreamPin",
    "VectorSet",
    "build_hermetic_environment",
    "build_reuse_admission",
    "classify_evidence",
    "close_baseline_map",
    "freeze_snapshot",
    "map_entrypoints",
    "monitor_upstream_drift",
    "open_campaign",
    "record_campaign_baseline",
    "reconcile_scope",
    "run_differential_tests",
]
