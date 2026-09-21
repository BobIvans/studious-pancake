"""PR-154 / NF-365..368: upstream semantic-drift review."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .common import artifact, fail_closed, canonical_hash, require_text, sorted_unique


def scan_upstream_semantic_drift(
    upstream_id: str,
    previous_symbols: Sequence[str],
    current_symbols: Sequence[str],
):
    uid = require_text(upstream_id, "upstream_id")
    before = set(sorted_unique(previous_symbols))
    after = set(sorted_unique(current_symbols))
    return artifact(
        child="PR-154",
        nf="NF-365",
        action="scan_upstream_semantic_drift",
        subject_id=uid,
        payload={
            "added": tuple(sorted(after - before)),
            "removed": tuple(sorted(before - after)),
            "stable": tuple(sorted(before & after)),
        },
    )


def refresh_golden_vectors(
    upstream_id: str,
    vectors: Sequence[Mapping[str, object]],
):
    uid = require_text(upstream_id, "upstream_id")
    hashes = tuple(sorted(canonical_hash(dict(vector)) for vector in vectors))
    if not hashes:
        return fail_closed(
            child="PR-154",
            nf="NF-366",
            action="refresh_golden_vectors",
            subject_id=uid,
            reason="INSUFFICIENT_EVIDENCE",
        )
    return artifact(
        child="PR-154",
        nf="NF-366",
        action="refresh_golden_vectors",
        subject_id=uid,
        payload={"vector_hashes": hashes, "vector_count": len(hashes)},
    )


def classify_breaking_change(
    upstream_id: str,
    removed_symbols: Sequence[str],
    changed_contracts: Sequence[str],
):
    uid = require_text(upstream_id, "upstream_id")
    removed = sorted_unique(removed_symbols)
    changed = sorted_unique(changed_contracts)
    severity = "BREAKING" if removed or changed else "COMPATIBLE"
    return artifact(
        child="PR-154",
        nf="NF-367",
        action="classify_breaking_change",
        subject_id=uid,
        payload={"severity": severity, "removed": removed, "changed": changed},
    )


def gate_dependency_upgrade(
    upstream_id: str,
    classification: str,
    conformance_passed: bool,
):
    uid = require_text(upstream_id, "upstream_id")
    category = require_text(classification, "classification").upper()
    if category not in {"COMPATIBLE", "BREAKING"}:
        return fail_closed(
            child="PR-154",
            nf="NF-368",
            action="gate_dependency_upgrade",
            subject_id=uid,
            reason="UNSUPPORTED_VERSION",
            payload={"classification": category},
        )
    if category == "BREAKING" or not conformance_passed:
        return fail_closed(
            child="PR-154",
            nf="NF-368",
            action="gate_dependency_upgrade",
            subject_id=uid,
            reason="INSUFFICIENT_EVIDENCE",
            payload={
                "classification": category,
                "conformance_passed": conformance_passed,
            },
        )
    return artifact(
        child="PR-154",
        nf="NF-368",
        action="gate_dependency_upgrade",
        subject_id=uid,
        payload={"classification": category, "conformance_passed": True},
    )
