"""Deterministic supply-chain audit policy for PR-043.

The policy consumes normalized vulnerability records. CI can feed it output from
pip-audit or another scanner after translating severities into this small schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


_SEVERITY_RANK = {
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
    Severity.UNKNOWN: 99,
}


@dataclass(frozen=True, slots=True)
class VulnerabilityRecord:
    package: str
    vulnerability_id: str
    severity: Severity | str
    fixed_versions: tuple[str, ...] = ()
    source: str = "manual"

    @property
    def normalized_severity(self) -> Severity:
        if isinstance(self.severity, Severity):
            return self.severity
        try:
            return Severity(str(self.severity).lower())
        except ValueError:
            return Severity.UNKNOWN


@dataclass(frozen=True, slots=True)
class SupplyChainDecision:
    allowed: bool
    reason: str
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DependencyAuditPolicy:
    """Critical-CVE gate used before production image promotion."""

    block_at_or_above: Severity = Severity.CRITICAL
    fail_unknown_severity: bool = True
    allowlist: frozenset[str] = frozenset()

    def evaluate(
        self,
        records: Iterable[VulnerabilityRecord],
    ) -> SupplyChainDecision:
        blockers: list[str] = []
        threshold = _SEVERITY_RANK[self.block_at_or_above]
        for record in records:
            if record.vulnerability_id in self.allowlist:
                continue
            severity = record.normalized_severity
            if severity is Severity.UNKNOWN and self.fail_unknown_severity:
                blockers.append(self._format_blocker(record, severity))
                continue
            if _SEVERITY_RANK[severity] >= threshold:
                blockers.append(self._format_blocker(record, severity))
        if blockers:
            return SupplyChainDecision(
                allowed=False,
                reason="dependency audit has blocking vulnerabilities",
                blockers=tuple(blockers),
            )
        return SupplyChainDecision(
            allowed=True,
            reason="dependency audit passed critical-CVE policy",
        )

    @staticmethod
    def _format_blocker(record: VulnerabilityRecord, severity: Severity) -> str:
        fixed = ",".join(record.fixed_versions) if record.fixed_versions else "none"
        return (
            f"{record.package}:{record.vulnerability_id}:"
            f"severity={severity.value}:fixed={fixed}:source={record.source}"
        )


DEFAULT_DEPENDENCY_AUDIT_POLICY = DependencyAuditPolicy()
