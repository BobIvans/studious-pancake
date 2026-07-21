from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from src.config.chain_registry import (
    COMPUTE_BUDGET_PROGRAM_ADDRESS,
    NATIVE_SOL_MINT_ADDRESS,
    SYSTEM_PROGRAM_ADDRESS,
    TOKEN_2022_PROGRAM_ADDRESS,
    TOKEN_PROGRAM_ADDRESS,
)
from src.lending.kamino import KaminoDeploymentProvenance, KaminoSupportedCombination
from src.lending.kamino_conformance import (
    MINIMUM_SHADOW_SOAK_SECONDS,
    KaminoAccountVectorKind,
    KaminoConformanceArtifact,
    KaminoConformanceArtifactKind,
    KaminoConformanceEvidence,
    KaminoHealthOracleMathEvidence,
    KaminoInstructionGoldenVector,
    KaminoPlannerReplayEvidence,
    KaminoRpcAccountVector,
    KaminoShadowSoakReference,
)
from src.lending.kamino_real_conformance import (
    KAMINO_DEVELOPER_DOCS,
    KLEND_SDK_PACKAGE,
    KLEND_SDK_REPOSITORY,
    KLEND_SOURCE_REPOSITORY,
    REQUIRED_EVIDENCE_ROOT,
    KaminoRealArtifact,
    KaminoRealArtifactKind,
    KaminoRealConformanceError,
    KaminoRealConformancePackage,
    KaminoRealMathEvidence,
    KaminoRealReviewEvidence,
    KaminoRealRpcEvidence,
    KaminoRealShadowSoakEvidence,
    KaminoRealSourcePins,
    assert_kamino_real_conformance,
    check_pr095_materialized_artifacts,
    evaluate_kamino_real_conformance,
)

USDC_MINT = "EPjFWdd5AufqSSqeM2qP52kZmxdr4WjGmrrSSJbptN5"
KLEND_PROGRAM = "SLendK7ySfcEzyaFqy93gDnD3RtrpXJcnRwb6zFHJSh"
CLOCK_SYSVAR = "SysvarC1ock11111111111111111111111111111111"
RENT_SYSVAR = "SysvarRent111111111111111111111111111111111"
REVIEWED_AT = datetime(2026, 7, 21, tzinfo=timezone.utc)
IDL_SHA = hashlib.sha256(b"klend-idl").hexdigest()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _git(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def _provenance() -> KaminoDeploymentProvenance:
    return KaminoDeploymentProvenance(
        source_url=KLEND_SDK_REPOSITORY,
        sdk_package=KLEND_SDK_PACKAGE,
        lending_program_id=KLEND_PROGRAM,
        idl_sha256=IDL_SHA,
        rpc_fixture_sha256=_digest("klend-rpc-fixture"),
        deployment_slot=123,
        reviewed_at="2026-07-21",
    ).validated()


def _combination(*, verified: bool = True) -> KaminoSupportedCombination:
    return KaminoSupportedCombination(
        combination_id="mainnet-sol-usdc",
        cluster="mainnet-beta",
        lending_program_id=KLEND_PROGRAM,
        market_address=SYSTEM_PROGRAM_ADDRESS,
        collateral_mint=NATIVE_SOL_MINT_ADDRESS,
        debt_mint=USDC_MINT,
        collateral_reserve=TOKEN_PROGRAM_ADDRESS,
        debt_reserve=TOKEN_2022_PROGRAM_ADDRESS,
        collateral_oracle=CLOCK_SYSVAR,
        debt_oracle=RENT_SYSVAR,
        liquidation_bonus_bps=500,
        protocol_fee_bps=25,
        flash_loan_fee_bps=9,
        min_net_profit_lamports=100_000,
        writable_accounts=(
            SYSTEM_PROGRAM_ADDRESS,
            TOKEN_PROGRAM_ADDRESS,
            TOKEN_2022_PROGRAM_ADDRESS,
            COMPUTE_BUDGET_PROGRAM_ADDRESS,
        ),
        provenance=_provenance(),
        verified=verified,
    ).validated()


def _pr067_artifact(
    kind: KaminoConformanceArtifactKind,
    marker: str,
) -> KaminoConformanceArtifact:
    return KaminoConformanceArtifact(
        path=f"evidence/pr067/{kind.value}.json",
        sha256=marker * 64,
        kind=kind,
    )


def _pr067_artifacts() -> tuple[KaminoConformanceArtifact, ...]:
    return tuple(
        _pr067_artifact(kind, marker)
        for kind, marker in zip(
            KaminoConformanceArtifactKind,
            ("1", "2", "3", "4", "5", "6", "7"),
            strict=True,
        )
    )


def _rpc_vector(
    account_address: str,
    kind: KaminoAccountVectorKind,
    marker: str,
    *,
    owner: str = KLEND_PROGRAM,
) -> KaminoRpcAccountVector:
    return KaminoRpcAccountVector(
        account_address=account_address,
        owner_program_id=owner,
        account_kind=kind,
        data_sha256=marker * 64,
        decoded_fields_sha256=marker.upper().lower() * 64,
        slot=100,
    )


def _rpc_vectors() -> tuple[KaminoRpcAccountVector, ...]:
    return (
        _rpc_vector(SYSTEM_PROGRAM_ADDRESS, KaminoAccountVectorKind.MARKET, "8"),
        _rpc_vector(TOKEN_PROGRAM_ADDRESS, KaminoAccountVectorKind.RESERVE, "9"),
        _rpc_vector(TOKEN_2022_PROGRAM_ADDRESS, KaminoAccountVectorKind.RESERVE, "a"),
        _rpc_vector(
            COMPUTE_BUDGET_PROGRAM_ADDRESS,
            KaminoAccountVectorKind.OBLIGATION,
            "b",
        ),
        _rpc_vector(
            CLOCK_SYSVAR,
            KaminoAccountVectorKind.ORACLE,
            "c",
            owner=SYSTEM_PROGRAM_ADDRESS,
        ),
    )


def _instruction_vectors() -> tuple[KaminoInstructionGoldenVector, ...]:
    return (
        KaminoInstructionGoldenVector(
            instruction_name="refresh_obligation",
            program_id=KLEND_PROGRAM,
            account_metas_sha256="d" * 64,
            data_sha256="e" * 64,
            account_count=8,
            writable_count=3,
            signer_count=0,
            sdk_fixture_sha256="f" * 64,
        ),
        KaminoInstructionGoldenVector(
            instruction_name="liquidate_obligation_and_redeem_reserve_collateral",
            program_id=KLEND_PROGRAM,
            account_metas_sha256="1" * 64,
            data_sha256="2" * 64,
            account_count=14,
            writable_count=8,
            signer_count=1,
            sdk_fixture_sha256="3" * 64,
        ),
    )


def _base_conformance(
    *,
    combination: KaminoSupportedCombination | None = None,
) -> KaminoConformanceEvidence:
    return KaminoConformanceEvidence(
        combination=combination or _combination(),
        code_commit=_git("pr067-code"),
        artifacts=_pr067_artifacts(),
        rpc_account_vectors=_rpc_vectors(),
        instruction_vectors=_instruction_vectors(),
        health_oracle_math=KaminoHealthOracleMathEvidence(
            sample_count=12,
            max_health_factor_error_bps=1,
            max_price_staleness_slots=2,
            liquidation_threshold_bps=8_000,
            oracle_sources=("pyth-mainnet", "switchboard-mainnet"),
            passed=True,
        ),
        planner_replay=KaminoPlannerReplayEvidence(
            replay_cases=10,
            accepted_cases=3,
            rejected_cases=7,
            mismatch_count=0,
            deterministic_replay_passed=True,
            corpus_sha256="4" * 64,
        ),
        shadow_soak=KaminoShadowSoakReference(
            run_id="pr095-shadow-soak-001",
            duration_seconds=MINIMUM_SHADOW_SOAK_SECONDS,
            evidence_sha256="5" * 64,
            passed=True,
            human_reviewed=True,
        ),
        operator="operator",
        reviewer="risk-reviewer",
        reviewed_at=REVIEWED_AT,
        signed_by="release-manager",
        signature_reference="evidence/pr067/signature.txt",
    )


def _source_pins() -> KaminoRealSourcePins:
    return KaminoRealSourcePins(
        klend_repository_url=KLEND_SOURCE_REPOSITORY,
        klend_commit=_git("klend-source"),
        klend_sdk_repository_url=KLEND_SDK_REPOSITORY,
        klend_sdk_commit=_git("klend-sdk-source"),
        sdk_package=KLEND_SDK_PACKAGE,
        sdk_version="5.1.11",
        developer_docs_url=KAMINO_DEVELOPER_DOCS,
        reviewed_at=REVIEWED_AT,
    )


def _real_artifact(kind: KaminoRealArtifactKind) -> KaminoRealArtifact:
    return KaminoRealArtifact(
        path=f"{REQUIRED_EVIDENCE_ROOT}/{kind.value}.json",
        sha256=_digest(kind.value),
        kind=kind,
        produced_by="pr095-evidence-builder",
    )


def _real_artifacts() -> tuple[KaminoRealArtifact, ...]:
    return tuple(_real_artifact(kind) for kind in KaminoRealArtifactKind)


def _package(
    *,
    base_conformance: KaminoConformanceEvidence | None = None,
) -> KaminoRealConformancePackage:
    return KaminoRealConformancePackage(
        source_pins=_source_pins(),
        base_conformance=base_conformance or _base_conformance(),
        artifacts=_real_artifacts(),
        deployment_program_hash_sha256=_digest("deployment-program"),
        idl_sha256=IDL_SHA,
        sdk_account_vectors_sha256=_digest("sdk-account-vectors"),
        sdk_instruction_vectors_sha256=_digest("sdk-instruction-vectors"),
        rpc_evidence=KaminoRealRpcEvidence(
            market_vector_sha256=_digest("rpc-market"),
            reserve_vector_sha256=_digest("rpc-reserves"),
            obligation_vector_sha256=_digest("rpc-obligations"),
            oracle_vector_sha256=_digest("rpc-oracles"),
            read_only_rpc_bundle_sha256=_digest("rpc-bundle"),
            min_context_slot=100,
            market_count=1,
            reserve_count=2,
            obligation_count=1,
            oracle_count=1,
        ),
        math_evidence=KaminoRealMathEvidence(
            oracle_health_fee_sha256=_digest("oracle-health-fee"),
            common_kernel_sha256=_digest("common-kernel"),
            sample_count=3,
            max_health_error_bps=1,
            max_fee_error_bps=1,
            borrow_flashloan_path_verified=True,
            liquidation_path_verified=True,
            no_live_authority=True,
        ),
        shadow_soak=KaminoRealShadowSoakEvidence(
            run_id="pr095-kamino-soak-001",
            duration_seconds=MINIMUM_SHADOW_SOAK_SECONDS,
            evidence_sha256=_digest("shadow-soak"),
            replay_corpus_sha256=_digest("replay-corpus"),
            deterministic_replay_passed=True,
            human_reviewed=True,
        ),
        review=KaminoRealReviewEvidence(
            operator="operator",
            reviewer="human-reviewer",
            reviewed_at=REVIEWED_AT,
            signed_by="release-manager",
            signature_reference=f"{REQUIRED_EVIDENCE_ROOT}/signature.txt",
        ),
    )


def test_complete_real_conformance_is_shadow_review_ready_but_never_live() -> None:
    result = assert_kamino_real_conformance(_package())

    assert result.ready_for_shadow_review is True
    assert result.live_execution_allowed is False
    assert result.state == "ready-for-shadow-review"
    assert result.blockers == ()
    assert result.metrics_summary["reserve_count"] == 2


def test_unready_pr067_base_conformance_blocks_pr095() -> None:
    base = _base_conformance(combination=_combination(verified=False))
    result = evaluate_kamino_real_conformance(_package(base_conformance=base))

    assert result.ready_for_shadow_review is False
    assert "PR067_BASE_CONFORMANCE_NOT_READY" in result.blockers
    assert "PR067:KAMINO_COMBINATION_NOT_VERIFIED" in result.blockers


def test_hash_and_vector_collapse_blocks_review() -> None:
    package = replace(
        _package(),
        deployment_program_hash_sha256=IDL_SHA,
        sdk_instruction_vectors_sha256=_digest("sdk-account-vectors"),
    )
    result = evaluate_kamino_real_conformance(package)

    assert "DEPLOYMENT_HASH_MUST_BE_DISTINCT_FROM_IDL_HASH" in result.blockers
    assert "SDK_ACCOUNT_AND_INSTRUCTION_VECTORS_COLLAPSED" in result.blockers


def test_rpc_math_and_soak_fail_closed() -> None:
    package = replace(
        _package(),
        rpc_evidence=replace(_package().rpc_evidence, reserve_count=1),
        math_evidence=replace(
            _package().math_evidence,
            borrow_flashloan_path_verified=False,
            max_health_error_bps=2,
        ),
        shadow_soak=replace(
            _package().shadow_soak,
            duration_seconds=60,
            deterministic_replay_passed=False,
            human_reviewed=False,
        ),
    )
    result = evaluate_kamino_real_conformance(package)

    assert "RPC_RESERVE_VECTORS_MISSING" in result.blockers
    assert "BORROW_FLASHLOAN_PATH_UNVERIFIED" in result.blockers
    assert "HEALTH_ERROR_TOO_HIGH" in result.blockers
    assert "SOAK_TOO_SHORT" in result.blockers
    assert "SOAK_REPLAY_NOT_DETERMINISTIC" in result.blockers
    assert "SOAK_NOT_HUMAN_REVIEWED" in result.blockers


def test_materialized_artifacts_are_hash_checked(tmp_path: Path) -> None:
    package = _package()
    for artifact in package.artifacts:
        path = tmp_path / artifact.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(artifact.kind.value, encoding="utf-8")

    assert check_pr095_materialized_artifacts(package, repository_root=tmp_path) == ()

    broken = tmp_path / package.artifacts[0].path
    broken.write_text("tampered", encoding="utf-8")

    blockers = check_pr095_materialized_artifacts(package, repository_root=tmp_path)
    assert any(reason.startswith("ARTIFACT_HASH_MISMATCH") for reason in blockers)


def test_source_pins_reject_wrong_sources_and_placeholder_commits() -> None:
    with pytest.raises(KaminoRealConformanceError, match="must be"):
        KaminoRealSourcePins(
            klend_repository_url="https://github.com/other/klend",
            klend_commit=_git("klend-source"),
            klend_sdk_repository_url=KLEND_SDK_REPOSITORY,
            klend_sdk_commit=_git("klend-sdk-source"),
            sdk_package=KLEND_SDK_PACKAGE,
            sdk_version="5.1.11",
            developer_docs_url=KAMINO_DEVELOPER_DOCS,
            reviewed_at=REVIEWED_AT,
        )

    with pytest.raises(KaminoRealConformanceError, match="non-placeholder"):
        replace(_source_pins(), klend_commit="a" * 40)


def test_artifact_paths_and_digests_reject_tmp_fixtures() -> None:
    with pytest.raises(KaminoRealConformanceError, match="under evidence/kamino/pr095"):
        KaminoRealArtifact(
            path="/tmp/kamino.json",
            sha256=_digest("artifact"),
            kind=KaminoRealArtifactKind.IDL,
            produced_by="fixture",
        )

    with pytest.raises(KaminoRealConformanceError, match="non-placeholder"):
        KaminoRealArtifact(
            path=f"{REQUIRED_EVIDENCE_ROOT}/idl.json",
            sha256="1" * 64,
            kind=KaminoRealArtifactKind.IDL,
            produced_by="fixture",
        )


def test_evaluation_dict_is_stable_json_serialisable() -> None:
    result = assert_kamino_real_conformance(_package())

    encoded = json.dumps(result.to_dict(), sort_keys=True)

    assert "ready-for-shadow-review" in encoded
    assert "mainnet-sol-usdc" in encoded
