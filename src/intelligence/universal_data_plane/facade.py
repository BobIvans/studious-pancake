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

from ..repo_graph.service import QueryBackend
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
