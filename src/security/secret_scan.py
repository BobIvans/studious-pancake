"""Offline plaintext key-material detection used by PR-043/PR-112 gates.

The scanner is intentionally conservative and value-redacting. It is not a
replacement for a hosted secret-scanning product; it is a deterministic local
fail-closed guard for the production runtime surface, fixtures, logs, and
operator-provided configuration snippets.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
import re
from typing import Mapping

_REFERENCE_RE = re.compile(r"^(env|file|keychain):.+$")
_ENV_TEMPLATE_RE = re.compile(
    r"^(?:os\.environ/[A-Z][A-Z0-9_]{1,80}|\$\{[A-Z][A-Z0-9_]{1,80}\})$"
)
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
    r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{80,120}" r"(?![1-9A-HJ-NP-Za-km-z])"
)
_PROVIDER_TOKEN_RES = (
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)xox[baprs]-[0-9A-Za-z-]{20,}"),
    re.compile(r"(?i)gh[pousr]_[0-9A-Za-z_]{20,}"),
)
_SECRET_NAME_HINTS = (
    "PRIVATE_KEY",
    "SECRET_KEY",
    "KEYPAIR",
    "SIGNER_KEY",
    "PHANTOM",
    "WALLET_SECRET",
)
_CREDENTIAL_NAME_RE = re.compile(
    r"(?i)(?:^|[_\-.])(?:api[_-]?key|access[_-]?token|auth[_-]?token|"
    r"bearer[_-]?token|client[_-]?secret|secret|passphrase|password)(?:$|[_\-.])"
)
_SECRET_METADATA_NAME_RE = re.compile(
    r"(?i)(?:secret|credential|token|auth)[_-]?(?:locator|reference|ref|domain)"
    r"|(?:locator|reference|ref|domain)[_-]?(?:secret|credential|token|auth)"
)
_CONTEXT_KEY_HINT_RE = re.compile(
    r"(?i)(private[_-]?key|secret[_-]?key|keypair|signer[_-]?key|phantom)\s*[:=]"
)
_SECRET_FIELD_ASSIGNMENT_RE = re.compile(
    r"""
    ^\s*
    (?P<name>["']?[A-Za-z0-9_.-]*
      (?:api[_-]?key|access[_-]?token|auth[_-]?token|bearer[_-]?token|
         client[_-]?secret|secret|passphrase|password)
      [A-Za-z0-9_.-]*["']?)
    \s*[:=]\s*
    (?P<value>.+?)
    \s*(?:\#.*)?$
    """,
    re.IGNORECASE | re.VERBOSE,
)
_SAFE_LITERAL_VALUES = {
    "",
    "null",
    "none",
    "false",
    "true",
    "redacted",
    "<redacted>",
    "[redacted]",
    "changeme",
    "change-me",
    "replace-me",
    "your-api-key",
    "your_api_key",
    "example",
    "example-value",
    "dummy",
    "placeholder",
}
_SAFE_REFERENCE_NAMES = {
    "credential",
    "env_value",
    "key",
    "provider_token_shape",
    "reference",
    "secret",
    "token",
    "value",
}


class PlaintextKeyMaterialError(ValueError):
    """Raised when plaintext wallet/signing key or provider credential material is found."""


@dataclass(frozen=True, slots=True)
class SecretScanFinding:
    """Redacted key-material finding."""

    source: str
    reason: str
    name: str | None = None

    def redacted_message(self) -> str:
        location = self.source if self.name is None else f"{self.source}:{self.name}"
        return f"{location}: {self.reason}"


def _strip_literal(value: str) -> str:
    cleaned = value.strip().rstrip(",")
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        cleaned = cleaned[1:-1]
    return cleaned.strip()


def _looks_like_reference(value: str) -> bool:
    stripped = _strip_literal(value)
    return bool(
        _REFERENCE_RE.fullmatch(stripped) or _ENV_TEMPLATE_RE.fullmatch(stripped)
    )


def _name_is_secret_metadata(name: str | None) -> bool:
    if name is None:
        return False
    return bool(_SECRET_METADATA_NAME_RE.search(name.strip("'\"")))


def _name_suggests_key_material(name: str | None) -> bool:
    if name is None or _name_is_secret_metadata(name):
        return False
    upper_name = name.upper()
    return any(hint in upper_name for hint in _SECRET_NAME_HINTS)


def _name_suggests_credential(name: str | None) -> bool:
    if name is None or _name_is_secret_metadata(name):
        return False
    return bool(_CREDENTIAL_NAME_RE.search(name))


def _has_provider_token_shape(value: str) -> bool:
    return any(pattern.search(value) for pattern in _PROVIDER_TOKEN_RES)


def _has_high_entropy_shape(value: str) -> bool:
    stripped = _strip_literal(value)
    if len(stripped) < 20 or any(char.isspace() for char in stripped):
        return False
    alphabet = set(stripped)
    has_alpha = any(char.isalpha() for char in stripped)
    has_digit = any(char.isdigit() for char in stripped)
    has_symbol = any(char in "_-./+=" for char in stripped)
    return len(alphabet) >= 10 and has_alpha and (has_digit or has_symbol)


def _literal_atom_is_secret(value: str) -> bool:
    stripped = _strip_literal(value)
    lowered = stripped.lower()
    if lowered in _SAFE_LITERAL_VALUES:
        return False
    if _looks_like_reference(stripped):
        return False
    if stripped.startswith(("<", "${")) or stripped.endswith(">"):
        return False
    if stripped.upper().startswith(("REPLACE_", "YOUR_", "EXAMPLE_", "DUMMY_")):
        return False
    return _has_provider_token_shape(stripped) or _has_high_entropy_shape(stripped)


def _is_safe_reference_expression(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id in _SAFE_REFERENCE_NAMES or node.id.endswith(
            ("_value", "_token", "_secret", "_key", "_reference", "_ref", "_shape")
        )
    if isinstance(node, ast.Attribute):
        return _is_safe_reference_expression(node.value)
    if isinstance(node, ast.Subscript):
        return _is_safe_reference_expression(node.value)
    if isinstance(node, ast.Call):
        return _is_safe_reference_expression(node.func)
    return False


def _expression_contains_secret_literal(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            if _literal_atom_is_secret(child.value):
                return True
    return False


def _literal_secret_value(value: str) -> bool:
    stripped = value.strip().rstrip(",")
    try:
        expression = ast.parse(stripped, mode="eval")
    except (SyntaxError, ValueError):
        return _literal_atom_is_secret(stripped)
    if not isinstance(expression, ast.Expression):
        return _literal_atom_is_secret(stripped)
    parsed = expression.body
    if _is_safe_reference_expression(parsed):
        return _expression_contains_secret_literal(parsed)
    return _literal_atom_is_secret(stripped)


def _scan_secret_field_assignments(
    text: str, *, source: str
) -> list[SecretScanFinding]:
    findings: list[SecretScanFinding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = _SECRET_FIELD_ASSIGNMENT_RE.match(line)
        if not match:
            continue
        raw_name = match.group("name").strip("'\"")
        if _name_is_secret_metadata(raw_name):
            continue
        if _literal_secret_value(match.group("value")):
            findings.append(
                SecretScanFinding(
                    source=f"{source}:{line_number}",
                    name=raw_name,
                    reason="literal credential in secret-named field",
                )
            )
    return findings


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
    if _has_provider_token_shape(text):
        findings.append(
            SecretScanFinding(
                source=source,
                name=name,
                reason="provider API token shaped value",
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
    if _name_suggests_credential(name) and _literal_secret_value(stripped):
        findings.append(
            SecretScanFinding(
                source=source,
                name=name,
                reason="literal credential in secret-named field",
            )
        )
    findings.extend(_scan_secret_field_assignments(text, source=source))

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
    """Fail closed when plaintext signing key or provider credential material is present."""

    if isinstance(values, str):
        findings = scan_text_for_key_material(values, source=source)
    else:
        findings = scan_mapping_for_key_material(values, source=source)
    if findings:
        reasons = "; ".join(finding.redacted_message() for finding in findings)
        raise PlaintextKeyMaterialError(
            "plaintext wallet/signing key material or provider credential material is "
            "forbidden: " + reasons
        )
