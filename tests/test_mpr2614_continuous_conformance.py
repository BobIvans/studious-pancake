from __future__ import annotations

from dataclasses import replace

from src.operations.mpr2613_guarded_operations import (
    AcceptedReleaseIdentity,
    MonetaryCaps,
    OperatingEnvelope,
    ResourceCaps,
    ScaleTier,
)
from src.operations.mpr2614_continuous_conformance import (
    ConformancePolicy,
    ReleaseConformancePin,
    RuntimeConformanceObservation,
    evaluate_runtime_conformance,
)
from src.operations.pr201_observability_readiness import (
    DeploymentHardeningSnapshot,
    ManagementReadinessSnapshot,
    ReadinessSignal,
    ReleaseImageManifest,
    operator_readiness_report,
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
IMAGE = "ghcr.io/bobivans/studious-pancake@sha256:" + HASH_1
OTHER_IMAGE = "ghcr.io/bobivans/studious-pancake@sha256:" + HASH_2
NOW_MS = 1_788_955_200_000  # 2026-09-09T12:00:00Z
MONO_NS = 10_000_000_000


def _release(**overrides: object) -> AcceptedReleaseIdentity:
    values = {
        "release_decision_hash": HASH_A,
        "tree_hash": HASH_B,
        "wheel_hash": HASH_C,
        "image_hash": HASH_1,
        "config_hash": HASH_D,
        "policy_hash": HASH_E,
        "schema_hash": HASH_F,
        "profile_hash": HASH_3,
        "accepted_at_utc": "2026-09-09T00:00:00Z",
        "expires_at_utc": "2026-09-11T00:00:00Z",
        "accepted": True,
    }
    values.update(overrides)
    return AcceptedReleaseIdentity(**values)


def _envelope(release: AcceptedReleaseIdentity | None = None, **overrides: object) -> OperatingEnvelope:
    values = {
        "release": release or _release(),
        "cluster_genesis_hash": HASH_4,
        "wallet_identity_hash": HASH_5,
        "payer_identity_hash": HASH_6,
        "strategy": "circular_arbitrage",
        "lender": "MarginFi",
        "router": "Jupiter",
        "program_set_hash": HASH_7,
        "provider_set_hash": HASH_8,
        "credential_generation_hash": HASH_A,
        "signer_generation_hash": HASH_B,
        "submission_generation_hash": HASH_C,
        "monetary_caps": MonetaryCaps(
            principal_atoms=1_000_000,
            fee_atoms=100_000,
            tip_atoms=100_000,
            rent_atoms=100_000,
            realized_loss_atoms=100_000,
            unresolved_exposure_atoms=100_000,
            protected_reserve_atoms=100_000,
        ),
        "resource_caps": ResourceCaps(
            max_attempts=3,
            max_concurrency=1,
            max_pending_reconciliations=2,
            max_db_backlog=64,
        ),
        "tier": ScaleTier.CANARY,
        "issued_at_utc": "2026-09-09T00:00:00Z",
        "expires_at_utc": "2026-09-10T00:00:00Z",
        "generation": 7,
    }
    values.update(overrides)
    return OperatingEnvelope(**values)


def _readiness(**overrides: object) -> ManagementReadinessSnapshot:
    values = {
        "run_id": "runtime/2614",
        "source_commit": HASH_A,
        "image_digest": IMAGE,
        "config_hash": HASH_D,
        "contract_evidence_hash": HASH_E,
        "observed_at_ms": NOW_MS - 100,
        "liveness_healthy": True,
        "safe_idle_allowed": True,
        "data_ready": True,
        "paper_worker_alive": True,
        "paper_workload_fresh": True,
        "protocol_ready": True,
        "db_healthy": True,
        "outbox_healthy": True,
        "signals": (
            ReadinessSignal(
                name="mandatory-runtime",
                healthy=True,
                mandatory=True,
                stale=False,
                evidence_hash=HASH_F,
            ),
        ),
    }
    values.update(overrides)
    return ManagementReadinessSnapshot(**values)


def _deployment(**overrides: object) -> DeploymentHardeningSnapshot:
    values = {
        "image_digest": IMAGE,
        "sbom_sha256": HASH_A,
        "attestation_sha256": HASH_B,
        "seccomp_profile_sha256": HASH_C,
        "resource_limits_sha256": HASH_D,
        "non_root_user": True,
        "read_only_rootfs": True,
        "cap_drop_all": True,
        "no_new_privileges": True,
        "persistent_volume_owner_uid": 10001,
    }
    values.update(overrides)
    return DeploymentHardeningSnapshot(**values)


def _pin(release: AcceptedReleaseIdentity | None = None, **overrides: object) -> ReleaseConformancePin:
    values = {
        "release": release or _release(),
        "release_generation": 11,
        "source_commit": HASH_A,
        "runtime_image_digest": IMAGE,
        "contract_evidence_hash": HASH_E,
        "qualification_digest": HASH_4,
        "runtime_authority_digest": HASH_5,
        "production_surface_digest": HASH_6,
        "platform_matrix_digest": HASH_7,
        "provider_deployment_digest": HASH_3,
        "receipt_digest": HASH_8,
        "receipt_verified": True,
    }
    values.update(overrides)
    return ReleaseConformancePin(**values)


def _observation(**overrides: object) -> RuntimeConformanceObservation:
    values = {
        "process_id": "worker/2614",
        "boot_generation": 4,
        "monotonic_observed_ns": MONO_NS - 1,
        "readiness": _readiness(),
        "deployment": _deployment(),
        "cluster_genesis_hash": HASH_4,
        "provider_set_hash": HASH_8,
        "signer_generation_hash": HASH_B,
        "submission_generation_hash": HASH_C,
        "provider_deployment_digest": HASH_3,
    }
    values.update(overrides)
    return RuntimeConformanceObservation(**values)


def _policy() -> ConformancePolicy:
    return ConformancePolicy(
        max_snapshot_age_ms=5_000,
        max_future_skew_ms=100,
        lease_ttl_ns=1_000_000_000,
    )


def _evaluate(**overrides: object):
    values = {
        "pin": _pin(),
        "envelope": _envelope(),
        "observation": _observation(),
        "policy": _policy(),
        "trusted_now_ms": NOW_MS,
        "monotonic_now_ns": MONO_NS,
    }
    values.update(overrides)
    return evaluate_runtime_conformance(**values)


def test_t2614_001_stale_pr201_snapshot_cannot_keep_conformance_healthy() -> None:
    stale = _readiness(observed_at_ms=0)
    assert stale.evaluate()["healthy"] is True  # reproduced PR-201 false positive

    decision = _evaluate(observation=_observation(readiness=stale))
    assert decision.healthy is False
    assert decision.lease is None
    assert "MPR2614_READINESS_STALE" in decision.reason_codes
    assert decision.suspension_required is True


def test_t2614_002_runtime_image_mismatch_blocks_even_when_pr201_looks_ready() -> None:
    readiness = _readiness(image_digest=OTHER_IMAGE)
    old_report = operator_readiness_report(
        readiness=readiness,
        slo={"blockers": ()},
        deployment={"blockers": (), "image_digest": OTHER_IMAGE},
        backup_restore={"blockers": ()},
        release_manifest=ReleaseImageManifest(
            source_commit=HASH_A,
            lock_hash=HASH_B,
            wheel_hash=HASH_C,
            image_digest=IMAGE,
            config_hash=HASH_D,
            contract_evidence_hash=HASH_E,
            soak_artifact_hash=HASH_F,
        ),
    )
    assert old_report["operator_ready"] is True  # reproduced PR-201 identity gap

    decision = _evaluate(
        observation=_observation(
            readiness=readiness,
            deployment=_deployment(image_digest=OTHER_IMAGE),
        )
    )
    assert decision.healthy is False
    assert "MPR2614_RELEASE_IMAGE_DRIFT" in decision.reason_codes
    assert "MPR2614_DEPLOYMENT_IMAGE_DRIFT" in decision.reason_codes


def test_t2614_003_source_mismatch_blocks() -> None:
    decision = _evaluate(observation=_observation(readiness=_readiness(source_commit=HASH_2)))
    assert "MPR2614_RELEASE_SOURCE_DRIFT" in decision.reason_codes


def test_t2614_004_config_mismatch_blocks() -> None:
    decision = _evaluate(observation=_observation(readiness=_readiness(config_hash=HASH_2)))
    assert "MPR2614_RELEASE_CONFIG_DRIFT" in decision.reason_codes


def test_t2614_005_deployment_image_mismatch_blocks() -> None:
    decision = _evaluate(observation=_observation(deployment=_deployment(image_digest=OTHER_IMAGE)))
    assert "MPR2614_DEPLOYMENT_IMAGE_DRIFT" in decision.reason_codes


def test_t2614_006_contract_evidence_mismatch_blocks() -> None:
    decision = _evaluate(
        observation=_observation(readiness=_readiness(contract_evidence_hash=HASH_2))
    )
    assert "MPR2614_RELEASE_CONTRACT_EVIDENCE_DRIFT" in decision.reason_codes


def test_t2614_007_lease_expires_without_refresh() -> None:
    decision = _evaluate()
    assert decision.healthy is True
    assert decision.lease is not None
    lease = decision.lease
    assert lease.valid_for(
        monotonic_now_ns=lease.expires_monotonic_ns - 1,
        release_generation=11,
        release_decision_hash=HASH_A,
        process_id="worker/2614",
        boot_generation=4,
        hard_latch_active=False,
    )
    assert not lease.valid_for(
        monotonic_now_ns=lease.expires_monotonic_ns,
        release_generation=11,
        release_decision_hash=HASH_A,
        process_id="worker/2614",
        boot_generation=4,
        hard_latch_active=False,
    )


def test_t2614_008_wall_clock_does_not_extend_monotonic_lease() -> None:
    lease = _evaluate().lease
    assert lease is not None
    # There is deliberately no wall-clock argument in lease validity.
    assert not lease.valid_for(
        monotonic_now_ns=lease.expires_monotonic_ns + 1,
        release_generation=11,
        release_decision_hash=HASH_A,
        process_id="worker/2614",
        boot_generation=4,
        hard_latch_active=False,
    )


def test_t2614_009_future_dated_heartbeat_fails() -> None:
    future = _readiness(observed_at_ms=NOW_MS + 101)
    decision = _evaluate(observation=_observation(readiness=future))
    assert "MPR2614_READINESS_FUTURE_DATED" in decision.reason_codes


def test_t2614_010_restart_cannot_reuse_prior_process_lease() -> None:
    lease = _evaluate().lease
    assert lease is not None
    assert not lease.valid_for(
        monotonic_now_ns=MONO_NS + 1,
        release_generation=11,
        release_decision_hash=HASH_A,
        process_id="worker/2614",
        boot_generation=5,
        hard_latch_active=False,
    )


def test_t2614_013_provider_generation_drift_blocks() -> None:
    observation = _observation(provider_set_hash=HASH_7)
    decision = _evaluate(observation=observation)
    assert "MPR2614_PROVIDER_GENERATION_DRIFT" in decision.reason_codes


def test_t2614_014_cluster_genesis_drift_blocks() -> None:
    decision = _evaluate(observation=_observation(cluster_genesis_hash=HASH_7))
    assert "MPR2614_CLUSTER_GENESIS_DRIFT" in decision.reason_codes


def test_t2614_015_signer_generation_drift_blocks() -> None:
    decision = _evaluate(observation=_observation(signer_generation_hash=HASH_7))
    assert "MPR2614_SIGNER_GENERATION_DRIFT" in decision.reason_codes


def test_t2614_016_unknown_economic_outcome_blocks_capital_reuse() -> None:
    decision = _evaluate(observation=_observation(unresolved_economic_ambiguity=True))
    assert "MPR2614_UNRESOLVED_ECONOMIC_AMBIGUITY" in decision.reason_codes


def test_t2614_017_018_slo_or_data_loss_requires_suspension() -> None:
    slo = _evaluate(observation=_observation(critical_slo_breach=True))
    loss = _evaluate(observation=_observation(data_loss_detected=True))
    assert "MPR2614_CRITICAL_SLO_BREACH" in slo.reason_codes
    assert "MPR2614_DATA_LOSS_DETECTED" in loss.reason_codes
    assert slo.suspension_required and loss.suspension_required


def test_t2614_021_later_green_heartbeat_does_not_auto_clear_sticky_suspension() -> None:
    decision = _evaluate(sticky_suspension_active=True)
    assert decision.healthy is False
    assert decision.lease is None
    assert "MPR2614_STICKY_SUSPENSION_ACTIVE" in decision.reason_codes
    assert decision.automatic_rearm_allowed is False


def test_t2614_026_observation_tamper_changes_digest_and_lease_lineage() -> None:
    first = _observation()
    second = replace(first, provider_deployment_digest=HASH_2)
    assert first.semantic_digest != second.semantic_digest
    decision = _evaluate(observation=second)
    assert decision.healthy is False
    assert "MPR2614_PROVIDER_DEPLOYMENT_DRIFT" in decision.reason_codes


def test_t2614_028_release_generation_change_invalidates_old_lease() -> None:
    lease = _evaluate().lease
    assert lease is not None
    assert not lease.valid_for(
        monotonic_now_ns=MONO_NS + 1,
        release_generation=12,
        release_decision_hash=HASH_A,
        process_id="worker/2614",
        boot_generation=4,
        hard_latch_active=False,
    )


def test_t2614_030_sentinel_never_grants_sign_send_or_live() -> None:
    decision = _evaluate()
    assert decision.healthy is True
    assert decision.live_enabled is False
    assert decision.signer_allowed is False
    assert decision.submission_allowed is False
    assert decision.automatic_rearm_allowed is False


def test_unverified_or_expired_release_cannot_issue_lease() -> None:
    unverified = _evaluate(pin=_pin(receipt_verified=False))
    assert "MPR2614_RELEASE_RECEIPT_NOT_VERIFIED" in unverified.reason_codes

    expired_release = _release(expires_at_utc="2026-09-09T11:00:00Z")
    expired = _evaluate(
        pin=_pin(release=expired_release),
        envelope=_envelope(
            release=expired_release,
            issued_at_utc="2026-09-09T00:00:00Z",
            expires_at_utc="2026-09-09T10:00:00Z",
        ),
    )
    assert "MPR2614_ACCEPTED_RELEASE_EXPIRED" in expired.reason_codes
