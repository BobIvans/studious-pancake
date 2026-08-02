"""PR-196 pass-3 external contract gates.

This module is intentionally sender-free. It validates already-materialized
external evidence for provider transport, rooted data freshness, mint policy,
cycle quota accounting, and retry semantics. It does not open sockets, resolve
DNS, call RPC/HTTP providers, load wallets, sign messages, build transactions,
or submit anything on chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import ipaddress
import json
import re
from typing import Any, Mapping
from urllib.parse import urlparse

PR196_PASS3_SCHEMA_VERSION = "pr196.pass3.external-contract-gates.v1"
LEGACY_SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EP8iFrKGij4kLhYjV4YB"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=-]{0,127}$")
_SAFE_HOST_RE = re.compile(r"^(?=.{1,253}$)(?!-)[A-Za-z0-9.-]+(?<!-)$")


class ExternalContractGateError(ValueError):
    """Fail-closed validation error with a stable PR-196 reason code."""

    def __init__(self, reason_code: str, message: str | None = None) -> None:
        self.reason_code = reason_code
        super().__init__(message or reason_code)


class RetryOperationClass(StrEnum):
    SAFE_READ = "safe_read"
    IDEMPOTENT_BUILD = "idempotent_build"
    NON_RETRYABLE_SEND = "non_retryable_send"


class TokenProgramPolicy(StrEnum):
    LEGACY_SPL_ONLY = "legacy_spl_only"
    TOKEN_2022_FAIL_CLOSED = "token_2022_fail_closed"


@dataclass(frozen=True, slots=True)
class RetryPolicyEvidence:
    """Typed retry policy evidence for one provider operation class."""

    operation_class: RetryOperationClass
    max_attempts: int
    backoff_base_ms: int
    full_jitter: bool
    idempotency_key_required: bool

    def validate(self) -> None:
        if self.max_attempts < 1:
            raise ExternalContractGateError("PR196_RETRY_MAX_ATTEMPTS_INVALID")
        if self.backoff_base_ms < 0:
            raise ExternalContractGateError("PR196_RETRY_BACKOFF_INVALID")
        if self.operation_class is RetryOperationClass.NON_RETRYABLE_SEND:
            if self.max_attempts != 1:
                raise ExternalContractGateError("PR196_SEND_RETRY_FORBIDDEN")
            if self.idempotency_key_required:
                raise ExternalContractGateError("PR196_SEND_IDEMPOTENCY_KEY_MISLEADING")
            return
        if self.max_attempts > 1 and not self.full_jitter:
            raise ExternalContractGateError("PR196_RETRY_FULL_JITTER_REQUIRED")
        if self.operation_class is RetryOperationClass.IDEMPOTENT_BUILD:
            if not self.idempotency_key_required:
                raise ExternalContractGateError("PR196_BUILD_IDEMPOTENCY_KEY_REQUIRED")


@dataclass(frozen=True, slots=True)
class EndpointResolutionEvidence:
    """Materialized DNS/redirect evidence collected by a read-only probe."""

    provider_id: str
    url: str
    resolved_ip: str
    allowed_hosts: frozenset[str]
    pinned_ip_hash: str
    redirect_urls: tuple[str, ...] = ()

    def validate(self) -> str:
        _require_safe_id(self.provider_id, "provider_id")
        if not self.allowed_hosts:
            raise ExternalContractGateError("PR196_ENDPOINT_ALLOWED_HOST_REQUIRED")
        for host in self.allowed_hosts:
            _require_host(host)
        parsed = urlparse(self.url)
        _require_https(parsed.scheme)
        host = parsed.hostname or ""
        _require_host(host)
        if host not in self.allowed_hosts:
            raise ExternalContractGateError("PR196_ENDPOINT_HOST_NOT_ALLOWED")
        _require_public_ip(self.resolved_ip)
        _require_sha256(self.pinned_ip_hash, "pinned_ip_hash")
        if _stable_hash({"host": host, "ip": self.resolved_ip}) != self.pinned_ip_hash:
            raise ExternalContractGateError("PR196_ENDPOINT_IP_PIN_MISMATCH")
        for redirect_url in self.redirect_urls:
            redirect = urlparse(redirect_url)
            _require_https(redirect.scheme)
            redirect_host = redirect.hostname or ""
            _require_host(redirect_host)
            if redirect_host != host:
                raise ExternalContractGateError("PR196_REDIRECT_HOST_CHANGED")
        return self.pinned_ip_hash


@dataclass(frozen=True, slots=True)
class FreshnessEvidence:
    """Rooted provider timestamp evidence using trusted receive time."""

    provider_id: str
    provider_observed_at: str
    trusted_received_at: str
    context_slot: int
    rooted_slot: int
    max_age_seconds: int
    max_future_skew_seconds: int

    def validate(self, *, now: datetime) -> None:
        _require_safe_id(self.provider_id, "provider_id")
        observed = _parse_utc(self.provider_observed_at, "provider_observed_at")
        received = _parse_utc(self.trusted_received_at, "trusted_received_at")
        now_utc = _as_utc(now)
        if self.context_slot < 0 or self.rooted_slot < 0:
            raise ExternalContractGateError("PR196_NEGATIVE_SLOT")
        if self.rooted_slot < self.context_slot:
            raise ExternalContractGateError("PR196_ROOTED_SLOT_BELOW_CONTEXT")
        if self.max_age_seconds <= 0:
            raise ExternalContractGateError("PR196_MAX_AGE_INVALID")
        if self.max_future_skew_seconds < 0:
            raise ExternalContractGateError("PR196_FUTURE_SKEW_INVALID")
        future_skew = (observed - received).total_seconds()
        if future_skew > self.max_future_skew_seconds:
            raise ExternalContractGateError("PR196_PROVIDER_TIMESTAMP_IN_FUTURE")
        trusted_age = (now_utc - received).total_seconds()
        if trusted_age < 0:
            raise ExternalContractGateError("PR196_TRUSTED_RECEIVE_TIME_IN_FUTURE")
        if trusted_age > self.max_age_seconds:
            raise ExternalContractGateError("PR196_PROVIDER_DATA_STALE")


@dataclass(frozen=True, slots=True)
class RequestCostReservation:
    provider_id: str
    operation_id: str
    operation_class: RetryOperationClass
    request_cost_units: int

    def validate(self) -> None:
        _require_safe_id(self.provider_id, "provider_id")
        _require_safe_id(self.operation_id, "operation_id")
        if self.request_cost_units <= 0:
            raise ExternalContractGateError("PR196_REQUEST_COST_INVALID")


@dataclass(frozen=True, slots=True)
class CycleBudgetEvidence:
    """Shared provider/cycle budget, not a process-local limiter snapshot."""

    provider_id: str
    cycle_id: str
    shared_budget_authority: str
    monotonic_started_ns: int
    monotonic_deadline_ns: int
    max_request_cost_units: int
    reservations: tuple[RequestCostReservation, ...] = ()

    def validate(self) -> int:
        _require_safe_id(self.provider_id, "provider_id")
        _require_safe_id(self.cycle_id, "cycle_id")
        _require_safe_id(self.shared_budget_authority, "shared_budget_authority")
        if self.shared_budget_authority == "process-local":
            raise ExternalContractGateError("PR196_PROCESS_LOCAL_QUOTA_FORBIDDEN")
        if self.monotonic_started_ns < 0 or self.monotonic_deadline_ns <= self.monotonic_started_ns:
            raise ExternalContractGateError("PR196_CYCLE_DEADLINE_INVALID")
        if self.max_request_cost_units <= 0:
            raise ExternalContractGateError("PR196_CYCLE_BUDGET_INVALID")
        seen: set[str] = set()
        total = 0
        for reservation in self.reservations:
            reservation.validate()
            if reservation.provider_id != self.provider_id:
                raise ExternalContractGateError("PR196_BUDGET_PROVIDER_MISMATCH")
            if reservation.operation_id in seen:
                raise ExternalContractGateError("PR196_DUPLICATE_OPERATION_RESERVATION")
            seen.add(reservation.operation_id)
            total += reservation.request_cost_units
        if total > self.max_request_cost_units:
            raise ExternalContractGateError("PR196_CYCLE_BUDGET_EXHAUSTED")
        return total


@dataclass(frozen=True, slots=True)
class RootedMintEvidence:
    """Rooted SPL mint policy evidence before candidate planning."""

    mint_address: str
    owner_program_id: str
    decimals: int
    supply: int
    account_hash: str
    rooted_slot: int
    token_extensions: tuple[str, ...] = ()
    freeze_authority: str | None = None
    mint_authority: str | None = None

    def validate(self, *, policy: TokenProgramPolicy) -> None:
        _require_safe_id(self.mint_address, "mint_address")
        _require_safe_id(self.owner_program_id, "owner_program_id")
        _require_sha256(self.account_hash, "account_hash")
        if self.decimals < 0 or self.decimals > 18:
            raise ExternalContractGateError("PR196_MINT_DECIMALS_OUT_OF_RANGE")
        if self.supply < 0:
            raise ExternalContractGateError("PR196_MINT_SUPPLY_NEGATIVE")
        if self.rooted_slot < 0:
            raise ExternalContractGateError("PR196_MINT_ROOTED_SLOT_INVALID")
        for authority_name, authority in (
            ("freeze_authority", self.freeze_authority),
            ("mint_authority", self.mint_authority),
        ):
            if authority is not None:
                _require_safe_id(authority, authority_name)
        for extension in self.token_extensions:
            _require_safe_id(extension, "token_extension")
        if policy is TokenProgramPolicy.LEGACY_SPL_ONLY:
            if self.owner_program_id != LEGACY_SPL_TOKEN_PROGRAM_ID:
                raise ExternalContractGateError("PR196_LEGACY_SPL_MINT_REQUIRED")
            if self.token_extensions:
                raise ExternalContractGateError("PR196_TOKEN2022_EXTENSIONS_FAIL_CLOSED")
            return
        if policy is TokenProgramPolicy.TOKEN_2022_FAIL_CLOSED:
            if self.owner_program_id == TOKEN_2022_PROGRAM_ID or self.token_extensions:
                raise ExternalContractGateError("PR196_TOKEN2022_FAIL_CLOSED")
            if self.owner_program_id != LEGACY_SPL_TOKEN_PROGRAM_ID:
                raise ExternalContractGateError("PR196_UNKNOWN_TOKEN_PROGRAM")


@dataclass(frozen=True, slots=True)
class ExternalContractGateReport:
    schema_version: str
    evidence_hash: str
    endpoint_pins: Mapping[str, str]
    budget_cost_units: Mapping[str, int]
    mint_policy: str
    live_execution_allowed: bool = False
    signer_or_sender_allowed: bool = False


@dataclass(frozen=True, slots=True)
class ExternalContractGateBundle:
    endpoints: tuple[EndpointResolutionEvidence, ...]
    retry_policies: tuple[RetryPolicyEvidence, ...]
    freshness: tuple[FreshnessEvidence, ...]
    budgets: tuple[CycleBudgetEvidence, ...]
    mints: tuple[RootedMintEvidence, ...]
    mint_policy: TokenProgramPolicy = TokenProgramPolicy.TOKEN_2022_FAIL_CLOSED
    required_providers: frozenset[str] = field(default_factory=lambda: frozenset({"jupiter"}))

    def validate(self, *, now: datetime) -> ExternalContractGateReport:
        if not self.endpoints:
            raise ExternalContractGateError("PR196_ENDPOINT_EVIDENCE_REQUIRED")
        if not self.freshness:
            raise ExternalContractGateError("PR196_FRESHNESS_EVIDENCE_REQUIRED")
        if not self.budgets:
            raise ExternalContractGateError("PR196_BUDGET_EVIDENCE_REQUIRED")
        if not self.mints:
            raise ExternalContractGateError("PR196_MINT_EVIDENCE_REQUIRED")
        endpoint_pins: dict[str, str] = {}
        for endpoint in self.endpoints:
            endpoint_pins[endpoint.provider_id] = endpoint.validate()
        for provider in self.required_providers:
            if provider not in endpoint_pins:
                raise ExternalContractGateError("PR196_REQUIRED_PROVIDER_ENDPOINT_MISSING")
        seen_retry_classes: set[RetryOperationClass] = set()
        for retry_policy in self.retry_policies:
            retry_policy.validate()
            seen_retry_classes.add(retry_policy.operation_class)
        for operation_class in (
            RetryOperationClass.SAFE_READ,
            RetryOperationClass.IDEMPOTENT_BUILD,
            RetryOperationClass.NON_RETRYABLE_SEND,
        ):
            if operation_class not in seen_retry_classes:
                raise ExternalContractGateError("PR196_RETRY_CLASS_POLICY_MISSING")
        for item in self.freshness:
            item.validate(now=now)
        budget_cost_units: dict[str, int] = {}
        for budget in self.budgets:
            key = f"{budget.provider_id}:{budget.cycle_id}"
            if key in budget_cost_units:
                raise ExternalContractGateError("PR196_DUPLICATE_CYCLE_BUDGET")
            budget_cost_units[key] = budget.validate()
        for mint in self.mints:
            mint.validate(policy=self.mint_policy)
        evidence_hash = _stable_hash(
            {
                "schema": PR196_PASS3_SCHEMA_VERSION,
                "endpoint_pins": endpoint_pins,
                "budget_cost_units": budget_cost_units,
                "mint_policy": self.mint_policy.value,
                "mint_hashes": [mint.account_hash for mint in self.mints],
            }
        )
        return ExternalContractGateReport(
            schema_version=PR196_PASS3_SCHEMA_VERSION,
            evidence_hash=evidence_hash,
            endpoint_pins=endpoint_pins,
            budget_cost_units=budget_cost_units,
            mint_policy=self.mint_policy.value,
        )


def endpoint_pin_hash(host: str, resolved_ip: str) -> str:
    _require_host(host)
    _require_public_ip(resolved_ip)
    return _stable_hash({"host": host, "ip": resolved_ip})


def _require_sha256(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ExternalContractGateError(f"PR196_INVALID_{field_name.upper()}_SHA256")


def _require_safe_id(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ExternalContractGateError(f"PR196_INVALID_{field_name.upper()}")


def _require_host(value: str) -> None:
    if not isinstance(value, str) or not _SAFE_HOST_RE.fullmatch(value):
        raise ExternalContractGateError("PR196_INVALID_ENDPOINT_HOST")
    if ".." in value:
        raise ExternalContractGateError("PR196_INVALID_ENDPOINT_HOST")


def _require_https(scheme: str) -> None:
    if scheme != "https":
        raise ExternalContractGateError("PR196_ENDPOINT_HTTPS_REQUIRED")


def _require_public_ip(value: str) -> None:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ExternalContractGateError("PR196_INVALID_RESOLVED_IP") from exc
    if not ip.is_global:
        raise ExternalContractGateError("PR196_RESOLVED_IP_NOT_GLOBAL")


def _parse_utc(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExternalContractGateError(f"PR196_INVALID_{field_name.upper()}") from exc
    if parsed.tzinfo is None:
        raise ExternalContractGateError(f"PR196_NAIVE_{field_name.upper()}")
    return parsed.astimezone(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ExternalContractGateError("PR196_NAIVE_NOW")
    return value.astimezone(timezone.utc)


def _stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
