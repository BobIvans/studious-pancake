"""MPR-NEXT-12 persistence authority and direct-DB-connect guard.

This module is intentionally sender-free and live-free.  It establishes the
repository policy that active runtime SQLite access must go through approved
persistence authorities/factories instead of ad-hoc ``sqlite3.connect`` or
``aiosqlite.connect`` calls spread across the product graph.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import ast
import fnmatch
import json
from importlib import resources
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

POLICY_SCHEMA = "mpr-next-12.persistence-authority-policy.v1"
REPORT_SCHEMA = "mpr-next-12.persistence-authority-report.v1"
_CONNECT_CALLS = frozenset({"sqlite3.connect", "aiosqlite.connect"})


class PersistenceAuthorityError(ValueError):
    """Raised when the MPR-NEXT-12 policy is malformed."""


@dataclass(frozen=True, slots=True)
class DirectConnectOccurrence:
    path: str
    line: int
    call: str
    classification: str
    approved: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PersistenceAuthorityReport:
    accepted: bool
    schema_version: str
    approved_factories: tuple[str, ...]
    occurrences: tuple[DirectConnectOccurrence, ...]
    blockers: tuple[str, ...]

    @property
    def total_occurrences(self) -> int:
        return len(self.occurrences)

    @property
    def unapproved_occurrences(self) -> int:
        return sum(not item.approved for item in self.occurrences)

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "schema_version": self.schema_version,
            "approved_factories": list(self.approved_factories),
            "total_occurrences": self.total_occurrences,
            "unapproved_occurrences": self.unapproved_occurrences,
            "blockers": list(self.blockers),
            "occurrences": [item.to_dict() for item in self.occurrences],
        }


def _load_default_policy() -> dict[str, Any]:
    path = resources.files("src.resources").joinpath(
        "persistence_authority_mpr_next_12.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _strings(payload: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise PersistenceAuthorityError(f"{key} must contain non-empty strings")
    return tuple(item.strip() for item in value)


def _policy_rows(payload: Mapping[str, Any], key: str) -> tuple[dict[str, str], ...]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise PersistenceAuthorityError(f"{key} must be a list")
    rows: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise PersistenceAuthorityError(f"{key} entries must be objects")
        row: dict[str, str] = {}
        for field in ("glob", "classification", "reason"):
            raw = item.get(field)
            if not isinstance(raw, str) or not raw.strip():
                raise PersistenceAuthorityError(f"{key}.{field} is required")
            row[field] = raw.strip()
        rows.append(row)
    return tuple(rows)


def validate_policy(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != POLICY_SCHEMA:
        raise PersistenceAuthorityError("unsupported persistence authority policy")
    approved_factories = _strings(payload, "approved_factories")
    if not approved_factories:
        raise PersistenceAuthorityError("at least one approved factory is required")
    allowed = _policy_rows(payload, "allowed_direct_connects")
    quarantined = _policy_rows(payload, "quarantined_direct_connects")
    blocked = _policy_rows(payload, "blocked_direct_connects")
    return {
        "schema_version": POLICY_SCHEMA,
        "approved_factories": approved_factories,
        "allowed_direct_connects": allowed,
        "quarantined_direct_connects": quarantined,
        "blocked_direct_connects": blocked,
    }


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        if parent:
            return f"{parent}.{node.attr}"
    return None


def _iter_python_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.py"):
        parts = set(path.parts)
        if parts & {".git", ".venv", "venv", "__pycache__", "build", "dist"}:
            continue
        yield path


def find_direct_connects(root: str | Path) -> tuple[tuple[str, int, str], ...]:
    base = Path(root)
    occurrences: list[tuple[str, int, str]] = []
    for path in sorted(_iter_python_files(base)):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        relative = path.relative_to(base).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            call = _call_name(node.func)
            if call in _CONNECT_CALLS:
                occurrences.append((relative, int(getattr(node, "lineno", 0)), call))
    return tuple(occurrences)


def _match(path: str, rows: Sequence[Mapping[str, str]]) -> Mapping[str, str] | None:
    for row in rows:
        if fnmatch.fnmatch(path, row["glob"]):
            return row
    return None


def _classify(
    path: str,
    *,
    allowed: Sequence[Mapping[str, str]],
    quarantined: Sequence[Mapping[str, str]],
    blocked: Sequence[Mapping[str, str]],
) -> tuple[str, bool, str]:
    blocked_row = _match(path, blocked)
    if blocked_row:
        return (blocked_row["classification"], False, blocked_row["reason"])
    allowed_row = _match(path, allowed)
    if allowed_row:
        return (allowed_row["classification"], True, allowed_row["reason"])
    quarantine_row = _match(path, quarantined)
    if quarantine_row:
        return (quarantine_row["classification"], False, quarantine_row["reason"])
    return ("active-runtime-unclassified", False, "direct DB connect is not approved")


def evaluate_persistence_authority(
    *,
    root: str | Path = ".",
    policy: Mapping[str, Any] | None = None,
    occurrences: Sequence[tuple[str, int, str]] | None = None,
) -> PersistenceAuthorityReport:
    validated = validate_policy(policy or _load_default_policy())
    raw_occurrences = tuple(occurrences) if occurrences is not None else find_direct_connects(root)
    rows: list[DirectConnectOccurrence] = []
    for path, line, call in raw_occurrences:
        classification, approved, reason = _classify(
            path,
            allowed=validated["allowed_direct_connects"],
            quarantined=validated["quarantined_direct_connects"],
            blocked=validated["blocked_direct_connects"],
        )
        rows.append(
            DirectConnectOccurrence(
                path=path,
                line=line,
                call=call,
                classification=classification,
                approved=approved,
                reason=reason,
            )
        )
    blockers = tuple(
        f"UNAPPROVED_DIRECT_CONNECT:{row.path}:{row.line}:{row.classification}"
        for row in rows
        if not row.approved
    )
    return PersistenceAuthorityReport(
        accepted=not blockers,
        schema_version=REPORT_SCHEMA,
        approved_factories=tuple(validated["approved_factories"]),
        occurrences=tuple(rows),
        blockers=blockers,
    )
