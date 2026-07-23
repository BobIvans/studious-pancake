from __future__ import annotations

import copy

import pytest

from src.production_economic_proof_pr197 import (
    MAX_SOLANA_WIRE_BYTES,
    PR197EconomicProofError,
    PR197_SCHEMA_VERSION,
    live_capability_allowed,
    sender_capability_allowed,
    signer_capability_allowed,
    validate_pr197_economic_proof,
)

_DIGEST = "a" * 64
_MESSAGE_HASH = "b" * 64
_DATA_HASH = "c" * 64


def _evidence() -> dict[str, object]:
    return {
        "schema_version": PR197_SCHEMA_VERSION,
        "artifact_hashes": {
            "rooted_snapshot_hash": "1" * 64,
            "route_plan_hash": "2" * 64,
            "semantic_firewall_hash": "3" * 64,
            "compiled_message_hash": _MESSAGE_HASH,
            "simulation_report_hash": "4" * 64,
            "account_delta_hash": "5" * 64,
            "fee_quote_hash": "6" * 64,
            "economics_hash": "7" * 64,
        },
        "atomic_sequence": [
            "setup",
            "flash_start",
            "borrow",
            "swap_a",
            "swap_b",
            "repay",
            "cleanup",
            "flash_end",
        ],
        "semantic_firewall": {
            "decoders": [
                "marginfi",
                "jupiter",
                "system",
                "ata",
                "spl_token",
                "compute_budget",
            ],
            "deny_unknown_instruction": True,
            "exact_account_roles": True,
            "exact_amount_binding": True,
            "writable_delta_budget_enforced": True,
            "forbidden_effect_fixtures": [
                "system_transfer",
                "token_transfer_unbudgeted",
                "token_approve",
                "token_set_authority",
                "token_close_account_unapproved",
                "delegate_change",
                "authority_change",
            ],
            "mutation_rejection_coverage": True,
        },
        "compiler": {
            "transaction_version": "v0",
            "serialized_wire_bytes": MAX_SOLANA_WIRE_BYTES,
            "immutable_blockhash": True,
            "immutable_alt_set": True,
            "sign_fully_rechecks_size": True,
            "public_apis_enforce_size": True,
            "compiled_message_hash": _MESSAGE_HASH,
            "simulated_message_hash": _MESSAGE_HASH,
        },
        "simulation": {
            "min_context_slot": 123,
            "valid_blockhash": True,
            "canonical_message_simulated": True,
            "expected_invoke_graph_verified": True,
            "account_state_bound": True,
            "account_snapshots": [
                {
                    "address": "payer1111111111111111111111111111111111111",
                    "owner": "11111111111111111111111111111111",
                    "lamports": 50_000_000,
                    "data_hash": _DATA_HASH,
                },
                {
                    "address": "marginfi-bank111111111111111111111111111111",
                    "owner": "marginfi-program1111111111111111111111111",
                    "lamports": 1_000_000,
                    "data_hash": _DIGEST,
                },
            ],
        },
        "economics": {
            "rpc_total_message_fee_lamports": 8_000,
            "explained_base_fee_lamports": 5_000,
            "explained_priority_fee_lamports": 3_000,
            "rent_lamports": 2_000,
            "protocol_fee_lamports": 1_000,
            "swap_fee_lamports": 1_000,
            "tip_lamports": 500,
            "contingency_lamports": 1_500,
            "failed_landing_fee_lamports": 8_000,
            "total_native_cost_lamports": 22_000,
            "projected_profit_lamports": 30_000,
        },
        "raw_state_decoder_is_sole_observation_source": True,
        "token_2022_policy_fail_closed": True,
        "signer_present": False,
        "sender_present": False,
        "live_enabled": False,
    }


def _codes(report) -> set[str]:
    return {diagnostic.code for diagnostic in report.diagnostics}


def test_pr197_accepts_complete_sender_free_economic_proof() -> None:
    report = validate_pr197_economic_proof(_evidence())

    assert report.ok is True
    assert report.diagnostics == ()
    assert len(report.evidence_hash) == 64
    assert live_capability_allowed() is False
    assert signer_capability_allowed() is False
    assert sender_capability_allowed() is False


def test_pr197_rejects_wrong_atomic_sequence() -> None:
    evidence = _evidence()
    evidence["atomic_sequence"] = ["setup", "borrow", "repay", "flash_end"]

    report = validate_pr197_economic_proof(evidence)

    assert report.ok is False
    assert "ATOMIC_SEQUENCE_INVALID" in _codes(report)


def test_pr197_rejects_missing_semantic_decoder_and_forbidden_fixtures() -> None:
    evidence = _evidence()
    firewall = copy.deepcopy(evidence["semantic_firewall"])
    firewall["decoders"] = ["marginfi", "jupiter"]
    firewall["forbidden_effect_fixtures"] = ["system_transfer"]
    evidence["semantic_firewall"] = firewall

    report = validate_pr197_economic_proof(evidence)

    assert report.ok is False
    assert "SEMANTIC_DECODER_MISSING" in _codes(report)
    assert "FORBIDDEN_EFFECT_FIXTURE_MISSING" in _codes(report)


def test_pr197_rejects_oversized_or_mutable_message() -> None:
    evidence = _evidence()
    compiler = copy.deepcopy(evidence["compiler"])
    compiler["serialized_wire_bytes"] = MAX_SOLANA_WIRE_BYTES + 1
    compiler["immutable_blockhash"] = False
    compiler["sign_fully_rechecks_size"] = False
    evidence["compiler"] = compiler

    report = validate_pr197_economic_proof(evidence)

    assert report.ok is False
    assert "WIRE_SIZE_LIMIT_EXCEEDED" in _codes(report)
    assert "BLOCKHASH_NOT_IMMUTABLE" in _codes(report)
    assert "SIGN_FULLY_SIZE_BYPASS" in _codes(report)


def test_pr197_rejects_message_simulation_mismatch() -> None:
    evidence = _evidence()
    compiler = copy.deepcopy(evidence["compiler"])
    compiler["simulated_message_hash"] = "d" * 64
    evidence["compiler"] = compiler

    report = validate_pr197_economic_proof(evidence)

    assert report.ok is False
    assert "SIMULATION_MESSAGE_MISMATCH" in _codes(report)


def test_pr197_rejects_unbound_simulation_state() -> None:
    evidence = _evidence()
    simulation = copy.deepcopy(evidence["simulation"])
    simulation["valid_blockhash"] = False
    simulation["account_state_bound"] = False
    simulation["account_snapshots"] = []
    evidence["simulation"] = simulation

    report = validate_pr197_economic_proof(evidence)

    assert report.ok is False
    assert "SIMULATION_BLOCKHASH_INVALID" in _codes(report)
    assert "ACCOUNT_STATE_NOT_BOUND" in _codes(report)
    assert "ACCOUNT_SNAPSHOTS_MISSING" in _codes(report)


def test_pr197_rejects_malformed_account_snapshot() -> None:
    evidence = _evidence()
    simulation = copy.deepcopy(evidence["simulation"])
    simulation["account_snapshots"] = [
        {"address": "", "owner": "", "lamports": -1, "data_hash": "bad"}
    ]
    evidence["simulation"] = simulation

    report = validate_pr197_economic_proof(evidence)

    assert report.ok is False
    assert "ACCOUNT_SNAPSHOT_FIELD_MISSING" in _codes(report)
    assert "ACCOUNT_DATA_HASH_INVALID" in _codes(report)
    assert "ACCOUNT_LAMPORTS_INVALID" in _codes(report)


def test_pr197_rejects_priority_fee_double_count_or_underfunded_profit() -> None:
    evidence = _evidence()
    economics = copy.deepcopy(evidence["economics"])
    economics["total_native_cost_lamports"] = 25_000
    economics["projected_profit_lamports"] = 20_000
    evidence["economics"] = economics

    report = validate_pr197_economic_proof(evidence)

    assert report.ok is False
    assert "NATIVE_COST_TOTAL_MISMATCH" in _codes(report)
    assert "PROJECTED_PROFIT_INSUFFICIENT" in _codes(report)


def test_pr197_rejects_caller_supplied_observations_and_token_2022_open_policy() -> None:
    evidence = _evidence()
    evidence["raw_state_decoder_is_sole_observation_source"] = False
    evidence["token_2022_policy_fail_closed"] = False

    report = validate_pr197_economic_proof(evidence)

    assert report.ok is False
    assert "CALLER_SUPPLIED_OBSERVATIONS_ALLOWED" in _codes(report)
    assert "TOKEN_2022_NOT_FAIL_CLOSED" in _codes(report)


@pytest.mark.parametrize("field", ["signer_present", "sender_present", "live_enabled"])
def test_pr197_rejects_live_signer_or_sender_capability(field: str) -> None:
    evidence = _evidence()
    evidence[field] = True

    report = validate_pr197_economic_proof(evidence)

    assert report.ok is False
    assert live_capability_allowed() is False
    assert signer_capability_allowed() is False
    assert sender_capability_allowed() is False


def test_pr197_rejects_schema_or_type_errors() -> None:
    evidence = _evidence()
    evidence["schema_version"] = "wrong"

    with pytest.raises(PR197EconomicProofError, match="unsupported"):
        validate_pr197_economic_proof(evidence)
