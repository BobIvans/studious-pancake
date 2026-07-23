from __future__ import annotations

from src.live_boundary.mega_pr03_cp2_isolated_signer_submission_gate import (
    BoundedSubmissionEvidence,
    CanaryBoundaryEvidence,
    ExactMessageAuthorizationEvidence,
    MegaPR03CP2Evidence,
    MegaPR03CP2State,
    REQUIRED_COVERAGE,
    SignerIsolationEvidence,
    blockers_by_code,
    evaluate_mega_pr03_cp2_evidence,
)


def h(seed: str) -> str:
    return (seed * 64)[:64]


def d(seed: str) -> str:
    return f"sha256:{h(seed)}"


def valid_evidence() -> MegaPR03CP2Evidence:
    message_hash = h("a")
    return MegaPR03CP2Evidence(
        coverage_items=REQUIRED_COVERAGE,
        signer_isolation=SignerIsolationEvidence(
            isolated_process_identity_hash=h("1"),
            signer_image_digest=d("2"),
            ipc_policy_hash=h("3"),
            key_authority_kind="hsm",
            key_authority_generation_hash=h("4"),
            signed_message_policy_hash=h("5"),
            message_decoder_hash=h("6"),
            replay_store_hash=h("7"),
            durable_authorization_outbox_hash=h("8"),
            runtime_container_has_key_access=False,
            private_key_material_exportable=False,
            private_key_in_environment=False,
            caller_supplies_signer_metadata=False,
            signer_decodes_message_bytes=True,
        ),
        exact_message_authorization=ExactMessageAuthorizationEvidence(
            exact_simulated_message_hash=message_hash,
            signer_decoded_message_hash=message_hash,
            simulation_evidence_hash=h("b"),
            semantic_policy_hash=h("c"),
            signer_policy_generation_hash=h("d"),
            cluster_genesis_hash=h("e"),
            alt_snapshot_hash=h("9"),
            current_block_height_at_authorization=100,
            last_valid_block_height=160,
            blockheight_safety_margin=20,
            trusted_now_unix_ns=1_000_000,
            signer_expires_at_unix_ns=1_200_000,
            maximum_permit_ttl_ns=300_000,
        ),
        bounded_submission=BoundedSubmissionEvidence(
            selected_transport="jito_bundle",
            bundle_or_signature_identity_hash=h("a5"),
            wire_message_digest=message_hash,
            durable_intent_store_hash=h("a1"),
            rate_limit_policy_hash=h("a2"),
            retry_budget_hash=h("a3"),
            max_rpc_send_attempts=0,
            max_jito_bundle_attempts=1,
            max_unknown_outcome_hold_ns=5_000_000,
            durable_intent_created_before_network=True,
            staged_write_evidence_required=True,
            no_blind_resend=True,
            ack_is_not_landing=True,
            confirmed_is_not_finality=True,
            jito_unbundling_safeguards_required=True,
            transaction_local_assertions_required=True,
        ),
        canary_boundary=CanaryBoundaryEvidence(
            release_bound_paper_evidence_hash=h("a4"),
            mega_pr02_paper_qualified=True,
            two_distinct_approvers_required=True,
            second_human_approval_required=True,
            one_in_flight_intent_limit=True,
            absolute_loss_budget_lamports=1,
            absolute_trade_count_limit=1,
            provider_drift_latch_required=True,
            reconciliation_latch_required=True,
            evidence_latch_required=True,
        ),
    )


def blocked(evidence: MegaPR03CP2Evidence, code: str) -> None:
    report = evaluate_mega_pr03_cp2_evidence(evidence)
    assert report.state is MegaPR03CP2State.BLOCKED
    assert code in blockers_by_code(report)
    assert not report.live_execution_allowed
    assert not report.unrestricted_live_allowed
    assert not report.automatic_scale_up_allowed


def replace(evidence: MegaPR03CP2Evidence, **parts: object) -> MegaPR03CP2Evidence:
    payload = {
        "coverage_items": evidence.coverage_items,
        "signer_isolation": evidence.signer_isolation,
        "exact_message_authorization": evidence.exact_message_authorization,
        "bounded_submission": evidence.bounded_submission,
        "canary_boundary": evidence.canary_boundary,
    }
    payload.update(parts)
    return MegaPR03CP2Evidence(**payload)


def test_accepts_complete_cp2_review_evidence() -> None:
    report = evaluate_mega_pr03_cp2_evidence(valid_evidence())

    assert report.state is MegaPR03CP2State.READY_FOR_CP3_FINALIZED_SETTLEMENT_REVIEW
    assert report.cp3_finalized_settlement_review_allowed
    assert report.bounded_canary_review_allowed
    assert not report.live_execution_allowed
    assert not report.unrestricted_live_allowed
    assert not report.automatic_scale_up_allowed


def test_rejects_missing_debt_coverage() -> None:
    evidence = valid_evidence()
    blocked(replace(evidence, coverage_items=REQUIRED_COVERAGE[:-1]), "MEGA_PR03_CP2_MISSING_COVERAGE")


def test_rejects_runtime_key_access() -> None:
    evidence = valid_evidence()
    signer = SignerIsolationEvidence(**{**evidence.signer_isolation.__dict__, "runtime_container_has_key_access": True})
    blocked(replace(evidence, signer_isolation=signer), "MEGA_PR03_CP2_RUNTIME_KEY_ACCESS")


def test_rejects_caller_metadata_policy() -> None:
    evidence = valid_evidence()
    signer = SignerIsolationEvidence(**{**evidence.signer_isolation.__dict__, "caller_supplies_signer_metadata": True})
    blocked(replace(evidence, signer_isolation=signer), "MEGA_PR03_CP2_CALLER_METADATA_TRUSTED")


def test_rejects_message_mutation_after_simulation() -> None:
    evidence = valid_evidence()
    msg = ExactMessageAuthorizationEvidence(
        **{**evidence.exact_message_authorization.__dict__, "signer_decoded_message_hash": h("a6")}
    )
    blocked(replace(evidence, exact_message_authorization=msg), "MEGA_PR03_CP2_MESSAGE_HASH_MISMATCH")


def test_rejects_stale_blockheight_and_overlong_permit() -> None:
    evidence = valid_evidence()
    msg = ExactMessageAuthorizationEvidence(
        **{
            **evidence.exact_message_authorization.__dict__,
            "current_block_height_at_authorization": 150,
            "signer_expires_at_unix_ns": 10_000_000,
        }
    )
    blocked(replace(evidence, exact_message_authorization=msg), "MEGA_PR03_CP2_BLOCKHEIGHT_EXPIRED")
    blocked(replace(evidence, exact_message_authorization=msg), "MEGA_PR03_CP2_PERMIT_TTL_TOO_LONG")


def test_rejects_blind_resend() -> None:
    evidence = valid_evidence()
    sub = BoundedSubmissionEvidence(**{**evidence.bounded_submission.__dict__, "no_blind_resend": False})
    blocked(replace(evidence, bounded_submission=sub), "MEGA_PR03_CP2_BLIND_RESEND_ALLOWED")


def test_rejects_ack_or_confirmed_as_truth() -> None:
    evidence = valid_evidence()
    sub = BoundedSubmissionEvidence(
        **{**evidence.bounded_submission.__dict__, "ack_is_not_landing": False, "confirmed_is_not_finality": False}
    )
    blocked(replace(evidence, bounded_submission=sub), "MEGA_PR03_CP2_ACK_AS_LANDING")
    blocked(replace(evidence, bounded_submission=sub), "MEGA_PR03_CP2_CONFIRMED_AS_FINALITY")


def test_rejects_missing_jito_transaction_local_safeguards() -> None:
    evidence = valid_evidence()
    sub = BoundedSubmissionEvidence(
        **{
            **evidence.bounded_submission.__dict__,
            "jito_unbundling_safeguards_required": False,
            "transaction_local_assertions_required": False,
        }
    )
    blocked(replace(evidence, bounded_submission=sub), "MEGA_PR03_CP2_MISSING_JITO_SAFEGUARDS")
    blocked(replace(evidence, bounded_submission=sub), "MEGA_PR03_CP2_MISSING_TX_LOCAL_ASSERTIONS")


def test_rejects_missing_mega_pr02_dependency() -> None:
    evidence = valid_evidence()
    canary = CanaryBoundaryEvidence(**{**evidence.canary_boundary.__dict__, "mega_pr02_paper_qualified": False})
    blocked(replace(evidence, canary_boundary=canary), "MEGA_PR03_CP2_MEGA_PR02_REQUIRED")


def test_rejects_live_unrestricted_or_scale_up_requests() -> None:
    evidence = valid_evidence()
    canary = CanaryBoundaryEvidence(
        **{
            **evidence.canary_boundary.__dict__,
            "live_execution_requested": True,
            "unrestricted_live_requested": True,
            "automatic_scale_up_requested": True,
        }
    )
    blocked(replace(evidence, canary_boundary=canary), "MEGA_PR03_CP2_LIVE_EXECUTION_REQUESTED")
    blocked(replace(evidence, canary_boundary=canary), "MEGA_PR03_CP2_UNRESTRICTED_LIVE_REQUESTED")
    blocked(replace(evidence, canary_boundary=canary), "MEGA_PR03_CP2_AUTOMATIC_SCALE_UP_REQUESTED")
