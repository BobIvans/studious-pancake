from __future__ import annotations

from src.mega_pr01_canonical_runtime_paper_core import (
    DataPlaneEvidence,
    DurableStateEvidence,
    CompositionRootEvidence,
    MegaPR01Evidence,
    PaperDependencyEvidence,
    ProtocolIdentityEvidence,
    ProviderConfigEvidence,
    evaluate_mega_pr01_evidence,
)


def _digest(seed: str) -> str:
    return (seed * 64)[:64]


def _complete_evidence(**overrides) -> MegaPR01Evidence:
    values = {
        "composition": CompositionRootEvidence(
            command="flashloan-bot run --mode paper",
            entrypoint_target="src.cli_pr189:main",
            source_module="src.cli_pr189",
            wheel_target_matches_cli=True,
            container_target_matches_cli=True,
            competing_runtime_surfaces=(),
        ),
        "durable_state": DurableStateEvidence(
            database_path="/var/lib/flashloan/paper/paper.sqlite3",
            journal_path="/var/lib/flashloan/paper/journal.jsonl",
            evidence_path="/var/lib/flashloan/paper/evidence.jsonl",
            root_filesystem_read_only=True,
            mounted_state_root="/var/lib/flashloan",
            container_uid=10001,
            uid_can_write=True,
            fsync_proven=True,
            restart_recovery_proven=True,
            kill9_recovery_proven=True,
            backup_restore_proven=True,
            corruption_handling_proven=True,
            idempotency_key_enforced=True,
        ),
        "provider_config": ProviderConfigEvidence(
            typed_provider_surfaces=(
                "helius",
                "solana_rpc",
                "marginfi",
                "kamino",
                "jupiter",
            ),
            secret_handle_surfaces=(
                "helius",
                "solana_rpc",
                "marginfi",
                "kamino",
                "jupiter",
            ),
            raw_secret_environment_allowed=False,
            generic_environment_injection_allowed=False,
            docker_runtime_env_secret_consumed_by_typed_loader=True,
            provider_config_schema_hash=_digest("a"),
        ),
        "paper_dependencies": PaperDependencyEvidence(
            dependency_status={
                "batch_source": True,
                "runtime_cycle": True,
                "atomic_stage_suite": True,
                "exact_fee_workflow": True,
                "verified_lending_provider": True,
                "jupiter_build_adapter": True,
                "durable_paper_sink": True,
            },
            positive_fixture_reaches_paper_accepted=True,
            negative_fixtures_have_stable_reject_reasons=True,
            default_dependency_none_count=0,
            placeholder_source_count=0,
            installed_wheel_cycle_hash=_digest("b"),
        ),
        "data_plane": DataPlaneEvidence(
            rooted_rpc_quorum=True,
            coherent_reserve_mint_oracle_snapshot=True,
            authenticated_helius_intake=True,
            durable_enqueue_before_ack=True,
            gap_repair_backfill=True,
            provider_disagreement_blocks_planning=True,
            lineage_fields=("source", "slot", "root", "freshness", "schema", "lineage"),
        ),
        "protocol_identity": ProtocolIdentityEvidence(
            registry_program_ids_attested=True,
            unknown_protocol_ids_forbidden=True,
            legacy_kamino_id_executable=False,
            marginfi_identity_current=True,
            kamino_klend_identity_current=True,
        ),
        "registered_debt_coverage": tuple(f"debt-{index:02d}" for index in range(17)),
        "implementation_findings_coverage": tuple(
            f"IMPL-{index:02d}" for index in range(1, 10)
        ),
        "optimized_mode_validation_proven": True,
    }
    values.update(overrides)
    return MegaPR01Evidence(**values)


def _codes(report: dict[str, object]) -> set[str]:
    blockers = report["blockers"]
    assert isinstance(blockers, list)
    return {str(blocker["code"]) for blocker in blockers}


def test_accepts_complete_sender_free_paper_core_evidence() -> None:
    report = evaluate_mega_pr01_evidence(_complete_evidence())

    assert report["schema_version"] == "mega-pr01.canonical-runtime-paper-core.v1"
    assert report["state"] == "ready_for_sender_free_paper_core"
    assert report["ready_for_functional_sender_free_paper_vertical"] is True
    assert report["production_ready"] is False
    assert report["live_execution_allowed"] is False
    assert report["signer_allowed"] is False
    assert report["sender_allowed"] is False
    assert report["blockers"] == []


def test_rejects_legacy_runtime_and_entrypoint_drift() -> None:
    report = evaluate_mega_pr01_evidence(
        _complete_evidence(
            composition=CompositionRootEvidence(
                command="python setup_flashloan.sh",
                entrypoint_target="src.cli:main",
                source_module="src.cli",
                wheel_target_matches_cli=False,
                container_target_matches_cli=False,
                competing_runtime_surfaces=("setup_flashloan.sh", "pm2_runtime"),
            )
        )
    )

    assert {
        "MEGA_PR01_UNEXPECTED_PAPER_COMMAND",
        "MEGA_PR01_ENTRYPOINT_DRIFT",
        "MEGA_PR01_COMPOSITION_ROOT_NOT_CANONICAL",
        "MEGA_PR01_WHEEL_CLI_TARGET_MISMATCH",
        "MEGA_PR01_CONTAINER_CLI_TARGET_MISMATCH",
        "MEGA_PR01_LEGACY_RUNTIME_SURFACE_ACTIVE",
    } <= _codes(report)


def test_rejects_non_durable_or_unowned_state_paths() -> None:
    base = _complete_evidence().durable_state
    report = evaluate_mega_pr01_evidence(
        _complete_evidence(
            durable_state=DurableStateEvidence(
                database_path="/app/paper.sqlite3",
                journal_path=base.journal_path,
                evidence_path=base.evidence_path,
                root_filesystem_read_only=False,
                mounted_state_root=base.mounted_state_root,
                container_uid=0,
                uid_can_write=False,
                fsync_proven=False,
                restart_recovery_proven=False,
                kill9_recovery_proven=False,
                backup_restore_proven=False,
                corruption_handling_proven=False,
                idempotency_key_enforced=False,
            )
        )
    )

    assert {
        "MEGA_PR01_DURABLE_PATH_NOT_MOUNTED",
        "MEGA_PR01_ROOT_FILESYSTEM_NOT_READ_ONLY",
        "MEGA_PR01_CONTAINER_UID_DRIFT",
        "MEGA_PR01_UID_CANNOT_WRITE_STATE",
        "MEGA_PR01_FSYNC_NOT_PROVEN",
        "MEGA_PR01_RESTART_RECOVERY_NOT_PROVEN",
        "MEGA_PR01_KILL9_RECOVERY_NOT_PROVEN",
        "MEGA_PR01_BACKUP_RESTORE_NOT_PROVEN",
        "MEGA_PR01_CORRUPTION_HANDLING_NOT_PROVEN",
        "MEGA_PR01_IDEMPOTENCY_NOT_ENFORCED",
    } <= _codes(report)


def test_rejects_raw_secret_environment_and_missing_provider_surfaces() -> None:
    report = evaluate_mega_pr01_evidence(
        _complete_evidence(
            provider_config=ProviderConfigEvidence(
                typed_provider_surfaces=("helius", "solana_rpc"),
                secret_handle_surfaces=("helius",),
                raw_secret_environment_allowed=True,
                generic_environment_injection_allowed=True,
                docker_runtime_env_secret_consumed_by_typed_loader=False,
                provider_config_schema_hash="not-a-digest",
            )
        )
    )

    assert {
        "MEGA_PR01_TYPED_PROVIDER_SURFACE_MISSING",
        "MEGA_PR01_SECRET_HANDLE_SURFACE_MISSING",
        "MEGA_PR01_RAW_SECRET_ENVIRONMENT_ALLOWED",
        "MEGA_PR01_GENERIC_ENVIRONMENT_INJECTION_ALLOWED",
        "MEGA_PR01_DOCKER_RUNTIME_ENV_SECRET_UNUSED",
        "MEGA_PR01_PROVIDER_SCHEMA_HASH_INVALID",
    } <= _codes(report)


def test_rejects_missing_paper_dependencies_and_placeholder_cycle() -> None:
    report = evaluate_mega_pr01_evidence(
        _complete_evidence(
            paper_dependencies=PaperDependencyEvidence(
                dependency_status={"batch_source": True},
                positive_fixture_reaches_paper_accepted=False,
                negative_fixtures_have_stable_reject_reasons=False,
                default_dependency_none_count=2,
                placeholder_source_count=1,
                installed_wheel_cycle_hash="bad",
            )
        )
    )

    assert {
        "MEGA_PR01_PAPER_DEPENDENCY_MISSING",
        "MEGA_PR01_NO_POSITIVE_INSTALLED_PAPER_ACCEPTED",
        "MEGA_PR01_NEGATIVE_REJECT_REASONS_UNSTABLE",
        "MEGA_PR01_DEFAULT_DEPENDENCY_NONE",
        "MEGA_PR01_PLACEHOLDER_SOURCE_STILL_DEFAULT",
        "MEGA_PR01_INSTALLED_WHEEL_CYCLE_HASH_INVALID",
    } <= _codes(report)


def test_rejects_unrooted_data_plane_and_missing_lineage() -> None:
    report = evaluate_mega_pr01_evidence(
        _complete_evidence(
            data_plane=DataPlaneEvidence(
                rooted_rpc_quorum=False,
                coherent_reserve_mint_oracle_snapshot=False,
                authenticated_helius_intake=False,
                durable_enqueue_before_ack=False,
                gap_repair_backfill=False,
                provider_disagreement_blocks_planning=False,
                lineage_fields=("source",),
            )
        )
    )

    assert {
        "MEGA_PR01_ROOTED_RPC_QUORUM_MISSING",
        "MEGA_PR01_COHERENT_SNAPSHOT_MISSING",
        "MEGA_PR01_HELIUS_AUTH_MISSING",
        "MEGA_PR01_ENQUEUE_BEFORE_ACK_MISSING",
        "MEGA_PR01_GAP_REPAIR_MISSING",
        "MEGA_PR01_PROVIDER_DISAGREEMENT_NOT_BLOCKING",
        "MEGA_PR01_PROVIDER_LINEAGE_FIELD_MISSING",
    } <= _codes(report)


def test_rejects_protocol_identity_drift_and_legacy_kamino_path() -> None:
    report = evaluate_mega_pr01_evidence(
        _complete_evidence(
            protocol_identity=ProtocolIdentityEvidence(
                registry_program_ids_attested=False,
                unknown_protocol_ids_forbidden=False,
                legacy_kamino_id_executable=True,
                marginfi_identity_current=False,
                kamino_klend_identity_current=False,
            )
        )
    )

    assert {
        "MEGA_PR01_PROTOCOL_REGISTRY_NOT_ATTESTED",
        "MEGA_PR01_UNKNOWN_PROTOCOL_IDS_NOT_FORBIDDEN",
        "MEGA_PR01_LEGACY_KAMINO_ID_EXECUTABLE",
        "MEGA_PR01_MARGINFI_IDENTITY_NOT_CURRENT",
        "MEGA_PR01_KAMINO_KLEND_IDENTITY_NOT_CURRENT",
    } <= _codes(report)


def test_rejects_live_signer_sender_and_private_key_scope() -> None:
    report = evaluate_mega_pr01_evidence(
        _complete_evidence(
            live_execution_requested=True,
            signer_requested=True,
            sender_requested=True,
            private_key_loading_reachable=True,
            optimized_mode_validation_proven=False,
            registered_debt_coverage=("one",),
            implementation_findings_coverage=("IMPL-01",),
        )
    )

    assert {
        "MEGA_PR01_LIVE_EXECUTION_REQUESTED",
        "MEGA_PR01_SIGNER_REQUESTED",
        "MEGA_PR01_SENDER_REQUESTED",
        "MEGA_PR01_PRIVATE_KEY_LOADING_REACHABLE",
        "MEGA_PR01_OPTIMIZED_MODE_VALIDATION_NOT_PROVEN",
        "MEGA_PR01_REGISTERED_DEBT_COVERAGE_INCOMPLETE",
        "MEGA_PR01_IMPL_FINDING_COVERAGE_MISSING",
    } <= _codes(report)
