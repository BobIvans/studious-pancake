"""PR-062 security, SBOM, chaos and operational-drill release gate.

This module is deliberately evidence-only.  It evaluates offline drill artifacts
and never imports signer adapters, provider clients, RPC senders, Jito
submission, or live runtime controls.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import re
from typing import Iterable

from src.security.supply_chain import (
    DEFAULT_DEPENDENCY_AUDIT_POLICY,
    DependencyAuditPolicy,
    SupplyChainDecision,
    VulnerabilityRecord,
)

SCHEMA_VERSION = "pr062.security-chaos-operational-drills.v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SECRET_REFERENCE_PREFIXES = ("env:", "file:/", "keychain:")
_UNSAFE_TERMINAL_STATES = frozenset(
    {
        "accepted",
        "landed",
        "submitted",
        "success",
        "production-ready",
        "live",
    }
)


class OperationalFailureArea(StrEnum):
    """Failure classes that must be rehearsed before release promotion."""

    ISOLATED_SIGNER = "isolated-signer"
    SBOM_IMAGE_PROVENANCE = "sbom-image-provenance"
    SECRET_SCAN = "secret-scan"
    DEPENDENCY_AUDIT = "dependency-audit"
    PROVIDER_RATE_LIMIT = "provider-rate-limit"
    PROVIDER_SCHEMA_DRIFT = "provider-schema-drift"
    RPC_FORK_OR_GAP = "rpc-fork-or-gap"
    JITO_AMBIGUOUS_SUBMISSION = "jito-ambiguous-submission"
    JOURNAL_CORRUPTION = "journal-corruption"
    QUEUE_SATURATION = "queue-saturation"
    MEMORY_TASK_LEAK = "memory-task-leak"
    ROLLBACK_RTO = "rollback-rto"


DEFAULT_REQUIRED_FAILURE_AREAS: frozenset[OperationalFailureArea] = frozenset(
    OperationalFailureArea
)


@dataclass(frozen=True, slots=True)
class SecurityOperationalEvidence:
    """Security and supply-chain evidence consumed by the PR-062 gate."""

    generated_at: datetime
    secret_scan_passed: bool
    plaintext_key_findings: tuple[str, ...]
    dependency_decision: SupplyChainDecision
    sbom_sha256: str
    image_digest: str
    signer_policy_enforced: bool
    isolated_signer_reference: str
    release_manifest_sha256: str | None = None

    @classmethod
    def from_vulnerability_records(
        cls,
        *,
        generated_at: datetime,
        records: Iterable[VulnerabilityRecord],
        sbom_sha256: str,
        image_digest: str,
        isolated_signer_reference: str,
        secret_scan_passed: bool = True,
        plaintext_key_findings: tuple[str, ...] = (),
        signer_policy_enforced: bool = True,
        dependency_policy: DependencyAuditPolicy = DEFAULT_DEPENDENCY_AUDIT_POLICY,
        release_manifest_sha256: str | None = None,
    ) -> "SecurityOperationalEvidence":
        return cls(
            generated_at=generated_at,
            secret_scan_passed=secret_scan_passed,
            plaintext_key_findings=tuple(plaintext_key_findings),
            dependency_decision=dependency_policy.evaluate(records),
            sbom_sha256=sbom_sha256,
            image_digest=image_digest,
            signer_policy_enforced=signer_policy_enforced,
            isolated_signer_reference=isolated_signer_reference,
            release_manifest_sha256=release_manifest_sha256,
        )


@dataclass(frozen=True, slots=True)
class FailureInjectionScenario:
    """One replayable load/chaos/failure-injection result."""

    area: OperationalFailureArea
    scenario_id: str
    injected_failure: str
    expected_safe_state: str
    passed: bool
    safe_state_proven: bool
    evidence_sha256: str
    max_retry_attempts: int
    observed_retry_attempts: int
    max_queue_depth: int
    observed_queue_depth: int
    max_rto_seconds: int | None = None
    observed_rto_seconds: int | None = None
    automatic_resubmission_attempted: bool = False
    residual_task_count: int = 0
    notes: str = ""


@dataclass(frozen=True, slots=True)
class OperationalDrillSuite:
    """Complete PR-062 evidence bundle for security and operational drills."""

    suite_id: str
    run_started_at: datetime
    run_finished_at: datetime
    operator: str
    environment: str
    security: SecurityOperationalEvidence
    scenarios: tuple[FailureInjectionScenario, ...]
    manual_rollback_rehearsed: bool
    kill_switch_rehearsed: bool
    no_live_submission: bool = True
    notes: str = ""

    @property
    def suite_hash(self) -> str:
        return _sha256_json(asdict(self))


@dataclass(frozen=True, slots=True)
class OperationalReadinessResult:
    """Fail-closed PR-062 readiness decision."""

    schema_version: str
    suite_id: str
    ready_for_limited_live: bool
    state: str
    suite_hash: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    checks_evaluated: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class OperationalReadinessGate:
    """Evaluate PR-062 evidence without enabling live execution."""

    def __init__(
        self,
        *,
        required_areas: Iterable[OperationalFailureArea] = (
            DEFAULT_REQUIRED_FAILURE_AREAS
        ),
        evaluated_at: datetime | None = None,
    ) -> None:
        self.required_areas = frozenset(required_areas)
        self.evaluated_at = evaluated_at or datetime.now(timezone.utc)
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        if not self.required_areas:
            raise ValueError("at least one operational failure area is required")

    def evaluate(self, suite: OperationalDrillSuite) -> OperationalReadinessResult:
        blockers: list[str] = []
        warnings: list[str] = []
        checks = 0

        def check(condition: bool, blocker: str) -> None:
            nonlocal checks
            checks += 1
            if not condition:
                blockers.append(blocker)

        self._check_suite_envelope(suite, check)
        self._check_security_evidence(suite.security, check, warnings)
        self._check_scenarios(suite.scenarios, check)

        check(suite.manual_rollback_rehearsed, "MANUAL_ROLLBACK_REHEARSAL_MISSING")
        check(suite.kill_switch_rehearsed, "KILL_SWITCH_REHEARSAL_MISSING")
        check(suite.no_live_submission, "LIVE_SUBMISSION_OCCURRED_DURING_DRILL")

        unique_blockers = tuple(dict.fromkeys(blockers))
        return OperationalReadinessResult(
            schema_version="pr062.operational-readiness-result.v1",
            suite_id=suite.suite_id,
            ready_for_limited_live=not unique_blockers,
            state="ready-for-limited-live" if not unique_blockers else "blocked",
            suite_hash=suite.suite_hash,
            blockers=unique_blockers,
            warnings=tuple(dict.fromkeys(warnings)),
            checks_evaluated=checks,
        )

    def _check_suite_envelope(
        self,
        suite: OperationalDrillSuite,
        check,
    ) -> None:
        check(bool(suite.suite_id.strip()), "SUITE_ID_MISSING")
        check(bool(suite.operator.strip()), "OPERATOR_MISSING")
        check(bool(suite.environment.strip()), "ENVIRONMENT_MISSING")
        for label, value in (
            ("run_started_at", suite.run_started_at),
            ("run_finished_at", suite.run_finished_at),
            ("security.generated_at", suite.security.generated_at),
        ):
            check(_timezone_aware(value), f"TIMESTAMP_NOT_TIMEZONE_AWARE:{label}")
        check(
            suite.run_finished_at >= suite.run_started_at,
            "DRILL_FINISHED_BEFORE_START",
        )
        check(
            suite.security.generated_at <= suite.run_finished_at,
            "SECURITY_EVIDENCE_AFTER_DRILL_FINISH",
        )

    def _check_security_evidence(
        self,
        security: SecurityOperationalEvidence,
        check,
        warnings: list[str],
    ) -> None:
        check(security.secret_scan_passed, "SECRET_SCAN_NOT_PASSED")
        check(
            not security.plaintext_key_findings,
            "PLAINTEXT_KEY_FINDINGS_PRESENT",
        )
        check(security.dependency_decision.allowed, "DEPENDENCY_AUDIT_BLOCKED")
        for blocker in security.dependency_decision.blockers:
            warnings.append(f"DEPENDENCY_AUDIT_BLOCKER:{blocker}")
        check(_is_sha256(security.sbom_sha256), "SBOM_DIGEST_INVALID")
        check(_is_image_digest(security.image_digest), "IMAGE_DIGEST_INVALID")
        check(security.signer_policy_enforced, "SIGNER_POLICY_NOT_ENFORCED")
        check(
            security.isolated_signer_reference.startswith(_SECRET_REFERENCE_PREFIXES),
            "ISOLATED_SIGNER_REFERENCE_NOT_STRUCTURAL",
        )
        if security.release_manifest_sha256 is not None:
            check(
                _is_sha256(security.release_manifest_sha256),
                "RELEASE_MANIFEST_DIGEST_INVALID",
            )

    def _check_scenarios(
        self,
        scenarios: tuple[FailureInjectionScenario, ...],
        check,
    ) -> None:
        scenarios_by_area: dict[OperationalFailureArea, FailureInjectionScenario] = {}
        duplicate_areas: set[OperationalFailureArea] = set()
        for scenario in scenarios:
            if scenario.area in scenarios_by_area:
                duplicate_areas.add(scenario.area)
            scenarios_by_area[scenario.area] = scenario

        missing = self.required_areas - set(scenarios_by_area)
        check(not missing, "REQUIRED_FAILURE_SCENARIOS_MISSING")
        for area in sorted(missing, key=lambda item: item.value):
            check(False, f"SCENARIO_MISSING:{area.value}")
        for area in sorted(duplicate_areas, key=lambda item: item.value):
            check(False, f"DUPLICATE_SCENARIO_AREA:{area.value}")

        for scenario in scenarios:
            self._check_one_scenario(scenario, check)

    def _check_one_scenario(self, scenario: FailureInjectionScenario, check) -> None:
        prefix = scenario.area.value
        check(bool(scenario.scenario_id.strip()), f"SCENARIO_ID_MISSING:{prefix}")
        check(bool(scenario.injected_failure.strip()), f"INJECTION_MISSING:{prefix}")
        check(
            bool(scenario.expected_safe_state.strip()),
            f"SAFE_STATE_MISSING:{prefix}",
        )
        check(scenario.passed, f"SCENARIO_FAILED:{prefix}")
        check(scenario.safe_state_proven, f"SAFE_STATE_NOT_PROVEN:{prefix}")
        check(
            _is_sha256(scenario.evidence_sha256),
            f"SCENARIO_EVIDENCE_HASH_INVALID:{prefix}",
        )
        check(
            _non_negative(scenario.max_retry_attempts)
            and _non_negative(scenario.observed_retry_attempts)
            and scenario.observed_retry_attempts <= scenario.max_retry_attempts,
            f"RETRY_BOUND_EXCEEDED:{prefix}",
        )
        check(
            _non_negative(scenario.max_queue_depth)
            and _non_negative(scenario.observed_queue_depth)
            and scenario.observed_queue_depth <= scenario.max_queue_depth,
            f"QUEUE_BOUND_EXCEEDED:{prefix}",
        )
        check(
            not scenario.automatic_resubmission_attempted,
            f"AUTOMATIC_RESUBMISSION_ATTEMPTED:{prefix}",
        )
        check(scenario.residual_task_count == 0, f"RESIDUAL_TASKS_AFTER_DRILL:{prefix}")
        if (
            scenario.max_rto_seconds is not None
            or scenario.observed_rto_seconds is not None
        ):
            check(
                scenario.max_rto_seconds is not None
                and scenario.observed_rto_seconds is not None
                and _non_negative(scenario.max_rto_seconds)
                and _non_negative(scenario.observed_rto_seconds)
                and scenario.observed_rto_seconds <= scenario.max_rto_seconds,
                f"RTO_BOUND_EXCEEDED:{prefix}",
            )
        terminal = scenario.expected_safe_state.strip().lower()
        check(
            terminal not in _UNSAFE_TERMINAL_STATES,
            f"UNSAFE_EXPECTED_STATE:{prefix}",
        )


def _timezone_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _non_negative(value: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_sha256(value: str) -> bool:
    return bool(_SHA256_RE.fullmatch(value)) and value != "0" * 64


def _is_image_digest(value: str) -> bool:
    return bool(_IMAGE_DIGEST_RE.fullmatch(value)) and value != "sha256:" + "0" * 64


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
    "DEFAULT_REQUIRED_FAILURE_AREAS",
    "FailureInjectionScenario",
    "OperationalDrillSuite",
    "OperationalFailureArea",
    "OperationalReadinessGate",
    "OperationalReadinessResult",
    "SCHEMA_VERSION",
    "SecurityOperationalEvidence",
]
