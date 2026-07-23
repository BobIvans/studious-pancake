"""PR-210 measured sender-free runtime qualification gate."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Mapping

SCHEMA_VERSION = "pr210.measured-sender-free-qualification.v1"
MIN_SOAK_MS = 72 * 60 * 60 * 1000
MAX_GAP_MS = 10 * 60 * 1000
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+=-]{2,127}$")
REQUIRED_ARTIFACTS = {"shadow_trace", "replay_bundle", "chaos_report", "event_store_export", "installed_artifact_manifest"}
REQUIRED_STAGES = (
    "installed_entrypoint_start", "provider_fixture_ingest", "durable_attempt_created",
    "capital_reservation", "protocol_bound_plan", "exact_compile_or_blocker",
    "exact_simulation_or_blocker", "economic_decision", "terminal_outcome",
    "restart_recovery", "deterministic_replay",
)
REQUIRED_METRICS = {"cycles_completed", "real_provider_cycles", "chaos_cycles", "terminal_outcomes", "unknown_outcomes"}
ALLOWED_TERMINAL = {"SUCCESS", "BLOCKED", "REJECTED", "FAILED"}
BAD_TERMINAL = {"UNKNOWN", "PENDING", "ACQUIRED", "IN_FLIGHT"}

class Severity(StrEnum):
    ERROR = "error"

@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    severity: Severity
    message: str
    path: str = ""
    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "severity": self.severity.value, "message": self.message, "path": self.path}

@dataclass(frozen=True, slots=True)
class PR210QualificationReport:
    schema_version: str
    qualified: bool
    reason_codes: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]
    evidence_hash: str
    live_capability_allowed: bool = False
    signer_capability_allowed: bool = False
    sender_capability_allowed: bool = False
    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "qualified": self.qualified, "reason_codes": list(self.reason_codes), "diagnostics": [d.to_dict() for d in self.diagnostics], "evidence_hash": self.evidence_hash, "live_capability_allowed": False, "signer_capability_allowed": False, "sender_capability_allowed": False}
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

def live_capability_allowed() -> bool: return False
def signer_capability_allowed() -> bool: return False
def sender_capability_allowed() -> bool: return False

def evaluate_pr210_sender_free_qualification(evidence: Mapping[str, Any], *, live_capability: bool = False, signer_capability: bool = False, sender_capability: bool = False) -> PR210QualificationReport:
    diags: list[Diagnostic] = []
    def add(code: str, msg: str = "", path: str = "") -> None:
        diags.append(Diagnostic(code, Severity.ERROR, msg or code, path))
    if evidence.get("schema_version") != SCHEMA_VERSION: add("SCHEMA_VERSION_MISMATCH", path="schema_version")
    if live_capability or signer_capability or sender_capability: add("LIVE_OR_SIGNER_CAPABILITY_ENABLED", path="capabilities")
    _sha(evidence.get("release_artifact_digest"), "release_artifact_digest"); _sid(evidence.get("installed_entrypoint"), "installed_entrypoint"); _sid(evidence.get("composition_root_id"), "composition_root_id")

    artifacts = evidence.get("artifacts", [])
    artifact_ids: set[str] = set()
    for i, a in enumerate(_list(artifacts, "artifacts")):
        a = _map(a, f"artifacts[{i}]"); aid = _sid(a.get("artifact_id"), f"artifacts[{i}].artifact_id")
        if aid in artifact_ids: add("DUPLICATE_ARTIFACT_ID", path="artifacts")
        artifact_ids.add(aid); digest = _sha(a.get("sha256"), f"artifacts[{i}].sha256")
        _pos(a.get("size_bytes"), f"artifacts[{i}].size_bytes"); _sid(a.get("schema_id"), f"artifacts[{i}].schema_id"); _sid(a.get("producer"), f"artifacts[{i}].producer"); _str(a.get("path"), f"artifacts[{i}].path")
        if not _bool(a.get("materialized"), f"artifacts[{i}].materialized"): add("ARTIFACT_NOT_MATERIALIZED", path=f"artifacts.{aid}")
        if digest in {"0"*64, "f"*64}: add("PLACEHOLDER_ARTIFACT_HASH", path=f"artifacts.{aid}.sha256")
    if REQUIRED_ARTIFACTS - artifact_ids: add("REQUIRED_ARTIFACT_MISSING", path="artifacts")

    stage_ids: list[str] = []
    stage_order = {s: n for n, s in enumerate(REQUIRED_STAGES)}
    observed_order: list[int] = []
    for i, s in enumerate(_list(evidence.get("trace_stages", []), "trace_stages")):
        s = _map(s, f"trace_stages[{i}]"); sid = _sid(s.get("stage_id"), f"trace_stages[{i}].stage_id"); stage_ids.append(sid)
        if sid in stage_order: observed_order.append(stage_order[sid])
        _sid(s.get("event_id"), f"trace_stages[{i}].event_id"); art = _sid(s.get("artifact_id"), f"trace_stages[{i}].artifact_id"); _pos(s.get("occurred_at_unix_ms"), f"trace_stages[{i}].occurred_at_unix_ms")
        if not _bool(s.get("reached"), f"trace_stages[{i}].reached"): add("TRACE_STAGE_NOT_REACHED", path=f"trace_stages.{sid}")
        if art not in artifact_ids: add("TRACE_STAGE_ARTIFACT_MISSING", path=f"trace_stages.{sid}.artifact_id")
    if len(stage_ids) != len(set(stage_ids)): add("DUPLICATE_TRACE_STAGE", path="trace_stages")
    if set(REQUIRED_STAGES) - set(stage_ids): add("INSTALLED_TRACE_STAGE_MISSING", path="trace_stages")
    if observed_order != sorted(observed_order): add("TRACE_STAGE_ORDER_INVALID", path="trace_stages")

    admitted = 0; attempt_ids: set[str] = set(); terminal_events: set[str] = set()
    for i, a in enumerate(_list(evidence.get("attempts", []), "attempts")):
        a = _map(a, f"attempts[{i}]"); attempt = _sid(a.get("attempt_id"), f"attempts[{i}].attempt_id"); event = _sid(a.get("terminal_event_id"), f"attempts[{i}].terminal_event_id"); state = _str(a.get("terminal_state"), f"attempts[{i}].terminal_state").upper(); _sid(a.get("cycle_id"), f"attempts[{i}].cycle_id")
        if _bool(a.get("admitted"), f"attempts[{i}].admitted"): admitted += 1
        if attempt in attempt_ids: add("DUPLICATE_ATTEMPT_ID", path=f"attempts.{attempt}")
        if event in terminal_events: add("DUPLICATE_TERMINAL_EVENT_ID", path=f"attempts.{attempt}.terminal_event_id")
        attempt_ids.add(attempt); terminal_events.add(event)
        if state in BAD_TERMINAL: add("NON_TERMINAL_OR_UNKNOWN_OUTCOME", path=f"attempts.{attempt}.terminal_state")
        elif state not in ALLOWED_TERMINAL: add("UNRECOGNIZED_TERMINAL_STATE", path=f"attempts.{attempt}.terminal_state")
    if admitted == 0: add("NO_ADMITTED_ATTEMPTS", path="attempts")

    metrics: dict[str, int] = {}
    for i, m in enumerate(_list(evidence.get("derived_metrics", []), "derived_metrics")):
        m = _map(m, f"derived_metrics[{i}]"); mid = _sid(m.get("metric_id"), f"derived_metrics[{i}].metric_id"); val = _nni(m.get("value"), f"derived_metrics[{i}].value"); src = {_sid(x, f"derived_metrics[{i}].source_event_ids[]") for x in _list(m.get("source_event_ids", []), f"derived_metrics[{i}].source_event_ids")}
        if mid in metrics: add("DUPLICATE_METRIC_ID", path=f"derived_metrics.{mid}")
        if val != len(src): add("DERIVED_METRIC_VALUE_MISMATCH", path=f"derived_metrics.{mid}")
        metrics[mid] = val
    if REQUIRED_METRICS - set(metrics): add("DERIVED_METRIC_MISSING", path="derived_metrics")
    else:
        if metrics["real_provider_cycles"] > metrics["cycles_completed"]: add("PROVIDER_CYCLES_EXCEED_TOTAL", path="derived_metrics.real_provider_cycles")
        if metrics["chaos_cycles"] > metrics["cycles_completed"]: add("CHAOS_CYCLES_EXCEED_TOTAL", path="derived_metrics.chaos_cycles")
        if metrics["terminal_outcomes"] != admitted: add("TERMINAL_OUTCOME_COUNT_MISMATCH", path="derived_metrics.terminal_outcomes")
        if metrics["unknown_outcomes"] != 0: add("UNKNOWN_OUTCOMES_PRESENT", path="derived_metrics.unknown_outcomes")

    times: list[int] = []
    for i, c in enumerate(_list(evidence.get("checkpoints", []), "checkpoints")):
        c = _map(c, f"checkpoints[{i}]"); _sid(c.get("checkpoint_id"), f"checkpoints[{i}].checkpoint_id"); times.append(_pos(c.get("observed_at_unix_ms"), f"checkpoints[{i}].observed_at_unix_ms")); _sha(c.get("event_store_head_hash"), f"checkpoints[{i}].event_store_head_hash")
        if not _bool(c.get("signed_by_observer"), f"checkpoints[{i}].signed_by_observer"): add("UNSIGNED_CHECKPOINT", path="checkpoints")
    if len(times) < 2: add("CHECKPOINTS_INSUFFICIENT", path="checkpoints")
    else:
        if times != sorted(times): add("CHECKPOINT_ORDER_INVALID", path="checkpoints")
        if max(times) - min(times) < MIN_SOAK_MS: add("SOAK_DURATION_TOO_SHORT", path="checkpoints")
        if max(b-a for a,b in zip(times, times[1:])) > MAX_GAP_MS: add("CHECKPOINT_GAP_TOO_LARGE", path="checkpoints")

    health = _map(evidence.get("runtime_health"), "runtime_health")
    dead = _bool(health.get("dead_worker_detected"), "runtime_health.dead_worker_detected"); stale = _bool(health.get("stale_worker_detected"), "runtime_health.stale_worker_detected"); ready = _bool(health.get("workload_ready"), "runtime_health.workload_ready")
    _bool(health.get("management_listener_alive"), "runtime_health.management_listener_alive")
    if (dead or stale) and ready: add("WORKLOAD_READY_WITH_DEAD_OR_STALE_WORKER", path="runtime_health.workload_ready")
    if not _bool(health.get("readiness_failed_on_dead_or_stale"), "runtime_health.readiness_failed_on_dead_or_stale"): add("READINESS_FAILURE_PROOF_MISSING", path="runtime_health.readiness_failed_on_dead_or_stale")
    if not _bool(health.get("backlog_pressure_seen"), "runtime_health.backlog_pressure_seen"): add("BACKLOG_PRESSURE_NOT_EXERCISED", path="runtime_health.backlog_pressure_seen")

    replay = _map(evidence.get("replay"), "replay"); recovery = _list(replay.get("restart_recovery_event_ids"), "replay.restart_recovery_event_ids")
    if not recovery: add("RESTART_RECOVERY_NOT_PROVEN", path="replay.restart_recovery_event_ids")
    for x in recovery: _sid(x, "replay.restart_recovery_event_ids[]")
    _sha(replay.get("replay_input_hash"), "replay.replay_input_hash"); _sha(replay.get("replay_output_hash"), "replay.replay_output_hash"); _sha(replay.get("deterministic_replay_hash"), "replay.deterministic_replay_hash")
    if _nni(replay.get("leaked_reservations"), "replay.leaked_reservations"): add("LEAKED_RESERVATIONS", path="replay.leaked_reservations")
    if _nni(replay.get("leaked_claims"), "replay.leaked_claims"): add("LEAKED_CLAIMS", path="replay.leaked_claims")
    if _nni(replay.get("unexplained_balance_deltas"), "replay.unexplained_balance_deltas"): add("UNEXPLAINED_BALANCE_DELTAS", path="replay.unexplained_balance_deltas")

    codes = tuple(sorted({d.code for d in diags}))
    return PR210QualificationReport(SCHEMA_VERSION, not codes, codes, tuple(diags), _hash(evidence))

def _map(v: Any, f: str) -> Mapping[str, Any]:
    if not isinstance(v, Mapping): raise TypeError(f"{f} must be a mapping")
    return v

def _list(v: Any, f: str) -> list[Any]:
    if not isinstance(v, list): raise TypeError(f"{f} must be a list")
    return v

def _str(v: Any, f: str) -> str:
    if not isinstance(v, str) or not v.strip(): raise TypeError(f"{f} must be a non-empty string")
    return v.strip()

def _sid(v: Any, f: str) -> str:
    s = _str(v, f)
    if not _ID.fullmatch(s): raise ValueError(f"{f} must be a stable identifier")
    return s

def _sha(v: Any, f: str) -> str:
    s = _str(v, f)
    if not _SHA.fullmatch(s): raise ValueError(f"{f} must be a sha256 digest")
    return s

def _bool(v: Any, f: str) -> bool:
    if not isinstance(v, bool): raise TypeError(f"{f} must be a boolean")
    return v

def _pos(v: Any, f: str) -> int:
    if not isinstance(v, int) or isinstance(v, bool) or v <= 0: raise TypeError(f"{f} must be positive int")
    return v

def _nni(v: Any, f: str) -> int:
    if not isinstance(v, int) or isinstance(v, bool) or v < 0: raise TypeError(f"{f} must be non-negative int")
    return v

def _hash(v: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
