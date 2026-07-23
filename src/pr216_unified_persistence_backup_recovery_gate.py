"""PR-216 unified persistence, backup and recovery platform gate.

This module is intentionally offline. It does not open SQLite files, copy
databases, mutate backups or perform restore operations. It models the Pass 7
PR-216 acceptance boundary so persistence/recovery evidence cannot be declared
ready while direct connection sites, multiple terminal authorities or unsafe
backup/restore protocols remain present.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Mapping

SCHEMA_VERSION = "pr216.unified-persistence-backup-recovery-gate.v1"
LIVE_EXECUTION_ALLOWED = False
RESTORE_MUTATION_ALLOWED = False
DATABASE_CONNECTION_ALLOWED = False

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=-]{0,127}$")

REQUIRED_FAULT_SCENARIOS = frozenset(
    {
        "manifest_torn_write",
        "enospc_during_backup",
        "permission_denied_during_restore",
        "corrupt_wal",
        "failed_replace",
        "failed_reopen",
        "process_kill_before_cutover",
    }
)


class PR216Blocker(StrEnum):
    """Stable blocker codes for the PR-216 acceptance gate."""

    DIRECT_SQLITE_CONNECT_OUTSIDE_PLATFORM = "DIRECT_SQLITE_CONNECT_OUTSIDE_PLATFORM"
    DATABASE_CATALOG_INCOMPLETE = "DATABASE_CATALOG_INCOMPLETE"
    PRAGMA_POLICY_NOT_CENTRALIZED = "PRAGMA_POLICY_NOT_CENTRALIZED"
    PRAGMA_PROFILE_INCOMPLETE = "PRAGMA_PROFILE_INCOMPLETE"
    MULTIPLE_TERMINAL_TRUTHS = "MULTIPLE_TERMINAL_TRUTHS"
    PROJECTIONS_NOT_REBUILDABLE = "PROJECTIONS_NOT_REBUILDABLE"
    RECOVERY_ORDER_NOT_DECLARED = "RECOVERY_ORDER_NOT_DECLARED"
    BACKUP_PUBLICATION_NOT_ATOMIC = "BACKUP_PUBLICATION_NOT_ATOMIC"
    BACKUP_PUBLICATION_NOT_DURABLE = "BACKUP_PUBLICATION_NOT_DURABLE"
    RESTORE_CLOSES_LIVE_STORE_TOO_EARLY = "RESTORE_CLOSES_LIVE_STORE_TOO_EARLY"
    RESTORE_ROLLBACK_NOT_PROVEN = "RESTORE_ROLLBACK_NOT_PROVEN"
    RESTORE_DIRECTORY_FSYNC_MISSING = "RESTORE_DIRECTORY_FSYNC_MISSING"
    FAULT_MATRIX_INCOMPLETE = "FAULT_MATRIX_INCOMPLETE"
    OLD_GENERATION_NOT_PRESERVED = "OLD_GENERATION_NOT_PRESERVED"
    LIVE_OR_SENDER_REACHABLE = "LIVE_OR_SENDER_REACHABLE"


class PR216EvidenceError(ValueError):
    """Raised when PR-216 evidence is malformed."""


@dataclass(frozen=True, slots=True)
class PersistenceCatalogEvidence:
    """Evidence for one platform-owned database catalog.

    Direct sqlite3/aiosqlite connection sites are allowed only when they are
    owned by the approved platform/factory surface. Every database/table owner
    must be catalogued before it can participate in recovery decisions.
    """

    platform_factory_sha256: str
    catalog_sha256: str
    discovered_connect_sites: int
    approved_platform_connect_sites: int
    direct_connects_outside_platform: int
    catalogued_databases: int
    catalogued_tables: int
    every_database_has_owner: bool
    every_table_has_rebuild_or_authority: bool

    def __post_init__(self) -> None:
        _sha256(self.platform_factory_sha256, "platform_factory_sha256")
        _sha256(self.catalog_sha256, "catalog_sha256")
        _non_negative_int(self.discovered_connect_sites, "discovered_connect_sites")
        _non_negative_int(
            self.approved_platform_connect_sites,
            "approved_platform_connect_sites",
        )
        _non_negative_int(
            self.direct_connects_outside_platform,
            "direct_connects_outside_platform",
        )
        _positive_int(self.catalogued_databases, "catalogued_databases")
        _positive_int(self.catalogued_tables, "catalogued_tables")


@dataclass(frozen=True, slots=True)
class PragmaPolicyEvidence:
    """Centralized SQLite PRAGMA profile evidence."""

    policy_sha256: str
    durable_critical_profile_sha256: str
    read_model_profile_sha256: str
    test_profile_sha256: str
    all_connections_apply_factory_policy: bool
    wal_enabled_for_durable_critical: bool
    synchronous_full_for_durable_critical: bool
    busy_timeout_configured: bool
    trusted_schema_disabled: bool
    foreign_keys_enabled: bool
    profile_validation_after_connect: bool

    def __post_init__(self) -> None:
        _sha256(self.policy_sha256, "policy_sha256")
        _sha256(
            self.durable_critical_profile_sha256,
            "durable_critical_profile_sha256",
        )
        _sha256(self.read_model_profile_sha256, "read_model_profile_sha256")
        _sha256(self.test_profile_sha256, "test_profile_sha256")


@dataclass(frozen=True, slots=True)
class TerminalTruthEvidence:
    """Evidence that terminal truth is owned by one transactional authority."""

    system_of_record_sha256: str
    projection_catalog_sha256: str
    terminal_authority_count: int
    projections_have_sequence_fence: bool
    projections_are_rebuildable_from_record: bool
    outbox_consumers_are_idempotent: bool
    recovery_order_sha256: str | None
    recovery_order_covers_all_stores: bool

    def __post_init__(self) -> None:
        _sha256(self.system_of_record_sha256, "system_of_record_sha256")
        _sha256(self.projection_catalog_sha256, "projection_catalog_sha256")
        _positive_int(self.terminal_authority_count, "terminal_authority_count")
        if self.recovery_order_sha256 is not None:
            _sha256(self.recovery_order_sha256, "recovery_order_sha256")


@dataclass(frozen=True, slots=True)
class BackupPublicationEvidence:
    """Crash-safe backup publication evidence."""

    backup_bundle_sha256: str
    schema_manifest_sha256: str
    product_manifest_sha256: str
    generation_directory_used: bool
    database_backup_fsynced: bool
    manifest_written_to_temp_then_renamed: bool
    manifest_file_fsynced: bool
    parent_directory_fsynced: bool
    atomic_pointer_publish: bool
    independent_verifier_recomputes_db_hash: bool

    def __post_init__(self) -> None:
        _sha256(self.backup_bundle_sha256, "backup_bundle_sha256")
        _sha256(self.schema_manifest_sha256, "schema_manifest_sha256")
        _sha256(self.product_manifest_sha256, "product_manifest_sha256")


@dataclass(frozen=True, slots=True)
class RestoreCutoverEvidence:
    """Crash-safe restore cutover evidence."""

    restore_plan_sha256: str
    replacement_materialized_before_cutover: bool
    replacement_opened_and_checked_before_closing_live: bool
    live_store_kept_available_until_validated: bool
    old_generation_preserved_until_healthcheck: bool
    rollback_marker_written: bool
    rollback_proven_after_replace_failure: bool
    directory_fsync_after_replace: bool
    healthcheck_before_retiring_old_generation: bool

    def __post_init__(self) -> None:
        _sha256(self.restore_plan_sha256, "restore_plan_sha256")


@dataclass(frozen=True, slots=True)
class FaultInjectionEvidence:
    """Deterministic backup/restore fault matrix evidence."""

    matrix_sha256: str
    executed_scenarios: tuple[str, ...]
    all_failures_preserved_old_generation: bool
    old_generation_available_after_each_failure: bool
    failure_reports_have_stable_reason_codes: bool
    subprocess_or_fork_crash_tests: bool

    def __post_init__(self) -> None:
        _sha256(self.matrix_sha256, "matrix_sha256")
        if not isinstance(self.executed_scenarios, tuple):
            raise PR216EvidenceError("executed_scenarios must be a tuple")
        for scenario in self.executed_scenarios:
            _identifier(scenario, "executed_scenarios")


@dataclass(frozen=True, slots=True)
class PR216UnifiedPersistenceEvidence:
    """Top-level evidence envelope for Pass 7 PR-216."""

    catalog: PersistenceCatalogEvidence
    pragma_policy: PragmaPolicyEvidence
    terminal_truth: TerminalTruthEvidence
    backup_publication: BackupPublicationEvidence
    restore_cutover: RestoreCutoverEvidence
    fault_injection: FaultInjectionEvidence
    live_execution_reachable: bool = False
    sender_reachable: bool = False
    direct_restore_mutation_reachable: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.catalog, PersistenceCatalogEvidence):
            raise PR216EvidenceError("catalog evidence has wrong type")
        if not isinstance(self.pragma_policy, PragmaPolicyEvidence):
            raise PR216EvidenceError("pragma_policy evidence has wrong type")
        if not isinstance(self.terminal_truth, TerminalTruthEvidence):
            raise PR216EvidenceError("terminal_truth evidence has wrong type")
        if not isinstance(self.backup_publication, BackupPublicationEvidence):
            raise PR216EvidenceError("backup_publication evidence has wrong type")
        if not isinstance(self.restore_cutover, RestoreCutoverEvidence):
            raise PR216EvidenceError("restore_cutover evidence has wrong type")
        if not isinstance(self.fault_injection, FaultInjectionEvidence):
            raise PR216EvidenceError("fault_injection evidence has wrong type")


@dataclass(frozen=True, slots=True)
class PR216UnifiedPersistenceReport:
    """Deterministic report emitted by the PR-216 gate."""

    schema_version: str
    ready: bool
    blockers: tuple[str, ...]
    evidence_hash: str
    live_execution_allowed: bool = LIVE_EXECUTION_ALLOWED
    restore_mutation_allowed: bool = RESTORE_MUTATION_ALLOWED
    database_connection_allowed: bool = DATABASE_CONNECTION_ALLOWED

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "ready": self.ready,
            "blockers": list(self.blockers),
            "evidence_hash": self.evidence_hash,
            "live_execution_allowed": self.live_execution_allowed,
            "restore_mutation_allowed": self.restore_mutation_allowed,
            "database_connection_allowed": self.database_connection_allowed,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def evaluate_pr216_unified_persistence(
    evidence: PR216UnifiedPersistenceEvidence,
) -> PR216UnifiedPersistenceReport:
    """Evaluate PR-216 unified persistence/backup/recovery evidence."""

    blockers: list[PR216Blocker] = []

    if (
        evidence.live_execution_reachable
        or evidence.sender_reachable
        or evidence.direct_restore_mutation_reachable
    ):
        blockers.append(PR216Blocker.LIVE_OR_SENDER_REACHABLE)

    catalog = evidence.catalog
    if catalog.direct_connects_outside_platform != 0:
        blockers.append(PR216Blocker.DIRECT_SQLITE_CONNECT_OUTSIDE_PLATFORM)
    if catalog.discovered_connect_sites != catalog.approved_platform_connect_sites:
        blockers.append(PR216Blocker.DIRECT_SQLITE_CONNECT_OUTSIDE_PLATFORM)
    if not (
        catalog.every_database_has_owner and catalog.every_table_has_rebuild_or_authority
    ):
        blockers.append(PR216Blocker.DATABASE_CATALOG_INCOMPLETE)

    pragma = evidence.pragma_policy
    if not (
        pragma.all_connections_apply_factory_policy
        and pragma.profile_validation_after_connect
    ):
        blockers.append(PR216Blocker.PRAGMA_POLICY_NOT_CENTRALIZED)
    if not (
        pragma.wal_enabled_for_durable_critical
        and pragma.synchronous_full_for_durable_critical
        and pragma.busy_timeout_configured
        and pragma.trusted_schema_disabled
        and pragma.foreign_keys_enabled
    ):
        blockers.append(PR216Blocker.PRAGMA_PROFILE_INCOMPLETE)

    terminal = evidence.terminal_truth
    if terminal.terminal_authority_count != 1:
        blockers.append(PR216Blocker.MULTIPLE_TERMINAL_TRUTHS)
    if not (
        terminal.projections_have_sequence_fence
        and terminal.projections_are_rebuildable_from_record
        and terminal.outbox_consumers_are_idempotent
    ):
        blockers.append(PR216Blocker.PROJECTIONS_NOT_REBUILDABLE)
    if terminal.recovery_order_sha256 is None or not terminal.recovery_order_covers_all_stores:
        blockers.append(PR216Blocker.RECOVERY_ORDER_NOT_DECLARED)

    backup = evidence.backup_publication
    if not (
        backup.generation_directory_used
        and backup.manifest_written_to_temp_then_renamed
        and backup.atomic_pointer_publish
    ):
        blockers.append(PR216Blocker.BACKUP_PUBLICATION_NOT_ATOMIC)
    if not (
        backup.database_backup_fsynced
        and backup.manifest_file_fsynced
        and backup.parent_directory_fsynced
        and backup.independent_verifier_recomputes_db_hash
    ):
        blockers.append(PR216Blocker.BACKUP_PUBLICATION_NOT_DURABLE)

    restore = evidence.restore_cutover
    if not (
        restore.replacement_materialized_before_cutover
        and restore.replacement_opened_and_checked_before_closing_live
        and restore.live_store_kept_available_until_validated
    ):
        blockers.append(PR216Blocker.RESTORE_CLOSES_LIVE_STORE_TOO_EARLY)
    if not (
        restore.old_generation_preserved_until_healthcheck
        and restore.rollback_marker_written
        and restore.rollback_proven_after_replace_failure
        and restore.healthcheck_before_retiring_old_generation
    ):
        blockers.append(PR216Blocker.RESTORE_ROLLBACK_NOT_PROVEN)
    if not restore.directory_fsync_after_replace:
        blockers.append(PR216Blocker.RESTORE_DIRECTORY_FSYNC_MISSING)

    fault = evidence.fault_injection
    missing_scenarios = REQUIRED_FAULT_SCENARIOS.difference(fault.executed_scenarios)
    if missing_scenarios or not (
        fault.failure_reports_have_stable_reason_codes and fault.subprocess_or_fork_crash_tests
    ):
        blockers.append(PR216Blocker.FAULT_MATRIX_INCOMPLETE)
    if not (
        fault.all_failures_preserved_old_generation
        and fault.old_generation_available_after_each_failure
    ):
        blockers.append(PR216Blocker.OLD_GENERATION_NOT_PRESERVED)

    blocker_values = tuple(sorted({blocker.value for blocker in blockers}))
    return PR216UnifiedPersistenceReport(
        schema_version=SCHEMA_VERSION,
        ready=not blocker_values,
        blockers=blocker_values,
        evidence_hash=_stable_hash(evidence_to_dict(evidence)),
    )


def evidence_to_dict(evidence: PR216UnifiedPersistenceEvidence) -> dict[str, object]:
    """Return deterministic JSON-compatible evidence representation."""

    return {
        "catalog": {
            "platform_factory_sha256": evidence.catalog.platform_factory_sha256,
            "catalog_sha256": evidence.catalog.catalog_sha256,
            "discovered_connect_sites": evidence.catalog.discovered_connect_sites,
            "approved_platform_connect_sites": evidence.catalog.approved_platform_connect_sites,
            "direct_connects_outside_platform": evidence.catalog.direct_connects_outside_platform,
            "catalogued_databases": evidence.catalog.catalogued_databases,
            "catalogued_tables": evidence.catalog.catalogued_tables,
            "every_database_has_owner": evidence.catalog.every_database_has_owner,
            "every_table_has_rebuild_or_authority": evidence.catalog.every_table_has_rebuild_or_authority,
        },
        "pragma_policy": {
            "policy_sha256": evidence.pragma_policy.policy_sha256,
            "durable_critical_profile_sha256": evidence.pragma_policy.durable_critical_profile_sha256,
            "read_model_profile_sha256": evidence.pragma_policy.read_model_profile_sha256,
            "test_profile_sha256": evidence.pragma_policy.test_profile_sha256,
            "all_connections_apply_factory_policy": evidence.pragma_policy.all_connections_apply_factory_policy,
            "wal_enabled_for_durable_critical": evidence.pragma_policy.wal_enabled_for_durable_critical,
            "synchronous_full_for_durable_critical": evidence.pragma_policy.synchronous_full_for_durable_critical,
            "busy_timeout_configured": evidence.pragma_policy.busy_timeout_configured,
            "trusted_schema_disabled": evidence.pragma_policy.trusted_schema_disabled,
            "foreign_keys_enabled": evidence.pragma_policy.foreign_keys_enabled,
            "profile_validation_after_connect": evidence.pragma_policy.profile_validation_after_connect,
        },
        "terminal_truth": {
            "system_of_record_sha256": evidence.terminal_truth.system_of_record_sha256,
            "projection_catalog_sha256": evidence.terminal_truth.projection_catalog_sha256,
            "terminal_authority_count": evidence.terminal_truth.terminal_authority_count,
            "projections_have_sequence_fence": evidence.terminal_truth.projections_have_sequence_fence,
            "projections_are_rebuildable_from_record": evidence.terminal_truth.projections_are_rebuildable_from_record,
            "outbox_consumers_are_idempotent": evidence.terminal_truth.outbox_consumers_are_idempotent,
            "recovery_order_sha256": evidence.terminal_truth.recovery_order_sha256,
            "recovery_order_covers_all_stores": evidence.terminal_truth.recovery_order_covers_all_stores,
        },
        "backup_publication": {
            "backup_bundle_sha256": evidence.backup_publication.backup_bundle_sha256,
            "schema_manifest_sha256": evidence.backup_publication.schema_manifest_sha256,
            "product_manifest_sha256": evidence.backup_publication.product_manifest_sha256,
            "generation_directory_used": evidence.backup_publication.generation_directory_used,
            "database_backup_fsynced": evidence.backup_publication.database_backup_fsynced,
            "manifest_written_to_temp_then_renamed": evidence.backup_publication.manifest_written_to_temp_then_renamed,
            "manifest_file_fsynced": evidence.backup_publication.manifest_file_fsynced,
            "parent_directory_fsynced": evidence.backup_publication.parent_directory_fsynced,
            "atomic_pointer_publish": evidence.backup_publication.atomic_pointer_publish,
            "independent_verifier_recomputes_db_hash": evidence.backup_publication.independent_verifier_recomputes_db_hash,
        },
        "restore_cutover": {
            "restore_plan_sha256": evidence.restore_cutover.restore_plan_sha256,
            "replacement_materialized_before_cutover": evidence.restore_cutover.replacement_materialized_before_cutover,
            "replacement_opened_and_checked_before_closing_live": evidence.restore_cutover.replacement_opened_and_checked_before_closing_live,
            "live_store_kept_available_until_validated": evidence.restore_cutover.live_store_kept_available_until_validated,
            "old_generation_preserved_until_healthcheck": evidence.restore_cutover.old_generation_preserved_until_healthcheck,
            "rollback_marker_written": evidence.restore_cutover.rollback_marker_written,
            "rollback_proven_after_replace_failure": evidence.restore_cutover.rollback_proven_after_replace_failure,
            "directory_fsync_after_replace": evidence.restore_cutover.directory_fsync_after_replace,
            "healthcheck_before_retiring_old_generation": evidence.restore_cutover.healthcheck_before_retiring_old_generation,
        },
        "fault_injection": {
            "matrix_sha256": evidence.fault_injection.matrix_sha256,
            "executed_scenarios": list(evidence.fault_injection.executed_scenarios),
            "all_failures_preserved_old_generation": evidence.fault_injection.all_failures_preserved_old_generation,
            "old_generation_available_after_each_failure": evidence.fault_injection.old_generation_available_after_each_failure,
            "failure_reports_have_stable_reason_codes": evidence.fault_injection.failure_reports_have_stable_reason_codes,
            "subprocess_or_fork_crash_tests": evidence.fault_injection.subprocess_or_fork_crash_tests,
        },
        "live_execution_reachable": evidence.live_execution_reachable,
        "sender_reachable": evidence.sender_reachable,
        "direct_restore_mutation_reachable": evidence.direct_restore_mutation_reachable,
    }


def _stable_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sha256(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise PR216EvidenceError(f"{name} must be a lowercase sha256 hex digest")
    if value in {"0" * 64, "f" * 64}:
        raise PR216EvidenceError(f"{name} must not be a placeholder digest")


def _identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise PR216EvidenceError(f"{name} must be a stable identifier")


def _non_negative_int(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise PR216EvidenceError(f"{name} must be a non-negative integer")


def _positive_int(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise PR216EvidenceError(f"{name} must be a positive integer")
