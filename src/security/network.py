"""Deny-by-default URL admission for residual operator and tooling paths."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from urllib.parse import urlsplit


class NetworkSecurityError(ValueError):
    """A URL is not permitted by the explicit network policy."""


@dataclass(frozen=True, slots=True)
class UrlPolicy:
    allowed_hosts: frozenset[str]
    allowed_ports: frozenset[int] = frozenset({443})
    require_https: bool = True


def _reject_address(host: str) -> None:
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return
    if not address.is_global:
        raise NetworkSecurityError("non-global literal IP addresses are forbidden")


def validate_url(url: str, *, policy: UrlPolicy) -> str:
    if len(url) > 2048:
        raise NetworkSecurityError("URL exceeds length limit")
    parsed = urlsplit(url)
    if policy.require_https and parsed.scheme != "https":
        raise NetworkSecurityError("only HTTPS URLs are permitted")
    if parsed.username is not None or parsed.password is not None:
        raise NetworkSecurityError("credentials in URLs are forbidden")
    if parsed.fragment:
        raise NetworkSecurityError("URL fragments are forbidden")
    if not parsed.hostname:
        raise NetworkSecurityError("URL host is required")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        raise NetworkSecurityError("localhost destinations are forbidden")
    _reject_address(host)
    if host not in policy.allowed_hosts:
        raise NetworkSecurityError("URL host is not allowlisted")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in policy.allowed_ports:
        raise NetworkSecurityError("URL port is not allowlisted")
    return parsed.geturl()
