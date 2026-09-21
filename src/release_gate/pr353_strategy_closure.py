"""PR-353 final strategy closure audit view.

This is an evidence/disposition layer only.  It consumes the existing canonical
NF ownership partition and release/capability authorities; it does not sign,
submit, allocate capital, contact providers, or promote live capability.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from src.release_gate.ultimate_mega1_closure import NF_TO_CLOSURE

SCHEMA = "pr353.final-strategy-closure.v1"
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")

WORK_PACKAGE_IDS = tuple(f"WP-{index}" for index in range(1, 9))
ALLOWED_WP_STATUSES = frozenset(
    {
        "IMPLEMENTED_CURRENT_HEAD",
        "SATISFIED_BY_EXISTING",
        "BLOCKED_EXTERNAL",
        "BLOCKED_INSUFFICIENT_DATA",
        "CODE_READY_EFFECT_NOT_AUTHORIZED",
        "NO_GO_BLOCKED_EXTERNAL",
    }
)
ALLOWED_STRATEGY_DISPOSITIONS = frozenset(
    {
        "QUALIFIED",
        "RESEARCH_CLOSED_POSITIVE",
        "RESEARCH_CLOSED_NEGATIVE",
        "BLOCKED_EXTERNAL",
        "DEFERRED",
        "OBSOLETE",
    }
)

EXPECTED_STRATEGY_IDS = (
    *(f"SOL-{index:02d}" for index in range(1, 30)),
    *(f"AI-{index:02d}" for index in range(1, 17)),
    *(f"EVM-{index:02d}" for index in range(1, 13)),
    *(f"SUI-{index:02d}" for index in range(1, 4)),
    *(f"INV-{index:02d}" for index in range(1, 7)),
    *(f"XCHAIN-{index:02d}" for index in range(1, 3)),
    "RWA-01",
    "PROD-01",
    "PROD-02",
    "FRONT-01",
    "FRONT-02",
)

RETIRED_PLANNING_ALIASES = tuple(range(354, 361))


class PR353ClosureError(ValueError):
    """Malformed or unsafe PR-353 closure evidence."""


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PR353ClosureError(f"{field}_REQUIRED")
    return value.strip()


def _texts(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise PR353ClosureError(f"{field}_LIST_REQUIRED")
    result = tuple(_text(item, field) for item in value)
    if len(set(result)) != len(result):
        raise PR353ClosureError(f"{field}_DUPLICATE")
    return result


@dataclass(frozen=True, slots=True)
class WorkPackageDisposition:
    wp_id: str
    status: str
    canonical_owner: str
    evidence_refs: tuple[str, ...]
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.wp_id not in WORK_PACKAGE_IDS:
            raise PR353ClosureError("UNKNOWN_WORK_PACKAGE")
        if self.status not in ALLOWED_WP_STATUSES:
            raise PR353ClosureError("INVALID_WORK_PACKAGE_STATUS")
        if not self.canonical_owner:
            raise PR353ClosureError("WORK_PACKAGE_OWNER_REQUIRED")
        if not self.evidence_refs:
            raise PR353ClosureError("WORK_PACKAGE_EVIDENCE_REQUIRED")
        if self.status in {
            "BLOCKED_EXTERNAL",
            "BLOCKED_INSUFFICIENT_DATA",
            "CODE_READY_EFFECT_NOT_AUTHORIZED",
            "NO_GO_BLOCKED_EXTERNAL",
        } and not self.blockers:
            raise PR353ClosureError("BLOCKED_WORK_PACKAGE_REQUIRES_BLOCKER")


@dataclass(frozen=True, slots=True)
class StrategyDisposition:
    strategy_id: str
    disposition: str
    evidence_refs: tuple[str, ...]
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.strategy_id not in EXPECTED_STRATEGY_IDS:
            raise PR353ClosureError("UNKNOWN_STRATEGY_ID")
        if self.disposition not in ALLOWED_STRATEGY_DISPOSITIONS:
            raise PR353ClosureError("INVALID_STRATEGY_DISPOSITION")
        if not self.evidence_refs:
            raise PR353ClosureError("STRATEGY_EVIDENCE_REQUIRED")
        if self.disposition in {"BLOCKED_EXTERNAL", "DEFERRED"} and not self.blockers:
            raise PR353ClosureError("BLOCKED_STRATEGY_REQUIRES_BLOCKER")


@dataclass(frozen=True, slots=True)
class PR353Audit:
    observed_main: str
    nf_owner_count: int
    work_package_count: int
    strategy_count: int
    blockers: tuple[str, ...]
    final_verdict: str
    production_ready: bool
    live_enabled: bool
    signer_access: bool
    submission_access: bool
    network_mutation: bool
    automatic_capital_increase: bool

    @property
    def structurally_complete(self) -> bool:
        return (
            self.nf_owner_count == 1016
            and self.work_package_count == 8
            and self.strategy_count == len(EXPECTED_STRATEGY_IDS)
        )


def _parse_work_packages(raw: object) -> tuple[WorkPackageDisposition, ...]:
    if not isinstance(raw, list):
        raise PR353ClosureError("WORK_PACKAGES_LIST_REQUIRED")
    rows: list[WorkPackageDisposition] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise PR353ClosureError("WORK_PACKAGE_OBJECT_REQUIRED")
        rows.append(
            WorkPackageDisposition(
                wp_id=_text(item.get("wp_id"), "wp_id"),
                status=_text(item.get("status"), "status"),
                canonical_owner=_text(item.get("canonical_owner"), "canonical_owner"),
                evidence_refs=_texts(item.get("evidence_refs", ()), "evidence_refs"),
                blockers=_texts(item.get("blockers", ()), "blockers"),
            )
        )
    ids = tuple(row.wp_id for row in rows)
    if len(set(ids)) != len(ids):
        raise PR353ClosureError("DUPLICATE_WORK_PACKAGE")
    if tuple(sorted(ids)) != WORK_PACKAGE_IDS:
        raise PR353ClosureError("WORK_PACKAGE_SET_MISMATCH")
    return tuple(rows)


def _parse_strategies(raw: object) -> tuple[StrategyDisposition, ...]:
    if not isinstance(raw, list):
        raise PR353ClosureError("STRATEGIES_LIST_REQUIRED")
    rows: list[StrategyDisposition] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise PR353ClosureError("STRATEGY_OBJECT_REQUIRED")
        rows.append(
            StrategyDisposition(
                strategy_id=_text(item.get("strategy_id"), "strategy_id"),
                disposition=_text(item.get("disposition"), "disposition"),
                evidence_refs=_texts(item.get("evidence_refs", ()), "evidence_refs"),
                blockers=_texts(item.get("blockers", ()), "blockers"),
            )
        )
    ids = tuple(row.strategy_id for row in rows)
    if len(set(ids)) != len(ids):
        raise PR353ClosureError("DUPLICATE_STRATEGY")
    if tuple(sorted(ids)) != tuple(sorted(EXPECTED_STRATEGY_IDS)):
        raise PR353ClosureError("STRATEGY_SET_MISMATCH")
    return tuple(rows)


def audit_pr353_manifest(payload: Mapping[str, Any]) -> PR353Audit:
    if payload.get("schema") != SCHEMA:
        raise PR353ClosureError("SCHEMA_MISMATCH")

    observed_main = _text(payload.get("observed_main"), "observed_main")
    if not _GIT_SHA.fullmatch(observed_main):
        raise PR353ClosureError("OBSERVED_MAIN_INVALID")

    aliases = payload.get("retired_planning_aliases")
    if aliases != list(RETIRED_PLANNING_ALIASES):
        raise PR353ClosureError("RETIRED_ALIAS_SET_MISMATCH")
    if payload.get("single_roadmap_pr") is not True:
        raise PR353ClosureError("SINGLE_PR_BOUNDARY_REQUIRED")

    if tuple(sorted(NF_TO_CLOSURE)) != tuple(range(1, 1017)):
        raise PR353ClosureError("NF_OWNER_PARTITION_INVALID")

    work_packages = _parse_work_packages(payload.get("work_packages"))
    by_wp = {row.wp_id: row for row in work_packages}
    if by_wp["WP-2"].status != "SATISFIED_BY_EXISTING":
        raise PR353ClosureError("WP2_MUST_REUSE_MERGED_CODE")
    wp2_evidence = " ".join(by_wp["WP-2"].evidence_refs)
    if "#530" not in wp2_evidence or "MEGA8-08" not in wp2_evidence:
        raise PR353ClosureError("WP2_MERGED_EVIDENCE_INCOMPLETE")
    if by_wp["WP-6"].status != "CODE_READY_EFFECT_NOT_AUTHORIZED":
        raise PR353ClosureError("WP6_EFFECT_BOUNDARY_MISMATCH")

    strategies = _parse_strategies(payload.get("strategy_dispositions"))

    final_verdict = _text(payload.get("final_verdict"), "final_verdict")
    if final_verdict != "NO_GO":
        raise PR353ClosureError("UNSUPPORTED_FINAL_VERDICT")
    blockers = _texts(payload.get("final_blockers", ()), "final_blockers")
    if not blockers:
        raise PR353ClosureError("NO_GO_REQUIRES_BLOCKERS")

    safety = payload.get("safety")
    if not isinstance(safety, Mapping):
        raise PR353ClosureError("SAFETY_OBJECT_REQUIRED")
    safety_fields = (
        "production_ready",
        "live_enabled",
        "signer_access",
        "submission_access",
        "network_mutation",
        "automatic_capital_increase",
    )
    for field in safety_fields:
        if safety.get(field) is not False:
            raise PR353ClosureError(f"UNSAFE_FLAG:{field}")

    return PR353Audit(
        observed_main=observed_main,
        nf_owner_count=len(NF_TO_CLOSURE),
        work_package_count=len(work_packages),
        strategy_count=len(strategies),
        blockers=blockers,
        final_verdict=final_verdict,
        production_ready=False,
        live_enabled=False,
        signer_access=False,
        submission_access=False,
        network_mutation=False,
        automatic_capital_increase=False,
    )


__all__ = [
    "ALLOWED_STRATEGY_DISPOSITIONS",
    "ALLOWED_WP_STATUSES",
    "EXPECTED_STRATEGY_IDS",
    "PR353Audit",
    "PR353ClosureError",
    "RETIRED_PLANNING_ALIASES",
    "SCHEMA",
    "StrategyDisposition",
    "WORK_PACKAGE_IDS",
    "WorkPackageDisposition",
    "audit_pr353_manifest",
]
