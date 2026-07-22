"""PR-141 paper readiness bridge gate.

Offline, side-effect-free gate that connects the newly inserted PR-128...140
blocker queue back to the real-paper PR-102...105 sequence.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

PR141_SCHEMA_VERSION = "pr141.paper-readiness-bridge.v1"
PR141_RESULT_SCHEMA_VERSION = "pr141.paper-readiness-bridge-result.v1"
PR141_READY_STATE = "paper-readiness-bridge-review-ready"
PR141_BLOCKED_STATE = "blocked"

CRITICAL_PATH_GROUPS: dict[str, tuple[str, ...]] = {
    "emergency": ("PR-112", "PR-120", "PR-123", "PR-126", "PR-133"),
    "canonical_external": ("PR-099", "PR-100", "PR-124", "PR-101"),
    "market_assets_state": (
        "PR-113",
        "PR-116",
        "PR-117",
        "PR-125",
        "PR-127",
        "PR-136",
    ),
    "transaction_economics": (
        "PR-114",
        "PR-115",
        "PR-118",
        "PR-119",
        "PR-128",
        "PR-129",
        "PR-131",
        "PR-137",
    ),
    "durability_operations": (
        "PR-121",
        "PR-122",
        "PR-132",
        "PR-135",
        "PR-139",
        "PR-140",
    ),
}
REAL_PAPER_SEQUENCE = ("PR-102", "PR-103", "PR-104", "PR-105")
LIVE_AFTER_SOAK_SEQUENCE = ("PR-106", "PR-130", "PR-138", "PR-134", "PR-107")
PAPER_SOAK_REQUIREMENTS = (
    "exact_paper_vertical",
    "cpi_call_graph",
    "observability_integrity",
    "data_lineage",
    "no_sender",
)
_COMPLETED = frozenset({"merged", "accepted"})
_VALID_STATUS = frozenset({"missing", "planned", "open", "draft", "blocked", "merged", "accepted"})
_PR_RE = re.compile(r"^PR-\d{3}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class PR141BridgeState(StrEnum):
    BLOCKED = PR141_BLOCKED_STATE
    REVIEW_READY = PR141_READY_STATE


class PR141BridgeError(ValueError):
    """Raised when PR-141 evidence is malformed."""


@dataclass(frozen=True, slots=True)
class PR141RoadmapItem:
    pr_id: str
    title: str
    status: str
    category: str
    evidence_sha256: str | None = None
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_pr_id(self.pr_id)
        _require_text(self.title, "title")
        _require_text(self.category, "category")
        if self.status not in _VALID_STATUS:
            raise PR141BridgeError(f"unsupported status: {self.status}")
        if self.evidence_sha256 is not None and not _HASH_RE.fullmatch(self.evidence_sha256):
            raise PR141BridgeError("evidence_sha256 must be a SHA-256 digest")
        for blocker in self.blockers:
            _require_text(blocker, "blocker")


@dataclass(frozen=True, slots=True)
class PR141PaperSoakScope:
    exact_paper_vertical: bool
    cpi_call_graph: bool
    observability_integrity: bool
    data_lineage: bool
    no_sender: bool
    live_sender_disabled: bool

    def __post_init__(self) -> None:
        for name in (
            "exact_paper_vertical",
            "cpi_call_graph",
            "observability_integrity",
            "data_lineage",
            "no_sender",
            "live_sender_disabled",
        ):
            if type(getattr(self, name)) is not bool:
                raise PR141BridgeError(f"{name} must be boolean")


@dataclass(frozen=True, slots=True)
class PR141BridgeEvidence:
    roadmap_items: tuple[PR141RoadmapItem, ...]
    paper_soak_scope: PR141PaperSoakScope
    real_paper_sequence: tuple[str, ...] = REAL_PAPER_SEQUENCE
    live_after_soak_sequence: tuple[str, ...] = LIVE_AFTER_SOAK_SEQUENCE
    schema_version: str = PR141_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PR141_SCHEMA_VERSION:
            raise PR141BridgeError("unsupported PR-141 schema")
        seen: set[str] = set()
        for item in self.roadmap_items:
            if item.pr_id in seen:
                raise PR141BridgeError(f"duplicate roadmap item: {item.pr_id}")
            seen.add(item.pr_id)
        if self.real_paper_sequence != REAL_PAPER_SEQUENCE:
            raise PR141BridgeError("real paper sequence was changed")
        if self.live_after_soak_sequence != LIVE_AFTER_SOAK_SEQUENCE:
            raise PR141BridgeError("live-after-soak sequence was changed")


@dataclass(frozen=True, slots=True)
class PR141BridgeReadiness:
    schema_version: str
    state: PR141BridgeState
    review_ready: bool
    real_paper_ready: bool
    live_canary_allowed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    missing_prs: tuple[str, ...]
    incomplete_prs: tuple[str, ...]
    checks_evaluated: int

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "state": self.state.value,
            "review_ready": self.review_ready,
            "real_paper_ready": self.real_paper_ready,
            "live_canary_allowed": self.live_canary_allowed,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "missing_prs": list(self.missing_prs),
            "incomplete_prs": list(self.incomplete_prs),
            "checks_evaluated": self.checks_evaluated,
        }


def evaluate_pr141_paper_readiness_bridge(
    evidence: PR141BridgeEvidence,
) -> PR141BridgeReadiness:
    """Fail closed unless every blocker PR is complete and soak scope is safe."""

    blockers: list[str] = []
    checks = 0
    by_id = {item.pr_id: item for item in evidence.roadmap_items}

    def check(condition: bool, reason: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            blockers.append(reason)

    required = _required_prs()
    missing = tuple(pr_id for pr_id in required if pr_id not in by_id)
    incomplete = tuple(
        pr_id
        for pr_id in required
        if pr_id in by_id and by_id[pr_id].status not in _COMPLETED
    )
    check(not missing, "CRITICAL_PATH_PR_MISSING")
    check(not incomplete, "CRITICAL_PATH_PR_INCOMPLETE")

    for group, pr_ids in CRITICAL_PATH_GROUPS.items():
        for pr_id in pr_ids:
            item = by_id.get(pr_id)
            if item is None:
                continue
            check(item.category == group, f"PR_GROUP_MISMATCH:{pr_id}")
            check(not item.blockers, f"PR_HAS_UNRESOLVED_BLOCKERS:{pr_id}")
            if item.status in _COMPLETED:
                check(
                    item.evidence_sha256 is not None,
                    f"PR_COMPLETION_EVIDENCE_MISSING:{pr_id}",
                )

    scope = evidence.paper_soak_scope
    for requirement in PAPER_SOAK_REQUIREMENTS:
        check(
            getattr(scope, requirement) is True,
            f"PAPER_SOAK_SCOPE_MISSING:{requirement.upper()}",
        )
    check(scope.live_sender_disabled, "PAPER_SOAK_MUST_KEEP_SENDER_DISABLED")

    for pr_id in evidence.live_after_soak_sequence:
        item = by_id.get(pr_id)
        if item is not None and item.status in _COMPLETED:
            pr105 = by_id.get("PR-105")
            check(
                pr105 is not None and pr105.status in _COMPLETED,
                f"LIVE_SEQUENCE_STARTED_BEFORE_SOAK:{pr_id}",
            )

    unique = tuple(dict.fromkeys(blockers))
    ready = not unique
    return PR141BridgeReadiness(
        schema_version=PR141_RESULT_SCHEMA_VERSION,
        state=PR141BridgeState.REVIEW_READY if ready else PR141BridgeState.BLOCKED,
        review_ready=ready,
        real_paper_ready=ready,
        live_canary_allowed=False,
        blockers=unique,
        warnings=("PR141_REVIEW_ONLY_RUNTIME_UNCHANGED",),
        missing_prs=missing,
        incomplete_prs=incomplete,
        checks_evaluated=checks,
    )


def assert_pr141_paper_readiness_bridge(
    evidence: PR141BridgeEvidence,
) -> PR141BridgeReadiness:
    result = evaluate_pr141_paper_readiness_bridge(evidence)
    if not result.review_ready:
        raise PR141BridgeError(f"PR141_BLOCKED:{','.join(result.blockers)}")
    return result


def _required_prs() -> tuple[str, ...]:
    return tuple(pr_id for group in CRITICAL_PATH_GROUPS.values() for pr_id in group)


def _require_pr_id(value: str) -> None:
    if not isinstance(value, str) or not _PR_RE.fullmatch(value):
        raise PR141BridgeError("pr_id must look like PR-000")


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise PR141BridgeError(f"{name} is required")
