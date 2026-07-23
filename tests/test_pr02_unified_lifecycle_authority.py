from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import sqlite3

import pytest

from src.durability import AttemptKey
from src.durability.unified_authority_pr02 import (
    AuthorityFence,
    PR02_PRODUCT_ID,
    ReservationTerminalState,
    UnifiedA3AdmissionSink,
    UnifiedAuthorityError,
    UnifiedLifecycleAuthority,
)
from src.execution.models import ExecutionState
from src.paper_shadow.a2_exact_attempt_runtime import (
    A2PaperOutcomeStatus,
    ExactAttemptRuntimeReport,
)
from src.paper_shadow.durable_service_a3 import (
    A3ExactAttemptBatch,
    A3PaperServiceStatus,
    A3ProviderEvidenceState,
    InstalledDurablePaperService,
    InstalledPaperServiceConfig,
)
from src.config.runtime import load_runtime_config
from src.time_authority import TimeSnapshot, TimeSourceStatus

pytestmark = pytest.mark.unit


def digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class FakeTimeAuthority:
    def __init__(self, *, boot_id: str = "boot-a", generation: int = 1) -> None:
        self._boot_id = boot_id
        self._generation = generation
        self.utc_ns = 1_000_000
        self.monotonic_ns = 10_000
        self.status = TimeSourceStatus.SYNCHRONIZED

    @property
    def boot_id(self) -> str:
        return self._boot_id

    @property
    def process_generation(self) -> int:
        return self._generation

    def snapshot(self) -> TimeSnapshot:
        return TimeSnapshot(
            utc_ns=self.utc_ns,
            monotonic_ns=self.monotonic_ns,
            boot_id=self._boot_id,
            process_generation=self._generation,
            time_source_status=self.status,
            max_uncertainty_ns=1,
        )

    def assert_healthy_for_sensitive_operation(self) -> TimeSnapshot:
        snapshot = self.snapshot()
        if not snapshot.healthy_for_sensitive_operations:
            raise RuntimeError("clock unhealthy")
        return snapshot

    def advance(self, amount: int = 1) -> None:
        self.utc_ns += amount
        self.monotonic_ns += amount

    def reboot(self) -> None:
        self._boot_id = "boot-b"
        self._generation += 1
        self.monotonic_ns = 1
        self.utc_ns += 1


def authority(tmp_path, clock: FakeTimeAuthority | None = None):
    clock = clock or FakeTimeAuthority()
    store = UnifiedLifecycleAuthority(
        tmp_path / "unified.sqlite3",
        release_digest=digest("release"),
        policy_bundle_hash=digest("policy"),
        time_authority=clock,
        owner_id="worker-a",
        lease_ttl_ns=1_000,
    )
    return store, clock


def begin_cycle(store: UnifiedLifecycleAuthority) -> AuthorityFence:
    return store.begin_cycle_intent(
        run_id="run-a",
        sequence=1,
        config_fingerprint=digest("config"),
        source_surface="installed-cli",
    )


def test_cycle_terminal_and_outbox_commit_atomically_and_replay(tmp_path):
    store, _ = authority(tmp_path)
    fence = begin_cycle(store)
    provider_hash = digest("provider")
    store.bind_provider_evidence(fence, provider_evidence_hash=provider_hash)

    first = store.commit_cycle_terminal(
        fence,
        outcome="BLOCKED",
        reason_code="NO_VERIFIED_WORK",
        report_hash=digest("report"),
        report_payload={"status": "BLOCKED"},
        provider_evidence_hash=provider_hash,
        ready_for_next_cycle=False,
        source_surface="installed-cli",
    )
    second = store.commit_cycle_terminal(
        fence,
        outcome="BLOCKED",
        reason_code="NO_VERIFIED_WORK",
        report_hash=digest("report"),
        report_payload={"status": "BLOCKED"},
        provider_evidence_hash=provider_hash,
        ready_for_next_cycle=False,
        source_surface="installed-cli",
    )

    assert not first.replayed
    assert second.replayed
    assert second.terminal_id == first.terminal_id
    assert (
        store.db.execute("SELECT COUNT(*) FROM pr02_terminal_records").fetchone()[0]
        == 1
    )
    assert store.db.execute("SELECT COUNT(*) FROM pr02_outbox_event").fetchone()[0] == 1
    assert (
        store.db.execute("SELECT status FROM pr02_outbox_delivery").fetchone()[0]
        == "pending"
    )


def test_fence_policy_or_boot_change_rolls_back_terminal(tmp_path):
    store, clock = authority(tmp_path)
    fence = begin_cycle(store)
    provider_hash = digest("provider")
    store.bind_provider_evidence(fence, provider_evidence_hash=provider_hash)
    clock.reboot()

    with pytest.raises(
        UnifiedAuthorityError,
        match="PR02_OWNER_FENCE_LEASE_OR_POLICY_MISMATCH",
    ):
        store.commit_cycle_terminal(
            fence,
            outcome="BLOCKED",
            reason_code="STALE_OWNER",
            report_hash=digest("report"),
            report_payload={"status": "BLOCKED"},
            provider_evidence_hash=provider_hash,
            ready_for_next_cycle=False,
            source_surface="installed-cli",
        )

    assert (
        store.db.execute("SELECT COUNT(*) FROM pr02_terminal_records").fetchone()[0]
        == 0
    )
    assert store.recovery_summary()[0]["recovery_action"] == (
        "safe_indeterminacy_reconcile"
    )


def test_attempt_terminal_updates_lifecycle_reservation_and_outbox_together(tmp_path):
    store, _ = authority(tmp_path)
    key = AttemptKey("opportunity", digest("plan"), 1)
    attempt = store.lifecycle.create_attempt(
        key,
        idempotency_key="create-attempt",
        reservation_id="reservation-a",
        candidate_id="candidate-a",
        reserved_lamports=123,
    )
    fence = store.begin_attempt_intent(
        attempt_id=attempt.attempt_id,
        attempt_generation=1,
        request_payload={"candidate": "candidate-a"},
    )

    committed = store.commit_attempt_terminal(
        fence,
        target_state=ExecutionState.REJECTED,
        reservation_terminal_state=ReservationTerminalState.RELEASED,
        outcome="RECONCILED_PAPER_FAILURE",
        reason_code="ECONOMIC_REJECTION",
        report_hash=digest("attempt-report"),
        report_payload={"net_lamports": -1},
    )
    replay = store.commit_attempt_terminal(
        fence,
        target_state=ExecutionState.REJECTED,
        reservation_terminal_state=ReservationTerminalState.RELEASED,
        outcome="RECONCILED_PAPER_FAILURE",
        reason_code="ECONOMIC_REJECTION",
        report_hash=digest("attempt-report"),
        report_payload={"net_lamports": -1},
    )

    row = store.db.execute(
        "SELECT state,reservation_state,revision FROM durable_attempts "
        "WHERE attempt_id=?",
        (attempt.attempt_id,),
    ).fetchone()
    reservation = store.db.execute(
        "SELECT state FROM durable_reservations WHERE reservation_id=?",
        ("reservation-a",),
    ).fetchone()
    terminal = store.db.execute(
        "SELECT lifecycle_event_id,reservation_terminal_state "
        "FROM pr02_terminal_records"
    ).fetchone()

    assert tuple(row) == (ExecutionState.REJECTED.value, "released", 1)
    assert reservation[0] == "released"
    assert terminal[0] == committed.lifecycle_event_id
    assert terminal[1] == "released"
    assert replay.replayed
    assert store.db.execute("SELECT COUNT(*) FROM pr02_outbox_event").fetchone()[0] == 1


def test_provider_sink_requires_the_same_authority_connection(tmp_path):
    store, clock = authority(tmp_path)
    sink = UnifiedA3AdmissionSink(time_authority=clock)

    @dataclass(frozen=True)
    class Evidence:
        event_identity: str = digest("event")
        provider_evidence_hash: str = digest("provider")
        release_digest: str = digest("release")
        policy_bundle_hash: str = digest("policy")
        evidence_hash: str = digest("all-evidence")
        expires_at_monotonic_ns: int = 20_000

    with store.db:
        result = sink.commit(store.db, Evidence())
    assert (
        result
        == store.db.execute(
            "SELECT intent_id FROM pr02_intents WHERE intent_kind='provider_handoff'"
        ).fetchone()[0]
    )

    foreign = sqlite3.connect(tmp_path / "foreign.sqlite3")
    with pytest.raises(
        UnifiedAuthorityError,
        match="PR02_AUTHORITY_METADATA_MISSING|PR02_FOREIGN_TRANSACTION_CONNECTION",
    ):
        sink.commit(foreign, Evidence())


def test_dead_letter_is_append_only_and_cannot_replace_history(tmp_path):
    store, clock = authority(tmp_path)
    fence = begin_cycle(store)
    first = store.append_dead_letter(
        fence,
        reason_code="PROVIDER_RETRY_EXHAUSTED",
        attempt_count=3,
        evidence_hash=digest("evidence-a"),
    )
    clock.advance()
    second = store.append_dead_letter(
        fence,
        reason_code="OPERATOR_REVIEWED_RETRY",
        attempt_count=4,
        evidence_hash=digest("evidence-b"),
    )

    assert first != second
    assert (
        store.db.execute("SELECT COUNT(*) FROM pr02_dead_letter_history").fetchone()[0]
        == 2
    )
    with pytest.raises(sqlite3.IntegrityError, match="PR02_DEAD_LETTER_IMMUTABLE"):
        store.db.execute("UPDATE pr02_dead_letter_history SET reason_code='rewritten'")


def test_installed_a3_records_intent_before_batch_and_uses_pr02_outbox(tmp_path):
    config = load_runtime_config()
    db_path = tmp_path / "paper.sqlite3"
    seen = []
    provider_hash = digest("provider")

    service = InstalledDurablePaperService(
        config,
        InstalledPaperServiceConfig(db_path=db_path, run_id="pr02-a3"),
        batch_source=lambda: _batch_after_intent(service, seen, provider_hash),
        runtime_cycle=_no_trade_cycle,
    )
    report = asyncio.run(service.run_once())

    assert seen == [1]
    assert report.status is A3PaperServiceStatus.NO_TRADE
    with sqlite3.connect(db_path) as db:
        assert (
            db.execute(
                "SELECT product_id FROM database_identity_pr195 WHERE singleton=1"
            ).fetchone()[0]
            == PR02_PRODUCT_ID
        )
        assert db.execute("SELECT COUNT(*) FROM pr02_outbox_event").fetchone()[0] == 1
        assert (
            db.execute("SELECT status FROM a3_paper_service_cycles").fetchone()[0]
            == "NO_TRADE"
        )
        assert (
            db.execute("SELECT topic FROM a3_paper_service_outbox").fetchone()[0]
            == "paper.service.cycle_recorded"
        )


def _batch_after_intent(service, seen, provider_hash):
    seen.append(
        service.authority.db.execute(
            "SELECT COUNT(*) FROM pr02_intents WHERE intent_kind='paper_cycle'"
        ).fetchone()[0]
    )
    return A3ExactAttemptBatch(
        A3ProviderEvidenceState(provider_hash, ready=True),
        ("request-a",),
    )


async def _no_trade_cycle(cycle_id, items):
    assert items == ("request-a",)
    return ExactAttemptRuntimeReport(
        cycle_id=cycle_id,
        status=A2PaperOutcomeStatus.NO_TRADE,
        terminal_reason="no_trade",
        records=(),
    )
