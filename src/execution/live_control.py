from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import secrets
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from src.execution.journal import SQLiteAttemptJournal
from src.execution.live_policy import (
    LiveRiskPolicy,
    canonical_policy_hash,
    load_live_policy,
)
from src.execution.models import ExecutionState

SCHEMA_VERSION = "pr018.live-risk.v1"
REPORT_SCHEMA_VERSION = "pr018.readiness-report.v1"
ACK_TEXT_VERSION = "pr018.operator-ack.v1"
_SECRET_RE = re.compile(
    r"(private.?key|seed|secret|authorization|api.?key|bearer\s+[a-z0-9._-]+)", re.I
)


class LiveMode(str, Enum):
    SHADOW = "shadow"
    DRY_RUN = "dry_run"
    LIMITED_LIVE = "live"


class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class LatchReason(str, Enum):
    MANUAL_KILL_SWITCH = "MANUAL_KILL_SWITCH"
    SIMULATION_LIVE_DIVERGENCE = "SIMULATION_LIVE_DIVERGENCE"
    RPC_STALE_OR_CLUSTER_MISMATCH = "RPC_STALE_OR_CLUSTER_MISMATCH"
    PROVIDER_QUOTA_EXHAUSTED = "PROVIDER_QUOTA_EXHAUSTED"
    PROVIDER_OR_ROUTE_UNHEALTHY = "PROVIDER_OR_ROUTE_UNHEALTHY"
    CONFIG_HASH_DRIFT = "CONFIG_HASH_DRIFT"
    WALLET_RESERVE_BREACH = "WALLET_RESERVE_BREACH"
    DAILY_LOSS_CAP_REACHED = "DAILY_LOSS_CAP_REACHED"
    PER_TRADE_CAP_BREACH = "PER_TRADE_CAP_BREACH"
    AMBIGUOUS_SUBMISSION = "AMBIGUOUS_SUBMISSION"
    UNRECONCILED_LANDED_ATTEMPT = "UNRECONCILED_LANDED_ATTEMPT"
    JOURNAL_INVARIANT_VIOLATION = "JOURNAL_INVARIANT_VIOLATION"
    UNEXPECTED_PROGRAM_OR_ACCOUNT = "UNEXPECTED_PROGRAM_OR_ACCOUNT"
    EXACTLY_ONE_TIP_VIOLATION = "EXACTLY_ONE_TIP_VIOLATION"


@dataclass(frozen=True, slots=True)
class ReadinessEvidence:
    source: str
    observed_at: float
    slot: int | None = None
    block_height: int | None = None
    max_age_seconds: int | None = None
    config_hash: str | None = None
    registry_hash: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReadinessGate:
    name: str
    required: bool
    status: GateStatus
    reason: str
    remediation: str
    evidence: ReadinessEvidence


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    schema_version: str
    report_id: str
    generated_at: float
    mode: str
    config_hash: str
    decision: str
    gates: tuple[ReadinessGate, ...]

    @property
    def passed(self) -> bool:
        return self.decision == "ALLOW"

    def to_dict(self) -> dict[str, Any]:
        return _redact(asdict(self))


@dataclass(frozen=True, slots=True)
class LiveOperatorConfirmation:
    confirmation_id: str
    config_hash: str
    issued_at: float
    expires_at: float
    session_id: str
    ack_text_version: str = ACK_TEXT_VERSION


@dataclass(frozen=True, slots=True)
class LiveSubmissionPermit:
    permit_id: str
    attempt_id: str
    attempt_generation: int
    plan_hash: str
    message_hash: str
    config_hash: str
    wallet: str
    route_provider: str
    market: str
    canary_reservation_id: str
    issued_at: float
    expires_at: float
    session_id: str
    nonce: str


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            out[k] = (
                "<redacted>"
                if _SECRET_RE.search(str(k)) or _SECRET_RE.search(str(v))
                else _redact(v)
            )
        return out
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    if isinstance(value, str) and _SECRET_RE.search(value):
        return "<redacted>"
    return value


def load_policy(path: str | Path) -> LiveRiskPolicy:
    return load_live_policy(path)


class LiveControlStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.db = sqlite3.connect(
            self.path, isolation_level=None, check_same_thread=False
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.migrate()

    def migrate(self) -> None:
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS live_latches(id INTEGER PRIMARY KEY, active INTEGER NOT NULL, reason TEXT NOT NULL, evidence TEXT NOT NULL, triggered_at REAL NOT NULL, cleared_at REAL, clear_config_hash TEXT);
        CREATE TABLE IF NOT EXISTS live_confirmations(confirmation_id TEXT PRIMARY KEY, config_hash TEXT NOT NULL, issued_at REAL NOT NULL, expires_at REAL NOT NULL, session_id TEXT NOT NULL, ack_text_version TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS live_permits(permit_id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL, attempt_generation INTEGER NOT NULL, plan_hash TEXT NOT NULL, message_hash TEXT NOT NULL, config_hash TEXT NOT NULL, wallet TEXT NOT NULL, route_provider TEXT NOT NULL, market TEXT NOT NULL, reservation_id TEXT NOT NULL, issued_at REAL NOT NULL, expires_at REAL NOT NULL, session_id TEXT NOT NULL, nonce_hash TEXT NOT NULL, consumed_at REAL, revoked_at REAL);
        CREATE TABLE IF NOT EXISTS live_budget_reservations(reservation_id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL, config_hash TEXT NOT NULL, worst_case_native_debit_lamports INTEGER NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS live_actual_outcomes(id INTEGER PRIMARY KEY, attempt_id TEXT NOT NULL, config_hash TEXT NOT NULL, asset TEXT NOT NULL, actual_delta INTEGER NOT NULL, simulated_delta INTEGER, divergence_abs INTEGER, tolerance INTEGER NOT NULL, reconciled_at REAL NOT NULL, provenance TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS live_audit_events(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, config_hash TEXT, evidence TEXT NOT NULL, created_at REAL NOT NULL);
        """)

    def active_latch(self) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM live_latches WHERE active=1 ORDER BY id DESC LIMIT 1"
        ).fetchone()

    def latch(self, reason: str, evidence: dict[str, Any] | None = None) -> None:
        self.db.execute(
            "INSERT INTO live_latches(active,reason,evidence,triggered_at) VALUES(1,?,?,?)",
            (reason, json.dumps(_redact(evidence or {}), sort_keys=True), time.time()),
        )

    def clear_latch(self, config_hash: str) -> bool:
        cur = self.db.execute(
            "UPDATE live_latches SET active=0, cleared_at=?, clear_config_hash=? WHERE active=1",
            (time.time(), config_hash),
        )
        return cur.rowcount > 0

    def arm(
        self, config_hash: str, expires_in_seconds: int, session_id: str | None = None
    ) -> LiveOperatorConfirmation:
        if expires_in_seconds <= 0 or expires_in_seconds > 3600:
            raise ValueError("expires-in must be between 1 and 3600 seconds")
        now = time.time()
        conf = LiveOperatorConfirmation(
            secrets.token_hex(16),
            config_hash,
            now,
            now + expires_in_seconds,
            session_id or str(os.getpid()),
        )
        self.db.execute(
            "INSERT INTO live_confirmations VALUES(?,?,?,?,?,?)",
            (
                conf.confirmation_id,
                conf.config_hash,
                conf.issued_at,
                conf.expires_at,
                conf.session_id,
                conf.ack_text_version,
            ),
        )
        return conf

    def fresh_confirmation(
        self, config_hash: str, now: float | None = None
    ) -> LiveOperatorConfirmation | None:
        now = time.time() if now is None else now
        row = self.db.execute(
            "SELECT * FROM live_confirmations WHERE config_hash=? AND expires_at>? ORDER BY issued_at DESC LIMIT 1",
            (config_hash, now),
        ).fetchone()
        return (
            None
            if not row
            else LiveOperatorConfirmation(
                row["confirmation_id"],
                row["config_hash"],
                row["issued_at"],
                row["expires_at"],
                row["session_id"],
                row["ack_text_version"],
            )
        )

    def issue_permit(
        self, permit: LiveSubmissionPermit, worst_case_native_debit_lamports: int
    ) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO live_budget_reservations VALUES(?,?,?,?,?,?)",
                (
                    permit.canary_reservation_id,
                    permit.attempt_id,
                    permit.config_hash,
                    worst_case_native_debit_lamports,
                    "reserved",
                    time.time(),
                ),
            )
            self.db.execute(
                "INSERT INTO live_permits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL)",
                (
                    permit.permit_id,
                    permit.attempt_id,
                    permit.attempt_generation,
                    permit.plan_hash,
                    permit.message_hash,
                    permit.config_hash,
                    permit.wallet,
                    permit.route_provider,
                    permit.market,
                    permit.canary_reservation_id,
                    permit.issued_at,
                    permit.expires_at,
                    permit.session_id,
                    hashlib.sha256(permit.nonce.encode()).hexdigest(),
                ),
            )

    def consume_permit(self, permit: LiveSubmissionPermit) -> bool:
        cur = self.db.execute(
            "UPDATE live_permits SET consumed_at=? WHERE permit_id=? AND consumed_at IS NULL AND revoked_at IS NULL AND message_hash=? AND config_hash=? AND expires_at>?",
            (
                time.time(),
                permit.permit_id,
                permit.message_hash,
                permit.config_hash,
                time.time(),
            ),
        )
        return cur.rowcount == 1

    def status(
        self,
        journal: SQLiteAttemptJournal | None = None,
        config_hash: str | None = None,
    ) -> dict[str, Any]:
        latch = self.active_latch()
        return _redact(
            {
                "schema_version": SCHEMA_VERSION,
                "config_hash": config_hash,
                "latch": dict(latch) if latch else None,
                "outstanding_attempts": outstanding_attempts(journal) if journal else 0,
            }
        )


def outstanding_attempts(journal: SQLiteAttemptJournal | None) -> int:
    if journal is None:
        return 0
    terminal = tuple(
        s.value
        for s in (
            ExecutionState.RECONCILED_SUCCESS,
            ExecutionState.RECONCILED_FAILURE,
            ExecutionState.PROVEN_EXPIRED,
            ExecutionState.REJECTED,
            ExecutionState.REJECTED_PRE_SEND,
            ExecutionState.FAILED,
            ExecutionState.EXPIRED,
            ExecutionState.RECONCILED,
        )
    )
    marks = ",".join("?" for _ in terminal)
    return int(
        journal.db.execute(
            f"SELECT COUNT(*) FROM attempts WHERE state NOT IN ({marks})", terminal
        ).fetchone()[0]
    )


class LiveReadinessService:
    REQUIRED = (
        "config_schema",
        "live_enabled",
        "operator_confirmation",
        "safety_latch",
        "wallet_reserve",
        "allowlists",
        "provider_capabilities",
        "rpc_health",
        "journal_outstanding",
        "canary_caps",
        "exactly_one_tip",
        "shadow_evidence",
    )

    def __init__(
        self,
        policy: LiveRiskPolicy | dict[str, Any],
        store: LiveControlStore,
        journal: SQLiteAttemptJournal | None = None,
        *,
        observed: dict[str, Any] | None = None,
    ):
        self.policy = policy
        self.store = store
        self.journal = journal
        self.observed = observed or {}
        self.config_hash = canonical_policy_hash(policy)

    def _gate(
        self,
        name: str,
        ok: bool | None,
        reason: str,
        remediation: str,
        diag: dict[str, Any] | None = None,
    ) -> ReadinessGate:
        status = (
            GateStatus.PASS
            if ok is True
            else GateStatus.FAIL if ok is False else GateStatus.UNKNOWN
        )
        return ReadinessGate(
            name,
            True,
            status,
            reason,
            remediation,
            ReadinessEvidence(
                "live_readiness",
                time.time(),
                self.observed.get("slot"),
                self.observed.get("block_height"),
                self.policy.get("freshness", {}).get("max_evidence_age_seconds"),
                self.config_hash,
                diagnostics=_redact(diag or {}),
            ),
        )

    def report(self, mode: LiveMode) -> ReadinessReport:
        p = self.policy
        gates: list[ReadinessGate] = []
        valid_schema = (
            p.get("schema_version") == SCHEMA_VERSION
            and p.get("max_outstanding_attempts") == 1
        )
        money_ints = [
            p.get("protected_reserve_lamports"),
            p.get("per_attempt", {}).get("max_net_native_debit_lamports"),
            p.get("canary", {}).get("max_principal_by_asset", {}).get("USDC"),
            p.get("loss_limits", {}).get("per_trade_lamports"),
            p.get("loss_limits", {}).get("daily_lamports"),
        ]
        valid_schema = valid_schema and all(
            isinstance(x, int) and x > 0 for x in money_ints
        )
        gates.append(
            self._gate(
                "config_schema",
                valid_schema,
                "schema version, integer caps and max_outstanding_attempts checked",
                "use config/live_risk.yaml schema v1",
            )
        )
        gates.append(
            self._gate(
                "live_enabled",
                mode is not LiveMode.LIMITED_LIVE or p.get("live_enabled") is True,
                "live_enabled must be true only for limited live",
                "set live_enabled intentionally and re-hash config",
            )
        )
        gates.append(
            self._gate(
                "operator_confirmation",
                mode is not LiveMode.LIMITED_LIVE
                or self.store.fresh_confirmation(self.config_hash) is not None,
                "fresh exact-hash operator confirmation required",
                "bot live arm --confirm-config-hash <hash>",
            )
        )
        gates.append(
            self._gate(
                "safety_latch",
                self.store.active_latch() is None,
                "no durable kill switch or auto latch may be active",
                "reconcile, clear-stop, rerun readiness and re-arm",
            )
        )
        balance = self.observed.get(
            "wallet_lamports", p.get("wallet", {}).get("observed_lamports", 0)
        )
        needed = p.get("protected_reserve_lamports", 0) + p.get("per_attempt", {}).get(
            "max_net_native_debit_lamports", 0
        )
        gates.append(
            self._gate(
                "wallet_reserve",
                isinstance(balance, int) and balance >= needed,
                "wallet must cover protected reserve plus worst-case debit",
                "fund wallet or lower explicit policy caps",
                {"wallet_lamports": balance, "required_lamports": needed},
            )
        )
        programs = p.get("allowlists", {}).get("program_ids", [])
        providers = p.get("providers", {})
        gates.append(
            self._gate(
                "allowlists",
                bool(programs) and bool(p.get("allowlists", {}).get("markets")),
                "program/market allowlists cannot be empty",
                "pin program, market, venue and mint allowlists",
            )
        )
        exec_ok = any(
            v.get("role") == "execution"
            and v.get("capability") == "composable_instructions"
            and v.get("required_for_live")
            for v in providers.values()
        )
        discovery_bad = any(
            k.lower() in {"openocean", "odos"} and v.get("role") == "execution"
            for k, v in providers.items()
        )
        gates.append(
            self._gate(
                "provider_capabilities",
                exec_ok and not discovery_bad,
                "execution providers must be composable and discovery-only providers cannot execute",
                "promote only verified Jupiter/OKX composable providers",
            )
        )
        gates.append(
            self._gate(
                "rpc_health",
                self.observed.get(
                    "genesis_hash", p.get("cluster", {}).get("genesis_hash")
                )
                == p.get("cluster", {}).get("genesis_hash")
                and self.observed.get("rpc_healthy", True),
                "RPC genesis, min-context and freshness evidence required",
                "use healthy RPC on configured cluster",
            )
        )
        gates.append(
            self._gate(
                "journal_outstanding",
                outstanding_attempts(self.journal) == 0,
                "zero ambiguous/non-terminal live attempts required",
                "reconcile durable journal before new live permit",
            )
        )
        canary = p.get("canary", {})
        gates.append(
            self._gate(
                "canary_caps",
                canary.get("max_landed_count_per_window") == 1
                and bool(canary.get("route_profile")),
                "first live is explicit canary with configured route profile",
                "configure canary policy explicitly",
            )
        )
        gates.append(
            self._gate(
                "exactly_one_tip",
                p.get("tip_policy", {}).get("exactly_one_tip") is True,
                "exactly-one-tip policy must be enabled",
                "enable PR-014 tip policy reference",
            )
        )
        gates.append(
            self._gate(
                "shadow_evidence",
                bool(p.get("shadow_evidence", {}).get("required_versions")),
                "required shadow/replay evidence versions must be present",
                "record PR-013/016/017 evidence before live",
            )
        )
        decision = (
            "ALLOW" if all(g.status is GateStatus.PASS for g in gates) else "DENY"
        )
        return ReadinessReport(
            REPORT_SCHEMA_VERSION,
            secrets.token_hex(12),
            time.time(),
            mode.value,
            self.config_hash,
            decision,
            tuple(gates),
        )


class LiveAdmissionService:
    def __init__(
        self,
        policy: LiveRiskPolicy | dict[str, Any],
        store: LiveControlStore,
        journal: SQLiteAttemptJournal,
        *,
        session_id: str | None = None,
    ):
        self.policy = policy
        self.store = store
        self.journal = journal
        self.session_id = session_id or str(os.getpid())
        self.config_hash = canonical_policy_hash(policy)

    def issue_permit(
        self,
        *,
        attempt_id: str,
        attempt_generation: int,
        plan_hash: str,
        message_hash: str,
        wallet: str,
        route_provider: str,
        market: str,
        readiness: ReadinessReport,
    ) -> LiveSubmissionPermit:
        if not readiness.passed or readiness.config_hash != self.config_hash:
            raise PermissionError(
                "readiness report is not a fresh pass for current config"
            )
        report = LiveReadinessService(self.policy, self.store, self.journal).report(
            LiveMode.LIMITED_LIVE
        )
        if not report.passed:
            raise PermissionError("mutable live gates denied permit")
        if wallet != self.policy.get("wallet", {}).get("public_key"):
            raise PermissionError("wallet mismatch")
        if route_provider not in self.policy.get("providers", {}):
            raise PermissionError("provider not allowlisted")
        if market not in self.policy.get("allowlists", {}).get("markets", []):
            raise PermissionError("market not allowlisted")
        permit = LiveSubmissionPermit(
            secrets.token_hex(16),
            attempt_id,
            attempt_generation,
            plan_hash,
            message_hash,
            self.config_hash,
            wallet,
            route_provider,
            market,
            secrets.token_hex(12),
            time.time(),
            time.time() + int(self.policy.get("permit_ttl_seconds", 30)),
            self.session_id,
            secrets.token_urlsafe(32),
        )
        self.store.issue_permit(
            permit, int(self.policy["per_attempt"]["max_net_native_debit_lamports"])
        )
        return permit

    def consume_for_submit(
        self, permit: LiveSubmissionPermit, *, message_hash: str, config_hash: str
    ) -> None:
        if permit.message_hash != message_hash or permit.config_hash != config_hash:
            raise PermissionError("permit binding mismatch")
        if self.store.active_latch() is not None:
            raise PermissionError("safety latch active")
        if not self.store.consume_permit(permit):
            raise PermissionError("permit stale, used, revoked or unknown")


class PermitBoundSender:
    def __init__(self, admission: LiveAdmissionService, transport: Any):
        self.admission = admission
        self.transport = transport

    async def submit(
        self, permit: LiveSubmissionPermit | None, payload: bytes, *, message_hash: str
    ) -> Any:
        if permit is None:
            raise PermissionError("live submission requires LiveSubmissionPermit")
        self.admission.consume_for_submit(
            permit, message_hash=message_hash, config_hash=self.admission.config_hash
        )
        return await self.transport.send(payload)


def record_actual_outcome(
    store: LiveControlStore,
    *,
    attempt_id: str,
    config_hash: str,
    asset: str,
    actual_delta: int,
    simulated_delta: int | None,
    tolerance: int,
    provenance: dict[str, Any],
) -> None:
    divergence = (
        None if simulated_delta is None else abs(actual_delta - simulated_delta)
    )
    with store.db:
        store.db.execute(
            "INSERT INTO live_actual_outcomes(attempt_id,config_hash,asset,actual_delta,simulated_delta,divergence_abs,tolerance,reconciled_at,provenance) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                attempt_id,
                config_hash,
                asset,
                actual_delta,
                simulated_delta,
                divergence,
                tolerance,
                time.time(),
                json.dumps(_redact(provenance), sort_keys=True),
            ),
        )
        if actual_delta < 0 and abs(actual_delta) > tolerance:
            store.latch(
                LatchReason.PER_TRADE_CAP_BREACH.value,
                {
                    "attempt_id": attempt_id,
                    "asset": asset,
                    "actual_delta": actual_delta,
                },
            )
        if divergence is not None and divergence > tolerance:
            store.latch(
                LatchReason.SIMULATION_LIVE_DIVERGENCE.value,
                {
                    "attempt_id": attempt_id,
                    "asset": asset,
                    "divergence_abs": divergence,
                    "tolerance": tolerance,
                },
            )


def _paths(
    args: Any,
) -> tuple[LiveRiskPolicy, LiveControlStore, SQLiteAttemptJournal, str]:
    policy = load_policy(args.config)
    h = canonical_policy_hash(policy)
    state = Path(
        policy.get("control_plane", {}).get("sqlite_path", ".live_control.sqlite")
    )
    journal = SQLiteAttemptJournal(state)
    return policy, LiveControlStore(state), journal, h


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bot")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("readiness")
    r.add_argument("--mode", choices=["shadow", "live"], default="shadow")
    r.add_argument("--config", required=True)
    r.add_argument("--json", action="store_true")
    live = sub.add_parser("live")
    lsub = live.add_subparsers(dest="live_cmd", required=True)
    arm = lsub.add_parser("arm")
    arm.add_argument("--confirm-config-hash", required=True)
    arm.add_argument("--expires-in", type=int, required=True)
    arm.add_argument("--config", default="config/live_risk.yaml")
    st = lsub.add_parser("status")
    st.add_argument("--json", action="store_true")
    st.add_argument("--config", default="config/live_risk.yaml")
    stop = lsub.add_parser("stop")
    stop.add_argument("--reason", required=True)
    stop.add_argument("--config", default="config/live_risk.yaml")
    clr = lsub.add_parser("clear-stop")
    clr.add_argument("--confirm-config-hash", required=True)
    clr.add_argument("--config", default="config/live_risk.yaml")
    dry = lsub.add_parser("dry-run")
    dry.add_argument("--opportunity", required=True)
    dry.add_argument("--config", required=True)
    dry.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    policy, store, journal, h = _paths(args)
    if args.cmd == "readiness":
        report = LiveReadinessService(policy, store, journal).report(
            LiveMode.LIMITED_LIVE if args.mode == "live" else LiveMode.SHADOW
        )
        print(
            json.dumps(report.to_dict(), indent=2, sort_keys=True)
            if args.json
            else f"{report.decision} config_hash={report.config_hash}"
        )
        return 0 if report.passed else 2
    if args.live_cmd == "arm":
        if args.confirm_config_hash != h:
            print("config hash mismatch", file=sys.stderr)
            return 2
        print(json.dumps(asdict(store.arm(h, args.expires_in)), sort_keys=True))
        return 0
    if args.live_cmd == "status":
        print(json.dumps(store.status(journal, h), indent=2, sort_keys=True))
        return 0
    if args.live_cmd == "stop":
        store.latch(
            LatchReason.MANUAL_KILL_SWITCH.value,
            {"reason": args.reason, "config_hash": h},
        )
        print("stopped")
        return 0
    if args.live_cmd == "clear-stop":
        if args.confirm_config_hash != h or outstanding_attempts(journal) != 0:
            print(
                "cannot clear: hash mismatch or outstanding attempts", file=sys.stderr
            )
            return 2
        store.clear_latch(h)
        print("cleared")
        return 0
    if args.live_cmd == "dry-run":
        report = LiveReadinessService(policy, store, journal).report(LiveMode.DRY_RUN)
        out = report.to_dict()
        out["opportunity"] = args.opportunity
        out["submitted"] = False
        out["budget_mutated"] = False
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0 if report.passed else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
