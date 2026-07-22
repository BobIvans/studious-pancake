from __future__ import annotations

import pytest

from src.paper_queue_pr145 import (
    PR145CiConclusion,
    PR145PullRequestState,
    PR145QueueError,
    PR145QueueEvidence,
    PR145QueuePolicy,
    PR145RequiredPullRequest,
    assert_pr145_parallel_pr_queue,
    evaluate_pr145_parallel_pr_queue,
)

MAIN = "a" * 40
HEAD = "b" * 40
HASH = "c" * 64


def _policy(**kwargs: object) -> PR145QueuePolicy:
    return PR145QueuePolicy(
        required_roadmap_prs=("PR-138", "PR-140", "PR-141", "PR-142"),
        **kwargs,
    )


def _pr(roadmap_pr: str, **kwargs: object) -> PR145RequiredPullRequest:
    data = {
        "roadmap_pr": roadmap_pr,
        "github_pr_number": 100 + int(roadmap_pr[-3:]),
        "title": f"{roadmap_pr} title",
        "state": PR145PullRequestState.CLOSED,
        "merged": True,
        "draft": False,
        "mergeable": True,
        "base_sha": MAIN,
        "head_sha": HEAD,
        "behind_by": 0,
        "ahead_by": 1,
        "changed_files": 3,
        "ci_conclusion": PR145CiConclusion.SUCCESS,
        "evidence_sha256": HASH,
        "unresolved_review_threads": 0,
    }
    data.update(kwargs)
    return PR145RequiredPullRequest(**data)


def _evidence(*prs: PR145RequiredPullRequest) -> PR145QueueEvidence:
    if not prs:
        prs = tuple(_pr(name) for name in _policy().required_roadmap_prs)
    return PR145QueueEvidence(
        current_main_sha=MAIN,
        observed_prs=tuple(prs),
        observed_at_utc="2026-07-22T16:45:00Z",
        queue_evidence_sha256=HASH,
    )


def test_pr145_complete_merged_queue_is_review_ready() -> None:
    result = assert_pr145_parallel_pr_queue(
        policy=_policy(),
        evidence=_evidence(),
    )

    assert result.review_ready is True
    assert result.state.value == "parallel-pr-merge-coordination-review-ready"
    assert result.paper_claim_allowed is False
    assert result.live_claim_allowed is False
    assert result.missing_roadmap_prs == ()
    assert result.open_roadmap_prs == ()
    assert result.metrics_summary["merged_pr_count"] == 4


def test_pr145_missing_required_pr_blocks() -> None:
    result = evaluate_pr145_parallel_pr_queue(
        policy=_policy(),
        evidence=_evidence(_pr("PR-138"), _pr("PR-140"), _pr("PR-142")),
    )

    assert result.review_ready is False
    assert "PR-141:MISSING_REQUIRED_PR" in result.blockers
    assert result.missing_roadmap_prs == ("PR-141",)


def test_pr145_open_pr_cannot_satisfy_readiness() -> None:
    result = evaluate_pr145_parallel_pr_queue(
        policy=_policy(),
        evidence=_evidence(
            _pr("PR-138"),
            _pr(
                "PR-140",
                state=PR145PullRequestState.OPEN,
                merged=False,
                mergeable=True,
            ),
            _pr("PR-141"),
            _pr("PR-142"),
        ),
    )

    assert result.review_ready is False
    assert "PR-140:PULL_REQUEST_STILL_OPEN" in result.blockers
    assert result.open_roadmap_prs == ("PR-140",)


def test_pr145_draft_pr_blocks_queue() -> None:
    result = evaluate_pr145_parallel_pr_queue(
        policy=_policy(),
        evidence=_evidence(
            _pr("PR-138"),
            _pr(
                "PR-140",
                state=PR145PullRequestState.OPEN,
                merged=False,
                draft=True,
            ),
            _pr("PR-141"),
            _pr("PR-142"),
        ),
    )

    assert result.review_ready is False
    assert "PR-140:PULL_REQUEST_IS_DRAFT" in result.blockers


def test_pr145_not_mergeable_open_pr_blocks() -> None:
    result = evaluate_pr145_parallel_pr_queue(
        policy=_policy(),
        evidence=_evidence(
            _pr("PR-138"),
            _pr(
                "PR-140",
                state=PR145PullRequestState.OPEN,
                merged=False,
                mergeable=False,
            ),
            _pr("PR-141"),
            _pr("PR-142"),
        ),
    )

    assert result.review_ready is False
    assert "PR-140:NOT_MERGEABLE" in result.blockers


def test_pr145_branch_behind_main_blocks() -> None:
    result = evaluate_pr145_parallel_pr_queue(
        policy=_policy(),
        evidence=_evidence(
            _pr("PR-138"),
            _pr("PR-140", behind_by=2),
            _pr("PR-141"),
            _pr("PR-142"),
        ),
    )

    assert result.review_ready is False
    assert "PR-140:BRANCH_BEHIND_MAIN" in result.blockers


def test_pr145_ci_success_and_review_threads_are_required() -> None:
    result = evaluate_pr145_parallel_pr_queue(
        policy=_policy(),
        evidence=_evidence(
            _pr("PR-138"),
            _pr(
                "PR-140",
                ci_conclusion=PR145CiConclusion.FAILURE,
                unresolved_review_threads=1,
            ),
            _pr("PR-141"),
            _pr("PR-142"),
        ),
    )

    assert result.review_ready is False
    assert "PR-140:CI_NOT_SUCCESS" in result.blockers
    assert "PR-140:UNRESOLVED_REVIEW_THREADS" in result.blockers


def test_pr145_release_claims_are_always_blocked_in_review_gate() -> None:
    result = evaluate_pr145_parallel_pr_queue(
        policy=_policy(paper_claim_requested=True, live_claim_requested=True),
        evidence=_evidence(),
    )

    assert result.review_ready is False
    assert "PAPER_CLAIM_BLOCKED_UNTIL_QUEUE_MERGED_AND_REVIEWED" in result.blockers
    assert "LIVE_CLAIM_BLOCKED_UNTIL_SOAK_AND_RELEASE_GATES" in result.blockers
    assert result.paper_claim_allowed is False
    assert result.live_claim_allowed is False


def test_pr145_closed_unmerged_pr_blocks() -> None:
    result = evaluate_pr145_parallel_pr_queue(
        policy=_policy(),
        evidence=_evidence(
            _pr("PR-138"),
            _pr("PR-140", merged=False),
            _pr("PR-141"),
            _pr("PR-142"),
        ),
    )

    assert result.review_ready is False
    assert "PR-140:PULL_REQUEST_CLOSED_UNMERGED" in result.blockers


def test_pr145_rejects_duplicate_and_missing_hash_evidence() -> None:
    with pytest.raises(PR145QueueError):
        PR145QueuePolicy(required_roadmap_prs=("PR-140", "PR-140"))

    with pytest.raises(PR145QueueError):
        _pr("PR-140", evidence_sha256="not-a-hash")
