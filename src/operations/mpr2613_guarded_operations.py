"""MPR-2613 guarded production operations.

This module is a post-release operating authority.  It does not accept a release,
load trading secrets, sign, submit, clear latches, or increase capital.  It can
materialize an already accepted release scope into a durable operating envelope,
re-check current-state admission, account operational error budgets, and move the
runtime only to equal-or-lower authority automatically.

MPR-2613 is a NEW_PROPOSED_EXTENSION after the historical MPR-2601..2612
sequence.  Until an actual MPR-2612 release decision is supplied by the accepted
release gate, production activation remains BLOCKED_INTEGRATION.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import IntEnum, StrEnum
import hashlib
import json
import re
import sqlite3
from typing import Mapping

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SCHEMA_VERSION = "mpr2613.guarded-operations.v1"
ENVELOPE_SCHEMA_VERSION = "mpr2613.operating-envelope.v1"


class GuardedOperationsError(RuntimeError):
    """Base error for guarded production operations."""


class IntegrationBlocked(GuardedOperationsError):
    """Required accepted upstream authority is unavailable."""


class AdmissionDenied(GuardedOperationsError):
    """Current state does not permit a new production effect."""


class StateTransitionDenied(GuardedOperationsError):
    """Requested operating-state transition would widen authority."""


class OperatingState(IntEnum):
    """Ordered from least to most production authority."""

    LATCHED = 0
    DORMANT = 1
    SHADOW_ONLY = 2
    DRAINING = 3
    DEGRADED = 4
    ACTIVE = 5


class ScaleTier(StrEnum):
    CANARY = "CANARY"
    PRODUCTION_TIER_1 = "PRODUCTION_TIER_1"
    PRODUCTION_TIER_2 = "PRODUCTION_TIER_2"


@dataclass(frozen=True, slots=True)
class MonetaryCaps:
    principal_atoms: int
    fee_atoms: int
    tip_atoms: int
    rent_atoms: int
    realized_loss_atoms: int
    unresolved_exposure_atoms: int
    protected_reserve_atoms: int

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class ResourceCaps:
    max_attempts: int
    max_concurrency: int
    max_pending_reconciliations: int
    max_db_backlog: int

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class AcceptedReleaseIdentity:
    """Opaque evidence emitted by the accepted MPR-2612 release authority."""

    release_decision_hash: str
    tree_hash: str
    wheel_hash: str
    image_hash: str
    config_hash: str
    policy_hash: str
    schema_hash: str
    profile_hash: str
    accepted_at_utc: str
    expires_at_utc: str
    accepted: bool

    def __post_init__(self) -> None:
        for name in (
            "release_decision_hash",
            "tree_hash",
            "wheel_hash",
            "image_hash",
            "config_hash",
            "policy_hash",
            "schema_hash",
            "profile_hash",
        ):
            _require_sha256(getattr(self, name), name)
        if type(self.accepted) is not bool:
            raise ValueError("accepted must be boolean")
        start = _parse_utc(self.accepted_at_utc)
        end = _parse_utc(self.expires_at_utc)
        if end <= start:
            raise ValueError("release expiry must follow acceptance")


@dataclass(frozen=True, slots=True)
class OperatingEnvelope:
    release: AcceptedReleaseIdentity
    cluster_genesis_hash: str
    wallet_identity_hash: str
    payer_identity_hash: str
    strategy: str
    lender: str
    router: str
    program_set_hash: str
    provider_set_hash: str
    credential_generation_hash: str
    signer_generation_hash: str
    submission_generation_hash: str
    monetary_caps: MonetaryCaps
    resource_caps: ResourceCaps
    tier: ScaleTier
    issued_at_utc: str
    expires_at_utc: str
    generation: int
    schema_version: str = ENVELOPE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ENVELOPE_SCHEMA_VERSION:
            raise ValueError("unsupported operating envelope schema")
        if self.strategy != "circular_arbitrage":
            raise ValueError("MPR-2613 v1 strategy scope must remain circular_arbitrage")
        if self.lender != "MarginFi" or self.router != "Jupiter":
            raise ValueError("MPR-2613 v1 protocol scope must remain MarginFi + Jupiter")
        for name in (
            "cluster_genesis_hash",
            "wallet_identity_hash",
            "payer_identity_hash",
            "program_set_hash",
            "provider_set_hash",
            "credential_generation_hash",
            "signer_generation_hash",
            "submission_generation_hash",
        ):
            _require_sha256(getattr(self, name), name)
        if isinstance(self.generation, bool) or self.generation <= 0:
            raise ValueError("generation must be positive")
        start = _parse_utc(self.issued_at_utc)
        end = _parse_utc(self.expires_at_utc)
        if end <= start:
            raise ValueError("envelope expiry must follow issue time")
        if end > _parse_utc(self.release.expires_at_utc):
            raise ValueError("envelope cannot outlive accepted release")

    @property
    def envelope_hash(self) -> str:
        return _hash_json(
            {
                "schema": self.schema_version,
                "release": asdict(self.release),
                "cluster_genesis_hash": self.cluster_genesis_hash,
                "wallet_identity_hash": self.wallet_identity_hash,
                "payer_identity_hash": self.payer_identity_hash,
                "strategy": self.strategy,
                "lender": self.lender,
                "router": self.router,
                "program_set_hash": self.program_set_hash,
                "provider_set_hash": self.provider_set_hash,
                "credential_generation_hash": self.credential_generation_hash,
                "signer_generation_hash": self.signer_generation_hash,
                "submission_generation_hash": self.submission_generation_hash,
                "monetary_caps": asdict(self.monetary_caps),
                "resource_caps": asdict(self.resource_caps),
                "tier": self.tier.value,
                "issued_at_utc": self.issued_at_utc,
                "expires_at_utc": self.expires_at_utc,
                "generation": self.generation,
            }
        )


@dataclass(frozen=True, slots=True)
class CurrentAdmissionFacts:
    release_decision_hash: str
    config_hash: str
    policy_hash: str
    profile_hash: str
    cluster_genesis_hash: str
    wallet_identity_hash: str
    provider_set_hash: str
    signer_generation_hash: str
    submission_generation_hash: str
    rooted_data_fresh: bool
    protocol_evidence_valid: bool
    exact_candidate_valid: bool
    firewall_allowed: bool
    final_simulation_valid: bool
    conservative_economics_valid: bool
    unresolved_attempts: int
    current_finalized_balance_atoms: int
    committed_capital_atoms: int
    realized_loss_atoms: int
    fee_spend_atoms: int
    tip_spend_atoms: int
    rent_spend_atoms: int
    unresolved_exposure_atoms: int
    open_hard_latches: int


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    allowed: bool
    reason: str
    envelope_hash: str
    state: OperatingState
    max_additional_principal_atoms: int


@dataclass(frozen=True, slots=True)
class SLOBudget:
    metric: str
    window: str
    denominator: str
    min_samples: int
    threshold: int
    consumed: int
    hard_failure: bool = False

    def __post_init__(self) -> None:
        if not self.metric.strip() or not self.window.strip() or not self.denominator.strip():
            raise ValueError("SLO identity fields are required")
        for name in ("min_samples", "threshold", "consumed"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be non-negative integer")


def install_guarded_operations_schema(db: sqlite3.Connection) -> None:
    """Explicit schema installation; caller owns migration transaction."""

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS mpr2613_operating_envelopes(
          envelope_hash TEXT PRIMARY KEY,
          release_decision_hash TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          generation INTEGER NOT NULL CHECK(generation>0),
          tier TEXT NOT NULL,
          issued_at_utc TEXT NOT NULL,
          expires_at_utc TEXT NOT NULL,
          accepted_release INTEGER NOT NULL CHECK(accepted_release IN (0,1))
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS mpr2613_operating_state(
          scope_key TEXT PRIMARY KEY,
          envelope_hash TEXT NOT NULL,
          state INTEGER NOT NULL,
          reason TEXT NOT NULL,
          writer_generation INTEGER NOT NULL CHECK(writer_generation>0),
          updated_at_utc TEXT NOT NULL,
          FOREIGN KEY(envelope_hash) REFERENCES mpr2613_operating_envelopes(envelope_hash)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS mpr2613_state_events(
          event_id INTEGER PRIMARY KEY AUTOINCREMENT,
          scope_key TEXT NOT NULL,
          envelope_hash TEXT NOT NULL,
          from_state INTEGER,
          to_state INTEGER NOT NULL,
          reason TEXT NOT NULL,
          automated INTEGER NOT NULL CHECK(automated IN (0,1)),
          created_at_utc TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS mpr2613_slo_budgets(
          envelope_hash TEXT NOT NULL,
          metric TEXT NOT NULL,
          window_id TEXT NOT NULL,
          denominator TEXT NOT NULL,
          min_samples INTEGER NOT NULL,
          threshold INTEGER NOT NULL,
          consumed INTEGER NOT NULL,
          hard_failure INTEGER NOT NULL CHECK(hard_failure IN (0,1)),
          PRIMARY KEY(envelope_hash,metric,window_id)
        )
        """
    )


def persist_envelope(db: sqlite3.Connection, envelope: OperatingEnvelope) -> str:
    """Persist an envelope only when it is backed by accepted MPR-2612 evidence."""

    if not envelope.release.accepted:
        raise IntegrationBlocked("MPR2613_ACCEPTED_MPR2612_REQUIRED")
    now = _parse_utc(envelope.issued_at_utc)
    if now < _parse_utc(envelope.release.accepted_at_utc):
        raise IntegrationBlocked("MPR2613_ENVELOPE_PRECEDES_RELEASE_ACCEPTANCE")
    envelope_hash = envelope.envelope_hash
    payload = json.dumps(
        _jsonable(asdict(envelope)), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    try:
        db.execute(
            """
            INSERT INTO mpr2613_operating_envelopes(
              envelope_hash,release_decision_hash,payload_json,generation,tier,
              issued_at_utc,expires_at_utc,accepted_release
            ) VALUES(?,?,?,?,?,?,?,1)
            """,
            (
                envelope_hash,
                envelope.release.release_decision_hash,
                payload,
                envelope.generation,
                envelope.tier.value,
                envelope.issued_at_utc,
                envelope.expires_at_utc,
            ),
        )
    except sqlite3.IntegrityError as exc:
        row = db.execute(
            "SELECT payload_json FROM mpr2613_operating_envelopes WHERE envelope_hash=?",
            (envelope_hash,),
        ).fetchone()
        if row is None or str(row[0]) != payload:
            raise IntegrationBlocked("MPR2613_ENVELOPE_IDENTITY_CONFLICT") from exc
    return envelope_hash


def initialize_scope(
    db: sqlite3.Connection,
    *,
    scope_key: str,
    envelope_hash: str,
    writer_generation: int,
    current_utc: str,
) -> None:
    """A newly materialized scope starts DORMANT, never ACTIVE."""

    if not scope_key.strip() or writer_generation <= 0:
        raise ValueError("scope_key and positive writer_generation are required")
    if db.execute(
        "SELECT 1 FROM mpr2613_operating_envelopes WHERE envelope_hash=? AND accepted_release=1",
        (envelope_hash,),
    ).fetchone() is None:
        raise IntegrationBlocked("MPR2613_ACCEPTED_ENVELOPE_REQUIRED")
    db.execute(
        "INSERT INTO mpr2613_operating_state VALUES(?,?,?,?,?,?)",
        (
            scope_key,
            envelope_hash,
            int(OperatingState.DORMANT),
            "awaiting-current-state-admission",
            writer_generation,
            current_utc,
        ),
    )
    _append_event(
        db,
        scope_key=scope_key,
        envelope_hash=envelope_hash,
        from_state=None,
        to_state=OperatingState.DORMANT,
        reason="scope_initialized_dormant",
        automated=False,
        current_utc=current_utc,
    )


def transition_state(
    db: sqlite3.Connection,
    *,
    scope_key: str,
    target_state: OperatingState,
    reason: str,
    writer_generation: int,
    current_utc: str,
    automated: bool,
    upward_authorization_hash: str | None = None,
) -> OperatingState:
    """Durably transition state; automation can only reduce authority."""

    row = db.execute(
        "SELECT envelope_hash,state,writer_generation FROM mpr2613_operating_state WHERE scope_key=?",
        (scope_key,),
    ).fetchone()
    if row is None:
        raise StateTransitionDenied("MPR2613_SCOPE_NOT_INITIALIZED")
    envelope_hash = str(row[0])
    current = OperatingState(int(row[1]))
    if int(row[2]) != writer_generation:
        raise StateTransitionDenied("MPR2613_STALE_WRITER_GENERATION")
    upward = target_state > current
    if upward and automated:
        raise StateTransitionDenied("MPR2613_AUTOMATIC_AUTHORITY_INCREASE_FORBIDDEN")
    if upward:
        if upward_authorization_hash is None:
            raise StateTransitionDenied("MPR2613_UPWARD_HUMAN_AUTHORIZATION_REQUIRED")
        _require_sha256(upward_authorization_hash, "upward_authorization_hash")
    if not reason.strip():
        raise ValueError("reason is required")
    cur = db.execute(
        """
        UPDATE mpr2613_operating_state SET state=?,reason=?,updated_at_utc=?
        WHERE scope_key=? AND writer_generation=? AND state=?
        """,
        (int(target_state), reason, current_utc, scope_key, writer_generation, int(current)),
    )
    if cur.rowcount != 1:
        raise StateTransitionDenied("MPR2613_STATE_CAS_CONFLICT")
    _append_event(
        db,
        scope_key=scope_key,
        envelope_hash=envelope_hash,
        from_state=current,
        to_state=target_state,
        reason=reason,
        automated=automated,
        current_utc=current_utc,
    )
    return target_state


def evaluate_current_admission(
    db: sqlite3.Connection,
    *,
    scope_key: str,
    envelope: OperatingEnvelope,
    facts: CurrentAdmissionFacts,
    current_utc: str,
    writer_generation: int,
) -> AdmissionDecision:
    """Re-check current production facts immediately before effect handoff."""

    row = db.execute(
        "SELECT envelope_hash,state,writer_generation FROM mpr2613_operating_state WHERE scope_key=?",
        (scope_key,),
    ).fetchone()
    if row is None:
        raise AdmissionDenied("MPR2613_SCOPE_NOT_INITIALIZED")
    state = OperatingState(int(row[1]))
    if str(row[0]) != envelope.envelope_hash:
        raise AdmissionDenied("MPR2613_ENVELOPE_CHANGED")
    if int(row[2]) != writer_generation:
        raise AdmissionDenied("MPR2613_STALE_WRITER_GENERATION")
    now = _parse_utc(current_utc)
    if not envelope.release.accepted:
        raise AdmissionDenied("MPR2613_RELEASE_NOT_ACCEPTED")
    if now >= _parse_utc(envelope.release.expires_at_utc) or now >= _parse_utc(envelope.expires_at_utc):
        raise AdmissionDenied("MPR2613_ENVELOPE_EXPIRED")
    if state is not OperatingState.ACTIVE:
        return AdmissionDecision(False, f"state:{state.name}", envelope.envelope_hash, state, 0)

    exact = {
        "release_decision_hash": envelope.release.release_decision_hash,
        "config_hash": envelope.release.config_hash,
        "policy_hash": envelope.release.policy_hash,
        "profile_hash": envelope.release.profile_hash,
        "cluster_genesis_hash": envelope.cluster_genesis_hash,
        "wallet_identity_hash": envelope.wallet_identity_hash,
        "provider_set_hash": envelope.provider_set_hash,
        "signer_generation_hash": envelope.signer_generation_hash,
        "submission_generation_hash": envelope.submission_generation_hash,
    }
    for name, expected in exact.items():
        if getattr(facts, name) != expected:
            return AdmissionDecision(False, f"identity-drift:{name}", envelope.envelope_hash, state, 0)
    hard_checks = {
        "rooted-data-stale": facts.rooted_data_fresh,
        "protocol-evidence-invalid": facts.protocol_evidence_valid,
        "candidate-invalid": facts.exact_candidate_valid,
        "firewall-denied": facts.firewall_allowed,
        "final-simulation-invalid": facts.final_simulation_valid,
        "economics-invalid": facts.conservative_economics_valid,
    }
    for reason, ok in hard_checks.items():
        if not ok:
            return AdmissionDecision(False, reason, envelope.envelope_hash, state, 0)
    if facts.open_hard_latches > 0:
        return AdmissionDecision(False, "hard-latch-open", envelope.envelope_hash, state, 0)
    caps = envelope.monetary_caps
    if facts.current_finalized_balance_atoms < caps.protected_reserve_atoms:
        return AdmissionDecision(False, "protected-reserve-breached", envelope.envelope_hash, state, 0)
    if facts.realized_loss_atoms > caps.realized_loss_atoms:
        return AdmissionDecision(False, "realized-loss-cap", envelope.envelope_hash, state, 0)
    if facts.fee_spend_atoms > caps.fee_atoms:
        return AdmissionDecision(False, "fee-cap", envelope.envelope_hash, state, 0)
    if facts.tip_spend_atoms > caps.tip_atoms:
        return AdmissionDecision(False, "tip-cap", envelope.envelope_hash, state, 0)
    if facts.rent_spend_atoms > caps.rent_atoms:
        return AdmissionDecision(False, "rent-cap", envelope.envelope_hash, state, 0)
    if facts.unresolved_exposure_atoms > caps.unresolved_exposure_atoms:
        return AdmissionDecision(False, "unresolved-exposure-cap", envelope.envelope_hash, state, 0)
    available_above_reserve = max(
        0,
        facts.current_finalized_balance_atoms
        - caps.protected_reserve_atoms
        - facts.committed_capital_atoms
        - facts.unresolved_exposure_atoms,
    )
    max_additional = min(caps.principal_atoms, available_above_reserve)
    if max_additional <= 0:
        return AdmissionDecision(False, "no-admissible-capital", envelope.envelope_hash, state, 0)
    return AdmissionDecision(True, "admitted", envelope.envelope_hash, state, max_additional)


def record_slo_budget(db: sqlite3.Connection, *, envelope_hash: str, budget: SLOBudget) -> None:
    db.execute(
        """
        INSERT INTO mpr2613_slo_budgets(
          envelope_hash,metric,window_id,denominator,min_samples,threshold,consumed,hard_failure
        ) VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(envelope_hash,metric,window_id) DO UPDATE SET
          denominator=excluded.denominator,
          min_samples=excluded.min_samples,
          threshold=excluded.threshold,
          consumed=MAX(mpr2613_slo_budgets.consumed,excluded.consumed),
          hard_failure=MAX(mpr2613_slo_budgets.hard_failure,excluded.hard_failure)
        """,
        (
            envelope_hash,
            budget.metric,
            budget.window,
            budget.denominator,
            budget.min_samples,
            budget.threshold,
            budget.consumed,
            int(budget.hard_failure),
        ),
    )


def recommended_downshift(budget: SLOBudget) -> OperatingState | None:
    """SLO automation may tighten only; it never recommends an upward state."""

    if budget.hard_failure:
        return OperatingState.LATCHED
    if budget.consumed > budget.threshold:
        return OperatingState.DEGRADED
    return None


def _append_event(
    db: sqlite3.Connection,
    *,
    scope_key: str,
    envelope_hash: str,
    from_state: OperatingState | None,
    to_state: OperatingState,
    reason: str,
    automated: bool,
    current_utc: str,
) -> None:
    db.execute(
        "INSERT INTO mpr2613_state_events(scope_key,envelope_hash,from_state,to_state,reason,automated,created_at_utc) VALUES(?,?,?,?,?,?,?)",
        (
            scope_key,
            envelope_hash,
            None if from_state is None else int(from_state),
            int(to_state),
            reason,
            int(automated),
            current_utc,
        ),
    )


def _parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp must use UTC Z format")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid UTC timestamp") from exc
    return parsed.astimezone(timezone.utc)


def _require_sha256(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value) or value == "0" * 64:
        raise ValueError(f"{name} must be a non-placeholder sha256")


def _jsonable(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(v) for v in value]
    return value


def _hash_json(value: object) -> str:
    raw = json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
