from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.observability.archive import (
    ArchiveCoordinator,
    ArchiveError,
    RemoteArchiveAck,
)
from src.observability.events import (
    Environment,
    EventEnvelope,
    EventType,
    Outcome,
    Severity,
)
from src.observability.export import export_jsonl, verify_archive
from src.observability.store import ObservabilityStore


def _ns(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=UTC).timestamp() * 1_000_000_000)


def _event(
    sequence_no: int,
    *,
    event_type: EventType = EventType.quote_received,
) -> EventEnvelope:
    aggregate_id = "pr198-aggregate"
    return EventEnvelope(
        event_id=f"{aggregate_id}-{sequence_no}-{event_type.value}",
        schema_version=1,
        occurred_at_utc_ns=_ns(2026, 7, 22),
        monotonic_ns=sequence_no,
        runtime_id="pr198-runtime",
        environment=Environment.test,
        trace_id="pr198-trace",
        logical_opportunity_id="pr198-opportunity",
        plan_hash="pr198-plan",
        attempt_generation=1,
        attempt_id="pr198-attempt",
        message_hash=None,
        tx_signature=None,
        jito_bundle_id=None,
        event_type=event_type,
        aggregate_id=aggregate_id,
        sequence_no=sequence_no,
        stage=event_type.value,
        outcome=Outcome.observed,
        reason_code=None,
        severity=Severity.info,
        correlation_id=None,
        provider_id="provider-test",
        venue_id="venue-test",
        attributes={"sequence_no": sequence_no},
        producer_code_version="release-pr198",
        config_checksum="policy-pr198",
        contract_fixture_version="contract-pr198",
        idempotency_key=f"{aggregate_id}:{sequence_no}:{event_type.value}",
    )


def test_pr198_second_export_preserves_first_immutable_segment(tmp_path: Path) -> None:
    store = ObservabilityStore(tmp_path / "archive.db")
    store.append(_event(1))

    first = export_jsonl(store, tmp_path / "out", exporter_id="exporter-a")
    first_path = Path(first["manifests"][0]["path"])
    first_bytes = first_path.read_bytes()

    store.append(_event(2))
    second = export_jsonl(store, tmp_path / "out", exporter_id="exporter-a")
    second_path = Path(second["manifests"][0]["path"])

    assert first_path != second_path
    assert first_path.read_bytes() == first_bytes
    assert second_path.exists()
    assert first_path.name.startswith("segment=")
    assert second_path.name.startswith("segment=")
    assert first["legacy_authoritative"] is False
    assert second["legacy_authoritative"] is False


def test_pr198_persists_every_manifest_and_exact_outbox_link(tmp_path: Path) -> None:
    store = ObservabilityStore(tmp_path / "archive.db")
    store.append(_event(1, event_type=EventType.quote_received))
    store.append(_event(2, event_type=EventType.route_planned))

    result = export_jsonl(store, tmp_path / "out", exporter_id="exporter-a")

    assert result["manifest_count"] == 2
    assert store.db.execute(
        "SELECT COUNT(*) FROM archive_segment_manifest"
    ).fetchone()[0] == 2
    assert store.db.execute("SELECT COUNT(*) FROM export_manifest").fetchone()[0] == 2
    assert store.db.execute(
        "SELECT COUNT(*) FROM archive_segment_event"
    ).fetchone()[0] == 2
    assert store.db.execute(
        "SELECT COUNT(*) FROM outbox WHERE status='done'"
    ).fetchone()[0] == 2
    assert verify_archive(store, tmp_path / "out")["ok"] is True


def test_pr198_fenced_claim_prevents_duplicate_exporter_ownership(
    tmp_path: Path,
) -> None:
    database = tmp_path / "archive.db"
    first_store = ObservabilityStore(database)
    first_store.append(_event(1))
    second_store = ObservabilityStore(database)

    first_claim = ArchiveCoordinator(first_store).claim_pending(
        exporter_id="exporter-a",
        lease_seconds=60,
    )
    second_claim = ArchiveCoordinator(second_store).claim_pending(
        exporter_id="exporter-b",
        lease_seconds=60,
    )

    assert first_claim is not None
    assert second_claim is None


def test_pr198_recovers_published_segment_after_precommit_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ObservabilityStore(tmp_path / "archive.db")
    store.append(_event(1))
    original_commit = ArchiveCoordinator.commit_segment
    calls = 0

    def crash_once(self: ArchiveCoordinator, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated crash after immutable publication")
        original_commit(self, **kwargs)

    monkeypatch.setattr(ArchiveCoordinator, "commit_segment", crash_once)
    with pytest.raises(RuntimeError, match="simulated crash"):
        export_jsonl(
            store,
            tmp_path / "out",
            exporter_id="crashing-exporter",
            lease_seconds=60,
        )

    orphan_files = list(
        (tmp_path / "out").glob("date_utc=*/event_type=*/segment=*.jsonl")
    )
    assert len(orphan_files) == 1
    assert store.db.execute(
        "SELECT COUNT(*) FROM archive_segment_manifest"
    ).fetchone()[0] == 0

    monkeypatch.setattr(ArchiveCoordinator, "commit_segment", original_commit)
    store.db.execute(
        "UPDATE archive_export_claim SET lease_expires_at=0 WHERE state='active'"
    )
    recovered = export_jsonl(
        store,
        tmp_path / "out",
        exporter_id="recovery-exporter",
        lease_seconds=60,
    )

    assert recovered["recovered_manifest_count"] == 1
    assert store.db.execute(
        "SELECT status FROM outbox WHERE event_id=?",
        (_event(1).event_id,),
    ).fetchone()[0] == "done"
    assert verify_archive(store, tmp_path / "out")["ok"] is True


def test_pr198_never_overwrites_conflicting_orphan_segment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ObservabilityStore(tmp_path / "archive.db")
    store.append(_event(1))
    original_commit = ArchiveCoordinator.commit_segment

    def crash(self: ArchiveCoordinator, **_kwargs: object) -> None:
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(ArchiveCoordinator, "commit_segment", crash)
    with pytest.raises(RuntimeError, match="simulated crash"):
        export_jsonl(store, tmp_path / "out", exporter_id="crash")
    orphan = next(
        (tmp_path / "out").glob("date_utc=*/event_type=*/segment=*.jsonl")
    )
    orphan.write_bytes(b"attacker-controlled replacement\n")
    tampered = orphan.read_bytes()

    monkeypatch.setattr(ArchiveCoordinator, "commit_segment", original_commit)
    store.db.execute(
        "UPDATE archive_export_claim SET lease_expires_at=0 WHERE state='active'"
    )
    with pytest.raises(ArchiveError, match="ARCHIVE_ORPHAN_CHECKSUM_MISMATCH"):
        export_jsonl(store, tmp_path / "out", exporter_id="recovery")
    assert orphan.read_bytes() == tampered


class _ArchiveUploader:
    def upload(
        self,
        *,
        segment_path: Path,
        manifest: dict[str, object],
    ) -> RemoteArchiveAck:
        assert segment_path.exists()
        return RemoteArchiveAck(
            archive_name="test-archive",
            object_key=str(manifest["object_key"]),
            object_version="version-1",
            object_digest=str(manifest["checksum"]),
            metadata={"retention": "immutable"},
        )


def test_pr198_records_required_remote_archive_ack(tmp_path: Path) -> None:
    store = ObservabilityStore(tmp_path / "archive.db")
    store.append(_event(1))

    result = export_jsonl(
        store,
        tmp_path / "out",
        exporter_id="exporter-a",
        archive_uploader=_ArchiveUploader(),
        require_remote_ack=True,
    )

    assert result["remote_ack_pending"] == 0
    ack = store.db.execute("SELECT * FROM archive_remote_ack").fetchone()
    assert ack["archive_name"] == "test-archive"
    assert ack["object_version"] == "version-1"
    assert verify_archive(
        store,
        tmp_path / "out",
        require_remote_ack=True,
    )["ok"] is True


class _FlakyArchiveUploader:
    def __init__(self) -> None:
        self.calls = 0

    def upload(
        self,
        *,
        segment_path: Path,
        manifest: dict[str, object],
    ) -> RemoteArchiveAck:
        self.calls += 1
        assert segment_path.exists()
        if self.calls == 1:
            raise RuntimeError("temporary archive failure")
        return RemoteArchiveAck(
            archive_name="test-archive",
            object_key=str(manifest["object_key"]),
            object_version="version-2",
            object_digest=str(manifest["checksum"]),
        )


def test_pr198_retries_remote_ack_from_persisted_manifest(tmp_path: Path) -> None:
    store = ObservabilityStore(tmp_path / "archive.db")
    store.append(_event(1))
    uploader = _FlakyArchiveUploader()

    with pytest.raises(ArchiveError, match="ARCHIVE_REMOTE_ACK_FAILED"):
        export_jsonl(
            store,
            tmp_path / "out",
            exporter_id="exporter-a",
            archive_uploader=uploader,
            require_remote_ack=True,
        )

    retried = export_jsonl(
        store,
        tmp_path / "out",
        exporter_id="exporter-b",
        archive_uploader=uploader,
        require_remote_ack=True,
    )

    assert uploader.calls == 2
    assert retried["event_count"] == 0
    assert retried["remote_ack_pending"] == 0
    assert store.db.execute(
        "SELECT remote_status FROM archive_segment_manifest"
    ).fetchone()[0] == "acked"
    assert verify_archive(
        store,
        tmp_path / "out",
        require_remote_ack=True,
    )["ok"] is True


def test_pr198_rejects_remote_ack_for_wrong_object_key(tmp_path: Path) -> None:
    store = ObservabilityStore(tmp_path / "archive.db")
    store.append(_event(1))
    result = export_jsonl(store, tmp_path / "out", exporter_id="exporter-a")
    manifest = result["manifests"][0]

    with pytest.raises(
        ArchiveError,
        match="ARCHIVE_REMOTE_OBJECT_KEY_MISMATCH",
    ):
        ArchiveCoordinator(store).record_remote_ack(
            segment_id=str(manifest["segment_id"]),
            ack=RemoteArchiveAck(
                archive_name="wrong-archive",
                object_key="wrong/object.jsonl",
                object_version="version-1",
                object_digest=str(manifest["checksum"]),
            ),
        )

    assert store.db.execute(
        "SELECT COUNT(*) FROM archive_remote_ack"
    ).fetchone()[0] == 0
