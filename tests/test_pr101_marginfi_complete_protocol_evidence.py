from __future__ import annotations

from copy import deepcopy

import pytest

from src.providers.marginfi.complete_evidence import (
    MAXIMUM_SHADOW_CAPABILITY,
    SCHEMA_VERSION,
    MarginfiCompleteEvidenceError,
    assert_marginfi_complete_evidence,
    evaluate_marginfi_complete_evidence,
)
from src.providers.marginfi.deployment_conformance import (
    load_marginfi_deployment_manifest,
)

SHA_A = "0123456789abcdef" * 4
SHA_B = "abcdef0123456789" * 4
SHA_C = "00112233445566778899aabbccddeeff" * 2
SHA_D = "ffeeddccbbaa99887766554433221100" * 2
SHA_E = "1234567890abcdef" * 4
SHA_F = "fedcba0987654321" * 4
SHA_G = "13579bdf2468ace0" * 4
SHA_H = "02468ace13579bdf" * 4
SHA_I = "89abcdef01234567" * 4
SHA_J = "76543210fedcba98" * 4


def test_pr101_default_marginfi_manifest_remains_blocked_until_complete() -> None:
    result = evaluate_marginfi_complete_evidence(load_marginfi_deployment_manifest())

    assert result.state == "blocked"
    assert not result.complete
    assert not result.shadow_execution_capable
    assert not result.live_execution_allowed
    assert "DECISIVE_FIELD_MISSING:idl.sha256" in result.blockers
    assert "DECISIVE_FIELD_FALSE:promotion.human_reviewed" in result.blockers
    assert (
        "DECISIVE_FIELD_MISSING:complete_protocol_evidence.source_release_pin_sha256"
        in result.blockers
    )
    assert "MAXIMUM_CAPABILITY_NOT_SHADOW_EXECUTION_CAPABLE" in result.blockers


def test_pr101_complete_manifest_can_reach_shadow_but_never_live() -> None:
    result = evaluate_marginfi_complete_evidence(_complete_manifest())

    assert result.complete
    assert result.shadow_execution_capable
    assert not result.live_execution_allowed
    assert result.state == MAXIMUM_SHADOW_CAPABILITY
    assert result.blockers == ()


def test_pr101_live_true_blocks_even_with_complete_evidence() -> None:
    manifest = _complete_manifest()
    manifest["promotion"]["live_allowed"] = True
    manifest["protocol_conformance"]["live_allowed"] = True
    manifest["complete_protocol_evidence"]["live_allowed"] = True

    result = evaluate_marginfi_complete_evidence(manifest)

    assert not result.complete
    assert not result.live_execution_allowed
    assert "LIVE_DENIAL_VIOLATED:promotion.live_allowed" in result.blockers
    assert "LIVE_DENIAL_VIOLATED:protocol_conformance.live_allowed" in result.blockers
    assert (
        "LIVE_DENIAL_VIOLATED:complete_protocol_evidence.live_allowed"
        in result.blockers
    )


def test_pr101_assertion_uses_stable_fail_closed_prefix() -> None:
    with pytest.raises(MarginfiCompleteEvidenceError) as exc_info:
        assert_marginfi_complete_evidence(load_marginfi_deployment_manifest())

    assert str(exc_info.value).startswith("PR101_MARGINFI_COMPLETE_EVIDENCE_BLOCKED:")


def _complete_manifest() -> dict[str, object]:
    manifest = deepcopy(load_marginfi_deployment_manifest())
    manifest["idl"]["sha256"] = SHA_A
    manifest["idl"]["canonical_program_metadata_verified"] = True
    manifest["sdk_golden_vectors"]["account_vectors_sha256"] = SHA_B
    manifest["sdk_golden_vectors"]["instruction_vectors_sha256"] = SHA_C
    manifest["rpc_evidence"].update(
        {
            "sha256": SHA_D,
            "min_context_slot": 123456,
            "program_executable_verified": True,
            "group_relationships_verified": True,
            "bank_relationships_verified": True,
            "oracle_relationships_verified": True,
            "fee_pause_config_verified": True,
            "flashloan_metas_verified": True,
            "token_2022_paths_verified": True,
        }
    )
    manifest["protocol_conformance"].update(
        {
            "status": "shadow-execution-capable",
            "shadow_execution_capable": True,
            "live_allowed": False,
        }
    )
    manifest["promotion"].update(
        {
            "execution_conformance_verified": True,
            "human_reviewed": True,
            "live_allowed": False,
            "maximum_capability": MAXIMUM_SHADOW_CAPABILITY,
        }
    )
    manifest["complete_protocol_evidence"] = {
        "schema_version": SCHEMA_VERSION,
        "status": "shadow-execution-capable",
        "source_release_pin_sha256": SHA_E,
        "canonical_idl_layout_sha256": SHA_A,
        "account_vector_bundle_sha256": SHA_B,
        "instruction_vector_bundle_sha256": SHA_C,
        "flashloan_meta_vector_sha256": SHA_F,
        "token_2022_vector_sha256": SHA_G,
        "repayment_math_sha256": SHA_H,
        "deployment_metadata_provenance_sha256": SHA_I,
        "human_review_sha256": SHA_J,
        "signature_reference": "evidence/marginfi/pr101/review.sig",
        "min_context_slot": 123456,
        "full_idl_layout_verified": True,
        "source_sdk_vectors_verified": True,
        "flashloan_instruction_vectors_verified": True,
        "conservative_repayment_math_verified": True,
        "deployment_metadata_provenance_verified": True,
        "human_reviewed": True,
        "maximum_capability": MAXIMUM_SHADOW_CAPABILITY,
        "live_allowed": False,
    }
    return manifest
