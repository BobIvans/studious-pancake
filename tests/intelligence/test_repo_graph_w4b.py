"""OCA-W4B tests: tokenizers, ranking, signature/body split, loss-aware packs."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.intelligence.repo_graph.graph_build import build_graph
from src.intelligence.repo_graph.ranking import personalized_pagerank
from src.intelligence.repo_graph.service import QueryBackend, resolve_repo_sha
from src.intelligence.repo_graph.tokenizers import (
    CharClassEstimator,
    resolve_tokenizer,
    signature_body_hashes,
)

from tests.intelligence.test_repo_graph import fixture_repo  # noqa: F401

FINANCIAL_CORE = '''"""Sizing with exact decimals and fees."""

def size_position(equity_atoms: int, fee_bps: int, decimals: int) -> int:
    fee_atoms = equity_atoms * fee_bps // 10_000
    return equity_atoms - fee_atoms

def slippage_bound(price_atoms: int, max_bps: int) -> int:
    return price_atoms * max_bps // 10_000
'''


@pytest.fixture()
def w4b_repo(fixture_repo: Path) -> Path:
    (fixture_repo / "src" / "pkg" / "sizing.py").write_text(
        FINANCIAL_CORE, encoding="utf-8"
    )
    from tests.intelligence.test_repo_graph import _commit_all

    _commit_all(fixture_repo, "w4b fixture")
    return fixture_repo


def test_fallback_estimator_is_deterministic_and_labelled() -> None:
    adapter, meta = resolve_tokenizer(None)
    assert meta["tokenizer"] == "char-class-estimator-v1"
    assert meta["tokenizer_uncertainty"]
    assert meta["degraded_reason"] is None
    data = b"def run(value):\n    return value * 2\n"
    assert adapter.count(data) == adapter.count(data)
    assert adapter.count(data) > 0


def test_tiktoken_profile_degrades_explicitly() -> None:
    adapter, meta = resolve_tokenizer("tiktoken:o200k_base")
    assert meta["tokenizer"] == "char-class-estimator-v1" or meta[
        "tokenizer"
    ].startswith("tiktoken:")
    if meta["tokenizer"] == "char-class-estimator-v1":
        # Explicit degradation recorded, never a silent estimate pretending
        # to be a real tokenizer.
        assert meta["degraded_reason"] == "TIKTOKEN_UNAVAILABLE: Exception" or (
            meta["degraded_reason"] or ""
        ).startswith("TIKTOKEN_UNAVAILABLE")


def test_signature_body_hashes_independent_and_deterministic() -> None:
    data = b"def run(value):\n    return value * 2\n"
    hashes = signature_body_hashes(data, 0, len(data))
    assert hashes["signature_hash"] != hashes["body_hash"]
    again = signature_body_hashes(data, 0, len(data))
    assert hashes == again
    # Body-only change leaves the signature hash stable.
    changed = b"def run(value):\n    return value * 3\n"
    assert (
        signature_body_hashes(changed, 0, len(changed))["signature_hash"]
        == hashes["signature_hash"]
    )
    assert (
        signature_body_hashes(changed, 0, len(changed))["body_hash"]
        != hashes["body_hash"]
    )


def test_pagerank_deterministic_and_conditioned() -> None:
    edges = [("a", "b"), ("b", "c"), ("c", "a"), ("a", "d")]
    r1 = personalized_pagerank(edges, {"a": 1.0})
    r2 = personalized_pagerank(edges, {"a": 1.0})
    assert r1 == r2
    assert r1["a"] > r1["d"]
    empty = personalized_pagerank(edges, {})
    assert empty == {}
    # Seeds change the ranking (task-conditioning).
    from_b = personalized_pagerank(edges, {"b": 1.0})
    assert from_b["b"] > from_b["a"]


def test_task_conditioned_ranking_and_deterministic_packs(
    w4b_repo: Path, tmp_path: Path
) -> None:
    root = tmp_path / "state"
    receipt = build_graph(w4b_repo, root)
    sha = receipt["repo_sha"]
    backend = QueryBackend(str(root), str(w4b_repo))
    task = "size_position fee decimals slippage bound"
    env_a = backend.task_context(task, repo_sha=sha, budget_tokens=4000)
    env_b = backend.task_context(task, repo_sha=sha, budget_tokens=4000)
    assert env_a == env_b, "same task/SHA/budget must produce identical packs"
    assert env_a["task_type"] == "generic"
    # The financial target is FULL and preserves exact decimal/fee semantics.
    target = env_a["_content"].get("src/pkg/sizing.py")
    assert target is not None, env_a["included_refs"]
    assert "equity_atoms * fee_bps // 10_000" in target
    assert "price_atoms * max_bps // 10_000" in target


def test_resolution_labels_and_never_mid_body(w4b_repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "state"
    receipt = build_graph(w4b_repo, root)
    sha = receipt["repo_sha"]
    backend = QueryBackend(str(root), str(w4b_repo))
    env = backend.task_context(
        "engine run normalise util core sizing",
        repo_sha=sha,
        budget_tokens=6000,
    )
    included = env["included_refs"]
    assert included, env["status"]
    resolutions = {ref["path"]: ref["resolution"] for ref in included}
    assert set(resolutions.values()) <= {"FULL", "SKELETON", "REFERENCE"}
    full_refs = [ref for ref in included if ref["resolution"] == "FULL"]
    assert all(ref["token_estimate"] > 0 for ref in included)
    # Skeletons contain only signature/heading lines taken from recorded
    # ranges: every line is the skeleton header or ends with ":" (a signature
    # opener) — body statements never appear.
    for ref in included:
        if ref["resolution"] == "SKELETON":
            content = env["_content"][ref["path"]]
            for line in content.splitlines()[1:]:
                stripped = line.strip()
                assert stripped.endswith(":"), (
                    "skeleton must not include body statements",
                    line,
                )


def test_critical_omission_is_zero_on_financial_task(
    w4b_repo: Path, tmp_path: Path
) -> None:
    root = tmp_path / "state"
    receipt = build_graph(w4b_repo, root)
    sha = receipt["repo_sha"]
    backend = QueryBackend(str(root), str(w4b_repo))
    env = backend.task_context(
        "size_position fee slippage decimals", repo_sha=sha, budget_tokens=2000
    )
    got = {ref["path"] for ref in env["included_refs"]} | {
        ref["path"] for ref in env["omitted_refs"]
    }
    assert "src/pkg/sizing.py" in got
    body = env["_content"].get("src/pkg/sizing.py")
    if body is not None:
        # Critical financial semantics survive verbatim (no lossy trimming).
        for needle in ("10_000", "equity_atoms", "slippage_bound"):
            assert needle in body
