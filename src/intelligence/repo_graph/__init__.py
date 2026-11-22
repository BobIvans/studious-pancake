"""Deterministic, LLM-free repository symbol graph (OCA-W0B).

Derived read-only view over canonical owners; no signing, submission, model
authority, or network access. See LLM_FREE_DETERMINISTIC_INDEXING_CONTRACT_RU.md
(design PR #666 head 6214202b) for the binding contract.
"""

from .schema import (
    GRAPH_SCHEMA_VERSION,
    PARSER_VERSION,
    SCHEMA_ID,
    canonical_jsonl,
    graph_generation,
    stable_symbol_id,
)
from .graph_build import build_graph
from .service import QueryBackend, resolve_repo_sha
from .store import artifact_path, dangling_edge_count, load_manifest

__all__ = [
    "GRAPH_SCHEMA_VERSION",
    "PARSER_VERSION",
    "SCHEMA_ID",
    "QueryBackend",
    "artifact_path",
    "build_graph",
    "canonical_jsonl",
    "dangling_edge_count",
    "graph_generation",
    "load_manifest",
    "resolve_repo_sha",
    "stable_symbol_id",
]
