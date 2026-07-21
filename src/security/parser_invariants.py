"""Parser invariant taxonomy and assertion-free validation helpers for PR-126.

The module is deliberately assert-free. Production validation must survive
``python -O`` because optimized mode removes ``assert`` statements before code
runs. These helpers provide typed, category-preserving failures for parser and
security boundaries while keeping diagnostic output free of raw payload values.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path
from typing import Any, cast


class ErrorCategory(StrEnum):
    """PR-126 cross-cutting parser/runtime error taxonomy."""

    PROVIDER_BUSINESS_ERROR = "provider-business-error"
    TRANSPORT_ERROR = "transport-error"
    SCHEMA_DRIFT = "schema-drift"
    PROTOCOL_REJECTION = "protocol-rejection"
    PROGRAMMER_INVARIANT_VIOLATION = "programmer-invariant-violation"
    SECURITY_VIOLATION = "security-violation"


class ParserInvariantError(ValueError):
    """Raised when parser validation fails without relying on ``assert``."""

    def __init__(
        self,
        message: str,
        *,
        category: ErrorCategory,
        source: str | None = None,
    ) -> None:
        self.category = category
        self.source = source
        prefix = f"{source}: " if source else ""
        super().__init__(prefix + message)


@dataclass(frozen=True, slots=True)
class ParserInvariantFinding:
    """Redacted source finding for assert and broad-exception debt."""

    path: str
    line: int
    code: str
    reason: str

    def redacted_message(self) -> str:
        return f"{self.path}:{self.line}: {self.code}: {self.reason}"


def require_invariant(
    condition: bool,
    message: str,
    *,
    category: ErrorCategory = ErrorCategory.PROGRAMMER_INVARIANT_VIOLATION,
    source: str | None = None,
) -> None:
    """Fail closed when a parser invariant is false.

    This is the PR-126 replacement for validation that might otherwise be
    expressed as ``assert condition``. It is a normal branch and is therefore
    still active under optimized Python mode.
    """

    if not condition:
        raise ParserInvariantError(message, category=category, source=source)


def parse_json_object_payload(
    payload: str | bytes,
    *,
    source: str,
    max_bytes: int = 1_000_000,
) -> dict[str, object]:
    """Parse a bounded JSON object or raise a categorized redacted failure."""

    raw_size = len(payload)
    require_invariant(
        raw_size <= max_bytes,
        "json payload exceeds configured parser budget",
        category=ErrorCategory.SECURITY_VIOLATION,
        source=source,
    )
    if isinstance(payload, bytes):
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ParserInvariantError(
                "json payload is not valid utf-8",
                category=ErrorCategory.SCHEMA_DRIFT,
                source=source,
            ) from exc
    else:
        text = payload

    try:
        decoded: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParserInvariantError(
            "json payload is not valid json",
            category=ErrorCategory.SCHEMA_DRIFT,
            source=source,
        ) from exc

    require_invariant(
        isinstance(decoded, dict),
        "json payload top-level value must be an object",
        category=ErrorCategory.SCHEMA_DRIFT,
        source=source,
    )
    return cast(dict[str, object], decoded)


def _is_broad_exception_type(node: ast.ExceptHandler) -> bool:
    if node.type is None:
        return True
    if isinstance(node.type, ast.Name):
        return node.type.id in {"BaseException", "Exception"}
    return False


def _line_has_broad_exception_justification(
    source_lines: tuple[str, ...],
    line_number: int,
) -> bool:
    start = max(0, line_number - 3)
    end = min(len(source_lines), line_number + 1)
    window = "\n".join(source_lines[start:end]).lower()
    return "pr126: allow-broad-except" in window


def scan_python_source_for_invariant_debt(
    source: str,
    *,
    path: str,
) -> tuple[ParserInvariantFinding, ...]:
    """Return redacted PR-126 findings for Python source text."""

    findings: list[ParserInvariantFinding] = []
    source_lines = tuple(source.splitlines())
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return (
            ParserInvariantFinding(
                path=path,
                line=exc.lineno or 1,
                code="PR126-SYNTAX",
                reason="source could not be parsed for invariant scanning",
            ),
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            findings.append(
                ParserInvariantFinding(
                    path=path,
                    line=node.lineno,
                    code="PR126-ASSERT",
                    reason="production parser validation must not rely on assert",
                )
            )
        if isinstance(node, ast.ExceptHandler) and _is_broad_exception_type(node):
            if _line_has_broad_exception_justification(source_lines, node.lineno):
                continue
            findings.append(
                ParserInvariantFinding(
                    path=path,
                    line=node.lineno,
                    code="PR126-BROAD-EXCEPT",
                    reason="broad exception handler requires explicit PR-126 justification",
                )
            )
    return tuple(findings)


def scan_python_paths_for_invariant_debt(
    paths: tuple[Path, ...],
) -> tuple[ParserInvariantFinding, ...]:
    """Scan known Python paths without executing their contents."""

    findings: list[ParserInvariantFinding] = []
    for path in paths:
        findings.extend(
            scan_python_source_for_invariant_debt(
                path.read_text(encoding="utf-8"),
                path=path.as_posix(),
            )
        )
    return tuple(findings)


def assert_no_parser_invariant_debt(
    findings: tuple[ParserInvariantFinding, ...],
) -> None:
    """Raise a categorized error if the scanner found unaccepted debt."""

    if not findings:
        return
    message = "; ".join(finding.redacted_message() for finding in findings)
    raise ParserInvariantError(
        message,
        category=ErrorCategory.PROGRAMMER_INVARIANT_VIOLATION,
    )
