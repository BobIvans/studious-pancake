"""PR-147 readiness evidence bundle manifest sealing gate.

This module is an offline, fail-closed review boundary. It does not call GitHub,
RPC, Jito, wallets, providers, signers, senders, filesystem scanners or live
runtime paths. It evaluates already-collected evidence metadata and produces a
deterministic manifest hash that later automation can persist or attest.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any

PR147_SCHEMA_VERSION = "pr147.evidence-bundle-manifest.v1"
PR147_RESULT_SCHEMA_VERSION = "pr147.evidence-bundle-result.v1"
PR147_READY_STATE = "evidence-bundle-review-ready"
PR147_BLOCKED_STATE = "blocked"

REQUIRED_PAPER_GATES = (
    "PR-128",  # compute/fee finalization
    "PR-129",  # blockhash/ALT/fork binding
    "PR-131",  # ATA/wSOL/rent lifecycle
    "PR-132",  # observability integrity
    "PR-137",  # CPI call graph
    "PR-140",  # data lineage
    "PR-141",  # paper readiness dependency bridge
    "PR-142",  # paper/live readiness evidence gate
    "PR-145",  # parallel PR merge coordination
)

REQUIRED_LIVE_CANARY_GATES = (
    "PR-105",  # 72h shadow soak
    "PR-130",  # Jito/MEV protection
    "PR-133",  # hermetic artifacts
    "PR-134",  # production sandbox
    "PR-136",  # rooted independent RPC
    "PR-138",  # finalized settlement
    "PR-139",  # scheduled drift
    "PR-143",  # operator acknowledgement
    "PR-144",  # shadow soak evidence gate
)

REQUIRED_BUNDLE_GATES = tuple(
    dict.fromkeys(REQUIRED_PAPER_GATES + REQUIRED_LIVE_CANARY_GATES)
)

_ALLOWED_ARTIFACT_PREFIXES = (
    "evidence/",
    "docs/evidence/",
    "artifacts/release/",
    "artifacts/soak/",
)
_GATE_RE = re.compile(r"^PR-\d{3}$")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9._/\-]+$")


class PR147BundleState(StrEnum):
    """Machine-readable PR-147 result state."""

    BLOCKED = PR147_BLOCKED_STATE
    REVIEW_READY = PR147_READY_STATE


class PR147BundleError(ValueError):
    """Raised when PR-147 evidence-bundle metadata is malformed."""


@dataclass(frozen=True, slots=True)
class PR147EvidenceEntry:
    """One immutable, redacted evidence artifact bound to a roadmap gate."""

    gate_id: str
    artifact_path: str
    evidence_sha256: str
    source_pr_number: int
    source_head_sha: str
    produced_by: str
    reviewed: bool = True
    redacted: bool = True
    immutable: bool = True
    synthetic: bool = False
    expires_at_utc: str | None = None

    def __post_init__(self) -> None:
        _require_gate_id(self.gate_id, "gate_id")
        _require_safe_artifact_path(self.artifact_path)
        _require_sha256(self.evidence_sha256, "evidence_sha256")
        _require_positive_int(self.source_pr_number, "source_pr_number")
        _require_sha1(self.source_head_sha, "source_head_sha")
        _require_nonempty(self.produced_by, "produced_by")
        for field in ("reviewed", "redacted", "immutable", "synthetic"):
            if type(getattr(self, field)) is not bool:
                raise PR147BundleError(f"{field} must be boolean")
        if self.expires_at_utc is not None:
            _require_nonempty(self.expires_at_utc, "expires_at_utc")

    def to_manifest_record(self) -> dict[str, Any]:
        return {
            "artifact_path": self.artifact_path,
            "evidence_sha256": self.evidence_sha256,
            "expires_at_utc": self.expires_at_utc,
            "gate_id": self.gate_id,
            "immutable": self.immutable,
            "produced_by": self.produced_by,
            "redacted": self.redacted,
            "reviewed": self.reviewed,
            "source_head_sha": self.source_head_sha,
            "source_pr_number": self.source_pr_number,
            "synthetic": self.synthetic,
        }


@dataclass(frozen=True, slots=True)
class PR147EvidenceBundleManifest:
    """Readiness/release evidence-bundle manifest for review."""

    repo_full_name: str
    base_main_sha: str
    bundle_branch: str
    generated_at_utc: str
    entries: tuple[PR147EvidenceEntry, ...]
    expected_bundle_sha256: str | None = None
    paper_claim_requested: bool = False
    live_claim_requested: bool = False
    allow_synthetic_evidence: bool = False
    schema_version: str = PR147_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PR147_SCHEMA_VERSION:
            raise PR147BundleError("unsupported PR-147 bundle schema")
        _require_repo(self.repo_full_name)
        _require_sha1(self.base_main_sha, "base_main_sha")
        _require_branch(self.bundle_branch)
        _require_nonempty(self.generated_at_utc, "generated_at_utc")
        if not self.entries:
            raise PR147BundleError("entries are required")
        if self.expected_bundle_sha256 is not None:
            _require_sha256(self.expected_bundle_sha256, "expected_bundle_sha256")
        for field in (
            "paper_claim_requested",
            "live_claim_requested",
            "allow_synthetic_evidence",
        ):
            if type(getattr(self, field)) is not bool:
                raise PR147BundleError(f"{field} must be boolean")

    @property
    def bundle_sha256(self) -> str:
        return _hash_json(self.to_manifest_record(include_expected=False))

    def to_manifest_record(self, *, include_expected: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "allow_synthetic_evidence": self.allow_synthetic_evidence,
            "base_main_sha": self.base_main_sha,
            "bundle_branch": self.bundle_branch,
            "entries": [
                entry.to_manifest_record()
                for entry in sorted(
                    self.entries,
                    key=lambda item: (
                        item.gate_id,
                        item.source_pr_number,
                        item.artifact_path,
                    ),
                )
            ],
            "generated_at_utc": self.generated_at_utc,
            "live_claim_requested": self.live_claim_requested,
            "paper_claim_requested": self.paper_claim_requested,
            "repo_full_name": self.repo_full_name,
            "schema_version": self.schema_version,
        }
        if include_expected:
            payload["expected_bundle_sha256"] = self.expected_bundle_sha256
        return payload


@dataclass(frozen=True, slots=True)
class PR147EvidenceBundleDecision:
    """Fail-closed readiness for an evidence bundle; not runtime permission."""

    schema_version: str
    state: PR147BundleState
    review_ready: bool
    paper_claim_allowed: bool
    live_claim_allowed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    bundle_sha256: str
    present_gate_ids: tuple[str, ...]
    required_gate_ids: tuple[str, ...]
    checks_evaluated: int
    metrics_summary: dict[str, int | str | bool]

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def evaluate_pr147_evidence_bundle(
    manifest: PR147EvidenceBundleManifest,
    *,
    required_gate_ids: tuple[str, ...] = REQUIRED_BUNDLE_GATES,
) -> PR147EvidenceBundleDecision:
    """Evaluate whether a readiness evidence bundle is review-ready."""

    _validate_required_gates(required_gate_ids)
    blockers: list[str] = []
    checks = 0

    def check(condition: bool, reason: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            blockers.append(reason)

    gate_counts: dict[str, int] = {}
    for entry in manifest.entries:
        gate_counts[entry.gate_id] = gate_counts.get(entry.gate_id, 0) + 1

        check(entry.reviewed, f"EVIDENCE_NOT_REVIEWED:{entry.gate_id}")
        check(entry.redacted, f"EVIDENCE_NOT_REDACTED:{entry.gate_id}")
        check(entry.immutable, f"EVIDENCE_NOT_IMMUTABLE:{entry.gate_id}")
        check(
            manifest.allow_synthetic_evidence or not entry.synthetic,
            f"SYNTHETIC_EVIDENCE_NOT_ALLOWED:{entry.gate_id}",
        )
        check(
            entry.expires_at_utc is None,
            f"EXPIRING_EVIDENCE_NOT_ALLOWED:{entry.gate_id}",
        )

    for gate_id in required_gate_ids:
        count = gate_counts.get(gate_id, 0)
        check(count > 0, f"REQUIRED_GATE_EVIDENCE_MISSING:{gate_id}")
        check(count <= 1, f"DUPLICATE_GATE_EVIDENCE:{gate_id}")

    for gate_id in sorted(gate_counts):
        check(gate_id in required_gate_ids, f"UNEXPECTED_GATE_EVIDENCE:{gate_id}")

    if manifest.expected_bundle_sha256 is not None:
        check(
            manifest.expected_bundle_sha256 == manifest.bundle_sha256,
            "BUNDLE_HASH_MISMATCH",
        )

    check(not manifest.paper_claim_requested, "PAPER_CLAIM_FORBIDDEN_IN_PR147")
    check(not manifest.live_claim_requested, "LIVE_CLAIM_FORBIDDEN_IN_PR147")

    unique_blockers = tuple(dict.fromkeys(blockers))
    ready = not unique_blockers
    present_gate_ids = tuple(sorted(gate_counts))
    return PR147EvidenceBundleDecision(
        schema_version=PR147_RESULT_SCHEMA_VERSION,
        state=PR147BundleState.REVIEW_READY if ready else PR147BundleState.BLOCKED,
        review_ready=ready,
        paper_claim_allowed=False,
        live_claim_allowed=False,
        blockers=unique_blockers,
        warnings=("PR147_REVIEW_ONLY_NO_RUNTIME_WIRING",),
        bundle_sha256=manifest.bundle_sha256,
        present_gate_ids=present_gate_ids,
        required_gate_ids=tuple(required_gate_ids),
        checks_evaluated=checks,
        metrics_summary={
            "entry_count": len(manifest.entries),
            "present_gate_count": len(present_gate_ids),
            "required_gate_count": len(required_gate_ids),
            "paper_claim_allowed": False,
            "live_claim_allowed": False,
            "state": PR147_READY_STATE if ready else PR147_BLOCKED_STATE,
        },
    )


def assert_pr147_evidence_bundle(
    manifest: PR147EvidenceBundleManifest,
    *,
    required_gate_ids: tuple[str, ...] = REQUIRED_BUNDLE_GATES,
) -> PR147EvidenceBundleDecision:
    decision = evaluate_pr147_evidence_bundle(
        manifest,
        required_gate_ids=required_gate_ids,
    )
    if not decision.review_ready:
        raise PR147BundleError(f"PR147_BLOCKED:{','.join(decision.blockers)}")
    return decision


def _validate_required_gates(gate_ids: tuple[str, ...]) -> None:
    if not gate_ids:
        raise PR147BundleError("required_gate_ids are required")
    seen: set[str] = set()
    for gate_id in gate_ids:
        _require_gate_id(gate_id, "required_gate_ids[]")
        if gate_id in seen:
            raise PR147BundleError("required_gate_ids must be unique")
        seen.add(gate_id)


def _require_nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise PR147BundleError(f"{name} is required")


def _require_repo(value: str) -> None:
    _require_nonempty(value, "repo_full_name")
    if value.count("/") != 1 or any(not part.strip() for part in value.split("/")):
        raise PR147BundleError("repo_full_name must be owner/name")


def _require_branch(value: str) -> None:
    _require_nonempty(value, "bundle_branch")
    if value.startswith("/") or ".." in value or " " in value:
        raise PR147BundleError("bundle_branch must be a safe git branch name")


def _require_gate_id(value: str, name: str) -> None:
    _require_nonempty(value, name)
    if not _GATE_RE.fullmatch(value):
        raise PR147BundleError(f"{name} must look like PR-000")


def _require_sha1(value: str, name: str) -> None:
    _require_nonempty(value, name)
    if not _SHA1_RE.fullmatch(value):
        raise PR147BundleError(f"{name} must be a full lowercase git SHA")


def _require_sha256(value: str, name: str) -> None:
    _require_nonempty(value, name)
    if not _SHA256_RE.fullmatch(value):
        raise PR147BundleError(f"{name} must be a SHA-256 digest")


def _require_positive_int(value: int, name: str) -> None:
    if not isinstance(value, int) or value <= 0:
        raise PR147BundleError(f"{name} must be a positive integer")


def _require_safe_artifact_path(path: str) -> None:
    _require_nonempty(path, "artifact_path")
    if path.startswith("/") or ".." in path or not _SAFE_PATH_RE.fullmatch(path):
        raise PR147BundleError("artifact_path must be a safe repository path")
    if not any(path.startswith(prefix) for prefix in _ALLOWED_ARTIFACT_PREFIXES):
        raise PR147BundleError("artifact_path must be under an evidence prefix")


def _hash_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in sorted(value.items())}
    return value
