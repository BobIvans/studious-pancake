from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, cast

import pytest

from src.config.chain_registry import (
    ASSOCIATED_TOKEN_PROGRAM_ADDRESS,
    BPF_UPGRADEABLE_LOADER_ADDRESS,
    COMPUTE_BUDGET_PROGRAM_ADDRESS,
    NATIVE_SOL_MINT_ADDRESS,
    SYSTEM_PROGRAM_ADDRESS,
    TOKEN_2022_PROGRAM_ADDRESS,
    TOKEN_PROGRAM_ADDRESS,
)
from src.providers.marginfi.deployment_conformance import (
    EXPECTED_MAIN_GROUP,
    EXPECTED_PROGRAM_ID,
    EXPECTED_VERIFIED_BUILD_HASH,
    PINNED_SOURCE_COMMIT,
    load_marginfi_deployment_manifest,
)
from src.providers.marginfi.protocol_conformance import (
    MarginfiAccountVector,
    MarginfiAccountVectorKind,
    MarginfiFlashloanMetaEvidence,
    MarginfiHumanReviewEvidence,
    MarginfiInstructionVector,
    MarginfiProtocolArtifact,
    MarginfiProtocolArtifactKind,
    MarginfiProtocolConformanceError,
    MarginfiProtocolConformanceEvidence,
    MarginfiReadonlyRpcEvidence,
    MarginfiRepaymentMathEvidence,
    MarginfiToken2022Evidence,
    assert_marginfi_protocol_conformance,
    evaluate_marginfi_protocol_conformance,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _artifact(kind: MarginfiProtocolArtifactKind) -> MarginfiProtocolArtifact:
    return MarginfiProtocolArtifact(
        path=f"evidence/marginfi/pr088/{kind.value}.json",
        sha256=_digest(f"artifact:{kind.value}"),
        kind=kind,
        produced_by="pr088-offline-evidence-builder",
    )


def _account_vector(
    kind: MarginfiAccountVectorKind,
    account_address: str,
    owner_program_id: str,
) -> MarginfiAccountVector:
    return MarginfiAccountVector(
        account_address=account_address,
        owner_program_id=owner_program_id,
        account_kind=kind,
        data_sha256=_digest(f"account:{kind.value}:data"),
        decoded_fields_sha256=_digest(f"account:{kind.value}:decoded"),
        slot=100,
        min_context_slot=99,
    )


def _instruction_vector(name: str) -> MarginfiInstructionVector:
    return MarginfiInstructionVector(
        instruction_name=name,
        program_id=EXPECTED_PROGRAM_ID,
        account_metas_sha256=_digest(f"instruction:{name}:metas"),
        data_sha256=_digest(f"instruction:{name}:data"),
        sdk_fixture_sha256=_digest(f"instruction:{name}:fixture"),
        account_count=4,
        writable_count=2,
        signer_count=1,
    )


def _complete_evidence() -> MarginfiProtocolConformanceEvidence:
    return MarginfiProtocolConformanceEvidence(
        source_commit=PINNED_SOURCE_COMMIT,
        verified_build_hash_sha256=EXPECTED_VERIFIED_BUILD_HASH,
        program_id=EXPECTED_PROGRAM_ID,
        main_group=EXPECTED_MAIN_GROUP,
        artifacts=tuple(_artifact(kind) for kind in MarginfiProtocolArtifactKind),
        account_vectors=(
            _account_vector(
                MarginfiAccountVectorKind.GROUP,
                EXPECTED_MAIN_GROUP,
                EXPECTED_PROGRAM_ID,
            ),
            _account_vector(
                MarginfiAccountVectorKind.BANK,
                COMPUTE_BUDGET_PROGRAM_ADDRESS,
                EXPECTED_PROGRAM_ID,
            ),
            _account_vector(
                MarginfiAccountVectorKind.MINT,
                NATIVE_SOL_MINT_ADDRESS,
                TOKEN_PROGRAM_ADDRESS,
            ),
            _account_vector(
                MarginfiAccountVectorKind.LIQUIDITY_VAULT,
                ASSOCIATED_TOKEN_PROGRAM_ADDRESS,
                TOKEN_PROGRAM_ADDRESS,
            ),
            _account_vector(
                MarginfiAccountVectorKind.ORACLE,
                BPF_UPGRADEABLE_LOADER_ADDRESS,
                SYSTEM_PROGRAM_ADDRESS,
            ),
            _account_vector(
                MarginfiAccountVectorKind.MARGIN_ACCOUNT,
                TOKEN_2022_PROGRAM_ADDRESS,
                EXPECTED_PROGRAM_ID,
            ),
        ),
        instruction_vectors=(
            _instruction_vector("lending_account_start_flashloan"),
            _instruction_vector("lending_account_borrow"),
            _instruction_vector("lending_account_repay"),
            _instruction_vector("lending_account_end_flashloan"),
        ),
        rpc_evidence=MarginfiReadonlyRpcEvidence(
            evidence_sha256=_digest("readonly-rpc-evidence"),
            min_context_slot=50,
            program_executable_verified=True,
            group_relationships_verified=True,
            bank_relationships_verified=True,
            oracle_relationships_verified=True,
            fee_pause_config_verified=True,
        ),
        flashloan_metas=MarginfiFlashloanMetaEvidence(
            start_end_index_bound=True,
            start_requires_instructions_sysvar=True,
            start_and_end_same_marginfi_account=True,
            signer_matches_marginfi_authority=True,
            borrow_repay_bank_order_verified=True,
            account_meta_order_verified=True,
            no_cpi_end_flashloan=True,
        ),
        token_2022=MarginfiToken2022Evidence(
            token_program_paths_verified=True,
            token_2022_program_paths_verified=True,
            mint_owner_matches_token_program=True,
            vault_owner_matches_token_program=True,
            token_2022_sample_count=1,
        ),
        repayment_math=MarginfiRepaymentMathEvidence(
            sample_count=2,
            max_liability_share_error_bps=1,
            max_repayment_error_bps=1,
            fee_model_verified=True,
            health_after_flashloan_verified=True,
        ),
        human_review=MarginfiHumanReviewEvidence(
            operator="automation",
            reviewer="human-reviewer",
            reviewed_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
            signed_by="release-operator",
            signature_reference="evidence/marginfi/pr088/signature.txt",
        ),
        official_sources=(
            "https://docs.marginfi.com/mfi-v2",
            "https://docs.marginfi.com/ts-sdk",
            "https://solana.com/docs/programs/verified-builds",
        ),
    )


def test_packaged_pr088_manifest_scaffold_is_fail_closed() -> None:
    manifest = load_marginfi_deployment_manifest()
    section = cast(dict[str, Any], manifest["protocol_conformance"])

    assert section["schema_version"] == "pr088.marginfi-protocol-conformance.v1"
    assert section["shadow_execution_capable"] is False
    assert section["live_allowed"] is False
    assert section["status"] == "blocked-missing-protocol-evidence"
    assert set(section["required_artifact_kinds"]) == {
        kind.value for kind in MarginfiProtocolArtifactKind
    }


def test_complete_protocol_evidence_is_shadow_capable_but_never_live() -> None:
    evaluation = assert_marginfi_protocol_conformance(_complete_evidence())

    assert evaluation.shadow_execution_capable is True
    assert evaluation.live_execution_allowed is False
    assert evaluation.state == "shadow-execution-capable"
    assert evaluation.blockers == ()
    assert evaluation.metrics_summary["instruction_vectors"] == 4


def test_missing_flashloan_meta_blocks_shadow_conformance() -> None:
    evidence = _complete_evidence()
    broken = replace(evidence.flashloan_metas, start_end_index_bound=False)

    evaluation = evaluate_marginfi_protocol_conformance(
        replace(evidence, flashloan_metas=broken)
    )

    assert evaluation.shadow_execution_capable is False
    assert "FLASHLOAN_END_INDEX_UNVERIFIED" in evaluation.blockers


def test_token_2022_path_must_be_verified() -> None:
    evidence = _complete_evidence()
    broken = replace(evidence.token_2022, token_2022_program_paths_verified=False)

    evaluation = evaluate_marginfi_protocol_conformance(
        replace(evidence, token_2022=broken)
    )

    assert evaluation.shadow_execution_capable is False
    assert "TOKEN_2022_PATHS_UNVERIFIED" in evaluation.blockers


def test_source_commit_and_verified_hash_are_pinned() -> None:
    evidence = replace(
        _complete_evidence(),
        source_commit="0" * 39 + "1",
        verified_build_hash_sha256=_digest("unexpected-hash"),
    )

    evaluation = evaluate_marginfi_protocol_conformance(evidence)

    assert evaluation.shadow_execution_capable is False
    assert "SOURCE_COMMIT_MISMATCH" in evaluation.blockers
    assert "VERIFIED_BUILD_HASH_MISMATCH" in evaluation.blockers


def test_placeholder_digest_is_rejected() -> None:
    with pytest.raises(
        MarginfiProtocolConformanceError,
        match="non-placeholder sha256 digest",
    ):
        MarginfiProtocolArtifact(
            path="evidence/marginfi/pr088/idl.json",
            sha256="1" * 64,
            kind=MarginfiProtocolArtifactKind.IDL,
            produced_by="fixture",
        )


def test_evaluation_dict_is_stable_json_serialisable() -> None:
    evaluation = assert_marginfi_protocol_conformance(_complete_evidence())

    encoded = json.dumps(evaluation.to_dict(), sort_keys=True)

    assert "shadow-execution-capable" in encoded
    assert EXPECTED_PROGRAM_ID in encoded
