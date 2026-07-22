from __future__ import annotations

import hashlib

from src.observability import (
    Environment,
    EventType,
    EvidenceRef,
    ObservabilityStore,
    Outcome,
    make_event,
)
from src.observability.cross_plane_pr196 import (
    AuthoritativeTruthBundle,
    CanonicalOutcome,
    CrossPlaneTerminalReconciler,
    CrossPlaneTruthStore,
    FinalizedSettlementEvidence,
    LedgerPostingEvidence,
    LifecycleTerminalEvidence,
    PlaneWatermark,
    ReleasePolicyEvidence,
    ReservationTerminalState,
    TerminalTruthState,
    TruthPlane,
)
from src.observability.metrics import verified_terminal_summary


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _watermark(plane: TruthPlane, sequence: int) -> PlaneWatermark:
    return PlaneWatermark(
        plane=plane,
        database_epoch=f"epoch-{plane.value}",
        sequence_no=sequence,
        observed_at_ns=sequence * 1000,
    )


def _success_fixture(
    *, amount: int = 25
) -> tuple[dict[str, object], AuthoritativeTruthBundle]:
    attempt_id = _hash("attempt")
    generation = 3
    plan_hash = _hash("plan")
    message_hash = _hash("message")
    lifecycle_event_id = "lifecycle-event-196"
    lifecycle_event_hash = _hash("lifecycle-event")
    settlement_digest = _hash("settlement")
    posting_id = "ledger-posting-196"
    posting_hash = _hash("posting")
    release_hash = _hash("release")
    policy_hash = _hash("policy")
    signature = "finalized-signature-196"
    asset = "So11111111111111111111111111111111111111112"
    slot = 196_000

    truth = AuthoritativeTruthBundle(
        lifecycle=LifecycleTerminalEvidence(
            attempt_id=attempt_id,
            attempt_generation=generation,
            logical_opportunity_id="opp-196",
            plan_hash=plan_hash,
            lifecycle_event_id=lifecycle_event_id,
            lifecycle_event_hash=lifecycle_event_hash,
            reservation_state=ReservationTerminalState.CONSUMED,
            outcome=CanonicalOutcome.SUCCESS,
            terminal_reason="finalized-settlement",
            watermark=_watermark(TruthPlane.LIFECYCLE, 11),
        ),
        settlement=FinalizedSettlementEvidence(
            attempt_id=attempt_id,
            attempt_generation=generation,
            message_hash=message_hash,
            finalized_signature=signature,
            finalized_slot=slot,
            settlement_evidence_digest=settlement_digest,
            asset_mint=asset,
            amount_base_units=amount,
            outcome=CanonicalOutcome.SUCCESS,
            watermark=_watermark(TruthPlane.SETTLEMENT, 12),
        ),
        ledger=LedgerPostingEvidence(
            attempt_id=attempt_id,
            attempt_generation=generation,
            posting_id=posting_id,
            posting_hash=posting_hash,
            settlement_evidence_digest=settlement_digest,
            asset_mint=asset,
            amount_base_units=amount,
            outcome=CanonicalOutcome.SUCCESS,
            watermark=_watermark(TruthPlane.LEDGER, 13),
        ),
        release_policy=ReleasePolicyEvidence(
            release_id="release-pr196",
            release_hash=release_hash,
            policy_bundle_hash=policy_hash,
        ),
    )
    authority = {
        "lifecycle_event_id": lifecycle_event_id,
        "lifecycle_event_hash": lifecycle_event_hash,
        "settlement_evidence_digest": settlement_digest,
        "ledger_posting_id": posting_id,
        "ledger_posting_hash": posting_hash,
        "reservation_state": "consumed",
        "release_hash": release_hash,
        "policy_bundle_hash": policy_hash,
        "asset_mint": asset,
        "amount_base_units": amount,
        "finalized_signature": signature,
        "finalized_slot": slot,
    }
    event_kwargs: dict[str, object] = {
        "event_type": EventType.attempt_terminal,
        "logical_opportunity_id": "opp-196",
        "plan_hash": plan_hash,
        "sequence_no": 1,
        "environment": Environment.paper,
        "aggregate_id": "attempt:pr196",
        "attempt_generation": generation,
        "attempt_id": attempt_id,
        "message_hash": message_hash,
        "tx_signature": signature,
        "outcome": Outcome.succeeded,
        "attributes": {
            "terminal_authority": authority,
            "realized_pnl": {
                "asset_mint": asset,
                "amount_base_units": amount,
                "settlement_evidence_digest": settlement_digest,
                "ledger_posting_id": posting_id,
                "finalized_signature": signature,
                "finalized_slot": slot,
            },
        },
        "evidence_ref": EvidenceRef(
            digest=settlement_digest,
            size_bytes=512,
            classification="financial-proof",
        ),
        "producer_code_version": "release-pr196",
        "config_checksum": _hash("config"),
        "contract_fixture_version": "fixture-pr196-v1",
    }
    return event_kwargs, truth


def test_fake_terminal_event_cannot_count_as_success() -> None:
    with ObservabilityStore(":memory:") as observability, CrossPlaneTruthStore() as truth_store:
        fake = make_event(
            event_type=EventType.attempt_terminal,
            logical_opportunity_id="fake-opp",
            plan_hash="not-a-hash",
            sequence_no=1,
            attempt_id="fake-attempt",
            outcome=Outcome.succeeded,
            attributes={"realized_pnl": {"caller": "arbitrary"}},
        )
        assert observability.append(fake) is True
        result = CrossPlaneTerminalReconciler(truth_store).reconcile(fake, None)
        assert result.state is TerminalTruthState.AMBIGUOUS
        assert result.counts_as_success is False
        assert "PR196_AUTHORITATIVE_BUNDLE_MISSING" in result.reason_codes
        assert verified_terminal_summary(truth_store)["verified_successes"] == 0
        raw = observability.db.execute(
            "SELECT terminal,outcome FROM attempt_projection WHERE attempt_id=?",
            (fake.attempt_id,),
        ).fetchone()
        assert tuple(raw) == (1, "succeeded")  # compatibility projection only


def test_verified_success_requires_all_authoritative_planes() -> None:
    event_kwargs, truth = _success_fixture()
    with ObservabilityStore(":memory:") as observability, CrossPlaneTruthStore() as truth_store:
        event = make_event(**event_kwargs)
        assert observability.append(event) is True
        result = CrossPlaneTerminalReconciler(truth_store).reconcile(event, truth)
        assert result.state is TerminalTruthState.TERMINAL_SUCCESS
        assert result.counts_as_success is True
        metrics = truth_store.metrics()
        assert metrics["verified_successes"] == 1
        assert metrics["verified_failures"] == 0
        assert set(metrics["watermarks"]) == {"lifecycle", "settlement", "ledger"}
        assert metrics["release_ready"] is True


def test_ledger_mismatch_is_ambiguous_and_blocks_release() -> None:
    event_kwargs, truth = _success_fixture(amount=25)
    assert truth.ledger is not None
    bad_truth = AuthoritativeTruthBundle(
        lifecycle=truth.lifecycle,
        settlement=truth.settlement,
        ledger=LedgerPostingEvidence(
            attempt_id=truth.ledger.attempt_id,
            attempt_generation=truth.ledger.attempt_generation,
            posting_id=truth.ledger.posting_id,
            posting_hash=truth.ledger.posting_hash,
            settlement_evidence_digest=truth.ledger.settlement_evidence_digest,
            asset_mint=truth.ledger.asset_mint,
            amount_base_units=24,
            outcome=truth.ledger.outcome,
            watermark=truth.ledger.watermark,
        ),
        release_policy=truth.release_policy,
    )
    with CrossPlaneTruthStore() as truth_store:
        event = make_event(**event_kwargs)
        result = CrossPlaneTerminalReconciler(truth_store).reconcile(event, bad_truth)
        assert result.state is TerminalTruthState.AMBIGUOUS
        assert "PR196_AMOUNT_MISMATCH" in result.reason_codes
        assert truth_store.metrics()["release_ready"] is False


def test_conflicting_terminal_outcomes_enter_explicit_conflict_state() -> None:
    success_kwargs, success_truth = _success_fixture()
    assert success_truth.settlement is not None
    with CrossPlaneTruthStore() as truth_store:
        reconciler = CrossPlaneTerminalReconciler(truth_store)
        success = make_event(**success_kwargs)
        assert reconciler.reconcile(success, success_truth).authoritative

        failure = make_event(
            event_type=EventType.attempt_terminal,
            logical_opportunity_id="opp-196",
            plan_hash=success_truth.lifecycle.plan_hash,
            sequence_no=2,
            environment=Environment.paper,
            aggregate_id="attempt:pr196",
            attempt_generation=success_truth.lifecycle.attempt_generation,
            attempt_id=success_truth.lifecycle.attempt_id,
            message_hash=success_truth.settlement.message_hash,
            outcome=Outcome.failed,
            attributes={
                "terminal_authority": {
                    "lifecycle_event_id": "lifecycle-failure-196",
                    "lifecycle_event_hash": _hash("lifecycle-failure"),
                    "reservation_state": "released",
                    "release_hash": success_truth.release_policy.release_hash,
                    "policy_bundle_hash": success_truth.release_policy.policy_bundle_hash,
                }
            },
            producer_code_version="release-pr196",
            config_checksum=_hash("config"),
            contract_fixture_version="fixture-pr196-v1",
        )
        failure_truth = AuthoritativeTruthBundle(
            lifecycle=LifecycleTerminalEvidence(
                attempt_id=success_truth.lifecycle.attempt_id,
                attempt_generation=success_truth.lifecycle.attempt_generation,
                logical_opportunity_id="opp-196",
                plan_hash=success_truth.lifecycle.plan_hash,
                lifecycle_event_id="lifecycle-failure-196",
                lifecycle_event_hash=_hash("lifecycle-failure"),
                reservation_state=ReservationTerminalState.RELEASED,
                outcome=CanonicalOutcome.FAILURE,
                terminal_reason="settlement-failed",
                watermark=_watermark(TruthPlane.LIFECYCLE, 14),
            ),
            settlement=None,
            ledger=None,
            release_policy=success_truth.release_policy,
        )
        result = reconciler.reconcile(failure, failure_truth)
        assert result.state is TerminalTruthState.CONFLICTED
        assert "PR196_CONFLICTING_TERMINAL_EVIDENCE" in result.reason_codes
        assert truth_store.metrics()["release_ready"] is False


def test_projection_rebuild_is_deterministic() -> None:
    event_kwargs, truth = _success_fixture()
    with ObservabilityStore(":memory:") as observability, CrossPlaneTruthStore() as truth_store:
        event = make_event(**event_kwargs)
        observability.append(event)
        reconciler = CrossPlaneTerminalReconciler(truth_store)
        first = reconciler.rebuild(observability, lambda candidate: truth)
        second = reconciler.rebuild(observability, lambda candidate: truth)
        assert first == second
