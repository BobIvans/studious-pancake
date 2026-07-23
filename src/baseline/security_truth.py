"""PR-152 baseline truth for import graph and security/quality gates.

This module is intentionally offline and side-effect free. It does not import
provider SDKs, read environment variables, touch wallets, call RPC endpoints,
sign, submit, or enable paper/live execution. It only describes and validates
the repository baseline evidence that must be true before deeper integration
PRs are trusted.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence


PR152_BASELINE_SCHEMA = "pr152.baseline-import-security-truth.v1"
PR152_BASELINE_HASH_DOMAIN = "flashloan-bot/pr152-baseline-truth"
_REQUIRED_GATE_IDS = frozenset(
    {
        "compileall",
        "quality-gate",
        "security-gate",
        "pytest-offline",
        "package-smoke",
    }
)
_QUARANTINED_IMPORT_PREFIXES = (
    "src.ingest.tx_builder",
    "src.execution.live_control",
)
_DIRECT_SIGNING_NAMES = frozenset({"Keypair"})
_DIRECT_SUBMISSION_MARKERS = (
    "sendTransaction",
    "send_transaction",
)
_SKIP_PREFLIGHT_RE = re.compile(r"skipPreflight['\"]?\s*[:=]\s*true", re.IGNORECASE)


class BaselineTruthError(ValueError):
    """Raised when PR-152 baseline metadata is incomplete or contradictory."""


class GateKind(StrEnum):
    IMPORT = "import"
    FORMAT = "format"
    TYPECHECK = "typecheck"
    SECURITY = "security"
    TEST = "test"
    PACKAGE = "package"


class FindingSeverity(StrEnum):
    BLOCKER = "blocker"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class GateCommand:
    """One command that belongs to the aggregate baseline verification contract."""

    gate_id: str
    kind: GateKind
    command: tuple[str, ...]
    required: bool = True
    description: str = ""

    def __post_init__(self) -> None:
        _require_name(self.gate_id, "gate_id")
        if not self.command or any(not part.strip() for part in self.command):
            raise BaselineTruthError(f"{self.gate_id}: command must be non-empty")
        if self.required and not self.description.strip():
            raise BaselineTruthError(f"{self.gate_id}: required gate needs description")


@dataclass(frozen=True, slots=True)
class BaselineManifest:
    """Machine-readable statement of the baseline gates expected by PR-152."""

    gates: Mapping[str, GateCommand]
    import_roots: tuple[str, ...] = ("src", "scripts", "tests")
    security_scan_roots: tuple[str, ...] = ("src", "scripts")
    optimized_mode_required: bool = True
    package_smoke_required: bool = True
    schema_version: str = PR152_BASELINE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != PR152_BASELINE_SCHEMA:
            raise BaselineTruthError("unsupported PR-152 baseline manifest schema")
        gate_map = MappingProxyType(dict(self.gates))
        object.__setattr__(self, "gates", gate_map)
        for key, gate in gate_map.items():
            if key != gate.gate_id:
                raise BaselineTruthError("gate mapping key must match gate_id")
        for root in self.import_roots + self.security_scan_roots:
            _require_name(root, "manifest root")
        missing = self.missing_required_gates
        if missing:
            raise BaselineTruthError(
                "missing required aggregate gates: " + ", ".join(missing)
            )

    @property
    def missing_required_gates(self) -> tuple[str, ...]:
        required = set(_REQUIRED_GATE_IDS)
        if not self.package_smoke_required:
            required.discard("package-smoke")
        return tuple(sorted(required.difference(self.gates)))

    @property
    def manifest_hash(self) -> str:
        return domain_hash(
            PR152_BASELINE_HASH_DOMAIN,
            {
                "schema_version": self.schema_version,
                "import_roots": list(self.import_roots),
                "security_scan_roots": list(self.security_scan_roots),
                "optimized_mode_required": self.optimized_mode_required,
                "package_smoke_required": self.package_smoke_required,
                "gates": {
                    key: {
                        "kind": gate.kind.value,
                        "command": list(gate.command),
                        "required": gate.required,
                        "description": gate.description,
                    }
                    for key, gate in sorted(self.gates.items())
                },
            },
        )


@dataclass(frozen=True, slots=True)
class SecurityFinding:
    """A deterministic finding emitted by the PR-152 source scanner."""

    path: str
    code: str
    detail: str
    severity: FindingSeverity = FindingSeverity.BLOCKER
    line: int | None = None

    def __post_init__(self) -> None:
        _require_name(self.path, "finding path")
        _require_name(self.code, "finding code")
        _require_name(self.detail, "finding detail")

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "code": self.code,
            "detail": self.detail,
            "severity": self.severity.value,
            "line": self.line,
        }


@dataclass(frozen=True, slots=True)
class ImportEdge:
    """Directed import edge used for deterministic cycle checks."""

    importer: str
    imported: str

    def __post_init__(self) -> None:
        _require_name(self.importer, "importer")
        _require_name(self.imported, "imported")


@dataclass(frozen=True, slots=True)
class BaselineTruthReport:
    """One immutable PR-152 baseline report."""

    manifest: BaselineManifest
    findings: tuple[SecurityFinding, ...] = ()
    import_cycles: tuple[tuple[str, ...], ...] = ()
    optimized_mode_import_ok: bool = False
    source_checkout_import_ok: bool = False
    installed_wheel_import_ok: bool = False

    @property
    def green(self) -> bool:
        return (
            not self.findings
            and not self.import_cycles
            and self.optimized_mode_import_ok
            and self.source_checkout_import_ok
            and self.installed_wheel_import_ok
        )

    @property
    def blocking_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        reasons.extend(f"{item.path}:{item.code}" for item in self.findings)
        reasons.extend(
            "import-cycle:" + " -> ".join(cycle) for cycle in self.import_cycles
        )
        if not self.optimized_mode_import_ok:
            reasons.append("optimized-mode-import-not-proven")
        if not self.source_checkout_import_ok:
            reasons.append("source-checkout-import-not-proven")
        if not self.installed_wheel_import_ok:
            reasons.append("installed-wheel-import-not-proven")
        return tuple(dict.fromkeys(reasons))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.manifest.schema_version,
            "manifest_hash": self.manifest.manifest_hash,
            "green": self.green,
            "optimized_mode_import_ok": self.optimized_mode_import_ok,
            "source_checkout_import_ok": self.source_checkout_import_ok,
            "installed_wheel_import_ok": self.installed_wheel_import_ok,
            "findings": [item.to_dict() for item in self.findings],
            "import_cycles": [list(cycle) for cycle in self.import_cycles],
            "blocking_reasons": list(self.blocking_reasons),
        }


def default_pr152_manifest() -> BaselineManifest:
    """Return the minimal aggregate gate manifest required by PR-152."""

    gates = {
        "compileall": GateCommand(
            "compileall",
            GateKind.IMPORT,
            (
                "python",
                "-m",
                "compileall",
                "-q",
                "arb_bot.py",
                "src",
                "scripts",
                "tests",
            ),
            description="all active Python entrypoints must compile",
        ),
        "quality-gate": GateCommand(
            "quality-gate",
            GateKind.FORMAT,
            ("python", "scripts/quality_gate.py"),
            description="aggregate format/type/import baseline gate",
        ),
        "security-gate": GateCommand(
            "security-gate",
            GateKind.SECURITY,
            ("python", "scripts/security_gate.py"),
            description="active parser/security checks are part of aggregate verify",
        ),
        "pytest-offline": GateCommand(
            "pytest-offline",
            GateKind.TEST,
            ("python", "-m", "pytest", "-m", "not live and not manual", "-q"),
            description="offline test suite must not require providers or live credentials",
        ),
        "package-smoke": GateCommand(
            "package-smoke",
            GateKind.PACKAGE,
            ("python", "scripts/package_smoke.py"),
            description="installed wheel import/CLI smoke must stay reproducible",
        ),
    }
    return BaselineManifest(gates=gates)


def scan_python_source(
    path: str,
    text: str,
    *,
    active_source: bool = True,
) -> tuple[SecurityFinding, ...]:
    """Scan one Python source text for PR-152 blocker patterns.

    The scanner is intentionally conservative and deterministic. It is a helper
    for tests and future CI wiring; it does not walk the filesystem by itself.
    """

    _require_name(path, "path")
    if not active_source:
        return ()
    findings: list[SecurityFinding] = []
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as exc:
        return (
            SecurityFinding(
                path,
                "syntax-error",
                exc.msg,
                line=exc.lineno,
            ),
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            findings.append(
                SecurityFinding(
                    path,
                    "assert-validation",
                    "assert statements are not accepted for active validation",
                    line=node.lineno,
                )
            )
        elif isinstance(node, ast.ExceptHandler):
            if node.type is None or _exception_name(node.type) in {
                "Exception",
                "BaseException",
            }:
                findings.append(
                    SecurityFinding(
                        path,
                        "broad-except",
                        "broad exception handling must be justified or narrowed",
                        severity=FindingSeverity.WARNING,
                        line=node.lineno,
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _is_quarantined_import(module):
                findings.append(
                    SecurityFinding(
                        path,
                        "quarantined-import",
                        f"active source imports quarantined module {module}",
                        line=node.lineno,
                    )
                )
            for alias in node.names:
                if alias.name in _DIRECT_SIGNING_NAMES:
                    findings.append(
                        SecurityFinding(
                            path,
                            "direct-keypair-import",
                            f"active source imports {alias.name}",
                            line=node.lineno,
                        )
                    )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if _is_quarantined_import(alias.name):
                    findings.append(
                        SecurityFinding(
                            path,
                            "quarantined-import",
                            f"active source imports quarantined module {alias.name}",
                            line=node.lineno,
                        )
                    )

    for marker in _DIRECT_SUBMISSION_MARKERS:
        if marker in text:
            findings.append(
                SecurityFinding(
                    path,
                    "direct-rpc-submission",
                    f"active source contains {marker}",
                )
            )
    if _SKIP_PREFLIGHT_RE.search(text):
        findings.append(
            SecurityFinding(
                path,
                "skip-preflight",
                "skipPreflight=true is not accepted in active recovery/submission code",
            )
        )
    return tuple(_dedupe_findings(findings))


def extract_import_edges(module_name: str, text: str) -> tuple[ImportEdge, ...]:
    """Extract top-level import edges from one module without importing it."""

    _require_name(module_name, "module_name")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ()
    edges: list[ImportEdge] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            edges.append(ImportEdge(module_name, node.module))
        elif isinstance(node, ast.Import):
            edges.extend(ImportEdge(module_name, alias.name) for alias in node.names)
    return tuple(edges)


def detect_import_cycles(edges: Iterable[ImportEdge]) -> tuple[tuple[str, ...], ...]:
    """Return deterministic cycles from a directed import graph."""

    graph: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        graph[edge.importer].add(edge.imported)
        graph.setdefault(edge.imported, set())

    cycles: set[tuple[str, ...]] = set()
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            cycle = visiting[visiting.index(node) :] + [node]
            cycles.add(_canonical_cycle(cycle))
            return
        if node in visited:
            return
        visiting.append(node)
        for target in sorted(graph.get(node, ())):
            visit(target)
        visiting.pop()
        visited.add(node)

    for node in sorted(graph):
        visit(node)
    return tuple(sorted(cycles))


def assert_baseline_green(report: BaselineTruthReport) -> None:
    if not report.green:
        raise BaselineTruthError(
            "baseline is not green: " + ", ".join(report.blocking_reasons)
        )


def domain_hash(domain: str, payload: object) -> str:
    _require_name(domain, "hash domain")
    raw = json.dumps(
        _jsonable(payload),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(domain.encode("utf-8") + b"\0" + raw).hexdigest()


def _jsonable(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "to_dict"):
        return _jsonable(value.to_dict())
    raise BaselineTruthError(f"unsupported JSON value: {type(value).__name__}")


def _require_name(value: str, field: str) -> None:
    if not value or not value.strip():
        raise BaselineTruthError(f"{field} must be non-empty")


def _exception_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _is_quarantined_import(module: str) -> bool:
    return any(
        module == prefix or module.startswith(prefix + ".")
        for prefix in _QUARANTINED_IMPORT_PREFIXES
    )


def _dedupe_findings(findings: Sequence[SecurityFinding]) -> tuple[SecurityFinding, ...]:
    seen: set[tuple[str, str, int | None]] = set()
    result: list[SecurityFinding] = []
    for finding in findings:
        key = (finding.path, finding.code, finding.line)
        if key not in seen:
            seen.add(key)
            result.append(finding)
    return tuple(result)


def _canonical_cycle(cycle: Sequence[str]) -> tuple[str, ...]:
    body = list(cycle[:-1])
    if not body:
        return tuple(cycle)
    rotations = [body[index:] + body[:index] for index in range(len(body))]
    best = min(rotations)
    return tuple(best + [best[0]])


__all__ = [
    "PR152_BASELINE_SCHEMA",
    "BaselineManifest",
    "BaselineTruthError",
    "BaselineTruthReport",
    "FindingSeverity",
    "GateCommand",
    "GateKind",
    "ImportEdge",
    "SecurityFinding",
    "assert_baseline_green",
    "default_pr152_manifest",
    "detect_import_cycles",
    "domain_hash",
    "extract_import_edges",
    "scan_python_source",
]
