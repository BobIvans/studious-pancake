"""Deterministic, LLM-free repository symbol graph (OCA-W0B).

Derived read-only view over the pinned git snapshot primitives in
``src/intelligence/repo_snapshot.py``. Never a canonical store; never a
replacement for the canonical owners listed in PROJECT_KNOWLEDGE_BASE_MAP.md.

Determinism contract (LLM_FREE_DETERMINISTIC_INDEXING_CONTRACT_RU.md, PR #666
head 6214202b): same repo SHA + pinned parser/resolver/schema versions produce
byte-identical canonical node/edge/coverage records and checksums. No LLM,
model API, embeddings, or network access anywhere in this package.
"""

from __future__ import annotations

import hashlib
import json

SCHEMA_ID = "studious.repo-graph.v1"
PARSER_VERSION = "stdlib-ast-py3.13"
GRAPH_SCHEMA_VERSION = 1

# Node kinds
KIND_MODULE = "module"
KIND_CLASS = "class"
KIND_FUNCTION = "function"

# Relation classes (static facts; runtime-observed edges require proven
# producers and are never emitted by this package).
EDGE_DEFINES = "DEFINES"
EDGE_IMPORTS = "IMPORTS"
EDGE_CALLS_RESOLVED = "CALLS_RESOLVED"
EDGE_CALLS_STATIC = "CALLS_STATIC"
EDGE_TESTED_BY = "TESTED_BY"
EDGE_CONFIGURED_BY = "CONFIGURED_BY"

# Edge provenance classes. Provenance is never upgraded automatically:
# STATIC_EXTRACTED facts come from AST structure; PATTERN_MATCH candidates
# stay PROPOSED; only canonical-registry joins may carry canonical evidence.
PROVENANCE_STATIC_EXTRACTED = "STATIC_EXTRACTED"
PROVENANCE_PATTERN_MATCH = "PATTERN_MATCH"

# Per-file coverage statuses (no silent omissions).
COVERAGE_INDEXED = "INDEXED"
COVERAGE_PARTIAL = "PARTIAL"
COVERAGE_UNSUPPORTED = "UNSUPPORTED"
COVERAGE_EXCLUDED_WITH_REASON = "EXCLUDED_WITH_REASON"
COVERAGE_PARSE_ERROR = "PARSE_ERROR"
COVERAGE_UNCLASSIFIED = "UNCLASSIFIED"

_CODE_SUFFIXES = (".py",)
_TEXT_SUFFIXES = (
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".txt",
    ".sql",
    ".sh",
    ".lock",
)


def language_class(path: str) -> str:
    """Deterministic coarse language classification for coverage records."""
    lowered = path.lower()
    if lowered.endswith(_CODE_SUFFIXES):
        return "python"
    if lowered.endswith(_TEXT_SUFFIXES):
        return "text-config"
    return "other"


def canonical_jsonl(records: list[dict]) -> bytes:
    """Serialize records deterministically: sorted keys, compact, stable order."""
    lines = [
        json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        for record in records
    ]
    return ("\n".join(lines) + "\n").encode("utf-8") if lines else b""


def stable_symbol_id(path: str, qualified_name: str) -> str:
    return f"py::{path}::{qualified_name}"


def graph_generation(repo_sha: str, canonical_checksum: str) -> str:
    """Deterministic generation identity for a built graph artifact."""
    payload = f"{SCHEMA_ID}|{GRAPH_SCHEMA_VERSION}|{repo_sha}|{canonical_checksum}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# OCA-W0B2: artifact classes and expanded coverage statuses (full-tree layer).
# ---------------------------------------------------------------------------

# 14 required artifact classes (FULL_REPOSITORY_GRAPH_AND_MCP_EXPANSION_RU.md §2.1).
ARTIFACT_CLASS_PYTHON_SOURCE = "python_source"
ARTIFACT_CLASS_TEST_CODE = "test_code"
ARTIFACT_CLASS_SCRIPT = "script"
ARTIFACT_CLASS_CONFIG = "config"
ARTIFACT_CLASS_SCHEMA = "schema"
ARTIFACT_CLASS_DOC = "doc"
ARTIFACT_CLASS_WORKFLOW = "workflow"
ARTIFACT_CLASS_BUILD_DEFINITION = "build_definition"
ARTIFACT_CLASS_DEPENDENCY_LOCK = "dependency_lock"
ARTIFACT_CLASS_VENDOR_REFERENCE = "vendor_reference"
ARTIFACT_CLASS_GENERATED_ASSET = "generated_asset"
ARTIFACT_CLASS_DATA_FIXTURE = "data_fixture"
ARTIFACT_CLASS_SECRET_EXCLUDED = "secret_excluded"
ARTIFACT_CLASS_OTHER_TRACKED = "other_tracked"
ARTIFACT_CLASSES = frozenset(
    {
        ARTIFACT_CLASS_PYTHON_SOURCE,
        ARTIFACT_CLASS_TEST_CODE,
        ARTIFACT_CLASS_SCRIPT,
        ARTIFACT_CLASS_CONFIG,
        ARTIFACT_CLASS_SCHEMA,
        ARTIFACT_CLASS_DOC,
        ARTIFACT_CLASS_WORKFLOW,
        ARTIFACT_CLASS_BUILD_DEFINITION,
        ARTIFACT_CLASS_DEPENDENCY_LOCK,
        ARTIFACT_CLASS_VENDOR_REFERENCE,
        ARTIFACT_CLASS_GENERATED_ASSET,
        ARTIFACT_CLASS_DATA_FIXTURE,
        ARTIFACT_CLASS_SECRET_EXCLUDED,
        ARTIFACT_CLASS_OTHER_TRACKED,
    }
)

# Expanded coverage statuses: STRUCTURE_INDEXED means a structural parser
# produced typed nodes; TEXT_INDEXED means text-layer extraction only;
# METADATA_ONLY means identity recorded without content parsing.
COVERAGE_STRUCTURE_INDEXED = "STRUCTURE_INDEXED"
COVERAGE_TEXT_INDEXED = "TEXT_INDEXED"
COVERAGE_METADATA_ONLY = "METADATA_ONLY"


def stable_node_id(language: str, path: str, qualified_name: str) -> str:
    """Cross-language stable symbol ID (W0B2); ``py`` kept for Python."""
    prefix = "py" if language == "python" else language
    return f"{prefix}::{path}::{qualified_name}"
