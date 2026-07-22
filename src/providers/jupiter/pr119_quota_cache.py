"""PR-119 Jupiter quota/cache review gate.

This module is intentionally offline and side-effect free.  It makes the
PR-119 contract explicit without changing active provider execution paths:
Jupiter callers must be purpose-aware, preserve a finalization budget, reuse an
exact request cache, share account-level quota across local processes, and carry
Retry-After cooldown evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any

PR119_SCHEMA_VERSION = "pr119.jupiter-quota-cache.v1"
PR119_RESULT_SCHEMA_VERSION = "pr119.jupiter-quota-cache-result.v1"
PR119_READY_STATE = "jupiter-quota-cache-review-ready"
PR119_BLOCKED_STATE = "blocked"

REQUIRED_PURPOSES = (
    "discovery",
    "exact_amount_coupling",
    "refinement",
    "final_build",
    "rebuild_after_blockhash",
    "finalization",
)
REQUIRED_CACHE_IDENTITY_FIELDS = (
    "api_account_identity_hash",
    "request_fingerprint",
    "input_mint",
    "output_mint",
    "amount_base_units",
    "taker",
    "swap_mode",
    "slippage_bps",
    "purpose",
    "schema_version_pin",
)
REQUIRED_TELEMETRY = (
    "requests_by_purpose",
    "cache_hits",
    "quota_wait",
    "finalization_denial",
    "http_429",
    "stale_discard",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PR119ReadinessState(StrEnum):
    BLOCKED = PR119_BLOCKED_STATE
    REVIEW_READY = PR119_READY_STATE


class PR119QuotaCacheError(ValueError):
    """Raised when PR-119 evidence is malformed or blocked."""


@dataclass(frozen=True, slots=True)
class JupiterQuotaCacheIdentity:
    """Redaction-safe exact Jupiter request identity."""

    api_account_identity_hash: str
    request_fingerprint: str
    input_mint: str
    output_mint: str
    amount_base_units: int
    taker: str
    swap_mode: str
    slippage_bps: int
    purpose: str
    schema_version_pin: str
    mode: str = "build"
    max_accounts: int | None = None
    dex_filters: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.amount_base_units <= 0:
            raise PR119QuotaCacheError("amount_base_units must be positive")
        if not 0 <= self.slippage_bps <= 10_000:
            raise PR119QuotaCacheError("slippage_bps must be between 0 and 10000")
        if self.purpose not in REQUIRED_PURPOSES:
            raise PR119QuotaCacheError("purpose is not part of PR-119 contract")
        for name in REQUIRED_CACHE_IDENTITY_FIELDS:
            value = getattr(self, name)
            if isinstance(value, str) and not value.strip():
                raise PR119QuotaCacheError(f"{name} is required")

    @property
    def cache_key(self) -> str:
        payload = _jsonable(self)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return "jupiter:v2:" + hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class PR119QuotaCachePackage:
    """Evidence package for the PR-119 Jupiter quota/cache boundary."""

    purpose_support: Mapping[str, bool]
    cache_identity_fields: Mapping[str, bool]
    telemetry: Mapping[str, bool]
    finalization_reserve_configured: bool
    finalization_quota_reserved: bool
    discovery_cannot_spend_finalization_reserve: bool
    shared_quota_authority: str
    shared_quota_keyed_by_api_account: bool
    cache_reused_before_quota_spend: bool
    exact_final_build_required: bool
    retry_after_numeric_supported: bool
    retry_after_http_date_supported: bool
    retry_after_propagated_to_quota: bool
    cache_key_redacts_secret_values: bool
    cache_key_includes_schema_pin: bool
    parallel_process_tested: bool
    chaos_429_tested: bool
    live_allowed: bool
    sender_enabled: bool
    provider_promotion_enabled: bool
    human_reviewed: bool
    evidence_sha256: str
    schema_version: str = PR119_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PR119_SCHEMA_VERSION:
            raise PR119QuotaCacheError("unsupported PR-119 schema")
        if not _sha256(self.evidence_sha256):
            raise PR119QuotaCacheError("evidence_sha256 must be a SHA-256 digest")
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name in {"purpose_support", "cache_identity_fields", "telemetry"}:
                _require_bool_mapping(field.name, value)
            elif isinstance(value, bool) and type(value) is not bool:
                raise PR119QuotaCacheError(f"{field.name} must be boolean")

    @property
    def package_sha256(self) -> str:
        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class PR119QuotaCacheReadiness:
    schema_version: str
    state: PR119ReadinessState
    review_ready: bool
    live_allowed: bool
    sender_enabled: bool
    provider_promotion_enabled: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    package_sha256: str
    checks_evaluated: int
    metrics_summary: Mapping[str, int | str | bool]

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def evaluate_pr119_quota_cache_package(
    package: PR119QuotaCachePackage,
) -> PR119QuotaCacheReadiness:
    """Evaluate PR-119 readiness without enabling provider execution."""

    blockers: list[str] = []
    checks = 0

    def check(condition: bool, reason: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            blockers.append(reason)

    for purpose in REQUIRED_PURPOSES:
        check(
            package.purpose_support.get(purpose) is True,
            f"PURPOSE_MISSING:{purpose}",
        )
    for field_name in REQUIRED_CACHE_IDENTITY_FIELDS:
        check(
            package.cache_identity_fields.get(field_name) is True,
            f"CACHE_IDENTITY_FIELD_MISSING:{field_name}",
        )
    for metric in REQUIRED_TELEMETRY:
        check(package.telemetry.get(metric) is True, f"TELEMETRY_MISSING:{metric}")

    check(
        package.finalization_reserve_configured,
        "FINALIZATION_RESERVE_NOT_CONFIGURED",
    )
    check(package.finalization_quota_reserved, "FINALIZATION_QUOTA_NOT_RESERVED")
    check(
        package.discovery_cannot_spend_finalization_reserve,
        "DISCOVERY_CAN_SPEND_FINALIZATION_RESERVE",
    )
    check(
        package.shared_quota_authority in {"sqlite", "redis", "single-instance-lock"},
        "SHARED_QUOTA_AUTHORITY_UNSUPPORTED",
    )
    check(
        package.shared_quota_keyed_by_api_account,
        "SHARED_QUOTA_NOT_KEYED_BY_API_ACCOUNT",
    )
    check(package.cache_reused_before_quota_spend, "CACHE_NOT_REUSED_BEFORE_QUOTA")
    check(package.exact_final_build_required, "EXACT_FINAL_BUILD_NOT_REQUIRED")
    check(package.retry_after_numeric_supported, "RETRY_AFTER_NUMERIC_UNSUPPORTED")
    check(package.retry_after_http_date_supported, "RETRY_AFTER_HTTP_DATE_UNSUPPORTED")
    check(package.retry_after_propagated_to_quota, "RETRY_AFTER_NOT_PROPAGATED")
    check(package.cache_key_redacts_secret_values, "CACHE_KEY_LEAKS_SECRET_VALUE")
    check(package.cache_key_includes_schema_pin, "CACHE_KEY_SCHEMA_PIN_MISSING")
    check(package.parallel_process_tested, "PARALLEL_PROCESS_NOT_TESTED")
    check(package.chaos_429_tested, "HTTP_429_CHAOS_NOT_TESTED")
    check(not package.live_allowed, "LIVE_ALLOWED")
    check(not package.sender_enabled, "SENDER_ENABLED")
    check(not package.provider_promotion_enabled, "PROVIDER_PROMOTION_ENABLED")
    check(package.human_reviewed, "HUMAN_REVIEW_MISSING")

    unique = tuple(dict.fromkeys(blockers))
    ready = not unique
    return PR119QuotaCacheReadiness(
        schema_version=PR119_RESULT_SCHEMA_VERSION,
        state=(
            PR119ReadinessState.REVIEW_READY
            if ready
            else PR119ReadinessState.BLOCKED
        ),
        review_ready=ready,
        live_allowed=False,
        sender_enabled=False,
        provider_promotion_enabled=False,
        blockers=unique,
        warnings=("PR119_REVIEW_ONLY_ACTIVE_RUNTIME_UNCHANGED",),
        package_sha256=package.package_sha256,
        checks_evaluated=checks,
        metrics_summary={
            "required_purposes": len(REQUIRED_PURPOSES),
            "required_cache_identity_fields": len(REQUIRED_CACHE_IDENTITY_FIELDS),
            "required_telemetry": len(REQUIRED_TELEMETRY),
            "shared_quota_authority": package.shared_quota_authority,
            "live_allowed": package.live_allowed,
        },
    )


def assert_pr119_quota_cache_package(
    package: PR119QuotaCachePackage,
) -> PR119QuotaCacheReadiness:
    result = evaluate_pr119_quota_cache_package(package)
    if not result.review_ready:
        raise PR119QuotaCacheError(f"PR119_BLOCKED:{','.join(result.blockers)}")
    return result


def _sha256(value: str) -> bool:
    return bool(_SHA256_RE.match(value))


def _digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _require_bool_mapping(name: str, value: object) -> None:
    if not isinstance(value, Mapping):
        raise PR119QuotaCacheError(f"{name} must be a mapping")
    for key, item in value.items():
        if not isinstance(key, str):
            raise PR119QuotaCacheError(f"{name} keys must be strings")
        if type(item) is not bool:
            raise PR119QuotaCacheError(f"{name}.{key} must be boolean")


def _jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value):
        return {
            field.name: _jsonable(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in sorted(value.items())}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value
