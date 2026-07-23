"""MEGA-PR-01 canonical runtime and durable paper-core gate.

This module is intentionally offline and sender-free.  It models the first
acceptance slice for MEGA-PR-01: a single installed paper composition root,
durable writable state, typed provider/secret evidence, real paper-cycle
surfaces and canonical protocol identity.  It does not construct, simulate,
sign, submit or reconcile transactions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

SCHEMA_VERSION: Final = "mega-pr01.canonical-runtime-paper-core.v1"
EXPECTED_ENTRYPOINT: Final = "src.cli_pr189:main"
EXPECTED_COMMAND: Final = "flashloan-bot run --mode paper"
EXPECTED_CONTAINER_UID: Final = 10001
REQUIRED_FINDINGS: Final = frozenset(
    {
        "IMPL-01",
        "IMPL-02",
        "IMPL-03",
        "IMPL-04",
        "IMPL-05",
        "IMPL-06",
        "IMPL-07",
        "IMPL-08",
        "IMPL-09",
    }
)
REQUIRED_PAPER_DEPENDENCIES: Final = frozenset(
    {
        "batch_source",
        "runtime_cycle",
        "atomic_stage_suite",
        "exact_fee_workflow",
        "verified_lending_provider",
        "jupiter_build_adapter",
        "durable_paper_sink",
    }
)
REQUIRED_PROVIDER_SURFACES: Final = frozenset(
    {
        "helius",
        "solana_rpc",
        "marginfi",
        "kamino",
        "jupiter",
    }
)
FORBIDDEN_LEGACY_SURFACES: Final = frozenset(
    {
        "setup_flashloan.sh",
        "ecosystem.config.js",
        "src.legacy_arb_bot",
        "legacy_kamino_program_id",
        "pm2_runtime",
    }
)


class MegaPR01State(StrEnum):
    READY_FOR_SENDER_FREE_PAPER_CORE = "ready_for_sender_free_paper_core"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class MegaPR01Blocker:
    code: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class CompositionRootEvidence:
    command: str
    entrypoint_target: str
    source_module: str
    wheel_target_matches_cli: bool
    container_target_matches_cli: bool
    competing_runtime_surfaces: tuple[str, ...] = ()

    def blockers(self) -> tuple[MegaPR01Blocker, ...]:
        blockers: list[MegaPR01Blocker] = []
        if self.command != EXPECTED_COMMAND:
            blockers.append(
                MegaPR01Blocker(
                    "MEGA_PR01_UNEXPECTED_PAPER_COMMAND",
                    f"expected {EXPECTED_COMMAND!r}, got {self.command!r}",
                )
            )
        if self.entrypoint_target != EXPECTED_ENTRYPOINT:
            blockers.append(
                MegaPR01Blocker(
                    "MEGA_PR01_ENTRYPOINT_DRIFT",
                    f"expected {EXPECTED_ENTRYPOINT!r}, got {self.entrypoint_target!r}",
                )
            )
        if self.source_module != "src.cli_pr189":
            blockers.append(
                MegaPR01Blocker(
                    "MEGA_PR01_COMPOSITION_ROOT_NOT_CANONICAL",
                    f"source_module={self.source_module!r}",
                )
            )
        if not self.wheel_target_matches_cli:
            blockers.append(
                MegaPR01Blocker(
                    "MEGA_PR01_WHEEL_CLI_TARGET_MISMATCH",
                    "installed wheel does not invoke the canonical CLI target",
                )
            )
        if not self.container_target_matches_cli:
            blockers.append(
                MegaPR01Blocker(
                    "MEGA_PR01_CONTAINER_CLI_TARGET_MISMATCH",
                    "container entrypoint does not invoke the canonical CLI target",
                )
            )
        legacy = sorted(set(self.competing_runtime_surfaces) & FORBIDDEN_LEGACY_SURFACES)
        if legacy:
            blockers.append(
                MegaPR01Blocker(
                    "MEGA_PR01_LEGACY_RUNTIME_SURFACE_ACTIVE",
                    ",".join(legacy),
                )
            )
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class DurableStateEvidence:
    database_path: str
    journal_path: str
    evidence_path: str
    root_filesystem_read_only: bool
    mounted_state_root: str
    container_uid: int
    uid_can_write: bool
    fsync_proven: bool
    restart_recovery_proven: bool
    kill9_recovery_proven: bool
    backup_restore_proven: bool
    corruption_handling_proven: bool
    idempotency_key_enforced: bool

    def blockers(self) -> tuple[MegaPR01Blocker, ...]:
        blockers: list[MegaPR01Blocker] = []
        for label, path in {
            "database": self.database_path,
            "journal": self.journal_path,
            "evidence": self.evidence_path,
        }.items():
            if not path.startswith(self.mounted_state_root.rstrip("/") + "/"):
                blockers.append(
                    MegaPR01Blocker(
                        "MEGA_PR01_DURABLE_PATH_NOT_MOUNTED",
                        f"{label}:{path}",
                    )
                )
        if not self.root_filesystem_read_only:
            blockers.append(
                MegaPR01Blocker(
                    "MEGA_PR01_ROOT_FILESYSTEM_NOT_READ_ONLY",
                    "paper container must run with a read-only application filesystem",
                )
            )
        if self.container_uid != EXPECTED_CONTAINER_UID:
            blockers.append(
                MegaPR01Blocker(
                    "MEGA_PR01_CONTAINER_UID_DRIFT",
                    f"expected {EXPECTED_CONTAINER_UID}, got {self.container_uid}",
                )
            )
        required_booleans = {
            "MEGA_PR01_UID_CANNOT_WRITE_STATE": self.uid_can_write,
            "MEGA_PR01_FSYNC_NOT_PROVEN": self.fsync_proven,
            "MEGA_PR01_RESTART_RECOVERY_NOT_PROVEN": self.restart_recovery_proven,
            "MEGA_PR01_KILL9_RECOVERY_NOT_PROVEN": self.kill9_recovery_proven,
            "MEGA_PR01_BACKUP_RESTORE_NOT_PROVEN": self.backup_restore_proven,
            "MEGA_PR01_CORRUPTION_HANDLING_NOT_PROVEN": self.corruption_handling_proven,
            "MEGA_PR01_IDEMPOTENCY_NOT_ENFORCED": self.idempotency_key_enforced,
        }
        for code, passed in required_booleans.items():
            if not passed:
                blockers.append(MegaPR01Blocker(code, code.lower()))
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class ProviderConfigEvidence:
    typed_provider_surfaces: tuple[str, ...]
    secret_handle_surfaces: tuple[str, ...]
    raw_secret_environment_allowed: bool
    generic_environment_injection_allowed: bool
    docker_runtime_env_secret_consumed_by_typed_loader: bool
    provider_config_schema_hash: str

    def blockers(self) -> tuple[MegaPR01Blocker, ...]:
        blockers: list[MegaPR01Blocker] = []
        typed = set(self.typed_provider_surfaces)
        missing_typed = sorted(REQUIRED_PROVIDER_SURFACES - typed)
        if missing_typed:
            blockers.append(
                MegaPR01Blocker(
                    "MEGA_PR01_TYPED_PROVIDER_SURFACE_MISSING",
                    ",".join(missing_typed),
                )
            )
        secret = set(self.secret_handle_surfaces)
        missing_secret = sorted(REQUIRED_PROVIDER_SURFACES - secret)
        if missing_secret:
            blockers.append(
                MegaPR01Blocker(
                    "MEGA_PR01_SECRET_HANDLE_SURFACE_MISSING",
                    ",".join(missing_secret),
                )
            )
        if self.raw_secret_environment_allowed:
            blockers.append(
                MegaPR01Blocker(
                    "MEGA_PR01_RAW_SECRET_ENVIRONMENT_ALLOWED",
                    "provider secrets must remain SecretHandle/FileHandle objects",
                )
            )
        if self.generic_environment_injection_allowed:
            blockers.append(
                MegaPR01Blocker(
                    "MEGA_PR01_GENERIC_ENVIRONMENT_INJECTION_ALLOWED",
                    "generic environment compatibility seam is still active",
                )
            )
        if not self.docker_runtime_env_secret_consumed_by_typed_loader:
            blockers.append(
                MegaPR01Blocker(
                    "MEGA_PR01_DOCKER_RUNTIME_ENV_SECRET_UNUSED",
                    "mounted runtime.env is not consumed by the typed loader",
                )
            )
        if len(self.provider_config_schema_hash) != 64:
            blockers.append(
                MegaPR01Blocker(
                    "MEGA_PR01_PROVIDER_SCHEMA_HASH_INVALID",
                    "provider_config_schema_hash must be a 64-character digest",
                )
            )
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class PaperDependencyEvidence:
    dependency_status: dict[str, bool]
    positive_fixture_reaches_paper_accepted: bool
    negative_fixtures_have_stable_reject_reasons: bool
    default_dependency_none_count: int
    placeholder_source_count: int
    installed_wheel_cycle_hash: str

    def blockers(self) -> tuple[MegaPR01Blocker, ...]:
        blockers: list[MegaPR01Blocker] = []
        missing = sorted(
            name
            for name in REQUIRED_PAPER_DEPENDENCIES
            if not self.dependency_status.get(name, False)
        )
        if missing:
            blockers.append(
                MegaPR01Blocker(
                    "MEGA_PR01_PAPER_DEPENDENCY_MISSING",
                    ",".join(missing),
                )
            )
        if not self.positive_fixture_reaches_paper_accepted:
            blockers.append(
                MegaPR01Blocker(
                    "MEGA_PR01_NO_POSITIVE_INSTALLED_PAPER_ACCEPTED",
                    "clean installed wheel has not produced durable paper_accepted",
                )
            )
        if not self.negative_fixtures_have_stable_reject_reasons:
            blockers.append(
                MegaPR01Blocker(
                    "MEGA_PR01_NEGATIVE_REJECT_REASONS_UNSTABLE",
                    "negative fixtures must produce stable fail-closed reasons",
                )
            )
        if self.default_dependency_none_count:
            blockers.append(
                MegaPR01Blocker(
                    "MEGA_PR01_DEFAULT_DEPENDENCY_NONE",
                    str(self.default_dependency_none_count),
                )
            )
        if self.placeholder_source_count:
            blockers.append(
                MegaPR01Blocker(
                    "MEGA_PR01_PLACEHOLDER_SOURCE_STILL_DEFAULT",
                    str(self.placeholder_source_count),
                )
            )
        if len(self.installed_wheel_cycle_hash) != 64:
            blockers.append(
                MegaPR01Blocker(
                    "MEGA_PR01_INSTALLED_WHEEL_CYCLE_HASH_INVALID",
                    "installed_wheel_cycle_hash must be a 64-character digest",
                )
            )
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class DataPlaneEvidence:
    rooted_rpc_quorum: bool
    coherent_reserve_mint_oracle_snapshot: bool
    authenticated_helius_intake: bool
    durable_enqueue_before_ack: bool
    gap_repair_backfill: bool
    provider_disagreement_blocks_planning: bool
    lineage_fields: tuple[str, ...]

    def blockers(self) -> tuple[MegaPR01Blocker, ...]:
        blockers: list[MegaPR01Blocker] = []
        required = {
            "MEGA_PR01_ROOTED_RPC_QUORUM_MISSING": self.rooted_rpc_quorum,
            "MEGA_PR01_COHERENT_SNAPSHOT_MISSING": (
                self.coherent_reserve_mint_oracle_snapshot
            ),
            "MEGA_PR01_HELIUS_AUTH_MISSING": self.authenticated_helius_intake,
            "MEGA_PR01_ENQUEUE_BEFORE_ACK_MISSING": self.durable_enqueue_before_ack,
            "MEGA_PR01_GAP_REPAIR_MISSING": self.gap_repair_backfill,
            "MEGA_PR01_PROVIDER_DISAGREEMENT_NOT_BLOCKING": (
                self.provider_disagreement_blocks_planning
            ),
        }
        for code, passed in required.items():
            if not passed:
                blockers.append(MegaPR01Blocker(code, code.lower()))
        required_lineage = {"source", "slot", "root", "freshness", "schema", "lineage"}
        missing_lineage = sorted(required_lineage - set(self.lineage_fields))
        if missing_lineage:
            blockers.append(
                MegaPR01Blocker(
                    "MEGA_PR01_PROVIDER_LINEAGE_FIELD_MISSING",
                    ",".join(missing_lineage),
                )
            )
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class ProtocolIdentityEvidence:
    registry_program_ids_attested: bool
    unknown_protocol_ids_forbidden: bool
    legacy_kamino_id_executable: bool
    marginfi_identity_current: bool
    kamino_klend_identity_current: bool

    def blockers(self) -> tuple[MegaPR01Blocker, ...]:
        blockers: list[MegaPR01Blocker] = []
        required = {
            "MEGA_PR01_PROTOCOL_REGISTRY_NOT_ATTESTED": (
                self.registry_program_ids_attested
            ),
            "MEGA_PR01_UNKNOWN_PROTOCOL_IDS_NOT_FORBIDDEN": (
                self.unknown_protocol_ids_forbidden
            ),
            "MEGA_PR01_MARGINFI_IDENTITY_NOT_CURRENT": self.marginfi_identity_current,
            "MEGA_PR01_KAMINO_KLEND_IDENTITY_NOT_CURRENT": (
                self.kamino_klend_identity_current
            ),
        }
        for code, passed in required.items():
            if not passed:
                blockers.append(MegaPR01Blocker(code, code.lower()))
        if self.legacy_kamino_id_executable:
            blockers.append(
                MegaPR01Blocker(
                    "MEGA_PR01_LEGACY_KAMINO_ID_EXECUTABLE",
                    "legacy Kamino program ID path remains executable",
                )
            )
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class MegaPR01Evidence:
    composition: CompositionRootEvidence
    durable_state: DurableStateEvidence
    provider_config: ProviderConfigEvidence
    paper_dependencies: PaperDependencyEvidence
    data_plane: DataPlaneEvidence
    protocol_identity: ProtocolIdentityEvidence
    registered_debt_coverage: tuple[str, ...]
    implementation_findings_coverage: tuple[str, ...]
    live_execution_requested: bool = False
    signer_requested: bool = False
    sender_requested: bool = False
    private_key_loading_reachable: bool = False
    optimized_mode_validation_proven: bool = False
    extra_blockers: tuple[MegaPR01Blocker, ...] = field(default_factory=tuple)


def evaluate_mega_pr01_evidence(evidence: MegaPR01Evidence) -> dict[str, object]:
    """Evaluate the first MEGA-PR-01 sender-free paper-core evidence bundle."""

    blockers: list[MegaPR01Blocker] = []
    blockers.extend(evidence.composition.blockers())
    blockers.extend(evidence.durable_state.blockers())
    blockers.extend(evidence.provider_config.blockers())
    blockers.extend(evidence.paper_dependencies.blockers())
    blockers.extend(evidence.data_plane.blockers())
    blockers.extend(evidence.protocol_identity.blockers())
    blockers.extend(evidence.extra_blockers)

    missing_findings = sorted(
        REQUIRED_FINDINGS - set(evidence.implementation_findings_coverage)
    )
    if missing_findings:
        blockers.append(
            MegaPR01Blocker(
                "MEGA_PR01_IMPL_FINDING_COVERAGE_MISSING",
                ",".join(missing_findings),
            )
        )
    if len(evidence.registered_debt_coverage) < 17:
        blockers.append(
            MegaPR01Blocker(
                "MEGA_PR01_REGISTERED_DEBT_COVERAGE_INCOMPLETE",
                str(len(evidence.registered_debt_coverage)),
            )
        )
    if evidence.live_execution_requested:
        blockers.append(
            MegaPR01Blocker(
                "MEGA_PR01_LIVE_EXECUTION_REQUESTED",
                "MEGA-PR-01 may only produce sender-free paper evidence",
            )
        )
    if evidence.signer_requested:
        blockers.append(
            MegaPR01Blocker(
                "MEGA_PR01_SIGNER_REQUESTED",
                "signer work belongs after production-qualified paper",
            )
        )
    if evidence.sender_requested:
        blockers.append(
            MegaPR01Blocker(
                "MEGA_PR01_SENDER_REQUESTED",
                "sender/submission is outside MEGA-PR-01",
            )
        )
    if evidence.private_key_loading_reachable:
        blockers.append(
            MegaPR01Blocker(
                "MEGA_PR01_PRIVATE_KEY_LOADING_REACHABLE",
                "private-key loading must be unreachable in paper runtime",
            )
        )
    if not evidence.optimized_mode_validation_proven:
        blockers.append(
            MegaPR01Blocker(
                "MEGA_PR01_OPTIMIZED_MODE_VALIDATION_NOT_PROVEN",
                "python -O must not disable admitted paper-path validation",
            )
        )

    unique_blockers = tuple(
        {f"{blocker.code}:{blocker.detail}": blocker for blocker in blockers}.values()
    )
    state = (
        MegaPR01State.READY_FOR_SENDER_FREE_PAPER_CORE
        if not unique_blockers
        else MegaPR01State.BLOCKED
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "state": state.value,
        "ready_for_functional_sender_free_paper_vertical": not unique_blockers,
        "production_ready": False,
        "live_execution_allowed": False,
        "signer_allowed": False,
        "sender_allowed": False,
        "blockers": [blocker.to_dict() for blocker in unique_blockers],
        "coverage": {
            "registered_debt_count": len(evidence.registered_debt_coverage),
            "implementation_findings": sorted(evidence.implementation_findings_coverage),
        },
    }
