from __future__ import annotations

import sqlite3

import pytest

from src.durability.unified_authority_pr02 import UnifiedLifecycleAuthority
from src.release_gate.mpr2612_durable_release import (
    DurableReleaseError,
    MPR2612DurableReleaseAuthority,
)
from src.release_gate.mpr31_final_promotion_gate import (
    FinalReleaseDecision,
    ReleaseApproval,
    ReleaseState,
    TARGET_PRODUCT_STATE,
)

D = "a" * 64
D2 = "b" * 64


def _approval(principal: str, key: str) -> ReleaseApproval:
    return ReleaseApproval(
        principal_id=principal,
        public_key_id=key,
        role="release-reviewer",
        release_id="release-A",
        proposal_digest=D,
        qualification_digest=D2,
        issued_at_ns=1,
        not_before_ns=2,
        expires_at_ns=100,
        signature="cryptographic-fixture",
    )


def _approvals() -> tuple[ReleaseApproval, ...]:
    return (
        _approval("human-one", "key-one"),
        _approval("human-two", "key-two"),
    )


def _decision() -> FinalReleaseDecision:
    return FinalReleaseDecision(
        state=ReleaseState.RELEASED_PRODUCTION_DEFAULT_OFF,
        allowed=True,
        reason_codes=(),
        release_id="release-A",
        proposal_digest=D,
        qualification_digest=D2,
        production_ready=True,
        release_claim_allowed=True,
        product_state=TARGET_PRODUCT_STATE,
        live_enabled=False,
        unrestricted_live_allowed=False,
        automatic_scale_up_allowed=False,
    )


@pytest.fixture
def durable(tmp_path):
    lifecycle = UnifiedLifecycleAuthority(
        tmp_path / "authority.sqlite3",
        release_digest=D,
        policy_bundle_hash=D,
    )
    authority = MPR2612DurableReleaseAuthority(lifecycle.db)
    with lifecycle.db:
        lifecycle.db.execute("BEGIN IMMEDIATE")
        authority.install_schema()
    yield lifecycle, authority
    lifecycle.close()


def _qualify(lifecycle, authority, *, expected_revision: int = 0) -> None:
    with lifecycle.db:
        lifecycle.db.execute("BEGIN IMMEDIATE")
        authority.qualify_default_off(
            release_id="release-A",
            qualification_digest=D2,
            expected_revision=expected_revision,
        )


def _promote(
    lifecycle,
    authority,
    *,
    expected_generation: int = 0,
    expected_revision: int = 1,
):
    with lifecycle.db:
        lifecycle.db.execute("BEGIN IMMEDIATE")
        return authority.promote(
            _decision(),
            _approvals(),
            expected_generation=expected_generation,
            expected_revision=expected_revision,
        )


def test_promotion_requires_caller_owned_transaction(durable) -> None:
    _lifecycle, authority = durable

    with pytest.raises(
        DurableReleaseError,
        match="CALLER_TRANSACTION_REQUIRED",
    ):
        authority.qualify_default_off(
            release_id="release-A",
            qualification_digest=D2,
            expected_revision=0,
        )


def test_atomic_promotion_increments_generation_once_and_stays_default_off(
    durable,
) -> None:
    lifecycle, authority = durable
    _qualify(lifecycle, authority)
    receipt = _promote(lifecycle, authority)

    state = authority.state()
    assert receipt.verify()
    assert receipt.release_generation == 1
    assert state["release_generation"] == 1
    assert state["state"] == ReleaseState.RELEASED_PRODUCTION_DEFAULT_OFF.value
    assert state["live_enabled"] == 0
    assert state["unrestricted_live_allowed"] == 0
    assert state["automatic_scale_up_allowed"] == 0


def test_crash_before_commit_leaves_release_unpromoted(durable) -> None:
    lifecycle, authority = durable
    _qualify(lifecycle, authority)

    lifecycle.db.execute("BEGIN IMMEDIATE")
    authority.promote(
        _decision(),
        _approvals(),
        expected_generation=0,
        expected_revision=1,
    )
    lifecycle.db.rollback()

    state = authority.state()
    assert state["state"] == ReleaseState.QUALIFIED_DEFAULT_OFF.value
    assert state["release_generation"] == 0


def test_exact_post_commit_replay_returns_same_receipt_without_increment(
    durable,
) -> None:
    lifecycle, authority = durable
    _qualify(lifecycle, authority)
    first = _promote(lifecycle, authority)

    with lifecycle.db:
        lifecycle.db.execute("BEGIN IMMEDIATE")
        replay = authority.promote(
            _decision(),
            _approvals(),
            expected_generation=0,
            expected_revision=1,
        )

    assert replay == first
    assert authority.state()["release_generation"] == 1


def test_consumed_approval_cannot_promote_another_generation(durable) -> None:
    lifecycle, authority = durable
    _qualify(lifecycle, authority)
    _promote(lifecycle, authority)

    with lifecycle.db:
        lifecycle.db.execute("BEGIN IMMEDIATE")
        authority.suspend(
            reason_code="safety",
            expected_revision=2,
        )

    _qualify(lifecycle, authority, expected_revision=3)
    with pytest.raises(
        DurableReleaseError,
        match="APPROVAL_ALREADY_CONSUMED",
    ):
        _promote(
            lifecycle,
            authority,
            expected_generation=1,
            expected_revision=4,
        )


def test_receipt_is_immutable_and_independently_recomputed(durable) -> None:
    lifecycle, authority = durable
    _qualify(lifecycle, authority)
    receipt = _promote(lifecycle, authority)

    reread = authority.read_receipt(receipt.receipt_digest)
    assert reread.verify()
    with pytest.raises(
        sqlite3.IntegrityError,
        match="MPR2612_IMMUTABLE_RECEIPT",
    ):
        with lifecycle.db:
            lifecycle.db.execute(
                "UPDATE mpr2612_release_receipt SET live_enabled=0 "
                "WHERE receipt_digest=?",
                (receipt.receipt_digest,),
            )


def test_suspend_never_auto_rearms_after_restart(durable) -> None:
    lifecycle, authority = durable
    _qualify(lifecycle, authority)
    _promote(lifecycle, authority)

    with lifecycle.db:
        lifecycle.db.execute("BEGIN IMMEDIATE")
        authority.suspend(
            reason_code="hard-latch",
            expected_revision=2,
        )

    assert authority.state()["state"] == ReleaseState.RELEASE_SUSPENDED.value
    reopened = MPR2612DurableReleaseAuthority(lifecycle.db)
    assert reopened.state()["state"] == ReleaseState.RELEASE_SUSPENDED.value


def test_revoke_is_terminal_and_rollback_cannot_resurrect(durable) -> None:
    lifecycle, authority = durable
    _qualify(lifecycle, authority)
    receipt = _promote(lifecycle, authority)

    with lifecycle.db:
        lifecycle.db.execute("BEGIN IMMEDIATE")
        authority.revoke(
            reason_code="operator-revoke",
            expected_revision=2,
        )
    assert authority.state()["state"] == ReleaseState.RELEASE_REVOKED.value

    with pytest.raises(
        DurableReleaseError,
        match="TERMINAL_RELEASE_STATE",
    ):
        with lifecycle.db:
            lifecycle.db.execute("BEGIN IMMEDIATE")
            authority.rollback(
                target_receipt_digest=receipt.receipt_digest,
                reason_code="rollback",
                expected_revision=3,
            )
