"""Fail-closed PR-055 MarginFi source and deployment conformance gate."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib import resources
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "pr055.marginfi-authoritative-conformance.v1"
RESOURCE_NAME = "marginfi_pr055.json"

EXPECTED_CLUSTER = "mainnet-beta"
EXPECTED_PROGRAM_ID = "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"
EXPECTED_MAIN_GROUP = "4qp6Fx6tnZkY5Wropq9wUYgtFxXKwE6viZxFHg3rdAG8"
DOCUMENTED_REPOSITORY_URL = "https://github.com/mrgnlabs/marginfi-v2"
RESOLVED_REPOSITORY_URL = "https://github.com/0dotxyz/marginfi-v2"
PINNED_SOURCE_COMMIT = "d4c70c84f8a9692405a2c32cbd7095bb1fe3f428"
REVIEWED_SOURCE_HEAD = "72c1680f119152d7d83972523d1706bc73e50cc9"
EXPECTED_SOURCE_HEAD_DELTA = (
    "SECURITY.md",
    "guides/ADMIN/DEPLOY_GUIDE.md",
)


class MarginfiDeploymentConformanceError(RuntimeError):
    """Raised when execution is requested without complete PR-055 evidence."""


@dataclass(frozen=True, slots=True)
class MarginfiConformanceReport:
    execution_allowed: bool
    blockers: tuple[str, ...]
    evidence_hash: str
    source_commit: str
    deployed_program_hash: str | None


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_lower_hex(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def load_marginfi_deployment_manifest(
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Load the PR-055 evidence manifest without promoting it."""

    try:
        if path is None:
            resource = resources.files("src.resources").joinpath(RESOURCE_NAME)
            text = resource.read_text(encoding="utf-8")
        else:
            text = Path(path).read_text(encoding="utf-8")
        raw = json.loads(text)
    except (FileNotFoundError, ModuleNotFoundError, OSError, json.JSONDecodeError) as exc:
        raise MarginfiDeploymentConformanceError(
            "PR055_MARGINFI_MANIFEST_MISSING_OR_MALFORMED"
        ) from exc
    if not isinstance(raw, dict):
        raise MarginfiDeploymentConformanceError(
            "PR055_MARGINFI_MANIFEST_ROOT_NOT_OBJECT"
        )
    return raw


def evaluate_marginfi_execution_conformance(
    manifest: Mapping[str, Any] | None = None,
) -> MarginfiConformanceReport:
    """Evaluate source, build, IDL, vector and RPC evidence.

    A local source pin or a matching hash prefix is never sufficient. Execution
    is admitted only when full reproducible-build and deployed-program hashes
    match and every independent evidence family is present.
    """

    raw = dict(manifest) if manifest is not None else load_marginfi_deployment_manifest()
    blockers: list[str] = []

    if raw.get("schema_version") != SCHEMA_VERSION:
        blockers.append("MANIFEST_SCHEMA_MISMATCH")
    if raw.get("cluster") != EXPECTED_CLUSTER:
        blockers.append("CLUSTER_MISMATCH")
    if raw.get("program_id") != EXPECTED_PROGRAM_ID:
        blockers.append("PROGRAM_ID_MISMATCH")
    if raw.get("main_group") != EXPECTED_MAIN_GROUP:
        blockers.append("MAIN_GROUP_MISMATCH")

    source = _mapping(raw.get("source"))
    aliases = source.get("repository_aliases")
    alias_set = set(aliases) if isinstance(aliases, list) else set()
    if DOCUMENTED_REPOSITORY_URL not in alias_set:
        blockers.append("DOCUMENTED_SOURCE_ALIAS_MISSING")
    if RESOLVED_REPOSITORY_URL not in alias_set:
        blockers.append("RESOLVED_SOURCE_ALIAS_MISSING")
    if source.get("resolved_repository_url") != RESOLVED_REPOSITORY_URL:
        blockers.append("SOURCE_REPOSITORY_MISMATCH")
    if source.get("source_commit") != PINNED_SOURCE_COMMIT:
        blockers.append("SOURCE_COMMIT_MISMATCH")
    if source.get("reviewed_source_head") != REVIEWED_SOURCE_HEAD:
        blockers.append("SOURCE_HEAD_MISMATCH")
    delta = source.get("source_head_delta")
    if not isinstance(delta, list) or tuple(sorted(delta)) != tuple(
        sorted(EXPECTED_SOURCE_HEAD_DELTA)
    ):
        blockers.append("SOURCE_DELTA_NOT_DOCS_ONLY")

    deployment = _mapping(raw.get("deployment"))
    hash_prefix = deployment.get("official_hash_prefix")
    deployed_hash_value = deployment.get("deployed_program_hash_sha256")
    build_hash_value = deployment.get("reproducible_build_hash_sha256")
    deployed_hash = deployed_hash_value if isinstance(deployed_hash_value, str) else None
    build_hash = build_hash_value if isinstance(build_hash_value, str) else None
    if not _is_lower_hex(deployed_hash, 64):
        blockers.append("DEPLOYED_HASH_MISSING")
    if not _is_lower_hex(build_hash, 64):
        blockers.append("BUILD_HASH_MISSING")
    if (
        deployed_hash is not None
        and build_hash is not None
        and _is_lower_hex(deployed_hash, 64)
        and _is_lower_hex(build_hash, 64)
    ):
        if deployed_hash != build_hash:
            blockers.append("DEPLOYED_BUILD_HASH_MISMATCH")
        if not isinstance(hash_prefix, str) or not deployed_hash.startswith(hash_prefix):
            blockers.append("DEPLOYED_HASH_PREFIX_MISMATCH")

    idl = _mapping(raw.get("idl"))
    if not _is_lower_hex(idl.get("sha256"), 64):
        blockers.append("IDL_HASH_MISSING")
    if idl.get("canonical_program_metadata_verified") is not True:
        blockers.append("CANONICAL_IDL_UNVERIFIED")

    vectors = _mapping(raw.get("sdk_golden_vectors"))
    if not _is_lower_hex(vectors.get("account_vectors_sha256"), 64):
        blockers.append("ACCOUNT_VECTORS_MISSING")
    if not _is_lower_hex(vectors.get("instruction_vectors_sha256"), 64):
        blockers.append("INSTRUCTION_VECTORS_MISSING")
    if vectors.get("generated_from_source_commit") != PINNED_SOURCE_COMMIT:
        blockers.append("VECTOR_SOURCE_COMMIT_MISMATCH")

    rpc = _mapping(raw.get("rpc_evidence"))
    if not _is_lower_hex(rpc.get("sha256"), 64):
        blockers.append("RPC_EVIDENCE_MISSING")
    if not isinstance(rpc.get("min_context_slot"), int) or rpc.get(
        "min_context_slot", 0
    ) <= 0:
        blockers.append("RPC_CONTEXT_SLOT_MISSING")
    if rpc.get("program_executable_verified") is not True:
        blockers.append("RPC_PROGRAM_UNVERIFIED")
    if rpc.get("group_relationships_verified") is not True:
        blockers.append("RPC_GROUP_RELATIONSHIPS_UNVERIFIED")
    if rpc.get("bank_relationships_verified") is not True:
        blockers.append("RPC_BANK_RELATIONSHIPS_UNVERIFIED")
    if rpc.get("flashloan_metas_verified") is not True:
        blockers.append("RPC_FLASHLOAN_METAS_UNVERIFIED")
    if rpc.get("token_2022_paths_verified") is not True:
        blockers.append("RPC_TOKEN_2022_UNVERIFIED")

    promotion = _mapping(raw.get("promotion"))
    if promotion.get("human_reviewed") is not True:
        blockers.append("HUMAN_REVIEW_MISSING")
    if promotion.get("execution_conformance_verified") is not True:
        blockers.append("PROMOTION_FLAG_FALSE")

    unique_blockers = tuple(dict.fromkeys(blockers))
    return MarginfiConformanceReport(
        execution_allowed=not unique_blockers,
        blockers=unique_blockers,
        evidence_hash=_canonical_hash(raw),
        source_commit=str(source.get("source_commit", "")),
        deployed_program_hash=(
            deployed_hash if _is_lower_hex(deployed_hash, 64) else None
        ),
    )


def assert_marginfi_execution_conformance(
    manifest: Mapping[str, Any] | None = None,
) -> MarginfiConformanceReport:
    """Return passing evidence or fail closed with stable blocker codes."""

    report = evaluate_marginfi_execution_conformance(manifest)
    if not report.execution_allowed:
        blockers = ",".join(report.blockers)
        raise MarginfiDeploymentConformanceError(
            f"PR055_MARGINFI_EXECUTION_BLOCKED:{blockers}"
        )
    return report
