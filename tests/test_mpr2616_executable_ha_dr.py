from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from src.ha_dr.mpr2616 import (
    CampaignEvidence,
    CampaignEvent,
    CoordinatorCapabilities,
    DispatchBoundary,
    EvidenceBlocked,
    FailoverController,
    HumanTakeoverAuthorization,
    LeaderState,
    LinearizableMemoryFencingBackend,
    QualificationInput,
    QualificationVerdict,
    RestoreEvidence,
    RuntimeIdentity,
    StaleFenceError,
    TakeoverConflict,
    canonical_digest,
    evaluate_ha_qualification,
    recover_after_host_loss,
    strict_json_loads,
    verify_campaign_set_unique,
    verify_takeover_request_identity,
)

H = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64
E = "e" * 64
F = "f" * 64


def identity(instance: str, *, release_generation: int = 3, conformance: bool = True):
    return RuntimeIdentity(
        release_id="rel-2616",
        release_generation=release_generation,
        source_commit=H,
        tree_digest=B,
        wheel_digest=C,
        image_digest=D,
        config_generation=7,
        policy_generation=9,
        runtime_authority_digest=E,
        genesis_hash=F,
        cluster="mainnet-beta",
        wallet_scope="wallet-public-scope",
        instance_id=instance,
        boot_generation=1,
        conformance_lease_digest=H if conformance else None,
    )


def restore(*, release_generation: int = 3, safe: bool = True):
    return RestoreEvidence(
        release_generation=release_generation,
        backup_artifact_digest=H,
        object_receipt_digest=B if safe else None,
        wal_included=safe,
        integrity_ok=safe,
        critical_state_before_digest=C,
        critical_state_after_digest=C if safe else D,
        consumed_permits_preserved=safe,
        unknown_holds_preserved=safe,
        risk_counters_not_decreased=safe,
        suspension_preserved=safe,
        fence_generation_not_decreased=safe,
        committed_ns=1_000_000_000,
        restored_ns=2_000_000_000,
    )


def auth(old_owner: str, standby: RuntimeIdentity, restore_value: RestoreEvidence, *, expected: int = 0):
    return HumanTakeoverAuthorization(
        occurrence_id="incident-1",
        old_owner_digest=old_owner,
        proposed_owner_digest=standby.semantic_digest,
        release_generation=standby.release_generation,
        restore_evidence_digest=restore_value.semantic_digest,
        conformance_evidence_digest=standby.conformance_lease_digest,
        expected_fence_generation=expected,
        action="failover",
        not_before_ns=10,
        expires_ns=10_000,
        canonical_authority_receipt_digest=D,
    )


def campaign(*, campaign_id: str = "c1", drill: str = "split_brain", dual: bool = False, release_generation: int = 3):
    owner1 = identity("a").semantic_digest
    owner2 = identity("b").semantic_digest
    events = [
        CampaignEvent("old-active", 100, 1, owner1, True),
        CampaignEvent("old-fenced", 200, 2, owner1, False),
        CampaignEvent("new-active-default-off", 300, 2, owner2, False),
    ]
    if dual:
        events.extend(
            [
                CampaignEvent("a-effect", 400, 2, owner1, True),
                CampaignEvent("b-effect", 400, 3, owner2, True),
            ]
        )
    return CampaignEvidence(
        campaign_id=campaign_id,
        drill=drill,
        release_id="rel-2616",
        release_generation=release_generation,
        raw_artifact_sha256=H,
        before_state_digest=B,
        after_state_digest=B,
        fault_injection_digest=C,
        events=tuple(events),
        committed_state_ns=1_000_000_000,
        recovered_state_ns=2_000_000_000,
        outage_started_ns=3_000_000_000,
        service_restored_ns=5_000_000_000,
        result="PASS",
    )


def production_coordinator():
    return CoordinatorCapabilities(
        backend_id="external-etcd-like",
        cross_host=True,
        strongly_consistent=True,
        monotonic_generation=True,
        compare_and_swap=True,
        coordinator_native_expiry=True,
        survives_application_host_loss=True,
        sandbox_only=False,
    )


def test_pr165_shape_only_cannot_qualify_executable_ha():
    result = evaluate_ha_qualification(
        QualificationInput(
            release_id="rel-2616",
            release_generation=3,
            ha_policy_generation=1,
            coordinator=None,
            campaigns=(),
            required_drills=frozenset({"split_brain"}),
            rpo_target_seconds=30,
            rto_target_seconds=60,
            signer_recovery_proven=False,
            provider_failover_proven=False,
            object_store_receipt_proven=False,
            unresolved_unknown_effects=0,
            legacy_pr165_review_ready=True,
        )
    )
    assert result.executable_ha_qualified is False
    assert result.verdict is QualificationVerdict.BLOCKED_EXTERNAL_INFRASTRUCTURE
    assert "PR165_SHAPE_ONLY_NOT_EXECUTABLE_PROOF" in result.blockers


def test_sandbox_backend_is_never_production_qualified():
    assert LinearizableMemoryFencingBackend().capabilities.production_eligible is False


def test_two_concurrent_takeovers_exactly_one_cas_wins():
    backend = LinearizableMemoryFencingBackend()
    scope = canonical_digest({"scope": "one"})
    owner_a = identity("a").semantic_digest
    owner_b = identity("b").semantic_digest

    def attempt(owner):
        try:
            return backend.acquire(scope, owner, expected_generation=0, lease_deadline_ns=10_000, now_ns=1)
        except TakeoverConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (owner_a, owner_b)))
    assert sum(result is not None for result in results) == 1
    assert backend.current(scope, now_ns=2).generation == 1


def test_stale_leader_denied_after_newer_fence():
    backend = LinearizableMemoryFencingBackend()
    scope = canonical_digest({"scope": "one"})
    old = backend.acquire(scope, identity("old").semantic_digest, expected_generation=0, lease_deadline_ns=10, now_ns=1)
    newer = backend.acquire(scope, identity("new").semantic_digest, expected_generation=1, lease_deadline_ns=30, now_ns=11)
    assert newer.generation == 2
    with pytest.raises(StaleFenceError):
        backend.assert_current(old, now_ns=12)


def test_takeover_returns_default_off_and_requires_fresh_effect_authorization():
    backend = LinearizableMemoryFencingBackend()
    controller = FailoverController(backend, require_conformance_lease=True)
    standby = identity("standby")
    restore_value = restore()
    old_owner = identity("old").semantic_digest
    result = controller.takeover(
        old_owner_digest=old_owner,
        standby=standby,
        restore=restore_value,
        authorization=auth(old_owner, standby, restore_value),
        lease_deadline_ns=20_000,
        now_ns=20,
        conformance_current=True,
    )
    assert result.state is LeaderState.ACTIVE_DEFAULT_OFF
    assert result.live_enabled is False
    assert result.effect_eligible is False
    assert result.automatic_scale_up is False
    with pytest.raises(EvidenceBlocked, match="fresh one-shot"):
        controller.assert_effect_adjacent_authority(
            lease=result.lease,
            runtime=standby,
            now_ns=21,
            fresh_one_shot_authorization=False,
            conformance_current=True,
            suspension_clear=True,
        )


def test_signer_sender_boundary_rechecks_current_fence():
    backend = LinearizableMemoryFencingBackend()
    controller = FailoverController(backend, require_conformance_lease=False)
    standby = identity("standby")
    restore_value = restore()
    old_owner = identity("old").semantic_digest
    result = controller.takeover(
        old_owner_digest=old_owner,
        standby=standby,
        restore=restore_value,
        authorization=auth(old_owner, standby, restore_value),
        lease_deadline_ns=100,
        now_ns=20,
        conformance_current=True,
    )
    backend.acquire(
        controller.scope_digest(standby),
        identity("newer").semantic_digest,
        expected_generation=result.lease.generation,
        lease_deadline_ns=300,
        now_ns=101,
    )
    with pytest.raises(StaleFenceError):
        controller.assert_signer_or_sender_authority(
            lease=result.lease,
            runtime=standby,
            now_ns=102,
            fresh_one_shot_authorization=True,
            conformance_current=True,
            suspension_clear=True,
        )


def test_unknown_dispatch_at_host_loss_never_blind_resends():
    result = recover_after_host_loss(DispatchBoundary.DURABLE_MARKER_WRITTEN)
    assert result.resend_allowed is False
    assert result.capital_quarantined is True
    assert result.requires_exact_identity_query is True


def test_pre_dispatch_host_loss_does_not_invent_external_effect():
    result = recover_after_host_loss(DispatchBoundary.NOT_ISSUED)
    assert result.resend_allowed is False
    assert result.capital_quarantined is False
    assert result.requires_exact_identity_query is False


def test_stale_restore_blocks_takeover():
    backend = LinearizableMemoryFencingBackend()
    controller = FailoverController(backend, require_conformance_lease=False)
    standby = identity("standby")
    restore_value = restore(safe=False)
    with pytest.raises(EvidenceBlocked, match="restore evidence"):
        controller.takeover(
            old_owner_digest=identity("old").semantic_digest,
            standby=standby,
            restore=restore_value,
            authorization=auth(identity("old").semantic_digest, standby, restore_value),
            lease_deadline_ns=100,
            now_ns=20,
            conformance_current=True,
        )


def test_restore_release_generation_mismatch_blocks_takeover():
    backend = LinearizableMemoryFencingBackend()
    controller = FailoverController(backend, require_conformance_lease=False)
    standby = identity("standby", release_generation=4)
    restore_value = restore(release_generation=3)
    with pytest.raises(EvidenceBlocked, match="restore release generation mismatch"):
        controller.takeover(
            old_owner_digest=identity("old").semantic_digest,
            standby=standby,
            restore=restore_value,
            authorization=auth(identity("old").semantic_digest, standby, restore_value),
            lease_deadline_ns=100,
            now_ns=20,
            conformance_current=True,
        )


def test_conformance_required_for_takeover_when_architecture_uses_2614():
    backend = LinearizableMemoryFencingBackend()
    controller = FailoverController(backend, require_conformance_lease=True)
    standby = identity("standby", conformance=False)
    restore_value = restore()
    authorization = HumanTakeoverAuthorization(
        occurrence_id="incident-1",
        old_owner_digest=identity("old").semantic_digest,
        proposed_owner_digest=standby.semantic_digest,
        release_generation=standby.release_generation,
        restore_evidence_digest=restore_value.semantic_digest,
        conformance_evidence_digest=None,
        expected_fence_generation=0,
        action="failover",
        not_before_ns=10,
        expires_ns=100,
        canonical_authority_receipt_digest=D,
    )
    with pytest.raises(EvidenceBlocked, match="conformance"):
        controller.takeover(
            old_owner_digest=identity("old").semantic_digest,
            standby=standby,
            restore=restore_value,
            authorization=authorization,
            lease_deadline_ns=100,
            now_ns=20,
            conformance_current=False,
        )


def test_hard_suspension_remains_sticky_after_takeover():
    backend = LinearizableMemoryFencingBackend()
    controller = FailoverController(backend, require_conformance_lease=False)
    standby = identity("standby")
    restore_value = restore()
    old_owner = identity("old").semantic_digest
    result = controller.takeover(
        old_owner_digest=old_owner,
        standby=standby,
        restore=restore_value,
        authorization=auth(old_owner, standby, restore_value),
        lease_deadline_ns=100,
        now_ns=20,
        conformance_current=True,
    )
    with pytest.raises(EvidenceBlocked, match="suspension"):
        controller.assert_effect_adjacent_authority(
            lease=result.lease,
            runtime=standby,
            now_ns=21,
            fresh_one_shot_authorization=True,
            conformance_current=True,
            suspension_clear=False,
        )


def test_duplicate_takeover_id_with_semantic_drift_rejected():
    first = verify_takeover_request_identity("takeover-1", {"owner": "a"}, {})
    with pytest.raises(TakeoverConflict):
        verify_takeover_request_identity("takeover-1", {"owner": "b"}, {"takeover-1": first})


def test_duplicate_campaign_id_with_semantic_drift_rejected():
    c1 = campaign(campaign_id="same")
    c2 = replace(c1, raw_artifact_sha256=B)
    with pytest.raises(EvidenceBlocked):
        verify_campaign_set_unique((c1, c2))


def test_rpo_rto_are_derived_from_raw_timestamps():
    c1 = campaign()
    assert c1.rpo_seconds == 1
    assert c1.rto_seconds == 2


def test_dual_active_campaign_fails_qualification():
    result = evaluate_ha_qualification(
        QualificationInput(
            release_id="rel-2616",
            release_generation=3,
            ha_policy_generation=1,
            coordinator=production_coordinator(),
            campaigns=(campaign(dual=True),),
            required_drills=frozenset({"split_brain"}),
            rpo_target_seconds=30,
            rto_target_seconds=60,
            signer_recovery_proven=True,
            provider_failover_proven=True,
            object_store_receipt_proven=True,
            unresolved_unknown_effects=0,
            legacy_pr165_review_ready=True,
        )
    )
    assert result.verdict is QualificationVerdict.FAILED
    assert result.executable_ha_qualified is False


def test_campaign_from_wrong_release_rejected():
    result = evaluate_ha_qualification(
        QualificationInput(
            release_id="rel-2616",
            release_generation=3,
            ha_policy_generation=1,
            coordinator=production_coordinator(),
            campaigns=(campaign(release_generation=4),),
            required_drills=frozenset({"split_brain"}),
            rpo_target_seconds=30,
            rto_target_seconds=60,
            signer_recovery_proven=True,
            provider_failover_proven=True,
            object_store_receipt_proven=True,
            unresolved_unknown_effects=0,
            legacy_pr165_review_ready=True,
        )
    )
    assert any(item.startswith("CAMPAIGN_RELEASE_MISMATCH:") for item in result.blockers)


def test_positive_materialized_qualification_is_default_off():
    result = evaluate_ha_qualification(
        QualificationInput(
            release_id="rel-2616",
            release_generation=3,
            ha_policy_generation=1,
            coordinator=production_coordinator(),
            campaigns=(campaign(),),
            required_drills=frozenset({"split_brain"}),
            rpo_target_seconds=30,
            rto_target_seconds=60,
            signer_recovery_proven=True,
            provider_failover_proven=True,
            object_store_receipt_proven=True,
            unresolved_unknown_effects=0,
            legacy_pr165_review_ready=True,
        )
    )
    assert result.verdict is QualificationVerdict.QUALIFIED_DEFAULT_OFF
    assert result.executable_ha_qualified is True
    assert result.live_enabled is False
    assert result.automatic_scale_up is False


def test_unresolved_unknown_effect_blocks_qualification():
    result = evaluate_ha_qualification(
        QualificationInput(
            release_id="rel-2616",
            release_generation=3,
            ha_policy_generation=1,
            coordinator=production_coordinator(),
            campaigns=(campaign(),),
            required_drills=frozenset({"split_brain"}),
            rpo_target_seconds=30,
            rto_target_seconds=60,
            signer_recovery_proven=True,
            provider_failover_proven=True,
            object_store_receipt_proven=True,
            unresolved_unknown_effects=1,
            legacy_pr165_review_ready=True,
        )
    )
    assert "UNRESOLVED_UNKNOWN_EFFECTS" in result.blockers


def test_strict_json_rejects_duplicate_keys_and_nonfinite_values():
    with pytest.raises(ValueError, match="duplicate JSON key"):
        strict_json_loads('{"a":1,"a":2}')
    with pytest.raises(ValueError, match="non-finite"):
        strict_json_loads('{"a":NaN}')


def test_bool_rejected_as_integer_measurement():
    with pytest.raises(ValueError):
        QualificationInput(
            release_id="r",
            release_generation=1,
            ha_policy_generation=1,
            coordinator=None,
            campaigns=(),
            required_drills=frozenset(),
            rpo_target_seconds=True,
            rto_target_seconds=1,
            signer_recovery_proven=False,
            provider_failover_proven=False,
            object_store_receipt_proven=False,
            unresolved_unknown_effects=0,
            legacy_pr165_review_ready=False,
        )
