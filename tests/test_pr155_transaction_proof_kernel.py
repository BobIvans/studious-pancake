from __future__ import annotations

from dataclasses import replace

from src.transaction_proof_pr155 import (
    Decision,
    EvidenceHash,
    InstructionProof,
    Reason,
    TransactionProof,
    evaluate_transaction_proof,
    scan_for_sender_surface,
)


def _hash(label: str) -> EvidenceHash:
    return EvidenceHash(
        domain=f"flashloan-bot/{label}",
        value=((label.encode().hex() + "abcdef") * 8)[:64],
    )


def _proof() -> TransactionProof:
    planned = (
        InstructionProof(0, "compute-budget", "set-cu-limit"),
        InstructionProof(
            1,
            "associated-token-account",
            "create-idempotent",
            destination="ata-usdc",
            authority="payer",
        ),
        InstructionProof(
            2,
            "jupiter",
            "swap-exact-in",
            source="ata-sol",
            destination="ata-usdc",
            authority="payer",
            amount_atoms=1_000_000,
        ),
        InstructionProof(
            3,
            "marginfi",
            "flash-repay",
            source="ata-usdc",
            destination="marginfi-vault",
            authority="payer",
            amount_atoms=1_003_000,
        ),
    )
    observed = tuple(
        replace(item, raw_data_hash=_hash(f"ix-{item.index}"))
        for item in planned
    )
    programs = tuple(item.program_id for item in planned)
    return TransactionProof(
        schema_version="pr155.transaction-proof.v1",
        cluster_genesis_hash="mainnet-genesis",
        candidate_hash=_hash("candidate"),
        plan_hash=_hash("plan"),
        message_hash=_hash("message"),
        transaction_count=1,
        transaction_version="v0",
        signed_wire_size_bytes=900,
        expected_payer="payer",
        observed_payer="payer",
        expected_signers=("payer",),
        observed_signers=("payer",),
        planned_instructions=planned,
        observed_instructions=observed,
        compute_ix_counts=(1, 1, 1),
        compute_units=300_000,
        final_fee_lamports=7_000,
        blockhash_valid=True,
        blockhash_not_expired=True,
        blockhash_context_ok=True,
        alt_hashes=(_hash("alt"),),
        alt_reviewed=True,
        simulation_hashes=(_hash("accounts"), _hash("inner"), _hash("logs")),
        simulation_units=310_000,
        simulation_err=None,
        simulation_truncated=False,
        planned_top_level_programs=programs,
        observed_top_level_programs=programs,
        observed_cpi_programs=("spl-token", "token-2022"),
        allowed_cpi_programs=("spl-token", "token-2022"),
        cpi_graph_hash=_hash("cpi"),
        principal_lamports=1_000_000,
        flash_fee_lamports=3_000,
        required_repayment_lamports=1_003_000,
        conservative_net_lamports=10_000,
    )


def _assert_reason(proof: TransactionProof, reason: Reason) -> None:
    report = evaluate_transaction_proof(proof)
    assert report.decision is Decision.BLOCKED
    assert any(item.reason is reason for item in report.failures)


def test_pr155_happy_path_is_proven() -> None:
    report = evaluate_transaction_proof(_proof())

    assert report.proven is True
    assert report.decision is Decision.PROVEN
    assert report.failures == ()
    assert len(report.proof_hash) == 64


def test_pr155_rejects_legacy_transaction() -> None:
    _assert_reason(replace(_proof(), transaction_version="legacy"), Reason.SHAPE)


def test_pr155_rejects_multi_transaction_bundle() -> None:
    _assert_reason(replace(_proof(), transaction_count=2), Reason.SHAPE)


def test_pr155_rejects_full_wire_over_1232_bytes() -> None:
    _assert_reason(replace(_proof(), signed_wire_size_bytes=1_233), Reason.SHAPE)


def test_pr155_rejects_payer_mismatch() -> None:
    _assert_reason(replace(_proof(), observed_payer="attacker"), Reason.SHAPE)


def test_pr155_rejects_signer_set_mismatch() -> None:
    _assert_reason(
        replace(_proof(), observed_signers=("payer", "extra")),
        Reason.SHAPE,
    )


def test_pr155_unknown_program_fails_closed() -> None:
    proof = _proof()
    observed = list(proof.observed_instructions)
    observed[2] = replace(observed[2], program_id="unknown-program")

    _assert_reason(
        replace(proof, observed_instructions=tuple(observed)),
        Reason.INSTRUCTION,
    )


def test_pr155_instruction_amount_change_invalidates_firewall() -> None:
    proof = _proof()
    observed = list(proof.observed_instructions)
    observed[2] = replace(observed[2], amount_atoms=999_999)

    _assert_reason(
        replace(proof, observed_instructions=tuple(observed)),
        Reason.INSTRUCTION,
    )


def test_pr155_unapproved_account_close_is_blocked() -> None:
    proof = _proof()
    observed = list(proof.observed_instructions)
    observed[1] = replace(observed[1], closes_account=True)

    _assert_reason(
        replace(proof, observed_instructions=tuple(observed)),
        Reason.INSTRUCTION,
    )


def test_pr155_compute_budget_must_be_unique_and_positive() -> None:
    _assert_reason(replace(_proof(), compute_ix_counts=(2, 1, 1)), Reason.COMPUTE)


def test_pr155_invalid_blockhash_blocks_proof() -> None:
    _assert_reason(replace(_proof(), blockhash_valid=False), Reason.BLOCKHASH)


def test_pr155_alt_must_be_reviewed() -> None:
    _assert_reason(replace(_proof(), alt_reviewed=False), Reason.ALT)


def test_pr155_truncated_simulation_is_indeterminate() -> None:
    _assert_reason(replace(_proof(), simulation_truncated=True), Reason.SIMULATION)


def test_pr155_unexpected_cpi_fails_closed() -> None:
    proof = _proof()
    cpi = ("spl-token", "evil-cpi")

    _assert_reason(replace(proof, observed_cpi_programs=cpi), Reason.CPI)


def test_pr155_double_counted_flash_fee_is_blocked() -> None:
    _assert_reason(
        replace(_proof(), required_repayment_lamports=1_006_000),
        Reason.RECONCILIATION,
    )


def test_pr155_placeholder_hash_is_blocked() -> None:
    message_hash = EvidenceHash("flashloan-bot/message", "0" * 64)

    _assert_reason(replace(_proof(), message_hash=message_hash), Reason.HASH)


def test_pr155_one_byte_change_changes_proof_hash() -> None:
    proof = _proof()
    changed = replace(proof, signed_wire_size_bytes=901)

    assert evaluate_transaction_proof(proof).proof_hash != (
        evaluate_transaction_proof(changed).proof_hash
    )


def test_pr155_sender_surface_scanner_flags_forbidden_tokens() -> None:
    assert scan_for_sender_surface("def safe(): return 'proof only'") == ()
    failures = scan_for_sender_surface("Keypair()\nsendTransaction")

    assert len(failures) == 2
    assert all(item.reason is Reason.SENDER_SURFACE for item in failures)
