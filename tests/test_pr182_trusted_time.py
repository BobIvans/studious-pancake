from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.durability import (
    AttemptKey,
    ClockSafeDurableLifecycleStore,
    DurableLifecycleStore,
    LeaseLostError,
)
from src.security.signer_policy import (
    SignerPolicyError,
    UnsignedMessage,
    build_signer_policy,
)
from src.time_authority import (
    ClockDomainMismatchError,
    ClockUnhealthyError,
    MonotonicDeadline,
    PersistedExpiry,
    SystemTimeAuthority,
    TimeSourceStatus,
)


@dataclass
class MutableClock:
    utc_ns: int = 1_000_000_000
    monotonic_ns: int = 500_000_000

    def utc(self) -> int:
        return self.utc_ns

    def monotonic(self) -> int:
        return self.monotonic_ns


def authority(
    clock: MutableClock,
    *,
    boot_id: str = "boot-a",
    status: TimeSourceStatus = TimeSourceStatus.SYNCHRONIZED,
    max_step_ns: int = 1_000,
) -> SystemTimeAuthority:
    return SystemTimeAuthority(
        boot_id=boot_id,
        source_status=status,
        max_uncertainty_ns=0,
        max_step_ns=max_step_ns,
        utc_clock_ns=clock.utc,
        monotonic_clock_ns=clock.monotonic,
    )


def test_public_store_is_clock_safe_authority() -> None:
    assert DurableLifecycleStore is ClockSafeDurableLifecycleStore


def test_wall_clock_rollback_cannot_extend_or_validate_lease(tmp_path) -> None:
    clock = MutableClock()
    store = DurableLifecycleStore(
        tmp_path / "lifecycle.sqlite",
        time_authority=authority(clock),
    )
    token = store.acquire_lease("attempt:one", owner_id="owner-a", ttl_ns=10_000)

    clock.monotonic_ns += 100
    clock.utc_ns -= 1_000_000

    with pytest.raises(ClockUnhealthyError):
        store._verify_lease(token, "attempt:one")
    status = store.trusted_time_status()
    assert status["live_permit_issuance_allowed"] is False
    assert status["incident_count"] >= 1


def test_forward_wall_step_freezes_ownership_transition(tmp_path) -> None:
    clock = MutableClock()
    store = DurableLifecycleStore(
        tmp_path / "lifecycle.sqlite",
        time_authority=authority(clock, max_step_ns=100),
    )
    store.acquire_lease("attempt:one", owner_id="owner-a", ttl_ns=10_000)

    clock.monotonic_ns += 1
    clock.utc_ns += 10_000

    with pytest.raises(ClockUnhealthyError):
        store.acquire_lease("attempt:two", owner_id="owner-b", ttl_ns=10_000)


def test_boot_change_invalidates_old_monotonic_lease_and_fences_new_owner(
    tmp_path,
) -> None:
    path = tmp_path / "lifecycle.sqlite"
    first_clock = MutableClock()
    first = DurableLifecycleStore(
        path,
        time_authority=authority(first_clock, boot_id="boot-a"),
    )
    old_token = first.acquire_lease(
        "attempt:one", owner_id="owner-a", ttl_ns=1_000_000
    )
    first.close()

    second_clock = MutableClock(
        utc_ns=first_clock.utc_ns + 100,
        monotonic_ns=first_clock.monotonic_ns + 100,
    )
    second = DurableLifecycleStore(
        path,
        time_authority=authority(second_clock, boot_id="boot-b"),
    )
    new_token = second.acquire_lease(
        "attempt:one", owner_id="owner-b", ttl_ns=1_000_000
    )

    assert new_token.fencing_token == old_token.fencing_token + 1
    with pytest.raises(LeaseLostError):
        second._verify_lease(old_token, "attempt:one")
    assert second.trusted_time_status()["incident_count"] == 1


def test_same_boot_outbox_claim_expiry_uses_monotonic_not_wall_time(tmp_path) -> None:
    clock = MutableClock()
    store = DurableLifecycleStore(
        tmp_path / "lifecycle.sqlite",
        time_authority=authority(clock),
    )
    store.create_attempt(
        AttemptKey("opportunity", "a" * 64, 1),
        idempotency_key="create-opportunity",
    )

    first = store.claim_outbox(
        topic="lifecycle.event", owner_id="worker-a", lease_ns=100
    )
    assert len(first) == 1

    # UTC does not move. Correctness still expires because same-boot monotonic time
    # advanced beyond the claim deadline.
    clock.monotonic_ns += 101
    second = store.claim_outbox(
        topic="lifecycle.event", owner_id="worker-b", lease_ns=100
    )
    assert len(second) == 1
    assert second[0].fencing_token > first[0].fencing_token
    assert store.complete_outbox(first[0], owner_id="worker-a") is False
    assert store.complete_outbox(second[0], owner_id="worker-b") is True


def test_persisted_expiry_is_invalid_after_boot_change() -> None:
    first_clock = MutableClock()
    first_authority = authority(first_clock, boot_id="boot-a")
    expiry = PersistedExpiry.issue(first_authority, ttl_ns=1_000)

    second_clock = MutableClock(
        utc_ns=first_clock.utc_ns + 10,
        monotonic_ns=first_clock.monotonic_ns + 10,
    )
    second_snapshot = authority(second_clock, boot_id="boot-b").snapshot()

    assert expiry.valid_at(second_snapshot) is False


def test_monotonic_deadline_rejects_cross_boot_comparison() -> None:
    clock = MutableClock()
    deadline = MonotonicDeadline(
        boot_id="boot-a",
        process_generation=1,
        started_at_monotonic_ns=clock.monotonic_ns,
        expires_at_monotonic_ns=clock.monotonic_ns + 100,
    )
    other = authority(clock, boot_id="boot-b").snapshot()

    with pytest.raises(ClockDomainMismatchError):
        deadline.expired(other)


def test_unsynchronized_clock_blocks_clock_safe_signer_permit() -> None:
    clock = MutableClock()
    policy = build_signer_policy(
        ["allowed-program"],
        time_authority=authority(
            clock,
            status=TimeSourceStatus.UNSYNCHRONIZED,
        ),
    )

    with pytest.raises(ClockUnhealthyError):
        policy.evaluate(
            unsigned_message=UnsignedMessage(
                b"message",
                ("allowed-program",),
            ),
            signer_reference="file:/run/secrets/signer",
        )


def test_clock_safe_signer_permit_expires_monotonically() -> None:
    clock = MutableClock()
    trusted = authority(clock)
    policy = build_signer_policy(
        ["allowed-program"],
        time_authority=trusted,
        permit_ttl_ns=100,
    )
    permit = policy.evaluate(
        unsigned_message=UnsignedMessage(b"message", ("allowed-program",)),
        signer_reference="file:/run/secrets/signer",
    )
    assert permit.clock_safe is True
    policy.assert_permit_current(permit)

    clock.monotonic_ns += 101
    clock.utc_ns += 101
    with pytest.raises(SignerPolicyError):
        policy.assert_permit_current(permit)


def test_legacy_signer_permit_cannot_be_promoted_to_clock_safe() -> None:
    legacy = build_signer_policy(["allowed-program"]).evaluate(
        unsigned_message=UnsignedMessage(b"message", ("allowed-program",)),
        signer_reference="file:/run/secrets/signer",
        now=1.0,
    )
    verifier = build_signer_policy(
        ["allowed-program"],
        time_authority=authority(MutableClock()),
    )

    assert legacy.clock_safe is False
    with pytest.raises(SignerPolicyError, match="not clock-safe"):
        verifier.assert_permit_current(legacy)
