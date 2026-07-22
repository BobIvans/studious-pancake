"""PR-150 structured durable sender-free paper runtime."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import json
from pathlib import Path
import sqlite3
import time
from types import MappingProxyType
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from src.paper_shadow.runner import PaperShadowRunStatus, PaperShadowRunSummary

PR150_SCHEMA_VERSION = "pr150.structured-durable-paper-runtime.v1"
PR150_OUTBOX_KIND = "paper_runtime_transition"


class StructuredPaperRuntimeState(StrEnum):
    HEALTHY_IDLE = "healthy_idle"
    PAPER_OUTCOME = "paper_outcome"
    BLOCKED = "blocked"
    DEGRADED = "degraded"
    FAILED = "failed"
    TIMEOUT = "timeout"


_READY_STATES = frozenset(
    {
        StructuredPaperRuntimeState.HEALTHY_IDLE,
        StructuredPaperRuntimeState.PAPER_OUTCOME,
    }
)
_FORBIDDEN_DETAIL_KEYS = frozenset(
    {
        "keypair",
        "private_key",
        "secret",
        "signature",
        "signed_transaction",
        "txid",
    }
)


class StructuredPaperRuntimeError(ValueError):
    """Raised when durable paper runtime evidence is unsafe."""


class PaperRuntimeCycle(Protocol):
    async def run_once(self) -> PaperShadowRunSummary:
        ...


@dataclass(frozen=True, slots=True)
class StructuredPaperRuntimePolicy:
    store_path: Path = Path(".runtime/paper-shadow-lifecycle.sqlite3")
    max_cycles: int = 1
    cycle_deadline_seconds: float = 30.0
    idle_sleep_seconds: float = 0.0
    sender_enabled: bool = False
    live_enabled: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "store_path", Path(self.store_path))
        if self.max_cycles <= 0:
            raise StructuredPaperRuntimeError("max_cycles must be positive")
        if self.cycle_deadline_seconds <= 0:
            raise StructuredPaperRuntimeError("cycle deadline must be positive")
        if self.idle_sleep_seconds < 0:
            raise StructuredPaperRuntimeError("idle sleep must be non-negative")
        if self.sender_enabled or self.live_enabled:
            raise StructuredPaperRuntimeError("paper runtime must stay live-disabled")


@dataclass(frozen=True, slots=True)
class PaperLifecycleTransition:
    run_id: str
    cycle: int
    state: StructuredPaperRuntimeState
    terminal_reason: str
    candidates_seen: int
    events_written: int
    ready_for_next_cycle: bool
    dependency_reasons: tuple[str, ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)
    created_at_unix_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    schema_version: str = PR150_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PR150_SCHEMA_VERSION:
            raise StructuredPaperRuntimeError("unsupported PR-150 schema")
        if not self.run_id.strip() or not self.terminal_reason.strip():
            raise StructuredPaperRuntimeError("run_id and terminal_reason are required")
        if self.cycle <= 0:
            raise StructuredPaperRuntimeError("cycle must be positive")
        if self.candidates_seen < 0 or self.events_written < 0:
            raise StructuredPaperRuntimeError("invalid lifecycle counters")

        safe_details = dict(self.details)
        _reject_unsafe_details(safe_details)
        dependency_reasons = tuple(
            dict.fromkeys(str(item) for item in self.dependency_reasons)
        )
        object.__setattr__(self, "dependency_reasons", dependency_reasons)
        object.__setattr__(self, "details", MappingProxyType(safe_details))

    @property
    def transition_id(self) -> str:
        return _digest(
            "transition",
            self.run_id,
            str(self.cycle),
            self.state.value,
            self.terminal_reason,
        )

    @property
    def attempt_id(self) -> str:
        return _digest("attempt", self.run_id, str(self.cycle))

    @property
    def outbox_id(self) -> str:
        return _digest("outbox", self.transition_id, PR150_OUTBOX_KIND)

    @classmethod
    def from_summary(
        cls,
        summary: PaperShadowRunSummary,
        *,
        cycle: int,
    ) -> "PaperLifecycleTransition":
        return cls(
            run_id=summary.run_id,
            cycle=cycle,
            state=_state_from_summary(summary.status),
            terminal_reason=summary.terminal_reason,
            candidates_seen=summary.candidates_seen,
            events_written=summary.events_written,
            ready_for_next_cycle=summary.ready_for_next_cycle,
            dependency_reasons=summary.dependency_reasons,
            details={"sender_enabled": False, "live_enabled": False},
        )

    @classmethod
    def fail_closed(
        cls,
        *,
        run_id: str,
        cycle: int,
        state: StructuredPaperRuntimeState,
        reason: str,
        details: Mapping[str, Any],
    ) -> "PaperLifecycleTransition":
        return cls(
            run_id=run_id,
            cycle=cycle,
            state=state,
            terminal_reason=reason,
            candidates_seen=0,
            events_written=0,
            ready_for_next_cycle=False,
            dependency_reasons=(reason,),
            details={"sender_enabled": False, "live_enabled": False, **dict(details)},
        )


@dataclass(frozen=True, slots=True)
class StructuredPaperRuntimeReport:
    run_id: str
    cycles_completed: int
    final_state: StructuredPaperRuntimeState
    store_path: str
    transition_ids: tuple[str, ...]
    outbox_ids: tuple[str, ...]
    ready_for_next_cycle: bool
    sender_enabled: bool = False
    live_enabled: bool = False
    schema_version: str = PR150_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "cycles_completed": self.cycles_completed,
            "final_state": self.final_state.value,
            "store_path": self.store_path,
            "transition_ids": list(self.transition_ids),
            "outbox_ids": list(self.outbox_ids),
            "ready_for_next_cycle": self.ready_for_next_cycle,
            "sender_enabled": self.sender_enabled,
            "live_enabled": self.live_enabled,
        }


class SQLitePaperLifecycleStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_lifecycle_transition (
                    transition_id TEXT PRIMARY KEY,
                    attempt_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    cycle INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    terminal_reason TEXT NOT NULL,
                    candidates_seen INTEGER NOT NULL,
                    events_written INTEGER NOT NULL,
                    ready_for_next_cycle INTEGER NOT NULL,
                    dependency_reasons_json TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at_unix_ms INTEGER NOT NULL,
                    schema_version TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_pr150_run_cycle
                ON paper_lifecycle_transition(run_id, cycle)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_lifecycle_outbox (
                    outbox_id TEXT PRIMARY KEY,
                    transition_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    cycle INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    delivered INTEGER NOT NULL DEFAULT 0,
                    created_at_unix_ms INTEGER NOT NULL
                )
                """
            )

    def record_transition(self, transition: PaperLifecycleTransition) -> None:
        self.migrate()
        dependency_reasons_json = json.dumps(
            list(transition.dependency_reasons),
            sort_keys=True,
        )
        details_json = json.dumps(dict(transition.details), sort_keys=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO paper_lifecycle_transition
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transition.transition_id,
                    transition.attempt_id,
                    transition.run_id,
                    transition.cycle,
                    transition.state.value,
                    transition.terminal_reason,
                    transition.candidates_seen,
                    transition.events_written,
                    int(transition.ready_for_next_cycle),
                    dependency_reasons_json,
                    details_json,
                    transition.created_at_unix_ms,
                    transition.schema_version,
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO paper_lifecycle_outbox
                VALUES (?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    transition.outbox_id,
                    transition.transition_id,
                    transition.run_id,
                    transition.cycle,
                    PR150_OUTBOX_KIND,
                    transition.created_at_unix_ms,
                ),
            )

    def read_transitions(self) -> tuple[dict[str, Any], ...]:
        if not self.path.exists():
            return ()
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM paper_lifecycle_transition ORDER BY cycle ASC
                """
            ).fetchall()
        return tuple(_transition_row(row) for row in rows)

    def read_outbox(self) -> tuple[dict[str, Any], ...]:
        if not self.path.exists():
            return ()
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                "SELECT * FROM paper_lifecycle_outbox ORDER BY cycle ASC"
            ).fetchall()
        return tuple(_outbox_row(row) for row in rows)


class StructuredPaperRuntimeController:
    def __init__(
        self,
        runtime: PaperRuntimeCycle,
        *,
        policy: StructuredPaperRuntimePolicy | None = None,
        store: SQLitePaperLifecycleStore | None = None,
        run_id: str = "pr150-paper-runtime",
    ) -> None:
        self.runtime = runtime
        self.policy = policy or StructuredPaperRuntimePolicy()
        self.store = store or SQLitePaperLifecycleStore(self.policy.store_path)
        self.run_id = run_id

    async def run_until_stopped(
        self,
        stop_event: asyncio.Event | None = None,
    ) -> StructuredPaperRuntimeReport:
        transitions: list[PaperLifecycleTransition] = []
        for cycle in range(1, self.policy.max_cycles + 1):
            if stop_event is not None and stop_event.is_set():
                break
            transition = await self._run_cycle(cycle)
            self.store.record_transition(transition)
            transitions.append(transition)
            if transition.state not in _READY_STATES:
                break
            if self.policy.idle_sleep_seconds:
                await asyncio.sleep(self.policy.idle_sleep_seconds)

        final = transitions[-1] if transitions else self._empty_cancelled_transition()
        return StructuredPaperRuntimeReport(
            run_id=self.run_id,
            cycles_completed=len(transitions),
            final_state=final.state,
            store_path=str(self.store.path),
            transition_ids=tuple(item.transition_id for item in transitions),
            outbox_ids=tuple(item.outbox_id for item in transitions),
            ready_for_next_cycle=final.ready_for_next_cycle,
        )

    async def _run_cycle(self, cycle: int) -> PaperLifecycleTransition:
        try:
            summary = await asyncio.wait_for(
                self.runtime.run_once(),
                timeout=self.policy.cycle_deadline_seconds,
            )
        except asyncio.TimeoutError:
            return PaperLifecycleTransition.fail_closed(
                run_id=self.run_id,
                cycle=cycle,
                state=StructuredPaperRuntimeState.TIMEOUT,
                reason="stage_deadline_exceeded",
                details={"deadline_seconds": self.policy.cycle_deadline_seconds},
            )
        except Exception as exc:
            return PaperLifecycleTransition.fail_closed(
                run_id=self.run_id,
                cycle=cycle,
                state=StructuredPaperRuntimeState.FAILED,
                reason="paper_runtime_cycle_failed",
                details={"error_type": type(exc).__name__},
            )
        return PaperLifecycleTransition.from_summary(summary, cycle=cycle)

    def _empty_cancelled_transition(self) -> PaperLifecycleTransition:
        return PaperLifecycleTransition.fail_closed(
            run_id=self.run_id,
            cycle=1,
            state=StructuredPaperRuntimeState.FAILED,
            reason="paper_runtime_not_started",
            details={},
        )


def build_structured_paper_runtime(
    runtime: PaperRuntimeCycle,
    *,
    store_path: str | Path | None = None,
    max_cycles: int = 1,
    cycle_deadline_seconds: float = 30.0,
    idle_sleep_seconds: float = 0.0,
    run_id: str = "pr150-paper-runtime",
) -> StructuredPaperRuntimeController:
    policy_store_path = (
        Path(store_path)
        if store_path is not None
        else StructuredPaperRuntimePolicy().store_path
    )
    policy = StructuredPaperRuntimePolicy(
        store_path=policy_store_path,
        max_cycles=max_cycles,
        cycle_deadline_seconds=cycle_deadline_seconds,
        idle_sleep_seconds=idle_sleep_seconds,
    )
    return StructuredPaperRuntimeController(runtime, policy=policy, run_id=run_id)


def _state_from_summary(status: PaperShadowRunStatus) -> StructuredPaperRuntimeState:
    return {
        PaperShadowRunStatus.HEALTHY_IDLE: StructuredPaperRuntimeState.HEALTHY_IDLE,
        PaperShadowRunStatus.PAPER_OUTCOME: StructuredPaperRuntimeState.PAPER_OUTCOME,
        PaperShadowRunStatus.BLOCKED: StructuredPaperRuntimeState.BLOCKED,
        PaperShadowRunStatus.DEGRADED: StructuredPaperRuntimeState.DEGRADED,
        PaperShadowRunStatus.FAILED: StructuredPaperRuntimeState.FAILED,
    }[status]


def _reject_unsafe_details(details: Mapping[str, Any]) -> None:
    for key, value in details.items():
        normalized = str(key).lower()
        if normalized in _FORBIDDEN_DETAIL_KEYS:
            raise StructuredPaperRuntimeError(f"forbidden lifecycle detail: {key}")
        if normalized in {"live_enabled", "sender_enabled"} and value is True:
            raise StructuredPaperRuntimeError(f"{key} must remain false")


def _digest(*parts: str) -> str:
    payload = "\x1f".join(("pr150", *parts))
    return uuid5(NAMESPACE_URL, payload).hex


def _transition_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "transition_id": row[0],
        "attempt_id": row[1],
        "run_id": row[2],
        "cycle": row[3],
        "state": row[4],
        "terminal_reason": row[5],
        "candidates_seen": row[6],
        "events_written": row[7],
        "ready_for_next_cycle": bool(row[8]),
        "dependency_reasons": json.loads(row[9]),
        "details": json.loads(row[10]),
        "created_at_unix_ms": row[11],
        "schema_version": row[12],
    }


def _outbox_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "outbox_id": row[0],
        "transition_id": row[1],
        "run_id": row[2],
        "cycle": row[3],
        "kind": row[4],
        "delivered": bool(row[5]),
        "created_at_unix_ms": row[6],
    }


__all__ = [
    "PR150_OUTBOX_KIND",
    "PR150_SCHEMA_VERSION",
    "PaperLifecycleTransition",
    "SQLitePaperLifecycleStore",
    "StructuredPaperRuntimeController",
    "StructuredPaperRuntimeError",
    "StructuredPaperRuntimePolicy",
    "StructuredPaperRuntimeReport",
    "StructuredPaperRuntimeState",
    "build_structured_paper_runtime",
]
