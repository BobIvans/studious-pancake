from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.paper_shadow.sender_free_runtime_evidence_pr198 import (
    PR197_EVIDENCE_NAME,
    REQUIRED_COMPOSITION_STAGES,
    REQUIRED_FAULT_SCENARIOS,
    REQUIRED_HASH_KEYS,
    REQUIRED_SLO_KEYS,
    AcceptedPrerequisiteEvidence,
    CompositionStageEvidence,
    DurableRuntimeEvidence,
    EvidenceBundleIdentity,
    FaultInjectionEvidence,
    RealSoakEvidence,
    ReplayEvidence,
    RuntimeMetricsEvidence,
    SenderFreeRuntimeEvidenceBundle,
    ShadowOutcomeEvidence,
    evaluate_sender_free_runtime_evidence,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64
COMMIT = "1" * 40
ASSEMBLED_AT = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)


def _prerequisite(**overrides: object) -> AcceptedPrerequisiteEvidence:
    values = {
        "name": PR197_EVIDENCE_NAME,
        "sha256": DIGEST_A,
        "source_commit": COMMIT,
        "accepted": True,
        "reviewed_by": "reviewer@example.com",
        "reviewed_at": ASSEMBLED_AT - timedelta(hours=3),
    }
    values.update(overrides)
    return AcceptedPrerequisiteEvidence(**values)


def _composition_stages(
    *,
    order: tuple[str, ...] = REQUIRED_COMPOSITION_STAGES,
) -> tuple[CompositionStageEvidence, ...]:
    return tuple(
        CompositionStageEvidence(
            stage=stage,
            evidence_hash=DIGEST_A,
            deterministic=True,
            durable=True,
            terminal_outcome_written=stage == "durable-outcome",
        )
        for stage in order
    )


def _runtime(**overrides: object) -> DurableRuntimeEvidence:
    values = {
        "queue_fenced_by_pr195": True,
        "outbox_fenced_by_pr195": True,
        "bounded_concurrency": True,
        "backpressure_enabled": True,
        "graceful_shutdown_verified": True,
        "restart_generations_tested": 8,
        "duplicate_attempt_generations": 0,
        "missing_terminal_outcomes": 0,
        "max_open_work_items": 4,
    }
    values.update(overrides)
    return DurableRuntimeEvidence(**values)


def _replay(**overrides: object) -> ReplayEvidence:
    values = {
        "raw_input_corpus_sha256": DIGEST_A,
        "protocol_snapshot_sha256": DIGEST_B,
        "replay_output_sha256": DIGEST_C,
        "deterministic_replay": True,
        "ambient_network_disabled": True,
        "runtime_db_secrets_required": False,
        "replayed_attempts": 12,
        "mismatched_replays": 0,
    }
    values.update(overrides)
    return ReplayEvidence(**values)


def _shadow_outcome(
    identity_hash: str = DIGEST_A,
    **overrides: object,
) -> ShadowOutcomeEvidence:
    values = {
        "would_submit_identity_hash": identity_hash,
        "rejection_reason": "shadow-profitable-but-sender-denied",
        "costs_lamports": 30_000,
        "expected_profit_lamports": 100_000,
        "source_slot": 200,
        "min_context_slot": 190,
        "freshness_ms": 250,
        "evidence_hash": DIGEST_B,
        "redacted": True,
        "immutable": True,
    }
    values.update(overrides)
    return ShadowOutcomeEvidence(**values)


def _soak(**overrides: object) -> RealSoakEvidence:
    values = {
        "started_at": ASSEMBLED_AT - timedelta(days=3),
        "ended_at": ASSEMBLED_AT - timedelta(hours=1),
        "non_synthetic_mainnet": True,
        "read_only": True,
        "trading_wallet_used": False,
        "attempts_observed": 10,
        "terminal_sender_free_outcomes": 10,
        "evidence_bundle_sha256": DIGEST_C,
        "human_acceptance_reviewer": "operator@example.com",
        "human_accepted_at": ASSEMBLED_AT,
    }
    values.update(overrides)
    return RealSoakEvidence(**values)


def _faults(
    *,
    scenarios: tuple[str, ...] = REQUIRED_FAULT_SCENARIOS,
    **overrides: object,
) -> tuple[FaultInjectionEvidence, ...]:
    return tuple(
        FaultInjectionEvidence(
            scenario=scenario,
            injected=bool(overrides.get("injected", True)),
            terminal_outcome_preserved=bool(
                overrides.get("terminal_outcome_preserved", True)
            ),
            duplicate_generation_created=bool(
                overrides.get("duplicate_generation_created", False)
            ),
            evidence_hash=DIGEST_D,
        )
        for scenario in scenarios
    )


def _metrics(**overrides: object) -> RuntimeMetricsEvidence:
    observed = {key: 10 for key in REQUIRED_SLO_KEYS}
    thresholds = {key: 100 for key in REQUIRED_SLO_KEYS}
    values = {
        "observed": observed,
        "thresholds": thresholds,
        "unexplained_task_growth": False,
        "unexplained_fd_growth": False,
        "unexplained_db_growth": False,
    }
    values.update(overrides)
    return RuntimeMetricsEvidence(**values)


def _evidence_bundle(**overrides: object) -> EvidenceBundleIdentity:
    values = {
        "artifact_hashes": {key: DIGEST_A for key in REQUIRED_HASH_KEYS},
        "signed": True,
        "redacted": True,
        "immutable": True,
        "independent_verifier": "assurance@example.com",
        "verifier_needs_runtime_db_secrets": False,
        "acceptance_signature_sha256": DIGEST_B,
    }
    values.update(overrides)
    return EvidenceBundleIdentity(**values)


def _bundle(**overrides: object) -> SenderFreeRuntimeEvidenceBundle:
    values = {
        "source_commit": COMMIT,
        "prerequisite": _prerequisite(),
        "composition_stages": _composition_stages(),
        "durable_runtime": _runtime(),
        "replay": _replay(),
        "shadow_outcomes": (
            _shadow_outcome(DIGEST_A),
            _shadow_outcome(DIGEST_C, rejection_reason="shadow-rejected-by-fee"),
        ),
        "real_soak": _soak(),
        "fault_injections": _faults(),
        "metrics": _metrics(),
        "evidence_bundle": _evidence_bundle(),
        "runtime_capabilities_present": (),
        "assembled_at": ASSEMBLED_AT,
        "assembled_by": "assembler@example.com",
    }
    values.update(overrides)
    return SenderFreeRuntimeEvidenceBundle(**values)


def test_sender_free_runtime_ready_still_denies_sender_and_live() -> None:
    report = evaluate_sender_free_runtime_evidence(_bundle())

    assert report.ready_for_pr199_review is True
    assert report.live_execution_allowed is False
    assert report.sender_import_allowed is False
    assert report.signing_allowed is False
    assert report.blockers == ()
    assert report.state.value == "ready-for-pr199-review"
    assert report.evidence_hash


def test_pr197_prerequisite_must_be_accepted_reviewed_and_same_commit() -> None:
    report = evaluate_sender_free_runtime_evidence(
        _bundle(
            prerequisite=_prerequisite(
                accepted=False,
                source_commit="2" * 40,
                reviewed_at=ASSEMBLED_AT + timedelta(minutes=1),
            )
        )
    )

    assert "PR197_EVIDENCE_NOT_ACCEPTED" in report.blockers
    assert "PR197_SOURCE_COMMIT_MISMATCH" in report.blockers
    assert "PR197_REVIEW_AFTER_ASSEMBLY" in report.blockers


def test_composition_root_order_and_durable_outcome_are_required() -> None:
    bad_stages = _composition_stages(
        order=(
            "ingest-inbox",
            "candidate",
            "normalization",
            "rooted-state",
            "plan",
            "compile",
            "exact-simulate",
            "durable-outcome",
        )
    )
    report = evaluate_sender_free_runtime_evidence(
        _bundle(composition_stages=bad_stages)
    )

    assert "COMPOSITION_ROOT_ORDER_INVALID" in report.blockers


def test_runtime_restart_cannot_duplicate_generations_or_lose_terminal_outcome() -> (
    None
):
    report = evaluate_sender_free_runtime_evidence(
        _bundle(
            durable_runtime=_runtime(
                queue_fenced_by_pr195=False,
                duplicate_attempt_generations=1,
                missing_terminal_outcomes=1,
            )
        )
    )

    assert "QUEUE_NOT_FENCED_BY_PR195" in report.blockers
    assert "DUPLICATE_ATTEMPT_GENERATION" in report.blockers
    assert "MISSING_TERMINAL_OUTCOME" in report.blockers


def test_replay_must_be_deterministic_offline_and_secret_free() -> None:
    report = evaluate_sender_free_runtime_evidence(
        _bundle(
            replay=_replay(
                deterministic_replay=False,
                ambient_network_disabled=False,
                runtime_db_secrets_required=True,
                mismatched_replays=1,
            )
        )
    )

    assert "REPLAY_NOT_DETERMINISTIC" in report.blockers
    assert "REPLAY_CAN_USE_AMBIENT_NETWORK" in report.blockers
    assert "REPLAY_REQUIRES_RUNTIME_DB_SECRETS" in report.blockers
    assert "REPLAY_MISMATCH_DETECTED" in report.blockers


def test_shadow_outcomes_require_unique_immutable_redacted_identities() -> None:
    report = evaluate_sender_free_runtime_evidence(
        _bundle(
            shadow_outcomes=(
                _shadow_outcome(DIGEST_A, redacted=False),
                _shadow_outcome(DIGEST_A, immutable=False),
            )
        )
    )

    assert "DUPLICATE_WOULD_SUBMIT_IDENTITY" in report.blockers
    assert "SHADOW_OUTCOME_NOT_REDACTED" in report.blockers
    assert "SHADOW_OUTCOME_NOT_IMMUTABLE" in report.blockers


def test_real_soak_must_be_multi_day_mainnet_read_only_and_accepted() -> None:
    report = evaluate_sender_free_runtime_evidence(
        _bundle(
            real_soak=_soak(
                started_at=ASSEMBLED_AT - timedelta(hours=3),
                non_synthetic_mainnet=False,
                read_only=False,
                trading_wallet_used=True,
                terminal_sender_free_outcomes=5,
            )
        )
    )

    assert "REAL_SOAK_TOO_SHORT" in report.blockers
    assert "REAL_SOAK_NOT_MAINNET" in report.blockers
    assert "REAL_SOAK_NOT_READ_ONLY" in report.blockers
    assert "REAL_SOAK_USED_TRADING_WALLET" in report.blockers
    assert "REAL_SOAK_MISSING_TERMINAL_OUTCOMES" in report.blockers


def test_required_fault_injections_must_preserve_terminal_outcomes() -> None:
    report = evaluate_sender_free_runtime_evidence(
        _bundle(
            fault_injections=_faults(
                scenarios=("rpc-disagreement",),
                terminal_outcome_preserved=False,
                duplicate_generation_created=True,
            )
        )
    )

    assert "FAULT_TERMINAL_OUTCOME_NOT_PRESERVED:rpc-disagreement" in report.blockers
    assert "FAULT_CREATED_DUPLICATE_GENERATION:rpc-disagreement" in report.blockers
    assert "FAULT_SCENARIO_MISSING:provider-429-timeout" in report.blockers


def test_metrics_and_evidence_bundle_are_release_blocking() -> None:
    observed = {key: 10 for key in REQUIRED_SLO_KEYS}
    observed["ingest_lag_ms"] = 500
    thresholds = {key: 100 for key in REQUIRED_SLO_KEYS}
    report = evaluate_sender_free_runtime_evidence(
        _bundle(
            metrics=_metrics(
                observed=observed,
                thresholds=thresholds,
                unexplained_fd_growth=True,
            ),
            evidence_bundle=_evidence_bundle(
                signed=False,
                verifier_needs_runtime_db_secrets=True,
                artifact_hashes={"commit_sha": DIGEST_A},
            ),
        )
    )

    assert "SLO_THRESHOLD_EXCEEDED:ingest_lag_ms" in report.blockers
    assert "UNEXPLAINED_FD_GROWTH" in report.blockers
    assert "EVIDENCE_HASH_MISSING:image_digest_sha256" in report.blockers
    assert "EVIDENCE_BUNDLE_NOT_SIGNED" in report.blockers
    assert "INDEPENDENT_VERIFIER_NEEDS_RUNTIME_DB_SECRETS" in report.blockers


def test_sender_live_capabilities_are_forbidden_in_pr198_process() -> None:
    report = evaluate_sender_free_runtime_evidence(
        _bundle(
            runtime_capabilities_present=(
                "sender-module-present",
                "live-permit-present",
            )
        )
    )

    assert "FORBIDDEN_RUNTIME_CAPABILITY:sender-module-present" in report.blockers
    assert "FORBIDDEN_RUNTIME_CAPABILITY:live-permit-present" in report.blockers
