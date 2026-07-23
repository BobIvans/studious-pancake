"""MEGA-PR-01 V6 runtime/data-plane repair acceptance gate.

The V6 audit adds three MEGA-PR-01 findings:

* IMPL-85: Jupiter quota must be account-wide across processes/restarts.
* IMPL-86: Jupiter cache identity must be semantic and collision-free.
* IMPL-94: management-secret reads must use single-open/no-follow evidence.

This module is a side-effect-free evidence contract. It does not call providers,
open signer/sender paths, load secrets or enable live execution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
from typing import Mapping, Sequence

SCHEMA_VERSION = "mega-pr-01.v6.runtime-data-plane-repair.v1"
REQUIRED_FINDINGS = frozenset({"IMPL-85", "IMPL-86", "IMPL-94"})
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


class MegaPr01V6Decision(StrEnum):
    READY_FOR_RUNTIME_WIRING = "READY_FOR_RUNTIME_WIRING"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class MegaPr01V6Violation:
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class MegaPr01V6Report:
    schema_version: str
    decision: MegaPr01V6Decision
    violations: tuple[MegaPr01V6Violation, ...]
    finding_ids: tuple[str, ...]
    evidence_hash: str
    durable_quota_ready: bool
    semantic_cache_ready: bool
    single_open_secret_ready: bool
    live_enabled: bool = False
    signer_loaded: bool = False
    sender_loaded: bool = False
    runtime_wiring_allowed: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.decision is MegaPr01V6Decision.READY_FOR_RUNTIME_WIRING

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "decision": self.decision.value,
            "violations": [
                {"code": item.code, "detail": item.detail} for item in self.violations
            ],
            "finding_ids": list(self.finding_ids),
            "evidence_hash": self.evidence_hash,
            "durable_quota_ready": self.durable_quota_ready,
            "semantic_cache_ready": self.semantic_cache_ready,
            "single_open_secret_ready": self.single_open_secret_ready,
            "live_enabled": False,
            "signer_loaded": False,
            "sender_loaded": False,
            "runtime_wiring_allowed": self.runtime_wiring_allowed,
            "metadata": dict(self.metadata),
        }


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _as_sequence(value: object) -> Sequence[object]:
    return value if isinstance(value, Sequence) and not isinstance(value, str) else ()


def _violate(
    violations: list[MegaPr01V6Violation], code: str, detail: str
) -> None:
    violations.append(MegaPr01V6Violation(code=code, detail=detail))


def _require_bool(
    violations: list[MegaPr01V6Violation],
    evidence: Mapping[str, object],
    key: str,
    code: str,
) -> bool:
    if evidence.get(key) is True:
        return True
    _violate(violations, code, f"{key} must be true")
    return False


def _stable_hash(evidence: Mapping[str, object]) -> str:
    encoded = json.dumps(
        evidence,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_findings(
    violations: list[MegaPr01V6Violation], evidence: Mapping[str, object]
) -> tuple[str, ...]:
    raw = _as_sequence(evidence.get("finding_ids"))
    findings = tuple(str(item) for item in raw)
    missing = tuple(sorted(REQUIRED_FINDINGS.difference(findings)))
    extra_duplicates = len(findings) != len(set(findings))
    if missing:
        _violate(
            violations,
            "MPR01_V6_FINDINGS_INCOMPLETE",
            f"missing findings: {','.join(missing)}",
        )
    if extra_duplicates:
        _violate(
            violations,
            "MPR01_V6_FINDINGS_DUPLICATED",
            "finding_ids must be unique",
        )
    return tuple(sorted(set(findings)))


def _validate_durable_quota(
    violations: list[MegaPr01V6Violation],
    evidence: Mapping[str, object],
) -> None:
    quota = _as_mapping(evidence.get("durable_jupiter_quota"))
    for key, code in (
        ("sqlite_backed", "MPR01_V6_QUOTA_NOT_DURABLE"),
        ("api_account_scoped", "MPR01_V6_QUOTA_NOT_ACCOUNT_SCOPED"),
        ("begin_immediate_serialized", "MPR01_V6_QUOTA_NOT_SERIALIZED"),
        ("cross_process_tested", "MPR01_V6_QUOTA_NOT_CROSS_PROCESS"),
        ("restart_recovery_tested", "MPR01_V6_QUOTA_NO_RESTART_RECOVERY"),
        ("cooldown_persisted", "MPR01_V6_COOLDOWN_NOT_PERSISTED"),
        ("mark_used_exactly_once", "MPR01_V6_QUOTA_MARK_USED_NOT_EXACTLY_ONCE"),
    ):
        _require_bool(violations, quota, key, code)
    limit = quota.get("limit")
    reserve = quota.get("finalization_reserve")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        _violate(violations, "MPR01_V6_QUOTA_LIMIT_INVALID", "limit must be > 0")
    if not isinstance(reserve, int) or isinstance(reserve, bool) or reserve < 0:
        _violate(
            violations,
            "MPR01_V6_QUOTA_RESERVE_INVALID",
            "finalization_reserve must be >= 0",
        )
    elif isinstance(limit, int) and reserve >= limit:
        _violate(
            violations,
            "MPR01_V6_QUOTA_RESERVE_EXHAUSTS_LIMIT",
            "finalization reserve must be smaller than limit",
        )


def _validate_semantic_cache(
    violations: list[MegaPr01V6Violation],
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
    fields = (
        set(str(item) for item in raw_fields)
        if isinstance(raw_fields, Sequence)
        else set()
    )
    missing = tuple(sorted(SEMANTIC_CACHE_FIELDS.difference(fields)))
    if missing:
        _violate(
            violations,
            "MPR01_V6_CACHE_FIELDS_INCOMPLETE",
            f"missing cache identity fields: {','.join(missing)}",
        )


def _validate_single_open_secret(
    violations: list[MegaPr01V6Violation],
    evidence: Mapping[str, object],
) -> None:
    secret = _as_mapping(evidence.get("management_secret_read"))
    for key, code in (
        ("uses_read_secure_regular_file", "MPR01_V6_SECRET_NOT_SECURE_FILE"),
        ("single_open_no_follow", "MPR01_V6_SECRET_NOT_SINGLE_OPEN"),
        ("fstat_before_after", "MPR01_V6_SECRET_NO_FSTAT_BOUNDARY"),
        ("symlink_rejected", "MPR01_V6_SECRET_SYMLINK_ALLOWED"),
        ("path_swap_tested", "MPR01_V6_SECRET_PATH_SWAP_NOT_TESTED"),
        ("owner_only_required", "MPR01_V6_SECRET_NOT_OWNER_ONLY"),
    ):
        _require_bool(violations, secret, key, code)


def _validate_forbidden_runtime(
    violations: list[MegaPr01V6Violation], evidence: Mapping[str, object]
) -> None:
    forbidden = (
        "live_enabled",
        "jito_enabled",
        "signer_loaded",
        "sender_loaded",
        "private_key_loaded",
        "provider_network_enabled",
    )
    for key in forbidden:
        if evidence.get(key) is True:
            _violate(
                violations,
                "MPR01_V6_FORBIDDEN_RUNTIME_SURFACE",
                f"{key} must remain false",
            )


def evaluate_mega_pr01_v6_runtime_data_plane_evidence(
    evidence: Mapping[str, object]
) -> MegaPr01V6Report:
    violations: list[MegaPr01V6Violation] = []
    finding_ids = _validate_findings(violations, evidence)
    _validate_durable_quota(violations, evidence)
    _validate_semantic_cache(violations, evidence)
    _validate_single_open_secret(violations, evidence)
    _validate_forbidden_runtime(violations, evidence)

    durable_ready = not any(item.code.startswith("MPR01_V6_QUOTA") for item in violations)
    durable_ready = durable_ready and not any(
        item.code == "MPR01_V6_COOLDOWN_NOT_PERSISTED" for item in violations
    )
    cache_ready = not any(item.code.startswith("MPR01_V6_CACHE") for item in violations)
    secret_ready = not any(item.code.startswith("MPR01_V6_SECRET") for item in violations)
    decision = (
        MegaPr01V6Decision.READY_FOR_RUNTIME_WIRING
        if not violations
        else MegaPr01V6Decision.BLOCKED
    )
    return MegaPr01V6Report(
        schema_version=SCHEMA_VERSION,
        decision=decision,
        violations=tuple(violations),
        finding_ids=finding_ids,
        evidence_hash=_stable_hash(evidence),
        durable_quota_ready=durable_ready,
        semantic_cache_ready=cache_ready,
        single_open_secret_ready=secret_ready,
        runtime_wiring_allowed=decision is MegaPr01V6Decision.READY_FOR_RUNTIME_WIRING,
        metadata={
            "required_findings": tuple(sorted(REQUIRED_FINDINGS)),
            "semantic_cache_fields": tuple(sorted(SEMANTIC_CACHE_FIELDS)),
        },
    )


__all__ = [
    "MegaPr01V6Decision",
    "MegaPr01V6Report",
    "MegaPr01V6Violation",
    "REQUIRED_FINDINGS",
    "SCHEMA_VERSION",
    "evaluate_mega_pr01_v6_runtime_data_plane_evidence",
]
