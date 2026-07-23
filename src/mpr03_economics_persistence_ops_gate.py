"""MPR-03 finalized economics, persistence, observability and release evidence gate.

This module is intentionally side-effect-free.  It validates materialized
evidence produced elsewhere and never opens databases, reads secrets, calls
providers, builds images, signs transactions, or submits anything on-chain.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "mpr03.finalized-economics-persistence-ops-evidence.v1"

REQUIRED_DEBT_IDS = frozenset(
    {
        "execution.finalized-settlement-binding",
        "evidence.finalized-economic-proof",
        "evidence.real-shadow-soak",
        "deployment.image-provenance",
        "operations.slo-readiness",
        "security.secret-incident-drill",
    }
)

REQUIRED_READINESS_STATES = frozenset(
    {
        "safe_idle",
        "dependency_blocked",
        "degraded",
        "shadow_ready",
        "release_ready",
        "live_denied",
    }
)

REQUIRED_METRICS = frozenset(
    {
        "provider_freshness",
        "queue_depth",
        "reconciliation_lag",
        "db_lock_contention",
        "reservation_leakage",
        "paper_attempt_terminal_counts",
        "data_lineage_counts",
        "drift_probe_age",
        "backup_restore_age",
    }
)

REQUIRED_BACKUP_STEPS = (
    "temp_write",
    "file_fsync",
    "atomic_rename",
    "dir_fsync",
    "publish_generation_pointer",
)

REQUIRED_BACKUP_FAULTS = frozenset(
    {
        "wal_checkpoint",
        "concurrent_writer",
        "torn_manifest",
        "crash_during_cutover",
        "restore_validation_failure",
        "rollback_generation",
    }
)

REQUIRED_MANIFEST_KEYS = frozenset(
    {
        "wheel_digest",
        "image_digest",
        "sbom_digest",
        "config_generation_digest",
        "capability_manifest_digest",
        "program_idl_hashes",
        "db_schema_fingerprint",
        "shadow_campaign_report_digest",
        "provider_drift_report_digest",
        "fault_injection_report_digest",
        "backup_restore_report_digest",
    }
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class MPR03Violation:
    code: str
    message: str


@dataclass(frozen=True)
class MPR03Report:
    schema_version: str
    ready: bool
    violations: tuple[MPR03Violation, ...]
    paper_shadow_evidence_review_allowed: bool
    operational_paper_ready_allowed: bool = False
    live_execution_allowed: bool = False
    signer_allowed: bool = False
    sender_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ready": self.ready,
            "violations": [
                {"code": violation.code, "message": violation.message}
                for violation in self.violations
            ],
            "paper_shadow_evidence_review_allowed": (
                self.paper_shadow_evidence_review_allowed
            ),
            "operational_paper_ready_allowed": self.operational_paper_ready_allowed,
            "live_execution_allowed": self.live_execution_allowed,
            "signer_allowed": self.signer_allowed,
            "sender_allowed": self.sender_allowed,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_set(value: Any) -> set[Any]:
    if isinstance(value, (list, tuple, set, frozenset)):
        return set(value)
    return set()


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(_HEX64.fullmatch(value))


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _has_materialized_ref(value: Any) -> bool:
    data = _as_mapping(value)
    return (
        _is_nonempty_string(data.get("path"))
        and _is_digest(data.get("sha256"))
        and not str(data.get("path", "")).startswith("/tmp/")
    )


def _require(condition: bool, violations: list[MPR03Violation], code: str, message: str) -> None:
    if not condition:
        violations.append(MPR03Violation(code, message))


def validate_mpr03_evidence(evidence: Mapping[str, Any]) -> MPR03Report:
    """Validate the MPR-03 evidence contract.

    The input is a plain mapping so callers can load it from JSON, YAML, or an
    immutable release bundle.  Missing, stale, self-attested, placeholder or
    unsafe evidence always produces a blocked report.
    """

    violations: list[MPR03Violation] = []

    _require(
        evidence.get("schema_version") == SCHEMA_VERSION,
        violations,
        "BAD_SCHEMA_VERSION",
        f"schema_version must be {SCHEMA_VERSION}",
    )

    debt_ids = _as_set(evidence.get("debt_ids"))
    missing_debt = sorted(REQUIRED_DEBT_IDS - debt_ids)
    extra_debt = sorted(debt_ids - REQUIRED_DEBT_IDS)
    _require(
        not missing_debt and not extra_debt and len(debt_ids) == len(REQUIRED_DEBT_IDS),
        violations,
        "DEBT_COVERAGE_MISMATCH",
        f"debt coverage must exactly match MPR-03 set; missing={missing_debt} extra={extra_debt}",
    )

    upstream = _as_mapping(evidence.get("upstream"))
    _require(
        upstream.get("mpr01_accepted") is True and _is_digest(upstream.get("mpr01_report_sha256")),
        violations,
        "MPR01_NOT_ACCEPTED",
        "MPR-03 requires materialized accepted MPR-01 evidence",
    )
    _require(
        upstream.get("mpr02_accepted") is True and _is_digest(upstream.get("mpr02_report_sha256")),
        violations,
        "MPR02_NOT_ACCEPTED",
        "MPR-03 requires materialized accepted MPR-02 evidence",
    )

    economics = _as_mapping(evidence.get("finalized_economics"))
    _require(
        economics.get("integer_base_units_only") is True
        and economics.get("quote_bound") is True
        and economics.get("simulation_bound") is True
        and economics.get("reservation_bound") is True
        and economics.get("payer_balance_deltas_bound") is True
        and economics.get("token_account_deltas_bound") is True
        and economics.get("flashloan_repayment_math_bound") is True
        and economics.get("fail_closed_when_finalized_unavailable") is True,
        violations,
        "FINALIZED_ECONOMICS_INCOMPLETE",
        "terminal outcome must reconcile quote, exact simulation, reservation, balance/token deltas and flashloan repayment math",
    )
    _require(
        economics.get("gross_spread_can_mark_success") is False
        and economics.get("conservative_net_required") is True
        and economics.get("negative_or_zero_net_blocks_success") is True,
        violations,
        "GROSS_SPREAD_SUCCESS_ALLOWED",
        "gross spread must not become paper success without conservative positive net economics",
    )
    _require(
        _has_materialized_ref(economics.get("materialized_report")),
        violations,
        "ECONOMICS_REPORT_NOT_MATERIALIZED",
        "finalized economic proof must be materialized with a stable digest",
    )

    persistence = _as_mapping(evidence.get("persistence"))
    _require(
        persistence.get("approved_factory_only") is True
        and persistence.get("direct_sqlite_connect_sites_remaining") == 0
        and persistence.get("direct_aiosqlite_connect_sites_remaining") == 0
        and persistence.get("central_pragma_policy") is True
        and persistence.get("schema_fingerprint") is True
        and persistence.get("migration_version_guard") is True
        and persistence.get("exactly_once_terminal_state") is True
        and persistence.get("crash_restart_no_duplicate_terminal") is True,
        violations,
        "PERSISTENCE_CUTOVER_INCOMPLETE",
        "direct DB islands must be removed/quarantined behind the approved persistence factory with exactly-once terminal state",
    )

    backup = _as_mapping(evidence.get("backup_recovery"))
    _require(
        tuple(backup.get("publication_steps", ())) == REQUIRED_BACKUP_STEPS
        and backup.get("restore_validation") is True
        and backup.get("rollback_markers") is True
        and backup.get("previous_generation_preserved") is True,
        violations,
        "BACKUP_PROTOCOL_INCOMPLETE",
        "backup must use temp->fsync->atomic rename->fsync dir->generation pointer and preserve rollback generation",
    )
    missing_faults = sorted(REQUIRED_BACKUP_FAULTS - _as_set(backup.get("fault_matrix")))
    _require(
        not missing_faults,
        violations,
        "BACKUP_FAULT_MATRIX_INCOMPLETE",
        f"backup/restore fault matrix missing: {missing_faults}",
    )

    observability = _as_mapping(evidence.get("observability"))
    readiness_states = _as_set(observability.get("readiness_states"))
    metrics = _as_set(observability.get("metrics"))
    _require(
        REQUIRED_READINESS_STATES <= readiness_states
        and observability.get("readiness_not_static_config_flag") is True
        and observability.get("live_denied_state_present") is True,
        violations,
        "READINESS_STATES_INCOMPLETE",
        "readiness must distinguish safe idle, blocked, degraded, shadow-ready, release-ready and live-denied states",
    )
    _require(
        REQUIRED_METRICS <= metrics
        and observability.get("stable_cardinality") is True
        and observability.get("secret_redaction_corpus") is True,
        violations,
        "OBSERVABILITY_METRICS_INCOMPLETE",
        "observability must expose freshness, lag, DB contention, reservation, lineage, drift and backup metrics with redaction",
    )

    soak = _as_mapping(evidence.get("shadow_soak"))
    lineage = _as_mapping(soak.get("lineage_counts"))
    _require(
        soak.get("sender_free") is True
        and soak.get("materialized_report") is not None
        and _has_materialized_ref(soak.get("materialized_report"))
        and {"synthetic", "recorded", "credentialed", "finalized"} <= set(lineage),
        violations,
        "SHADOW_SOAK_LINEAGE_INCOMPLETE",
        "shadow soak report must be sender-free, materialized and separate synthetic/recorded/credentialed/finalized lineage",
    )
    _require(
        soak.get("synthetic_counted_as_real_release_evidence") is False
        and soak.get("recorded_counted_as_real_release_evidence") is False,
        violations,
        "SYNTHETIC_RELEASE_EVIDENCE_ALLOWED",
        "synthetic or recorded data must not be counted as real release evidence",
    )

    manifest = _as_mapping(evidence.get("release_manifest"))
    missing_manifest = sorted(REQUIRED_MANIFEST_KEYS - set(manifest))
    _require(
        not missing_manifest,
        violations,
        "RELEASE_MANIFEST_KEYS_MISSING",
        f"production cutover manifest missing keys: {missing_manifest}",
    )
    bad_manifest_keys: list[str] = []
    for key in REQUIRED_MANIFEST_KEYS & set(manifest):
        item = _as_mapping(manifest[key])
        if item.get("status") == "available":
            if not _is_digest(item.get("sha256")):
                bad_manifest_keys.append(key)
        elif item.get("status") == "fail_closed_missing":
            if not _is_nonempty_string(item.get("reason")):
                bad_manifest_keys.append(key)
        else:
            bad_manifest_keys.append(key)
    _require(
        not bad_manifest_keys,
        violations,
        "RELEASE_MANIFEST_NOT_FAIL_CLOSED",
        f"manifest entries must be digest-available or explicit fail_closed_missing: {bad_manifest_keys}",
    )

    incident = _as_mapping(evidence.get("secret_incident_drill"))
    _require(
        incident.get("rotation_drill") is True
        and incident.get("revocation_drill") is True
        and incident.get("diagnostic_redaction_drill") is True
        and _has_materialized_ref(incident.get("materialized_report")),
        violations,
        "SECRET_INCIDENT_DRILL_INCOMPLETE",
        "secret incident drill must prove rotation, revocation and redacted diagnostics with materialized report",
    )

    forbidden = _as_mapping(evidence.get("forbidden_runtime"))
    _require(
        forbidden.get("live_execution_requested") is False
        and forbidden.get("signer_requested") is False
        and forbidden.get("sender_requested") is False
        and forbidden.get("private_key_material_present") is False,
        violations,
        "FORBIDDEN_RUNTIME_SURFACE_REQUESTED",
        "MPR-03 must not enable live, signer, sender or private-key material",
    )

    ready = not violations
    return MPR03Report(
        schema_version=SCHEMA_VERSION,
        ready=ready,
        violations=tuple(violations),
        paper_shadow_evidence_review_allowed=ready,
    )


def assert_mpr03_ready(evidence: Mapping[str, Any]) -> MPR03Report:
    """Return the report or raise ValueError with stable violation codes."""

    report = validate_mpr03_evidence(evidence)
    if not report.ready:
        codes = ",".join(violation.code for violation in report.violations)
        raise ValueError(f"MPR-03 evidence blocked: {codes}")
    return report
