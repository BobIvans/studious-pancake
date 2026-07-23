"""SUPER-MPR-B durable economic authority and evidence primitives.

This module is intentionally sender-free.  It models paper/shadow economics as a
single durable authority that can be tested without RPC, Jito, signer or wallet
access.  Real provider/RPC integration must feed normalized/digested evidence
into this authority; synthetic evidence is never accepted for promotion.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Iterable, Mapping, Sequence

ECONOMIC_AUTHORITY_SCHEMA = "super-mpr-b.economic-authority.v1"
SHADOW_SOAK_SCHEMA = "super-mpr-b.shadow-soak-report.v1"
EVIDENCE_BUNDLE_SCHEMA = "super-mpr-b.evidence-bundle.v1"

REQUIRED_STATES: tuple[str, ...] = (
    "DISCOVERED",
    "NORMALIZED",
    "REJECTED",
    "ADMITTED",
    "RESERVED",
    "SIMULATED",
    "PAPER_FILLED",
    "PAPER_SETTLED",
    "EXPIRED",
    "RECONCILED",
    "FAILED",
)

REQUIRED_DIGEST_IDS: tuple[str, ...] = (
    "opportunity_id",
    "route_digest",
    "provider_digest",
    "quote_digest",
    "simulation_digest",
    "reservation_id",
    "capital_ledger_id",
    "paper_fill_id",
    "settlement_digest",
    "run_trace_id",
)

REQUIRED_RELEASE_ARTIFACTS: tuple[str, ...] = (
    "wheel_digest.json",
    "image_digest.json",
    "sbom.json",
    "lock_digest.json",
    "config_generation_digest.json",
    "capability_manifest_digest.json",
    "program_idl_hashes.json",
    "database_schema_fingerprint.json",
)

REQUIRED_SHADOW_SOAK_FIELDS: tuple[str, ...] = (
    "start_time",
    "end_time",
    "duration",
    "runtime_version",
    "wheel_digest",
    "config_digest",
    "provider_set",
    "rpc_set",
    "opportunities_seen",
    "opportunities_rejected_by_reason",
    "opportunities_admitted",
    "paper_simulations",
    "paper_settlements",
    "expired_quotes",
    "provider_errors",
    "rpc_errors",
    "restart_count",
    "recovery_count",
    "capital_ledger_reconciled",
    "max_drawdown_paper",
    "gross_pnl_paper",
    "net_pnl_paper",
    "fee_rent_repayment_impact",
)

REQUIRED_FAULT_SCENARIOS: tuple[str, ...] = (
    "provider_timeout",
    "provider_stale_slot",
    "provider_malformed_json",
    "provider_disagreement",
    "rpc_fork_stale_context",
    "blockhash_expiry",
    "database_write_failure",
    "crash_after_reservation",
    "crash_after_simulation",
    "crash_before_settlement",
    "webhook_duplicate_delivery",
    "webhook_missing_delivery",
    "quota_exhaustion",
)

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "DISCOVERED": frozenset({"NORMALIZED", "REJECTED", "FAILED"}),
    "NORMALIZED": frozenset({"ADMITTED", "REJECTED", "EXPIRED", "FAILED"}),
    "ADMITTED": frozenset({"RESERVED", "REJECTED", "EXPIRED", "FAILED"}),
    "RESERVED": frozenset({"SIMULATED", "REJECTED", "EXPIRED", "FAILED"}),
    "SIMULATED": frozenset({"PAPER_FILLED", "REJECTED", "EXPIRED", "FAILED"}),
    "PAPER_FILLED": frozenset({"PAPER_SETTLED", "FAILED"}),
    "PAPER_SETTLED": frozenset({"RECONCILED"}),
    "REJECTED": frozenset({"RECONCILED"}),
    "EXPIRED": frozenset({"RECONCILED"}),
    "FAILED": frozenset({"RECONCILED"}),
    "RECONCILED": frozenset(),
}

_TERMINAL_RELEASE_STATES = frozenset({"REJECTED", "EXPIRED", "FAILED", "RECONCILED"})


class EvidenceKind(StrEnum):
    REAL = "real"
    SYNTHETIC = "synthetic"
    PLACEHOLDER = "placeholder"


@dataclass(frozen=True, slots=True)
class EconomicEvent:
    state: str
    event_digest: str
    observed_at_unix_ns: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EconomicIdentity:
    opportunity_id: str
    route_digest: str
    provider_digest: str
    quote_digest: str
    simulation_digest: str
    reservation_id: str
    capital_ledger_id: str
    paper_fill_id: str
    settlement_digest: str
    run_trace_id: str

    @classmethod
    def derive(cls, *, run_trace_id: str, opportunity_payload: Mapping[str, Any]) -> "EconomicIdentity":
        base = _sha256_json({"run_trace_id": run_trace_id, "opportunity": opportunity_payload})
        return cls(
            opportunity_id=_domain_digest("opportunity", base),
            route_digest=_domain_digest("route", base),
            provider_digest=_domain_digest("provider", base),
            quote_digest=_domain_digest("quote", base),
            simulation_digest=_domain_digest("simulation", base),
            reservation_id=_domain_digest("reservation", base),
            capital_ledger_id=_domain_digest("capital-ledger", base),
            paper_fill_id=_domain_digest("paper-fill", base),
            settlement_digest=_domain_digest("settlement", base),
            run_trace_id=run_trace_id,
        )

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PaperAccounting:
    estimated_swap_output_lamports: int
    slippage_lamports: int
    network_fee_lamports: int
    priority_fee_lamports: int
    ata_rent_lamports: int
    wsol_lifecycle_lamports: int
    flashloan_repayment_lamports: int
    borrow_repay_fee_lamports: int
    provider_drift_lamports: int
    quote_expiry_cost_lamports: int
    failed_attempt_cost_lamports: int
    gross_input_lamports: int

    @property
    def gross_pnl_lamports(self) -> int:
        return self.estimated_swap_output_lamports - self.gross_input_lamports

    @property
    def total_cost_lamports(self) -> int:
        return (
            self.slippage_lamports
            + self.network_fee_lamports
            + self.priority_fee_lamports
            + self.ata_rent_lamports
            + self.wsol_lifecycle_lamports
            + self.flashloan_repayment_lamports
            + self.borrow_repay_fee_lamports
            + self.provider_drift_lamports
            + self.quote_expiry_cost_lamports
            + self.failed_attempt_cost_lamports
        )

    @property
    def net_pnl_lamports(self) -> int:
        return self.gross_pnl_lamports - self.total_cost_lamports

    def to_dict(self) -> dict[str, int]:
        payload = asdict(self)
        payload["gross_pnl_lamports"] = self.gross_pnl_lamports
        payload["total_cost_lamports"] = self.total_cost_lamports
        payload["net_pnl_lamports"] = self.net_pnl_lamports
        return payload


def assert_net_paper_profit(accounting: PaperAccounting) -> bool:
    """Return true only when net PnL is positive after every mandatory cost."""

    return accounting.net_pnl_lamports > 0


@dataclass(frozen=True, slots=True)
class ReservationRecord:
    reservation_id: str
    opportunity_id: str
    amount_lamports: int
    expires_at_unix_ns: int
    state: str
    request_digest: str
    created_at_unix_ns: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DurableCapitalLedger:
    """Small atomic JSON ledger for restart-safe paper capital reservations."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._payload = self._load()

    def reserve(
        self,
        *,
        reservation_id: str,
        opportunity_id: str,
        amount_lamports: int,
        expires_at_unix_ns: int,
        request_payload: Mapping[str, Any],
        now_unix_ns: int | None = None,
    ) -> ReservationRecord:
        if amount_lamports <= 0:
            raise ValueError("reservation amount must be positive")
        request_digest = _sha256_json(request_payload)
        existing = self._reservations().get(reservation_id)
        if existing is not None:
            if existing.get("request_digest") == request_digest:
                return ReservationRecord(**existing)
            raise ValueError("reservation replay conflict")
        record = ReservationRecord(
            reservation_id=reservation_id,
            opportunity_id=opportunity_id,
            amount_lamports=amount_lamports,
            expires_at_unix_ns=expires_at_unix_ns,
            state="RESERVED",
            request_digest=request_digest,
            created_at_unix_ns=now_unix_ns or time.time_ns(),
        )
        self._reservations()[reservation_id] = record.to_dict()
        self._write()
        return record

    def release(self, reservation_id: str, *, reason: str) -> ReservationRecord:
        raw = self._reservations().get(reservation_id)
        if raw is None:
            raise KeyError(reservation_id)
        if raw["state"] == "RESERVED":
            raw = dict(raw)
            raw["state"] = "RELEASED"
            raw["release_reason"] = reason
            self._reservations()[reservation_id] = raw
            self._write()
        return ReservationRecord(**{key: raw[key] for key in ReservationRecord.__slots__})

    def reconcile_expired(self, *, now_unix_ns: int) -> tuple[str, ...]:
        reconciled: list[str] = []
        for reservation_id, raw in list(self._reservations().items()):
            if raw["state"] == "RESERVED" and int(raw["expires_at_unix_ns"]) <= now_unix_ns:
                updated = dict(raw)
                updated["state"] = "EXPIRED"
                self._reservations()[reservation_id] = updated
                reconciled.append(reservation_id)
        if reconciled:
            self._write()
        return tuple(sorted(reconciled))

    def active_reserved_lamports(self) -> int:
        return sum(
            int(raw["amount_lamports"])
            for raw in self._reservations().values()
            if raw["state"] == "RESERVED"
        )

    def snapshot(self) -> dict[str, Any]:
        return json.loads(_canonical_json(self._payload).decode("utf-8"))

    def _reservations(self) -> dict[str, dict[str, Any]]:
        return self._payload.setdefault("reservations", {})

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": ECONOMIC_AUTHORITY_SCHEMA, "reservations": {}}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != ECONOMIC_AUTHORITY_SCHEMA:
            raise ValueError("unsupported capital ledger schema")
        if not isinstance(payload.get("reservations"), dict):
            raise ValueError("reservations must be an object")
        return payload

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = _canonical_json(self._payload)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "wb", closefd=True) as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise


@dataclass(frozen=True, slots=True)
class EconomicAuthoritySnapshot:
    schema_version: str
    identity: EconomicIdentity
    current_state: str
    events: tuple[EconomicEvent, ...]
    accounting: PaperAccounting | None = None
    evidence_kind: str = EvidenceKind.REAL.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "identity": self.identity.to_dict(),
            "current_state": self.current_state,
            "events": [event.to_dict() for event in self.events],
            "accounting": self.accounting.to_dict() if self.accounting else None,
            "evidence_kind": self.evidence_kind,
        }


def validate_economic_authority_snapshot(snapshot: Mapping[str, Any]) -> tuple[str, ...]:
    blockers: list[str] = []
    if snapshot.get("schema_version") != ECONOMIC_AUTHORITY_SCHEMA:
        blockers.append("ECONOMIC_AUTHORITY_SCHEMA_INVALID")
    identity = snapshot.get("identity")
    if not isinstance(identity, Mapping):
        blockers.append("ECONOMIC_IDENTITY_MISSING")
    else:
        for key in REQUIRED_DIGEST_IDS:
            value = identity.get(key)
            if not isinstance(value, str) or not value:
                blockers.append(f"ECONOMIC_IDENTITY_{key.upper()}_MISSING")
    if snapshot.get("evidence_kind") != EvidenceKind.REAL.value:
        blockers.append("SYNTHETIC_ECONOMIC_EVIDENCE_CANNOT_PROMOTE")
    events = snapshot.get("events")
    if not isinstance(events, list) or not events:
        blockers.append("ECONOMIC_EVENTS_MISSING")
        return tuple(dict.fromkeys(blockers))
    states: list[str] = []
    for event in events:
        if not isinstance(event, Mapping):
            blockers.append("ECONOMIC_EVENT_INVALID")
            continue
        state = event.get("state")
        if state not in REQUIRED_STATES:
            blockers.append("ECONOMIC_EVENT_STATE_INVALID")
            continue
        states.append(str(state))
    for previous, current in zip(states, states[1:], strict=False):
        if current not in _ALLOWED_TRANSITIONS.get(previous, frozenset()):
            blockers.append(f"ECONOMIC_TRANSITION_INVALID:{previous}->{current}")
    if snapshot.get("current_state") != (states[-1] if states else None):
        blockers.append("ECONOMIC_CURRENT_STATE_MISMATCH")
    accounting = snapshot.get("accounting")
    if accounting is not None:
        if not isinstance(accounting, Mapping):
            blockers.append("PAPER_ACCOUNTING_INVALID")
        elif accounting.get("net_pnl_lamports") is None:
            blockers.append("PAPER_ACCOUNTING_NET_PNL_MISSING")
    return tuple(dict.fromkeys(blockers))


def build_shadow_soak_report(
    *,
    runtime_version: str,
    wheel_digest: str,
    config_digest: str,
    provider_set: Sequence[str],
    rpc_set: Sequence[str],
    opportunities_seen: int,
    opportunities_rejected_by_reason: Mapping[str, int],
    opportunities_admitted: int,
    paper_simulations: int,
    paper_settlements: int,
    expired_quotes: int,
    provider_errors: int,
    rpc_errors: int,
    restart_count: int,
    recovery_count: int,
    capital_ledger_reconciled: bool,
    max_drawdown_paper: int,
    gross_pnl_paper: int,
    net_pnl_paper: int,
    fee_rent_repayment_impact: int,
    start_time: str = "1970-01-01T00:00:00Z",
    end_time: str = "1970-01-01T00:00:01Z",
) -> dict[str, Any]:
    return {
        "schema_version": SHADOW_SOAK_SCHEMA,
        "start_time": start_time,
        "end_time": end_time,
        "duration": "PT1S",
        "runtime_version": runtime_version,
        "wheel_digest": wheel_digest,
        "config_digest": config_digest,
        "provider_set": list(provider_set),
        "rpc_set": list(rpc_set),
        "opportunities_seen": opportunities_seen,
        "opportunities_rejected_by_reason": dict(opportunities_rejected_by_reason),
        "opportunities_admitted": opportunities_admitted,
        "paper_simulations": paper_simulations,
        "paper_settlements": paper_settlements,
        "expired_quotes": expired_quotes,
        "provider_errors": provider_errors,
        "rpc_errors": rpc_errors,
        "restart_count": restart_count,
        "recovery_count": recovery_count,
        "capital_ledger_reconciled": capital_ledger_reconciled,
        "max_drawdown_paper": max_drawdown_paper,
        "gross_pnl_paper": gross_pnl_paper,
        "net_pnl_paper": net_pnl_paper,
        "fee_rent_repayment_impact": fee_rent_repayment_impact,
    }


def validate_shadow_soak_report(report: Mapping[str, Any]) -> tuple[str, ...]:
    blockers: list[str] = []
    if report.get("schema_version") != SHADOW_SOAK_SCHEMA:
        blockers.append("SHADOW_SOAK_SCHEMA_INVALID")
    missing = [field for field in REQUIRED_SHADOW_SOAK_FIELDS if field not in report]
    blockers.extend(f"SHADOW_SOAK_FIELD_MISSING:{field}" for field in missing)
    for field in (
        "opportunities_seen",
        "opportunities_admitted",
        "paper_simulations",
        "paper_settlements",
        "expired_quotes",
        "provider_errors",
        "rpc_errors",
        "restart_count",
        "recovery_count",
        "max_drawdown_paper",
        "gross_pnl_paper",
        "net_pnl_paper",
        "fee_rent_repayment_impact",
    ):
        value = report.get(field)
        if not isinstance(value, int) or value < 0 and field not in {"net_pnl_paper"}:
            blockers.append(f"SHADOW_SOAK_NUMERIC_FIELD_INVALID:{field}")
    if report.get("capital_ledger_reconciled") is not True:
        blockers.append("SHADOW_SOAK_CAPITAL_LEDGER_NOT_RECONCILED")
    return tuple(dict.fromkeys(blockers))


def evaluate_super_mpr_b_evidence(
    root: str | os.PathLike[str],
    *,
    evidence_path: str | os.PathLike[str] = "release_artifacts/super_mpr_b_evidence.json",
) -> dict[str, Any]:
    root_path = Path(root)
    bundle_path = root_path / evidence_path
    blockers: list[str] = []
    if not bundle_path.is_file():
        return {
            "schema_version": EVIDENCE_BUNDLE_SCHEMA,
            "accepted": False,
            "evidence_path": str(Path(evidence_path).as_posix()),
            "blockers": ("SUPER_MPR_B_EVIDENCE_MISSING",),
            "artifact_status": {},
        }
    try:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {
            "schema_version": EVIDENCE_BUNDLE_SCHEMA,
            "accepted": False,
            "evidence_path": str(Path(evidence_path).as_posix()),
            "blockers": ("SUPER_MPR_B_EVIDENCE_INVALID_JSON",),
            "artifact_status": {},
        }
    if not isinstance(bundle, Mapping):
        blockers.append("SUPER_MPR_B_EVIDENCE_NOT_OBJECT")
        bundle = {}
    if bundle.get("schema_version") != EVIDENCE_BUNDLE_SCHEMA:
        blockers.append("SUPER_MPR_B_EVIDENCE_SCHEMA_INVALID")
    if bundle.get("evidence_kind") != EvidenceKind.REAL.value:
        blockers.append("SYNTHETIC_EVIDENCE_CANNOT_PROMOTE")
    artifact_status: dict[str, str] = {}
    for relative in REQUIRED_RELEASE_ARTIFACTS:
        artifact = root_path / "release_artifacts" / relative
        artifact_status[relative] = "present" if artifact.is_file() else "missing"
        if not artifact.is_file():
            blockers.append(f"RELEASE_ARTIFACT_MISSING:{relative}")
    shadow_report = bundle.get("shadow_soak_report")
    if isinstance(shadow_report, Mapping):
        blockers.extend(validate_shadow_soak_report(shadow_report))
    else:
        blockers.append("SHADOW_SOAK_REPORT_MISSING")
    authority = bundle.get("economic_authority")
    if isinstance(authority, Mapping):
        blockers.extend(validate_economic_authority_snapshot(authority))
    else:
        blockers.append("ECONOMIC_AUTHORITY_SNAPSHOT_MISSING")
    fault = bundle.get("fault_injection")
    if isinstance(fault, Mapping):
        covered = set(str(item) for item in fault.get("covered", ()))
        missing_faults = sorted(set(REQUIRED_FAULT_SCENARIOS) - covered)
        blockers.extend(f"FAULT_SCENARIO_MISSING:{item}" for item in missing_faults)
    else:
        blockers.append("FAULT_INJECTION_REPORT_MISSING")
    backup = bundle.get("backup_restore")
    if not isinstance(backup, Mapping) or backup.get("restore_verified") is not True:
        blockers.append("BACKUP_RESTORE_NOT_VERIFIED")
    return {
        "schema_version": EVIDENCE_BUNDLE_SCHEMA,
        "accepted": not blockers,
        "evidence_path": str(Path(evidence_path).as_posix()),
        "blockers": tuple(dict.fromkeys(blockers)),
        "artifact_status": artifact_status,
    }


def _sha256_json(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _domain_digest(domain: str, value: str) -> str:
    return "sha256:" + hashlib.sha256(f"{domain}:{value}".encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
