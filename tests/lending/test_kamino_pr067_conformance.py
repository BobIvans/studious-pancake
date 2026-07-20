from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

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
    KaminoConformanceError,
    KaminoConformanceEvidence,
    KaminoHealthOracleMathEvidence,
    KaminoInstructionGoldenVector,
    KaminoPlannerReplayEvidence,
    KaminoRpcAccountVector,
    KaminoShadowSoakReference,
    evaluate_kamino_conformance,
)

USDC_MINT = "EPjFWdd5AufqSSqeM2qP52kZmxdr4WjGmrrSSJbptN5"
KLEND_PROGRAM = "SLendK7ySfcEzyaFqy93gDnD3RtrpXJcnRwb6zFHJSh"
CLOCK_SYSVAR = "SysvarC1ock11111111111111111111111111111111"
RENT_SYSVAR = "SysvarRent111111111111111111111111111111111"
GIT_SHA = "a" * 40


def _provenance() -> KaminoDeploymentProvenance:
    return KaminoDeploymentProvenance(
        source_url="https://github.com/Kamino-Finance/klend-sdk",
        sdk_package="@kamino-finance/klend-sdk",
        lending_program_id=KLEND_PROGRAM,
        idl_sha256="1" * 64,
        rpc_fixture_sha256="2" * 64,
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


def _artifact(
    kind: KaminoConformanceArtifactKind,
    marker: str,
) -> KaminoConformanceArtifact:
    return KaminoConformanceArtifact(
        path=f"evidence/pr067/{kind.value}.json",
        sha256=marker * 64,
        kind=kind,
    )


def _artifacts() -> tuple[KaminoConformanceArtifact, ...]:
    return (
        _artifact(KaminoConformanceArtifactKind.IDL, "1"),
        _artifact(KaminoConformanceArtifactKind.RPC_ACCOUNT_FIXTURES, "2"),
        _artifact(KaminoConformanceArtifactKind.INSTRUCTION_GOLDEN_VECTORS, "3"),
        _artifact(KaminoConformanceArtifactKind.HEALTH_ORACLE_REPORT, "4"),
        _artifact(KaminoConformanceArtifactKind.PLANNER_REPLAY, "5"),
        _artifact(KaminoConformanceArtifactKind.SHADOW_SOAK_REPORT, "6"),
        _artifact(KaminoConformanceArtifactKind.HUMAN_REVIEW, "7"),
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


def _evidence(
    *,
    combination: KaminoSupportedCombination | None = None,
) -> KaminoConformanceEvidence:
    return KaminoConformanceEvidence(
        combination=combination or _combination(),
        code_commit=GIT_SHA,
        artifacts=_artifacts(),
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
            run_id="pr060-shadow-soak-001",
            duration_seconds=MINIMUM_SHADOW_SOAK_SECONDS,
            evidence_sha256="5" * 64,
            passed=True,
            human_reviewed=True,
        ),
        operator="operator",
        reviewer="risk-reviewer",
        reviewed_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
        signed_by="release-manager",
        signature_reference="evidence/pr067/signature.txt",
    )


def test_passing_kamino_conformance_is_shadow_ready_but_never_live_allowed() -> None:
    result = evaluate_kamino_conformance(_evidence())

    assert result.conformance_ready is True
    assert result.live_execution_allowed is False
    assert result.state == "shadow-conformance-ready"
    assert result.blockers == ()
    assert result.metrics_summary["rpc_account_vectors"] == 5
    assert "GITHUB_SOURCE_PIN_REQUIRES_RELEASE_TAG_OR_COMMIT_REVIEW" in result.warnings


def test_unverified_combination_blocks_promotion() -> None:
    result = evaluate_kamino_conformance(
        _evidence(combination=_combination(verified=False))
    )

    assert result.conformance_ready is False
    assert "KAMINO_COMBINATION_NOT_VERIFIED" in result.blockers


def test_missing_vectors_and_owner_mismatch_fail_closed() -> None:
    broken_vectors = (
        _rpc_vector(
            SYSTEM_PROGRAM_ADDRESS,
            KaminoAccountVectorKind.MARKET,
            "8",
            owner=TOKEN_PROGRAM_ADDRESS,
        ),
        _rpc_vector(
            CLOCK_SYSVAR,
            KaminoAccountVectorKind.ORACLE,
            "c",
            owner=SYSTEM_PROGRAM_ADDRESS,
        ),
    )
    result = evaluate_kamino_conformance(
        replace(_evidence(), rpc_account_vectors=broken_vectors)
    )

    assert "INSUFFICIENT_RPC_GOLDEN_ACCOUNT_VECTORS" in result.blockers
    assert "REQUIRED_ACCOUNT_VECTOR_KINDS_MISSING" in result.blockers
    assert "KAMINO_ACCOUNT_OWNER_MISMATCH" in result.blockers
    assert "COLLATERAL_RESERVE_VECTOR_MISSING" in result.blockers


def test_instruction_vector_program_mismatch_blocks_promotion() -> None:
    bad_instruction = replace(
        _instruction_vectors()[0],
        program_id=TOKEN_PROGRAM_ADDRESS,
    )
    result = evaluate_kamino_conformance(
        replace(
            _evidence(),
            instruction_vectors=(bad_instruction, _instruction_vectors()[1]),
        )
    )

    assert result.conformance_ready is False
    assert "INSTRUCTION_PROGRAM_MISMATCH" in result.blockers


def test_short_or_unreviewed_shadow_soak_blocks_promotion() -> None:
    short_soak = KaminoShadowSoakReference(
        run_id="short",
        duration_seconds=60,
        evidence_sha256="6" * 64,
        passed=False,
        human_reviewed=False,
    )
    result = evaluate_kamino_conformance(replace(_evidence(), shadow_soak=short_soak))

    assert "SHADOW_SOAK_NOT_PASSED" in result.blockers
    assert "SHADOW_SOAK_DURATION_TOO_SHORT" in result.blockers
    assert "SHADOW_SOAK_NOT_HUMAN_REVIEWED" in result.blockers


def test_replay_and_health_math_mismatches_block_promotion() -> None:
    result = evaluate_kamino_conformance(
        replace(
            _evidence(),
            planner_replay=KaminoPlannerReplayEvidence(
                replay_cases=2,
                accepted_cases=1,
                rejected_cases=1,
                mismatch_count=1,
                deterministic_replay_passed=False,
                corpus_sha256="7" * 64,
            ),
            health_oracle_math=KaminoHealthOracleMathEvidence(
                sample_count=1,
                max_health_factor_error_bps=2,
                max_price_staleness_slots=11,
                liquidation_threshold_bps=8_000,
                oracle_sources=("pyth-mainnet",),
                passed=False,
            ),
        )
    )

    assert "PLANNER_REPLAY_MISMATCHES" in result.blockers
    assert "PLANNER_REPLAY_NOT_DETERMINISTIC" in result.blockers
    assert "HEALTH_ORACLE_MATH_NOT_PASSED" in result.blockers
    assert "HEALTH_FACTOR_ERROR_TOO_HIGH" in result.blockers
    assert "PRICE_STALENESS_TOO_HIGH" in result.blockers


def test_malformed_artifacts_and_clock_values_are_rejected() -> None:
    with pytest.raises(KaminoConformanceError, match="repository-relative path"):
        KaminoConformanceArtifact(
            path="/tmp/fixture.json",
            sha256="8" * 64,
            kind=KaminoConformanceArtifactKind.IDL,
        )

    with pytest.raises(KaminoConformanceError, match="non-placeholder"):
        KaminoConformanceArtifact(
            path="evidence/pr067/fixture.json",
            sha256="0" * 64,
            kind=KaminoConformanceArtifactKind.IDL,
        )

    with pytest.raises(KaminoConformanceError, match="timezone-aware"):
        replace(_evidence(), reviewed_at=datetime(2026, 7, 21))
