"""Content-addressed parse cache and tree-diff classification.

Cache keys are (blob_sha256, parser_version) — never paths or mtimes (OCA-W16
requirement pulled forward per the incremental contract). Renames are explicit
records derived from identical blob identity at a new path, never silent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import PARSER_VERSION

CACHE_SCHEMA = "studious.repo-graph.parse-cache.v1"


def classify_tree_changes(
    previous: dict[str, str], current: dict[str, str]
) -> dict[str, list[dict[str, str]]]:
    """Classify path->blob_sha256 maps into add/modify/delete/rename.

    A rename is recorded when the exact blob sha256 appears at a new path while
    disappearing from its old path; the old->new pair is evidence, not a guess.
    """
    added: list[dict[str, str]] = []
    modified: list[dict[str, str]] = []
    deleted: list[dict[str, str]] = []
    renamed: list[dict[str, str]] = []
    old_by_sha: dict[str, list[str]] = {}
    for path, sha in previous.items():
        old_by_sha.setdefault(sha, []).append(path)
    new_by_sha: dict[str, list[str]] = {}
    for path, sha in current.items():
        new_by_sha.setdefault(sha, []).append(path)
    for path in sorted(set(previous) | set(current)):
        old_sha = previous.get(path)
        new_sha = current.get(path)
        if old_sha == new_sha:
            continue
        if old_sha is None:
            assert new_sha is not None, "old_sha None implies new blob identity"
            # An add may actually be the destination of a rename.
            if new_sha in old_by_sha:
                renamed.append(
                    {
                        "old_path": old_by_sha[new_sha][0],
                        "new_path": path,
                        "blob_sha256": new_sha,
                    }
                )
            else:
                added.append({"path": path, "blob_sha256": new_sha})
        elif new_sha is None:
            if old_sha in new_by_sha:
                continue  # accounted for as a rename destination
            deleted.append({"path": path, "blob_sha256": old_sha})
        else:
            modified.append(
                {"path": path, "old_blob_sha256": old_sha, "new_blob_sha256": new_sha}
            )
    return {
        "added": added,
        "modified": modified,
        "deleted": deleted,
        "renamed": renamed,
    }


def load_cache(state_root: str) -> dict[str, Any]:
    path = Path(state_root) / "repo_graph" / "parse_cache.json"
    if not path.exists():
        return {"schema": CACHE_SCHEMA, "parser_version": PARSER_VERSION, "entries": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("parser_version") != PARSER_VERSION:
        # Version change invalidates the affected caches (contract 2.1).
        return {"schema": CACHE_SCHEMA, "parser_version": PARSER_VERSION, "entries": {}}
    return payload


def save_cache(state_root: str, cache: dict[str, Any]) -> None:
    path = Path(state_root) / "repo_graph" / "parse_cache.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(cache, sort_keys=True, indent=1)
    path.write_text(rendered + "\n", encoding="utf-8")
