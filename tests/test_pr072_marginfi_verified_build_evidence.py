from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from src.providers.marginfi.deployment_conformance import (
    EXPECTED_VERIFIED_BUILD_HASH,
    PINNED_SOURCE_COMMIT,
    evaluate_marginfi_execution_conformance,
    load_marginfi_deployment_manifest,
)


_OTHER_HASH = "1" * 64
_IDL_HASH = "2" * 64
_ACCOUNT_VECTOR_HASH = "3" * 64
_INSTRUCTION_VECTOR_HASH = "4" * 64
_RPC_EVIDENCE_HASH = "5" * 64


def _section(manifest: dict[str, Any], name: str) -> dict[str, Any]:
    return cast(dict[str, Any], manifest[name])


def _shadow_capable_manifest() -> dict[str, Any]:
    manifest = deepcopy(load_marginfi_deployment_manifest())
    _section(manifest, "idl")["sha256"] = _IDL_HASH
    _section(manifest, "idl")["canonical_program_metadata_verified"] = True
    _section(manifest, "sdk_golden_vectors")["account_vectors_sha256"] = (
        _ACCOUNT_VECTOR_HASH
    )
    _section(manifest, "sdk_golden_vectors")["instruction_vectors_sha256"] = (
        _INSTRUCTION_VECTOR_HASH
    )
    _section(manifest, "rpc_evidence")["sha256"] = _RPC_EVIDENCE_HASH
    _section(manifest, "rpc_evidence")["min_context_slot"] = 1
    _section(manifest, "rpc_evidence")["program_executable_verified"] = True
    _section(manifest, "rpc_evidence")["group_relationships_verified"] = True
    _section(manifest, "rpc_evidence")["bank_relationships_verified"] = True
    _section(manifest, "rpc_evidence")["flashloan_metas_verified"] = True
    _section(manifest, "rpc_evidence")["token_2022_paths_verified"] = True
    _section(manifest, "promotion")["execution_conformance_verified"] = True
    _section(manifest, "promotion")["human_reviewed"] = True
    return manifest


def test_pr072_records_verified_build_hash_without_live_promotion() -> None:
    manifest = load_marginfi_deployment_manifest()
    source = _section(manifest, "source")
    deployment = _section(manifest, "deployment")
    promotion = _section(manifest, "promotion")

    assert source["source_commit"] == PINNED_SOURCE_COMMIT
    assert deployment["expected_verified_build_hash_sha256"] == (
        EXPECTED_VERIFIED_BUILD_HASH
    )
    assert deployment["deployed_program_hash_sha256"] == EXPECTED_VERIFIED_BUILD_HASH
    assert deployment["reproducible_build_hash_sha256"] == (
        EXPECTED_VERIFIED_BUILD_HASH
    )
    assert promotion["live_allowed"] is False

    report = evaluate_marginfi_execution_conformance(manifest)
    assert report.execution_allowed is False
    assert report.deployed_program_hash == EXPECTED_VERIFIED_BUILD_HASH
    assert "DEPLOYED_HASH_MISSING" not in report.blockers
    assert "BUILD_HASH_MISSING" not in report.blockers
    assert "DEPLOYED_BUILD_HASH_MISMATCH" not in report.blockers
    assert "IDL_HASH_MISSING" in report.blockers
    assert "RPC_EVIDENCE_MISSING" in report.blockers
    assert "HUMAN_REVIEW_MISSING" in report.blockers
    assert "PROMOTION_FLAG_FALSE" in report.blockers


def test_pr072_expected_verified_build_hash_is_enforced() -> None:
    manifest = _shadow_capable_manifest()
    _section(manifest, "deployment")["deployed_program_hash_sha256"] = _OTHER_HASH

    report = evaluate_marginfi_execution_conformance(manifest)

    assert report.execution_allowed is False
    assert "DEPLOYED_BUILD_HASH_MISMATCH" in report.blockers
    assert "DEPLOYED_HASH_UNEXPECTED" in report.blockers


def test_pr072_complete_evidence_can_be_shadow_capable_without_live() -> None:
    manifest = _shadow_capable_manifest()

    report = evaluate_marginfi_execution_conformance(manifest)

    assert report.execution_allowed is True
    assert _section(manifest, "promotion")["live_allowed"] is False
