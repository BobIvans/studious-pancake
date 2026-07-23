from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from src.execution.atomic_kernel_pr197 import (
    AddressLookupTableBinding,
    AtomicKernelError,
    AtomicKernelStatus,
    BlockhashBinding,
    ExecutionBinding,
    ExternalStateBinding,
    FinalMessageBinding,
    InstructionSequenceBinding,
    IntegerEconomics,
    SimulationBinding,
    evaluate_atomic_sender_free_kernel,
    stable_json,
)

pytestmark = pytest.mark.unit


def _h(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _binding() -> ExecutionBinding:
    external = ExternalStateBinding(
        state_snapshot_hash=_h("state"),
        provider_response_hash=_h("jupiter-build-response"),
        route_plan_hash=_h("v2-bps-route-plan"),
        marginfi_identity_hash=_h("marginfi-program-bank-oracle"),
        quote_slot=120,
        market_state_slot=124,
        oracle_slot=122,
        provider_received_at_unix_ns=1_900_000_000,
    )
    sequence = InstructionSequenceBinding(
        instruction_roles=(
            "marginfi.begin",
            "marginfi.borrow",
            "jupiter.leg_a",
            "jupiter.leg_b",
            "marginfi.repay",
            "marginfi.end",
        ),
        instruction_programs_hash=_h("programs"),
        instruction_accounts_hash=_h("accounts"),
        instruction_data_hash=_h("ix-data"),
    )
    economics = IntegerEconomics(
        principal_lamports=1_000_000,
        repayment_lamports=1_003_000,
        flash_fee_lamports=3_000,
        expected_output_lamports=1_020_000,
        base_network_fee_lamports=5_000,
        priority_fee_lamports=1_000,
        jito_tip_lamports=1_000,
        ata_rent_peak_lamports=2_039_280,
        token2022_transfer_fee_lamports=0,
        contingency_lamports=500,
        protected_reserve_lamports=10_000,
        wallet_lamports=3_000_000,
        minimum_profit_lamports=1_000,
    )
    return ExecutionBinding(
        attempt_id="attempt-197-1",
        plan_hash=_h("plan"),
        compiler_version="pr197-v0-compiler-contract",
        config_generation_hash=_h("config-generation"),
        policy_bundle_hash=_h("policy-bundle"),
        external_state=external,
        instruction_sequence=sequence,
        blockhash=BlockhashBinding(
            blockhash="ExampleBlockhash197",
            source_slot=130,
            last_valid_block_height=900_000,
            fetched_at_unix_ns=1_900_000_010,
        ),
        final_message=FinalMessageBinding(
            message_hash=_h("final-message"),
            wire_size_bytes=900,
            required_signers_hash=_h("payer-only"),
            static_account_count=28,
            lookup_account_count=12,
            compiled_at_unix_ns=1_900_000_020,
        ),
        economics=economics,
        alt_bindings=(
            AddressLookupTableBinding(
                address="AltAddress197",
                account_hash=_h("alt-account"),
                addresses_hash=_h("alt-addresses"),
                source_slot=129,
            ),
        ),
    )


def _simulation(binding: ExecutionBinding) -> SimulationBinding:
    return SimulationBinding(
        transaction_message_hash=binding.final_message.message_hash,
        simulation_slot=131,
        min_context_slot=binding.min_context_slot,
        success=True,
        logs_hash=_h("simulation-logs"),
        units_consumed=420_000,
    )


def test_valid_kernel_report_is_sender_free_and_deterministic() -> None:
    binding = _binding()
    report = evaluate_atomic_sender_free_kernel(binding, _simulation(binding))

    assert report.status is AtomicKernelStatus.READY_SENDER_FREE
    assert report.ok is True
    assert report.signed is False
    assert report.submitted is False
    assert report.live_enabled is False
    assert report.binding_hash == binding.binding_hash
    assert report.to_dict()["diagnostics"] == []


def test_binding_hash_changes_when_exact_economics_change() -> None:
    binding = _binding()
    changed = replace(
        binding,
        economics=replace(binding.economics, jito_tip_lamports=2_000),
    )

    assert changed.binding_hash != binding.binding_hash


def test_floating_point_values_are_forbidden_in_kernel_evidence() -> None:
    with pytest.raises(AtomicKernelError, match="floating point"):
        stable_json({"unsafe_float": 0.1})

    with pytest.raises(AtomicKernelError, match="principal_lamports"):
        IntegerEconomics(
            principal_lamports=1.0,
            repayment_lamports=1,
            flash_fee_lamports=0,
            expected_output_lamports=2,
            base_network_fee_lamports=0,
            priority_fee_lamports=0,
            jito_tip_lamports=0,
            ata_rent_peak_lamports=0,
            token2022_transfer_fee_lamports=0,
            contingency_lamports=0,
            protected_reserve_lamports=0,
            wallet_lamports=1,
            minimum_profit_lamports=0,
        )


def test_stale_blockhash_and_simulation_identity_reject() -> None:
    binding = replace(
        _binding(),
        blockhash=BlockhashBinding(
            blockhash="StaleBlockhash197",
            source_slot=1,
            last_valid_block_height=900_000,
            fetched_at_unix_ns=1_900_000_010,
        ),
    )
    simulation = replace(
        _simulation(binding),
        transaction_message_hash=_h("different-message"),
    )

    report = evaluate_atomic_sender_free_kernel(binding, simulation)

    codes = {item.code for item in report.diagnostics}
    assert report.ok is False
    assert "BLOCKHASH_BEFORE_EXECUTION_CONTEXT" in codes
    assert "SIMULATION_MESSAGE_MISMATCH" in codes


def test_provider_tip_and_incomplete_marginfi_bracket_reject() -> None:
    binding = replace(
        _binding(),
        instruction_sequence=InstructionSequenceBinding(
            instruction_roles=(
                "marginfi.begin",
                "marginfi.borrow",
                "provider.tip",
                "jupiter.leg_a",
                "marginfi.repay",
                "marginfi.end",
            ),
            instruction_programs_hash=_h("programs"),
            instruction_accounts_hash=_h("accounts"),
            instruction_data_hash=_h("ix-data"),
        ),
    )

    report = evaluate_atomic_sender_free_kernel(binding, _simulation(binding))

    codes = {item.code for item in report.diagnostics}
    assert report.status is AtomicKernelStatus.STRUCTURE_REJECTED
    assert "FORBIDDEN_INSTRUCTION_ROLE" in codes
    assert "MISSING_INSTRUCTION_ROLE" in codes


def test_economics_reject_when_profit_or_wallet_reserve_is_insufficient() -> None:
    binding = replace(
        _binding(),
        economics=replace(
            _binding().economics,
            expected_output_lamports=1_005_000,
            wallet_lamports=100,
        ),
    )

    report = evaluate_atomic_sender_free_kernel(binding, _simulation(binding))

    codes = {item.code for item in report.diagnostics}
    assert "INSUFFICIENT_CONSERVATIVE_OUTPUT" in codes
    assert "INSUFFICIENT_WALLET_RESERVE" in codes
