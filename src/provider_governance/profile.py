"""Bounded offline connection profiles: reviewed references, never secret material."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ipaddress
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Any, NoReturn, Sequence
from urllib.parse import urlsplit

from src.contracts.registry import (
    get_schema_registry,
    SchemaRegistryError,
    PayloadLimits,
)
from .models import ProviderEntitlement, ProviderOperation

SCHEMA_VERSION = "mpr2602.connections.v1"
_KNOWN_PROVIDERS = frozenset(
    {"jupiter_router", "okx_dex", "openocean", "odos", "solana_rpc", "helius_rpc"}
)


class ConnectionProfileError(ValueError):
    """Only bounded reason codes are exposed; never include supplied values."""


@dataclass(frozen=True)
class ConnectionProfile:
    entitlements: Mapping[str, ProviderEntitlement]
    credential_bindings: Mapping[str, tuple[str, str]]
    credential_env_names: Mapping[str, str]
    statuses: tuple[tuple[str, str], ...]
    profile_sha256: str


def _deny(reason: str) -> NoReturn:
    raise ConnectionProfileError(reason)


def _pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            _deny("duplicate_field")
        result[key] = value
    return result


def _constant(value: str) -> NoReturn:
    _deny("non_integer_number")


def _preflight(raw: bytes, limits: PayloadLimits) -> str:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError:
        _deny("utf8_invalid")
    depth = 0
    quoted = escaped = False
    length = 0
    for char in text:
        if quoted:
            if char == '"' and not escaped:
                quoted = False
            else:
                length += 1
                if length > limits.max_string_length:
                    _deny("string_limit")
            escaped = char == "\\" and not escaped
        elif char == '"':
            quoted = True
            length = 0
        elif char in "[{":
            depth += 1
            if depth > limits.max_depth:
                _deny("depth_limit")
        elif char in "]}":
            depth -= 1
    return text


def load_connection_profile(path: str | Path) -> ConnectionProfile:
    """Read one bounded JSON profile without loading ENV values or making effects."""
    registry = get_schema_registry()
    limits = registry.require(SCHEMA_VERSION).limits
    try:
        with Path(path).open("rb") as handle:
            raw = handle.read(limits.max_bytes + 1)
    except OSError:
        raise ConnectionProfileError("profile_unreadable") from None
    if len(raw) > limits.max_bytes:
        _deny("byte_limit")
    text = _preflight(raw, limits)
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_float=_constant,
            parse_constant=_constant,
        )
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        if isinstance(exc, ConnectionProfileError):
            raise
        raise ConnectionProfileError("json_invalid") from None
    try:
        canonical_payload = registry.validate_payload(SCHEMA_VERSION, payload)
    except SchemaRegistryError:
        raise ConnectionProfileError("registered_schema_invalid") from None
    connections = payload["connections"]
    entitlements = {}
    bindings = {}
    env_names = {}
    statuses = []
    seen = set()
    for item in connections:
        provider = item["provider_id"]
        if provider in seen:
            _deny("provider_duplicate")
        seen.add(provider)
        endpoint = item["endpoint"]
        if not isinstance(endpoint, str) or any(ord(char) < 33 for char in endpoint):
            _deny("endpoint_invalid")
        try:
            parsed = urlsplit(endpoint)
        except ValueError:
            _deny("endpoint_invalid")
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            _deny("endpoint_credentials_or_query")
        http_methods = frozenset(item["http_methods"])
        rpc_methods = frozenset(item["rpc_methods"])
        query_parameters = frozenset(item["query_parameters"])
        if any(
            "".join(c for c in key.lower() if c.isalnum())
            in {
                "apikey",
                "key",
                "token",
                "accesstoken",
                "authorization",
                "secret",
                "password",
                "signature",
            }
            for key in query_parameters
        ):
            _deny("credential_query_forbidden")
        if item["kind"] == "outbound_rest" and rpc_methods:
            _deny("kind_scope_invalid")
        credential = item["credential"]
        if credential is not None:
            if any(
                word in credential["env_name"]
                for word in ("PRIVATE_KEY", "SEED", "MNEMONIC", "SIGNER", "TRADING_KEY")
            ):
                _deny("signing_credential_forbidden")
        limits = item["entitlement"]
        operations = (
            frozenset(limits["operations"]) if limits is not None else frozenset()
        )
        if item["kind"] == "inbound_webhook":
            status = "disabled_inbound_unimplemented"
        elif provider not in _KNOWN_PROVIDERS:
            status = "disabled_unknown_provider"
        elif not item["enabled"]:
            status = "disabled"
        elif not item["reviewed"]:
            status = "disabled_unreviewed"
        else:
            status = "reviewed_reference_only"
        statuses.append((provider, status))
        if status != "reviewed_reference_only":
            continue
        if (
            limits is None
            or credential is None
            or item["review_ref"] is None
            or item["quota_pool_ref"] is None
        ):
            _deny("reviewed_profile_incomplete")
        if parsed.scheme != "https" or not parsed.hostname or not http_methods:
            _deny("reviewed_endpoint_invalid")
        if parsed.hostname.endswith(".invalid") or parsed.hostname == "localhost":
            _deny("placeholder_endpoint_denied")
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            _deny("private_endpoint_denied")
        if item["kind"] == "outbound_rpc" and (
            not rpc_methods or http_methods != frozenset({"POST"})
        ):
            _deny("rpc_scope_missing")
        try:
            entitlements[provider] = ProviderEntitlement(
                provider_id=provider,
                generation=limits["generation"],
                allowed_operations=frozenset(ProviderOperation(x) for x in operations),
                window_seconds=limits["window_seconds"],
                request_limit=limits["request_limit"],
                cost_unit_limit=limits["cost_unit_limit"],
                spend_limit_micros=limits["spend_limit_micros"],
                max_concurrency=limits["max_concurrency"],
                expires_at_epoch_seconds=limits["expires_at_epoch_seconds"],
                source_ref=item["review_ref"],
                quota_pool_ref=item["quota_pool_ref"],
                spend_window_seconds=limits["spend_window_seconds"],
                allowed_endpoints=(endpoint,),
                allowed_http_methods=http_methods,
                allowed_rpc_methods=rpc_methods,
                allowed_query_parameters=query_parameters,
                credential_ref=credential["ref"],
                credential_generation=credential["generation"],
            )
        except ValueError:
            raise ConnectionProfileError("entitlement_invalid") from None
        bindings[provider] = (credential["ref"], credential["generation"])
        env_names[provider] = credential["env_name"]
    return ConnectionProfile(
        MappingProxyType(entitlements),
        MappingProxyType(bindings),
        MappingProxyType(env_names),
        tuple(statuses),
        hashlib.sha256(canonical_payload).hexdigest(),
    )


__all__ = ["ConnectionProfile", "ConnectionProfileError", "load_connection_profile"]
