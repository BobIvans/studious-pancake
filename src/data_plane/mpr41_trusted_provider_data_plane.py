"""MPR-41 trusted provider, webhook and protocol-conformance data plane.

This module is intentionally default-off.  It defines the evidence contract and
static bypass scanner that later MPR-41 implementation PRs can bind to the real
installed runtime.  It does not open live trading, sender imports, signer access,
Jito settlement authority, or production promotion.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import hashlib
import json
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

MPR41_ID = "MPR-41"
MPR41_SCHEMA_VERSION = "mpr41.trusted-provider-data-plane.v1"
MPR41_EVIDENCE_KIND = "trusted-provider-data-plane"
MAX_PROVIDER_RESPONSE_BYTES = 1_048_576
MAX_PROVIDER_TIMEOUT_MS = 10_000

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NETWORK_BYPASS_RULES = (
    ("MPR41_DIRECT_AIOHTTP_CLIENT", re.compile(r"\baiohttp\.ClientSession\s*\(")),
    ("MPR41_DIRECT_HTTPX_CLIENT", re.compile(r"\bhttpx\.(?:AsyncClient|Client)\s*\(")),
    ("MPR41_DIRECT_REQUESTS_CALL", re.compile(r"\brequests\.(?:get|post|put|patch|delete|request)\s*\(")),
    ("MPR41_DIRECT_URLLIB_CALL", re.compile(r"\burllib\.request\.urlopen\s*\(")),
    ("MPR41_DIRECT_SOCKET_CONNECT", re.compile(r"\bsocket\.(?:create_connection|socket)\s*\(")),
    ("MPR41_AMBIENT_PROXY_TRUST", re.compile(r"\btrust_env\s*=\s*True\b")),
)
_DEFAULT_ALLOWED_PATH_MARKERS = (
    "mpr41_trusted_provider_data_plane.py",
    "trusted_transport",
    "provider_gateway",
    "tests/fixtures/",
)


@dataclass(frozen=True, slots=True)
class MPR41Violation:
    code: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TransportPolicyEvidence:
    authority: str
    deny_by_default: bool
    tls_required: bool
    ambient_proxy_trust: bool
    strict_json_duplicate_keys_rejected: bool
    durable_quota: bool
    retry_budget_persisted: bool
    max_response_bytes: int
    total_timeout_ms: int
    allowed_hosts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProviderResponseEvidence:
    provider: str
    endpoint: str
    credential_generation_sha256: str
    request_sha256: str
    response_sha256: str
    tls_peer_fingerprint_sha256: str
    received_at_unix_ns: int
    context_slot: int
    response_size_bytes: int
    provenance_persisted: bool


@dataclass(frozen=True, slots=True)
class WebhookIntakeEvidence:
    ack_after_durable_commit: bool
    durable_inbox_commit_sha256: str
    dedupe_key_sha256: str
    batch_atomic: bool
    durable_nack_or_dead_letter: bool
    trusted_forwarded_headers_only: bool
    timestamp_units_validated: bool
    routing_identity_authenticated: bool
    rate_limit_state_bounded: bool


@dataclass(frozen=True, slots=True)
class RuntimeSurfaceEvidence:
    source_only: bool
    live_enabled: bool
    signer_loaded: bool
    sender_loaded: bool
    jito_settlement_authority: bool


@dataclass(frozen=True, slots=True)
class MPR41EvidenceBundle:
    schema_version: str
    transport: TransportPolicyEvidence
    providers: tuple[ProviderResponseEvidence, ...]
    webhook: WebhookIntakeEvidence
    runtime_surface: RuntimeSurfaceEvidence
    issued_at_ns: int
    evidence_sha256: str


@dataclass(frozen=True, slots=True)
class NetworkBypassFinding:
    path: str
    rule: str
    line: int
    snippet: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MPR41Decision:
    schema_version: str
    accepted: bool
    evidence_kind: str
    reason_codes: tuple[str, ...]
    violations: tuple[MPR41Violation, ...]
    bundle_digest: str
    provider_network_allowed: bool
    webhook_ack_authorized: bool
    live_enabled: bool
    signer_loaded: bool
    sender_loaded: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "accepted": self.accepted,
            "evidence_kind": self.evidence_kind,
            "reason_codes": list(self.reason_codes),
            "violations": [item.to_dict() for item in self.violations],
            "bundle_digest": self.bundle_digest,
            "provider_network_allowed": self.provider_network_allowed,
            "webhook_ack_authorized": self.webhook_ack_authorized,
            "live_enabled": self.live_enabled,
            "signer_loaded": self.signer_loaded,
            "sender_loaded": self.sender_loaded,
            "production_ready": False,
            "paper_ready": False,
            "live_ready": False,
        }


def evaluate_mpr41_evidence(bundle: MPR41EvidenceBundle) -> MPR41Decision:
    """Evaluate trusted-data-plane evidence as a default-off release gate."""

    violations: list[MPR41Violation] = []
    reasons: list[str] = []

    if bundle.schema_version != MPR41_SCHEMA_VERSION:
        violations.append(_violation("MPR41_SCHEMA_VERSION", "unexpected schema version"))

    _validate_digest(bundle.evidence_sha256, "evidence_sha256", violations)
    _validate_ns(bundle.issued_at_ns, "issued_at_ns", violations)
    _validate_transport(bundle.transport, violations)
    _validate_providers(bundle.providers, bundle.transport, violations)
    _validate_webhook(bundle.webhook, violations)
    _validate_runtime_surface(bundle.runtime_surface, violations)

    if violations:
        reasons.extend(sorted({item.code for item in violations}))
    else:
        reasons.append("MPR41_TRUSTED_DATA_PLANE_ACCEPTED_DEFAULT_OFF")

    digest = _hash_json(_bundle_public_payload(bundle) | {"violations": [v.to_dict() for v in violations]})
    accepted = not violations
    return MPR41Decision(
        schema_version=MPR41_SCHEMA_VERSION,
        accepted=accepted,
        evidence_kind=MPR41_EVIDENCE_KIND,
        reason_codes=tuple(reasons),
        violations=tuple(violations),
        bundle_digest=digest,
        provider_network_allowed=accepted,
        webhook_ack_authorized=accepted,
        live_enabled=bundle.runtime_surface.live_enabled,
        signer_loaded=bundle.runtime_surface.signer_loaded,
        sender_loaded=bundle.runtime_surface.sender_loaded,
    )


def bundle_from_mapping(payload: Mapping[str, Any]) -> MPR41EvidenceBundle:
    """Decode JSON-like evidence into strict dataclasses."""

    return MPR41EvidenceBundle(
        schema_version=_text(payload, "schema_version"),
        transport=TransportPolicyEvidence(
            authority=_text(_mapping(payload, "transport"), "authority"),
            deny_by_default=_bool(_mapping(payload, "transport"), "deny_by_default"),
            tls_required=_bool(_mapping(payload, "transport"), "tls_required"),
            ambient_proxy_trust=_bool(_mapping(payload, "transport"), "ambient_proxy_trust"),
            strict_json_duplicate_keys_rejected=_bool(_mapping(payload, "transport"), "strict_json_duplicate_keys_rejected"),
            durable_quota=_bool(_mapping(payload, "transport"), "durable_quota"),
            retry_budget_persisted=_bool(_mapping(payload, "transport"), "retry_budget_persisted"),
            max_response_bytes=_int(_mapping(payload, "transport"), "max_response_bytes"),
            total_timeout_ms=_int(_mapping(payload, "transport"), "total_timeout_ms"),
            allowed_hosts=tuple(_strings(_mapping(payload, "transport"), "allowed_hosts")),
        ),
        providers=tuple(
            ProviderResponseEvidence(
                provider=_text(row, "provider"),
                endpoint=_text(row, "endpoint"),
                credential_generation_sha256=_text(row, "credential_generation_sha256"),
                request_sha256=_text(row, "request_sha256"),
                response_sha256=_text(row, "response_sha256"),
                tls_peer_fingerprint_sha256=_text(row, "tls_peer_fingerprint_sha256"),
                received_at_unix_ns=_int(row, "received_at_unix_ns"),
                context_slot=_int(row, "context_slot"),
                response_size_bytes=_int(row, "response_size_bytes"),
                provenance_persisted=_bool(row, "provenance_persisted"),
            )
            for row in _sequence(payload, "providers")
        ),
        webhook=WebhookIntakeEvidence(
            ack_after_durable_commit=_bool(_mapping(payload, "webhook"), "ack_after_durable_commit"),
            durable_inbox_commit_sha256=_text(_mapping(payload, "webhook"), "durable_inbox_commit_sha256"),
            dedupe_key_sha256=_text(_mapping(payload, "webhook"), "dedupe_key_sha256"),
            batch_atomic=_bool(_mapping(payload, "webhook"), "batch_atomic"),
            durable_nack_or_dead_letter=_bool(_mapping(payload, "webhook"), "durable_nack_or_dead_letter"),
            trusted_forwarded_headers_only=_bool(_mapping(payload, "webhook"), "trusted_forwarded_headers_only"),
            timestamp_units_validated=_bool(_mapping(payload, "webhook"), "timestamp_units_validated"),
            routing_identity_authenticated=_bool(_mapping(payload, "webhook"), "routing_identity_authenticated"),
            rate_limit_state_bounded=_bool(_mapping(payload, "webhook"), "rate_limit_state_bounded"),
        ),
        runtime_surface=RuntimeSurfaceEvidence(
            source_only=_bool(_mapping(payload, "runtime_surface"), "source_only"),
            live_enabled=_bool(_mapping(payload, "runtime_surface"), "live_enabled"),
            signer_loaded=_bool(_mapping(payload, "runtime_surface"), "signer_loaded"),
            sender_loaded=_bool(_mapping(payload, "runtime_surface"), "sender_loaded"),
            jito_settlement_authority=_bool(_mapping(payload, "runtime_surface"), "jito_settlement_authority"),
        ),
        issued_at_ns=_int(payload, "issued_at_ns"),
        evidence_sha256=_text(payload, "evidence_sha256"),
    )


def scan_text_for_network_bypasses(
    path: str,
    content: str,
    *,
    allowed_path_markers: Iterable[str] = _DEFAULT_ALLOWED_PATH_MARKERS,
) -> tuple[NetworkBypassFinding, ...]:
    """Find direct network client construction outside reviewed gateway paths."""

    normalized = path.replace("\\", "/")
    if any(marker in normalized for marker in allowed_path_markers):
        return ()
    findings: list[NetworkBypassFinding] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        for rule, pattern in _NETWORK_BYPASS_RULES:
            if pattern.search(line):
                findings.append(
                    NetworkBypassFinding(
                        path=normalized,
                        rule=rule,
                        line=line_number,
                        snippet=line.strip()[:160],
                    )
                )
    return tuple(findings)


def scan_paths_for_network_bypasses(paths: Iterable[str | Path]) -> tuple[NetworkBypassFinding, ...]:
    findings: list[NetworkBypassFinding] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_dir():
            candidates = sorted(path.rglob("*.py"))
        elif path.suffix == ".py" and path.is_file():
            candidates = [path]
        else:
            candidates = []
        for candidate in candidates:
            try:
                content = candidate.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            findings.extend(scan_text_for_network_bypasses(str(candidate), content))
    return tuple(findings)


def static_contract() -> dict[str, Any]:
    return {
        "schema_version": MPR41_SCHEMA_VERSION,
        "mpr_id": MPR41_ID,
        "evidence_kind": MPR41_EVIDENCE_KIND,
        "default_off": True,
        "requires_one_transport_authority": True,
        "requires_durable_webhook_ack": True,
        "requires_provider_provenance": True,
        "requires_ambient_proxy_disabled": True,
        "requires_strict_json_decoding": True,
        "requires_durable_quota_and_retry_state": True,
        "forbidden_runtime_claims": [
            "source_only",
            "live_enabled",
            "signer_loaded",
            "sender_loaded",
            "jito_settlement_authority",
        ],
        "network_bypass_rules": [rule for rule, _ in _NETWORK_BYPASS_RULES],
        "production_ready": False,
    }


def _validate_transport(policy: TransportPolicyEvidence, violations: list[MPR41Violation]) -> None:
    if not policy.authority.strip():
        violations.append(_violation("MPR41_TRANSPORT_AUTHORITY_REQUIRED", "authority is empty"))
    _must_be(policy.deny_by_default, True, "MPR41_TRANSPORT_MUST_DENY_BY_DEFAULT", violations)
    _must_be(policy.tls_required, True, "MPR41_TLS_REQUIRED", violations)
    _must_be(policy.ambient_proxy_trust, False, "MPR41_AMBIENT_PROXY_FORBIDDEN", violations)
    _must_be(policy.strict_json_duplicate_keys_rejected, True, "MPR41_STRICT_JSON_REQUIRED", violations)
    _must_be(policy.durable_quota, True, "MPR41_DURABLE_QUOTA_REQUIRED", violations)
    _must_be(policy.retry_budget_persisted, True, "MPR41_DURABLE_RETRY_REQUIRED", violations)
    if policy.max_response_bytes <= 0 or policy.max_response_bytes > MAX_PROVIDER_RESPONSE_BYTES:
        violations.append(_violation("MPR41_RESPONSE_SIZE_LIMIT", "max_response_bytes out of bounds"))
    if policy.total_timeout_ms <= 0 or policy.total_timeout_ms > MAX_PROVIDER_TIMEOUT_MS:
        violations.append(_violation("MPR41_TIMEOUT_BUDGET", "total_timeout_ms out of bounds"))
    if not policy.allowed_hosts:
        violations.append(_violation("MPR41_ALLOWED_HOSTS_REQUIRED", "allowed_hosts is empty"))


def _validate_providers(
    providers: tuple[ProviderResponseEvidence, ...],
    policy: TransportPolicyEvidence,
    violations: list[MPR41Violation],
) -> None:
    if not providers:
        violations.append(_violation("MPR41_PROVIDER_EVIDENCE_REQUIRED", "no provider evidence"))
        return
    allowed_hosts = set(policy.allowed_hosts)
    for provider in providers:
        endpoint = urlparse(provider.endpoint)
        if endpoint.scheme != "https":
            violations.append(_violation("MPR41_PROVIDER_ENDPOINT_HTTPS", f"{provider.provider} endpoint must be https"))
        if endpoint.hostname not in allowed_hosts:
            violations.append(_violation("MPR41_PROVIDER_HOST_NOT_ALLOWED", f"{endpoint.hostname} not in allowed hosts"))
        for key in (
            "credential_generation_sha256",
            "request_sha256",
            "response_sha256",
            "tls_peer_fingerprint_sha256",
        ):
            _validate_digest(getattr(provider, key), key, violations)
        _validate_ns(provider.received_at_unix_ns, "received_at_unix_ns", violations)
        if provider.context_slot < 0:
            violations.append(_violation("MPR41_CONTEXT_SLOT_INVALID", "context_slot must be non-negative"))
        if provider.response_size_bytes <= 0 or provider.response_size_bytes > policy.max_response_bytes:
            violations.append(_violation("MPR41_PROVIDER_RESPONSE_SIZE", "response size out of bounds"))
        _must_be(provider.provenance_persisted, True, "MPR41_PROVIDER_PROVENANCE_REQUIRED", violations)


def _validate_webhook(webhook: WebhookIntakeEvidence, violations: list[MPR41Violation]) -> None:
    for key in ("durable_inbox_commit_sha256", "dedupe_key_sha256"):
        _validate_digest(getattr(webhook, key), key, violations)
    _must_be(webhook.ack_after_durable_commit, True, "MPR41_WEBHOOK_ACK_BEFORE_DURABILITY", violations)
    _must_be(webhook.batch_atomic, True, "MPR41_WEBHOOK_BATCH_NOT_ATOMIC", violations)
    _must_be(webhook.durable_nack_or_dead_letter, True, "MPR41_WEBHOOK_NACK_REQUIRED", violations)
    _must_be(webhook.trusted_forwarded_headers_only, True, "MPR41_FORWARDED_HEADERS_UNTRUSTED", violations)
    _must_be(webhook.timestamp_units_validated, True, "MPR41_WEBHOOK_TIMESTAMP_VALIDATION_REQUIRED", violations)
    _must_be(webhook.routing_identity_authenticated, True, "MPR41_WEBHOOK_ROUTING_AUTH_REQUIRED", violations)
    _must_be(webhook.rate_limit_state_bounded, True, "MPR41_WEBHOOK_RATE_LIMIT_UNBOUNDED", violations)


def _validate_runtime_surface(surface: RuntimeSurfaceEvidence, violations: list[MPR41Violation]) -> None:
    _must_be(surface.source_only, False, "MPR41_SOURCE_ONLY_SURFACE_FORBIDDEN", violations)
    _must_be(surface.live_enabled, False, "MPR41_LIVE_FORBIDDEN", violations)
    _must_be(surface.signer_loaded, False, "MPR41_SIGNER_FORBIDDEN", violations)
    _must_be(surface.sender_loaded, False, "MPR41_SENDER_FORBIDDEN", violations)
    _must_be(surface.jito_settlement_authority, False, "MPR41_JITO_SETTLEMENT_FORBIDDEN", violations)


def _bundle_public_payload(bundle: MPR41EvidenceBundle) -> dict[str, Any]:
    return {
        "schema_version": bundle.schema_version,
        "transport": asdict(bundle.transport),
        "providers": [asdict(provider) for provider in bundle.providers],
        "webhook": asdict(bundle.webhook),
        "runtime_surface": asdict(bundle.runtime_surface),
        "issued_at_ns": bundle.issued_at_ns,
        "evidence_sha256": bundle.evidence_sha256,
    }


def _validate_digest(value: Any, key: str, violations: list[MPR41Violation]) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        violations.append(_violation("MPR41_INVALID_DIGEST", f"{key} must be lowercase sha256"))


def _validate_ns(value: Any, key: str, violations: list[MPR41Violation]) -> None:
    if type(value) is not int or value < 0:
        violations.append(_violation("MPR41_INVALID_TIME", f"{key} must be non-negative int ns"))


def _must_be(value: bool, expected: bool, code: str, violations: list[MPR41Violation]) -> None:
    if value is not expected:
        violations.append(_violation(code, f"expected {expected}, got {value}"))


def _violation(code: str, detail: str) -> MPR41Violation:
    return MPR41Violation(code=code, detail=detail)


def _mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be an object")
    return value


def _sequence(payload: Mapping[str, Any], key: str) -> tuple[Mapping[str, Any], ...]:
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"{key} must contain objects")
    return tuple(value)


def _strings(payload: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{key} must contain non-empty strings")
    return tuple(value)


def _text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be non-empty text")
    return value.strip()


def _bool(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if type(value) is not bool:
        raise ValueError(f"{key} must be bool")
    return value


def _int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if type(value) is not int:
        raise ValueError(f"{key} must be int")
    return value


def _hash_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


__all__ = [
    "MPR41_EVIDENCE_KIND",
    "MPR41_ID",
    "MPR41_SCHEMA_VERSION",
    "MPR41Decision",
    "MPR41EvidenceBundle",
    "NetworkBypassFinding",
    "ProviderResponseEvidence",
    "RuntimeSurfaceEvidence",
    "TransportPolicyEvidence",
    "WebhookIntakeEvidence",
    "bundle_from_mapping",
    "evaluate_mpr41_evidence",
    "scan_paths_for_network_bypasses",
    "scan_text_for_network_bypasses",
    "static_contract",
]
