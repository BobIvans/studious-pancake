from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from src.canonical_control_plane_pr195 import (
    CanonicalControlPlaneStore,
    ConfigGeneration,
    ManualTrustedClock,
)
from src.human_intervention import (
    HumanInterventionLedger,
    HumanInterventionRequest,
    InterventionAction,
    InterventionBlocked,
    InterventionTarget,
    PermitConflict,
    VerifiedApproval,
)
from src.mpr2603_human_recovery import (
    RecoveryTargetConflict,
    apply_clear_and_authorize_recovery,
    install_human_recovery_schema,
    recovery_pending,
)


def _h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _store(tmp_path) -> CanonicalControlPlaneStore:
    return CanonicalControlPlaneStore(
        tmp_path / "control.sqlite",
        trusted_clock=ManualTrustedClock(utc_ns=2_000_000_000),
    )


def _request(target: InterventionTarget, *, start: str = "2026-09-09T02:00:00Z") -> HumanInterventionRequest:
    placeholder = _h("placeholder-request")
    base = HumanInterventionRequest(
        action=InterventionAction.CLEAR_SAFETY_LATCH,
        target=target,
        request_id="req-2603-a",
        nonce="server-nonce-a",
        requested_at_utc=start,
        expires_at_utc="2026-09-09T02:10:00Z",
        trust_epoch=_h("trust-epoch-1"),
        approvals=(
            VerifiedApproval(
                principal_id="person-a",
                credential_id="ssh-a",
                request_hash=placeholder,
                decision="APPROVE",
                verified_payload_hash=_h("sig-a"),
                trust_epoch=_h("trust-epoch-1"),
                valid_from_utc="2026-09-09T01:59:00Z",
                expires_at_utc="2026-09-09T02:09:00Z",
            ),
            VerifiedApproval(
                principal_id="person-b",
                credential_id="ssh-b",
                request_hash=placeholder,
                decision="APPROVE",
                verified_payload_hash=_h("sig-b"),
                trust_epoch=_h("trust-epoch-1"),
                valid_from_utc="2026-09-09T01:59:00Z",
                expires_at_utc="2026-09-09T02:09:00Z",
            ),
        ),
    )
    request_hash = base.request_hash
    approvals = tuple(replace(a, request_hash=request_hash) for a in base.approvals)
    return replace(base, approvals=approvals)


def _activate_target_config(store: CanonicalControlPlaneStore, target: InterventionTarget) -> None:
    store.record_config_generation(
        ConfigGeneration(
            generation_hash=target.config_hash,
            release_hash=target.release_hash,
            policy_hash=_h("policy"),
            approved_by="test-fixture",
            evidence_hash=_h("config-evidence"),
            active=True,
        )
    )


def _issue(store: CanonicalControlPlaneStore, request: HumanInterventionRequest):
    ledger = HumanInterventionLedger(store.db)
    store.db.execute("BEGIN IMMEDIATE")
    try:
        permit = ledger.issue(request, current_utc="2026-09-09T02:01:00Z")
    except BaseException:
        store.db.execute("ROLLBACK")
        raise
    else:
        store.db.execute("COMMIT")
    return permit


def test_mpr2603_issue_does_not_commit_caller_transaction(tmp_path) -> None:
    with _store(tmp_path) as store:
        install_human_recovery_schema(store.db)
        store.db.execute("CREATE TABLE caller_probe(value TEXT)")
        target = InterventionTarget(
            "pr195-latch", "latch-a", _h("subject"), _h("evidence"), _h("release"), _h("config")
        )
        request = _request(target)
        ledger = HumanInterventionLedger(store.db)

        store.db.execute("BEGIN IMMEDIATE")
        store.db.execute("INSERT INTO caller_probe VALUES('before')")
        ledger.issue(request, current_utc="2026-09-09T02:01:00Z")
        store.db.execute("ROLLBACK")

        assert store.db.execute("SELECT COUNT(*) FROM caller_probe").fetchone()[0] == 0
        assert store.db.execute("SELECT COUNT(*) FROM mpr2603_human_permits").fetchone()[0] == 0


def test_mpr2603_not_before_is_enforced_at_issue_and_consume(tmp_path) -> None:
    with _store(tmp_path) as store:
        install_human_recovery_schema(store.db)
        target = InterventionTarget(
            "pr195-latch", "latch-a", _h("subject"), _h("evidence"), _h("release"), _h("config")
        )
        request = _request(target, start="2026-09-09T02:05:00Z")
        with pytest.raises(InterventionBlocked, match="NOT_YET_VALID"):
            HumanInterventionLedger(store.db).issue(
                request, current_utc="2026-09-09T02:04:59Z"
            )


def test_mpr2603_atomic_clear_consumes_permit_and_creates_pending_intent(tmp_path) -> None:
    with _store(tmp_path) as store:
        install_human_recovery_schema(store.db)
        latch_hash = store.open_latch(
            latch_id="provider-auth:jupiter",
            reason_code="AUTH_FAILURE",
            evidence={"provider": "jupiter", "generation": 7},
        )
        target = InterventionTarget(
            "pr195-latch",
            "provider-auth:jupiter",
            latch_hash,
            _h("recovery-evidence"),
            _h("release"),
            _h("config"),
        )
        _activate_target_config(store, target)
        permit = _issue(store, _request(target))

        receipt = apply_clear_and_authorize_recovery(
            store.db,
            permit=permit,
            target=target,
            current_utc="2026-09-09T02:02:00Z",
            current_trust_epoch=_h("trust-epoch-1"),
            idempotency_key="apply-1",
        )

        assert store.db.execute(
            "SELECT active FROM pr195_latches WHERE latch_id=?",
            (target.subject_id,),
        ).fetchone()[0] == 0
        consumed = store.db.execute(
            "SELECT consumed_at_utc FROM mpr2603_human_permits WHERE permit_hash=?",
            (permit.permit_hash,),
        ).fetchone()[0]
        assert consumed == "2026-09-09T02:02:00Z"
        assert recovery_pending(store.db, receipt.recovery_intent_id)


def test_mpr2603_failure_rolls_back_permit_consumption(tmp_path) -> None:
    with _store(tmp_path) as store:
        install_human_recovery_schema(store.db)
        latch_hash = store.open_latch(
            latch_id="provider-auth:jupiter",
            reason_code="AUTH_FAILURE",
            evidence={"provider": "jupiter", "generation": 7},
        )
        target = InterventionTarget(
            "pr195-latch", "provider-auth:jupiter", latch_hash, _h("evidence"), _h("release"), _h("config")
        )
        _activate_target_config(store, target)
        permit = _issue(store, _request(target))
        store.db.execute(
            "UPDATE pr195_latches SET evidence_hash=? WHERE latch_id=?",
            (_h("new-occurrence"), target.subject_id),
        )

        with pytest.raises(RecoveryTargetConflict, match="OCCURRENCE_CHANGED"):
            apply_clear_and_authorize_recovery(
                store.db,
                permit=permit,
                target=target,
                current_utc="2026-09-09T02:02:00Z",
                current_trust_epoch=_h("trust-epoch-1"),
                idempotency_key="apply-1",
            )

        assert store.db.execute(
            "SELECT consumed_at_utc FROM mpr2603_human_permits WHERE permit_hash=?",
            (permit.permit_hash,),
        ).fetchone()[0] is None
        assert store.db.execute(
            "SELECT active FROM pr195_latches WHERE latch_id=?", (target.subject_id,)
        ).fetchone()[0] == 1
        assert store.db.execute("SELECT COUNT(*) FROM mpr2603_recovery_intents").fetchone()[0] == 0


def test_mpr2603_release_or_config_drift_denies_and_rolls_back(tmp_path) -> None:
    with _store(tmp_path) as store:
        install_human_recovery_schema(store.db)
        latch_hash = store.open_latch(
            latch_id="provider-auth:jupiter",
            reason_code="AUTH_FAILURE",
            evidence={"provider": "jupiter", "generation": 7},
        )
        target = InterventionTarget(
            "pr195-latch", "provider-auth:jupiter", latch_hash, _h("evidence"), _h("release"), _h("config")
        )
        _activate_target_config(store, target)
        permit = _issue(store, _request(target))
        store.record_config_generation(
            ConfigGeneration(
                generation_hash=_h("new-config"),
                release_hash=_h("new-release"),
                policy_hash=_h("policy-2"),
                approved_by="test-fixture",
                evidence_hash=_h("config-evidence-2"),
                active=True,
            )
        )

        with pytest.raises(RecoveryTargetConflict, match="ACTIVE_CONFIG_CHANGED"):
            apply_clear_and_authorize_recovery(
                store.db,
                permit=permit,
                target=target,
                current_utc="2026-09-09T02:02:00Z",
                current_trust_epoch=_h("trust-epoch-1"),
                idempotency_key="apply-drift",
            )
        assert store.db.execute(
            "SELECT consumed_at_utc FROM mpr2603_human_permits WHERE permit_hash=?",
            (permit.permit_hash,),
        ).fetchone()[0] is None
        assert store.db.execute(
            "SELECT active FROM pr195_latches WHERE latch_id=?", (target.subject_id,)
        ).fetchone()[0] == 1


def test_mpr2603_exact_replay_returns_receipt_but_semantic_change_conflicts(tmp_path) -> None:
    with _store(tmp_path) as store:
        install_human_recovery_schema(store.db)
        latch_hash = store.open_latch(
            latch_id="provider-auth:jupiter",
            reason_code="AUTH_FAILURE",
            evidence={"provider": "jupiter", "generation": 7},
        )
        target = InterventionTarget(
            "pr195-latch", "provider-auth:jupiter", latch_hash, _h("evidence"), _h("release"), _h("config")
        )
        _activate_target_config(store, target)
        permit = _issue(store, _request(target))
        first = apply_clear_and_authorize_recovery(
            store.db,
            permit=permit,
            target=target,
            current_utc="2026-09-09T02:02:00Z",
            current_trust_epoch=_h("trust-epoch-1"),
            idempotency_key="apply-1",
        )
        replay = apply_clear_and_authorize_recovery(
            store.db,
            permit=permit,
            target=target,
            current_utc="2026-09-09T02:02:30Z",
            current_trust_epoch=_h("trust-epoch-1"),
            idempotency_key="apply-1",
        )
        assert replay.replayed is True
        assert replay.receipt_id == first.receipt_id

        forged = replace(permit, target=replace(target, config_hash=_h("other-config")))
        with pytest.raises(PermitConflict, match="BINDING_MISMATCH"):
            apply_clear_and_authorize_recovery(
                store.db,
                permit=forged,
                target=forged.target,
                current_utc="2026-09-09T02:03:00Z",
                current_trust_epoch=_h("trust-epoch-1"),
                idempotency_key="apply-1",
            )
