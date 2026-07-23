"""MPR-11 routing, quota, freshness and transport conformance gate.

This module is intentionally sender-free. It validates already-materialized
Evidence for the V6 MPR-11 boundary without opening sockets, constructing
transactions, calling providers, signing messages, or enabling live execution.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Any

MPR11_SCHEMA_VERSION = "mpr11.routing-quota-transport-gate.v1"
MPR11_FINDINGS = tuple(f"F-{number}" for number in range(304, 314))


@dataclass(frozen=True, slots=True)
class MPR11GateReport:
    """Deterministic report for MPR-11 conformance evidence."""

    schema_version: str
    accepted: bool
    blockers: tuple[str, ...]
    evidence_hash: str
    covered_findings: tuple[str, ...]
    live_execution_allowed: bool
    provider_network_allowed: bool
    signer_allowed: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_mpr11_routing_quota_gate(evidence: Mapping[str, Any]) -> MPR11GateReport:
    """Validate MPR-11 evidence and return a fail-closed report."""

    blockers: list[str] = []
    _require(
        evidence.get("schema_version") == MPR11_SCHEMA_VERSION,
        blockers,
        "SCHEMA_VERSION_INVALID",
    )

    covered_findings = _string_tuple(evidence.get("covered_findings"))
    missing = sorted(set(MPR11_FINDINGS) - set(covered_findings))
    _require(not missing, blockers, "FINDING_COVERAGE_INCOMPLETE")

    _check_cache(evidence.get("cache_identity"), blockers)
    _check_quota(evidence.get("quota"), blockers)
    _check_scheduler(evidence.get("scheduler"), blockers)
    _check_public_keys(evidence.get("public_keys"), blockers)
    _check_quote_freshness(evidence.get("quote_freshness"), blockers)
    _check_transport(evidence.get("transport"), blockers)
    _check_adapters(evidence.get("adapters"), blockers)
    _check_route_identity(evidence.get("route_identity"), blockers)

    _require(
        not bool(evidence.get("live_execution_enabled")),
        blockers,
        "LIVE_EXECUTION_FORBIDDEN",
    )
    _require(
        not bool(evidence.get("provider_network_enabled")),
        blockers,
        "PROVIDER_NETWORK_FORBIDDEN",
    )
    _require(not bool(evidence.get("signer_enabled")), blockers, "SIGNER_FORBIDDEN")

    evidence_hash = _hash_json(_redacted_for_hash(evidence))
    return MPR11GateReport(
        schema_version=MPR11_SCHEMA_VERSION,
        accepted=not blockers,
        blockers=tuple(dict.fromkeys(blockers)),
        evidence_hash=evidence_hash,
        covered_findings=tuple(covered_findings),
        live_execution_allowed=False,
        provider_network_allowed=False,
        signer_allowed=False,
    )


def canonical_cache_key(*parts: object, domain: str = "mpr11.cache-key.v1") -> str:
    """Return a collision-safe cache key for typed request descriptors.

    The key is a SHA-256 over canonical JSON with explicit part type names. It
    deliberately does not use delimiter joining, so ("a|b", "c") and ("a",
    "b|c") cannot collide through textual concatenation.
    """

    descriptor = {
        "domain": domain,
        "parts": [{"type": type(part).__name__, "value": part} for part in parts],
    }
    return _hash_json(descriptor)


@dataclass(slots=True)
class IdempotentQuotaReservation:
    """Small in-memory transition primitive for focused MPR-11 tests."""

    token: str
    issued: bool = False

    def mark_used(self) -> bool:
        """Mark the reservation used once and return whether a transition occurred."""

        if self.issued:
            return False
        self.issued = True
        return True


def validate_attempt_timing(
    *,
    now_unix_s: float,
    quote_created_at_unix_s: float,
    deadline_unix_s: float,
    max_quote_age_s: float,
    max_clock_skew_s: float = 0.0,
) -> tuple[bool, str]:
    """Fail closed for NaN/infinite, future quote and reversed deadline inputs."""

    values = (
        now_unix_s,
        quote_created_at_unix_s,
        deadline_unix_s,
        max_quote_age_s,
        max_clock_skew_s,
    )
    if not all(math.isfinite(value) for value in values):
        return False, "TIME_VALUE_NOT_FINITE"
    if max_quote_age_s < 0 or max_clock_skew_s < 0:
        return False, "TIME_BOUND_NEGATIVE"
    if quote_created_at_unix_s - now_unix_s > max_clock_skew_s:
        return False, "QUOTE_CREATED_IN_FUTURE"
    if now_unix_s > deadline_unix_s:
        return False, "DEADLINE_EXPIRED"
    if now_unix_s - quote_created_at_unix_s > max_quote_age_s:
        return False, "QUOTE_STALE"
    return True, "READY"


def _check_cache(value: object, blockers: list[str]) -> None:
    data = _mapping(value)
    _require(data is not None, blockers, "CACHE_EVIDENCE_MISSING")
    if data is None:
        return
    _require(bool(data.get("canonical_typed_hash")), blockers, "CACHE_KEY_NOT_CANONICAL")
    _require(
        bool(data.get("collision_vectors_rejected")),
        blockers,
        "CACHE_COLLISION_PROBE_NOT_REJECTED",
    )
    _require(
        bool(data.get("descriptor_hash_verified_on_read")),
        blockers,
        "CACHE_DESCRIPTOR_NOT_VERIFIED",
    )
    _require(bool(data.get("generation_aware")), blockers, "CACHE_GENERATION_NOT_BOUND")
    _require(_positive_int(data.get("max_entries")), blockers, "CACHE_ENTRY_BOUND_MISSING")
    _require(_positive_int(data.get("max_bytes")), blockers, "CACHE_BYTE_BOUND_MISSING")


def _check_quota(value: object, blockers: list[str]) -> None:
    data = _mapping(value)
    _require(data is not None, blockers, "QUOTA_EVIDENCE_MISSING")
    if data is None:
        return
    _require(bool(data.get("idempotent_mark_used")), blockers, "QUOTA_MARK_USED_NOT_IDEMPOTENT")
    _require(
        bool(data.get("concurrent_mark_used_single_winner")),
        blockers,
        "QUOTA_CONCURRENT_MARK_USED_UNSAFE",
    )
    _require(bool(data.get("account_wide_authority")), blockers, "QUOTA_ACCOUNT_AUTHORITY_MISSING")
    _require(
        bool(data.get("reservation_identity_persisted")),
        blockers,
        "QUOTA_RESERVATION_NOT_PERSISTED",
    )


def _check_scheduler(value: object, blockers: list[str]) -> None:
    data = _mapping(value)
    _require(data is not None, blockers, "SCHEDULER_EVIDENCE_MISSING")
    if data is None:
        return
    _require(
        bool(data.get("finite_time_validation")),
        blockers,
        "SCHEDULER_TIME_NOT_FINITE_VALIDATED",
    )
    _require(
        bool(data.get("causal_quote_time_validation")),
        blockers,
        "SCHEDULER_CAUSALITY_MISSING",
    )
    _require(
        bool(data.get("atomic_plan_reservations")),
        blockers,
        "SCHEDULER_PLAN_RESERVATION_MISSING",
    )
    _require(
        bool(data.get("profile_failure_resurrection_blocked")),
        blockers,
        "SCHEDULER_PROFILE_RESURRECTION",
    )
    remaining = data.get("remaining_quota_slots")
    planned = data.get("planned_attempts")
    _require(isinstance(remaining, int) and remaining >= 0, blockers, "SCHEDULER_REMAINING_QUOTA_INVALID")
    _require(isinstance(planned, int) and planned >= 0, blockers, "SCHEDULER_PLANNED_ATTEMPTS_INVALID")
    if isinstance(remaining, int) and isinstance(planned, int):
        _require(planned <= remaining, blockers, "SCHEDULER_OVERPLANS_QUOTA")


def _check_public_keys(value: object, blockers: list[str]) -> None:
    data = _mapping(value)
    _require(data is not None, blockers, "PUBLIC_KEY_EVIDENCE_MISSING")
    if data is None:
        return
    _require(bool(data.get("canonical_solana_decode")), blockers, "PUBLIC_KEY_REGEX_ONLY")
    _require(bool(data.get("round_trip_normalization")), blockers, "PUBLIC_KEY_NOT_NORMALIZED")
    _require(bool(data.get("regex_only_vectors_rejected")), blockers, "PUBLIC_KEY_REGEX_VECTOR_ACCEPTED")


def _check_quote_freshness(value: object, blockers: list[str]) -> None:
    data = _mapping(value)
    _require(data is not None, blockers, "QUOTE_FRESHNESS_EVIDENCE_MISSING")
    if data is None:
        return
    _require(bool(data.get("trusted_current_time_or_slot")), blockers, "QUOTE_TRUSTED_TIME_MISSING")
    _require(bool(data.get("no_expiry_execution_rejected")), blockers, "QUOTE_NO_EXPIRY_EXECUTABLE")
    _require(bool(data.get("stale_replay_rejected")), blockers, "QUOTE_STALE_REPLAY_ACCEPTED")
    _require(
        bool(data.get("blockhash_or_provider_validity_bound")),
        blockers,
        "QUOTE_CHAIN_VALIDITY_MISSING",
    )


def _check_transport(value: object, blockers: list[str]) -> None:
    data = _mapping(value)
    _require(data is not None, blockers, "TRANSPORT_EVIDENCE_MISSING")
    if data is None:
        return
    _require(
        bool(data.get("actual_client_policy_attested")),
        blockers,
        "TRANSPORT_CLIENT_NOT_ATTESTED",
    )
    _require(
        bool(data.get("injected_insecure_client_rejected")),
        blockers,
        "TRANSPORT_INSECURE_CLIENT_ACCEPTED",
    )
    _require(
        bool(data.get("tls_verify_bound_to_evidence")),
        blockers,
        "TRANSPORT_TLS_EVIDENCE_NOT_ACTUAL",
    )
    _require(
        bool(data.get("proxy_redirect_policy_bound")),
        blockers,
        "TRANSPORT_PROXY_REDIRECT_UNBOUND",
    )


def _check_adapters(value: object, blockers: list[str]) -> None:
    data = _mapping(value)
    _require(data is not None, blockers, "ADAPTER_EVIDENCE_MISSING")
    if data is None:
        return
    _require(bool(data.get("jupiter_slippage_not_widened")), blockers, "JUPITER_SLIPPAGE_WIDENING")
    _require(bool(data.get("jupiter_swap_mode_echo_verified")), blockers, "JUPITER_SWAP_MODE_UNBOUND")
    _require(bool(data.get("openocean_mint_echo_verified")), blockers, "OPENOCEAN_MINT_UNBOUND")
    _require(bool(data.get("odos_token_amount_echo_verified")), blockers, "ODOS_RESPONSE_UNBOUND")
    _require(bool(data.get("okx_request_response_bound")), blockers, "OKX_RESPONSE_UNBOUND")
    _require(
        bool(data.get("cross_request_substitution_rejected")),
        blockers,
        "ADAPTER_SUBSTITUTION_ACCEPTED",
    )


def _check_route_identity(value: object, blockers: list[str]) -> None:
    data = _mapping(value)
    _require(data is not None, blockers, "ROUTE_IDENTITY_EVIDENCE_MISSING")
    if data is None:
        return
    _require(
        bool(data.get("program_pool_account_identity")),
        blockers,
        "ROUTE_LABEL_ONLY_IDENTITY",
    )
    _require(bool(data.get("blockhash_validity_bound")), blockers, "ROUTE_BLOCKHASH_VALIDITY_MISSING")
    _require(bool(data.get("schema_generation_bound")), blockers, "ROUTE_SCHEMA_GENERATION_MISSING")
    _require(bool(data.get("expired_blockhash_rejected")), blockers, "ROUTE_EXPIRED_BLOCKHASH_ACCEPTED")


def _mapping(value: object) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    return None


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and value > 0


def _require(condition: bool, blockers: list[str], code: str) -> None:
    if not condition:
        blockers.append(code)


def _redacted_for_hash(evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in evidence.items()
        if key not in {"operator_note", "debug", "comment"}
    }


def _hash_json(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
