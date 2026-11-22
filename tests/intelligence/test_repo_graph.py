"""OCA-W0B contract tests: determinism, parity, freshness, coverage, envelope.

All fixtures are local temporary git repositories; no network, no live
evidence, no model APIs (runs under pytest --disable-socket).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.intelligence.repo_graph.graph_build import build_graph
from src.intelligence.repo_graph.service import QueryBackend, resolve_repo_sha
from src.intelligence.repo_graph.store import (
    artifact_path,
    dangling_edge_count,
    load_manifest,
)

CORE_PY = '''"""Core engine module."""

import json

from .util import normalise


class Engine:
    def __init__(self, name: str) -> None:
        self.name = name

    def run(self, value: str) -> str:
        return normalise(value)


def run_engine(engine: Engine, value: str) -> str:
    return engine.run(value)


def _unused_helper(value: str) -> str:
    return json.dumps({"value": value})
'''

UTIL_PY = '''"""Utility helpers."""

def normalise(value: str) -> str:
    return value.strip().lower()
'''

TEST_PY = """from src.pkg.core import Engine

def test_engine() -> None:
    assert Engine("a").run(" X ") == "x"
"""

CONFIG_JSON = '{"feature_flags": {"demo": false}}\n'


def _git(repo: Path, *args: str) -> None:
    subprocess.check_output(["git", "-C", str(repo), *args])


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.name=fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-m",
        message,
    )
    return subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()


@pytest.fixture()
def fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "src" / "pkg").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "config").mkdir()
    (repo / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "src" / "pkg" / "core.py").write_text(CORE_PY, encoding="utf-8")
    (repo / "src" / "pkg" / "util.py").write_text(UTIL_PY, encoding="utf-8")
    (repo / "tests" / "test_core.py").write_text(TEST_PY, encoding="utf-8")
    (repo / "config" / "app.json").write_text(CONFIG_JSON, encoding="utf-8")
    (repo / "README.md").write_text("# fixture\n", encoding="utf-8")
    (repo / ".env").write_text("SECRET_TOKEN=not-a-real-secret\n", encoding="utf-8")
    (repo / "blob.bin").write_bytes(b"\x00\x01\x02binary")
    _git(repo, "init", "-q")
    _commit_all(repo, "fixture v1")
    return repo


def _write_source(repo: Path, relative: str, content: str) -> None:
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def test_two_clean_builds_are_byte_identical(
    fixture_repo: Path, tmp_path: Path
) -> None:
    root_a = tmp_path / "state-a"
    root_b = tmp_path / "state-b"
    receipt_a = build_graph(fixture_repo, root_a)
    receipt_b = build_graph(fixture_repo, root_b)
    assert receipt_a["canonical_checksum"] == receipt_b["canonical_checksum"]
    assert receipt_a["generation"] == receipt_b["generation"]
    dir_a = Path(receipt_a["artifact_dir"])
    dir_b = Path(receipt_b["artifact_dir"])
    for name in ("nodes.jsonl", "edges.jsonl", "coverage.jsonl"):
        assert (dir_a / name).read_bytes() == (dir_b / name).read_bytes(), name


def test_incremental_matches_clean_rebuild(fixture_repo: Path, tmp_path: Path) -> None:
    sha_1 = resolve_repo_sha(str(fixture_repo), "HEAD")
    root = tmp_path / "state"
    first = build_graph(fixture_repo, root)
    _write_source(
        fixture_repo, "src/pkg/extra.py", "def extra() -> int:\n    return 1\n"
    )
    _commit_all(fixture_repo, "fixture v2")
    incremental = build_graph(fixture_repo, root)
    clean_root = tmp_path / "state-clean"
    clean = build_graph(fixture_repo, clean_root)
    assert incremental["repo_sha"] != sha_1
    assert incremental["canonical_checksum"] == clean["canonical_checksum"]
    assert incremental["generation"] == clean["generation"]
    assert first["repo_sha"] == sha_1
    added = incremental["tree_changes"]["added"]
    assert any(item["path"] == "src/pkg/extra.py" for item in added)


def test_rename_and_delete_handling(fixture_repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "state"
    build_graph(fixture_repo, root)
    _git(fixture_repo, "mv", "src/pkg/util.py", "src/pkg/helper.py")
    _commit_all(fixture_repo, "rename util -> helper")
    receipt = build_graph(fixture_repo, root)
    renamed = receipt["tree_changes"]["renamed"]
    assert any(
        item["old_path"] == "src/pkg/util.py"
        and item["new_path"] == "src/pkg/helper.py"
        for item in renamed
    )
    clean_root = tmp_path / "state-clean"
    clean = build_graph(fixture_repo, clean_root)
    assert receipt["canonical_checksum"] == clean["canonical_checksum"]

    (fixture_repo / "src/pkg/helper.py").unlink()
    _commit_all(fixture_repo, "delete helper")
    after_delete = build_graph(fixture_repo, root)
    clean_after = build_graph(fixture_repo, tmp_path / "state-clean2")
    assert after_delete["canonical_checksum"] == clean_after["canonical_checksum"]
    coverage_paths = {
        row["path"]
        for row in load_manifest(str(root), after_delete["repo_sha"])["inventory"]
    }
    assert "src/pkg/helper.py" not in coverage_paths


def test_coverage_statuses_no_silent_omissions(
    fixture_repo: Path, tmp_path: Path
) -> None:
    root = tmp_path / "state"
    receipt = build_graph(fixture_repo, root)
    manifest = load_manifest(str(root), receipt["repo_sha"])
    by_path = {row["path"]: row for row in manifest["inventory"]}
    assert by_path[".env"]["coverage"] == "EXCLUDED_WITH_REASON"
    assert by_path["blob.bin"]["coverage"] == "UNSUPPORTED"
    assert by_path["config/app.json"]["coverage"] == "INDEXED"
    assert by_path["README.md"]["coverage"] == "INDEXED"
    core = by_path["src/pkg/core.py"]
    assert core["coverage"] == "INDEXED"
    assert core["symbol_count"] >= 3
    # Every tracked file has exactly one coverage row (contract 1.3).
    assert set(by_path) == {row["path"] for row in manifest["inventory"]}
    assert manifest["counts"]["files_tracked"] == len(manifest["inventory"])


def test_dangling_edges_zero(fixture_repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "state"
    receipt = build_graph(fixture_repo, root)
    assert dangling_edge_count(receipt["artifact_dir"]) == 0


def test_edges_resolution_statuses(fixture_repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "state"
    receipt = build_graph(fixture_repo, root)
    edges = [
        json_line
        for json_line in (Path(receipt["artifact_dir"]) / "edges.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    import json as _json

    parsed = [_json.loads(line) for line in edges]
    relations = {edge["relation"] for edge in parsed}
    assert {"DEFINES", "IMPORTS", "TESTED_BY"} <= relations
    tested_by = [edge for edge in parsed if edge["relation"] == "TESTED_BY"]
    assert any("tests/test_core.py" in edge["target"] for edge in tested_by)
    # Same-name guesses must never be CALLS_RESOLVED (contract 1.5).
    for edge in parsed:
        if edge["relation"] == "CALLS_RESOLVED":
            assert edge["resolution"] == "RESOLVED"


def test_task_context_envelope_and_expansion(
    fixture_repo: Path, tmp_path: Path
) -> None:
    root = tmp_path / "state"
    receipt = build_graph(fixture_repo, root)
    sha = receipt["repo_sha"]
    backend = QueryBackend(str(root), str(fixture_repo))
    envelope = backend.task_context("engine run normalise", repo_sha=sha)
    assert envelope["status"] in {"FRESH", "BUDGET_LIMITED"}
    assert envelope["repo_sha"] == sha
    assert envelope["indexed_sha"] == sha
    assert envelope["freshness"]["status"] == "FRESH"
    included_paths = {ref["path"] for ref in envelope["included_refs"]}
    assert "src/pkg/core.py" in included_paths
    assert envelope["tokenizer"].startswith("byte-estimate")
    # Exact expansion by stable symbol ID.
    core_module_id = f"py::src/pkg/core.py::src.pkg.core"
    expansion = backend.expand_context([core_module_id], repo_sha=sha)
    assert expansion["status"] == "FRESH"
    symbol_payload = expansion["refs"][core_module_id]
    assert symbol_payload["kind"] == "symbol"
    assert symbol_payload["source"].startswith('"""Core engine module."""')
    # Stale-SHA rejection: a different SHA must never present as FRESH.
    stale = backend.task_context("anything", repo_sha="0" * 40)
    assert stale["status"] in {"STALE", "UNAVAILABLE"}
    assert stale["included_refs"] == []


def test_unknown_repo_sha_is_unavailable(tmp_path: Path) -> None:
    backend = QueryBackend(str(tmp_path / "empty-state"), str(tmp_path))
    fresh = backend.freshness("b" * 40)
    assert fresh["status"] == "UNAVAILABLE"
