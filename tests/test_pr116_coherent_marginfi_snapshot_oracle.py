from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from src.providers.marginfi.coherent_snapshot import (
    MAXIMUM_SNAPSHOT_CAPABILITY,
    MarginfiAccountRole,
    MarginfiCoherentSnapshotError,
    MarginfiCoherentSnapshotPackage,
    MarginfiOracleEvidence,
    MarginfiSnapshotAccountEvidence,
    RpcBatchEvidence,
    assert_marginfi_coherent_snapshot,
    calculate_pr116_state_fingerprint,
    evaluate_marginfi_coherent_snapshot,
)

SLOT = 1_234_567
ROOTED_SLOT = SLOT + 32
SHA_A = "0123456789abcdef" * 4
SHA_B = "abcdef0123456789" * 4
SHA_C = "00112233445566778899aabbccddeeff" * 2
SHA_D = "ffeeddccbbaa99887766554433221100" * 2
SHA_E = "1234567890abcdef" * 4
SHA_F = "fedcba0987654321" * 4
SHA_G = "13579bdf2468ace0" * 4
SHA_H = "02468ace13579bdf" * 4
SHA_I = "89abcdef01234567" * 4
SHA_J = "76543210fedcba98" * 4
SHA_K = "a1b2c3d4e5f60718" * 4
SHA_L = "0f1e2d3c4b5a6978" * 4
SHA_M = "1122334455667788" * 4
SHA_N = "8877665544332211" * 4


def _account(
    address: str,
    role: MarginfiAccountRole,
    sha256: str,
    *,
    slot: int = SLOT,
    executable: bool = False,
) -> MarginfiSnapshotAccountEvidence:
    return MarginfiSnapshotAccountEvidence(
        address=address,
        owner=f"owner-{role.value}",
        role=role,
        slot=slot,
        data_sha256=sha256,
        decoded_sha256=sha256,
        lamports=10_000,
        executable=executable,
    )


def _accounts(*, slot: int = SLOT) -> tuple[MarginfiSnapshotAccountEvidence, ...]:
    return (
        _account(
            "program", MarginfiAccountRole.PROGRAM, SHA_A, slot=slot, executable=True
        ),
        _account("programdata", MarginfiAccountRole.PROGRAMDATA, SHA_B, slot=slot),
        _account("group", MarginfiAccountRole.GROUP, SHA_C, slot=slot),
        _account("margin", MarginfiAccountRole.MARGIN_ACCOUNT, SHA_D, slot=slot),
        _account("target-bank", MarginfiAccountRole.TARGET_BANK, SHA_E, slot=slot),
        _account("active-bank", MarginfiAccountRole.ACTIVE_BANK, SHA_F, slot=slot),
        _account("vault", MarginfiAccountRole.LIQUIDITY_VAULT, SHA_G, slot=slot),
        _account("oracle-target", MarginfiAccountRole.ORACLE, SHA_H, slot=slot),
        _account("oracle-active", MarginfiAccountRole.ORACLE, SHA_I, slot=slot),
    )


def _oracle(
    oracle_address: str,
    bank_address: str,
    sha256: str,
    *,
    publish_slot: int = SLOT - 2,
    context_slot: int = SLOT,
    relationship_verified: bool = True,
) -> MarginfiOracleEvidence:
    return MarginfiOracleEvidence(
        oracle_address=oracle_address,
        bank_address=bank_address,
        source="pyth-pinned-fixture",
        owner="oracle-owner",
        price_mantissa=25_000_000,
        exponent=-6,
        confidence_mantissa=100,
        publish_slot=publish_slot,
        context_slot=context_slot,
        max_staleness_slots=10,
        relationship_verified=relationship_verified,
        evidence_sha256=sha256,
    )


def _batch(
    accounts: tuple[MarginfiSnapshotAccountEvidence, ...],
    *,
    batch_id: str = "batch-1",
    context_slot: int = SLOT,
    addresses: tuple[str, ...] | None = None,
) -> RpcBatchEvidence:
    return RpcBatchEvidence(
        batch_id=batch_id,
        context_slot=context_slot,
        min_context_slot=SLOT - 10,
        rooted_slot=ROOTED_SLOT,
        commitment="confirmed",
        addresses=addresses or tuple(account.address for account in accounts),
        response_sha256=SHA_J,
    )


def _package(**overrides) -> MarginfiCoherentSnapshotPackage:
    accounts = overrides.pop("accounts", _accounts())
    values = {
        "context_slot": SLOT,
        "min_context_slot": SLOT - 10,
        "rooted_slot": ROOTED_SLOT,
        "rpc_batches": (_batch(accounts),),
        "accounts": accounts,
        "oracle_evidence": (
            _oracle("oracle-target", "target-bank", SHA_K),
            _oracle("oracle-active", "active-bank", SHA_L),
        ),
        "risk_remaining_account_order": ("target-bank", "active-bank"),
        "snapshot_fingerprint_sha256": calculate_pr116_state_fingerprint(accounts),
        "pr101_complete_evidence_sha256": SHA_M,
        "pr115_simulation_evidence_sha256": SHA_N,
        "pr101_shadow_execution_capable": True,
        "pr115_simulation_owned_decoding_ready": True,
        "multi_call_slot_vector_verified": True,
        "account_set_stable_after_discovery": True,
        "human_reviewed": True,
        "live_allowed": False,
        "assembled_at": datetime(2026, 7, 21, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return MarginfiCoherentSnapshotPackage(**values)


def test_pr116_complete_snapshot_is_coherent_but_never_live() -> None:
    result = evaluate_marginfi_coherent_snapshot(_package())

    assert result.state == MAXIMUM_SNAPSHOT_CAPABILITY
    assert result.coherent_snapshot_capable is True
    assert result.live_execution_allowed is False
    assert result.blockers == ()
    assert result.metrics_summary["banks"] == 2
    assert result.metrics_summary["oracles"] == 2


def test_pr116_rejects_mixed_slot_snapshot_bytes() -> None:
    accounts = list(_accounts())
    accounts[1] = replace(accounts[1], slot=SLOT - 1)
    mixed_accounts = tuple(accounts)

    result = evaluate_marginfi_coherent_snapshot(
        _package(
            accounts=mixed_accounts,
            rpc_batches=(_batch(mixed_accounts),),
            snapshot_fingerprint_sha256=calculate_pr116_state_fingerprint(
                mixed_accounts
            ),
        )
    )

    assert result.state == "blocked"
    assert "PR116_ACCOUNT_SLOT_MISMATCH" in result.blockers
    assert result.live_execution_allowed is False


def test_pr116_rejects_mismatched_rpc_batch_context() -> None:
    package = _package()

    result = evaluate_marginfi_coherent_snapshot(
        replace(
            package,
            rpc_batches=(
                _batch(tuple(package.accounts), batch_id="batch-1"),
                _batch(
                    tuple(package.accounts),
                    batch_id="batch-2",
                    context_slot=SLOT + 1,
                ),
            ),
        )
    )

    assert "PR116_BATCH_CONTEXT_SLOT_MISMATCH" in result.blockers


def test_pr116_requires_multi_call_slot_vector_when_split_batches() -> None:
    accounts = tuple(_accounts())
    first = tuple(account.address for account in accounts[:4])
    second = tuple(account.address for account in accounts[4:])

    result = evaluate_marginfi_coherent_snapshot(
        _package(
            rpc_batches=(
                _batch(accounts, batch_id="discovery", addresses=first),
                _batch(accounts, batch_id="coherent-read", addresses=second),
            ),
            multi_call_slot_vector_verified=False,
        )
    )

    assert "PR116_MULTI_CALL_SLOT_VECTOR_NOT_VERIFIED" in result.blockers


def test_pr116_requires_oracle_for_every_bank() -> None:
    result = evaluate_marginfi_coherent_snapshot(
        _package(oracle_evidence=(_oracle("oracle-target", "target-bank", SHA_K),))
    )

    assert "PR116_BANK_WITHOUT_ORACLE_EVIDENCE" in result.blockers


def test_pr116_rejects_stale_or_unrelated_oracle_evidence() -> None:
    result = evaluate_marginfi_coherent_snapshot(
        _package(
            oracle_evidence=(
                _oracle(
                    "oracle-target",
                    "target-bank",
                    SHA_K,
                    publish_slot=SLOT - 100,
                ),
                _oracle(
                    "oracle-active",
                    "active-bank",
                    SHA_L,
                    relationship_verified=False,
                ),
            )
        )
    )

    assert "PR116_ORACLE_STALE:oracle-target" in result.blockers
    assert "PR116_ORACLE_RELATIONSHIP_UNVERIFIED:oracle-active" in result.blockers


def test_pr116_rejects_fingerprint_that_omits_slot_vector() -> None:
    result = evaluate_marginfi_coherent_snapshot(
        _package(snapshot_fingerprint_sha256=SHA_A)
    )

    assert "PR116_STATE_FINGERPRINT_MISMATCH" in result.blockers


def test_pr116_blocks_without_upstream_evidence_and_human_review() -> None:
    result = evaluate_marginfi_coherent_snapshot(
        _package(
            pr101_shadow_execution_capable=False,
            pr115_simulation_owned_decoding_ready=False,
            human_reviewed=False,
            live_allowed=True,
        )
    )

    assert "PR101_NOT_SHADOW_CAPABLE" in result.blockers
    assert "PR115_SIMULATION_DECODING_NOT_READY" in result.blockers
    assert "PR116_HUMAN_REVIEW_MISSING" in result.blockers
    assert "PR116_LIVE_ALLOWED_TRUE" in result.blockers
    assert result.live_execution_allowed is False


def test_pr116_assertion_uses_stable_fail_closed_prefix() -> None:
    with pytest.raises(MarginfiCoherentSnapshotError) as exc_info:
        assert_marginfi_coherent_snapshot(_package(snapshot_fingerprint_sha256=SHA_A))

    assert str(exc_info.value).startswith("PR116_MARGINFI_SNAPSHOT_BLOCKED:")
