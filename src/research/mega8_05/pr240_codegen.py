"""PR-240 / CODEGEN-01: deterministic signer-free adapter skeleton generation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .base import Disposition, ResearchArtifact, artifact, nonempty_text


def _names(values: Iterable[str], field: str) -> tuple[str, ...]:
    names = tuple(sorted({nonempty_text(value, field) for value in values}))
    for name in names:
        if not name.replace("_", "").isalnum() or name[0].isdigit():
            raise ValueError(f"{field} contains unsafe identifier: {name}")
    return names


def _generated(
    *,
    family: str,
    schema_sha256: str,
    members: Iterable[str],
) -> str:
    if len(schema_sha256) != 64:
        raise ValueError("schema_sha256 must be a 64-character digest")
    safe_members = _names(members, "member")
    lines = [
        '"""Generated read-only adapter skeleton. Do not add signing/submission."""',
        f'SCHEMA_SHA256 = "{schema_sha256}"',
        "READ_ONLY = True",
        "SIGNING_ALLOWED = False",
        "SUBMISSION_ALLOWED = False",
        f'FAMILY = "{family}"',
        f"MEMBERS = {safe_members!r}",
        "",
    ]
    return "\n".join(lines)


def generate_idl_account_decoder(
    schema_sha256: str,
    fields: Iterable[str],
) -> str:
    return _generated(family="solana-idl", schema_sha256=schema_sha256, members=fields)


def generate_abi_read_adapter(
    schema_sha256: str,
    methods: Iterable[str],
) -> str:
    return _generated(
        family="evm-abi-read", schema_sha256=schema_sha256, members=methods
    )


def generate_move_resource_decoder(
    schema_sha256: str,
    resources: Iterable[str],
) -> str:
    return _generated(
        family="move-resource", schema_sha256=schema_sha256, members=resources
    )


def validate_generated_adapter(
    generated_source: str,
    *,
    schema_sha256: str,
    golden_vectors: Iterable[Mapping[str, Any]],
) -> ResearchArtifact:
    source = nonempty_text(generated_source, "generated_source")
    vectors = tuple(golden_vectors)
    required_markers = (
        f'SCHEMA_SHA256 = "{schema_sha256}"',
        "READ_ONLY = True",
        "SIGNING_ALLOWED = False",
        "SUBMISSION_ALLOWED = False",
    )
    markers_ok = all(marker in source for marker in required_markers)
    vectors_ok = bool(vectors) and all(
        bool(vector.get("matched")) for vector in vectors
    )
    disposition = Disposition.PASS if markers_ok and vectors_ok else Disposition.BLOCKED
    reason = (
        "golden-vectors-match"
        if disposition is Disposition.PASS
        else "validation-incomplete"
    )
    return artifact(
        "generated-adapter-validation",
        {
            "schema_sha256": schema_sha256,
            "markers_ok": markers_ok,
            "vector_count": len(vectors),
            "vectors_ok": vectors_ok,
            "generated_code_executed": False,
        },
        disposition=disposition,
        reason=reason,
    )


__all__ = [
    "generate_abi_read_adapter",
    "generate_idl_account_decoder",
    "generate_move_resource_decoder",
    "validate_generated_adapter",
]
