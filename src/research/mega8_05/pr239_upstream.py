"""PR-239 / UPSTREAM-03: read-only upstream discovery dossiers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .base import Disposition, ResearchArtifact, artifact, nonempty_text


def discover_upstream_release_candidates(
    releases: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Deduplicate already-captured official release metadata without network I/O."""
    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    for release in releases:
        repository = nonempty_text(release.get("repository"), "repository")
        immutable_ref = nonempty_text(release.get("immutable_ref"), "immutable_ref")
        if not bool(release.get("official")):
            continue
        key = (repository, immutable_ref)
        payload = {
            "repository": repository,
            "immutable_ref": immutable_ref,
            "release": str(release.get("release", "")),
            "license_id": str(release.get("license_id", "UNSPECIFIED")),
            "source_url": str(release.get("source_url", "")),
        }
        candidates.setdefault(key, payload)
    return tuple(candidates[key] for key in sorted(candidates))


def extract_candidate_symbols(
    candidate: Mapping[str, Any],
) -> dict[str, tuple[str, ...]]:
    """Extract exact paths/symbols/tests from captured metadata only."""
    result: dict[str, tuple[str, ...]] = {}
    for key in ("paths", "symbols", "callers", "tests"):
        values = candidate.get(key, ())
        if isinstance(values, str):
            values = (values,)
        result[key] = tuple(
            sorted({nonempty_text(value, key) for value in values})
        )
    return result


def rank_reuse_opportunity(
    candidates: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Rank by supplied evidence while keeping the score advisory-only."""
    ranked = []
    for candidate in candidates:
        usefulness = int(candidate.get("usefulness", 0))
        maturity = int(candidate.get("maturity", 0))
        test_quality = int(candidate.get("test_quality", 0))
        integration_cost = int(candidate.get("integration_cost", 0))
        score = usefulness + maturity + test_quality - integration_cost
        ranked.append({**dict(candidate), "reuse_score": score})
    return tuple(
        sorted(
            ranked,
            key=lambda item: (
                -int(item["reuse_score"]),
                str(item.get("repository", "")),
                str(item.get("immutable_ref", "")),
            ),
        )
    )


def publish_upstream_research_dossier(
    candidate: Mapping[str, Any],
) -> ResearchArtifact:
    repository = nonempty_text(candidate.get("repository"), "repository")
    immutable_ref = nonempty_text(candidate.get("immutable_ref"), "immutable_ref")
    official = bool(candidate.get("official"))
    license_id = (
        str(candidate.get("license_id", "UNSPECIFIED")).strip() or "UNSPECIFIED"
    )
    disposition = Disposition.PASS
    reason = "candidate-pinned-for-research"
    if not official:
        disposition = Disposition.REJECT
        reason = "unofficial-source"
    elif license_id == "UNSPECIFIED":
        disposition = Disposition.BLOCKED
        reason = "license-unspecified"
    payload = {
        "repository": repository,
        "immutable_ref": immutable_ref,
        "official": official,
        "license_id": license_id,
        "symbols": extract_candidate_symbols(candidate),
        "auto_import_allowed": False,
        "code_execution_allowed": False,
    }
    return artifact(
        "upstream-dossier",
        payload,
        disposition=disposition,
        reason=reason,
    )


__all__ = [
    "discover_upstream_release_candidates",
    "extract_candidate_symbols",
    "publish_upstream_research_dossier",
    "rank_reuse_opportunity",
]
