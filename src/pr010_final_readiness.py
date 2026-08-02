"""Fail-closed PR-010 final integration and readiness decision.

This module consumes a *materialized* release manifest.  It intentionally does
not infer readiness from a successful unit test or from a debt owner's claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "pr010.final-readiness.v1"
REQUIRED_MERGES = tuple(f"PR-{number:03d}" for number in range(1, 10))
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class Decision(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class Blocker:
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class FinalReadiness:
    decision: Decision
    blockers: tuple[Blocker, ...]
    production_debt_closed: tuple[str, ...]
    production_debt_open: tuple[str, ...]


def evaluate_final_readiness(manifest: Mapping[str, Any]) -> FinalReadiness:
    """Evaluate Wave 6 without turning declarations into evidence."""
    blockers: list[Blocker] = []
    _require(manifest.get("schema_version") == SCHEMA_VERSION, blockers, "SCHEMA", "schema_version")

    merges = _maps(manifest.get("merged_prs"))
    merge_ids = [str(item.get("id", "")) for item in merges]
    _require(merge_ids == list(REQUIRED_MERGES), blockers, "MERGE_ORDER", ",".join(merge_ids))
    for item in merges:
        _require(bool(GIT_SHA.fullmatch(str(item.get("merge_commit", "")))), blockers, "MERGE_COMMIT", str(item.get("id", "")))
        _require(item.get("verified_ancestor") is True, blockers, "MERGE_ANCESTRY", str(item.get("id", "")))

    _require(not tuple(manifest.get("stale_open_branches", ())), blockers, "STALE_BRANCHES", "stale/open PR branches remain")

    graph = _mapping(manifest.get("product_graph"))
    for key in ("installed_wheel_graph_sha256", "release_bundle_sha256", "qualification_log_sha256"):
        _require(_real_hash(graph.get(key)), blockers, "MATERIALIZED_HASH", key)
    for key in ("single_composition_root", "source_wheel_parity", "clean_install_verified", "release_bundle_verified"):
        _require(graph.get(key) is True, blockers, "PRODUCT_GRAPH", key)
    _require(graph.get("authority_count") == 1, blockers, "PRODUCT_AUTHORITY", "authority_count")
    _require(not tuple(graph.get("superseded_proof_islands", ())), blockers, "PROOF_ISLANDS", "superseded proof islands remain")

    closed: list[str] = []
    opened: list[str] = []
    for debt in _maps(manifest.get("production_debt")):
        debt_id = str(debt.get("id", ""))
        if debt.get("status") == "closed":
            evidence = _mapping(debt.get("evidence"))
            valid = (
                evidence.get("materialized") is True
                and evidence.get("verified") is True
                and _real_hash(evidence.get("sha256"))
                and isinstance(evidence.get("path"), str)
                and bool(evidence.get("path"))
            )
            if valid:
                closed.append(debt_id)
            else:
                opened.append(debt_id)
                blockers.append(Blocker("DEBT_WITHOUT_EVIDENCE", debt_id))
        else:
            opened.append(debt_id)

    _require(bool(manifest.get("production_debt")), blockers, "DEBT_INVENTORY", "missing")
    _require(not opened, blockers, "OPEN_DEBT", ",".join(opened))
    unique = tuple(dict.fromkeys(blockers))
    return FinalReadiness(
        decision=Decision.READY if not unique else Decision.BLOCKED,
        blockers=unique,
        production_debt_closed=tuple(closed),
        production_debt_open=tuple(opened),
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _maps(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(_mapping(item) for item in value)


def _real_hash(value: Any) -> bool:
    text = str(value)
    return bool(SHA256.fullmatch(text)) and len(set(text)) > 1


def _require(condition: bool, blockers: list[Blocker], code: str, detail: str) -> None:
    if not condition:
        blockers.append(Blocker(code, detail))
