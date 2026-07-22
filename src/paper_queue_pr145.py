"""PR-145 parallel pull-request merge coordination gate.

This module is an offline, fail-closed evidence boundary for coordinating many
parallel roadmap PRs. It does not call GitHub, mutate branches, submit
transactions, sign payloads, or enable paper/live runtime behavior.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any

PR145_SCHEMA_VERSION = "pr145.parallel-pr-merge-coordination.v1"
PR145_RESULT_SCHEMA_VERSION = "pr145.parallel-pr-merge-coordination-result.v1"
PR145_READY_STATE = "parallel-pr-merge-coordination-review-ready"
PR145_BLOCKED_STATE = "blocked"

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PR145QueueState(StrEnum):
    BLOCKED = PR145_BLOCKED_STATE
    REVIEW_READY = PR145_READY_STATE


class PR145QueueError(ValueError):
    """Raised when PR-145 queue evidence is malformed."""


class PR145PullRequestState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class PR145CiConclusion(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    PENDING = "pending"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class PR145RequiredPullRequest:
    """Observed state for one required roadmap pull request."""

    roadmap_pr: str
    github_pr_number: int
    title: str
    state: PR145PullRequestState
    merged: bool
    draft: bool
    mergeable: bool | None
    base_sha: str
    head_sha: str
    behind_by: int
    ahead_by: int
    changed_files: int
    ci_conclusion: PR145CiConclusion
    evidence_sha256: str
    unresolved_review_threads: int = 0

    def __post_init__(self) -> None:
        _require_roadmap_pr(self.roadmap_pr)
        if not isinstance(self.github_pr_number, int) or self.github_pr_number <= 0:
            raise PR145QueueError("github_pr_number must be a positive integer")
        _require_non_empty(self.title, "title")
        if not isinstance(self.state, PR145PullRequestState):
            raise PR145QueueError("state must be PR145PullRequestState")
        if type(self.merged) is not bool:
            raise PR145QueueError("merged must be boolean")
        if type(self.draft) is not bool:
            raise PR145QueueError("draft must be boolean")
        if self.mergeable is not None and type(self.mergeable) is not bool:
            raise PR145QueueError("mergeable must be boolean or None")
        _require_sha(self.base_sha, "base_sha")
        _require_sha(self.head_sha, "head_sha")
        for name in ("behind_by", "ahead_by", "changed_files"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise PR145QueueError(f"{name} must be a non-negative integer")
        if not isinstance(self.ci_conclusion, PR145CiConclusion):
            raise PR145QueueError("ci_conclusion must be PR145CiConclusion")
        _require_sha256(self.evidence_sha256, "evidence_sha256")
        if (
            not isinstance(self.unresolved_review_threads, int)
            or self.unresolved_review_threads < 0
        ):
            raise PR145QueueError(
                "unresolved_review_threads must be a non-negative integer"
            )

    @property
    def is_merged_green(self) -> bool:
        return (
            self.state == PR145PullRequestState.CLOSED
            and self.merged
            and not self.draft
            and self.behind_by == 0
            and self.ci_conclusion == PR145CiConclusion.SUCCESS
            and self.unresolved_review_threads == 0
        )

    def blockers(self, *, current_main_sha: str) -> tuple[str, ...]:
        """Return fail-closed queue blockers for this PR snapshot."""

        blockers: list[str] = []
        prefix = self.roadmap_pr

        if self.base_sha != current_main_sha and not self.merged:
            blockers.append(f"{prefix}:BASE_NOT_CURRENT_MAIN")
        if self.state == PR145PullRequestState.OPEN:
            blockers.append(f"{prefix}:PULL_REQUEST_STILL_OPEN")
        if self.state == PR145PullRequestState.CLOSED and not self.merged:
            blockers.append(f"{prefix}:PULL_REQUEST_CLOSED_UNMERGED")
        if self.draft:
            blockers.append(f"{prefix}:PULL_REQUEST_IS_DRAFT")
        if self.mergeable is False and not self.merged:
            blockers.append(f"{prefix}:NOT_MERGEABLE")
        if self.mergeable is None and not self.merged:
            blockers.append(f"{prefix}:MERGEABLE_UNKNOWN")
        if self.behind_by > 0:
            blockers.append(f"{prefix}:BRANCH_BEHIND_MAIN")
        if self.ahead_by == 0 and not self.merged:
            blockers.append(f"{prefix}:NO_REVIEWABLE_DIFF")
        if self.changed_files == 0 and not self.merged:
            blockers.append(f"{prefix}:NO_CHANGED_FILES")
        if self.ci_conclusion != PR145CiConclusion.SUCCESS:
            blockers.append(f"{prefix}:CI_NOT_SUCCESS")
        if self.unresolved_review_threads > 0:
            blockers.append(f"{prefix}:UNRESOLVED_REVIEW_THREADS")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class PR145QueuePolicy:
    """Roadmap PRs that must be coordinated before claiming readiness."""

    required_roadmap_prs: tuple[str, ...]
    allow_open_prs_for_review: bool = False
    live_claim_requested: bool = False
    paper_claim_requested: bool = False
    schema_version: str = PR145_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PR145_SCHEMA_VERSION:
            raise PR145QueueError("unsupported PR-145 policy schema")
        if not self.required_roadmap_prs:
            raise PR145QueueError("required_roadmap_prs is required")
        _reject_duplicate_roadmap_prs(self.required_roadmap_prs)
        for roadmap_pr in self.required_roadmap_prs:
            _require_roadmap_pr(roadmap_pr)
        if type(self.allow_open_prs_for_review) is not bool:
            raise PR145QueueError("allow_open_prs_for_review must be boolean")
        if type(self.live_claim_requested) is not bool:
            raise PR145QueueError("live_claim_requested must be boolean")
        if type(self.paper_claim_requested) is not bool:
            raise PR145QueueError("paper_claim_requested must be boolean")


@dataclass(frozen=True, slots=True)
class PR145QueueEvidence:
    """Point-in-time PR queue evidence collected outside this offline gate."""

    current_main_sha: str
    observed_prs: tuple[PR145RequiredPullRequest, ...]
    observed_at_utc: str
    queue_evidence_sha256: str
    schema_version: str = PR145_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PR145_SCHEMA_VERSION:
            raise PR145QueueError("unsupported PR-145 evidence schema")
        _require_sha(self.current_main_sha, "current_main_sha")
        if not self.observed_prs:
            raise PR145QueueError("observed_prs is required")
        _reject_duplicate_roadmap_prs(
            tuple(item.roadmap_pr for item in self.observed_prs)
        )
        _require_non_empty(self.observed_at_utc, "observed_at_utc")
        _require_sha256(self.queue_evidence_sha256, "queue_evidence_sha256")


@dataclass(frozen=True, slots=True)
class PR145QueueReadiness:
    schema_version: str
    state: PR145QueueState
    review_ready: bool
    paper_claim_allowed: bool
    live_claim_allowed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    missing_roadmap_prs: tuple[str, ...]
    merged_roadmap_prs: tuple[str, ...]
    open_roadmap_prs: tuple[str, ...]
    queue_hash: str
    checks_evaluated: int
    metrics_summary: dict[str, int | str | bool]

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def evaluate_pr145_parallel_pr_queue(
    *,
    policy: PR145QueuePolicy,
    evidence: PR145QueueEvidence,
) -> PR145QueueReadiness:
    """Evaluate whether the parallel roadmap PR queue can be trusted."""

    checks = 0
    blockers: list[str] = []
    warnings: list[str] = ["PR145_REVIEW_ONLY_RUNTIME_UNCHANGED"]

    observed = {item.roadmap_pr: item for item in evidence.observed_prs}

    for roadmap_pr in policy.required_roadmap_prs:
        checks += 1
        if roadmap_pr not in observed:
            blockers.append(f"{roadmap_pr}:MISSING_REQUIRED_PR")
            continue

        pull_request = observed[roadmap_pr]
        item_blockers = pull_request.blockers(
            current_main_sha=evidence.current_main_sha
        )
        checks += len(item_blockers)
        if item_blockers:
            blockers.extend(item_blockers)

    if policy.paper_claim_requested:
        checks += 1
        blockers.append("PAPER_CLAIM_BLOCKED_UNTIL_QUEUE_MERGED_AND_REVIEWED")
    if policy.live_claim_requested:
        checks += 1
        blockers.append("LIVE_CLAIM_BLOCKED_UNTIL_SOAK_AND_RELEASE_GATES")

    if policy.allow_open_prs_for_review:
        warnings.append("open PRs may be inspected but cannot satisfy readiness")

    queue_hash = _hash_json(
        {
            "schema_version": PR145_SCHEMA_VERSION,
            "policy": _jsonable(policy),
            "evidence": _jsonable(evidence),
        }
    )

    missing = tuple(
        roadmap_pr
        for roadmap_pr in policy.required_roadmap_prs
        if roadmap_pr not in observed
    )
    merged = tuple(
        sorted(
            item.roadmap_pr
            for item in evidence.observed_prs
            if item.state == PR145PullRequestState.CLOSED and item.merged
        )
    )
    open_items = tuple(
        sorted(
            item.roadmap_pr
            for item in evidence.observed_prs
            if item.state == PR145PullRequestState.OPEN
        )
    )

    unique_blockers = tuple(dict.fromkeys(blockers))
    ready = not unique_blockers
    return PR145QueueReadiness(
        schema_version=PR145_RESULT_SCHEMA_VERSION,
        state=PR145QueueState.REVIEW_READY if ready else PR145QueueState.BLOCKED,
        review_ready=ready,
        paper_claim_allowed=False,
        live_claim_allowed=False,
        blockers=unique_blockers,
        warnings=tuple(warnings),
        missing_roadmap_prs=missing,
        merged_roadmap_prs=merged,
        open_roadmap_prs=open_items,
        queue_hash=queue_hash,
        checks_evaluated=checks,
        metrics_summary={
            "required_pr_count": len(policy.required_roadmap_prs),
            "observed_pr_count": len(evidence.observed_prs),
            "missing_pr_count": len(missing),
            "merged_pr_count": len(merged),
            "open_pr_count": len(open_items),
            "paper_claim_allowed": False,
            "live_claim_allowed": False,
        },
    )


def assert_pr145_parallel_pr_queue(
    *,
    policy: PR145QueuePolicy,
    evidence: PR145QueueEvidence,
) -> PR145QueueReadiness:
    result = evaluate_pr145_parallel_pr_queue(policy=policy, evidence=evidence)
    if not result.review_ready:
        raise PR145QueueError(f"PR145_BLOCKED:{','.join(result.blockers)}")
    return result


def _reject_duplicate_roadmap_prs(roadmap_prs: tuple[str, ...]) -> None:
    if len(set(roadmap_prs)) != len(roadmap_prs):
        raise PR145QueueError("duplicate roadmap PR in queue evidence")


def _require_roadmap_pr(value: str) -> None:
    _require_non_empty(value, "roadmap_pr")
    if not re.fullmatch(r"PR-\d{3}", value):
        raise PR145QueueError("roadmap_pr must look like PR-000")


def _require_non_empty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise PR145QueueError(f"{name} is required")


def _require_sha(value: str, name: str) -> None:
    _require_non_empty(value, name)
    if not _SHA_RE.fullmatch(value):
        raise PR145QueueError(f"{name} must be a 40-character git SHA")


def _require_sha256(value: str, name: str) -> None:
    _require_non_empty(value, name)
    if not _SHA256_RE.fullmatch(value):
        raise PR145QueueError(f"{name} must be a SHA-256 digest")


def _hash_json(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


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
