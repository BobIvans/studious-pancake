"""PR-225 secure provider, quote and rooted discovery plane gate.

The module is an offline, sender-free evidence validator for the Pass 8/9
PR-225 roadmap slice.  It intentionally performs no HTTP, RPC, signer, sender,
Jito or live-trading work.  Runtime code must feed it already materialized
provider/transport/quota/quote/discovery evidence before a provider plane can be
considered reviewable.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "pr225.secure-provider-plane.v1"
U64_MAX = 2**64 - 1
SOLANA_PUBKEY_BYTES = 32
MAX_SLIPPAGE_BPS = 1_000
MAX_RESPONSE_BYTES = 1_048_576
REQUIRED_FINDINGS = (
    *(f"F-{number:03d}" for number in range(309, 355)),
    *(f"F-{number:03d}" for number in range(444, 481)),
)
DANGEROUS_RESPONSE_KEYS = {
    "privateKey",
    "secretKey",
    "signature",
    "signatures",
    "swapTransaction",
    "transaction",
    "wallet",
}
FORBIDDEN_CAPABILITIES = {
    "live_enabled",
    "sender_loaded",
    "signer_loaded",
    "private_key_loaded",
    "jito_submit_enabled",
}
BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


class PR225FailureCode(str, Enum):
    INVALID_PROVIDER_REGISTRY = "PR225_INVALID_PROVIDER_REGISTRY"
    UNSAFE_TRANSPORT = "PR225_UNSAFE_TRANSPORT"
    UNSAFE_RETRY_POLICY = "PR225_UNSAFE_RETRY_POLICY"
    NON_DURABLE_QUOTA = "PR225_NON_DURABLE_QUOTA"
    INVALID_RESPONSE_PROVENANCE = "PR225_INVALID_RESPONSE_PROVENANCE"
    INVALID_QUOTE_DOMAIN = "PR225_INVALID_QUOTE_DOMAIN"
    INVALID_DISCOVERY_SELECTION = "PR225_INVALID_DISCOVERY_SELECTION"
    FORBIDDEN_RUNTIME_CAPABILITY = "PR225_FORBIDDEN_RUNTIME_CAPABILITY"
    MISSING_INSTALLED_CYCLE = "PR225_MISSING_INSTALLED_CYCLE"


@dataclass(frozen=True)
class PR225Violation:
    code: PR225FailureCode
    detail: str


@dataclass(frozen=True)
class ProviderContract:
    provider: str
    endpoint: str
    credential_generation_sha256: str
    schema_generation_sha256: str
    allowed_methods: tuple[str, ...]
    additive_unknown_fields_policy: str = "quarantine-dangerous"


@dataclass(frozen=True)
class TransportPolicyEvidence:
    owner: str
    deny_by_default: bool
    allowed_hosts: tuple[str, ...]
    resolved_ip_classes_denied: tuple[str, ...]
    redirect_policy: str
    tls_peer_fingerprint_sha256: str
    ca_bundle_sha256: str
    total_deadline_ms: int
    max_response_bytes: int
    strict_json_duplicate_keys_rejected: bool
    redaction_policy_sha256: str
    injected_client_can_bypass: bool = False


@dataclass(frozen=True)
class RetryPolicyEvidence:
    retries_non_idempotent_post: bool
    provider_idempotency_contract_sha256: str | None
    retry_after_http_date_supported: bool
    jitter_enabled: bool
    total_deadline_covers_retries: bool
    cancellation_cleanup_proven: bool


@dataclass(frozen=True)
class QuotaAuthorityEvidence:
    authority: str
    durable: bool
    account_wide: bool
    credential_generation_sha256: str
    endpoint_generation_sha256: str
    account_plan_sha256: str
    serialized_cross_process: bool
    unknown_purpose_fails_closed: bool
    unknown_token_fails_closed: bool
    two_process_race_proof_sha256: str
    persisted_cooldown_proof_sha256: str
    exact_once_mark_used: bool


@dataclass(frozen=True)
class RawResponseProvenance:
    provider: str
    endpoint: str
    credential_generation_sha256: str
    request_sha256: str
    raw_response_sha256: str
    status_code: int
    header_digest_sha256: str
    received_at_unix_ns: int
    context_slot: int
    provider_timestamp_unix_ns: int
    parsed_keys: tuple[str, ...]
    schema_generation_sha256: str


@dataclass(frozen=True)
class ProviderCapabilities:
    provider: str
    exact_in_supported: bool
    guaranteed_minimum_output_supported: bool
    explicit_expiry_supported: bool
    executable_artifact_supported: bool
    jito_submit_supported: bool = False


@dataclass(frozen=True)
class QuoteRequest:
    provider: str
    input_mint: str
    output_mint: str
    amount: int
    slippage_bps: int
    request_policy_sha256: str


@dataclass(frozen=True)
class NormalizedQuote:
    request: QuoteRequest
    provenance: RawResponseProvenance
    capabilities: ProviderCapabilities
    minimum_output_amount: int
    expected_output_amount: int
    expires_at_unix_ns: int
    executable_artifact_sha256: str
    route_plan_sha256: str
    fee_identity_sha256: str


@dataclass(frozen=True)
class DiscoveryCandidate:
    quote_identity_sha256: str
    guaranteed_profit_base_units: int
    risk_bps: int
    executable_artifact_sha256: str


@dataclass(frozen=True)
class InstalledProviderCycleEvidence:
    installed_wheel_sha256: str
    command_surface_sha256: str
    configured_endpoint: str
    transport_owner: str
    provider_cycle_non_empty: bool
    missing_transport_blocks_startup: bool
    sender_free: bool
    live_enabled: bool = False
    sender_loaded: bool = False
    signer_loaded: bool = False


@dataclass(frozen=True)
class PR225EvidenceBundle:
    schema_version: str
    covered_findings: tuple[str, ...]
    installed_cycle: InstalledProviderCycleEvidence
    providers: tuple[ProviderContract, ...]
    transport: TransportPolicyEvidence
    retry_policy: RetryPolicyEvidence
    quota: QuotaAuthorityEvidence
    quotes: tuple[NormalizedQuote, ...]
    discovery_candidates: tuple[DiscoveryCandidate, ...]
    selected_quote_identity_sha256: str
    runtime_capabilities: Mapping[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class PR225Report:
    ok: bool
    status: str
    schema_version: str
    evidence_digest_sha256: str
    violations: tuple[PR225Violation, ...]
    provider_plane_review_allowed: bool
    provider_network_allowed: bool = False
    executable_candidate_allowed: bool = False
    live_execution_allowed: bool = False
    signer_allowed: bool = False
    sender_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["violations"] = [asdict(item) for item in self.violations]
        return payload


class PR225ValidationError(ValueError):
    """Raised by strict helper validators when evidence is malformed."""


def _json_digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise PR225ValidationError(f"{field} must be lowercase sha256")
    if value in {"0" * 64, "f" * 64}:
        raise PR225ValidationError(f"{field} must not be placeholder")


def _require_non_bool_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PR225ValidationError(f"{field} must be non-bool int")
    return value


def _require_u64(value: object, field: str) -> int:
    number = _require_non_bool_int(value, field)
    if number < 0 or number > U64_MAX:
        raise PR225ValidationError(f"{field} must be within u64")
    return number


def _decode_base58(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise PR225ValidationError("pubkey must be non-empty string")
    number = 0
    for char in value:
        if char not in BASE58_ALPHABET:
            raise PR225ValidationError("pubkey contains invalid base58 char")
        number = number * 58 + BASE58_ALPHABET.index(char)
    raw = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    leading_zeroes = len(value) - len(value.lstrip("1"))
    return b"\x00" * leading_zeroes + raw


def require_solana_pubkey(value: str, field: str) -> None:
    try:
        decoded = _decode_base58(value)
    except PR225ValidationError as exc:
        raise PR225ValidationError(f"{field}: {exc}") from exc
    if len(decoded) != SOLANA_PUBKEY_BYTES:
        raise PR225ValidationError(f"{field} must decode to 32 bytes")


def validate_quote_request(request: QuoteRequest) -> None:
    if request.provider.strip() != request.provider or not request.provider:
        raise PR225ValidationError("provider must be canonical")
    require_solana_pubkey(request.input_mint, "input_mint")
    require_solana_pubkey(request.output_mint, "output_mint")
    if request.input_mint == request.output_mint:
        raise PR225ValidationError("input_mint and output_mint must differ")
    _require_u64(request.amount, "amount")
    if request.amount == 0:
        raise PR225ValidationError("amount must be positive")
    slippage = _require_non_bool_int(request.slippage_bps, "slippage_bps")
    if slippage < 0 or slippage > MAX_SLIPPAGE_BPS:
        raise PR225ValidationError("slippage_bps outside safety cap")
    _require_sha256(request.request_policy_sha256, "request_policy_sha256")


def validate_response_provenance(provenance: RawResponseProvenance) -> None:
    for field_name in (
        "credential_generation_sha256",
        "request_sha256",
        "raw_response_sha256",
        "header_digest_sha256",
        "schema_generation_sha256",
    ):
        _require_sha256(getattr(provenance, field_name), field_name)
    if not (200 <= provenance.status_code < 300):
        raise PR225ValidationError("provider response status must be successful")
    for field_name in ("received_at_unix_ns", "provider_timestamp_unix_ns"):
        if _require_non_bool_int(getattr(provenance, field_name), field_name) <= 0:
            raise PR225ValidationError(f"{field_name} must be positive")
    if _require_non_bool_int(provenance.context_slot, "context_slot") < 0:
        raise PR225ValidationError("context_slot must be non-negative")
    if set(provenance.parsed_keys).intersection(DANGEROUS_RESPONSE_KEYS):
        raise PR225ValidationError("dangerous provider response field present")


def validate_capabilities(capabilities: ProviderCapabilities) -> None:
    if not capabilities.exact_in_supported:
        raise PR225ValidationError("ExactIn provider capability is required")
    if not capabilities.guaranteed_minimum_output_supported:
        raise PR225ValidationError("guaranteed output capability is required")
    if not capabilities.explicit_expiry_supported:
        raise PR225ValidationError("explicit quote expiry is required")
    if not capabilities.executable_artifact_supported:
        raise PR225ValidationError("executable artifact capability is required")
    if capabilities.jito_submit_supported:
        raise PR225ValidationError("Jito submit is outside PR-225")


def validate_normalized_quote(quote: NormalizedQuote) -> str:
    validate_quote_request(quote.request)
    validate_response_provenance(quote.provenance)
    validate_capabilities(quote.capabilities)
    if quote.request.provider != quote.provenance.provider:
        raise PR225ValidationError("quote provider/provenance provider mismatch")
    if quote.request.provider != quote.capabilities.provider:
        raise PR225ValidationError("quote provider/capabilities mismatch")
    minimum = _require_u64(quote.minimum_output_amount, "minimum_output_amount")
    expected = _require_u64(quote.expected_output_amount, "expected_output_amount")
    if minimum == 0 or expected == 0 or minimum > expected:
        raise PR225ValidationError("guaranteed output must be positive and conservative")
    if quote.expires_at_unix_ns <= quote.provenance.received_at_unix_ns:
        raise PR225ValidationError("quote expiry must be after receive time")
    for field_name in (
        "executable_artifact_sha256",
        "route_plan_sha256",
        "fee_identity_sha256",
    ):
        _require_sha256(getattr(quote, field_name), field_name)
    return semantic_quote_identity(quote)


def semantic_quote_identity(quote: NormalizedQuote) -> str:
    payload = {
        "provider": quote.request.provider,
        "request": asdict(quote.request),
        "raw_response_sha256": quote.provenance.raw_response_sha256,
        "endpoint": quote.provenance.endpoint,
        "credential_generation_sha256": quote.provenance.credential_generation_sha256,
        "schema_generation_sha256": quote.provenance.schema_generation_sha256,
        "capabilities": asdict(quote.capabilities),
        "minimum_output_amount": quote.minimum_output_amount,
        "expires_at_unix_ns": quote.expires_at_unix_ns,
        "executable_artifact_sha256": quote.executable_artifact_sha256,
        "route_plan_sha256": quote.route_plan_sha256,
        "fee_identity_sha256": quote.fee_identity_sha256,
    }
    return _json_digest(payload)


def _validate_provider_registry(providers: Sequence[ProviderContract]) -> None:
    if not providers:
        raise PR225ValidationError("at least one provider contract is required")
    seen: set[str] = set()
    for provider in providers:
        if provider.provider in seen:
            raise PR225ValidationError("duplicate provider contract")
        seen.add(provider.provider)
        if provider.endpoint.startswith(("http://", "ws://")):
            raise PR225ValidationError("provider endpoints must be TLS protected")
        if not provider.allowed_methods:
            raise PR225ValidationError("provider must declare allowed methods")
        if provider.additive_unknown_fields_policy != "quarantine-dangerous":
            raise PR225ValidationError("dangerous unknown fields must quarantine")
        _require_sha256(
            provider.credential_generation_sha256,
            "credential_generation_sha256",
        )
        _require_sha256(provider.schema_generation_sha256, "schema_generation_sha256")


def _validate_transport(transport: TransportPolicyEvidence) -> None:
    if transport.owner != "owned-hardened-transport":
        raise PR225ValidationError("one owned hardened transport is required")
    if not transport.deny_by_default or not transport.allowed_hosts:
        raise PR225ValidationError("transport host policy must deny by default")
    if transport.injected_client_can_bypass:
        raise PR225ValidationError("injected client bypass is forbidden")
    denied = set(transport.resolved_ip_classes_denied)
    if not {"private", "loopback", "link-local"}.issubset(denied):
        raise PR225ValidationError("DNS/IP policy must deny unsafe ranges")
    if transport.redirect_policy != "revalidate-each-hop":
        raise PR225ValidationError("redirects must be revalidated")
    if transport.total_deadline_ms <= 0:
        raise PR225ValidationError("total deadline must be positive")
    if not (0 < transport.max_response_bytes <= MAX_RESPONSE_BYTES):
        raise PR225ValidationError("response byte budget is invalid")
    if not transport.strict_json_duplicate_keys_rejected:
        raise PR225ValidationError("strict JSON duplicate-key rejection required")
    for field_name in (
        "tls_peer_fingerprint_sha256",
        "ca_bundle_sha256",
        "redaction_policy_sha256",
    ):
        _require_sha256(getattr(transport, field_name), field_name)


def _validate_retry(policy: RetryPolicyEvidence) -> None:
    if policy.retries_non_idempotent_post and not policy.provider_idempotency_contract_sha256:
        raise PR225ValidationError("non-idempotent POST retry lacks contract")
    if policy.provider_idempotency_contract_sha256:
        _require_sha256(
            policy.provider_idempotency_contract_sha256,
            "provider_idempotency_contract_sha256",
        )
    if not policy.retry_after_http_date_supported:
        raise PR225ValidationError("Retry-After HTTP-date parsing required")
    if not policy.jitter_enabled:
        raise PR225ValidationError("retry jitter required")
    if not policy.total_deadline_covers_retries:
        raise PR225ValidationError("one total deadline must cover retries")
    if not policy.cancellation_cleanup_proven:
        raise PR225ValidationError("cancellation cleanup proof required")


def _validate_quota(quota: QuotaAuthorityEvidence) -> None:
    if quota.authority != "durable-account-wide-quota":
        raise PR225ValidationError("durable account-wide quota authority required")
    required_flags = (
        quota.durable,
        quota.account_wide,
        quota.serialized_cross_process,
        quota.unknown_purpose_fails_closed,
        quota.unknown_token_fails_closed,
        quota.exact_once_mark_used,
    )
    if not all(required_flags):
        raise PR225ValidationError("quota authority is not fail-closed/durable")
    for field_name in (
        "credential_generation_sha256",
        "endpoint_generation_sha256",
        "account_plan_sha256",
        "two_process_race_proof_sha256",
        "persisted_cooldown_proof_sha256",
    ):
        _require_sha256(getattr(quota, field_name), field_name)


def _validate_installed_cycle(cycle: InstalledProviderCycleEvidence) -> None:
    for field_name in ("installed_wheel_sha256", "command_surface_sha256"):
        _require_sha256(getattr(cycle, field_name), field_name)
    if not cycle.provider_cycle_non_empty:
        raise PR225ValidationError("installed provider cycle must be non-empty")
    if not cycle.missing_transport_blocks_startup:
        raise PR225ValidationError("missing transport cannot be successful idle")
    if not cycle.sender_free:
        raise PR225ValidationError("installed provider cycle must be sender-free")
    if cycle.live_enabled or cycle.sender_loaded or cycle.signer_loaded:
        raise PR225ValidationError("forbidden runtime capability is enabled")


def _validate_findings(bundle: PR225EvidenceBundle) -> None:
    if tuple(sorted(bundle.covered_findings)) != tuple(sorted(REQUIRED_FINDINGS)):
        raise PR225ValidationError("PR-225 finding coverage mismatch")


def _validate_discovery(
    candidates: Sequence[DiscoveryCandidate],
    identities: set[str],
    selected_identity: str,
) -> None:
    if not candidates:
        raise PR225ValidationError("discovery requires at least one candidate")
    for candidate in candidates:
        _require_sha256(candidate.quote_identity_sha256, "quote_identity_sha256")
        _require_sha256(
            candidate.executable_artifact_sha256,
            "candidate.executable_artifact_sha256",
        )
        if candidate.quote_identity_sha256 not in identities:
            raise PR225ValidationError("candidate quote identity is unknown")
        if candidate.guaranteed_profit_base_units < 0:
            raise PR225ValidationError("candidate profit must use guaranteed output")
        if candidate.risk_bps < 0:
            raise PR225ValidationError("candidate risk must be non-negative")
    ordered = sorted(
        candidates,
        key=lambda item: (
            -item.guaranteed_profit_base_units,
            item.risk_bps,
            item.quote_identity_sha256,
        ),
    )
    if tuple(candidates) != tuple(ordered):
        raise PR225ValidationError("discovery order must be deterministic value/risk")
    if ordered[0].quote_identity_sha256 != selected_identity:
        raise PR225ValidationError("selected candidate must be best value/risk item")


def _capability_violations(bundle: PR225EvidenceBundle) -> list[PR225Violation]:
    violations: list[PR225Violation] = []
    for key in FORBIDDEN_CAPABILITIES:
        if bundle.runtime_capabilities.get(key) is True:
            violations.append(
                PR225Violation(
                    PR225FailureCode.FORBIDDEN_RUNTIME_CAPABILITY,
                    f"forbidden runtime capability {key} is true",
                )
            )
    return violations


def _evidence_digest(bundle: PR225EvidenceBundle) -> str:
    return _json_digest(asdict(bundle))


def evaluate_pr225_evidence(bundle: PR225EvidenceBundle) -> PR225Report:
    violations: list[PR225Violation] = []
    if bundle.schema_version != SCHEMA_VERSION:
        violations.append(
            PR225Violation(
                PR225FailureCode.INVALID_PROVIDER_REGISTRY,
                "schema version mismatch",
            )
        )
    checks: tuple[tuple[PR225FailureCode, Any], ...] = (
        (PR225FailureCode.INVALID_PROVIDER_REGISTRY, lambda: _validate_findings(bundle)),
        (
            PR225FailureCode.MISSING_INSTALLED_CYCLE,
            lambda: _validate_installed_cycle(bundle.installed_cycle),
        ),
        (
            PR225FailureCode.INVALID_PROVIDER_REGISTRY,
            lambda: _validate_provider_registry(bundle.providers),
        ),
        (PR225FailureCode.UNSAFE_TRANSPORT, lambda: _validate_transport(bundle.transport)),
        (PR225FailureCode.UNSAFE_RETRY_POLICY, lambda: _validate_retry(bundle.retry_policy)),
        (PR225FailureCode.NON_DURABLE_QUOTA, lambda: _validate_quota(bundle.quota)),
    )
    for code, check in checks:
        try:
            check()
        except PR225ValidationError as exc:
            violations.append(PR225Violation(code, str(exc)))

    identities: set[str] = set()
    for quote in bundle.quotes:
        try:
            identities.add(validate_normalized_quote(quote))
        except PR225ValidationError as exc:
            violations.append(
                PR225Violation(PR225FailureCode.INVALID_QUOTE_DOMAIN, str(exc))
            )

    try:
        _validate_discovery(
            bundle.discovery_candidates,
            identities,
            bundle.selected_quote_identity_sha256,
        )
    except PR225ValidationError as exc:
        violations.append(
            PR225Violation(PR225FailureCode.INVALID_DISCOVERY_SELECTION, str(exc))
        )
    violations.extend(_capability_violations(bundle))
    ok = not violations
    return PR225Report(
        ok=ok,
        status="ready-for-secure-provider-plane-review" if ok else "blocked",
        schema_version=SCHEMA_VERSION,
        evidence_digest_sha256=_evidence_digest(bundle),
        violations=tuple(violations),
        provider_plane_review_allowed=ok,
    )
