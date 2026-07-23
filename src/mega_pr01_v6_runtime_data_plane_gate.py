"""MEGA-PR-01 V6 runtime/data-plane repair acceptance gate.

The V6 audit adds three MEGA-PR-01 findings:

* IMPL-85: Jupiter quota must be account-wide across processes/restarts.
* IMPL-86: Jupiter cache identity must be semantic and checked before quota spend.
* IMPL-94: container management secret reads must use a single-open boundary.

This module is side-effect-free. It does not call Jupiter, RPC, Jito, a signer or
sender. It gives the runtime a deterministic fail-closed contract before these
repairs may be counted as operational paper evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping, Sequence

SCHEMA_VERSION = "mega-pr-01.v6.runtime-data-plane-repair.v1"
REQUIRED_FINDINGS = ("IMPL-85", "IMPL-86", "IMPL-94")
SEMANTIC_CACHE_FIELDS = frozenset(
    {
        "api_account_hash",
        "endpoint_schema",
        "input_mint",
        "output_mint",
        "amount",
        "taker",
        "payer",
        "slippage_bps",
        "dex_policy",
        "purpose",
        "lifecycle_stage",
    }
)


class MegaPR01V6Decision(StrEnum):
    READY_FOR_MPR01_REVIEW = "READY_FOR_MPR01_REVIEW"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class MegaPR01V6Violation:
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class MegaPR01V6Report:
    schema_version: str
    decision: MegaPR01V6Decision
    violations: tuple[MegaPR01V6Violation, ...]
    live_enabled: bool = False
    signer_loaded: bool = False
    sender_loaded: bool = False

    @property
    def ready(self) -> bool:
        return self.decision is MegaPR01V6Decision.READY_FOR_MPR01_REVIEW

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "decision": self.decision.value,
            "ready": self.ready,
            "violations": [
                {"code": item.code, "detail": item.detail} for item in self.violations
            ],
            "live_enabled": False,
            "signer_loaded": False,
            "sender_loaded": False,
        }


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _bool(mapping: Mapping[str, object], key: str) -> bool:
    return mapping.get(key) is True


def _violate(
    violations: list[MegaPR01V6Violation],
    code: str,
    detail: str,
) -> None:
    violations.append(MegaPR01V6Violation(code, detail))


def _require_bool(
    violations: list[MegaPR01V6Violation],
    mapping: Mapping[str, object],
    key: str,
    code: str,
) -> None:
    if not _bool(mapping, key):
        _violate(violations, code, f"{key} must be true")


def _validate_findings(
    violations: list[MegaPR01V6Violation],
    evidence: Mapping[str, object],
) -> None:
    raw = evidence.get("closed_findings")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        _violate(violations, "MPR01_V6_FINDINGS_MISSING", "closed_findings required")
        return
    values = tuple(str(item) for item in raw)
    if len(set(values)) != len(values):
        _violate(violations, "MPR01_V6_FINDINGS_DUPLICATE", "duplicate finding closure")
    missing = tuple(item for item in REQUIRED_FINDINGS if item not in values)
    if missing:
        _violate(
            violations,
            "MPR01_V6_FINDINGS_INCOMPLETE",
            f"missing findings: {','.join(missing)}",
        )


def _validate_quota(
    violations: list[MegaPR01V6Violation],
    evidence: Mapping[str, object],
) -> None:
    quota = _as_mapping(evidence.get("durable_jupiter_quota"))
    for key, code in (
        ("api_account_scoped", "MPR01_V6_QUOTA_NOT_ACCOUNT_SCOPED"),
        ("serialized_with_begin_immediate", "MPR01_V6_QUOTA_NOT_SERIALIZED"),
        ("cross_process_tested", "MPR01_V6_QUOTA_NOT_CROSS_PROCESS"),
        ("restart_recovery_tested", "MPR01_V6_QUOTA_NO_RESTART_RECOVERY"),
        ("cooldown_persisted", "MPR01_V6_QUOTA_COOLDOWN_NOT_DURABLE"),
        ("reserve_mark_used_release_atomic", "MPR01_V6_QUOTA_TRANSITIONS_NOT_ATOMIC"),
    ):
        _require_bool(violations, quota, key, code)


def _validate_cache(
    violations: list[MegaPR01V6Violation],
    evidence: Mapping[str, object],
) -> None:
    cache = _as_mapping(evidence.get("semantic_jupiter_cache"))
    for key, code in (
        ("canonical_json_sha256", "MPR01_V6_CACHE_NOT_CANONICAL"),
        ("collision_property_tested", "MPR01_V6_CACHE_COLLISION_NOT_TESTED"),
        ("lookup_before_quota_spend", "MPR01_V6_CACHE_LOOKUP_AFTER_QUOTA"),
        ("trace_id_excluded_from_identity", "MPR01_V6_CACHE_TRACE_ID_IDENTITY"),
        ("provenance_bound_to_request_response", "MPR01_V6_CACHE_PROVENANCE_MISSING"),
    ):
        _require_bool(violations, cache, key, code)
    raw_fields = cache.get("identity_fields")
    fields = set(str(item) for item in raw_fields) if isinstance(raw_fields, Sequence) else set()
    missing = tuple(sorted(SEMANTIC_CACHE_FIELDS.difference(fields)))
    if missing:
        _violate(
            violations,
            "MPR01_V6_CACHE_FIELDS_INCOMPLETE",
            f"missing cache identity fields: {','.join(missing)}",
        )


def _validate_filesystem(
    violations: list[MegaPR01V6Violation],
    evidence: Mapping[str, object],
) -> None:
    fs = _as_mapping(evidence.get("management_secret_filesystem"))
    for key, code in (
        ("uses_single_open_helper", "MPR01_V6_SECRET_NO_SINGLE_OPEN"),
        ("uses_no_follow", "MPR01_V6_SECRET_NO_NOFOLLOW"),
        ("fstat_before_after", "MPR01_V6_SECRET_NO_FSTAT_BOUNDARY"),
        ("owner_only_enforced", "MPR01_V6_SECRET_OWNER_NOT_ENFORCED"),
        ("symlink_path_swap_tested", "MPR01_V6_SECRET_SWAP_NOT_TESTED"),
        ("check_then_open_removed", "MPR01_V6_SECRET_CHECK_THEN_OPEN"),
    ):
        _require_bool(violations, fs, key, code)


def _validate_safety(
    violations: list[MegaPR01V6Violation],
    evidence: Mapping[str, object],
) -> None:
    for key in (
        "live_enabled",
        "jito_enabled",
        "signer_loaded",
        "sender_loaded",
        "private_key_loaded",
    ):
        if evidence.get(key) is True:
            _violate(violations, "MPR01_V6_FORBIDDEN_RUNTIME_SURFACE", key)


def evaluate_mega_pr01_v6_runtime_data_plane_evidence(
    evidence: Mapping[str, object],
) -> MegaPR01V6Report:
    violations: list[MegaPR01V6Violation] = []
    _validate_findings(violations, evidence)
    _validate_quota(violations, evidence)
    _validate_cache(violations, evidence)
    _validate_filesystem(violations, evidence)
    _validate_safety(violations, evidence)
    return MegaPR01V6Report(
        schema_version=SCHEMA_VERSION,
        decision=(
            MegaPR01V6Decision.READY_FOR_MPR01_REVIEW
            if not violations
            else MegaPR01V6Decision.BLOCKED
        ),
        violations=tuple(violations),
    )


__all__ = [
    "MegaPR01V6Decision",
    "MegaPR01V6Report",
    "MegaPR01V6Violation",
    "REQUIRED_FINDINGS",
    "SCHEMA_VERSION",
    "evaluate_mega_pr01_v6_runtime_data_plane_evidence",
]
