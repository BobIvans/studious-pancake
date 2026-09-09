"""MPR-2609 durable, fail-closed limited-live canary authority.

This module deliberately does not sign or submit transactions. It binds reviewed
predecessor evidence, dual-human authorization, and an exact candidate/message into
one durable one-shot admission record that the MPR-2608 boundary may consume.

The caller owns the SQLite transaction. Methods never commit or roll back, and the
schema installer deliberately avoids ``executescript`` because that API can create
an implicit transaction boundary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import sqlite3
from typing import Iterable, Mapping


class MPR2609Error(ValueError):
    """Raised when limited-live canary invariants are violated."""


class DurableCanaryMode(StrEnum):
    SHADOW = "shadow"
    REVIEW_PENDING = "review_pending"
    ARMED = "armed"
    SUBMISSION_OUTSTANDING = "submission_outstanding"
    RECONCILIATION_PENDING = "reconciliation_pending"
    LATCHED = "latched"


class DurableLatch(StrEnum):
    MANUAL_KILL = "manual_kill"
    PREREQUISITE_DRIFT = "prerequisite_drift"
    POLICY_DRIFT = "policy_drift"
    MESSAGE_MISMATCH = "message_mismatch"
    OUTSTANDING_SUBMISSION = "outstanding_submission"
    UNKNOWN_SUBMISSION = "unknown_submission"
    RECONCILIATION_MISMATCH = "reconciliation_mismatch"
    STORE_FENCE_FAILURE = "store_fence_failure"


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _nonempty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MPR2609Error(f"{name} must be non-empty")
    return value.strip()


def _sha(value: str, name: str) -> str:
    value = _nonempty(value, name)
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value.lower()
    ):
        raise MPR2609Error(f"{name} must be a SHA-256 hex digest")
    return value.lower()


def _integer(value: int, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise MPR2609Error(f"{name} must be an integer >= {minimum}")
    return value


def _state_int(
    state: Mapping[str, object],
    name: str,
    *,
    default: int | None = None,
) -> int:
    value = state.get(name)
    if value is None and default is not None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise MPR2609Error(f"durable state {name} must be an integer")
    return value


@dataclass(frozen=True, slots=True)
class PrerequisiteIdentity:
    runtime_2601: str
    human_control_2603: str
    frozen_release_2604: str
    protocol_2605: str
    vertical_2606: str
    shadow_2607: str
    signer_transport_2608: str
    release_hash: str
    config_hash: str
    policy_hash: str
    capability_hash: str
    wallet_ref: str
    cluster: str
    genesis_hash: str

    def __post_init__(self) -> None:
        for name in (
            "runtime_2601",
            "human_control_2603",
            "frozen_release_2604",
            "protocol_2605",
            "vertical_2606",
            "shadow_2607",
            "signer_transport_2608",
            "release_hash",
            "config_hash",
            "policy_hash",
            "capability_hash",
            "genesis_hash",
        ):
            object.__setattr__(self, name, _sha(getattr(self, name), name))
        object.__setattr__(
            self,
            "wallet_ref",
            _nonempty(self.wallet_ref, "wallet_ref"),
        )
        object.__setattr__(self, "cluster", _nonempty(self.cluster, "cluster"))

    @property
    def digest(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True, slots=True)
class CanaryBudget:
    max_principal_base_units: int
    max_wallet_spend_lamports: int
    protected_wallet_reserve_lamports: int
    max_base_fee_lamports: int
    max_priority_fee_lamports: int
    max_jito_tip_lamports: int
    max_total_cost_lamports: int
    max_attempt_loss_lamports: int
    max_cumulative_loss_lamports: int
    max_attempts: int
    max_consecutive_failures: int
    max_data_age_ms: int
    max_rpc_slot_divergence: int
    min_blockheight_margin: int

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            _integer(value, name, 1)

    @property
    def digest(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True, slots=True)
class HumanPermit:
    """Consumed dual-human permit evidence; MPR-2609 does not issue approvals."""

    permit_id: str
    principal_a: str
    principal_b: str
    prerequisite_digest: str
    budget_digest: str
    candidate_scope_hash: str
    issued_at_ms: int
    expires_at_ms: int

    def __post_init__(self) -> None:
        for name in ("permit_id", "principal_a", "principal_b"):
            object.__setattr__(self, name, _nonempty(getattr(self, name), name))
        if self.principal_a == self.principal_b:
            raise MPR2609Error("two distinct human principals are required")
        object.__setattr__(
            self,
            "prerequisite_digest",
            _sha(self.prerequisite_digest, "prerequisite_digest"),
        )
        object.__setattr__(
            self,
            "budget_digest",
            _sha(self.budget_digest, "budget_digest"),
        )
        object.__setattr__(
            self,
            "candidate_scope_hash",
            _sha(self.candidate_scope_hash, "candidate_scope_hash"),
        )
        _integer(self.issued_at_ms, "issued_at_ms")
        _integer(self.expires_at_ms, "expires_at_ms", 1)
        if self.expires_at_ms <= self.issued_at_ms:
            raise MPR2609Error("permit expiry must be after issue time")


@dataclass(frozen=True, slots=True)
class CanaryAdmissionBundle:
    attempt_id: str
    attempt_generation: int
    prerequisite_digest: str
    budget_digest: str
    candidate_digest: str
    route_digest: str
    message_digest: str
    simulation_digest: str
    account_metas_digest: str
    blockhash: str
    last_valid_block_height: int
    wallet_ref: str
    market: str
    reservation_id: str
    transport: str
    permit_id: str
    deadline_ms: int

    def __post_init__(self) -> None:
        for name in (
            "attempt_id",
            "wallet_ref",
            "market",
            "reservation_id",
            "transport",
            "permit_id",
            "blockhash",
        ):
            object.__setattr__(self, name, _nonempty(getattr(self, name), name))
        _integer(self.attempt_generation, "attempt_generation", 1)
        _integer(self.last_valid_block_height, "last_valid_block_height", 1)
        _integer(self.deadline_ms, "deadline_ms", 1)
        for name in (
            "prerequisite_digest",
            "budget_digest",
            "candidate_digest",
            "route_digest",
            "message_digest",
            "simulation_digest",
            "account_metas_digest",
        ):
            object.__setattr__(self, name, _sha(getattr(self, name), name))

    @property
    def admission_digest(self) -> str:
        return _digest(asdict(self))


_SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS mpr2609_canary_control (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        mode TEXT NOT NULL,
        generation INTEGER NOT NULL,
        prerequisite_digest TEXT,
        budget_digest TEXT,
        permit_id TEXT,
        arm_expires_at_ms INTEGER,
        consumed_admission_digest TEXT,
        outstanding_attempt_id TEXT,
        cumulative_loss_lamports INTEGER NOT NULL DEFAULT 0,
        consecutive_failures INTEGER NOT NULL DEFAULT 0,
        latch_code TEXT,
        revision INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS mpr2609_canary_admissions (
        admission_digest TEXT PRIMARY KEY,
        attempt_id TEXT NOT NULL UNIQUE,
        generation INTEGER NOT NULL,
        message_digest TEXT NOT NULL,
        bundle_json TEXT NOT NULL,
        consumed INTEGER NOT NULL DEFAULT 0 CHECK (consumed IN (0,1))
    )""",
    """CREATE TABLE IF NOT EXISTS mpr2609_canary_events (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        generation INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        event_digest TEXT NOT NULL,
        payload_json TEXT NOT NULL
    )""",
)


class DurableCanaryAuthority:
    """Canonical durable MPR-2609 control/admission authority.

    A single caller-owned sqlite3 connection is reused. This class never opens a
    second database connection and never commits or rolls back, preserving the
    repository's transaction/fence ownership model.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise MPR2609Error("caller-owned sqlite3 connection is required")
        self._db = connection

    def install_schema(self) -> None:
        for statement in _SCHEMA_STATEMENTS:
            self._db.execute(statement)
        self._db.execute(
            """INSERT OR IGNORE INTO mpr2609_canary_control
               (singleton, mode, generation, cumulative_loss_lamports,
                consecutive_failures, revision)
               VALUES (1, ?, 0, 0, 0, 0)""",
            (DurableCanaryMode.SHADOW.value,),
        )

    def _row(self) -> sqlite3.Row | tuple[object, ...]:
        row = self._db.execute(
            """SELECT mode, generation, prerequisite_digest, budget_digest,
                      permit_id, arm_expires_at_ms, consumed_admission_digest,
                      outstanding_attempt_id, cumulative_loss_lamports,
                      consecutive_failures, latch_code, revision
               FROM mpr2609_canary_control WHERE singleton = 1"""
        ).fetchone()
        if row is None:
            raise MPR2609Error("MPR-2609 schema is not installed")
        return row

    def status(self) -> Mapping[str, object]:
        row = self._row()
        keys = (
            "mode",
            "generation",
            "prerequisite_digest",
            "budget_digest",
            "permit_id",
            "arm_expires_at_ms",
            "consumed_admission_digest",
            "outstanding_attempt_id",
            "cumulative_loss_lamports",
            "consecutive_failures",
            "latch_code",
            "revision",
        )
        return dict(zip(keys, row, strict=True))

    def arm(
        self,
        *,
        prerequisites: PrerequisiteIdentity,
        budget: CanaryBudget,
        permit: HumanPermit,
        now_ms: int,
    ) -> int:
        _integer(now_ms, "now_ms")
        state = self.status()
        if (
            state["latch_code"] is not None
            or state["outstanding_attempt_id"] is not None
        ):
            raise MPR2609Error("active latch/outstanding attempt blocks arming")
        if permit.expires_at_ms <= now_ms:
            raise MPR2609Error("human permit expired")
        if permit.prerequisite_digest != prerequisites.digest:
            raise MPR2609Error("permit prerequisite binding mismatch")
        if permit.budget_digest != budget.digest:
            raise MPR2609Error("permit budget binding mismatch")

        generation = _state_int(state, "generation") + 1
        revision = _state_int(state, "revision")
        cursor = self._db.execute(
            """UPDATE mpr2609_canary_control
               SET mode=?, generation=?, prerequisite_digest=?, budget_digest=?,
                   permit_id=?, arm_expires_at_ms=?, consumed_admission_digest=NULL,
                   revision=revision+1
               WHERE singleton=1 AND revision=? AND latch_code IS NULL
                   AND outstanding_attempt_id IS NULL""",
            (
                DurableCanaryMode.ARMED.value,
                generation,
                prerequisites.digest,
                budget.digest,
                permit.permit_id,
                permit.expires_at_ms,
                revision,
            ),
        )
        if cursor.rowcount != 1:
            raise MPR2609Error("stale writer fence while arming")
        self._event(generation, "armed", {"permit_id": permit.permit_id})
        return generation

    def admit_one_shot(
        self,
        *,
        bundle: CanaryAdmissionBundle,
        now_ms: int,
        current_block_height: int,
        min_blockheight_margin: int,
    ) -> str:
        _integer(now_ms, "now_ms")
        _integer(current_block_height, "current_block_height", 1)
        _integer(min_blockheight_margin, "min_blockheight_margin", 1)
        state = self.status()
        if state["mode"] != DurableCanaryMode.ARMED.value:
            raise MPR2609Error("canary is not armed")
        if (
            state["latch_code"] is not None
            or state["outstanding_attempt_id"] is not None
        ):
            raise MPR2609Error("active latch/outstanding attempt blocks admission")
        if _state_int(state, "generation") != bundle.attempt_generation:
            raise MPR2609Error("control generation mismatch")
        if state["prerequisite_digest"] != bundle.prerequisite_digest:
            raise MPR2609Error("prerequisite drift")
        if state["budget_digest"] != bundle.budget_digest:
            raise MPR2609Error("budget drift")
        if state["permit_id"] != bundle.permit_id:
            raise MPR2609Error("permit mismatch")
        if (
            _state_int(state, "arm_expires_at_ms", default=0) <= now_ms
            or bundle.deadline_ms <= now_ms
        ):
            raise MPR2609Error("arm/admission expired")
        if (
            bundle.last_valid_block_height - current_block_height
            < min_blockheight_margin
        ):
            raise MPR2609Error("blockheight safety margin exhausted")
        if state["consumed_admission_digest"] is not None:
            raise MPR2609Error("one-shot arm already consumed")

        digest = bundle.admission_digest
        payload = _canonical(asdict(bundle))
        self._db.execute(
            """INSERT INTO mpr2609_canary_admissions
               (admission_digest, attempt_id, generation, message_digest,
                bundle_json, consumed)
               VALUES (?, ?, ?, ?, ?, 1)""",
            (
                digest,
                bundle.attempt_id,
                bundle.attempt_generation,
                bundle.message_digest,
                payload,
            ),
        )
        cursor = self._db.execute(
            """UPDATE mpr2609_canary_control
               SET mode=?, consumed_admission_digest=?, outstanding_attempt_id=?,
                   revision=revision+1
               WHERE singleton=1 AND revision=? AND mode=?
                   AND consumed_admission_digest IS NULL
                   AND outstanding_attempt_id IS NULL""",
            (
                DurableCanaryMode.SUBMISSION_OUTSTANDING.value,
                digest,
                bundle.attempt_id,
                _state_int(state, "revision"),
                DurableCanaryMode.ARMED.value,
            ),
        )
        if cursor.rowcount != 1:
            raise MPR2609Error(
                "stale writer fence while consuming one-shot admission"
            )
        self._event(
            bundle.attempt_generation,
            "admitted",
            {"admission_digest": digest},
        )
        return digest

    def mark_unknown(self, *, attempt_id: str) -> None:
        attempt_id = _nonempty(attempt_id, "attempt_id")
        state = self.status()
        if state["outstanding_attempt_id"] != attempt_id:
            raise MPR2609Error("attempt identity mismatch")
        self._latch(DurableLatch.UNKNOWN_SUBMISSION, attempt_id)

    def finalize(
        self,
        *,
        attempt_id: str,
        realized_pnl_lamports: int,
        success: bool,
        reconciliation_digest: str,
        max_cumulative_loss_lamports: int,
        max_consecutive_failures: int,
    ) -> None:
        attempt_id = _nonempty(attempt_id, "attempt_id")
        if isinstance(realized_pnl_lamports, bool) or not isinstance(
            realized_pnl_lamports, int
        ):
            raise MPR2609Error("realized PnL must be exact integer lamports")
        reconciliation_digest = _sha(
            reconciliation_digest,
            "reconciliation_digest",
        )
        _integer(
            max_cumulative_loss_lamports,
            "max_cumulative_loss_lamports",
            1,
        )
        _integer(max_consecutive_failures, "max_consecutive_failures", 1)
        state = self.status()
        if state["outstanding_attempt_id"] != attempt_id:
            raise MPR2609Error("finalization attempt identity mismatch")

        cumulative_loss = _state_int(state, "cumulative_loss_lamports")
        if realized_pnl_lamports < 0:
            cumulative_loss += -realized_pnl_lamports
        failures = (
            0
            if success
            else _state_int(state, "consecutive_failures") + 1
        )
        latch: DurableLatch | None = None
        if cumulative_loss >= max_cumulative_loss_lamports:
            latch = DurableLatch.POLICY_DRIFT
        elif failures >= max_consecutive_failures:
            latch = DurableLatch.RECONCILIATION_MISMATCH

        mode = DurableCanaryMode.LATCHED if latch else DurableCanaryMode.SHADOW
        cursor = self._db.execute(
            """UPDATE mpr2609_canary_control
               SET mode=?, outstanding_attempt_id=NULL, permit_id=NULL,
                   arm_expires_at_ms=NULL, cumulative_loss_lamports=?,
                   consecutive_failures=?, latch_code=?, revision=revision+1
               WHERE singleton=1 AND revision=?
                   AND outstanding_attempt_id=?""",
            (
                mode.value,
                cumulative_loss,
                failures,
                latch.value if latch else None,
                _state_int(state, "revision"),
                attempt_id,
            ),
        )
        if cursor.rowcount != 1:
            raise MPR2609Error("stale writer fence while finalizing")
        self._event(
            _state_int(state, "generation"),
            "finalized",
            {
                "attempt_id": attempt_id,
                "success": bool(success),
                "realized_pnl_lamports": realized_pnl_lamports,
                "reconciliation_digest": reconciliation_digest,
                "returned_to_shadow": latch is None,
            },
        )

    def rollback_to_shadow(self) -> int:
        state = self.status()
        generation = _state_int(state, "generation") + 1
        cursor = self._db.execute(
            """UPDATE mpr2609_canary_control
               SET mode=?, generation=?, permit_id=NULL, arm_expires_at_ms=NULL,
                   consumed_admission_digest=NULL, revision=revision+1
               WHERE singleton=1 AND revision=?""",
            (
                DurableCanaryMode.SHADOW.value,
                generation,
                _state_int(state, "revision"),
            ),
        )
        if cursor.rowcount != 1:
            raise MPR2609Error("stale writer fence while rolling back")
        self._event(generation, "rollback_to_shadow", {})
        return generation

    def kill(self, *, evidence: str) -> None:
        self._latch(
            DurableLatch.MANUAL_KILL,
            _nonempty(evidence, "evidence"),
        )

    def _latch(self, code: DurableLatch, evidence: str) -> None:
        state = self.status()
        cursor = self._db.execute(
            """UPDATE mpr2609_canary_control
               SET mode=?, latch_code=?, permit_id=NULL, arm_expires_at_ms=NULL,
                   revision=revision+1
               WHERE singleton=1 AND revision=?""",
            (
                DurableCanaryMode.LATCHED.value,
                code.value,
                _state_int(state, "revision"),
            ),
        )
        if cursor.rowcount != 1:
            raise MPR2609Error("stale writer fence while latching")
        self._event(
            _state_int(state, "generation"),
            "latched",
            {"code": code.value, "evidence": evidence},
        )

    def _event(
        self,
        generation: int,
        event_type: str,
        payload: Mapping[str, object],
    ) -> None:
        payload_json = _canonical(dict(payload))
        event_digest = _digest(
            {
                "generation": generation,
                "event_type": event_type,
                "payload": json.loads(payload_json),
            }
        )
        self._db.execute(
            """INSERT INTO mpr2609_canary_events
               (generation, event_type, event_digest, payload_json)
               VALUES (?, ?, ?, ?)""",
            (generation, event_type, event_digest, payload_json),
        )


def prerequisite_digest_map(items: Iterable[tuple[str, str]]) -> str:
    """Hash named predecessor evidence without treating a boolean as qualification."""

    normalized: dict[str, str] = {}
    for name, digest in items:
        name = _nonempty(name, "prerequisite name")
        if name in normalized:
            raise MPR2609Error("duplicate prerequisite name")
        normalized[name] = _sha(digest, name)
    if not normalized:
        raise MPR2609Error("at least one prerequisite is required")
    return _digest(normalized)
