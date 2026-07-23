from __future__ import annotations

import sqlite3

import pytest

from src.canonical_control_plane_pr195 import (
    CanonicalControlPlaneStore,
    ConfigContractError,
    ConfigGeneration,
    FenceLostError,
    IllegalTransitionError,
    ManualTrustedClock,
    TransitionConflictError,
    UnknownSchemaVersionError,
    sha256_text,
)

pytestmark = pytest.mark.unit


def _hash(name: str) -> str:
    return sha256_text(f"test:{name}")


def _generation(active: bool = True) -> ConfigGeneration:
    return ConfigGeneration(
        generation_hash=_hash("generation"),
        release_hash=_hash("release"),
        policy_hash=_hash("policy"),
        approved_by="reviewer@example.invalid",
        evidence_hash=_hash("evidence"),
        active=active,
    )


def _store(tmp_path, *, clock: ManualTrustedClock | None = None):
    store = CanonicalControlPlaneStore(
        tmp_path / "control.sqlite",
        trusted_clock=clock or ManualTrustedClock(),
    )
    store.record_config_generation(_generation())
    return store


def test_pr195_migrates_with_backup_and_schema_fingerprint(tmp_path) -> None:
    path = tmp_path / "control.sqlite"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE legacy_attempts(attempt_id TEXT PRIMARY KEY)")
    db.execute("INSERT INTO legacy_attempts VALUES('old')")
    db.commit()
    db.close()

    with CanonicalControlPlaneStore(path, trusted_clock=ManualTrustedClock()) as store:
        assert store.backup_manifest is not None
        backup_path = tmp_path / store.backup_manifest.path.split("/")[-1]
        assert backup_path.exists()
        fingerprint = store.schema_fingerprint()
        assert fingerprint.schema_version == "pr195.canonical-control-plane.v1"
        store.assert_schema_fingerprint()


def test_pr195_refuses_unknown_future_schema(tmp_path) -> None:
    path = tmp_path / "future.sqlite"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE pr195_migrations("
        "version INTEGER PRIMARY KEY,name TEXT,checksum TEXT,"
        "schema_fingerprint TEXT,backup_manifest_json TEXT,applied_utc_ns INTEGER)"
    )
    db.execute(
        "INSERT INTO pr195_migrations VALUES(999,'future','x','x',NULL,1)"
    )
    db.commit()
    db.close()

    with pytest.raises(UnknownSchemaVersionError):
        CanonicalControlPlaneStore(path, trusted_clock=ManualTrustedClock())


def test_pr195_atomic_transition_rejects_stale_revision_without_event(tmp_path) -> None:
    with _store(tmp_path) as store:
        attempt = store.create_attempt(
            attempt_id="attempt-a",
            generation=1,
            idempotency_key="create-a",
            evidence={"source": "unit"},
        )
        fence = store.acquire_fence(
            "attempt:attempt-a",
            owner_id="worker-a",
            ttl_ns=1_000_000,
        )
        first = store.append_transition(
            attempt_id=attempt.attempt_id,
            expected_revision=0,
            target_state="planned",
            idempotency_key="transition-planned",
            fence=fence,
            reason_code="PLANNED",
            evidence={"plan_hash": _hash("plan")},
        )

        assert first.revision == 1
        with pytest.raises(TransitionConflictError):
            store.append_transition(
                attempt_id=attempt.attempt_id,
                expected_revision=0,
                target_state="config_bound",
                idempotency_key="stale-transition",
                fence=fence,
                reason_code="STALE",
            )

        events = store.event_chain(attempt.attempt_id)
        assert [event.revision for event in events] == [0, 1]
        assert store.get_attempt(attempt.attempt_id).revision == 1


def test_pr195_idempotent_transition_replays_same_event(tmp_path) -> None:
    with _store(tmp_path) as store:
        store.create_attempt(
            attempt_id="attempt-idem",
            generation=1,
            idempotency_key="create-idem",
        )
        fence = store.acquire_fence(
            "attempt:attempt-idem",
            owner_id="worker-a",
            ttl_ns=1_000_000,
        )
        first = store.append_transition(
            attempt_id="attempt-idem",
            expected_revision=0,
            target_state="planned",
            idempotency_key="same-transition",
            fence=fence,
            reason_code="PLANNED",
        )
        replay = store.append_transition(
            attempt_id="attempt-idem",
            expected_revision=0,
            target_state="planned",
            idempotency_key="same-transition",
            fence=fence,
            reason_code="PLANNED",
        )

        assert replay == first
        assert len(store.event_chain("attempt-idem")) == 2


def test_pr195_state_machine_bypass_is_impossible(tmp_path) -> None:
    with _store(tmp_path) as store:
        store.create_attempt(
            attempt_id="attempt-bypass",
            generation=1,
            idempotency_key="create-bypass",
        )
        fence = store.acquire_fence(
            "attempt:attempt-bypass",
            owner_id="worker-a",
            ttl_ns=1_000_000,
        )

        with pytest.raises(IllegalTransitionError):
            store.append_transition(
                attempt_id="attempt-bypass",
                expected_revision=0,
                target_state="submission_intent_recorded",
                idempotency_key="direct-submit",
                fence=fence,
                reason_code="DIRECT_SUBMIT",
            )

        attempt = store.get_attempt("attempt-bypass")
        assert attempt.state == "created"
        assert attempt.revision == 0
        assert len(store.event_chain("attempt-bypass")) == 1


def test_pr195_current_row_reconstructs_from_event_history(tmp_path) -> None:
    with _store(tmp_path) as store:
        store.create_attempt(
            attempt_id="attempt-replay",
            generation=1,
            idempotency_key="create-replay",
        )
        fence = store.acquire_fence(
            "attempt:attempt-replay",
            owner_id="worker-a",
            ttl_ns=1_000_000,
        )
        store.append_transition(
            attempt_id="attempt-replay",
            expected_revision=0,
            target_state="planned",
            idempotency_key="planned-replay",
            fence=fence,
            reason_code="PLANNED",
        )
        store.append_transition(
            attempt_id="attempt-replay",
            expected_revision=1,
            target_state="config_bound",
            idempotency_key="config-replay",
            fence=fence,
            reason_code="CONFIG_BOUND",
            evidence={"config_generation_hash": _hash("generation")},
        )

        reconstructed = store.reconstruct_attempt_state("attempt-replay")
        assert reconstructed.state == "config_bound"
        assert reconstructed.revision == 2


def test_pr195_boot_domain_change_invalidates_old_fence(tmp_path) -> None:
    clock = ManualTrustedClock(boot_id="boot-a", process_generation=1)
    with _store(tmp_path, clock=clock) as store:
        store.create_attempt(
            attempt_id="attempt-clock",
            generation=1,
            idempotency_key="create-clock",
        )
        fence = store.acquire_fence(
            "attempt:attempt-clock",
            owner_id="worker-a",
            ttl_ns=1_000_000,
        )
        clock.reboot(boot_id="boot-b", process_generation=2)

        with pytest.raises(FenceLostError):
            store.append_transition(
                attempt_id="attempt-clock",
                expected_revision=0,
                target_state="planned",
                idempotency_key="planned-clock",
                fence=fence,
                reason_code="PLANNED",
            )

        replacement = store.acquire_fence(
            "attempt:attempt-clock",
            owner_id="worker-a",
            ttl_ns=1_000_000,
        )
        assert replacement.boot_id == "boot-b"
        assert replacement.fencing_token == fence.fencing_token + 1


def test_pr195_unknown_flashloan_env_is_fatal_only_in_production(tmp_path) -> None:
    with _store(tmp_path) as store:
        env = {
            "FLASHLOAN_RUNTIME_MODE": "paper",
            "FLASHLOAN_RUNTME_MODE": "typo",
            "OTHER": "ignored",
        }

        with pytest.raises(ConfigContractError):
            store.validate_unknown_flashloan_env(
                env,
                allowed_names={"FLASHLOAN_RUNTIME_MODE"},
                production=True,
            )

        assert store.validate_unknown_flashloan_env(
            env,
            allowed_names={"FLASHLOAN_RUNTIME_MODE"},
            production=False,
        ) == ("FLASHLOAN_RUNTME_MODE",)


def test_pr195_latch_clear_requires_exact_latch_and_approval(tmp_path) -> None:
    with _store(tmp_path) as store:
        store.open_latch(
            latch_id="latch-a",
            reason_code="CLOCK_ANOMALY",
            evidence={"incident": "clock"},
        )

        with pytest.raises(TransitionConflictError):
            store.clear_latch(
                latch_id="latch-b",
                acknowledged_by="operator-a",
                clear_approval_hash=_hash("approval"),
            )

        store.clear_latch(
            latch_id="latch-a",
            acknowledged_by="operator-a",
            clear_approval_hash=_hash("approval"),
        )
        assert store.live_capability_allowed() is False
