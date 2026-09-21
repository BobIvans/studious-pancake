"""PR-244 / LICENSE-02: fail-closed source-reuse policy evidence.

This is an engineering policy gate, not legal advice.  It records supplied
license evidence and refuses source copying when that evidence is unknown or
outside the repository's allowlist.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import re
from typing import Any

from .base import Disposition, ResearchArtifact, artifact, nonempty_text

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_PERMISSIVE = frozenset(
    {
        "Apache-2.0",
        "MIT",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "ISC",
    }
)


def scan_license_surface(
    entries: Iterable[Mapping[str, Any]],
) -> ResearchArtifact:
    normalized = []
    for item in entries:
        normalized.append(
            {
                "path": nonempty_text(item.get("path"), "path"),
                "license_id": str(item.get("license_id", "UNKNOWN")).strip()
                or "UNKNOWN",
                "source_sha256": str(item.get("source_sha256", "UNKNOWN")),
            }
        )
    normalized.sort(key=lambda item: item["path"])
    unknown = tuple(
        item["path"] for item in normalized if item["license_id"] == "UNKNOWN"
    )
    return artifact(
        "license-surface",
        {"entries": normalized, "unknown_paths": unknown},
        disposition=Disposition.PASS if not unknown else Disposition.BLOCKED,
        reason=(
            "license-evidence-complete" if not unknown else "license-evidence-unknown"
        ),
    )


def classify_copy_eligibility(
    license_ids: Iterable[str],
    *,
    requested_mode: str,
) -> ResearchArtifact:
    licenses = tuple(
        sorted({nonempty_text(value, "license_id") for value in license_ids})
    )
    mode = nonempty_text(requested_mode, "requested_mode").upper()
    copy_mode = mode in {"PORT", "VENDOR", "VENDOR-PURE"}
    eligible = bool(licenses) and all(item in _PERMISSIVE for item in licenses)
    if copy_mode and not eligible:
        decision = "REFERENCE_ONLY"
        disposition = Disposition.BLOCKED
    else:
        decision = mode if eligible or not copy_mode else "REFERENCE_ONLY"
        disposition = Disposition.PASS
    return artifact(
        "copy-eligibility",
        {
            "license_ids": licenses,
            "requested_mode": mode,
            "decision": decision,
            "public_visibility_is_permission": False,
        },
        disposition=disposition,
        reason="policy-classified",
    )


def generate_attribution_bundle(
    *,
    source_repository: str,
    immutable_ref: str,
    source_hashes: Iterable[str],
    notices: Iterable[str],
) -> ResearchArtifact:
    hashes = tuple(sorted(set(source_hashes)))
    normalized_notices = tuple(
        sorted({nonempty_text(notice, "notice") for notice in notices})
    )
    if not hashes:
        raise ValueError("source_hashes cannot be empty")
    if any(not _SHA256_RE.fullmatch(source_hash) for source_hash in hashes):
        raise ValueError("source_hashes must contain lowercase sha256 values")
    if not normalized_notices:
        raise ValueError("notices cannot be empty")
    payload = {
        "source_repository": nonempty_text(source_repository, "source_repository"),
        "immutable_ref": nonempty_text(immutable_ref, "immutable_ref"),
        "source_hashes": hashes,
        "notices": normalized_notices,
    }
    return artifact("attribution-bundle", payload)


def enforce_source_reuse_policy(
    eligibility: ResearchArtifact,
    attribution: ResearchArtifact | None,
) -> ResearchArtifact:
    decision = str(eligibility.payload.get("decision", "REFERENCE_ONLY"))
    copying = decision in {"PORT", "VENDOR", "VENDOR-PURE"}
    attribution_complete = (
        attribution is not None
        and attribution.kind == "attribution-bundle"
        and attribution.disposition is Disposition.PASS
        and bool(attribution.payload.get("source_hashes"))
        and bool(attribution.payload.get("notices"))
        and bool(attribution.payload.get("source_repository"))
        and bool(attribution.payload.get("immutable_ref"))
    )
    passed = eligibility.disposition is Disposition.PASS and (
        not copying or attribution_complete
    )
    return artifact(
        "source-reuse-policy",
        {
            "eligibility": eligibility.identity,
            "attribution": attribution.identity if attribution else "NONE",
            "source_copy_allowed": bool(passed and copying),
        },
        disposition=Disposition.PASS if passed else Disposition.BLOCKED,
        reason="reuse-policy-satisfied" if passed else "reuse-policy-blocked",
    )


__all__ = [
    "classify_copy_eligibility",
    "enforce_source_reuse_policy",
    "generate_attribution_bundle",
    "scan_license_surface",
]
