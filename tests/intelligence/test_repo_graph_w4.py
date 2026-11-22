"""OCA-W4 adaptive retrieval tests: task-type routing, directory refs, cursor."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.intelligence.repo_graph.service import (
    QueryBackend,
    detect_task_type,
    _task_hash,
)
from src.intelligence.repo_graph.graph_build import build_graph

from tests.intelligence.test_repo_graph import (
    CONFIG_JSON,
    CORE_PY,
    TEST_PY,
    UTIL_PY,
    _commit_all,
    fixture_repo,  # noqa: F401  (pytest fixture)
)


def test_detect_task_type_rules() -> None:
    assert detect_task_type("Fix the traceback in the engine run path") == "bug"
    assert (
        detect_task_type("which adapter owns the jupiter quote endpoint") == "provider"
    )
    assert detect_task_type("strategy capital lender economics") == "strategy"
    assert detect_task_type("add flaky test coverage") == "test"
    assert detect_task_type("refactor the split of this module") == "refactor"
    assert detect_task_type("where is AssetResolver defined") == "generic"


def test_directory_must_include_refs_expand(fixture_repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "state"
    receipt = build_graph(fixture_repo, root)
    sha = receipt["repo_sha"]
    backend = QueryBackend(str(root), str(fixture_repo))
    envelope = backend.task_context(
        "engine behaviour",
        repo_sha=sha,
        must_include_refs=["src/pkg"],
        budget_tokens=4000,
    )
    assert envelope["status"] in {"FRESH", "BUDGET_LIMITED"}
    assert (
        envelope["resolved_directory_refs"]["src/pkg"][:1]
        == sorted(envelope["resolved_directory_refs"]["src/pkg"])[:1]
    )
    included = {ref["path"] for ref in envelope["included_refs"]}
    omitted = {ref["path"] for ref in envelope["omitted_refs"]}
    contained = set(envelope["resolved_directory_refs"]["src/pkg"])
    assert contained and contained <= (included | omitted)


def test_continuation_cursor_round_trip(fixture_repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "state"
    receipt = build_graph(fixture_repo, root)
    sha = receipt["repo_sha"]
    backend = QueryBackend(str(root), str(fixture_repo))
    first = backend.task_context(
        "engine run normalise util core",
        repo_sha=sha,
        budget_tokens=1,
    )
    assert first["status"] in {"BUDGET_LIMITED", "FRESH"}
    cursor = first["continuation_cursor"]
    if cursor is None:
        pytest.skip("no omissions at this budget")
    assert cursor["task_hash"] == _task_hash(
        "engine run normalise util core", sha, 1, ("auto",)
    )
    second = backend.task_context(
        "engine run normalise util core",
        repo_sha=sha,
        budget_tokens=1,
        continuation_cursor=cursor,
    )
    assert second["freshness"]["status"] == "FRESH"
    with pytest.raises(ValueError):
        backend.task_context(
            "different task",
            repo_sha=sha,
            budget_tokens=1,
            continuation_cursor=cursor,
        )


def test_task_type_boost_is_deterministic(fixture_repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "state"
    receipt = build_graph(fixture_repo, root)
    sha = receipt["repo_sha"]
    backend = QueryBackend(str(root), str(fixture_repo))
    bug_view = backend.task_context("engine failure traceback fix", repo_sha=sha)
    generic_view = backend.task_context("engine run normalise", repo_sha=sha)
    assert bug_view["task_type"] == "bug"
    assert generic_view["task_type"] == "generic"
    assert bug_view["included_refs"] == bug_view["included_refs"]


def test_continuation_multi_page_no_repeats_no_skips(
    fixture_repo: Path, tmp_path: Path
) -> None:
    """P2-B: a ranked candidate set larger than one page must paginate with
    every expected ref returned exactly once and no empty page while
    unprocessed candidates remain."""
    from src.intelligence.repo_graph.graph_build import build_graph
    from src.intelligence.repo_graph.service import QueryBackend, resolve_repo_sha

    for index in range(30):
        module = (
            "def paginate_candidate_%d(value: str) -> str:\n"
            "    return value + str(%d)\n" % (index, index)
        )
        (fixture_repo / "src" / "pkg" / f"pagetest_{index:02d}.py").write_text(
            module, encoding="utf-8"
        )
    from tests.intelligence.test_repo_graph import _commit_all

    _commit_all(fixture_repo, "pagination fixture")
    root = tmp_path / "state"
    receipt = build_graph(fixture_repo, root)
    sha = receipt["repo_sha"]
    backend = QueryBackend(str(root), str(fixture_repo))
    task = "paginate candidate"
    seen: list[str] = []
    cursor = None
    pages = 0
    for _ in range(10):
        envelope = backend.task_context(
            task,
            repo_sha=sha,
            budget_tokens=8000,
            continuation_cursor=cursor,
        )
        pages += 1
        page_paths = [ref["path"] for ref in envelope["included_refs"]]
        assert page_paths, "no empty page while unprocessed candidates remain"
        seen.extend(page_paths)
        cursor = envelope["continuation_cursor"]
        if cursor is None:
            break
    assert pages >= 3, f"expected >=3 pages, got {pages}"
    assert len(seen) == len(set(seen)), "repeated candidate across pages"
    assert len(seen) == 30
    delivered = {Path(path).name for path in seen}
    assert len(delivered) == 30
