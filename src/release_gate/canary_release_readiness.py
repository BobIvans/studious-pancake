"""PR-064 canary and release readiness aggregator.

This module is deliberately offline and fail-closed.  It does not arm a
controller, sign, submit, fund a wallet, mutate rollout state or consume a
sender permit.  It only combines already-produced PR-046 canary state, PR-047
release-gate state and the upstream PR-060..063 evidence required by the
2026-07-21 remediation roadmap.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Iterable, Mapping

from src.live_canary.models import CanaryMode, CanaryReport

from .gate import ReleaseGateResult

SCHEMA_VERSION = "pr064.canary-release-readiness.v1"
RESULT_SCHEMA_VERSION = "pr064.canary-release-readiness-result.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class UpstreamDependency(StrEnum):
    """Roadmap work that must be complete before PR-064 can pass."""

    PR060_SHADOW_SOAK = "pr060-real-shadow-soak"
    PR061_DATA_LIFECYCLE_OBSERVABILITY = "pr061-data-lifecycle-observability"
    PR062_SECURITY_CHAOS_OPS = "pr062-security-chaos-ops"
    PR063_SENDER_CONSOLIDATION = "pr063-sender-consolidation"


class ReadinessBlocker(StrEnum):
    """Machine-stable blockers for PR-064 readiness."""

    UPSTREAM_EVIDENCE_MISSING = "UPSTREAM_EVIDENCE_MISSING"
    UPSTREAM_EVIDENCE_NOT_PASSED = "UPSTREAM_EVIDENCE_NOT_PASSED"
    UPSTREAM_EVIDENCE_NOT_HUMAN_REVIEWED = "UPSTREAM_EVIDENCE_NOT_HUMAN_REVIEWED"
    CANARY_AI_AUTHORITY_PRESENT = "CANARY_AI_AUTHORITY_PRESENT"
    CANARY_NOT_LIMITED_LIVE = "CANARY_NOT_LIMITED_LIVE"
    CANARY_NOT_ARMED = "CANARY_NOT_ARMED"
    CANARY_ACTIVE_LATCH = "CANARY_ACTIVE_LATCH"
    CANARY_OUTSTANDING_SUBMISSION = "CANARY_OUTSTANDING_SUBMISSION"
    CANARY_EVIDENCE_HASH_MISSING = "CANARY_EVIDENCE_HASH_MISSING"
    RELEASE_GATE_NOT_READY = "RELEASE_GATE_NOT_READY"
    RELEASE_GATE_HAS_BLOCKERS = "RELEASE_GATE_HAS_BLOCKERS"
    RELEASE_MANIFEST_HASH_INVALID = "RELEASE_MANIFEST_HASH_INVALID"


def _stable_json(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    return value


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _require_real_sha256(value: str, field_name: str) -> str:
    lowered = value.lower()
    if not _SHA256_RE.fullmatch(lowered) or lowered == "0" * 64:
        raise ValueError(f"{field_name} must be a non-placeholder SHA-256 digest")
    return lowered


@dataclass(frozen=True, slots=True)
class UpstreamEvidenceRecord:
    """Human-reviewed completion evidence for one PR-060..063 dependency."""

    dependency: UpstreamDependency
    evidence_hash: str
    source_ref: str
    passed: bool
    human_reviewed: bool
    reviewer: str
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_hash",
            _require_real_sha256(self.evidence_hash, "evidence_hash"),
        )
        for field_name in ("source_ref", "reviewer"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} is required")
            object.__setattr__(self, field_name, value.strip())
        object.__setattr__(self, "notes", self.notes.strip())


@dataclass(frozen=True, slots=True)
class CanaryReleaseReadinessResult:
    schema_version: str
    ready: bool
    state: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    upstream_evidence_hash: str
    canary_report_hash: str
    release_manifest_hash: str
    release_id: str
    checks_evaluated: int
    ai_authority: bool = False
    live_mode_mutated: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class CanaryReleaseReadinessGate:
    """Final offline PR-064 readiness gate.

    The gate composes evidence that must already exist. It never calls network
    clients, never opens or closes latches and never changes live/canary mode.
    """

    required_dependencies: frozenset[UpstreamDependency] = frozenset(
        UpstreamDependency
    )

    def evaluate(
        self,
        *,
        canary_report: CanaryReport,
        release_result: ReleaseGateResult,
        upstream_evidence: Iterable[UpstreamEvidenceRecord],
    ) -> CanaryReleaseReadinessResult:
        blockers: list[str] = []
        warnings: list[str] = []
        checks = 0

        def check(condition: bool, reason: ReadinessBlocker) -> None:
            nonlocal checks
            checks += 1
            if not condition:
                blockers.append(reason.value)

        evidence_by_dependency = {item.dependency: item for item in upstream_evidence}
        check(
            set(evidence_by_dependency) == set(self.required_dependencies),
            ReadinessBlocker.UPSTREAM_EVIDENCE_MISSING,
        )
        for dependency in sorted(self.required_dependencies, key=str):
            item = evidence_by_dependency.get(dependency)
            if item is None:
                continue
            check(
                item.passed,
                ReadinessBlocker.UPSTREAM_EVIDENCE_NOT_PASSED,
            )
            check(
                item.human_reviewed,
                ReadinessBlocker.UPSTREAM_EVIDENCE_NOT_HUMAN_REVIEWED,
            )

        check(
            not canary_report.ai_authority,
            ReadinessBlocker.CANARY_AI_AUTHORITY_PRESENT,
        )
        check(
            canary_report.mode is CanaryMode.LIMITED_LIVE,
            ReadinessBlocker.CANARY_NOT_LIMITED_LIVE,
        )
        check(canary_report.armed, ReadinessBlocker.CANARY_NOT_ARMED)
        check(not canary_report.active_latches, ReadinessBlocker.CANARY_ACTIVE_LATCH)
        check(
            canary_report.outstanding_attempt_id is None,
            ReadinessBlocker.CANARY_OUTSTANDING_SUBMISSION,
        )
        check(
            canary_report.evidence_hash is not None,
            ReadinessBlocker.CANARY_EVIDENCE_HASH_MISSING,
        )

        check(release_result.production_ready, ReadinessBlocker.RELEASE_GATE_NOT_READY)
        check(release_result.state == "production-ready", ReadinessBlocker.RELEASE_GATE_NOT_READY)
        check(not release_result.blockers, ReadinessBlocker.RELEASE_GATE_HAS_BLOCKERS)
        check(
            _SHA256_RE.fullmatch(release_result.manifest_sha256) is not None
            and release_result.manifest_sha256 != "0" * 64,
            ReadinessBlocker.RELEASE_MANIFEST_HASH_INVALID,
        )
        if release_result.warnings:
            warnings.extend(f"RELEASE_GATE_WARNING:{item}" for item in release_result.warnings)

        upstream_hash = sha256_json(
            tuple(sorted(evidence_by_dependency.values(), key=lambda item: item.dependency))
        )
        unique_blockers = tuple(dict.fromkeys(blockers))
        ready = not unique_blockers
        return CanaryReleaseReadinessResult(
            schema_version=RESULT_SCHEMA_VERSION,
            ready=ready,
            state="ready-for-human-controlled-canary-release" if ready else "blocked",
            blockers=unique_blockers,
            warnings=tuple(dict.fromkeys(warnings)),
            upstream_evidence_hash=upstream_hash,
            canary_report_hash=canary_report.report_hash,
            release_manifest_hash=release_result.manifest_sha256,
            release_id=release_result.release_id,
            checks_evaluated=checks,
            ai_authority=False,
            live_mode_mutated=False,
        )
