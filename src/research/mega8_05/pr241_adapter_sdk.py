"""PR-241 / ADAPTER-SDK-01: portable adapter conformance contracts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .base import Disposition, ResearchArtifact, artifact, nonempty_text


def define_adapter_conformance_contract(
    *,
    adapter_id: str,
    deployment_id: str,
    schema_sha256: str,
    quote_supported: bool,
    build_supported: bool,
) -> ResearchArtifact:
    payload = {
        "adapter_id": nonempty_text(adapter_id, "adapter_id"),
        "deployment_id": nonempty_text(deployment_id, "deployment_id"),
        "schema_sha256": nonempty_text(schema_sha256, "schema_sha256"),
        "state_read": True,
        "quote_supported": bool(quote_supported),
        "build_supported": bool(build_supported),
        "signing_supported": False,
        "submission_supported": False,
    }
    return artifact("adapter-contract", payload)


def build_golden_vector_pack(
    vectors: Iterable[Mapping[str, Any]],
) -> ResearchArtifact:
    normalized = []
    for vector in vectors:
        vector_id = nonempty_text(vector.get("vector_id"), "vector_id")
        normalized.append(
            {
                "vector_id": vector_id,
                "input": vector.get("input"),
                "expected": vector.get("expected"),
                "malicious": bool(vector.get("malicious", False)),
            }
        )
    if not normalized:
        raise ValueError("at least one golden vector is required")
    normalized.sort(key=lambda item: item["vector_id"])
    return artifact("adapter-golden-vectors", {"vectors": normalized})


def run_adapter_differential_suite(
    local_outputs: Mapping[str, Any],
    upstream_outputs: Mapping[str, Any],
) -> ResearchArtifact:
    keys = sorted(set(local_outputs) | set(upstream_outputs))
    mismatches = tuple(
        key for key in keys if local_outputs.get(key) != upstream_outputs.get(key)
    )
    disposition = (
        Disposition.PASS if not mismatches and bool(keys) else Disposition.REJECT
    )
    return artifact(
        "adapter-differential",
        {"case_count": len(keys), "mismatches": mismatches},
        disposition=disposition,
        reason="exact-match" if not mismatches and keys else "differential-mismatch",
    )


def publish_adapter_qualification(
    contract: ResearchArtifact,
    vectors: ResearchArtifact,
    differential: ResearchArtifact,
    *,
    version: str,
) -> ResearchArtifact:
    passed = all(
        item.disposition is Disposition.PASS
        for item in (contract, vectors, differential)
    )
    return artifact(
        "adapter-qualification",
        {
            "version": nonempty_text(version, "version"),
            "contract": contract.identity,
            "vectors": vectors.identity,
            "differential": differential.identity,
            "execution_authority": False,
        },
        disposition=Disposition.PASS if passed else Disposition.BLOCKED,
        reason="qualified-readonly-adapter" if passed else "conformance-incomplete",
    )


__all__ = [
    "build_golden_vector_pack",
    "define_adapter_conformance_contract",
    "publish_adapter_qualification",
    "run_adapter_differential_suite",
]
