from __future__ import annotations

import asyncio
import sqlite3

import pytest

from src.mpr2603_human_recovery import install_human_recovery_schema
from src.mpr2603_provider_recovery import (
    ProviderRecoveryBinding,
    ProviderRecoveryError,
    bind_provider_recovery,
    install_provider_recovery_schema,
    run_authorized_recovery_probe,
)
from src.provider_governance.dependency import DependencyController
from src.provider_governance.models import DependencyFailureKind, DependencyMode


def _db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.execute("PRAGMA foreign_keys=ON")
    install_human_recovery_schema(db)
    install_provider_recovery_schema(db)
    db.execute(
        """
        INSERT INTO mpr2603_recovery_intents(
          intent_id,permit_hash,latch_id,latch_evidence_hash,status,created_at_utc
        ) VALUES(?,?,?,?,?,?)
        """,
        (
            "recovery-1",
            "a" * 64,
            "provider-auth",
            "b" * 64,
            "recovery_pending",
            "2026-09-09T12:00:00Z",
        ),
    )
    return db


def _bind(db: sqlite3.Connection, *, generation: str = "g1", max_attempts: int = 2) -> None:
    bind_provider_recovery(
        db,
        ProviderRecoveryBinding(
            intent_id="recovery-1",
            provider_id="jupiter",
            generation=generation,
            deadline_utc="2026-09-09T12:10:00Z",
            max_attempts=max_attempts,
        ),
    )


def test_authorized_probe_recovers_disabled_exact_generation() -> None:
    db = _db()
    _bind(db)
    controller = DependencyController()
    asyncio.run(
        controller.record_failure(
            "jupiter",
            "g1",
            DependencyFailureKind.AUTH,
        )
    )
    assert controller.peek("jupiter", "g1").mode is DependencyMode.DISABLED
    observed: list[tuple[str, str, bool]] = []

    async def probe(provider_id: str, generation: str) -> bool:
        observed.append((provider_id, generation, db.in_transaction))
        return True

    result = asyncio.run(
        run_authorized_recovery_probe(
            db,
            controller=controller,
            intent_id="recovery-1",
            current_utc="2026-09-09T12:01:00Z",
            probe=probe,
        )
    )
    assert observed == [("jupiter", "g1", False)]
    assert result.recovered is True
    assert result.attempt_number == 1
    assert controller.peek("jupiter", "g1").mode is DependencyMode.ACTIVE
    assert db.execute(
        "SELECT status FROM mpr2603_recovery_intents WHERE intent_id='recovery-1'"
    ).fetchone() == ("completed",)
    assert db.execute(
        "SELECT outcome FROM mpr2603_provider_recovery_attempts"
    ).fetchall() == [("succeeded",)]


def test_failed_probe_is_accounted_and_does_not_recover() -> None:
    db = _db()
    _bind(db)
    controller = DependencyController()
    asyncio.run(
        controller.record_failure(
            "jupiter",
            "g1",
            DependencyFailureKind.AUTH,
        )
    )

    async def probe(_provider_id: str, _generation: str) -> bool:
        return False

    result = asyncio.run(
        run_authorized_recovery_probe(
            db,
            controller=controller,
            intent_id="recovery-1",
            current_utc="2026-09-09T12:01:00Z",
            probe=probe,
        )
    )
    assert result.recovered is False
    assert controller.peek("jupiter", "g1").mode is DependencyMode.DISABLED
    assert db.execute(
        "SELECT attempt_count,status FROM mpr2603_provider_recovery_bindings"
    ).fetchone() == (1, "pending")
    assert db.execute(
        "SELECT outcome FROM mpr2603_provider_recovery_attempts"
    ).fetchone() == ("failed",)


def test_attempt_budget_and_deadline_fail_closed_without_probe() -> None:
    db = _db()
    _bind(db, max_attempts=1)
    controller = DependencyController()
    calls = 0

    async def probe(_provider_id: str, _generation: str) -> bool:
        nonlocal calls
        calls += 1
        return False

    asyncio.run(
        run_authorized_recovery_probe(
            db,
            controller=controller,
            intent_id="recovery-1",
            current_utc="2026-09-09T12:01:00Z",
            probe=probe,
        )
    )
    with pytest.raises(ProviderRecoveryError, match="ATTEMPTS_EXHAUSTED"):
        asyncio.run(
            run_authorized_recovery_probe(
                db,
                controller=controller,
                intent_id="recovery-1",
                current_utc="2026-09-09T12:02:00Z",
                probe=probe,
            )
        )
    assert calls == 1

    db2 = _db()
    _bind(db2)
    with pytest.raises(ProviderRecoveryError, match="DEADLINE_EXPIRED"):
        asyncio.run(
            run_authorized_recovery_probe(
                db2,
                controller=DependencyController(),
                intent_id="recovery-1",
                current_utc="2026-09-09T12:10:00Z",
                probe=probe,
            )
        )
    assert calls == 1


def test_generation_change_denies_before_external_probe() -> None:
    db = _db()
    _bind(db, generation="g1")
    controller = DependencyController()
    controller.activate_generation("jupiter", "g2")
    calls = 0

    async def probe(_provider_id: str, _generation: str) -> bool:
        nonlocal calls
        calls += 1
        return True

    with pytest.raises(ProviderRecoveryError, match="GENERATION_CHANGED"):
        asyncio.run(
            run_authorized_recovery_probe(
                db,
                controller=controller,
                intent_id="recovery-1",
                current_utc="2026-09-09T12:01:00Z",
                probe=probe,
            )
        )
    assert calls == 0
    assert db.execute(
        "SELECT attempt_count FROM mpr2603_provider_recovery_bindings"
    ).fetchone() == (0,)


def test_recovered_replay_returns_without_second_probe() -> None:
    db = _db()
    _bind(db)
    controller = DependencyController()
    calls = 0

    async def probe(_provider_id: str, _generation: str) -> bool:
        nonlocal calls
        calls += 1
        return True

    first = asyncio.run(
        run_authorized_recovery_probe(
            db,
            controller=controller,
            intent_id="recovery-1",
            current_utc="2026-09-09T12:01:00Z",
            probe=probe,
        )
    )
    second = asyncio.run(
        run_authorized_recovery_probe(
            db,
            controller=controller,
            intent_id="recovery-1",
            current_utc="2026-09-09T12:02:00Z",
            probe=probe,
        )
    )
    assert first.recovered and second.recovered
    assert first.attempt_number == second.attempt_number == 1
    assert calls == 1
