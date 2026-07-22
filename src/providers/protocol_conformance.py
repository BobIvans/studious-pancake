"""MEGA-PR B provider/protocol conformance contracts.

This module is intentionally offline and side-effect free. It does not perform
network probes; it validates whether externally captured provider/protocol
evidence is promotable by the canonical sender-free paper runtime.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
import re
from urllib.parse import urlparse

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REFERENCE_DATE_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")


class ProviderConformanceError(ValueError):
    """Raised when provider conformance evidence is malformed."""


class ProviderId(StrEnum):
    JUPITER = "jupiter"
    MARGINFI = "marginfi"
    KAMINO = "kamino"
    HELIUS = "helius"
    JITO = "jito"
    SOLANA_RPC = "solana-rpc"


class PromotionState(StrEnum):
    BLOCKED = "blocked"
    REPLAY_ONLY = "replay-only"
    PROTECTED_PROBE = "protected-probe"
    PROMOTED_READONLY = "promoted-readonly"


class AuthMode(StrEnum):
    NONE = "none"
    API_KEY = "api-key"
    HEADER = "header"
    RPC_PROVIDER_KEY = "rpc-provider-key"
    PROGRAM_DEPLOYMENT = "program-deployment"


class Purpose(StrEnum):
    ROUTE_BUILD = "route-build"
    PROGRAM_ATTESTATION = "program-attestation"
    WEBHOOK_DELIVERY = "webhook-delivery"
    TIP_ACCOUNT_DISCOVERY = "tip-account-discovery"
    ROOTED_RPC_READ = "rooted-rpc-read"
    UNSUPPORTED_REGISTRY = "unsupported-registry"


@dataclass(frozen=True, slots=True)
class OfficialReference:
    source_url: str
    reviewed_on: str
    reviewer: str

    def __post_init__(self) -> None:
        parsed = urlparse(self.source_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ProviderConformanceError("official reference must be an https URL")
        if not _REFERENCE_DATE_RE.fullmatch(self.reviewed_on):
            raise ProviderConformanceError("reviewed_on must use YYYY-MM-DD")
        if not self.reviewer.strip():
            raise ProviderConformanceError("official reference reviewer is required")


@dataclass(frozen=True, slots=True)
class ProviderProtocolEvidence:
    provider: ProviderId
    purpose: Purpose
    endpoint: str
    method: str
    auth_mode: AuthMode
    request_schema_sha256: str
    response_schema_sha256: str
    credentialed_probe_sha256: str
    negative_fixture_sha256: str
    max_body_bytes: int
    timeout_ms: int
    retry_budget: int
    freshness_contract: str
    quota_contract: str
    consistency_contract: str
    promotion_state: PromotionState
    official_reference: OfficialReference
    drift_revokes_admission: bool = True
    packaged_surface: str = "src.providers"

    def __post_init__(self) -> None:
        for field_name, value in (
            ("request_schema_sha256", self.request_schema_sha256),
            ("response_schema_sha256", self.response_schema_sha256),
            ("credentialed_probe_sha256", self.credentialed_probe_sha256),
            ("negative_fixture_sha256", self.negative_fixture_sha256),
        ):
            _validate_sha256(field_name, value)
        if self.max_body_bytes <= 0 or self.max_body_bytes > 10_000_000:
            raise ProviderConformanceError("max_body_bytes must be bounded")
        if self.timeout_ms <= 0 or self.timeout_ms > 30_000:
            raise ProviderConformanceError("timeout_ms must be positive and bounded")
        if self.retry_budget < 0 or self.retry_budget > 5:
            raise ProviderConformanceError("retry_budget must be bounded")
        for field_name, value in (
            ("endpoint", self.endpoint),
            ("method", self.method),
            ("freshness_contract", self.freshness_contract),
            ("quota_contract", self.quota_contract),
            ("consistency_contract", self.consistency_contract),
            ("packaged_surface", self.packaged_surface),
        ):
            if not value.strip():
                raise ProviderConformanceError(f"{field_name} is required")
        if not self.drift_revokes_admission:
            raise ProviderConformanceError("provider drift must revoke admission")
        _reject_legacy_endpoint(self)


@dataclass(frozen=True, slots=True)
class ProviderConformanceManifest:
    schema_version: str
    evidences: tuple[ProviderProtocolEvidence, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "mega-pr-b.provider-conformance.v1":
            raise ProviderConformanceError("unsupported provider conformance schema")
        if not self.evidences:
            raise ProviderConformanceError("provider conformance evidence is required")
        keys = [(item.provider, item.purpose, item.endpoint) for item in self.evidences]
        if len(keys) != len(set(keys)):
            raise ProviderConformanceError("provider conformance entries must be unique")


@dataclass(frozen=True, slots=True)
class ProviderConformanceReport:
    admitted: bool
    blockers: tuple[str, ...]
    provider_states: Mapping[str, str]


def evaluate_provider_conformance(
    manifest: ProviderConformanceManifest,
    *,
    required: Iterable[tuple[ProviderId, Purpose]] = (),
) -> ProviderConformanceReport:
    blockers: list[str] = []
    provider_states = {
        f"{item.provider.value}:{item.purpose.value}": item.promotion_state.value
        for item in manifest.evidences
    }
    by_key = {(item.provider, item.purpose): item for item in manifest.evidences}

    for provider, purpose in required:
        if (provider, purpose) not in by_key:
            blockers.append(f"missing:{provider.value}:{purpose.value}")

    for item in manifest.evidences:
        if item.promotion_state is PromotionState.BLOCKED:
            continue
        if item.provider is ProviderId.KAMINO and item.purpose is Purpose.UNSUPPORTED_REGISTRY:
            blockers.append("kamino:unsupported-combination-promoted")
        if item.provider is ProviderId.MARGINFI:
            _check_marginfi_truth(item, blockers)
        if not item.packaged_surface.startswith("src.providers"):
            blockers.append(f"{item.provider.value}:not-in-supported-provider-package")

    return ProviderConformanceReport(
        admitted=not blockers,
        blockers=tuple(blockers),
        provider_states=provider_states,
    )


def required_pr_b_readonly_surfaces() -> tuple[tuple[ProviderId, Purpose], ...]:
    return (
        (ProviderId.JUPITER, Purpose.ROUTE_BUILD),
        (ProviderId.MARGINFI, Purpose.PROGRAM_ATTESTATION),
        (ProviderId.HELIUS, Purpose.WEBHOOK_DELIVERY),
        (ProviderId.JITO, Purpose.TIP_ACCOUNT_DISCOVERY),
        (ProviderId.SOLANA_RPC, Purpose.ROOTED_RPC_READ),
        (ProviderId.KAMINO, Purpose.UNSUPPORTED_REGISTRY),
    )


def _validate_sha256(field_name: str, value: str) -> None:
    lowered = value.lower()
    if value != lowered or not _SHA256_RE.fullmatch(value) or value == "0" * 64:
        raise ProviderConformanceError(f"{field_name} must be a real lowercase sha256")


def _reject_legacy_endpoint(evidence: ProviderProtocolEvidence) -> None:
    endpoint = evidence.endpoint.lower()
    method = evidence.method.strip()
    if evidence.provider is ProviderId.JUPITER:
        if evidence.purpose is Purpose.ROUTE_BUILD and "/swap/v2/build" not in endpoint:
            raise ProviderConformanceError("jupiter route build must use /swap/v2/build")
        stale = ("/swap/v1/", "/swap/v2/quote", "/swap/v2/swap-instructions")
        if any(fragment in endpoint for fragment in stale):
            raise ProviderConformanceError("legacy Jupiter endpoint is not promotable")
    if evidence.provider is ProviderId.JITO:
        if "tip_accounts" in endpoint or "tip-accounts" in endpoint:
            raise ProviderConformanceError("Jito tip accounts must use JSON-RPC")
        if evidence.purpose is Purpose.TIP_ACCOUNT_DISCOVERY and method != "getTipAccounts":
            raise ProviderConformanceError("Jito tip discovery method must be getTipAccounts")
    if evidence.provider is ProviderId.HELIUS:
        if evidence.purpose is Purpose.WEBHOOK_DELIVERY and evidence.auth_mode is not AuthMode.HEADER:
            raise ProviderConformanceError("Helius delivery must verify Authorization header")


def _check_marginfi_truth(
    evidence: ProviderProtocolEvidence,
    blockers: list[str],
) -> None:
    combined = " ".join(
        (
            evidence.freshness_contract,
            evidence.quota_contract,
            evidence.consistency_contract,
        )
    ).lower()
    if "env" in combined or "percentage" in combined:
        blockers.append("marginfi:fee-repayment-truth-not-evidence-bound")


__all__ = [
    "AuthMode",
    "OfficialReference",
    "PromotionState",
    "ProviderConformanceError",
    "ProviderConformanceManifest",
    "ProviderConformanceReport",
    "ProviderId",
    "ProviderProtocolEvidence",
    "Purpose",
    "evaluate_provider_conformance",
    "required_pr_b_readonly_surfaces",
]
