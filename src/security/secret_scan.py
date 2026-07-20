"""Offline plaintext key-material detection used by PR-043 gates.

The scanner is intentionally conservative and value-redacting. It is not a
replacement for a hosted secret-scanning product; it is a deterministic local
fail-closed guard for the production runtime surface, fixtures, logs, and
operator-provided configuration snippets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
import re


_REFERENCE_RE = re.compile(r"^(env|file|keychain):.+$")
_PEM_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:OPENSSH |EC |RSA |DSA |ED25519 )?PRIVATE KEY-----"
)
_SECRET_JSON_FIELD_RE = re.compile(
    r'(?i)"(?:secretKey|privateKey|walletPrivateKey|keypair)"\s*:'
)
_JSON_KEYPAIR_ARRAY_RE = re.compile(
    r"\[(?:\s*(?:[0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\s*,)"
    r"{31,}\s*(?:[0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\s*\]"
)
_BASE58_SECRET_RE = re.compile(
    r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{80,120}"
    r"(?![1-9A-HJ-NP-Za-km-z])"
)
_SECRET_NAME_HINTS = (
    "PRIVATE_KEY",
    "SECRET_KEY",
    "KEYPAIR",
    "SIGNER_KEY",
    "PHANTOM",
    "WALLET_SECRET",
)
_CONTEXT_KEY_HINT_RE = re.compile(
    r"(?i)(private[_-]?key|secret[_-]?key|keypair|signer[_-]?key|phantom)\s*[:=]"
)


class PlaintextKeyMaterialError(ValueError):
    """Raised when plaintext wallet/signing key material is found."""


@dataclass(frozen=True, slots=True)
class SecretScanFinding:
    """Redacted key-material finding.

    The actual value is intentionally omitted so logs and test failures cannot
    leak the key material that triggered the guard.
    """

    source: str
    reason: str
    name: str | None = None

    def redacted_message(self) -> str:
        location = self.source if self.name is None else f"{self.source}:{self.name}"
        return f"{location}: {self.reason}"


def _looks_like_reference(value: str) -> bool:
    return bool(_REFERENCE_RE.fullmatch(value.strip()))


def _name_suggests_key_material(name: str | None) -> bool:
    if name is None:
        return False
    upper_name = name.upper()
    return any(hint in upper_name for hint in _SECRET_NAME_HINTS)


def scan_text_for_key_material(
    text: str,
    *,
    source: str,
    name: str | None = None,
) -> tuple[SecretScanFinding, ...]:
    """Return redacted findings for plaintext wallet/signing key material."""

    findings: list[SecretScanFinding] = []
    stripped = text.strip()
    if not stripped or _looks_like_reference(stripped):
        return ()

    if _PEM_PRIVATE_KEY_RE.search(text):
        findings.append(
            SecretScanFinding(source=source, name=name, reason="PEM private key block")
        )
    if _SECRET_JSON_FIELD_RE.search(text):
        findings.append(
            SecretScanFinding(source=source, name=name, reason="private-key JSON field")
        )
    if _JSON_KEYPAIR_ARRAY_RE.search(text):
        findings.append(
            SecretScanFinding(
                source=source,
                name=name,
                reason="Solana-style keypair byte array",
            )
        )
    if _BASE58_SECRET_RE.search(text) and (
        _name_suggests_key_material(name) or _CONTEXT_KEY_HINT_RE.search(text)
    ):
        findings.append(
            SecretScanFinding(
                source=source,
                name=name,
                reason="base58-sized private key material",
            )
        )
    if _name_suggests_key_material(name) and len(stripped) >= 20:
        findings.append(
            SecretScanFinding(
                source=source,
                name=name,
                reason="secret-shaped value in key-material field",
            )
        )

    deduped: dict[tuple[str, str | None, str], SecretScanFinding] = {}
    for finding in findings:
        deduped[(finding.source, finding.name, finding.reason)] = finding
    return tuple(deduped.values())


def scan_mapping_for_key_material(
    values: Mapping[str, str],
    *,
    source: str,
) -> tuple[SecretScanFinding, ...]:
    """Scan a string mapping such as env vars or parsed redacted logs."""

    findings: list[SecretScanFinding] = []
    for name, value in sorted(values.items()):
        findings.extend(
            scan_text_for_key_material(value, source=source, name=str(name))
        )
    return tuple(findings)


def assert_no_plaintext_key_material(
    values: Mapping[str, str] | str,
    *,
    source: str,
) -> None:
    """Fail closed when plaintext signing key material is present."""

    if isinstance(values, str):
        findings = scan_text_for_key_material(values, source=source)
    else:
        findings = scan_mapping_for_key_material(values, source=source)
    if findings:
        reasons = "; ".join(finding.redacted_message() for finding in findings)
        raise PlaintextKeyMaterialError(
            "plaintext wallet/signing key material is forbidden: " + reasons
        )
