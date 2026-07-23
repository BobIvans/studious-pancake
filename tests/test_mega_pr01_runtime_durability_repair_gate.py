from src.mega_pr01_runtime_durability_repair_gate import (
    SCHEMA_ID, REQUIRED_FINDINGS, EvidenceRef, MegaPr01RuntimeDurabilityEvidence,
    QueueRuntimeEvidence, PersistenceEvidence, OutboxWebhookSecretEvidence,
    PaperMergeGateEvidence, evaluate_mega_pr01_runtime_durability,
)

SHA = "a" * 64

def good(**kw):
    ev = MegaPr01RuntimeDurabilityEvidence(
        schema_id=SCHEMA_ID,
        findings=frozenset(REQUIRED_FINDINGS),
        evidence_refs=(EvidenceRef("artifacts/mega-pr01/v3.json", SHA, 100),),
        queue_runtime=QueueRuntimeEvidence(True, True, True, True, True, True, True, True, True),
        persistence=PersistenceEvidence(True, True, True, True, True, True, True, True, True, True),
        outbox_webhook_secret=OutboxWebhookSecretEvidence(True, True, True, True, True, True, True, True, True, True, True, True, True),
        paper_merge_gate=PaperMergeGateEvidence(72, True, True, True, True, True, True),
    )
    data = ev.__dict__.copy(); data.update(kw)
    return MegaPr01RuntimeDurabilityEvidence(**data)

def assert_blocks(ev, *codes):
    report = evaluate_mega_pr01_runtime_durability(ev)
    assert report.accepted is False
    for code in codes:
        assert code in report.blockers
    return report

def test_happy_path_allows_sender_free_merge_review_only():
    report = evaluate_mega_pr01_runtime_durability(good())
    assert report.accepted is True
    assert report.sender_free_paper_merge_review_allowed is True
    assert report.operational_paper_ready_allowed is False
    assert report.live_execution_allowed is False
    assert report.signer_allowed is False
    assert report.sender_allowed is False

def test_missing_finding_fails_closed():
    findings = frozenset(f for f in REQUIRED_FINDINGS if f != "IMPL-38")
    assert_blocks(good(findings=findings), "MISSING_FINDINGS:IMPL-38")

def test_rejects_unmaterialized_placeholder_evidence():
    assert_blocks(
        good(evidence_refs=(EvidenceRef("../source-only.json", "0"*64, 0, materialized=False),)),
        "EVIDENCE_REF_0_NOT_MATERIALIZED", "EVIDENCE_REF_0_UNSAFE_PATH", "EVIDENCE_REF_0_INVALID_SHA256", "EVIDENCE_REF_0_EMPTY",
    )

def test_queue_expiry_and_supervision_are_required():
    assert_blocks(
        good(queue_runtime=QueueRuntimeEvidence(False, False, False, False, False, False, True, True, True)),
        "QUEUE_EXPIRY_NOT_ATOMIC", "DEDUPE_NOT_RELEASED_OR_TERMINALIZED", "CRITICAL_TASK_SUPERVISION_MISSING", "TASK_DEATH_DOES_NOT_CLOSE_READINESS",
    )

def test_bounded_runtime_and_shutdown_are_required():
    assert_blocks(
        good(queue_runtime=QueueRuntimeEvidence(True, True, True, True, True, True, False, False, False)),
        "RUNTIME_COLLECTIONS_UNBOUNDED", "SHUTDOWN_HAS_NO_ABSOLUTE_OWNER", "REMAINING_WORK_NOT_PERSISTED_AFTER_TIMEOUT",
    )

def test_persistence_requires_async_writer_time_idempotency_and_recovery():
    assert_blocks(
        good(persistence=PersistenceEvidence(False, False, False, False, False, False, False, False, False, False)),
        "PROVIDER_INTAKE_BLOCKS_ASYNCIO", "SQLITE_WRITER_NOT_DEDICATED_OR_BOUNDED", "MONOTONIC_DEADLINE_NOT_BOOT_BOUND",
        "IDEMPOTENCY_COMMAND_HASH_MISSING", "MIGRATION_IDENTITY_CHECKSUM_MISSING", "RESERVATION_RECOVERY_INCOMPLETE",
    )

def test_outbox_requires_real_delivery_state_machine():
    assert_blocks(
        good(outbox_webhook_secret=OutboxWebhookSecretEvidence(False, False, False, False, True, True, True, True, True, True, True, True, True)),
        "OUTBOX_STATE_MACHINE_MISSING", "OUTBOX_BOOT_GENERATION_FENCING_MISSING", "OUTBOX_PENDING_ROW_COUNTS_AS_DELIVERED",
    )

def test_webhook_identity_fencing_dlq_and_bounds_are_required():
    assert_blocks(
        good(outbox_webhook_secret=OutboxWebhookSecretEvidence(True, True, True, True, False, False, False, False, False, True, True, True, True)),
        "WEBHOOK_IDENTITY_NOT_CHAIN_STABLE", "WEBHOOK_ACK_NACK_NOT_FENCED", "WEBHOOK_POISON_NOT_DLQ_AT_MAX_ATTEMPTS", "WEBHOOK_BOUNDS_OR_INDEXES_MISSING",
    )

def test_rpc_url_secret_redaction_is_required():
    assert_blocks(
        good(outbox_webhook_secret=OutboxWebhookSecretEvidence(True, True, True, True, True, True, True, True, True, False, False, False, False)),
        "ENDPOINT_ORIGIN_NOT_SEPARATE_FROM_SECRET", "CREDENTIAL_PATH_QUERY_ALLOWED", "RPC_SECRET_REDACTION_INCOMPLETE", "PROVIDER_ERRORS_LEAK_SECRETS",
    )

def test_paper_merge_gate_requires_soak_and_drills():
    assert_blocks(
        good(paper_merge_gate=PaperMergeGateEvidence(24, False, False, False, False, False, False)),
        "ACCELERATED_LONG_SOAK_TOO_SHORT", "BOUNDED_CARDINALITY_NOT_PROVEN", "TASK_DEATH_READINESS_NOT_PROVEN", "OUTBOX_EXACTLY_ONCE_NOT_PROVEN", "SECRET_BYTES_IN_ARTIFACTS",
    )

def test_live_signer_sender_private_key_requests_are_forbidden():
    assert_blocks(
        good(live_execution_requested=True, signer_requested=True, sender_requested=True, private_key_access_requested=True),
        "LIVE_EXECUTION_REQUESTED", "SIGNER_REQUESTED", "SENDER_REQUESTED", "PRIVATE_KEY_ACCESS_REQUESTED",
    )
