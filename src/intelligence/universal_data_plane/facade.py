"""Read-only cross-store facade: one entry point, stable-ID resolution.

The facade delegates all retrieval to ``repo_graph.service.QueryBackend`` (the
single backend shared by CLI/MCP/export) and adds store inventory + honest
unavailable-dimension reporting. It holds no write paths.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..repo_graph.graph_build import build_graph
from ..repo_graph.service import QueryBackend, resolve_repo_sha
from ..repo_graph.store import load_manifest
from . import SCHEMA_ID, STORES


class UniversalDataPlane:
    def __init__(self, state_root: str, repo_root: str | None = None) -> None:
        self._backend = QueryBackend(state_root, repo_root)
        self._state_root = state_root

    def inventory(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_ID,
            "stores": dict(sorted(STORES.items())),
            "note": (
                "runtime dimensions report UNAVAILABLE until OCA-W10 wires "
                "real EventEnvelope producers (OCA-W0 trace, PR #680)"
            ),
        }

    @property
    def repo_root(self) -> str | None:
        return self._backend._repo_root

    def resolve_repo_ref(
        self,
        repo_ref: str = "main",
        *,
        auto_refresh: bool = False,
    ) -> dict[str, Any]:
        """Resolve a ref once, pin the SHA, and optionally refresh locally.

        Refresh runs only when explicitly enabled, is guarded by a one-writer
        lock file, and never mutates canonical stores (build artifacts only).
        """
        if self._backend._repo_root is None:
            raise ValueError("repo_root required for repo_ref resolution")
        repo_sha = resolve_repo_sha(self._backend._repo_root, repo_ref)
        fresh = self._backend.freshness(repo_sha)
        refreshed = False
        if fresh["status"] == "UNAVAILABLE" and auto_refresh:
            lock = Path(self._state_root) / "repo_graph" / "refresh.lock"
            if lock.exists():
                fresh = {**fresh, "status": fresh["status"], "note": "refresh busy"}
            else:
                lock.parent.mkdir(parents=True, exist_ok=True)
                lock.write_text(repo_sha, encoding="utf-8")
                try:
                    receipt = build_graph(self._backend._repo_root, self._state_root)
                    refreshed = True
                    fresh = self._backend.freshness(repo_sha)
                    fresh["refreshed_generation"] = receipt["generation"]
                finally:
                    lock.unlink(missing_ok=True)
        return {
            "repo_ref": repo_ref,
            "repo_sha": repo_sha,
            "freshness": fresh,
            "auto_refreshed": refreshed,
        }

    def publish_index(self, repo_sha: str) -> dict[str, Any]:
        """Immutable SHA-bound publication of the current artifact manifest."""
        manifest = load_manifest(self._state_root, repo_sha)
        published = Path(self._state_root) / "repo_graph" / "published" / repo_sha[:16]
        target = published / "manifest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            return {"published": str(target), "immutable": "already published"}
        target.write_text(
            json.dumps(manifest, sort_keys=True, indent=1) + chr(10), encoding="utf-8"
        )
        return {"published": str(target), "generation": manifest["generation"]}

    def task_context(self, task: str, **kwargs: Any) -> dict[str, Any]:
        envelope = self._backend.task_context(task, **kwargs)
        if envelope.get("status") in {"STALE", "UNAVAILABLE"}:
            envelope["source_fallback_required"] = True
        return envelope

    def expand_context(self, refs: list[str], **kwargs: Any) -> dict[str, Any]:
        return self._backend.expand_context(refs, **kwargs)

    def repo_card(self, repo_sha: str) -> dict[str, Any]:
        return self._backend.repo_card(repo_sha)

    def export_context_pack(
        self, envelope: dict[str, Any], out_path: str | Path
    ) -> dict[str, Any]:
        """Write a portable, SHA-bound context pack bundle (JSON, hashed).

        The pack carries the full envelope manifest plus the resolved source
        contents and a sha256 over the canonical serialization. No timestamps
        enter the pack hash.
        """
        content = envelope.pop("_content", {})
        bundle = {
            "schema": f"{SCHEMA_ID}.context-pack",
            "envelope": envelope,
            "contents": dict(sorted(content.items())),
        }
        rendered = json.dumps(bundle, sort_keys=True, indent=1)
        digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        bundle["pack_sha256"] = digest
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(bundle, sort_keys=True, indent=1) + "\n", encoding="utf-8"
        )
        return {
            "pack_sha256": digest,
            "path": str(out),
            "refs": len(envelope.get("included_refs", [])),
        }
