from __future__ import annotations

from dataclasses import replace

import pytest

from src.pr171_chain_context import (
    AccountSetEvidence,
    ChainContext,
    Commitment,
    PR171ChainContextError,
    SimulationEvidenceBundle,
    build_cache_key,
    evaluate_finalized_accounting_context,
    evaluate_simulation_bundle,
    reorg_invalidation_reasons,
    require_no_implicit_commitment,
    require_simulation_context_slot,
)

pytestmark = pytest.mark.unit

HASH_A = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
HASH_B = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
HASH_C = "123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef0"
HASH_D = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
GENESIS = "solana-mainnet-genesis"


def _context(
    *,
    commitment: Commitment = Commitment.CONFIRMED,
    method: str = "simulateTransaction",
    request_hash: str = HASH_A,
    fork: str = "fork-a/root-95",
    response_context_present: bool = True,
    context_slot: int | None = 100,
    min_context_slot: int | None = 90,
    root_slot: int | None = 95,
    finalized_slot: int | None = 92,
    current_slot: int = 110,
    correlation_group: str = "rpc-quorum-a",
) -> ChainContext:
    return ChainContext(
        cluster_genesis=GENESIS,
        endpoint_identity="rpc-primary",
        correlation_group=correlation_group,
        request_method=method,
        request_hash=request_hash,
        commitment=commitment,
        current_slot=current_slot,
        wall_time_ns=1_000_000_000,
        monotonic_time_ns=2_000_000_000,
        fork_fingerprint=fork,
        context_slot=context_slot,
        min_context_slot=min_context_slot,
        root_slot=root_slot,
        finalized_slot=finalized_slot,
        block_height=50_000,
        response_context_present=response_context_present,
        evidence_expires_at_ns=1_000_500_000,
    )


def _ready_bundle() -> SimulationEvidenceBundle:
    pre = _context(method="getMultipleAccounts", request_hash=HASH_A)
    simulation = _context(method="simulateTransaction", request_hash=HASH_B)
    fee = _context(method="getFeeForMessage", request_hash=HASH_C)
    blockhash = _context(method="getLatestBlockhash", request_hash=HASH_D)
    return SimulationEvidenceBundle(
        pre_state=pre,
        simulation=simulation,
        fee=fee,
        blockhash_alt=blockhash,
        account_set=AccountSetEvidence(
            requested_addresses=("AccountA", "AccountB"),
            returned_addresses=("AccountA", "AccountB"),
            context=pre,
        ),
    )


def test_ready_chain_context_bundle_is_manual_review_only() -> None:
    report = evaluate_simulation_bundle(_ready_bundle())

    assert report.ready is True
    assert report.runtime_live_enabled is False
    assert report.to_dict()["status"] == "ready"
    assert report.to_dict()["metrics"]["stage_context_count"] == 4


def test_critical_rpc_call_cannot_omit_commitment() -> None:
    with pytest.raises(PR171ChainContextError, match="implicit commitment"):
        require_no_implicit_commitment(method="simulateTransaction", commitment=None)

    assert require_no_implicit_commitment(
        method="simulateTransaction",
        commitment=Commitment.CONFIRMED,
    ) == Commitment.CONFIRMED


def test_missing_simulation_context_cannot_fallback_to_blockhash_slot() -> None:
    with pytest.raises(PR171ChainContextError, match="blockhash source slot"):
        require_simulation_context_slot(
            response_context_slot=None,
            blockhash_source_slot=101,
        )

    missing_context = _context(
        method="simulateTransaction",
        request_hash=HASH_B,
        response_context_present=False,
        context_slot=None,
    )
    bundle = replace(_ready_bundle(), simulation=missing_context)
    report = evaluate_simulation_bundle(bundle)

    assert report.ready is False
    assert "simulation:missing-response-context-slot" in report.reasons


def test_processed_simulation_cannot_satisfy_execution_evidence() -> None:
    processed = _context(
        commitment=Commitment.PROCESSED,
        method="simulateTransaction",
        request_hash=HASH_B,
    )
    report = evaluate_simulation_bundle(replace(_ready_bundle(), simulation=processed))

    assert report.ready is False
    assert "simulation:commitment-below-confirmed" in report.reasons
    assert "coherence:commitment-mismatch" in report.reasons


def test_account_cardinality_mismatch_fails_closed() -> None:
    pre = _context(method="getMultipleAccounts", request_hash=HASH_A)

    with pytest.raises(PR171ChainContextError, match="cardinality mismatch"):
        AccountSetEvidence(
            requested_addresses=("AccountA", "AccountB"),
            returned_addresses=("AccountA",),
            context=pre,
        )


def test_confirmed_context_cannot_be_finalized_accounting() -> None:
    report = evaluate_finalized_accounting_context(
        _context(commitment=Commitment.CONFIRMED, method="getTransaction")
    )

    assert report.ready is False
    assert "settlement:commitment-below-finalized" in report.reasons


def test_cache_key_is_commitment_and_fork_aware() -> None:
    confirmed = _context(commitment=Commitment.CONFIRMED)
    finalized = replace(confirmed, commitment=Commitment.FINALIZED)
    other_fork = replace(confirmed, fork_fingerprint="fork-b/root-95")

    assert build_cache_key(confirmed).to_tuple() != build_cache_key(finalized).to_tuple()
    assert build_cache_key(confirmed).to_tuple() != build_cache_key(other_fork).to_tuple()


def test_fee_from_different_fork_blocks_bundle() -> None:
    fee = _context(
        method="getFeeForMessage",
        request_hash=HASH_C,
        fork="fork-b/root-95",
    )
    report = evaluate_simulation_bundle(replace(_ready_bundle(), fee=fee))

    assert report.ready is False
    assert "coherence:fork-fingerprint-mismatch" in report.reasons


def test_root_or_fork_change_invalidates_dependent_artifacts() -> None:
    before = _context(root_slot=95, finalized_slot=92, fork="fork-a/root-95")
    after = _context(root_slot=101, finalized_slot=98, fork="fork-b/root-101")

    reasons = reorg_invalidation_reasons(before, after)

    assert "fork-fingerprint-changed" in reasons
    assert "root-advanced" in reasons


def test_placeholder_hash_is_rejected() -> None:
    with pytest.raises(PR171ChainContextError, match="placeholder"):
        _context(request_hash="a" * 64)
