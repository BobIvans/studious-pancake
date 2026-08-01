"""Fail-closed contracts for the installed continuous sender-free graph.

This module deliberately contains no signer, key or submission adapter.  It
turns durable probes into readiness and hash-bound soak evidence; it does not
turn assertions supplied by an operator into release truth.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Mapping


class DataLineage(str, Enum):
    SYNTHETIC_FIXTURE = "synthetic_fixture"
    RECORDED_PROVIDER_FIXTURE = "recorded_provider_fixture"
    CREDENTIALED_PROVIDER_SNAPSHOT = "credentialed_provider_snapshot"
    FINALIZED_ONCHAIN_EVIDENCE = "finalized_onchain_evidence"

    @property
    def promotion_eligible(self) -> bool:
        return self in {
            self.CREDENTIALED_PROVIDER_SNAPSHOT,
            self.FINALIZED_ONCHAIN_EVIDENCE,
        }


class RuntimeMode(str, Enum):
    SAFE_IDLE = "safe-idle"
    PAPER = "paper"
    SHADOW = "shadow"
    CANARY_BLOCKED = "live-gate/canary-blocked"


class PromotionState(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"
    SAFE_IDLE = "SAFE_IDLE"
    RECORDED_REPLAY = "RECORDED_REPLAY"
    LIVE_DATA_SHADOW = "LIVE_DATA_SHADOW"
    PAPER_QUALIFIED = "PAPER_QUALIFIED"
    CANARY_ELIGIBLE = "CANARY_ELIGIBLE"
    ONE_TX_CANARY_ACTIVE = "ONE_TX_CANARY_ACTIVE"
    CANARY_PAUSED = "CANARY_PAUSED"


READINESS_PROBES = (
    "tasks",
    "db_writer",
    "schema",
    "provider_freshness",
    "rpc_quorum",
    "trusted_time",
    "queue",
    "outbox",
    "disk",
    "replay",
    "config",
    "release_capability",
    "terminal_cycle",
    "reconciliation",
    "evidence",
    "exact_simulator",
)


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


@dataclass(frozen=True)
class Probe:
    healthy: bool
    generation: int
    observed_ns: int
    reason_code: str = "ok"


def compute_readiness(mode: RuntimeMode, probes: Mapping[str, Probe]) -> dict[str, Any]:
    """Compute readiness from concrete probes; missing/stale probes fail closed."""
    now = time.time_ns()
    blockers: list[str] = []
    for name in READINESS_PROBES:
        probe = probes.get(name)
        if probe is None:
            blockers.append(f"missing:{name}")
        elif not probe.healthy:
            blockers.append(f"{name}:{probe.reason_code}")
        elif probe.generation < 1:
            blockers.append(f"generation:{name}")
        elif now - probe.observed_ns > 30_000_000_000:
            blockers.append(f"stale:{name}")
    if mode in {RuntimeMode.SAFE_IDLE, RuntimeMode.CANARY_BLOCKED}:
        blockers.append(f"mode:{mode.value}")
    return {
        "live": True,
        "ready": not blockers,
        "status": "READY" if not blockers else "BLOCKED",
        "mode": mode.value,
        "blockers": sorted(blockers),
        "probe_digest": digest({k: asdict(v) for k, v in sorted(probes.items())}),
        "signer_available": False,
        "submission_available": False,
    }


class SoakLedger:
    """SQLite authority for unique cycles and append-only hash chaining."""

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(root / "cycles.sqlite3")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS cycles (
          sequence INTEGER PRIMARY KEY, cycle_id TEXT UNIQUE NOT NULL,
          observed_ns INTEGER NOT NULL, lineage TEXT NOT NULL, data_hash TEXT NOT NULL,
          identity_json TEXT NOT NULL, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL
        )""")
        self.db.commit()

    def append(
        self,
        *,
        lineage: DataLineage,
        bindings: Mapping[str, str],
        observed_ns: int | None = None,
    ) -> dict[str, Any]:
        required = {
            "release_digest",
            "config_digest",
            "registry_digest",
            "schema_fingerprint",
            "data_hash",
            "runtime_generation",
            "opportunity_id",
            "attempt_id",
        }
        missing = sorted(required - bindings.keys())
        if missing:
            raise ValueError(f"missing identity bindings: {missing}")
        last = self.db.execute(
            "SELECT sequence, event_hash FROM cycles ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        seq, previous = (1, "0") if last is None else (int(last[0]) + 1, str(last[1]))
        observed = observed_ns if observed_ns is not None else time.time_ns()
        identity = {
            **bindings,
            "sequence": seq,
            "observed_ns": observed,
            "lineage": lineage.value,
        }
        cycle_id = digest(identity)
        event_hash = digest(
            {"cycle_id": cycle_id, "previous_hash": previous, "identity": identity}
        )
        self.db.execute(
            "INSERT INTO cycles VALUES (?,?,?,?,?,?,?,?)",
            (
                seq,
                cycle_id,
                observed,
                lineage.value,
                bindings["data_hash"],
                canonical_bytes(identity).decode(),
                previous,
                event_hash,
            ),
        )
        self.db.commit()
        return {
            "sequence": seq,
            "cycle_id": cycle_id,
            "event_hash": event_hash,
            "lineage": lineage.value,
        }

    def close(self) -> None:
        self.db.close()


def verify_soak(root: Path, *, minimum_hours: int = 72) -> dict[str, Any]:
    """Independently recompute continuity; wall-clock rows define duration."""
    db = sqlite3.connect(f"file:{root / 'cycles.sqlite3'}?mode=ro", uri=True)
    rows = db.execute(
        "SELECT sequence,cycle_id,observed_ns,lineage,data_hash,identity_json,previous_hash,event_hash FROM cycles ORDER BY sequence"
    ).fetchall()
    db.close()
    blockers: list[str] = []
    previous = "0"
    eligible = 0
    seen: set[str] = set()
    for (
        sequence,
        cycle_id,
        observed,
        lineage,
        data_hash,
        identity_json,
        prior,
        event_hash,
    ) in rows:
        identity = json.loads(identity_json)
        expected_id = digest(identity)
        expected_event = digest(
            {"cycle_id": expected_id, "previous_hash": previous, "identity": identity}
        )
        if (
            sequence != len(seen) + 1
            or cycle_id in seen
            or cycle_id != expected_id
            or prior != previous
            or event_hash != expected_event
            or data_hash != identity.get("data_hash")
        ):
            blockers.append(f"integrity:sequence:{sequence}")
        seen.add(cycle_id)
        previous = event_hash
        if DataLineage(lineage).promotion_eligible:
            eligible += 1
    duration_ns = (rows[-1][2] - rows[0][2]) if len(rows) > 1 else 0
    accepted_hours = duration_ns / 3_600_000_000_000
    if eligible != len(rows):
        blockers.append("non_promotion_lineage")
    if accepted_hours < minimum_hours:
        blockers.append("real_shadow_soak_incomplete")
    if not rows:
        blockers.append("no_cycles")
    report = {
        "schema_version": "pr007.shadow-soak.v1",
        "verified": not blockers,
        "promotion_eligible": not blockers,
        "cycle_count": len(rows),
        "unique_cycle_count": len(seen),
        "eligible_cycle_count": eligible,
        "accepted_hours": accepted_hours,
        "blockers": sorted(set(blockers)),
        "final_event_hash": previous,
        "signer_available": False,
        "submission_available": False,
    }
    report["report_sha256"] = digest(report)
    return report


def fixture_bindings(sequence: int) -> dict[str, str]:
    """Deterministic CI bindings, explicitly ineligible for promotion."""
    h = lambda label: hashlib.sha256(f"fixture:{label}".encode()).hexdigest()
    return {
        "release_digest": h("release"),
        "config_digest": h("config"),
        "registry_digest": h("registry"),
        "schema_fingerprint": h("schema"),
        "data_hash": h(f"data:{sequence}"),
        "runtime_generation": "1",
        "opportunity_id": h(f"opportunity:{sequence}"),
        "attempt_id": h(f"attempt:{sequence}"),
    }
