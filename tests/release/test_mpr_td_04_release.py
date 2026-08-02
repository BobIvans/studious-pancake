from __future__ import annotations

import sqlite3

import pytest

from src.release import (
    GenerationFenceStore,
    HandoffPhase,
    HandoffState,
    InvalidHandoffTransition,
    ReleaseGenerationIdentity,
    RollbackClass,
    StaleGenerationError,
    decide_rollback,
)


def _identity() -> ReleaseGenerationIdentity:
    digest = "a" * 64
    return ReleaseGenerationIdentity(
        source_sha="b" * 40,
        wheel_sha256=digest,
        image_digest=None,
        schema_registry_sha256=digest,
        config_identity="config-generation-1",
        provider_registry_sha256=digest,
        capability_manifest_sha256=digest,
        production_surface_sha256=digest,
        runtime_authority_sha256=digest,
        dependency_lock_sha256=digest,
        migration_set_sha256=digest,
    )


def test_release_generation_identity_is_deterministic_and_bound() -> None:
    first = _identity()
    second = _identity()
    assert first.generation_id == second.generation_id
    assert len(first.generation_id) == 64


def test_generation_fence_revokes_old_workers() -> None:
    database = sqlite3.connect(":memory:")
    store = GenerationFenceStore(database)
    first = store.activate("generation-a")
    store.assert_authorized(first)
    second = store.activate("generation-b", expected_epoch=first.epoch)
    store.assert_authorized(second)
    with pytest.raises(StaleGenerationError):
        store.assert_authorized(first)


def test_handoff_sequence_is_strict_and_abort_is_terminal() -> None:
    state = HandoffState("upgrade-1", "old", "new")
    for phase in (
        HandoffPhase.ADMISSION_STOPPED,
        HandoffPhase.DRAINED,
        HandoffPhase.BACKED_UP,
        HandoffPhase.MIGRATED,
        HandoffPhase.ACTIVATED,
        HandoffPhase.VERIFIED,
        HandoffPhase.RESUMED,
    ):
        state = state.transition(phase)
    assert state.phase is HandoffPhase.RESUMED
    with pytest.raises(InvalidHandoffTransition):
        state.transition(HandoffPhase.ABORTED)


def test_rollback_requires_immutable_artifact_backup_and_compatibility() -> None:
    allowed = decide_rollback(
        storage_backward_readable=True,
        configuration_compatible=True,
        provider_contracts_compatible=True,
        destructive_contraction=False,
        immutable_previous_artifact_available=True,
        verified_backup_available=True,
    )
    assert allowed.allowed is True
    assert allowed.rollback_class is RollbackClass.SCHEMA_COMPATIBLE

    blocked = decide_rollback(
        storage_backward_readable=True,
        configuration_compatible=True,
        provider_contracts_compatible=True,
        destructive_contraction=True,
        immutable_previous_artifact_available=True,
        verified_backup_available=True,
    )
    assert blocked.allowed is False
    assert blocked.rollback_class is RollbackClass.FORWARD_RECOVERY_ONLY
