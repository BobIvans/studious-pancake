from __future__ import annotations

from dataclasses import replace

import pytest

from src.config.chain_registry import (
    ADDRESS_LOOKUP_TABLE_PROGRAM_ADDRESS,
    NATIVE_SOL_MINT_ADDRESS,
    SYSTEM_PROGRAM_ADDRESS,
    TOKEN_2022_PROGRAM_ADDRESS,
    TOKEN_PROGRAM_ADDRESS,
    ChainRegistry,
)
from src.kernel import domain_sha256
from src.rooted_truth import (
    AddressLookupTableState,
    BlockhashLease,
    DeployedIdentityRegistry,
    ForkContext,
    MintSnapshot,
    OracleSnapshot,
    PoolSnapshot,
    RootedRuntimeTruth,
    RootedTruthError,
    RuntimeTruthPolicy,
    build_admission,
)

GENESIS = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"


def digest(label: str) -> str:
    return domain_sha256(
        domain="mpr-sys-01-test",
        schema_id="fixture.v1",
        payload=label.encode(),
    )


def build_truth() -> RootedRuntimeTruth:
    policy = RuntimeTruthPolicy.load_default()
    registry = DeployedIdentityRegistry.from_chain_registry(
        ChainRegistry.load_default(),
        cluster="mainnet-beta",
        genesis_hash=GENESIS,
        external_blockers=policy.external_required_programs,
    )
    fork = ForkContext(
        cluster="mainnet-beta",
        genesis_hash=GENESIS,
        provider_id="independent-offline-quorum",
        context_slot=100,
        root_slot=100,
        block_height=90,
        commitment="finalized",
        feature_set_sha256=digest("features"),
        registry_generation=registry.generation,
        observed_monotonic_ns=1,
        observed_at_utc="2026-08-02T00:00:00Z",
    )
    blockhash = BlockhashLease(
        blockhash=GENESIS,
        last_valid_block_height=150,
        observed_block_height=90,
        context_slot=100,
        registry_generation=registry.generation,
        evidence_sha256=digest("blockhash"),
    )
    alt = AddressLookupTableState(
        table_address=ADDRESS_LOOKUP_TABLE_PROGRAM_ADDRESS,
        owner_program_id=ADDRESS_LOOKUP_TABLE_PROGRAM_ADDRESS,
        authority=None,
        deactivation_slot=None,
        last_extended_slot=90,
        ordered_addresses=(SYSTEM_PROGRAM_ADDRESS, TOKEN_PROGRAM_ADDRESS),
        account_sha256=digest("alt-account"),
        context_slot=100,
        root_slot=100,
        registry_generation=registry.generation,
    )
    mint = MintSnapshot(
        mint=NATIVE_SOL_MINT_ADDRESS,
        token_program_id=TOKEN_PROGRAM_ADDRESS,
        decimals=9,
        mint_authority=None,
        freeze_authority=None,
        permanent_delegate=None,
        transfer_hook_program=None,
        extensions=(),
        transfer_fee_bps=0,
        withheld_amount=0,
        account_length=82,
        rent_lamports=1,
        context_slot=100,
        root_slot=100,
        registry_generation=registry.generation,
        evidence_sha256=digest("mint"),
        expires_at_slot=120,
    )
    oracle = OracleSnapshot(
        oracle_id="independent-oracle",
        price_atomic=1_000_000,
        confidence_bps=10,
        divergence_bps=20,
        observed_slot=100,
        root_slot=100,
        source_ids=("source-a", "source-b"),
        evidence_sha256=digest("oracle"),
    )
    pool = PoolSnapshot(
        pool_id=TOKEN_PROGRAM_ADDRESS,
        program_id=SYSTEM_PROGRAM_ADDRESS,
        vault_owners=(TOKEN_PROGRAM_ADDRESS, SYSTEM_PROGRAM_ADDRESS),
        fee_bps=10,
        oracle_id=oracle.oracle_id,
        context_slot=100,
        root_slot=100,
        registry_generation=registry.generation,
        evidence_sha256=digest("pool"),
        expires_at_slot=120,
    )
    admission = build_admission(
        mint=mint,
        oracle=oracle,
        pool=pool,
        policy=policy,
        registry=registry,
        current_root_slot=100,
    )
    assert admission.admitted
    return RootedRuntimeTruth(
        registry=registry,
        fork=fork,
        blockhash=blockhash,
        alts=(alt,),
        admission=admission,
    )


def test_candidate_is_bound_to_one_rooted_generation() -> None:
    truth = build_truth()
    binding = truth.bind_candidate(
        candidate_id="candidate-1",
        message_sha256=digest("message"),
        required_program_ids=(SYSTEM_PROGRAM_ADDRESS, TOKEN_PROGRAM_ADDRESS),
        expected_alt_digests=tuple(item.digest for item in truth.alts),
        current_root_slot=100,
        current_block_height=100,
        rpc_reports_blockhash_valid=True,
    )
    assert binding.registry_generation == truth.registry.generation
    assert binding.rooted_truth_sha256 == truth.digest
    assert binding.admission_generation == truth.admission.generation


def test_blockhash_expiry_uses_last_valid_block_height() -> None:
    truth = build_truth()
    with pytest.raises(RootedTruthError, match="lastValidBlockHeight"):
        truth.bind_candidate(
            candidate_id="expired",
            message_sha256=digest("expired-message"),
            required_program_ids=(SYSTEM_PROGRAM_ADDRESS,),
            expected_alt_digests=tuple(item.digest for item in truth.alts),
            current_root_slot=100,
            current_block_height=151,
            rpc_reports_blockhash_valid=True,
        )


def test_token_2022_is_default_deny() -> None:
    truth = build_truth()
    token_2022 = replace(
        truth.admission.mint,
        token_program_id=TOKEN_2022_PROGRAM_ADDRESS,
        extensions=("transfer_hook",),
        transfer_hook_program=SYSTEM_PROGRAM_ADDRESS,
    )
    admission = build_admission(
        mint=token_2022,
        oracle=truth.admission.oracle,
        pool=truth.admission.pool,
        policy=RuntimeTruthPolicy.load_default(),
        registry=truth.registry,
        current_root_slot=100,
    )
    assert not admission.mint_decision.admitted
    assert "TOKEN_2022_DEFAULT_DENY" in admission.mint_decision.reasons
