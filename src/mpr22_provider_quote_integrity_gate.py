from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Mapping, Sequence

SCHEMA_VERSION = "mpr22.provider-routing-quote-integrity-gate.v1"
PRODUCT_ID = "studious-pancake.mpr22.provider-routing-quote-integrity-gate"

_REQUIRED_FINDINGS: tuple[str, ...] = (
    "F-304", "F-305", "F-306", "F-307", "F-308",
    "F-309", "F-310", "F-311", "F-312", "F-313",
    "F-420", "F-421", "F-422", "F-423", "F-424",
    "F-425", "F-426", "F-427", "F-428", "F-429",
)
_ALLOWED_PROVIDERS: tuple[str, ...] = ("jupiter", "rpc", "helius")
_PUBKEY_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class MPR22GateState(StrEnum):
    READY_FOR_PROVIDER_REVIEW = "ready-for-provider-review"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class TransportEvidence:
    provider: str
    request_hash: str
    endpoint_identity: str
    cluster_genesis_hash: str
    absolute_deadline_ms: int
    total_elapsed_ms: int
    bounded_response_bytes: bool
    hardened_json_parser: bool
    dns_rebinding_protected: bool
    tls_peer_pinned: bool
    private_ip_denied: bool
    redirect_revalidated: bool
    request_bound_provenance: bool

    def __post_init__(self) -> None:
        if self.provider not in _ALLOWED_PROVIDERS:
            raise ValueError("provider must be an admitted provider id")
        _sha256(self.request_hash, "request_hash")
        _identifier(self.endpoint_identity, "endpoint_identity")
        _sha256(self.cluster_genesis_hash, "cluster_genesis_hash")
        if self.absolute_deadline_ms <= 0:
            raise ValueError("absolute_deadline_ms must be positive")
        if self.total_elapsed_ms < 0:
            raise ValueError("total_elapsed_ms must be non-negative")


@dataclass(frozen=True, slots=True)
class QuoteEvidence:
    provider: str
    request_hash: str
    quote_hash: str
    quote_expires_at_ms: int
    observed_at_ms: int
    provider_generation: int
    swap_mode: str
    slippage_bps: int
    input_mint: str
    output_mint: str
    amount_in: int
    route_identity: str
    provenance_bound: bool
    request_policy_preserved: bool

    def __post_init__(self) -> None:
        if self.provider not in _ALLOWED_PROVIDERS:
            raise ValueError("provider must be an admitted provider id")
        _sha256(self.request_hash, "request_hash")
        _sha256(self.quote_hash, "quote_hash")
        if self.quote_expires_at_ms <= 0 or self.observed_at_ms <= 0:
            raise ValueError("timestamps must be positive")
        if self.provider_generation <= 0:
            raise ValueError("provider_generation must be positive")
        if self.swap_mode not in {"ExactIn", "ExactOut"}:
            raise ValueError("swap_mode must be ExactIn or ExactOut")
        if not 0 <= self.slippage_bps <= 5000:
            raise ValueError("slippage_bps out of range")
        _pubkey(self.input_mint, "input_mint")
        _pubkey(self.output_mint, "output_mint")
        if self.input_mint == self.output_mint:
            raise ValueError("input_mint and output_mint must differ")
        if self.amount_in <= 0:
            raise ValueError("amount_in must be positive")
        _identifier(self.route_identity, "route_identity")


@dataclass(frozen=True, slots=True)
class QuotaAuthorityEvidence:
    authority_generation: int
    reservation_id: str
    reservation_bound_to_request: bool
    cross_process_serialized: bool
    monotonic_time_authority: bool
    exactly_once_mark_used: bool
    bounded_history: bool

    def __post_init__(self) -> None:
        if self.authority_generation <= 0:
            raise ValueError("authority_generation must be positive")
        _identifier(self.reservation_id, "reservation_id")


@dataclass(frozen=True, slots=True)
class FindingClosure:
    finding_id: str
    closed: bool

    def __post_init__(self) -> None:
        if self.finding_id not in _REQUIRED_FINDINGS:
            raise ValueError("unexpected finding id")


@dataclass(frozen=True, slots=True)
class GateViolation:
    code: str
    subject: str
    detail: str

    def __post_init__(self) -> None:
        _identifier(self.code, "violation.code")
        if not self.subject or not self.detail:
            raise ValueError("violation subject/detail must not be empty")

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class MPR22GateReport:
    schema_version: str
    product_id: str
    state: MPR22GateState
    evidence_hash: str
    violations: tuple[GateViolation, ...]
    live_execution_allowed: bool = False
    signer_allowed: bool = False
    sender_allowed: bool = False

    @property
    def ready(self) -> bool:
        return self.state is MPR22GateState.READY_FOR_PROVIDER_REVIEW

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "product_id": self.product_id,
            "state": self.state.value,
            "ready": self.ready,
            "evidence_hash": self.evidence_hash,
            "violation_count": len(self.violations),
            "violations": [v.to_dict() for v in self.violations],
            "safety_boundary": {
                "live_execution_allowed": self.live_execution_allowed,
                "signer_allowed": self.signer_allowed,
                "sender_allowed": self.sender_allowed,
            },
        }


def evaluate_mpr22_provider_gate(
    *,
    transport: TransportEvidence,
    quote: QuoteEvidence,
    quota: QuotaAuthorityEvidence,
    findings: Sequence[FindingClosure],
) -> MPR22GateReport:
    violations: list[GateViolation] = []

    closure_map = {item.finding_id: item.closed for item in findings}
    for finding_id in _REQUIRED_FINDINGS:
        if closure_map.get(finding_id) is not True:
            violations.append(
                GateViolation(
                    code="missing_required_finding_closure",
                    subject=finding_id,
                    detail="required MPR-22 finding closure is absent or open",
                )
            )

    if transport.request_hash != quote.request_hash:
        violations.append(
            GateViolation(
                code="request_hash_mismatch",
                subject="transport/quote",
                detail="transport and quote must bind to the exact same request hash",
            )
        )

    if transport.total_elapsed_ms > transport.absolute_deadline_ms:
        violations.append(
            GateViolation(
                code="absolute_deadline_exceeded",
                subject=str(transport.total_elapsed_ms),
                detail="provider operation exceeded the absolute end-to-end budget",
            )
        )

    _require_bool_flag(transport.bounded_response_bytes, "bounded_response_bytes", violations)
    _require_bool_flag(transport.hardened_json_parser, "hardened_json_parser", violations)
    _require_bool_flag(transport.dns_rebinding_protected, "dns_rebinding_protected", violations)
    _require_bool_flag(transport.tls_peer_pinned, "tls_peer_pinned", violations)
    _require_bool_flag(transport.private_ip_denied, "private_ip_denied", violations)
    _require_bool_flag(transport.redirect_revalidated, "redirect_revalidated", violations)
    _require_bool_flag(transport.request_bound_provenance, "request_bound_provenance", violations)

    if quote.quote_expires_at_ms <= quote.observed_at_ms:
        violations.append(
            GateViolation(
                code="quote_not_fresh",
                subject=quote.route_identity,
                detail="quote expiry must be strictly after observed_at",
            )
        )

    _require_quote_flag(quote.provenance_bound, "quote_provenance_bound", violations)
    _require_quote_flag(quote.request_policy_preserved, "request_policy_preserved", violations)

    _require_quota_flag(quota.reservation_bound_to_request, "reservation_bound_to_request", violations)
    _require_quota_flag(quota.cross_process_serialized, "cross_process_serialized", violations)
    _require_quota_flag(quota.monotonic_time_authority, "monotonic_time_authority", violations)
    _require_quota_flag(quota.exactly_once_mark_used, "exactly_once_mark_used", violations)
    _require_quota_flag(quota.bounded_history, "bounded_history", violations)

    report = MPR22GateReport(
        schema_version=SCHEMA_VERSION,
        product_id=PRODUCT_ID,
        state=MPR22GateState.BLOCKED if violations else MPR22GateState.READY_FOR_PROVIDER_REVIEW,
        evidence_hash=_evidence_hash(transport, quote, quota, findings),
        violations=tuple(sorted(violations, key=lambda v: (v.code, v.subject, v.detail))),
    )
    return report


def _require_bool_flag(ok: bool, subject: str, violations: list[GateViolation]) -> None:
    if not ok:
        violations.append(
            GateViolation(
                code="transport_guard_missing",
                subject=subject,
                detail="required transport guard is not proven",
            )
        )


def _require_quote_flag(ok: bool, subject: str, violations: list[GateViolation]) -> None:
    if not ok:
        violations.append(
            GateViolation(
                code="quote_integrity_missing",
                subject=subject,
                detail="required quote integrity proof is missing",
            )
        )


def _require_quota_flag(ok: bool, subject: str, violations: list[GateViolation]) -> None:
    if not ok:
        violations.append(
            GateViolation(
                code="quota_authority_missing",
                subject=subject,
                detail="required quota/circuit authority proof is missing",
            )
        )


def _sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")
    return value


def _identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a stable identifier")
    return value


def _pubkey(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _PUBKEY_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a canonical base58 pubkey")
    return value


def _evidence_hash(
    transport: TransportEvidence,
    quote: QuoteEvidence,
    quota: QuotaAuthorityEvidence,
    findings: Sequence[FindingClosure],
) -> str:
    payload = {
        "domain": "studious-pancake/mpr22/provider-integrity-gate",
        "transport": asdict(transport),
        "quote": asdict(quote),
        "quota": asdict(quota),
        "findings": sorted(
            ({"finding_id": f.finding_id, "closed": f.closed} for f in findings),
            key=lambda item: item["finding_id"],
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
