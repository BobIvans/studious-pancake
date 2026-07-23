from dataclasses import replace

from src.execution.finalized_message_evidence_mega_pr02 import (
    AltTableEvidence,
    CausalEvidenceTimeline,
    CompiledMessageFingerprint,
    ComputeBudgetFinalization,
    FinalBlockhashEvidence,
    FinalizedMessageReason,
    FinalizedMessageStatus,
    HARDENED_COMPILER_ID,
    HardenedFinalizedMessageAuthority,
    HardenedFinalizedMessageEvidence,
    MandatoryAccountDerivation,
    RootedInputEvidence,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
HASH_F = "f" * 64
HASH_1 = "1" * 64
HASH_2 = "2" * 64
HASH_3 = "3" * 64
HASH_4 = "4" * 64
HASH_5 = "5" * 64
HASH_6 = "6" * 64
HASH_7 = "7" * 64
HASH_8 = "8" * 64
HASH_9 = "9" * 64
ZERO_HASH = "0" * 64


def alt(**kwargs) -> AltTableEvidence:
    defaults = {
        "table_address": "alt-table",
        "owner": "address-lookup-table-program",
        "raw_hash": HASH_A,
        "resolved_slot": 104,
        "extension_slot": 91,
        "deactivation_slot": None,
        "authority_hash": HASH_B,
        "addresses_hash": HASH_C,
        "genesis_hash": HASH_D,
        "metadata_source": "on_chain_raw_bytes",
    }
    defaults.update(kwargs)
    return AltTableEvidence(**defaults)


def compute(**kwargs) -> ComputeBudgetFinalization:
    defaults = {
        "compute_unit_limit": 420_000,
        "compute_unit_price_micro_lamports": 9_000,
        "loaded_account_data_size_limit_bytes": 96_000,
        "landing_cost_cap_lamports": 30_000,
        "final_observation_slot": 106,
        "priority_fee_hash": HASH_E,
        "policy_hash": HASH_F,
        "emitted_compute_unit_limit_instructions": 1,
        "emitted_compute_unit_price_instructions": 1,
        "emitted_loaded_data_limit_instructions": 1,
    }
    defaults.update(kwargs)
    return ComputeBudgetFinalization(**defaults)


def rooted(**kwargs) -> RootedInputEvidence:
    defaults = {
        "provider_id": "rpc-quorum-a",
        "genesis_hash": HASH_D,
        "quote_slot": 100,
        "market_slot": 101,
        "oracle_slot": 102,
        "alt_slot": 103,
        "root_slot": 105,
        "quote_hash": HASH_1,
        "market_hash": HASH_2,
        "oracle_hash": HASH_3,
    }
    defaults.update(kwargs)
    return RootedInputEvidence(**defaults)


def timeline(**kwargs) -> CausalEvidenceTimeline:
    defaults = {
        "provider_id": "rpc-quorum-a",
        "genesis_hash": HASH_D,
        "validation_slot": 100,
        "provisional_simulation_slot": 103,
        "compute_finalization_slot": 106,
        "final_simulation_slot": 108,
        "fee_quote_slot": 109,
        "blockhash_check_slot": 110,
        "validation_hash": HASH_4,
        "provisional_simulation_hash": HASH_5,
        "final_simulation_hash": HASH_6,
        "fee_quote_hash": HASH_7,
        "blockhash_check_hash": HASH_8,
    }
    defaults.update(kwargs)
    return CausalEvidenceTimeline(**defaults)


def monitored(**kwargs) -> MandatoryAccountDerivation:
    mandatory = {
        "payer",
        "wallet-usdc",
        "wallet-sol",
        "tmp-wsol",
        "marginfi-vault",
        "marginfi-bank",
        "marginfi-account",
        "oracle-pyth",
        "cleanup-recipient",
    }
    defaults = {
        "payer": "payer",
        "writable_accounts": frozenset({"wallet-usdc", "wallet-sol"}),
        "token_accounts": frozenset({"wallet-usdc"}),
        "temporary_accounts": frozenset({"tmp-wsol"}),
        "protocol_vaults": frozenset({"marginfi-vault"}),
        "protocol_banks": frozenset({"marginfi-bank"}),
        "margin_accounts": frozenset({"marginfi-account"}),
        "oracle_accounts": frozenset({"oracle-pyth"}),
        "cleanup_recipients": frozenset({"cleanup-recipient"}),
        "caller_extra_accounts": frozenset({"extra-readonly"}),
        "returned_raw_snapshot_accounts": frozenset(mandatory | {"extra-readonly"}),
    }
    defaults.update(kwargs)
    return MandatoryAccountDerivation(**defaults)


def evidence(**kwargs) -> HardenedFinalizedMessageEvidence:
    alt_table = kwargs.pop("alt_table", alt())
    compute_budget = kwargs.pop("compute_budget", compute())
    message = kwargs.pop(
        "compiled_message",
        CompiledMessageFingerprint(
            compiler_id=HARDENED_COMPILER_ID,
            compiler_policy_hash=HASH_9,
            plan_hash=HASH_1,
            message_hash=HASH_2,
            blockhash="blockhash-abc",
            blockhash_source_slot=104,
            alt_fingerprints=(alt_table.fingerprint,),
            static_account_hash=HASH_3,
            instruction_hash=HASH_4,
            wire_size_bytes=1_100,
            compute_unit_limit=compute_budget.compute_unit_limit,
            compute_unit_price_micro_lamports=(
                compute_budget.compute_unit_price_micro_lamports
            ),
            loaded_account_data_size_limit_bytes=(
                compute_budget.loaded_account_data_size_limit_bytes
            ),
            compute_budget_fingerprint=compute_budget.fingerprint,
            generated_by_exact_simulation=True,
        ),
    )
    defaults = {
        "rooted_inputs": rooted(),
        "compiled_message": message,
        "alt_tables": (alt_table,),
        "compute_budget": compute_budget,
        "timeline": timeline(),
        "final_blockhash": FinalBlockhashEvidence(
            blockhash=message.blockhash,
            checked_at_slot=111,
            current_block_height=10_000,
            last_valid_block_height=10_180,
            remaining_height_margin=40,
            is_blockhash_valid=True,
            response_hash=HASH_5,
        ),
        "monitored_accounts": monitored(),
        "min_context_slot": 105,
        "permit_issuer_evidence_hash": ZERO_HASH,
        "signer_authorization_evidence_hash": ZERO_HASH,
    }
    defaults.update(kwargs)
    draft = HardenedFinalizedMessageEvidence(**defaults)
    return replace(
        draft,
        permit_issuer_evidence_hash=draft.evidence_hash,
        signer_authorization_evidence_hash=draft.evidence_hash,
    )


def verify(item: HardenedFinalizedMessageEvidence):
    return HardenedFinalizedMessageAuthority().verify(item)


def test_canonical_hardened_finalized_message_evidence_is_ready():
    result = verify(evidence())

    assert result.status is FinalizedMessageStatus.READY
    assert result.reason is FinalizedMessageReason.READY
    assert result.ready
    assert result.evidence_hash is not None


def test_plain_compiler_cannot_be_used_by_exact_simulation_boundary():
    base = evidence()
    forged = replace(
        base,
        compiled_message=replace(
            base.compiled_message,
            compiler_id="LegacyPlainCompiler",
            generated_by_exact_simulation=False,
        ),
    )

    result = verify(forged)

    assert result.status is FinalizedMessageStatus.BLOCKED
    assert result.reason is FinalizedMessageReason.UNHARDENED_COMPILER


def test_alt_metadata_must_be_raw_derived_and_not_caller_overridden():
    caller_alt = alt(metadata_source="caller_supplied_json")
    result = verify(evidence(alt_table=caller_alt))

    assert result.status is FinalizedMessageStatus.BLOCKED
    assert result.reason is FinalizedMessageReason.ALT_METADATA_NOT_RAW_DERIVED


def test_alt_deactivation_at_context_slot_blocks_message():
    result = verify(evidence(alt_table=alt(deactivation_slot=105)))

    assert result.status is FinalizedMessageStatus.BLOCKED
    assert result.reason is FinalizedMessageReason.ALT_DEACTIVATED


def test_protocol_wire_size_ceiling_cannot_expand_for_oversized_transaction():
    base = evidence()
    oversized = replace(
        base,
        compiled_message=replace(base.compiled_message, wire_size_bytes=1_233),
    )

    result = verify(oversized)

    assert result.status is FinalizedMessageStatus.BLOCKED
    assert result.reason is FinalizedMessageReason.WIRE_SIZE_LIMIT_EXCEEDED


def test_missing_quote_market_oracle_provenance_blocks_min_context_zero_path():
    result = verify(evidence(rooted_inputs=rooted(root_slot=101)))

    assert result.status is FinalizedMessageStatus.BLOCKED
    assert result.reason is FinalizedMessageReason.INPUT_PROVENANCE_MISSING


def test_causal_slot_regression_between_simulation_and_fee_is_rejected():
    regressing = timeline(fee_quote_slot=107)
    result = verify(evidence(timeline=regressing))

    assert result.status is FinalizedMessageStatus.BLOCKED
    assert result.reason is FinalizedMessageReason.SLOT_REGRESSION


def test_post_final_blockhash_viability_and_margin_are_required():
    base = evidence()
    invalid = replace(
        base,
        final_blockhash=replace(base.final_blockhash, is_blockhash_valid=False),
    )
    thin_margin = replace(
        base,
        final_blockhash=replace(
            base.final_blockhash,
            current_block_height=10_160,
            remaining_height_margin=40,
        ),
    )

    assert verify(invalid).reason is FinalizedMessageReason.BLOCKHASH_NOT_FINAL_VALID
    assert verify(thin_margin).reason is FinalizedMessageReason.BLOCKHASH_MARGIN_INSUFFICIENT


def test_pr128_compute_policy_must_be_finalized_and_bound_to_message():
    non_final = evidence(
        compute_budget=compute(emitted_compute_unit_price_instructions=2)
    )
    base = evidence()
    disconnected = replace(
        base,
        compiled_message=replace(base.compiled_message, compute_unit_limit=399_999),
    )

    assert verify(non_final).reason is FinalizedMessageReason.COMPUTE_BUDGET_NOT_FINALIZED
    assert (
        verify(disconnected).reason
        is FinalizedMessageReason.COMPUTE_BUDGET_NOT_BOUND_TO_MESSAGE
    )


def test_raw_snapshots_must_cover_all_semantic_economic_accounts():
    missing = monitored(
        returned_raw_snapshot_accounts=frozenset({"payer", "wallet-usdc"})
    )

    result = verify(evidence(monitored_accounts=missing))

    assert result.status is FinalizedMessageStatus.BLOCKED
    assert result.reason is FinalizedMessageReason.MONITORED_ACCOUNT_MISSING


def test_permit_issuer_and_signer_must_consume_same_evidence_hash():
    base = evidence()
    drifted = replace(base, signer_authorization_evidence_hash=HASH_A)

    result = verify(drifted)

    assert result.status is FinalizedMessageStatus.BLOCKED
    assert result.reason is FinalizedMessageReason.DOWNSTREAM_EVIDENCE_HASH_MISMATCH
