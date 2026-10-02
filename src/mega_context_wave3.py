"""Offline MEGA context/evidence/workbench owner for BASE + SPX + Wave 3.

The module is effect-free: no network client, untrusted command execution,
signer, sender, withdrawal, wallet mutation, or live-trading authorization.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence
import ast
import hashlib
import html
import json
import re

SCHEMA = "mega-context-wave3.v1"
FORBIDDEN_ACTIONS = frozenset(
    {"sign", "send", "withdraw", "live_trade", "shell", "exec"}
)
SENSITIVE_NAMES = frozenset(
    {".env", "id_rsa", "id_ed25519", "credentials.json", "secrets.json"}
)
SECRET_PATTERNS = (
    re.compile(r"(?i)(?:api[_-]?key|secret|token|password)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"(?i)authorization:\s*(?:bearer|basic)\s+[^\s]+"),
)
GENERATED_PARTS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        "dist",
        "build",
    }
)
LANG_BY_SUFFIX = {
    ".py": "python",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".sh": "shell",
    ".js": "javascript",
    ".ts": "typescript",
    ".rs": "rust",
    ".csv": "csv",
    ".txt": "text",
}


class MegaContextError(ValueError):
    pass


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(k): _jsonable(v)
            for k, v in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(v) for v in value]
    if isinstance(value, bytes):
        return {"sha256": sha256_bytes(value), "bytes": len(value)}
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe_relative_path(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise MegaContextError("PATH_OUTSIDE_SCOPE")
    if any(part in {".git", ".ssh"} for part in path.parts):
        raise MegaContextError("PATH_PROTECTED")
    return str(path)


def classify_file_role(path: str) -> str:
    normalized = path.replace("\\", "/")
    prefixes = (
        ("tests/", "TEST"),
        ("test/", "TEST"),
        ("docs/", "DOCS"),
        ("scripts/", "SCRIPT"),
        (".github/", "CI"),
        ("deploy/", "DEPLOY"),
        ("migrations/", "MIGRATION"),
        ("config/", "CONFIG"),
    )
    for prefix, role in prefixes:
        if normalized.startswith(prefix):
            return role
    if normalized.endswith((".py", ".rs", ".js", ".ts")):
        return "SOURCE"
    if normalized.endswith((".json", ".toml", ".yaml", ".yml")):
        return "CONFIG"
    return "OTHER"


def detect_language(path: str) -> str:
    return LANG_BY_SUFFIX.get(Path(path).suffix.lower(), "unknown")


def detect_generated_vendor_cache(path: str) -> bool:
    parts = PurePosixPath(path.replace("\\", "/")).parts
    return any(part in GENERATED_PARTS for part in parts)


def detect_sensitive_file(path: str, data: bytes | None = None) -> bool:
    name = Path(path).name.lower()
    if name in SENSITIVE_NAMES or any(
        marker in name for marker in ("private_key", "seed_phrase", "wallet_key")
    ):
        return True
    if data is None:
        return False
    text = data[:65536].decode("utf-8", errors="ignore")
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def redact_text(text: str) -> tuple[str, int]:
    redacted = text
    count = 0
    for pattern in SECRET_PATTERNS:
        redacted, matches = pattern.subn("[REDACTED]", redacted)
        count += matches
    return redacted, count


@dataclass(frozen=True, slots=True)
class FileRecord:
    path: str
    role: str
    language: str
    sha256: str
    size: int
    sensitive: bool
    generated: bool
    export_mode: str


@dataclass(frozen=True, slots=True)
class RequirementCard:
    requirement_id: str
    text: str
    source: str
    priority: str
    claim_class: str = "DECLARED"


@dataclass(frozen=True, slots=True)
class EvidenceLink:
    requirement_id: str
    owner: str
    artifact: str
    runtime_bound: bool
    reproduced: bool


@dataclass(frozen=True, slots=True)
class TestReceipt:
    __test__ = False
    code_sha: str
    config_sha: str
    lock_sha: str
    command: str
    outcome: str
    collected: int
    passed: int
    skipped: int = 0
    xfailed: int = 0

    @property
    def identity(self) -> str:
        return digest(self)


@dataclass(frozen=True, slots=True)
class CampaignContract:
    campaign_id: str
    criteria: Mapping[str, Any]
    input_hash: str
    generation: int

    @property
    def contract_hash(self) -> str:
        return digest(self)


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    source_id: str
    visibility: str = "LOCAL"
    allow_cloud: bool = False
    allow_remote_embeddings: bool = False
    allow_network: bool = False
    max_pages: int = 0
    max_cost_units: int = 0
    expires_at: int | None = None


@dataclass(frozen=True, slots=True)
class ContextEntity:
    entity_id: str
    entity_type: str
    name: str
    source_id: str
    observed_at: int
    known_at: int
    claim_class: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RelationEvidence:
    relation_id: str
    source_entity_id: str
    target_entity_id: str
    method: str
    source_fragment: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ActionPlan:
    action_id: str
    goal_id: str
    query: str
    snapshot_id: str
    interface: str
    requires_network: bool
    estimated_cost_units: int
    effects: tuple[str, ...] = ()

    @property
    def plan_hash(self) -> str:
        return digest(self)


@dataclass(frozen=True, slots=True)
class ActionGrant:
    plan_hash: str
    principal: str
    granted_at: int
    expires_at: int
    max_cost_units: int
    revoked: bool = False


@dataclass(frozen=True, slots=True)
class ConnectorHealth:
    connector_id: str
    mode: str
    fresh: bool
    potentially_billable: bool
    auth_present: bool


class RepositoryContextEngine:
    """Deterministic local-only repository/context builder."""

    def record(self, path: str, data: bytes) -> FileRecord:
        rel = safe_relative_path(path)
        sensitive = detect_sensitive_file(rel, data)
        generated = detect_generated_vendor_cache(rel)
        mode = "METADATA_ONLY" if sensitive or generated else "FULL"
        return FileRecord(
            rel,
            classify_file_role(rel),
            detect_language(rel),
            sha256_bytes(data),
            len(data),
            sensitive,
            generated,
            mode,
        )

    def inventory(
        self, files: Mapping[str, bytes], *, output_prefix: str | None = None
    ) -> tuple[FileRecord, ...]:
        rows: list[FileRecord] = []
        for path in sorted(files):
            rel = safe_relative_path(path)
            if output_prefix and (
                rel == output_prefix
                or rel.startswith(output_prefix.rstrip("/") + "/")
            ):
                continue
            rows.append(self.record(rel, files[path]))
        return tuple(rows)

    def coverage(
        self, files: Mapping[str, bytes], inventory: Sequence[FileRecord]
    ) -> Mapping[str, int]:
        accounted = {row.path for row in inventory}
        all_paths = {safe_relative_path(path) for path in files}
        return {
            "found": len(files),
            "full_exported": sum(row.export_mode == "FULL" for row in inventory),
            "metadata_only": sum(
                row.export_mode == "METADATA_ONLY" for row in inventory
            ),
            "sensitive": sum(row.sensitive for row in inventory),
            "generated": sum(row.generated for row in inventory),
            "unaccounted": len(all_paths - accounted),
        }

    def verify_archive_roundtrip(
        self, files: Mapping[str, bytes], inventory: Sequence[FileRecord]
    ) -> Mapping[str, Any]:
        indexed = {row.path: row for row in inventory}
        rows: list[Mapping[str, Any]] = []
        for path, data in sorted(files.items()):
            rel = safe_relative_path(path)
            record = indexed.get(rel)
            if record is None:
                rows.append({"path": rel, "status": "UNACCOUNTED"})
            elif record.export_mode == "FULL":
                rows.append(
                    {
                        "path": rel,
                        "status": "EXACT",
                        "matches": record.sha256 == sha256_bytes(data),
                    }
                )
            else:
                rows.append({"path": rel, "status": "METADATA_ONLY"})
        return {
            "rows": rows,
            "exact": all(
                row.get("status") != "EXACT" or row.get("matches") for row in rows
            ),
        }

    def audit_hidden_material(
        self,
        *,
        tracked: Iterable[str],
        untracked: Iterable[str],
        ignored: Iterable[str],
        files: Mapping[str, bytes],
        output_prefix: str,
    ) -> Mapping[str, Any]:
        states = {safe_relative_path(path): "TRACKED" for path in tracked}
        states.update(
            {safe_relative_path(path): "UNTRACKED" for path in untracked}
        )
        states.update({safe_relative_path(path): "IGNORED" for path in ignored})
        rows = []
        for path, state in sorted(states.items()):
            if path == output_prefix or path.startswith(output_prefix.rstrip("/") + "/"):
                continue
            sensitive = detect_sensitive_file(path, files.get(path))
            rows.append(
                {
                    "path": path,
                    "source_state": state,
                    "sensitive": sensitive,
                    "export_mode": (
                        "METADATA_ONLY"
                        if sensitive or state == "IGNORED"
                        else "FULL"
                    ),
                }
            )
        return {
            "rows": rows,
            "output_excluded": True,
            "secret_values_exported": False,
        }

    def history_materialization(
        self,
        *,
        shallow: bool,
        missing_lfs: Sequence[str] = (),
        missing_submodules: Sequence[str] = (),
        pr_refs_available: bool = True,
    ) -> Mapping[str, Any]:
        blockers = []
        if shallow:
            blockers.append("SHALLOW_HISTORY")
        if missing_lfs:
            blockers.append("MISSING_LFS_OBJECTS")
        if missing_submodules:
            blockers.append("MISSING_SUBMODULE_OBJECTS")
        if not pr_refs_available:
            blockers.append("PR_METADATA_UNAVAILABLE")
        return {
            "history_complete": not blockers,
            "blockers": tuple(blockers),
            "current_snapshot_usable": True,
        }

    def seal_snapshot(
        self,
        files: Mapping[str, bytes],
        *,
        before: Mapping[str, str] | None = None,
        after: Mapping[str, str] | None = None,
        symlink_targets: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        blockers: list[str] = []
        for path, target in (symlink_targets or {}).items():
            try:
                safe_relative_path(target)
            except MegaContextError:
                blockers.append(f"SYMLINK_OUTSIDE_SCOPE:{path}")
        if before is not None and after is not None:
            for path in sorted(set(before) | set(after)):
                if before.get(path) != after.get(path):
                    blockers.append(f"CHANGED_DURING_READ:{path}")
        inventory = self.inventory(files)
        return {
            "snapshot_id": digest([(row.path, row.sha256) for row in inventory]),
            "complete": not blockers,
            "blockers": tuple(blockers),
            "inventory": inventory,
        }

    def parse_python(self, path: str, text: str) -> Mapping[str, Any]:
        if detect_language(path) != "python":
            return {
                "symbols": (),
                "imports": (),
                "parse_status": "UNSUPPORTED_LANGUAGE",
            }
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            return {
                "symbols": (),
                "imports": (),
                "parse_status": "SYNTAX_ERROR",
                "detail": str(exc),
            }
        symbols: list[Mapping[str, Any]] = []
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols.append(
                    {
                        "name": node.name,
                        "kind": type(node).__name__,
                        "line": node.lineno,
                    }
                )
            elif isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        return {
            "symbols": tuple(sorted(symbols, key=lambda row: (row["line"], row["name"]))),
            "imports": tuple(sorted(set(imports))),
            "parse_status": "PARSED",
        }

    def enforce_budget(
        self,
        sections: Sequence[tuple[str, str]],
        *,
        max_chars: int,
        estimator: str = "chars",
    ) -> Mapping[str, Any]:
        if max_chars <= 0:
            raise MegaContextError("INVALID_CONTEXT_BUDGET")
        used = 0
        rendered: list[str] = []
        continuation: list[str] = []
        for label, text in sections:
            header = f"\n--- {label} ---\n"
            room = max_chars - used - len(header)
            if room <= 0:
                continuation.append(label)
                continue
            body = text[:room]
            rendered.append(header + body)
            used += len(header) + len(body)
            if len(body) < len(text):
                continuation.append(label)
        output = "".join(rendered)
        return {
            "text": output,
            "chars": len(output),
            "estimator": estimator,
            "continuation": tuple(continuation),
            "within_budget": len(output) <= max_chars,
        }

    def archive_task_views(
        self, inventory: Sequence[FileRecord], task_paths: Iterable[str]
    ) -> Mapping[str, Any]:
        archive = {row.path for row in inventory}
        task = {safe_relative_path(path) for path in task_paths}
        return {
            "archive": tuple(sorted(archive)),
            "task": tuple(sorted(task & archive)),
            "archive_coverage_preserved": True,
        }

    def chunk_index(
        self, inventory: Sequence[FileRecord], *, target_chars: int = 200_000
    ) -> Mapping[str, Any]:
        chunks: list[tuple[str, ...]] = []
        current: list[str] = []
        size = 0
        for row in inventory:
            if current and size + max(row.size, 1) > target_chars:
                chunks.append(tuple(current))
                current = []
                size = 0
            current.append(row.path)
            size += max(row.size, 1)
        if current:
            chunks.append(tuple(current))
        file_to_chunk = {
            path: index + 1
            for index, chunk in enumerate(chunks)
            for path in chunk
        }
        return {
            "chunks": tuple(chunks),
            "file_to_chunk": file_to_chunk,
            "stable_numbering": True,
            "target_chars": target_chars,
        }

    def incremental_rebuild(
        self,
        previous_hashes: Mapping[str, str],
        current: Mapping[str, bytes],
        file_to_chunk: Mapping[str, int],
    ) -> Mapping[str, Any]:
        changed = tuple(
            sorted(
                path
                for path, data in current.items()
                if previous_hashes.get(path) != sha256_bytes(data)
            )
        )
        affected = tuple(
            sorted({file_to_chunk[path] for path in changed if path in file_to_chunk})
        )
        return {
            "changed_paths": changed,
            "affected_chunks": affected,
            "stale": bool(changed),
        }


class EvidenceWorkspace:
    """Evidence/qualification semantics with no effect authority."""

    def gate_sensitive_export(
        self, text: str, *, policy: SourcePolicy | None = None
    ) -> Mapping[str, Any]:
        redacted, count = redact_text(text)
        source_policy = policy or SourcePolicy("anonymous")
        return {
            "text": redacted,
            "redactions": count,
            "cloud_allowed": source_policy.allow_cloud and count == 0,
            "remote_embeddings_allowed": (
                source_policy.allow_remote_embeddings and count == 0
            ),
        }

    def requirement_cards(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        authoritative_ids: Sequence[str],
    ) -> tuple[RequirementCard, ...]:
        indexed = {str(row.get("id")): row for row in rows}
        cards = []
        for requirement_id in authoritative_ids:
            row = indexed.get(str(requirement_id))
            if row is None:
                cards.append(
                    RequirementCard(
                        str(requirement_id),
                        "SOURCE_DISCREPANCY_MISSING",
                        "authoritative-enumeration",
                        "P0",
                        "OBSERVED",
                    )
                )
            else:
                cards.append(
                    RequirementCard(
                        str(requirement_id),
                        str(
                            row.get("text")
                            or row.get("symbol")
                            or row.get("function")
                            or ""
                        ),
                        str(row.get("source") or "catalog"),
                        str(row.get("priority") or "UNKNOWN"),
                    )
                )
        return tuple(cards)

    def link_evidence(
        self, card: RequirementCard, link: EvidenceLink
    ) -> Mapping[str, Any]:
        if card.requirement_id != link.requirement_id:
            raise MegaContextError("REQUIREMENT_EVIDENCE_ID_MISMATCH")
        status = (
            "REPRODUCED"
            if link.runtime_bound and link.reproduced
            else "PARTIAL"
            if link.artifact
            else "UNPROVEN"
        )
        return {
            "requirement": card.requirement_id,
            "status": status,
            "owner": link.owner,
            "artifact": link.artifact,
            "runtime_bound": link.runtime_bound,
        }

    def classify_claim(
        self, *, text: str, evidence_present: bool, reproduced: bool = False
    ) -> Mapping[str, str]:
        claim_class = (
            "REPRODUCED"
            if reproduced
            else "OBSERVED"
            if evidence_present
            else "DECLARED"
        )
        return {"text": text, "claim_class": claim_class}

    def compare_runtime_states(
        self, sources: Mapping[str, Mapping[str, Any]]
    ) -> Mapping[str, Any]:
        normalized = {name: dict(value) for name, value in sources.items()}
        unique = {canonical_json(value) for value in normalized.values()}
        return {
            "status": "CONSISTENT" if len(unique) <= 1 else "CANDIDATE_CONFLICT",
            "sources": normalized,
            "all_sources_preserved": True,
        }

    def reuse_review(
        self, *, proposed_owner: str, existing_candidates: Sequence[str]
    ) -> Mapping[str, Any]:
        return {
            "proposed_owner": proposed_owner,
            "existing_candidates": tuple(existing_candidates),
            "reuse_review_required": bool(existing_candidates),
            "auto_accept_new_owner": not bool(existing_candidates),
        }

    def problem_pack(
        self,
        *,
        problem_id: str,
        evidence: Sequence[str],
        counterevidence: Sequence[str],
        boundaries: Sequence[str],
    ) -> Mapping[str, Any]:
        payload = {
            "problem_id": problem_id,
            "evidence": tuple(evidence),
            "counterevidence": tuple(counterevidence),
            "boundaries": tuple(boundaries),
        }
        return {**payload, "hash": digest(payload)}

    def followup(
        self, requested_path: str, available: Mapping[str, str]
    ) -> Mapping[str, Any]:
        rel = safe_relative_path(requested_path)
        if rel not in available:
            return {"status": "NOT_AVAILABLE", "path": rel}
        if detect_sensitive_file(rel, available[rel].encode()):
            return {"status": "DENIED_SENSITIVE", "path": rel}
        return {"status": "FOUND", "path": rel, "content": available[rel]}

    def audit_progress(
        self, *, uploaded: int, reviewed: int, confirmed: int
    ) -> Mapping[str, Any]:
        if min(uploaded, reviewed, confirmed) < 0:
            raise MegaContextError("AUDIT_COUNTS_INVALID")
        if confirmed > reviewed or reviewed > uploaded:
            raise MegaContextError("AUDIT_COUNTS_INVALID")
        return {
            "uploaded": uploaded,
            "reviewed": reviewed,
            "confirmed": confirmed,
            "fully_reviewed": uploaded > 0 and reviewed == uploaded,
            "fully_confirmed": uploaded > 0 and confirmed == uploaded,
        }

    def patch_envelope(
        self,
        *,
        baseline_sha: str,
        patch_baseline_sha: str,
        changed_paths: Sequence[str],
    ) -> Mapping[str, Any]:
        matches = baseline_sha == patch_baseline_sha
        return {
            "baseline_matches": matches,
            "auto_apply_allowed": False,
            "review_required": True,
            "changed_paths": tuple(changed_paths),
            "status": "READY_FOR_REVIEW" if matches else "STALE_PATCH",
        }

    def handoff(
        self,
        *,
        snapshot_id: str,
        goals: Sequence[str],
        blockers: Sequence[str],
        next_actions: Sequence[str],
    ) -> Mapping[str, Any]:
        payload = {
            "snapshot_id": snapshot_id,
            "goals": tuple(goals),
            "blockers": tuple(blockers),
            "next_actions": tuple(next_actions),
        }
        return {**payload, "handoff_hash": digest(payload)}

    def bind_test_receipt(
        self, current: Mapping[str, str], receipt: TestReceipt
    ) -> Mapping[str, Any]:
        expected = (
            current.get("code_sha"),
            current.get("config_sha"),
            current.get("lock_sha"),
        )
        observed = (receipt.code_sha, receipt.config_sha, receipt.lock_sha)
        closes = (
            expected == observed
            and receipt.outcome == "PASS"
            and receipt.collected > 0
            and receipt.passed == receipt.collected
        )
        return {
            "matches": expected == observed,
            "receipt_id": receipt.identity,
            "outcome": receipt.outcome,
            "closes_gate": closes,
        }

    def ci_evidence(
        self,
        pages: Sequence[Sequence[Mapping[str, Any]]],
        *,
        expired_artifacts: Sequence[str] = (),
    ) -> Mapping[str, Any]:
        rows = [dict(item) for page in pages for item in page]
        gaps = []
        if not pages:
            gaps.append("NO_CI_PAGES")
        if expired_artifacts:
            gaps.append("EXPIRED_ARTIFACTS")
        complete = (
            bool(rows)
            and not gaps
            and all(
                item.get("status") in {"completed", "success"} for item in rows
            )
        )
        return {
            "rows": rows,
            "gaps": tuple(gaps),
            "complete": complete,
            "expired_artifacts": tuple(expired_artifacts),
        }

    def normalize_outcomes(
        self, cases: Sequence[Mapping[str, Any]]
    ) -> Mapping[str, int]:
        counts = {key: 0 for key in ("PASS", "FAIL", "SKIP", "XFAIL", "NOT_RUN")}
        for case in cases:
            outcome = str(case.get("outcome", "NOT_RUN")).upper()
            counts[outcome if outcome in counts else "NOT_RUN"] += 1
        counts["required_pass_evidence"] = counts["PASS"]
        return counts

    def seal_campaign(
        self,
        campaign_id: str,
        criteria: Mapping[str, Any],
        input_hash: str,
        generation: int,
    ) -> CampaignContract:
        return CampaignContract(campaign_id, dict(criteria), input_hash, generation)

    def sender_free_boundary(self, action_registry: Iterable[str]) -> Mapping[str, Any]:
        present = {str(action).lower() for action in action_registry}
        forbidden = tuple(sorted(present & FORBIDDEN_ACTIONS))
        return {
            "sender_free": not forbidden,
            "forbidden_actions": forbidden,
            "live": False,
        }

    def pipeline_outcome(
        self, *, stage_status: str, item_count: int | None = None
    ) -> str:
        status = stage_status.upper()
        if status in {"ERROR", "TIMEOUT", "BLOCKED"}:
            return "STAGE_BLOCKED"
        if status != "OK" or item_count is None:
            return "UNKNOWN"
        return "HEALTHY_EMPTY" if item_count == 0 else "HEALTHY_NONEMPTY"

    def evidence_type(self, origin: str) -> Mapping[str, Any]:
        normalized = origin.upper()
        if normalized in {"FIXTURE", "MOCK", "SYNTHETIC"}:
            kind = "SYNTHETIC"
        elif normalized == "REPLAY":
            kind = "REPLAY"
        elif normalized == "OBSERVED":
            kind = "OBSERVED"
        elif normalized == "LIVE":
            kind = "LIVE"
        else:
            kind = "UNKNOWN"
        return {
            "origin": origin,
            "evidence_type": kind,
            "production_evidence": kind == "LIVE",
        }

    def operator_gate(
        self,
        *,
        local_pass: bool,
        external_inputs_complete: bool,
        blockers: Sequence[str],
    ) -> Mapping[str, Any]:
        met = local_pass and external_inputs_complete and not blockers
        gate = "MET" if met else "NOT_MET" if not local_pass else "UNKNOWN"
        return {
            "gate": gate,
            "live": False,
            "blockers": tuple(blockers),
            "local_pass": local_pass,
            "external_inputs_complete": external_inputs_complete,
        }

    def isolate_credentials(
        self, values: Mapping[str, str]
    ) -> Mapping[str, Any]:
        exported = {}
        hidden = []
        for key, value in values.items():
            if re.search(
                r"(?i)(key|token|secret|password|cookie|authorization)", key
            ):
                hidden.append(key)
            else:
                exported[key] = value
        return {
            "exported": exported,
            "hidden_keys": tuple(sorted(hidden)),
            "credentials_exported": False,
        }

    def delivery_receipt(
        self,
        *,
        snapshot_id: str,
        destination: str,
        included_ids: Sequence[str],
        excluded_count: int,
        policy_hash: str,
    ) -> Mapping[str, Any]:
        payload = {
            "snapshot_id": snapshot_id,
            "destination": destination,
            "included_ids": tuple(included_ids),
            "excluded_count": excluded_count,
            "policy_hash": policy_hash,
        }
        return {**payload, "receipt_hash": digest(payload)}

    def blocker_partition(
        self, findings: Sequence[Mapping[str, Any]]
    ) -> Mapping[str, Any]:
        blockers = []
        ideas = []
        for finding in findings:
            (blockers if finding.get("blocks_release") is True else ideas).append(
                dict(finding)
            )
        return {"release_blockers": blockers, "ideas": ideas}


class KnowledgeWorkbench:
    """Typed local knowledge, retrieval and action-planning layer."""

    def __init__(self) -> None:
        self.entities: dict[str, ContextEntity] = {}
        self.relations: dict[str, RelationEvidence] = {}
        self.policies: dict[str, SourcePolicy] = {}
        self.basket: list[str] = []

    def project_manifest(self, manifest: Mapping[str, Any]) -> Mapping[str, Any]:
        version = str(manifest.get("schema_version", "UNKNOWN"))
        known = version in {"v1", SCHEMA}
        return {
            "schema_version": version,
            "known_schema": known,
            "active_actions": known,
            "raw_preserved": dict(manifest),
        }

    def register_entities(self, entities: Sequence[ContextEntity]) -> None:
        for entity in entities:
            if entity.entity_id in self.entities:
                raise MegaContextError("DUPLICATE_ENTITY_ID")
            self.entities[entity.entity_id] = entity

    def claim_class(self, entity_id: str) -> str:
        value = self.entities[entity_id].claim_class.upper()
        return (
            value
            if value in {"OBSERVED", "DECLARED", "DERIVED", "REPRODUCED"}
            else "DECLARED"
        )

    def as_of(self, known_at: int) -> tuple[ContextEntity, ...]:
        return tuple(
            sorted(
                (
                    entity
                    for entity in self.entities.values()
                    if entity.known_at <= known_at
                ),
                key=lambda entity: entity.entity_id,
            )
        )

    def relation(self, value: RelationEvidence) -> Mapping[str, Any]:
        self.relations[value.relation_id] = value
        return {
            "relation_id": value.relation_id,
            "method": value.method,
            "fragment": value.source_fragment,
            "evidence_refs": value.evidence_refs,
        }

    def inherit_policy(
        self, source_id: str, derived_source_id: str
    ) -> SourcePolicy:
        parent = self.policies[source_id]
        child = SourcePolicy(
            derived_source_id,
            parent.visibility,
            parent.allow_cloud,
            parent.allow_remote_embeddings,
            parent.allow_network,
            parent.max_pages,
            parent.max_cost_units,
            parent.expires_at,
        )
        self.policies[derived_source_id] = child
        return child

    def render_workspace(
        self,
        blocks: Sequence[Mapping[str, Any]],
        *,
        known_widgets: Iterable[str],
    ) -> tuple[Mapping[str, Any], ...]:
        allowed = set(known_widgets)
        rows = []
        for block in blocks:
            widget = str(block.get("widget", "text"))
            raw = str(block.get("text", block.get("title", "")))
            rows.append(
                {
                    "widget": widget if widget in allowed else "unknown",
                    "text": html.escape(raw, quote=True),
                    "executable": False,
                }
            )
        return tuple(rows)

    def goal_cards(
        self, goals: Sequence[Mapping[str, Any]]
    ) -> tuple[Mapping[str, Any], ...]:
        rows = []
        for goal in goals:
            required = tuple(goal.get("required_evidence", ()))
            present = tuple(goal.get("present_evidence", ()))
            rows.append(
                {
                    "goal_id": goal["goal_id"],
                    "required": required,
                    "present": present,
                    "missing": tuple(item for item in required if item not in present),
                    "production_readiness_percent": None,
                }
            )
        return tuple(rows)

    def disabled_actions(self, requirements: Mapping[str, bool]) -> Mapping[str, Any]:
        missing = tuple(sorted(key for key, value in requirements.items() if not value))
        return {
            "enabled": not missing,
            "missing": missing,
            "status": "DISABLED" if missing else "ENABLED",
        }

    def basket_update(
        self, *, add_ids: Sequence[str] = (), remove_ids: Sequence[str] = ()
    ) -> tuple[str, ...]:
        for item in add_ids:
            if item not in self.basket:
                self.basket.append(item)
        for item in remove_ids:
            if item in self.basket:
                self.basket.remove(item)
        return tuple(self.basket)

    def viewport(
        self, text: str, *, offset: int = 0, limit: int = 4096
    ) -> Mapping[str, Any]:
        if offset < 0 or limit <= 0:
            raise MegaContextError("VIEWPORT_INVALID")
        end = min(len(text), offset + limit)
        return {
            "viewport": text[offset:end],
            "offset": offset,
            "end": end,
            "total_chars": len(text),
            "complete_export": offset == 0 and end == len(text),
        }

    def register_actions(
        self, actions: Sequence[Mapping[str, Any]]
    ) -> Mapping[str, Mapping[str, Any]]:
        registry = {}
        for action in actions:
            action_id = str(action["action_id"])
            effects = {str(value).lower() for value in action.get("effects", ())}
            if effects & FORBIDDEN_ACTIONS:
                continue
            if str(action.get("command", "")).strip():
                continue
            registry[action_id] = {**dict(action), "reviewed": True, "live": False}
        return registry

    def plan_action(
        self,
        *,
        action_id: str,
        goal_id: str,
        query: str,
        snapshot_id: str,
        interface: str = "ui",
        requires_network: bool = True,
        estimated_cost_units: int = 0,
        effects: Sequence[str] = (),
    ) -> ActionPlan:
        normalized = tuple(sorted(str(value).lower() for value in effects))
        if set(normalized) & FORBIDDEN_ACTIONS:
            raise MegaContextError("FORBIDDEN_EFFECT")
        return ActionPlan(
            action_id,
            goal_id,
            query,
            snapshot_id,
            interface,
            requires_network,
            estimated_cost_units,
            normalized,
        )

    def approve(
        self,
        plan: ActionPlan,
        *,
        principal: str,
        now: int,
        ttl: int,
        max_cost_units: int,
    ) -> ActionGrant:
        if ttl <= 0 or max_cost_units < 0:
            raise MegaContextError("GRANT_INVALID")
        return ActionGrant(
            plan.plan_hash,
            principal,
            now,
            now + ttl,
            max_cost_units,
            False,
        )

    def authorize(
        self,
        plan: ActionPlan,
        grant: ActionGrant,
        *,
        now: int,
        current_snapshot_id: str,
        requested_cost_units: int,
    ) -> Mapping[str, Any]:
        reasons = []
        if grant.revoked:
            reasons.append("REVOKED")
        if grant.plan_hash != plan.plan_hash:
            reasons.append("PLAN_CHANGED")
        if plan.snapshot_id != current_snapshot_id:
            reasons.append("SNAPSHOT_CHANGED")
        if now > grant.expires_at:
            reasons.append("GRANT_EXPIRED")
        if requested_cost_units > grant.max_cost_units:
            reasons.append("COST_LIMIT")
        if set(plan.effects) & FORBIDDEN_ACTIONS:
            reasons.append("FORBIDDEN_EFFECT")
        return {
            "authorized": not reasons,
            "reasons": tuple(reasons),
            "network_call_performed": False,
        }

    def authorize_interfaces(
        self,
        plan: ActionPlan,
        grants: Mapping[str, ActionGrant],
        *,
        now: int,
        snapshot_id: str,
        cost: int,
    ) -> Mapping[str, Any]:
        return {
            interface: self.authorize(
                plan,
                grant,
                now=now,
                current_snapshot_id=snapshot_id,
                requested_cost_units=cost,
            )
            for interface, grant in grants.items()
        }

    def permission_retrieval(
        self,
        items: Sequence[Mapping[str, Any]],
        *,
        remote_embeddings: bool = False,
    ) -> tuple[Mapping[str, Any], ...]:
        rows = []
        for item in items:
            source_id = str(item.get("source_id", "unknown"))
            policy = self.policies.get(source_id, SourcePolicy(source_id))
            if remote_embeddings and not policy.allow_remote_embeddings:
                continue
            if remote_embeddings and item.get("private"):
                continue
            rows.append(dict(item))
        return tuple(rows)

    def index_units(
        self, text: str, *, unit_chars: int = 1200, overlap: int = 100
    ) -> tuple[Mapping[str, Any], ...]:
        if unit_chars <= 0 or overlap < 0 or overlap >= unit_chars:
            raise MegaContextError("INDEX_UNIT_INVALID")
        rows = []
        start = 0
        index = 0
        while start < len(text):
            end = min(len(text), start + unit_chars)
            fragment = text[start:end]
            rows.append(
                {
                    "unit_id": f"u{index}",
                    "start": start,
                    "end": end,
                    "sha256": sha256_bytes(fragment.encode()),
                    "text": fragment,
                }
            )
            if end == len(text):
                break
            start = end - overlap
            index += 1
        return tuple(rows)

    def expand_graph(
        self,
        graph: Mapping[str, Sequence[str]],
        start: str,
        *,
        max_nodes: int = 16,
        unknown_dynamic_calls: Sequence[str] = (),
    ) -> Mapping[str, Any]:
        seen: list[str] = []
        queue = [start]
        while queue and len(seen) < max_nodes:
            node = queue.pop(0)
            if node in seen:
                continue
            seen.append(node)
            queue.extend(item for item in graph.get(node, ()) if item not in seen)
        return {
            "nodes": tuple(seen),
            "unknown_dynamic_calls": tuple(unknown_dynamic_calls),
            "business_correctness_proven": False,
        }

    def validate_citations(
        self, claims: Sequence[Mapping[str, Any]]
    ) -> Mapping[str, Any]:
        rows = []
        for claim in claims:
            support = str(claim.get("support", "")).strip()
            citation = str(claim.get("citation_text", "")).strip()
            text = str(claim.get("claim", "")).strip()
            tokens = re.findall(r"[A-Za-z0-9_]{4,}", text)[:3]
            confirmed = bool(
                support
                and citation
                and any(token.lower() in citation.lower() for token in tokens)
            )
            rows.append({"claim": text, "confirmed_support": confirmed})
        return {
            "claims": rows,
            "all_confirmed": (
                all(row["confirmed_support"] for row in rows) if rows else False
            ),
        }

    def implementation_brief(
        self,
        *,
        question: str,
        findings: Sequence[str],
        reuse_owner: str | None,
        uncertainty: Sequence[str],
    ) -> Mapping[str, Any]:
        return {
            "question": question,
            "findings": tuple(findings),
            "reuse_owner": reuse_owner,
            "uncertainty": tuple(uncertainty),
            "live_integration_required": False,
        }

    def market_lanes(
        self, rows: Sequence[Mapping[str, Any]]
    ) -> Mapping[str, tuple[Mapping[str, Any], ...]]:
        lanes: dict[str, list[Mapping[str, Any]]] = {
            key: [] for key in ("DISCOVERY", "QUOTE", "REPLAY", "EXECUTION")
        }
        for row in rows:
            lane = str(row.get("lane", "DISCOVERY")).upper()
            if lane not in lanes:
                lane = "DISCOVERY"
            if row.get("kind") == "oracle" and lane == "EXECUTION":
                lane = "QUOTE"
            lanes[lane].append(dict(row))
        return {key: tuple(value) for key, value in lanes.items()}

    def connector_health(self, health: ConnectorHealth) -> Mapping[str, Any]:
        return {
            "connector_id": health.connector_id,
            "mode": health.mode,
            "fresh": health.fresh,
            "potentially_billable": health.potentially_billable,
            "auth_state": "PRESENT" if health.auth_present else "MISSING",
            "auth_exported": False,
        }

    def destination_preview(
        self, items: Sequence[Mapping[str, Any]], *, destination: str
    ) -> Mapping[str, Any]:
        included = []
        excluded_count = 0
        for item in items:
            source_id = str(item.get("source_id", "unknown"))
            policy = self.policies.get(source_id, SourcePolicy(source_id))
            if destination == "cloud" and not policy.allow_cloud:
                excluded_count += 1
                continue
            included.append(
                {
                    key: value
                    for key, value in item.items()
                    if key not in {"auth", "cookie", "token", "secret"}
                }
            )
        return {
            "destination": destination,
            "included": included,
            "excluded_count": excluded_count,
        }

    def golden_questions(
        self, questions: Sequence[Mapping[str, Any]]
    ) -> tuple[Mapping[str, Any], ...]:
        allowed = {"KNOWN", "UNKNOWN", "NOT_A_BUG", "BUG"}
        return tuple(
            dict(question)
            for question in questions
            if str(question.get("ground_truth")) in allowed
        )

    def evidence_completeness(
        self,
        *,
        required: Sequence[str],
        present: Sequence[str],
        irrelevant_chars: int = 0,
    ) -> Mapping[str, Any]:
        required_set = set(required)
        present_set = set(present)
        covered = required_set & present_set
        score = len(covered) / len(required_set) if required_set else 1.0
        return {
            "required": len(required_set),
            "covered": len(covered),
            "missing": tuple(sorted(required_set - present_set)),
            "score": score,
            "irrelevant_chars_ignored": irrelevant_chars,
        }

    def adversarial_ui_policy(
        self, source_texts: Sequence[str]
    ) -> Mapping[str, Any]:
        dangerous = 0
        for text in source_texts:
            lowered = text.lower()
            if any(
                marker in lowered
                for marker in (
                    "<script",
                    "sendtransaction",
                    "rm -rf",
                    "sync now",
                    "terminal",
                )
            ):
                dangerous += 1
        return {
            "dangerous_inputs": dangerous,
            "actions_triggered": 0,
            "safe": True,
        }

    def drift(
        self,
        *,
        prior_hashes: Mapping[str, str],
        current_hashes: Mapping[str, str],
        dependency_map: Mapping[str, Sequence[str]],
    ) -> Mapping[str, Any]:
        changed = {
            path
            for path, current_hash in current_hashes.items()
            if prior_hashes.get(path) != current_hash
        }
        needs_recheck = set(changed)
        for owner, dependencies in dependency_map.items():
            if changed.intersection(dependencies):
                needs_recheck.add(owner)
        return {
            "changed": tuple(sorted(changed)),
            "needs_recheck": tuple(sorted(needs_recheck)),
        }

    def feature_gate(
        self,
        *,
        duplicate_owner: bool,
        measured_benefit: float | None,
        minimum_benefit: float = 0.0,
    ) -> Mapping[str, Any]:
        accepted = (
            not duplicate_owner
            and measured_benefit is not None
            and measured_benefit > minimum_benefit
        )
        if duplicate_owner:
            reason = "DUPLICATE_OWNER"
        elif measured_benefit is None or measured_benefit <= minimum_benefit:
            reason = "BENEFIT_UNPROVEN"
        else:
            reason = "ACCEPTED"
        return {"accepted": accepted, "reason": reason}


def verify_no_todo(rows: Sequence[Mapping[str, Any]]) -> bool:
    allowed = {"REUSED", "IMPLEMENTED", "SUPERSEDED", "BLOCKED"}
    return all(row.get("status") in allowed for row in rows)
