from __future__ import annotations

from pathlib import Path

import pytest

from src.config.runtime import load_runtime_config
from src.execution.financing_evidence import (
    FinalizedFinancingEvidence,
    FinancingRepaymentEvidence,
    validate_financing_repayment,
)
from src.lending.financing import (
    FinancingContractError,
    FinancingEvidence,
    FinancingObligation,
    FinancingRole,
    validate_financing_binding,
)
from src.runtime.core_v1_composition import build_core_v1_composition
from src.runtime.core_v1_materializer import (
    CORE_V1_BLOCKED_EXTERNAL,
    CORE_V1_PROFILE_ID,
    CoreV1ReleaseProfile,
)

SHA_A = "a" * 64
SHA_B = "b" * 64


def _financing_evidence(
    lender: str = "jupiter-lend", generation: int = 2
) -> FinancingEvidence:
    return FinancingEvidence(
        lender_id=lender,
        program_id="program",
        deployment_generation=generation,
        evidence_sha256=SHA_A,
        decoder_identity=f"{lender}-decoder-v1",
        decoder_generation=1,
    )


def test_financing_obligation_is_exact_lender_and_generation_bound() -> None:
    evidence = _financing_evidence()
    obligation = FinancingObligation(
        obligation_id="primary-1",
        role=FinancingRole.PRIMARY,
        lender_id=evidence.lender_id,
        program_id=evidence.program_id,
        deployment_generation=evidence.deployment_generation,
        asset_id="spl:USDC:6",
        principal_base_units=1_000_000,
        required_repayment_base_units=1_000_500,
        evidence_sha256=evidence.evidence_sha256,
        repayment_destination="reserve",
        instruction_constraints_sha256=SHA_B,
    )
    assert validate_financing_binding(
        lender_id="jupiter-lend",
        deployment_generation=2,
        evidence=evidence,
        obligations=(obligation,),
    ) == (obligation,)


def test_wrong_lender_and_stale_generation_are_rejected() -> None:
    evidence = _financing_evidence()
    with pytest.raises(FinancingContractError, match="LENDER_MISMATCH"):
        validate_financing_binding(
            lender_id="slumlord", deployment_generation=2, evidence=evidence
        )
    with pytest.raises(FinancingContractError, match="GENERATION_MISMATCH"):
        validate_financing_binding(
            lender_id="jupiter-lend", deployment_generation=3, evidence=evidence
        )


def test_legacy_profile_identity_cannot_be_relabelled() -> None:
    config = load_runtime_config(cli_overrides={"runtime.mode": "paper"})
    with pytest.raises(ValueError, match="LEGACY_PROFILE_LENDER_MISMATCH"):
        CoreV1ReleaseProfile(
            profile_id=CORE_V1_PROFILE_ID,
            strategy="circular_arbitrage",
            lender="jupiter-lend",
            router="jupiter",
            cluster=config.cluster.name,
            genesis_hash=config.cluster.genesis_hash,
            transport="rpc",
        )


def test_new_lender_profile_reuses_authority_but_has_no_marginfi_planner(
    tmp_path: Path,
) -> None:
    config = load_runtime_config(cli_overrides={"runtime.mode": "paper"})
    profile = CoreV1ReleaseProfile(
        profile_id="core-jupiter-lend-jupiter-v1",
        strategy="circular_arbitrage",
        lender="jupiter-lend",
        router="jupiter",
        cluster=config.cluster.name,
        genesis_hash=config.cluster.genesis_hash,
        transport="rpc",
        profile_generation=2,
    )
    composition = build_core_v1_composition(
        config,
        db_path=tmp_path / "generic.sqlite3",
        profile=profile,
        dependencies=None,
    )
    try:
        assert composition.admitted is False
        assert composition.blockers == (CORE_V1_BLOCKED_EXTERNAL,)
        assert composition.planner is None
        assert composition.capital.store is composition.authority.lifecycle
    finally:
        composition.close()


class _Validator:
    lender_id = "jupiter-lend"
    deployment_generation = 2
    decoder_identity = "jupiter-lend-decoder-v1"

    def validate(self, evidence: FinancingRepaymentEvidence) -> bool:
        return (
            evidence.debt_after_base_units == 0
            and evidence.observed_repayment_base_units
            >= evidence.required_repayment_base_units
        )


def _repayment() -> FinancingRepaymentEvidence:
    return FinancingRepaymentEvidence(
        lender_id="jupiter-lend",
        program_id="program",
        deployment_generation=2,
        decoder_identity="jupiter-lend-decoder-v1",
        obligation_digest=SHA_A,
        source_evidence_sha256=SHA_B,
        asset_id="spl:USDC:6",
        debt_before_base_units=100,
        debt_after_base_units=0,
        required_repayment_base_units=101,
        observed_repayment_base_units=101,
    )


def test_generic_repayment_requires_exact_decoder() -> None:
    decision = validate_financing_repayment(_repayment(), ())
    assert decision.proven is False
    assert decision.reason == "FINANCING_DECODER_REQUIRED"


def test_protocol_decoder_can_prove_and_bind_finalized_evidence() -> None:
    decision = validate_financing_repayment(_repayment(), (_Validator(),))
    assert decision.proven is True
    finalized = FinalizedFinancingEvidence(
        attempt_id="attempt-1",
        attempt_generation=1,
        message_hash=SHA_A,
        finalized_slot=123,
        repayment=decision,
    )
    assert len(finalized.digest) == 64
