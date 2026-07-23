from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import cast

import pytest
from aiohttp import web

from src.observability.active_management import ActiveManagementHttpServer
from src.observability.audit_anchor_pr06 import (
    AuditAnchorError,
    capture_signed_checkpoint,
    create_external_anchor,
    verify_checkpoint_and_anchor,
)
from src.observability.integrity import (
    ZERO_CHAIN_DIGEST,
    compute_chain_digest,
    sha256_json,
)
from src.observability.management_plane_pr170 import (
    ManagementPlanePolicy,
    SnapshotValidation,
)

pytestmark = pytest.mark.unit


def _write_keypair(path: Path):
    from solders.keypair import Keypair

    keypair = Keypair()
    path.write_text(json.dumps(list(bytes(keypair))), encoding="utf-8")
    path.chmod(0o600)
    return keypair


def _event_payload() -> dict[str, object]:
    return {
        "event_id": "event-pr06",
        "aggregate_id": "attempt:pr06",
        "sequence_no": 1,
        "idempotency_key": "pr06:event:1",
        "occurred_at_utc_ns": 100,
        "monotonic_ns": 50,
        "event_type": "attempt_terminal",
        "schema_version": 2,
        "reason_code": None,
        "outcome": "failed",
        "stage": "settlement",
        "severity": "warning",
        "environment": "paper",
        "logical_opportunity_id": "opp-pr06",
        "plan_hash": hashlib.sha256(b"plan").hexdigest(),
        "attempt_generation": 1,
        "attempt_id": "attempt-pr06",
        "message_hash": hashlib.sha256(b"message").hexdigest(),
        "tx_signature": None,
        "jito_bundle_id": None,
        "provider_id": "fixture",
        "venue_id": "marginfi",
        "config_checksum": hashlib.sha256(b"policy").hexdigest(),
        "producer_code_version": "release-pr06",
        "contract_fixture_version": "fixture-pr06-v1",
        "attributes": {"terminal_authority": "test"},
    }


def _make_audit_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(
        """
        CREATE TABLE audit_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO audit_meta(key,value) VALUES('database_epoch','epoch-pr06');
        CREATE TABLE event_log(
            event_id TEXT PRIMARY KEY,
            aggregate_id TEXT NOT NULL,
            sequence_no INTEGER NOT NULL,
            idempotency_key TEXT NOT NULL,
            occurred_at_utc_ns INTEGER NOT NULL,
            monotonic_ns INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            reason_code TEXT,
            outcome TEXT NOT NULL,
            stage TEXT NOT NULL,
            severity TEXT NOT NULL,
            environment TEXT NOT NULL,
            logical_opportunity_id TEXT NOT NULL,
            plan_hash TEXT NOT NULL,
            attempt_generation INTEGER NOT NULL,
            attempt_id TEXT,
            message_hash TEXT,
            tx_signature TEXT,
            jito_bundle_id TEXT,
            provider_id TEXT,
            venue_id TEXT,
            payload_json TEXT NOT NULL,
            payload_digest TEXT NOT NULL,
            config_checksum TEXT NOT NULL,
            redaction_version TEXT NOT NULL,
            redaction_hits INTEGER NOT NULL,
            producer_code_version TEXT NOT NULL,
            contract_fixture_version TEXT NOT NULL,
            previous_chain_digest TEXT NOT NULL,
            chain_digest TEXT NOT NULL,
            database_epoch TEXT NOT NULL,
            writer_generation TEXT NOT NULL,
            release_id TEXT NOT NULL,
            policy_bundle_hash TEXT NOT NULL
        );
        """
    )
    payload = _event_payload()
    payload_digest = sha256_json(payload)
    row = {
        **{key: value for key, value in payload.items() if key != "attributes"},
        "payload_json": json.dumps(payload, sort_keys=True, separators=(",", ":")),
        "payload_digest": payload_digest,
        "redaction_version": "pr043.redaction.v1",
        "redaction_hits": 0,
        "previous_chain_digest": ZERO_CHAIN_DIGEST,
        "database_epoch": "epoch-pr06",
        "writer_generation": "runtime-pr06",
        "release_id": "release-pr06",
        "policy_bundle_hash": payload["config_checksum"],
    }
    row["chain_digest"] = compute_chain_digest(
        row=row,
        previous_chain_digest=ZERO_CHAIN_DIGEST,
        database_epoch="epoch-pr06",
        writer_generation="runtime-pr06",
        release_id="release-pr06",
        policy_bundle_hash=str(payload["config_checksum"]),
    )
    columns = tuple(row)
    placeholders = ",".join("?" for _ in columns)
    connection.execute(
        f"INSERT INTO event_log({','.join(columns)}) VALUES({placeholders})",
        tuple(row[column] for column in columns),
    )
    connection.commit()
    return connection


def test_signed_checkpoint_anchor_and_independent_verification(tmp_path: Path) -> None:
    database = tmp_path / "observability.sqlite"
    connection = _make_audit_database(database)
    checkpoint_key_path = tmp_path / "checkpoint-key.json"
    anchor_key_path = tmp_path / "anchor-key.json"
    checkpoint_key = _write_keypair(checkpoint_key_path)
    anchor_key = _write_keypair(anchor_key_path)
    policy_hash = hashlib.sha256(b"policy").hexdigest()
    bundle = tmp_path / "bundle"
    anchors = tmp_path / "external-anchor"
    try:
        checkpoint = capture_signed_checkpoint(
            database_path=database,
            output_directory=bundle,
            release_id="release-pr06",
            source_commit="a" * 40,
            environment="paper",
            policy_bundle_hash=policy_hash,
            keypair_path=checkpoint_key_path,
            created_at_unix_ns=1_000,
        )
    finally:
        connection.close()
    receipt, receipt_path = create_external_anchor(
        checkpoint_path=bundle / "audit-checkpoint.json",
        anchor_directory=anchors,
        anchor_id="worm-mount-pr06",
        keypair_path=anchor_key_path,
        anchored_at_unix_ns=2_000,
    )
    result = verify_checkpoint_and_anchor(
        checkpoint_path=bundle / "audit-checkpoint.json",
        anchor_receipt_path=receipt_path,
        expected_checkpoint_pubkey=str(checkpoint_key.pubkey()),
        expected_anchor_pubkey=str(anchor_key.pubkey()),
        expected_policy_bundle_hash=policy_hash,
        expected_environment="paper",
    )
    assert result.accepted is True
    assert result.blockers == ()
    assert result.event_count == 1
    assert checkpoint.checkpoint_digest == receipt.checkpoint_digest
    assert {item.role for item in checkpoint.artifacts} >= {"snapshot", "raw-db"}
    assert stat_mode(receipt_path) == 0o600


def test_snapshot_mutation_invalidates_checkpoint(tmp_path: Path) -> None:
    database = tmp_path / "observability.sqlite"
    connection = _make_audit_database(database)
    checkpoint_key_path = tmp_path / "checkpoint-key.json"
    anchor_key_path = tmp_path / "anchor-key.json"
    checkpoint_key = _write_keypair(checkpoint_key_path)
    anchor_key = _write_keypair(anchor_key_path)
    policy_hash = hashlib.sha256(b"policy").hexdigest()
    bundle = tmp_path / "bundle"
    try:
        capture_signed_checkpoint(
            database_path=database,
            output_directory=bundle,
            release_id="release-pr06",
            source_commit="b" * 40,
            environment="paper",
            policy_bundle_hash=policy_hash,
            keypair_path=checkpoint_key_path,
            created_at_unix_ns=1_000,
        )
    finally:
        connection.close()
    _, receipt_path = create_external_anchor(
        checkpoint_path=bundle / "audit-checkpoint.json",
        anchor_directory=tmp_path / "external-anchor",
        anchor_id="worm-mount-pr06",
        keypair_path=anchor_key_path,
        anchored_at_unix_ns=2_000,
    )
    snapshot = bundle / "observability-snapshot.sqlite"
    with sqlite3.connect(snapshot) as mutable:
        mutable.execute("UPDATE event_log SET stage='tampered'")
    result = verify_checkpoint_and_anchor(
        checkpoint_path=bundle / "audit-checkpoint.json",
        anchor_receipt_path=receipt_path,
        expected_checkpoint_pubkey=str(checkpoint_key.pubkey()),
        expected_anchor_pubkey=str(anchor_key.pubkey()),
        expected_policy_bundle_hash=policy_hash,
        expected_environment="paper",
    )
    assert result.accepted is False
    assert any(
        blocker.startswith("ARTIFACT_HASH_MISMATCH")
        or blocker == "CONSISTENT_SNAPSHOT_CHAIN_INVALID"
        for blocker in result.blockers
    )


def test_anchor_receipt_is_create_only(tmp_path: Path) -> None:
    database = tmp_path / "observability.sqlite"
    connection = _make_audit_database(database)
    checkpoint_key_path = tmp_path / "checkpoint-key.json"
    anchor_key_path = tmp_path / "anchor-key.json"
    _write_keypair(checkpoint_key_path)
    _write_keypair(anchor_key_path)
    bundle = tmp_path / "bundle"
    try:
        capture_signed_checkpoint(
            database_path=database,
            output_directory=bundle,
            release_id="release-pr06",
            source_commit="c" * 40,
            environment="paper",
            policy_bundle_hash=hashlib.sha256(b"policy").hexdigest(),
            keypair_path=checkpoint_key_path,
            created_at_unix_ns=1_000,
        )
    finally:
        connection.close()
    arguments = {
        "checkpoint_path": bundle / "audit-checkpoint.json",
        "anchor_directory": tmp_path / "external-anchor",
        "anchor_id": "worm-mount-pr06",
        "keypair_path": anchor_key_path,
    }
    _, first_path = create_external_anchor(**arguments, anchored_at_unix_ns=2_000)
    _, second_path = create_external_anchor(**arguments, anchored_at_unix_ns=2_000)
    assert first_path == second_path
    with pytest.raises(AuditAnchorError, match="different content"):
        create_external_anchor(**arguments, anchored_at_unix_ns=3_000)


def test_management_deadline_includes_semaphore_wait() -> None:
    policy = ManagementPlanePolicy(
        max_connections=1,
        request_timeout_seconds=0.05,
        policy_bundle_hash="0" * 64,
    )
    server = ActiveManagementHttpServer(
        lambda: SnapshotValidation(False, None), policy=policy
    )

    async def exercise() -> tuple[int, float]:
        await server._connections.acquire()

        async def unreachable(_request: web.Request) -> web.Response:
            raise AssertionError("handler ran without queue admission")

        started = time.monotonic()
        try:
            response = await server._bounded(
                unreachable, cast(web.Request, object())
            )
        finally:
            server._connections.release()
        return response.status, time.monotonic() - started

    status, elapsed = asyncio.run(exercise())
    assert status == 503
    assert elapsed < 0.2


def test_state_provider_runs_outside_event_loop_thread() -> None:
    policy = ManagementPlanePolicy(policy_bundle_hash="0" * 64)
    observed_thread: list[int] = []

    def provider() -> SnapshotValidation:
        observed_thread.append(threading.get_ident())
        return SnapshotValidation(False, None)

    server = ActiveManagementHttpServer(provider, policy=policy)

    async def exercise() -> tuple[int, SnapshotValidation]:
        loop_thread = threading.get_ident()
        result = await server._state_validation()
        return loop_thread, result

    loop_thread, result = asyncio.run(exercise())
    assert result.ok is False
    assert observed_thread and observed_thread[0] != loop_thread


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777
