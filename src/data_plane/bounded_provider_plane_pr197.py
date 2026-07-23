"""PR-197 bounded data/provider-plane safety primitives.

This module is intentionally side-effect-free with respect to live trading: it
contains no signer, sender, wallet, or transaction submission code.  It provides
reusable authorities for the new PR-197 vertical: hardened provider response
admission, account-wide quota reservation, deterministic discovery identity,
rooted RPC quorum checks and durable Helius-style webhook acknowledgement.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import gzip
import hashlib
import io
import ipaddress
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Any
from urllib.parse import urlparse

PR197_SCHEMA_VERSION = "pr197.bounded-provider-plane.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class ProviderPlaneError(ValueError):
    """Fail-closed provider-plane validation error with a stable reason code."""

    def __init__(self, reason_code: str, message: str | None = None) -> None:
        self.reason_code = reason_code
        super().__init__(message or reason_code)


class ProviderPlaneDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"
    RETRYABLE = "retryable"


@dataclass(frozen=True, slots=True)
class HostResolution:
    """A hostname resolution decision that pins the validated destination set."""

    hostname: str
    addresses: tuple[str, ...]
    address_fingerprints: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HardenedEndpointPolicy:
    """Fail-closed endpoint policy for HTTP/JSON-RPC/WebSocket providers."""

    allowed_hosts: frozenset[str]
    allowed_cidrs: tuple[
        ipaddress.IPv4Network | ipaddress.IPv6Network, ...
    ] = field(default_factory=tuple)
    require_https: bool = True
    allow_private_networks: bool = False
    max_body_bytes: int = 262_144
    max_decompressed_bytes: int = 524_288
    max_json_depth: int = 48
    max_attempts: int = 3
    total_deadline_ms: int = 2_000

    def __post_init__(self) -> None:
        if not self.allowed_hosts:
            raise ProviderPlaneError("PR197_EMPTY_HOST_ALLOWLIST")
        for host in self.allowed_hosts:
            _require_safe_host(host)
        _require_positive_int(self.max_body_bytes, "max_body_bytes")
        _require_positive_int(self.max_decompressed_bytes, "max_decompressed_bytes")
        _require_positive_int(self.max_json_depth, "max_json_depth")
        _require_positive_int(self.max_attempts, "max_attempts")
        _require_positive_int(self.total_deadline_ms, "total_deadline_ms")
        if self.max_decompressed_bytes < self.max_body_bytes:
            raise ProviderPlaneError("PR197_DECOMPRESSED_LIMIT_LT_COMPRESSED_LIMIT")

    def validate_url(
        self,
        url: str,
        *,
        resolver: Callable[[str], Sequence[str]] | None = None,
    ) -> HostResolution:
        parsed = urlparse(url)
        if self.require_https and parsed.scheme != "https":
            raise ProviderPlaneError("PR197_ENDPOINT_NOT_HTTPS")
        if not parsed.hostname:
            raise ProviderPlaneError("PR197_ENDPOINT_HOST_MISSING")
        if parsed.username or parsed.password:
            raise ProviderPlaneError("PR197_ENDPOINT_CREDENTIALS_FORBIDDEN")
        host = parsed.hostname.lower().rstrip(".")
        allowed_hosts = {item.lower().rstrip(".") for item in self.allowed_hosts}
        if host not in allowed_hosts:
            raise ProviderPlaneError("PR197_ENDPOINT_HOST_NOT_ALLOWED")
        raw_addresses: Sequence[str]
        literal = _parse_ip_literal(host)
        if literal is not None:
            raw_addresses = (str(literal),)
        else:
            if resolver is None:
                raise ProviderPlaneError("PR197_DNS_RESOLUTION_REQUIRED")
            raw_addresses = resolver(host)
        addresses: list[str] = []
        fingerprints: list[str] = []
        for raw_address in raw_addresses:
            address = ipaddress.ip_address(str(raw_address))
            if _is_forbidden_address(
                address, allow_private=self.allow_private_networks
            ):
                raise ProviderPlaneError("PR197_ENDPOINT_PRIVATE_OR_LOCAL_ADDRESS")
            if self.allowed_cidrs and not any(
                address in network for network in self.allowed_cidrs
            ):
                raise ProviderPlaneError("PR197_ENDPOINT_CIDR_NOT_ALLOWED")
            normalized = str(address)
            addresses.append(normalized)
            fingerprints.append(_sha256_text(normalized))
        if not addresses:
            raise ProviderPlaneError("PR197_DNS_EMPTY_RESULT")
        return HostResolution(
            hostname=host,
            addresses=tuple(addresses),
            address_fingerprints=tuple(fingerprints),
        )


@dataclass(frozen=True, slots=True)
class RetryBudget:
    """Attempt budget bounded by one absolute freshness deadline."""

    max_attempts: int
    total_deadline_ms: int
    started_at_ms: int

    def __post_init__(self) -> None:
        _require_positive_int(self.max_attempts, "max_attempts")
        _require_positive_int(self.total_deadline_ms, "total_deadline_ms")
        if self.started_at_ms < 0:
            raise ProviderPlaneError("PR197_NEGATIVE_START_MS")

    def assert_attempt_allowed(self, *, attempt_number: int, now_ms: int) -> None:
        if attempt_number < 1 or attempt_number > self.max_attempts:
            raise ProviderPlaneError("PR197_RETRY_ATTEMPT_EXHAUSTED")
        if now_ms - self.started_at_ms > self.total_deadline_ms:
            raise ProviderPlaneError("PR197_RETRY_DEADLINE_EXPIRED")

    def clamp_retry_after_ms(self, retry_after_ms: int, *, now_ms: int) -> int:
        if retry_after_ms < 0:
            raise ProviderPlaneError("PR197_NEGATIVE_RETRY_AFTER")
        remaining = self.total_deadline_ms - (now_ms - self.started_at_ms)
        if remaining <= 0:
            raise ProviderPlaneError("PR197_RETRY_DEADLINE_EXPIRED")
        if retry_after_ms > remaining:
            raise ProviderPlaneError("PR197_RETRY_AFTER_EXCEEDS_DEADLINE")
        return retry_after_ms


@dataclass(frozen=True, slots=True)
class BoundedJsonResult:
    value: object
    body_sha256: str
    content_type: str
    compressed_bytes: int
    decompressed_bytes: int
    max_depth_observed: int


def parse_bounded_json_response(
    body: bytes,
    *,
    content_type: str,
    content_encoding: str | None = None,
    declared_content_length: int | None = None,
    policy: HardenedEndpointPolicy,
) -> BoundedJsonResult:
    """Parse one provider response only after byte, type and depth checks."""

    normalized_type = content_type.split(";", 1)[0].strip().lower()
    if normalized_type not in {"application/json", "application/json-rpc"}:
        raise ProviderPlaneError("PR197_UNSUPPORTED_CONTENT_TYPE")
    if declared_content_length is not None:
        if declared_content_length < 0:
            raise ProviderPlaneError("PR197_NEGATIVE_CONTENT_LENGTH")
        if declared_content_length > policy.max_body_bytes:
            raise ProviderPlaneError("PR197_DECLARED_BODY_TOO_LARGE")
    if len(body) > policy.max_body_bytes:
        raise ProviderPlaneError("PR197_BODY_TOO_LARGE")
    encoding = (content_encoding or "identity").strip().lower()
    if encoding in {"", "identity"}:
        decoded = body
    elif encoding == "gzip":
        decoded = _bounded_gzip_decode(body, max_bytes=policy.max_decompressed_bytes)
    else:
        raise ProviderPlaneError("PR197_UNSUPPORTED_CONTENT_ENCODING")
    if len(decoded) > policy.max_decompressed_bytes:
        raise ProviderPlaneError("PR197_DECOMPRESSED_BODY_TOO_LARGE")
    try:
        value = json.loads(
            decoded.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderPlaneError("PR197_INVALID_JSON") from exc
    depth = _json_depth(value)
    if depth > policy.max_json_depth:
        raise ProviderPlaneError("PR197_JSON_TOO_DEEP")
    return BoundedJsonResult(
        value=value,
        body_sha256=hashlib.sha256(decoded).hexdigest(),
        content_type=normalized_type,
        compressed_bytes=len(body),
        decompressed_bytes=len(decoded),
        max_depth_observed=depth,
    )


@dataclass(frozen=True, slots=True)
class QuotaReservation:
    provider: str
    key_fingerprint: str
    bucket_start_ms: int
    bucket_span_ms: int
    used_after: int
    limit: int
    reservation_id: str


class SQLiteQuotaAuthority:
    """Cross-process quota authority keyed by provider and API-key fingerprint."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._db_path, isolation_level=None)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA trusted_schema=OFF")
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS quota_windows ("
            "provider TEXT NOT NULL, "
            "key_fingerprint TEXT NOT NULL, "
            "bucket_start_ms INTEGER NOT NULL, "
            "bucket_span_ms INTEGER NOT NULL, "
            "used INTEGER NOT NULL, "
            "limit_value INTEGER NOT NULL, "
            "PRIMARY KEY(provider, key_fingerprint, bucket_start_ms, bucket_span_ms))"
        )

    def reserve(
        self,
        *,
        provider: str,
        key_fingerprint: str,
        now_ms: int,
        limit: int,
        bucket_span_ms: int,
        units: int = 1,
    ) -> QuotaReservation:
        _require_safe_id(provider, "provider")
        _require_sha256(key_fingerprint, "key_fingerprint")
        _require_positive_int(now_ms, "now_ms")
        _require_positive_int(limit, "limit")
        _require_positive_int(bucket_span_ms, "bucket_span_ms")
        _require_positive_int(units, "units")
        if units > limit:
            raise ProviderPlaneError("PR197_QUOTA_UNITS_EXCEED_LIMIT")
        bucket_start = (now_ms // bucket_span_ms) * bucket_span_ms
        with self._connection:
            self._connection.execute("BEGIN IMMEDIATE")
            row = self._connection.execute(
                "SELECT used, limit_value FROM quota_windows WHERE "
                "provider=? AND key_fingerprint=? AND bucket_start_ms=? "
                "AND bucket_span_ms=?",
                (provider, key_fingerprint, bucket_start, bucket_span_ms),
            ).fetchone()
            if row is None:
                used = 0
                stored_limit = limit
                self._connection.execute(
                    "INSERT INTO quota_windows(provider, key_fingerprint, "
                    "bucket_start_ms, bucket_span_ms, used, limit_value) "
                    "VALUES (?, ?, ?, ?, 0, ?)",
                    (provider, key_fingerprint, bucket_start, bucket_span_ms, limit),
                )
            else:
                used = _strict_int(row[0], "used")
                stored_limit = _strict_int(row[1], "limit_value")
                if stored_limit != limit:
                    raise ProviderPlaneError("PR197_QUOTA_LIMIT_DRIFT")
            if used + units > limit:
                raise ProviderPlaneError("PR197_QUOTA_EXHAUSTED")
            used_after = used + units
            self._connection.execute(
                "UPDATE quota_windows SET used=? WHERE provider=? AND "
                "key_fingerprint=? AND bucket_start_ms=? AND bucket_span_ms=?",
                (used_after, provider, key_fingerprint, bucket_start, bucket_span_ms),
            )
        reservation_id = _sha256_json(
            {
                "provider": provider,
                "key_fingerprint": key_fingerprint,
                "bucket_start_ms": bucket_start,
                "bucket_span_ms": bucket_span_ms,
                "used_after": used_after,
                "units": units,
            }
        )
        return QuotaReservation(
            provider=provider,
            key_fingerprint=key_fingerprint,
            bucket_start_ms=bucket_start,
            bucket_span_ms=bucket_span_ms,
            used_after=used_after,
            limit=limit,
            reservation_id=reservation_id,
        )

    def close(self) -> None:
        self._connection.close()


@dataclass(frozen=True, slots=True)
class DiscoverySnapshot:
    provider: str
    route_id: str
    input_mint: str
    output_mint: str
    in_amount: int
    out_amount: int
    context_slot: int
    observed_at_ms: int
    response_hash: str

    def __post_init__(self) -> None:
        _require_safe_id(self.provider, "provider")
        _require_safe_id(self.route_id, "route_id")
        _require_safe_id(self.input_mint, "input_mint")
        _require_safe_id(self.output_mint, "output_mint")
        _require_nonnegative_int(self.in_amount, "in_amount")
        _require_nonnegative_int(self.out_amount, "out_amount")
        _require_positive_int(self.context_slot, "context_slot")
        _require_positive_int(self.observed_at_ms, "observed_at_ms")
        _require_sha256(self.response_hash, "response_hash")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "route_id": self.route_id,
            "input_mint": self.input_mint,
            "output_mint": self.output_mint,
            "in_amount": self.in_amount,
            "out_amount": self.out_amount,
            "context_slot": self.context_slot,
            "observed_at_ms": self.observed_at_ms,
            "response_hash": self.response_hash,
        }


def deterministic_cycle_id(
    *,
    opportunity_identity: str,
    evidence_generation: str,
    request_payload_hash: str,
    provider_set: Sequence[str],
) -> str:
    _require_safe_id(opportunity_identity, "opportunity_identity")
    _require_safe_id(evidence_generation, "evidence_generation")
    _require_sha256(request_payload_hash, "request_payload_hash")
    providers = tuple(
        sorted(_require_safe_id(item, "provider") for item in provider_set)
    )
    if not providers:
        raise ProviderPlaneError("PR197_EMPTY_PROVIDER_SET")
    return _sha256_json(
        {
            "schema": "pr197.discovery-cycle-id.v1",
            "opportunity_identity": opportunity_identity,
            "evidence_generation": evidence_generation,
            "request_payload_hash": request_payload_hash,
            "provider_set": providers,
        }
    )


def canonicalize_snapshots(
    snapshots: Sequence[DiscoverySnapshot],
) -> tuple[DiscoverySnapshot, ...]:
    """Deduplicate with a deterministic best-evidence tie-break."""

    best: dict[tuple[str, str, int], DiscoverySnapshot] = {}
    for snapshot in snapshots:
        key = (snapshot.input_mint, snapshot.output_mint, snapshot.in_amount)
        current = best.get(key)
        if current is None or _snapshot_rank(snapshot) < _snapshot_rank(current):
            best[key] = snapshot
    return tuple(best[key] for key in sorted(best))


@dataclass(frozen=True, slots=True)
class RootedRpcObservation:
    provider: str
    correlation_group: str
    genesis_hash: str
    rooted_slot: int
    min_context_slot: int
    state_hash: str

    def __post_init__(self) -> None:
        _require_safe_id(self.provider, "provider")
        _require_safe_id(self.correlation_group, "correlation_group")
        _require_sha256(self.genesis_hash, "genesis_hash")
        _require_positive_int(self.rooted_slot, "rooted_slot")
        _require_positive_int(self.min_context_slot, "min_context_slot")
        _require_sha256(self.state_hash, "state_hash")
        if self.rooted_slot < self.min_context_slot:
            raise ProviderPlaneError("PR197_RPC_ROOT_BELOW_MIN_CONTEXT")


@dataclass(frozen=True, slots=True)
class RpcQuorumVerdict:
    accepted: bool
    generation_id: str | None
    blockers: tuple[str, ...]
    rooted_slot: int | None
    source_count: int


def evaluate_rooted_rpc_quorum(
    observations: Sequence[RootedRpcObservation],
    *,
    min_sources: int = 2,
    min_distinct_groups: int = 2,
) -> RpcQuorumVerdict:
    _require_positive_int(min_sources, "min_sources")
    _require_positive_int(min_distinct_groups, "min_distinct_groups")
    blockers: list[str] = []
    if len(observations) < min_sources:
        blockers.append("PR197_RPC_INSUFFICIENT_SOURCES")
    groups = {item.correlation_group for item in observations}
    if len(groups) < min_distinct_groups:
        blockers.append("PR197_RPC_INSUFFICIENT_CORRELATION_GROUPS")
    genesis_values = {item.genesis_hash for item in observations}
    if len(genesis_values) != 1:
        blockers.append("PR197_RPC_GENESIS_DISAGREEMENT")
    state_values = {item.state_hash for item in observations}
    if len(state_values) != 1:
        blockers.append("PR197_RPC_STATE_DISAGREEMENT")
    rooted_slots = tuple(item.rooted_slot for item in observations)
    rooted_slot = min(rooted_slots) if rooted_slots else None
    if rooted_slot is None:
        blockers.append("PR197_RPC_NO_ROOTED_SLOT")
    accepted = not blockers
    generation_id = None
    if accepted and rooted_slot is not None:
        generation_id = _sha256_json(
            {
                "schema": "pr197.rooted-rpc-generation.v1",
                "genesis_hash": next(iter(genesis_values)),
                "state_hash": next(iter(state_values)),
                "rooted_slot": rooted_slot,
                "sources": tuple(sorted(item.provider for item in observations)),
                "groups": tuple(sorted(groups)),
            }
        )
    return RpcQuorumVerdict(
        accepted=accepted,
        generation_id=generation_id,
        blockers=tuple(blockers),
        rooted_slot=rooted_slot,
        source_count=len(observations),
    )


@dataclass(frozen=True, slots=True)
class DurableWebhookDecision:
    decision: ProviderPlaneDecision
    delivery_id: str
    body_hash: str
    inserted: bool
    status_code: int
    reason_code: str | None = None


class DurableWebhookInbox:
    """Durable inbox that persists/deduplicates before returning HTTP 200."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        auth_token_hash: str,
        max_body_bytes: int = 262_144,
        max_json_depth: int = 48,
    ) -> None:
        _require_sha256(auth_token_hash, "auth_token_hash")
        _require_positive_int(max_body_bytes, "max_body_bytes")
        _require_positive_int(max_json_depth, "max_json_depth")
        self._auth_token_hash = auth_token_hash
        self._max_body_bytes = max_body_bytes
        self._max_json_depth = max_json_depth
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._db_path, isolation_level=None)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA trusted_schema=OFF")
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS webhook_inbox ("
            "delivery_id TEXT PRIMARY KEY, "
            "body_hash TEXT NOT NULL, "
            "received_at_ms INTEGER NOT NULL, "
            "payload TEXT NOT NULL, "
            "processed INTEGER NOT NULL DEFAULT 0)"
        )

    def receive(
        self,
        *,
        delivery_id: str,
        body: bytes,
        authorization: str,
        received_at_ms: int | None = None,
    ) -> DurableWebhookDecision:
        _require_safe_id(delivery_id, "delivery_id")
        if _sha256_text(authorization) != self._auth_token_hash:
            return DurableWebhookDecision(
                decision=ProviderPlaneDecision.REJECTED,
                delivery_id=delivery_id,
                body_hash=_sha256_bytes(body),
                inserted=False,
                status_code=401,
                reason_code="PR197_WEBHOOK_AUTH_REJECTED",
            )
        policy = HardenedEndpointPolicy(
            allowed_hosts=frozenset({"localhost"}),
            max_body_bytes=self._max_body_bytes,
            max_decompressed_bytes=self._max_body_bytes,
            max_json_depth=self._max_json_depth,
        )
        try:
            parsed = parse_bounded_json_response(
                body,
                content_type="application/json",
                policy=policy,
            )
        except ProviderPlaneError as exc:
            return DurableWebhookDecision(
                decision=ProviderPlaneDecision.RETRYABLE,
                delivery_id=delivery_id,
                body_hash=_sha256_bytes(body),
                inserted=False,
                status_code=503,
                reason_code=exc.reason_code,
            )
        now = int(received_at_ms if received_at_ms is not None else time.time() * 1000)
        try:
            with self._connection:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._connection.execute(
                    "SELECT body_hash FROM webhook_inbox WHERE delivery_id=?",
                    (delivery_id,),
                ).fetchone()
                if row is None:
                    self._connection.execute(
                        "INSERT INTO webhook_inbox("
                        "delivery_id, body_hash, received_at_ms, payload) "
                        "VALUES (?, ?, ?, ?)",
                        (
                            delivery_id,
                            parsed.body_sha256,
                            now,
                            json.dumps(
                                parsed.value,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                        ),
                    )
                    return DurableWebhookDecision(
                        decision=ProviderPlaneDecision.ACCEPTED,
                        delivery_id=delivery_id,
                        body_hash=parsed.body_sha256,
                        inserted=True,
                        status_code=200,
                    )
                existing_hash = str(row[0])
                if existing_hash != parsed.body_sha256:
                    return DurableWebhookDecision(
                        decision=ProviderPlaneDecision.REJECTED,
                        delivery_id=delivery_id,
                        body_hash=parsed.body_sha256,
                        inserted=False,
                        status_code=409,
                        reason_code="PR197_WEBHOOK_DELIVERY_REBOUND",
                    )
                return DurableWebhookDecision(
                    decision=ProviderPlaneDecision.DUPLICATE,
                    delivery_id=delivery_id,
                    body_hash=parsed.body_sha256,
                    inserted=False,
                    status_code=200,
                )
        except sqlite3.Error as exc:
            raise ProviderPlaneError("PR197_WEBHOOK_DURABILITY_FAILURE") from exc

    def pending_payloads(self) -> tuple[dict[str, object], ...]:
        rows = self._connection.execute(
            "SELECT payload FROM webhook_inbox WHERE processed=0 "
            "ORDER BY received_at_ms, delivery_id"
        ).fetchall()
        return tuple(json.loads(str(row[0])) for row in rows)

    def close(self) -> None:
        self._connection.close()


def provider_plane_report(
    *,
    cycle_id: str,
    quota_reservation: QuotaReservation | None,
    rpc_quorum: RpcQuorumVerdict | None,
    snapshots: Sequence[DiscoverySnapshot],
) -> dict[str, object]:
    _require_sha256(cycle_id, "cycle_id")
    canonical = canonicalize_snapshots(snapshots)
    return {
        "schema_version": PR197_SCHEMA_VERSION,
        "live_enabled": False,
        "signer_reachable": False,
        "sender_reachable": False,
        "submission_allowed": False,
        "cycle_id": cycle_id,
        "quota_reservation_id": (
            quota_reservation.reservation_id if quota_reservation is not None else None
        ),
        "rpc_quorum_accepted": rpc_quorum.accepted if rpc_quorum is not None else False,
        "rpc_generation_id": (
            rpc_quorum.generation_id if rpc_quorum is not None else None
        ),
        "candidate_count": len(canonical),
        "candidate_hash": _sha256_json(
            [item.canonical_payload() for item in canonical]
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _snapshot_rank(snapshot: DiscoverySnapshot) -> tuple[int, int, str, str]:
    return (
        -snapshot.context_slot,
        -snapshot.out_amount,
        snapshot.provider,
        snapshot.response_hash,
    )


def _bounded_gzip_decode(body: bytes, *, max_bytes: int) -> bytes:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
            decoded = stream.read(max_bytes + 1)
    except OSError as exc:
        raise ProviderPlaneError("PR197_INVALID_GZIP") from exc
    if len(decoded) > max_bytes:
        raise ProviderPlaneError("PR197_DECOMPRESSED_BODY_TOO_LARGE")
    return decoded


def _json_depth(value: object) -> int:
    if isinstance(value, Mapping):
        if not value:
            return 1
        return 1 + max(_json_depth(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if not value:
            return 1
        return 1 + max(_json_depth(item) for item in value)
    return 1


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _parse_ip_literal(
    host: str,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def _is_forbidden_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    *,
    allow_private: bool,
) -> bool:
    if address.is_loopback or address.is_link_local or address.is_multicast:
        return True
    if address.is_private and not allow_private:
        return True
    if address.is_unspecified or address.is_reserved:
        return True
    return False


def _require_safe_host(value: str) -> str:
    if not value or len(value) > 253 or any(part == "" for part in value.split(".")):
        raise ProviderPlaneError("PR197_UNSAFE_HOST")
    for part in value.split("."):
        if len(part) > 63 or not re.fullmatch(r"[A-Za-z0-9-]+", part):
            raise ProviderPlaneError("PR197_UNSAFE_HOST")
    return value


def _require_safe_id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ProviderPlaneError(f"PR197_INVALID_{field_name.upper()}")
    return value


def _require_sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ProviderPlaneError(f"PR197_INVALID_{field_name.upper()}")
    return value


def _require_positive_int(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProviderPlaneError(f"PR197_INVALID_{field_name.upper()}")
    return value


def _require_nonnegative_int(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProviderPlaneError(f"PR197_INVALID_{field_name.upper()}")
    return value


def _strict_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProviderPlaneError(f"PR197_INVALID_{field_name.upper()}")
    return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
