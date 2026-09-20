from __future__ import annotations

from src.liquidation.mpr2619_qualification import (
    Blocker,
    FirewallPolicy,
    InstructionDescriptor,
    LiquidationCapabilityEvidence,
    LiquidationMode,
    QualificationVerdict,
    SimulationRawProof,
    qualify_liquidation_capability,
    validate_instruction_firewall,
    verify_raw_simulation_proof,
)


def _capability(**overrides: object) -> LiquidationCapabilityEvidence:
    values: dict[str, object] = {
        "mode": LiquidationMode.MARGINFI_CLASSIC,
        "fixture_only_quarantine": True,
        "exact_abi_proven": False,
        "financing_qualified": False,
        "unwind_qualified": False,
        "final_simulation_decoder_proven": False,
        "economic_ledger_proven": False,
        "circuit_breaker_state_proven": False,
        "source_commit": "a" * 40,
        "deployment_generation": "marginfi-mainnet-generation-unknown",
        "evidence_hash": "b" * 64,
    }
    values.update(overrides)
    return LiquidationCapabilityEvidence(**values)  # type: ignore[arg-type]


def test_mpr2619_fixture_only_liquidation_cannot_be_enabled_by_config() -> None:
    decision = qualify_liquidation_capability(_capability())

    assert decision.verdict is QualificationVerdict.BLOCKED
    assert Blocker.FIXTURE_ONLY_QUARANTINE in decision.blockers
    assert Blocker.EXACT_ABI_UNPROVEN in decision.blockers
    assert Blocker.FINAL_SIMULATION_DECODER_UNPROVEN in decision.blockers


def test_mpr2619_only_marginfi_classic_can_reach_this_qualification_boundary() -> None:
    decision = qualify_liquidation_capability(
        _capability(mode=LiquidationMode.KAMINO, fixture_only_quarantine=False)
    )

    assert decision.verdict is QualificationVerdict.BLOCKED
    assert Blocker.UNSUPPORTED_LIQUIDATION_MODE in decision.blockers


def test_mpr2619_all_offline_evidence_can_close_only_this_boundary() -> None:
    decision = qualify_liquidation_capability(
        _capability(
            fixture_only_quarantine=False,
            exact_abi_proven=True,
            financing_qualified=True,
            unwind_qualified=True,
            final_simulation_decoder_proven=True,
            economic_ledger_proven=True,
            circuit_breaker_state_proven=True,
        )
    )

    assert decision.verdict is QualificationVerdict.VERIFIED_OFFLINE
    assert decision.blockers == ()
    assert len(decision.decision_hash) == 64


def test_mpr2619_legacy_placeholder_plan_is_rejected_by_firewall() -> None:
    blockers = validate_instruction_firewall(
        (
            InstructionDescriptor(
                "marginfi_flashloan_provider_pr009",
                "start_flashloan",
                "end_index:5",
            ),
            InstructionDescriptor("route", "unwind", "01"),
        ),
        FirewallPolicy(
            allowed_program_ids=frozenset({"qualified-lender", "qualified-unwind"}),
            allowed_instruction_names=frozenset({"borrow", "repay", "swap"}),
        ),
    )

    assert Blocker.LEGACY_PLACEHOLDER_INSTRUCTION in blockers
    assert Blocker.UNEXPECTED_PROGRAM in blockers
    assert Blocker.UNEXPECTED_INSTRUCTION in blockers


def test_mpr2619_firewall_accepts_only_explicitly_qualified_programs_and_names() -> None:
    blockers = validate_instruction_firewall(
        (
            InstructionDescriptor("marginfi-program", "start_liquidation"),
            InstructionDescriptor("marginfi-program", "liquidate"),
            InstructionDescriptor("jupiter-program", "swap"),
            InstructionDescriptor("lender-program", "repay"),
            InstructionDescriptor("marginfi-program", "end_liquidation"),
        ),
        FirewallPolicy(
            allowed_program_ids=frozenset(
                {"marginfi-program", "jupiter-program", "lender-program"}
            ),
            allowed_instruction_names=frozenset(
                {"start_liquidation", "liquidate", "swap", "repay", "end_liquidation"}
            ),
        ),
    )

    assert blockers == ()


def test_mpr2619_caller_claims_without_raw_state_cannot_qualify() -> None:
    decision = verify_raw_simulation_proof(
        SimulationRawProof(
            raw_simulation_hash="",
            returned_accounts_hash="",
            simulation_slot=123,
            target_debt_delta=None,
            target_collateral_delta=None,
            flash_principal=100,
            flash_fee=1,
            flash_repayment_observed=101,
            economics_complete=True,
            realized_pnl_atomic_units=10,
        )
    )

    assert decision.accepted is False
    assert Blocker.RAW_SIMULATION_EVIDENCE_REQUIRED in decision.blockers
    assert Blocker.TARGET_STATE_CHANGE_UNPROVEN in decision.blockers


def test_mpr2619_flash_repayment_includes_actual_qualified_fee() -> None:
    decision = verify_raw_simulation_proof(
        SimulationRawProof(
            raw_simulation_hash="c" * 64,
            returned_accounts_hash="d" * 64,
            simulation_slot=123,
            target_debt_delta=-100,
            target_collateral_delta=-120,
            flash_principal=100,
            flash_fee=2,
            flash_repayment_observed=100,
            economics_complete=True,
            realized_pnl_atomic_units=5,
        )
    )

    assert decision.accepted is False
    assert Blocker.FLASH_REPAYMENT_UNPROVEN in decision.blockers


def test_mpr2619_simulation_success_requires_positive_complete_realized_economics() -> None:
    decision = verify_raw_simulation_proof(
        SimulationRawProof(
            raw_simulation_hash="c" * 64,
            returned_accounts_hash="d" * 64,
            simulation_slot=123,
            target_debt_delta=-100,
            target_collateral_delta=-120,
            flash_principal=100,
            flash_fee=2,
            flash_repayment_observed=102,
            economics_complete=True,
            realized_pnl_atomic_units=5,
        )
    )

    assert decision.accepted is True
    assert decision.blockers == ()
    assert len(decision.proof_hash) == 64


def test_mpr2619_zero_or_negative_pnl_is_no_trade_not_success() -> None:
    for pnl in (0, -1):
        decision = verify_raw_simulation_proof(
            SimulationRawProof(
                raw_simulation_hash="c" * 64,
                returned_accounts_hash="d" * 64,
                simulation_slot=123,
                target_debt_delta=-100,
                target_collateral_delta=-120,
                flash_principal=100,
                flash_fee=2,
                flash_repayment_observed=102,
                economics_complete=True,
                realized_pnl_atomic_units=pnl,
            )
        )
        assert decision.accepted is False
        assert Blocker.NON_POSITIVE_REALIZED_PNL in decision.blockers
