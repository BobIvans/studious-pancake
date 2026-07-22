from __future__ import annotations

import pytest

from src.paper_readiness_pr141 import (
    CRITICAL_PATH_GROUPS,
    PR141BridgeError,
    PR141BridgeEvidence,
    PR141PaperSoakScope,
    PR141RoadmapItem,
    assert_pr141_paper_readiness_bridge,
    evaluate_pr141_paper_readiness_bridge,
)

HASH = "a" * 64


def _scope(**overrides: bool) -> PR141PaperSoakScope:
    values = {
        "exact_paper_vertical": True,
        "cpi_call_graph": True,
        "observability_integrity": True,
        "data_lineage": True,
        "no_sender": True,
        "live_sender_disabled": True,
    }
    values.update(overrides)
    return PR141PaperSoakScope(**values)


def _items(*, status: str = "merged") -> tuple[PR141RoadmapItem, ...]:
    items: list[PR141RoadmapItem] = []
    for category, pr_ids in CRITICAL_PATH_GROUPS.items():
        for pr_id in pr_ids:
            items.append(
                PR141RoadmapItem(
                    pr_id=pr_id,
                    title=f"{pr_id} {category}",
                    status=status,
                    category=category,
                    evidence_sha256=HASH if status in {"merged", "accepted"} else None,
                )
            )
    return tuple(items)


def _evidence(
    *,
    items: tuple[PR141RoadmapItem, ...] | None = None,
    scope: PR141PaperSoakScope | None = None,
) -> PR141BridgeEvidence:
    return PR141BridgeEvidence(
        roadmap_items=_items() if items is None else items,
        paper_soak_scope=_scope() if scope is None else scope,
    )


def test_pr141_complete_bridge_is_review_ready_but_not_live() -> None:
    result = assert_pr141_paper_readiness_bridge(_evidence())

    assert result.review_ready is True
    assert result.real_paper_ready is True
    assert result.live_canary_allowed is False
    assert result.blockers == ()
    assert result.state.value == "paper-readiness-bridge-review-ready"


def test_pr141_missing_critical_path_pr_blocks() -> None:
    items = tuple(item for item in _items() if item.pr_id != "PR-136")
    result = evaluate_pr141_paper_readiness_bridge(_evidence(items=items))

    assert result.review_ready is False
    assert "CRITICAL_PATH_PR_MISSING" in result.blockers
    assert result.missing_prs == ("PR-136",)


def test_pr141_incomplete_critical_path_pr_blocks() -> None:
    items = tuple(
        PR141RoadmapItem(
            pr_id=item.pr_id,
            title=item.title,
            status="open" if item.pr_id == "PR-140" else item.status,
            category=item.category,
            evidence_sha256=None if item.pr_id == "PR-140" else item.evidence_sha256,
        )
        for item in _items()
    )
    result = evaluate_pr141_paper_readiness_bridge(_evidence(items=items))

    assert result.review_ready is False
    assert "CRITICAL_PATH_PR_INCOMPLETE" in result.blockers
    assert result.incomplete_prs == ("PR-140",)


def test_pr141_completion_requires_evidence_hash() -> None:
    item_without_hash = PR141RoadmapItem(
        pr_id="PR-128",
        title="compute finalization",
        status="merged",
        category="transaction_economics",
    )
    items = tuple(
        item_without_hash if item.pr_id == "PR-128" else item for item in _items()
    )
    result = evaluate_pr141_paper_readiness_bridge(_evidence(items=items))

    assert result.review_ready is False
    assert "PR_COMPLETION_EVIDENCE_MISSING:PR-128" in result.blockers


def test_pr141_group_mismatch_blocks_bridge() -> None:
    wrong = PR141RoadmapItem(
        pr_id="PR-133",
        title="hermetic supply chain",
        status="merged",
        category="durability_operations",
        evidence_sha256=HASH,
    )
    items = tuple(wrong if item.pr_id == "PR-133" else item for item in _items())
    result = evaluate_pr141_paper_readiness_bridge(_evidence(items=items))

    assert result.review_ready is False
    assert "PR_GROUP_MISMATCH:PR-133" in result.blockers


def test_pr141_unresolved_item_blockers_fail_closed() -> None:
    blocked = PR141RoadmapItem(
        pr_id="PR-137",
        title="cpi graph",
        status="merged",
        category="transaction_economics",
        evidence_sha256=HASH,
        blockers=("unexpected CPI fixture missing",),
    )
    items = tuple(blocked if item.pr_id == "PR-137" else item for item in _items())
    result = evaluate_pr141_paper_readiness_bridge(_evidence(items=items))

    assert result.review_ready is False
    assert "PR_HAS_UNRESOLVED_BLOCKERS:PR-137" in result.blockers


def test_pr141_paper_soak_scope_must_include_required_surfaces() -> None:
    result = evaluate_pr141_paper_readiness_bridge(
        _evidence(scope=_scope(cpi_call_graph=False, data_lineage=False))
    )

    assert result.review_ready is False
    assert "PAPER_SOAK_SCOPE_MISSING:CPI_CALL_GRAPH" in result.blockers
    assert "PAPER_SOAK_SCOPE_MISSING:DATA_LINEAGE" in result.blockers


def test_pr141_paper_soak_must_keep_sender_disabled() -> None:
    result = evaluate_pr141_paper_readiness_bridge(
        _evidence(scope=_scope(live_sender_disabled=False))
    )

    assert result.review_ready is False
    assert "PAPER_SOAK_MUST_KEEP_SENDER_DISABLED" in result.blockers


def test_pr141_live_sequence_cannot_start_before_pr105_soak() -> None:
    live_item = PR141RoadmapItem(
        pr_id="PR-130",
        title="Jito protection",
        status="merged",
        category="live_after_soak",
        evidence_sha256=HASH,
    )
    result = evaluate_pr141_paper_readiness_bridge(
        _evidence(items=_items() + (live_item,))
    )

    assert result.review_ready is False
    assert "LIVE_SEQUENCE_STARTED_BEFORE_SOAK:PR-130" in result.blockers


def test_pr141_schema_and_pr_id_validation() -> None:
    with pytest.raises(PR141BridgeError):
        PR141RoadmapItem("PR-14", "bad", "merged", "x", HASH)
    with pytest.raises(PR141BridgeError):
        PR141BridgeEvidence(
            roadmap_items=_items(),
            paper_soak_scope=_scope(),
            schema_version="wrong",
        )
