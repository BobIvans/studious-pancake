"""PR-078 actual security, SBOM and chaos evidence gate.

The PR-062 gate defined the shape of the security/chaos release evidence.  This
module adds the next fail-closed layer: every required record must be backed by
an on-disk artifact with a real digest and by a PR-062 operational-drill suite
that still evaluates to safe-idle.  The evaluator is intentionally offline and
never imports signer, RPC, Jito or live submission code.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable

from .operational_drills import (
    OperationalDrillSuite,
    OperationalReadinessGate,
    OperationalReadinessResult,
)

SCHEMA_VERSION = "pr078.actual-security-sbom-chaos-evidence.v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_IDLE_STATES = frozenset(
    {
        "blocked_manual_review",
        "manual_review_required",
        "rollback_complete",
        "safe_idle",
        "shadow_idle",
        "paper_shadow_idle",
    }
)
_DISALLOWED_ARTIFACT_SOURCES = frozenset(
    {
        "placeholder",
        "synthetic",
        "test-fixture",
        "unit-test",
    }
)


class ActualEvidenceKind(StrEnum):
    """Required PR-078 real evidence artifacts."""

    ISOLATED_SIGNER_BOUNDARY = "isolated-signer-boundary"
    INLINE_PRIVATE_KEY_REJECTION = "inline-private-key-rejection"
    CYCLONEDX_SBOM = "cyclonedx-sbom"
    SPDX_SBOM = "spdx-sbom"
    DEPENDENCY_VULNERABILITY_SCAN = "dependency-vulnerability-scan"
    SIGNED_ARTIFACT_PROVENANCE = "signed-artifact-provenance"
    LICENSE_INVENTORY = "license-inventory"
    SECRET_SCAN = "secret-scan"
    PROVIDER_429_5XX_SCHEMA_DRIFT = "provider-429-5xx-schema-drift"
    RPC_LAG_FORK_DROP = "rpc-lag-fork-drop"
    BLOCKHASH_ALT_EXPIRY = "blockhash-alt-expiry"
    QUEUE_SATURATION = "queue-saturation"
    JOURNAL_LOCK_CORRUPTION = "journal-lock-corruption"
    AMBIGUOUS_RPC_JITO_ACK = "ambiguous-rpc-jito-ack"
    BOUNDED_RETRIES_TASKS_QUEUES = "bounded-retries-tasks-queues"
    RECOVERY_TIME_SLO = "recovery-time-slo"
    RESTORE_CORRUPTION_DRILL = "restore-corruption-drill"


REQUIRED_ACTUAL_EVIDENCE_KINDS: frozenset[ActualEvidenceKind] = frozenset(
    ActualEvidenceKind
)
_REVIEW_REQUIRED_KINDS = frozenset(
    {
        ActualEvidenceKind.JOURNAL_LOCK_CORRUPTION,
        ActualEvidenceKind.RESTORE_CORRUPTION_DRILL,
        ActualEvidenceKind.RECOVERY_TIME_SLO,
    }
)
_SECURITY_POLICY_KINDS = frozenset(
    {
        ActualEvidenceKind.INLINE_PRIVATE_KEY_REJECTION,
        ActualEvidenceKind.DEPENDENCY_VULNERABILITY_SCAN,
        ActualEvidenceKind.SECRET_SCAN,
    }
)


@dataclass(frozen=True, slots=True)
class ActualEvidenceArtifact:
    """One real build/test/drill artifact with a pinned file digest."""

    kind: ActualEvidenceKind
    path: str
    sha256: str
    generated_at: datetime
    source: str
    policy_enforced: bool = True
    reviewed: bool = False
    reviewer: str | None = None
    critical_findings: int = 0
    placeholder: bool = False
    notes: str = ""


@dataclass(frozen=True, slots=True)
class ActualEvidencePackage:
    """Complete PR-078 package consumed by the PR-062 operational gate."""

    package_id: str
    generated_at: datetime
    artifacts: tuple[ActualEvidenceArtifact, ...]
    drill_suite: OperationalDrillSuite
    notes: str = ""

    @property
    def package_hash(self) -> str:
        return _sha256_json(asdict(self))


@dataclass(frozen=True, slots=True)
class ActualEvidenceGateResult:
    """Fail-closed PR-078 admission result."""

    schema_version: str
    package_id: str
    accepted: bool
    state: str
    package_hash: str
    pr062_result: OperationalReadinessResult
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    checks_evaluated: int

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["pr062_result"] = self.pr062_result.to_dict()
        return payload


class ActualEvidenceGate:
    """Validate real PR-078 evidence without enabling production/live code."""

    def __init__(
        self,
        *,
        repo_root: str | Path,
        required_kinds: Iterable[ActualEvidenceKind] = REQUIRED_ACTUAL_EVIDENCE_KINDS,
        evaluated_at: datetime | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.required_kinds = frozenset(required_kinds)
        self.evaluated_at = evaluated_at or datetime.now(timezone.utc)
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        if not self.required_kinds:
            raise ValueError("at least one actual evidence kind is required")

    def evaluate(self, package: ActualEvidencePackage) -> ActualEvidenceGateResult:
        blockers: list[str] = []
        warnings: list[str] = []
        checks = 0

        def check(condition: bool, blocker: str) -> None:
            nonlocal checks
            checks += 1
            if not condition:
                blockers.append(blocker)

        check(bool(package.package_id.strip()), "PACKAGE_ID_MISSING")
        check(
            _timezone_aware(package.generated_at),
            "PACKAGE_TIMESTAMP_NOT_TIMEZONE_AWARE",
        )
        self._check_artifacts(package.artifacts, check, warnings)

        pr062_result = OperationalReadinessGate(
            evaluated_at=self.evaluated_at
        ).evaluate(package.drill_suite)
        checks += pr062_result.checks_evaluated
        for blocker in pr062_result.blockers:
            blockers.append(f"PR062_GATE_BLOCKED:{blocker}")
        for warning in pr062_result.warnings:
            warnings.append(f"PR062_GATE_WARNING:{warning}")

        check(
            pr062_result.ready_for_limited_live,
            "PR062_OPERATIONAL_GATE_NOT_READY",
        )
        check(
            package.drill_suite.no_live_submission,
            "LIVE_SUBMISSION_OCCURRED_DURING_PR078_EVIDENCE",
        )
        for scenario in package.drill_suite.scenarios:
            prefix = scenario.area.value
            expected_state = scenario.expected_safe_state.strip().lower()
            check(
                expected_state in _SAFE_IDLE_STATES,
                f"SCENARIO_DID_NOT_END_SAFE_IDLE:{prefix}",
            )
            check(
                not scenario.automatic_resubmission_attempted,
                f"DUPLICATE_SUBMISSION_RISK:{prefix}",
            )
            check(
                scenario.residual_task_count == 0,
                f"RESIDUAL_TASKS_AFTER_PR078_DRILL:{prefix}",
            )

        unique_blockers = tuple(dict.fromkeys(blockers))
        return ActualEvidenceGateResult(
            schema_version="pr078.actual-evidence-result.v1",
            package_id=package.package_id,
            accepted=not unique_blockers,
            state="accepted" if not unique_blockers else "blocked",
            package_hash=package.package_hash,
            pr062_result=pr062_result,
            blockers=unique_blockers,
            warnings=tuple(dict.fromkeys(warnings)),
            checks_evaluated=checks,
        )

    def _check_artifacts(
        self,
        artifacts: tuple[ActualEvidenceArtifact, ...],
        check,
        warnings: list[str],
    ) -> None:
        by_kind: dict[ActualEvidenceKind, ActualEvidenceArtifact] = {}
        duplicate_kinds: set[ActualEvidenceKind] = set()
        for artifact in artifacts:
            if artifact.kind in by_kind:
                duplicate_kinds.add(artifact.kind)
            by_kind[artifact.kind] = artifact

        missing = self.required_kinds - set(by_kind)
        check(not missing, "REQUIRED_ACTUAL_ARTIFACTS_MISSING")
        for kind in sorted(missing, key=lambda item: item.value):
            check(False, f"ACTUAL_ARTIFACT_MISSING:{kind.value}")
        for kind in sorted(duplicate_kinds, key=lambda item: item.value):
            check(False, f"DUPLICATE_ACTUAL_ARTIFACT:{kind.value}")

        for artifact in artifacts:
            self._check_one_artifact(artifact, check, warnings)

    def _check_one_artifact(
        self,
        artifact: ActualEvidenceArtifact,
        check,
        warnings: list[str],
    ) -> None:
        prefix = artifact.kind.value
        check(
            _timezone_aware(artifact.generated_at),
            f"ARTIFACT_TIMESTAMP_INVALID:{prefix}",
        )
        check(_valid_sha256(artifact.sha256), f"ARTIFACT_DIGEST_INVALID:{prefix}")
        check(not artifact.placeholder, f"PLACEHOLDER_ARTIFACT_REJECTED:{prefix}")
        source = artifact.source.strip().lower()
        check(bool(source), f"ARTIFACT_SOURCE_MISSING:{prefix}")
        check(
            source not in _DISALLOWED_ARTIFACT_SOURCES,
            f"SYNTHETIC_ARTIFACT_SOURCE_REJECTED:{prefix}",
        )
        if artifact.kind in _SECURITY_POLICY_KINDS:
            check(artifact.policy_enforced, f"SECURITY_POLICY_NOT_ENFORCED:{prefix}")
        if artifact.kind is ActualEvidenceKind.DEPENDENCY_VULNERABILITY_SCAN:
            check(
                artifact.critical_findings == 0,
                "CRITICAL_CVE_POLICY_NOT_ENFORCED",
            )
        if artifact.kind in _REVIEW_REQUIRED_KINDS:
            check(artifact.reviewed, f"ARTIFACT_NOT_REVIEWED:{prefix}")
            check(
                bool((artifact.reviewer or "").strip()),
                f"ARTIFACT_REVIEWER_MISSING:{prefix}",
            )
        if not self._artifact_hash_matches(artifact):
            check(False, f"ARTIFACT_FILE_MISSING_OR_HASH_MISMATCH:{prefix}")
        if artifact.notes.lower().find("placeholder") >= 0:
            warnings.append(f"ARTIFACT_NOTE_MENTIONS_PLACEHOLDER:{prefix}")

    def _artifact_hash_matches(self, artifact: ActualEvidenceArtifact) -> bool:
        relative = artifact.path.replace("\\", "/")
        parts = relative.split("/")
        if (
            not relative
            or relative.startswith(("/", "~"))
            or any(part in {"", ".", ".."} for part in parts)
        ):
            return False
        candidate = (self.repo_root / relative).resolve()
        try:
            candidate.relative_to(self.repo_root)
        except ValueError:
            return False
        if not candidate.is_file():
            return False
        observed = hashlib.sha256(candidate.read_bytes()).hexdigest()
        return observed == artifact.sha256


def _timezone_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _valid_sha256(value: str) -> bool:
    return bool(_SHA256_RE.fullmatch(value)) and value != "0" * 64


def _sha256_json(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "ActualEvidenceArtifact",
    "ActualEvidenceGate",
    "ActualEvidenceGateResult",
    "ActualEvidenceKind",
    "ActualEvidencePackage",
    "REQUIRED_ACTUAL_EVIDENCE_KINDS",
    "SCHEMA_VERSION",
]
