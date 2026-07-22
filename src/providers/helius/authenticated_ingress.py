"""PR-199 authenticated inbound gateway boundary for Helius deliveries.

The provider only repeats a configured ``Authorization`` value.  This module
therefore does not mislabel that header as a body signature or cryptographic
proof of provider origin.  Production acceptance additionally requires a
reviewed gateway identity, trusted proxy parsing, TLS, source policy, an exact
server-side webhook/config generation and a logical credential version.

The installer preserves the public PR-188 delivery API.  It replaces the
exported ``HeliusDeliveryPlane`` class after ``delivery`` is imported so direct
imports from ``src.providers.helius.delivery`` receive the hardened boundary as
well as package-level imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import hashlib
import hmac
import ipaddress
import json
import sqlite3
import threading
import time
from types import ModuleType
from typing import Any, Callable, Mapping, Sequence


class CredentialState(str, Enum):
    STAGED = "staged"
    ACTIVE = "active"
    OVERLAP = "overlap"
    REVOKED = "revoked"


class IngressRejectReason(str, Enum):
    WEBHOOK_ID_MISMATCH = "WEBHOOK_ID_MISMATCH"
    CONFIG_GENERATION_MISMATCH = "CONFIG_GENERATION_MISMATCH"
    MISSING_REQUEST_METADATA = "MISSING_REQUEST_METADATA"
    UNTRUSTED_GATEWAY = "UNTRUSTED_GATEWAY"
    AMBIGUOUS_FORWARDED_CHAIN = "AMBIGUOUS_FORWARDED_CHAIN"
    FORWARDED_CHAIN_TOO_LONG = "FORWARDED_CHAIN_TOO_LONG"
    TLS_REQUIRED = "TLS_REQUIRED"
    SOURCE_NETWORK_DENIED = "SOURCE_NETWORK_DENIED"
    MISSING_CREDENTIAL = "MISSING_CREDENTIAL"
    INVALID_CREDENTIAL = "INVALID_CREDENTIAL"
    CREDENTIAL_NOT_ACTIVE = "CREDENTIAL_NOT_ACTIVE"
    CREDENTIAL_REVOKED = "CREDENTIAL_REVOKED"
    DELIVERY_METADATA_CONFLICT = "DELIVERY_METADATA_CONFLICT"
    INGRESS_AUDIT_STORE_ERROR = "INGRESS_AUDIT_STORE_ERROR"


class IngressRejected(PermissionError):
    def __init__(self, reason: IngressRejectReason, status_code: int) -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class CredentialBinding:
    """Logical credential identity plus the in-memory verification value.

    ``authorization`` is excluded from repr and audit output.
    Durable records contain only ``credential_id`` and ``version``.
    """

    credential_id: str
    version: str
    authorization: str = field(repr=False)
    state: CredentialState = CredentialState.ACTIVE
    not_before_utc_ns: int | None = None
    not_after_utc_ns: int | None = None

    def __post_init__(self) -> None:
        if not self.credential_id.strip() or not self.version.strip():
            raise ValueError("credential_id and version are required")
        if not self.authorization:
            raise ValueError("authorization is required")
        if (
            self.not_before_utc_ns is not None
            and self.not_after_utc_ns is not None
            and self.not_before_utc_ns >= self.not_after_utc_ns
        ):
            raise ValueError("credential validity window is invalid")

    def valid_at(self, utc_ns: int) -> bool:
        if self.not_before_utc_ns is not None and utc_ns < self.not_before_utc_ns:
            return False
        if self.not_after_utc_ns is not None and utc_ns >= self.not_after_utc_ns:
            return False
        return True

    @property
    def accepts_requests(self) -> bool:
        return self.state in {CredentialState.ACTIVE, CredentialState.OVERLAP}


@dataclass(frozen=True, slots=True)
class IngressGatewayPolicy:
    expected_webhook_id: str
    config_generation: str
    credentials: tuple[CredentialBinding, ...]
    trusted_proxy_cidrs: tuple[str, ...]
    allowed_source_cidrs: tuple[str, ...] = ()
    required_peer_identities: tuple[str, ...] = ()
    network: str = "mainnet-beta"
    webhook_type: str = "enhanced_transaction"
    require_tls: bool = True
    allow_direct_peers: bool = False
    forwarded_hop_limit: int = 8

    def __post_init__(self) -> None:
        if not self.expected_webhook_id.strip():
            raise ValueError("expected_webhook_id is required")
        if not self.config_generation.strip():
            raise ValueError("config_generation is required")
        if not self.credentials:
            raise ValueError("at least one credential is required")
        if self.forwarded_hop_limit <= 0:
            raise ValueError("forwarded_hop_limit must be positive")
        if not self.allow_direct_peers and not self.trusted_proxy_cidrs:
            raise ValueError(
                "trusted proxies are required when direct peers are disabled"
            )

        identities: set[tuple[str, str]] = set()
        authorizations: set[str] = set()
        for credential in self.credentials:
            identity = (credential.credential_id, credential.version)
            if identity in identities:
                raise ValueError("credential identity/version must be unique")
            if credential.authorization in authorizations:
                raise ValueError("credential authorization values must be unique")
            identities.add(identity)
            authorizations.add(credential.authorization)

        for value in (*self.trusted_proxy_cidrs, *self.allowed_source_cidrs):
            ipaddress.ip_network(value, strict=False)

    def with_credentials(
        self, credentials: Sequence[CredentialBinding]
    ) -> "IngressGatewayPolicy":
        return replace(self, credentials=tuple(credentials))


@dataclass(frozen=True, slots=True)
class IngressConnectionMetadata:
    """Trusted metadata supplied by the HTTP server/gateway adapter.

    None of these fields should be populated from request body/query values.
    ``config_generation`` is the generation selected by server-side routing.
    """

    immediate_peer: str
    transport_tls: bool
    config_generation: str
    observed_webhook_id: str | None = None
    peer_identity: str | None = None
    provider_delivery_id: str | None = None
    received_monotonic_ns: int | None = None
    received_utc_ns: int | None = None


@dataclass(frozen=True, slots=True)
class InboundRequestContext:
    immediate_peer: str
    client_ip: str
    trusted_proxy_chain: tuple[str, ...]
    tls_verified: bool
    peer_identity: str | None
    webhook_id: str
    config_generation: str
    credential_id: str
    credential_version: str
    network: str
    webhook_type: str
    received_monotonic_ns: int
    received_utc_ns: int
    body_digest: str
    provider_delivery_id: str | None
    provider_origin_cryptographically_proven: bool = False

    def audit_record(self) -> dict[str, Any]:
        return {
            "immediate_peer": self.immediate_peer,
            "client_ip": self.client_ip,
            "trusted_proxy_chain": list(self.trusted_proxy_chain),
            "tls_verified": self.tls_verified,
            "peer_identity": self.peer_identity,
            "webhook_id": self.webhook_id,
            "config_generation": self.config_generation,
            "credential_id": self.credential_id,
            "credential_version": self.credential_version,
            "network": self.network,
            "webhook_type": self.webhook_type,
            "received_monotonic_ns": self.received_monotonic_ns,
            "received_utc_ns": self.received_utc_ns,
            "body_digest": self.body_digest,
            "provider_delivery_id": self.provider_delivery_id,
            "provider_origin_cryptographically_proven": False,
        }


@dataclass(frozen=True, slots=True)
class _ResolvedPeer:
    immediate_peer: str
    client_ip: str
    trusted_proxy_chain: tuple[str, ...]
    tls_verified: bool


def _headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        str(key).strip().lower(): str(value).strip() for key, value in headers.items()
    }


def _parse_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    candidate = str(value).strip()
    if candidate.startswith("["):
        closing = candidate.find("]")
        if closing >= 0:
            candidate = candidate[1:closing]
    else:
        try:
            return ipaddress.ip_address(candidate)
        except ValueError:
            if candidate.count(":") == 1:
                host, port = candidate.rsplit(":", 1)
                if port.isdigit():
                    candidate = host
    return ipaddress.ip_address(candidate)


def _in_networks(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    cidrs: Sequence[str],
) -> bool:
    return any(address in ipaddress.ip_network(value, strict=False) for value in cidrs)


def _parse_forwarded_for(value: str) -> tuple[list[str], str | None]:
    addresses: list[str] = []
    proto: str | None = None
    for element in value.split(","):
        parameters: dict[str, str] = {}
        for token in element.split(";"):
            if "=" not in token:
                continue
            key, raw = token.split("=", 1)
            parameters[key.strip().lower()] = raw.strip().strip('"')
        raw_for = parameters.get("for")
        if raw_for:
            if raw_for.lower() == "unknown" or raw_for.startswith("_"):
                raise IngressRejected(
                    IngressRejectReason.AMBIGUOUS_FORWARDED_CHAIN, 400
                )
            addresses.append(str(_parse_ip(raw_for)))
        if parameters.get("proto"):
            proto = parameters["proto"].lower()
    return addresses, proto


def _parse_x_forwarded_for(value: str) -> list[str]:
    addresses: list[str] = []
    for item in value.split(","):
        item = item.strip()
        if item:
            addresses.append(str(_parse_ip(item)))
    return addresses


def _resolve_peer(
    headers: Mapping[str, str],
    metadata: IngressConnectionMetadata,
    policy: IngressGatewayPolicy,
) -> _ResolvedPeer:
    canonical = _headers(headers)
    try:
        peer = _parse_ip(metadata.immediate_peer)
    except ValueError as exc:
        raise IngressRejected(IngressRejectReason.UNTRUSTED_GATEWAY, 403) from exc

    peer_is_trusted_proxy = _in_networks(peer, policy.trusted_proxy_cidrs)
    if policy.required_peer_identities and (
        metadata.peer_identity not in policy.required_peer_identities
    ):
        raise IngressRejected(IngressRejectReason.UNTRUSTED_GATEWAY, 403)
    if not peer_is_trusted_proxy and not policy.allow_direct_peers:
        raise IngressRejected(IngressRejectReason.UNTRUSTED_GATEWAY, 403)

    if not peer_is_trusted_proxy:
        client = peer
        tls_verified = bool(metadata.transport_tls)
        chain: tuple[str, ...] = ()
    else:
        forwarded_values: list[str] = []
        forwarded_proto: str | None = None
        if canonical.get("forwarded"):
            forwarded_values, forwarded_proto = _parse_forwarded_for(
                canonical["forwarded"]
            )
        xff_values = (
            _parse_x_forwarded_for(canonical["x-forwarded-for"])
            if canonical.get("x-forwarded-for")
            else []
        )
        if forwarded_values and xff_values and forwarded_values != xff_values:
            raise IngressRejected(IngressRejectReason.AMBIGUOUS_FORWARDED_CHAIN, 400)
        supplied = forwarded_values or xff_values
        if len(supplied) + 1 > policy.forwarded_hop_limit:
            raise IngressRejected(IngressRejectReason.FORWARDED_CHAIN_TOO_LONG, 400)
        chain = tuple([*supplied, str(peer)])

        remaining = [_parse_ip(item) for item in chain]
        while remaining and _in_networks(remaining[-1], policy.trusted_proxy_cidrs):
            remaining.pop()
        client = remaining[-1] if remaining else peer

        xfp = canonical.get("x-forwarded-proto")
        if xfp:
            xfp = xfp.split(",")[-1].strip().lower()
        effective_proto = forwarded_proto or xfp
        tls_verified = bool(metadata.transport_tls) or effective_proto == "https"

    if policy.require_tls and not tls_verified:
        raise IngressRejected(IngressRejectReason.TLS_REQUIRED, 403)
    if policy.allowed_source_cidrs and not _in_networks(
        client, policy.allowed_source_cidrs
    ):
        raise IngressRejected(IngressRejectReason.SOURCE_NETWORK_DENIED, 403)

    return _ResolvedPeer(
        immediate_peer=str(peer),
        client_ip=str(client),
        trusted_proxy_chain=chain,
        tls_verified=tls_verified,
    )


def _select_credential(
    headers: Mapping[str, str],
    policy: IngressGatewayPolicy,
    utc_ns: int,
) -> CredentialBinding:
    observed = _headers(headers).get("authorization")
    if not observed:
        raise IngressRejected(IngressRejectReason.MISSING_CREDENTIAL, 401)

    matches: list[CredentialBinding] = []
    for credential in policy.credentials:
        if hmac.compare_digest(observed, credential.authorization):
            matches.append(credential)
    if len(matches) != 1:
        raise IngressRejected(IngressRejectReason.INVALID_CREDENTIAL, 401)

    credential = matches[0]
    if credential.state is CredentialState.REVOKED:
        raise IngressRejected(IngressRejectReason.CREDENTIAL_REVOKED, 401)
    if not credential.accepts_requests or not credential.valid_at(utc_ns):
        raise IngressRejected(IngressRejectReason.CREDENTIAL_NOT_ACTIVE, 401)
    return credential


def authenticate_inbound_request(
    *,
    policy: IngressGatewayPolicy,
    headers: Mapping[str, str],
    raw_body: bytes,
    metadata: IngressConnectionMetadata,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
    utc_ns: Callable[[], int] = time.time_ns,
) -> InboundRequestContext:
    if metadata.config_generation != policy.config_generation:
        raise IngressRejected(IngressRejectReason.CONFIG_GENERATION_MISMATCH, 403)
    if (
        metadata.observed_webhook_id is not None
        and metadata.observed_webhook_id != policy.expected_webhook_id
    ):
        raise IngressRejected(IngressRejectReason.WEBHOOK_ID_MISMATCH, 403)

    received_utc_ns = metadata.received_utc_ns or utc_ns()
    received_monotonic_ns = metadata.received_monotonic_ns or monotonic_ns()
    resolved = _resolve_peer(headers, metadata, policy)
    credential = _select_credential(headers, policy, received_utc_ns)
    return InboundRequestContext(
        immediate_peer=resolved.immediate_peer,
        client_ip=resolved.client_ip,
        trusted_proxy_chain=resolved.trusted_proxy_chain,
        tls_verified=resolved.tls_verified,
        peer_identity=metadata.peer_identity,
        webhook_id=policy.expected_webhook_id,
        config_generation=policy.config_generation,
        credential_id=credential.credential_id,
        credential_version=credential.version,
        network=policy.network,
        webhook_type=policy.webhook_type,
        received_monotonic_ns=received_monotonic_ns,
        received_utc_ns=received_utc_ns,
        body_digest=hashlib.sha256(raw_body).hexdigest(),
        provider_delivery_id=metadata.provider_delivery_id,
    )


def install_authenticated_ingress(delivery_module: ModuleType) -> None:
    """Install the PR-199 boundary onto the already-imported delivery module."""

    if getattr(delivery_module, "_PR199_AUTHENTICATED_INGRESS_INSTALLED", False):
        return

    base_plane = delivery_module.HeliusDeliveryPlane
    schema_version = getattr(delivery_module, "SCHEMA_VERSION", "helius-delivery")

    class AuthenticatedHeliusDeliveryPlane(base_plane):
        """PR-188 delivery plane with a server-owned PR-199 ingress identity."""

        def __init__(
            self,
            config: Any,
            *,
            ingress_policy: IngressGatewayPolicy | None = None,
            clock_monotonic_ns: Callable[[], int] = time.monotonic_ns,
            monotonic_ns: Callable[[], int] | None = None,
        ) -> None:
            super().__init__(
                config,
                clock_monotonic_ns=clock_monotonic_ns,
                monotonic_ns=monotonic_ns,
            )
            self._ingress_policy_lock = threading.RLock()
            self._ingress_policy = ingress_policy
            self.last_request_context: InboundRequestContext | None = None
            if ingress_policy is not None:
                self._validate_policy_binding(ingress_policy)
                self._ensure_ingress_audit_schema()

        @property
        def ingress_policy(self) -> IngressGatewayPolicy | None:
            with self._ingress_policy_lock:
                return self._ingress_policy

        def replace_ingress_policy(self, policy: IngressGatewayPolicy) -> None:
            """Atomically activate a new generation/rotation policy."""

            self._validate_policy_binding(policy)
            self._ensure_ingress_audit_schema()
            with self._ingress_policy_lock:
                self._ingress_policy = policy

        def _validate_policy_binding(self, policy: IngressGatewayPolicy) -> None:
            if policy.expected_webhook_id != self.config.webhook_id:
                raise ValueError("ingress policy webhook_id must match delivery config")
            if policy.network != self.config.cluster_genesis:
                raise ValueError("ingress policy network must match delivery config")

        def accept_delivery(
            self,
            *,
            headers: Mapping[str, str],
            raw_body: bytes,
            webhook_id: str | None = None,
            request_metadata: IngressConnectionMetadata | None = None,
            started_monotonic_ns: int | None = None,
        ) -> Any:
            started_ns = (
                self._monotonic_ns()
                if started_monotonic_ns is None
                else started_monotonic_ns
            )
            with self._ingress_policy_lock:
                policy = self._ingress_policy

            observed_ids = {
                value
                for value in (
                    webhook_id,
                    (
                        request_metadata.observed_webhook_id
                        if request_metadata is not None
                        else None
                    ),
                )
                if value is not None
            }
            if any(value != self.config.webhook_id for value in observed_ids):
                return self._pr199_reject(
                    IngressRejectReason.WEBHOOK_ID_MISMATCH, 403, started_ns
                )

            if policy is None:
                # Compatibility mode remains available to existing non-production
                # tests/callers, but identity is always server-owned.  Supplying a
                # different caller value can never create a new authority domain.
                return super().accept_delivery(
                    headers=headers,
                    raw_body=raw_body,
                    webhook_id=self.config.webhook_id,
                    started_monotonic_ns=started_ns,
                )

            if request_metadata is None:
                return self._pr199_reject(
                    IngressRejectReason.MISSING_REQUEST_METADATA, 403, started_ns
                )
            try:
                context = authenticate_inbound_request(
                    policy=policy,
                    headers=headers,
                    raw_body=raw_body,
                    metadata=request_metadata,
                    monotonic_ns=self._monotonic_ns,
                )
                self._reject_provider_delivery_conflict(context)
            except IngressRejected as exc:
                return self._pr199_reject(exc.reason, exc.status_code, started_ns)
            except (sqlite3.DatabaseError, ValueError):
                return self._pr199_reject(
                    IngressRejectReason.INGRESS_AUDIT_STORE_ERROR,
                    503,
                    started_ns,
                )

            # PR-188 verifies its configured primary value.  PR-199 has already
            # selected an active/overlap credential, so delegate with the private
            # configured value rather than weakening the base verifier.
            delegated_headers = _headers(headers)
            delegated_headers["authorization"] = self.config.auth_header
            outcome = super().accept_delivery(
                headers=delegated_headers,
                raw_body=raw_body,
                webhook_id=self.config.webhook_id,
                started_monotonic_ns=started_ns,
            )
            if outcome.acknowledged:
                try:
                    self._record_request_context(
                        context, outcome.delivery_id, started_ns
                    )
                except (sqlite3.DatabaseError, ValueError):
                    return self._pr199_reject(
                        IngressRejectReason.INGRESS_AUDIT_STORE_ERROR,
                        503,
                        started_ns,
                        payload_hash=outcome.payload_hash,
                    )
                self.last_request_context = context
            return outcome

        def _pr199_reject(
            self,
            reason: IngressRejectReason,
            status_code: int,
            started_ns: int,
            *,
            payload_hash: str | None = None,
        ) -> Any:
            return delivery_module.DeliveryOutcome(
                schema_version,
                delivery_module.DeliveryDecision.REJECTED,
                status_code,
                reason.value,
                None,
                0,
                0,
                payload_hash,
                False,
                False,
                self._elapsed_ms(started_ns),
            )

        def _connection(self, *, deadline_ns: int | None = None) -> sqlite3.Connection:
            connector = getattr(self.store, "_connect", None)
            if callable(connector):
                return connector(
                    deadline_ns=deadline_ns,
                    monotonic_ns=self._monotonic_ns,
                )
            return sqlite3.connect(str(self.store.path), timeout=0.25)

        def _ensure_ingress_audit_schema(self) -> None:
            with self._connection() as con:
                con.executescript("""
                    CREATE TABLE IF NOT EXISTS helius_inbound_request (
                        request_id TEXT PRIMARY KEY,
                        delivery_id TEXT,
                        webhook_id TEXT NOT NULL,
                        config_generation TEXT NOT NULL,
                        credential_id TEXT NOT NULL,
                        credential_version TEXT NOT NULL,
                        immediate_peer TEXT NOT NULL,
                        client_ip TEXT NOT NULL,
                        trusted_proxy_chain_json TEXT NOT NULL,
                        tls_verified INTEGER NOT NULL,
                        peer_identity TEXT,
                        network TEXT NOT NULL,
                        webhook_type TEXT NOT NULL,
                        body_digest TEXT NOT NULL,
                        provider_delivery_id TEXT,
                        received_monotonic_ns INTEGER NOT NULL,
                        received_utc_ns INTEGER NOT NULL,
                        provider_origin_cryptographically_proven INTEGER NOT NULL
                            DEFAULT 0
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS
                        uq_helius_inbound_provider_delivery
                    ON helius_inbound_request(
                        webhook_id, config_generation, provider_delivery_id
                    )
                    WHERE provider_delivery_id IS NOT NULL;
                    """)

        def _reject_provider_delivery_conflict(
            self, context: InboundRequestContext
        ) -> None:
            if context.provider_delivery_id is None:
                return
            with self._connection() as con:
                row = con.execute(
                    "SELECT body_digest FROM helius_inbound_request"
                    " WHERE webhook_id = ? AND config_generation = ?"
                    " AND provider_delivery_id = ?",
                    (
                        context.webhook_id,
                        context.config_generation,
                        context.provider_delivery_id,
                    ),
                ).fetchone()
            if row is not None and str(row[0]) != context.body_digest:
                raise IngressRejected(
                    IngressRejectReason.DELIVERY_METADATA_CONFLICT, 409
                )

        def _record_request_context(
            self,
            context: InboundRequestContext,
            delivery_id: str | None,
            started_ns: int,
        ) -> None:
            deadline_ns = (
                started_ns + self.config.limits.delivery_deadline_ms * 1_000_000
            )
            if self._monotonic_ns() >= deadline_ns:
                raise ValueError("ingress audit deadline exceeded")
            request_material = "\0".join(
                (
                    "pr199.inbound-request.v1",
                    context.webhook_id,
                    context.config_generation,
                    context.provider_delivery_id or "",
                    context.body_digest,
                    str(context.received_monotonic_ns),
                )
            )
            request_id = hashlib.sha256(request_material.encode()).hexdigest()
            with self._connection(deadline_ns=deadline_ns) as con:
                con.execute(
                    "INSERT OR IGNORE INTO helius_inbound_request ("
                    "request_id, delivery_id, webhook_id, config_generation,"
                    "credential_id, credential_version, immediate_peer, client_ip,"
                    "trusted_proxy_chain_json, tls_verified, peer_identity, network,"
                    "webhook_type, body_digest, provider_delivery_id,"
                    "received_monotonic_ns, received_utc_ns,"
                    "provider_origin_cryptographically_proven"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                    (
                        request_id,
                        delivery_id,
                        context.webhook_id,
                        context.config_generation,
                        context.credential_id,
                        context.credential_version,
                        context.immediate_peer,
                        context.client_ip,
                        json.dumps(context.trusted_proxy_chain),
                        int(context.tls_verified),
                        context.peer_identity,
                        context.network,
                        context.webhook_type,
                        context.body_digest,
                        context.provider_delivery_id,
                        context.received_monotonic_ns,
                        context.received_utc_ns,
                    ),
                )

        def inbound_request_count(self) -> int:
            self._ensure_ingress_audit_schema()
            with self._connection() as con:
                return int(
                    con.execute(
                        "SELECT COUNT(*) FROM helius_inbound_request"
                    ).fetchone()[0]
                )

        def request_context_for_delivery(
            self, delivery_id: str
        ) -> Mapping[str, Any] | None:
            self._ensure_ingress_audit_schema()
            with self._connection() as con:
                row = con.execute(
                    "SELECT webhook_id, config_generation, credential_id,"
                    " credential_version, immediate_peer, client_ip,"
                    " trusted_proxy_chain_json, tls_verified, peer_identity,"
                    " network, webhook_type, body_digest, provider_delivery_id,"
                    " received_monotonic_ns, received_utc_ns,"
                    " provider_origin_cryptographically_proven"
                    " FROM helius_inbound_request WHERE delivery_id = ?"
                    " ORDER BY received_monotonic_ns DESC LIMIT 1",
                    (delivery_id,),
                ).fetchone()
            if row is None:
                return None
            return {
                "webhook_id": str(row[0]),
                "config_generation": str(row[1]),
                "credential_id": str(row[2]),
                "credential_version": str(row[3]),
                "immediate_peer": str(row[4]),
                "client_ip": str(row[5]),
                "trusted_proxy_chain": tuple(json.loads(str(row[6]))),
                "tls_verified": bool(row[7]),
                "peer_identity": row[8],
                "network": str(row[9]),
                "webhook_type": str(row[10]),
                "body_digest": str(row[11]),
                "provider_delivery_id": row[12],
                "received_monotonic_ns": int(row[13]),
                "received_utc_ns": int(row[14]),
                "provider_origin_cryptographically_proven": bool(row[15]),
            }

    AuthenticatedHeliusDeliveryPlane.__name__ = "HeliusDeliveryPlane"
    AuthenticatedHeliusDeliveryPlane.__qualname__ = "HeliusDeliveryPlane"
    AuthenticatedHeliusDeliveryPlane.__module__ = delivery_module.__name__
    delivery_module.HeliusDeliveryPlane = AuthenticatedHeliusDeliveryPlane
    delivery_module._PR199_AUTHENTICATED_INGRESS_INSTALLED = True


__all__ = [
    "CredentialBinding",
    "CredentialState",
    "InboundRequestContext",
    "IngressConnectionMetadata",
    "IngressGatewayPolicy",
    "IngressRejectReason",
    "IngressRejected",
    "authenticate_inbound_request",
    "install_authenticated_ingress",
]
