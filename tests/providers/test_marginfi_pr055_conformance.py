from __future__ import annotations

from copy import deepcopy

import pytest

from src.providers.marginfi.deployment_conformance import (
    EXPECTED_MAIN_GROUP,
    EXPECTED_PROGRAM_ID,
    PINNED_SOURCE_COMMIT,
    MarginfiDeploymentConformanceError,
    assert_marginfi_execution_conformance,
    evaluate_marginfi_execution_conformance,
    load_marginfi_deployment_manifest,
)


def _complete_manifest() -> dict:
    raw = deepcopy(load_marginfi_deployment_manifest())
    full_hash = "26dda5e" + ("0" * 57)
    raw["deployment"]["deployed_program_hash_sha256"] = full_hash
    raw["deployment"]["reproducible_build_hash_sha256"] = full_hash
    raw["idl"]["sha256"] = "1" * 64
    raw["idl"]["canonical_program_metadata_verified"] = True
    raw["sdk_golden_vectors"]["account_vectors_sha256"] = "2" * 64
    raw["sdk_golden_vectors"]["instruction_vectors_sha256"] = "3" * 64
    raw["rpc_evidence"].update(
        {
            "sha256": "4" * 64,
            "min_context_slot": 1,
            "program_executable_verified": True,
            "group_relationships_verified": True,
            "bank_relationships_verified": True,
            "flashloan_metas_verified": True,
            "token_2022_paths_verified": True,
        }
    )
    raw["promotion"]["human_reviewed"] = True
    raw["promotion"]["execution_conformance_verified"] = True
    return raw


def test_packaged_manifest_is_authoritative_but_fail_closed() -> None:
    raw = load_marginfi_deployment_manifest()

    assert raw["program_id"] == EXPECTED_PROGRAM_ID
    assert raw["main_group"] == EXPECTED_MAIN_GROUP
    assert raw["source"]["source_commit"] == PINNED_SOURCE_COMMIT
    assert raw["source"]["repository_relation"] == "github-redirect-same-repository"

    report = evaluate_marginfi_execution_conformance(raw)

    assert report.execution_allowed is False
    assert "DEPLOYED_HASH_MISSING" in report.blockers
    assert "BUILD_HASH_MISSING" in report.blockers
    assert "CANONICAL_IDL_UNVERIFIED" in report.blockers
    assert "RPC_EVIDENCE_MISSING" in report.blockers
    assert "PROMOTION_FLAG_FALSE" in report.blockers


def test_complete_independent_evidence_is_required_for_promotion() -> None:
    report = assert_marginfi_execution_conformance(_complete_manifest())

    assert report.execution_allowed is True
    assert report.blockers == ()
    assert len(report.evidence_hash) == 64


def test_matching_prefix_without_matching_full_hash_is_rejected() -> None:
    raw = _complete_manifest()
    raw["deployment"]["reproducible_build_hash_sha256"] = "26dda5e" + ("f" * 57)

    report = evaluate_marginfi_execution_conformance(raw)

    assert report.execution_allowed is False
    assert "DEPLOYED_BUILD_HASH_MISMATCH" in report.blockers


def test_repository_alias_does_not_replace_resolved_identity() -> None:
    raw = _complete_manifest()
    raw["source"]["resolved_repository_url"] = raw["source"][
        "documented_repository_url"
    ]

    report = evaluate_marginfi_execution_conformance(raw)

    assert report.execution_allowed is False
    assert "SOURCE_REPOSITORY_MISMATCH" in report.blockers


def test_promotion_flag_alone_cannot_bypass_missing_evidence() -> None:
    raw = load_marginfi_deployment_manifest()
    raw["promotion"]["execution_conformance_verified"] = True
    raw["promotion"]["human_reviewed"] = True

    with pytest.raises(
        MarginfiDeploymentConformanceError,
        match="PR055_MARGINFI_EXECUTION_BLOCKED",
    ):
        assert_marginfi_execution_conformance(raw)
