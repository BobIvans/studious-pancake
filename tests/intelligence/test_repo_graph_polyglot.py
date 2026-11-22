"""OCA-W0B2 polyglot tests: artifact classes, extractors, tree-sitter modes."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.intelligence.repo_graph.extractors import (
    classify_artifact,
    extract_structured,
)
from src.intelligence.repo_graph.graph_build import build_graph
from src.intelligence.repo_graph.parsers import GRAMMAR_PACKS, capability_report
from src.intelligence.repo_graph.store import load_manifest

from tests.intelligence.test_repo_graph import _commit_all, fixture_repo  # noqa: F401

WORKFLOW_YAML = b"""name: fixture-ci
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: pytest -q
"""

CONFIG_TOML = b'[tool.fixture]\nflag = "value"\nlimit = 3\n'

DOC_MD = b"""# Fixture ADR

Decision: see [ADR-7](adr-007.md) and `make_event` producer contract.
"""

SCRIPT_SH = b"""#!/usr/bin/env bash
say_hello() {
  echo hello
}
say_hello
"""

VENDOR_RS = b"pub fn flashloan(v: u64) -> u64 { v }\n"


@pytest.fixture()
def polyglot_repo(fixture_repo: Path) -> Path:
    (fixture_repo / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (fixture_repo / "docs").mkdir(parents=True, exist_ok=True)
    (fixture_repo / "scripts").mkdir(parents=True, exist_ok=True)
    (fixture_repo / "src" / "resources" / "contracts").mkdir(
        parents=True, exist_ok=True
    )
    (fixture_repo / ".github" / "workflows" / "ci.yml").write_bytes(WORKFLOW_YAML)
    (fixture_repo / "config" / "fixture.toml").write_bytes(CONFIG_TOML)
    (fixture_repo / "docs" / "adr-001.md").write_bytes(DOC_MD)
    (fixture_repo / "scripts" / "fixture.sh").write_bytes(SCRIPT_SH)
    (fixture_repo / "src" / "resources" / "contracts" / "fixture.rs").write_bytes(
        VENDOR_RS
    )
    (fixture_repo / "requirements.lock").write_bytes(b"orjson==3.11.0\n")
    _commit_all(fixture_repo, "polyglot fixture")
    return fixture_repo


def test_artifact_classification_rules() -> None:
    assert (
        classify_artifact("src/pkg/core.py", "EXACT")["artifact_class"]
        == "python_source"
    )
    assert (
        classify_artifact("tests/test_x.py", "EXACT")["artifact_class"] == "test_code"
    )
    assert (
        classify_artifact(".github/workflows/ci.yml", "EXACT")["artifact_class"]
        == "workflow"
    )
    assert classify_artifact("config/app.json", "EXACT")["artifact_class"] == "config"
    assert (
        classify_artifact("src/resources/schema_registry.json", "EXACT")[
            "artifact_class"
        ]
        == "schema"
    )
    assert classify_artifact("docs/adr.md", "EXACT")["artifact_class"] == "doc"
    assert (
        classify_artifact("src/resources/contracts/m/flashloan.rs", "EXACT")[
            "artifact_class"
        ]
        == "vendor_reference"
    )
    assert (
        classify_artifact("src/resources/contracts/m/flashloan.rs", "EXACT")[
            "first_party"
        ]
        == "False"
    )
    assert (
        classify_artifact("requirements.lock", "EXACT")["artifact_class"]
        == "dependency_lock"
    )
    assert (
        classify_artifact("pyproject.toml", "EXACT")["artifact_class"]
        == "build_definition"
    )
    assert classify_artifact("scripts/tool.py", "EXACT")["artifact_class"] == "script"
    assert (
        classify_artifact(".env", "SECRET_METADATA_ONLY")["artifact_class"]
        == "secret_excluded"
    )


def test_extractors_deterministic_and_value_free() -> None:
    toml = extract_structured("config/fixture.toml", CONFIG_TOML)
    assert toml is not None and toml["parser"] == "stdlib-tomllib"
    names = [node["qualified_name"] for node in toml["nodes"]]
    assert "tool.fixture.flag" in names and "tool.fixture.limit" in names
    # Values are never extracted (secret-exclusion rule).
    rendered = repr(toml["nodes"])
    assert "value" not in rendered
    md = extract_structured("docs/adr-001.md", DOC_MD)
    kinds = {node["kind"] for node in md["nodes"]}
    assert {"doc_heading", "doc_link"} <= kinds
    again = extract_structured("config/fixture.toml", CONFIG_TOML)
    assert again == toml


def test_polyglot_build_full_accounting(polyglot_repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "state"
    receipt = build_graph(polyglot_repo, root)
    manifest = load_manifest(str(root), receipt["repo_sha"])
    by_path = {row["path"]: row for row in manifest["inventory"]}
    assert by_path[".github/workflows/ci.yml"]["coverage"] == "STRUCTURE_INDEXED"
    assert by_path["config/fixture.toml"]["coverage"] == "STRUCTURE_INDEXED"
    assert by_path["docs/adr-001.md"]["coverage"] == "STRUCTURE_INDEXED"
    assert by_path["scripts/fixture.sh"]["coverage"] in {"STRUCTURE_INDEXED", "PARTIAL"}
    if by_path["scripts/fixture.sh"]["coverage"] == "PARTIAL":
        assert "TREE_SITTER_GRAMMAR_ABSENT" in by_path["scripts/fixture.sh"]["reason"]
    vendor = by_path["src/resources/contracts/fixture.rs"]
    assert vendor["coverage"] == "METADATA_ONLY"
    assert vendor["artifact_class"] == "vendor_reference"
    # 100% tracked-path accounting: one coverage row per inventory entry.
    assert len(manifest["inventory"]) == manifest["counts"]["files_tracked"]
    assert {row["path"] for row in manifest["inventory"]} == set(by_path)
    # Polyglot nodes entered the graph.
    nodes_text = (Path(receipt["artifact_dir"]) / "nodes.jsonl").read_text(
        encoding="utf-8"
    )
    assert "yaml::.github/workflows/ci.yml::job:build" in nodes_text
    assert "toml::config/fixture.toml::tool.fixture.flag" in nodes_text
    assert "md::docs/adr-001.md::h1:Fixture ADR" in nodes_text


def test_capability_report_is_explicit() -> None:
    report = capability_report()
    assert report["core"]["package"] == "tree-sitter==0.25.2"
    for language, pack in GRAMMAR_PACKS.items():
        entry = report["grammars"][language]
        assert entry["pinned"] == pack
        assert isinstance(entry["available"], bool)


def test_golden_multi_language_retrieval(polyglot_repo: Path, tmp_path: Path) -> None:
    """Golden questions across non-Python artifact classes (W0B2 acceptance)."""
    from src.intelligence.repo_graph.service import QueryBackend, resolve_repo_sha

    root = tmp_path / "state"
    receipt = build_graph(polyglot_repo, root)
    sha = receipt["repo_sha"]
    backend = QueryBackend(str(root), str(polyglot_repo))
    questions = [
        ("which workflow job runs the tests", {".github/workflows/ci.yml"}),
        ("fixture toml config flag and limit keys", {"config/fixture.toml"}),
        ("ADR fixture decision document", {"docs/adr-001.md"}),
        ("dependency pins in the lock file", {"requirements.lock"}),
    ]
    for task, expected in questions:
        envelope = backend.task_context(
            task, repo_sha=resolve_repo_sha(str(polyglot_repo), "HEAD")
        )
        got = {ref["path"] for ref in envelope["included_refs"]} | {
            ref["path"] for ref in envelope["omitted_refs"]
        }
        assert expected <= got, (task, expected, got)


def test_dependency_pin_byte_offsets_with_non_ascii(tmp_path: Path) -> None:
    """P2-C: non-ASCII content before a pin must not shift byte ranges —
    expand_context byte slicing returns the exact original source bytes."""
    from src.intelligence.repo_graph.extractors import extract_structured

    # 7 multibyte characters (2 bytes each) precede the pin line.
    content = "# комментарий — émojis ✅ before\norjson==3.11.0\n".encode("utf-8")
    extracted = extract_structured("requirements.lock", content)
    assert extracted is not None
    assert extracted["parser"] == "regex-dependency-pins-utf8-bytes"
    node = extracted["nodes"][0]
    start, end = node["start_byte"], node["end_byte"]
    assert content[start:end].decode("utf-8") == "orjson==3.11.0", (
        start,
        end,
        content[start : end + 4],
    )


def test_markdown_byte_offsets_with_non_ascii(tmp_path: Path) -> None:
    """P2-6: multibyte headings keep exact byte ranges too."""
    from src.intelligence.repo_graph.extractors import extract_structured

    content = "— é — ✅\n\n# Заголовок секции\n".encode("utf-8")
    extracted = extract_structured("docs/notes.md", content)
    heading = next(n for n in extracted["nodes"] if n["kind"] == "doc_heading")
    text = content.decode("utf-8")
    assert (
        text.encode("utf-8")[heading["start_byte"] : heading["end_byte"]]
        .decode("utf-8")
        .startswith("#")
    )
