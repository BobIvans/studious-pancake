from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path

import pytest

from src.release_soak_pr07 import (
    FaultDrill,
    PR07_CHECKPOINT_DOMAIN,
    PR07_CHECKPOINT_SCHEMA,
    PR07_GENESIS_CHECKPOINT,
    SQLiteSoakCheckpointStore,
    SignedSoakCheckpoint,
    SoakCheckpointPayload,
    SoakRunIdentity,
    SoakVerdict,
    SoakVerificationError,
    evaluate_soak,
)
from src.security.trust_anchors import SignedEnvelope, TrustVerificationResult

NOW = datetime(2026, 7, 23, 0, 0, tzinfo=timezone.utc)
SHA1 = "1" * 64
SHA2 = "2" * 64
SHA3 = "3" * 64
SHA4 = "4" * 64
SHA5 = "5" * 64


class FakeRegistry:
    generation = "trust-generation-7"

    def verify(
        self,
        envelope,
        payload,
        *,
        usage,
        evaluated_at,
        expected_domain,
        expected_environment,
    ):
        observed = hashlib.sha256(payload).hexdigest()
        blockers = []
        if envelope.domain != expected_domain:
            blockers.append("SIGNED_DOMAIN_MISMATCH")
        if envelope.environment != expected_environment:
            blockers.append("SIGNED_ENVIRONMENT_MISMATCH")
        if envelope.payload_sha256 != observed:
            blockers.append("SIGNED_PAYLOAD_HASH_MISMATCH")
        if not envelope.signature_base58.startswith("S"):
            blockers.append("CRYPTOGRAPHIC_SIGNATURE_INVALID")
        return TrustVerificationResult(
            verified=not blockers,
            key_id=envelope.key_id,
            blockers=tuple(blockers),
            payload_sha256=observed,
            registry_generation=self.generation,
        )


def _identity() -> SoakRunIdentity:
    return SoakRunIdentity(
        run_id="release-soak-20260723",
        source_commit="a" * 40,
        release_digest="sha256:" + SHA1,
        wheel_sha256=SHA2,
        image_digest="sha256:" + SHA3,
        policy_bundle_sha256=SHA4,
        provider_evidence_sha256=SHA5,
        cluster_genesis="5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
        environment="paper-mainnet",
        started_at=NOW,
    )


def _all_drills():
    return tuple(
        (drill, hashlib.sha256(drill.value.encode()).hexdigest())
        for drill in FaultDrill
    )


def _payload(
    identity: SoakRunIdentity,
    *,
    sequence: int,
    previous: str,
    hours: int,
    **overrides,
) -> SoakCheckpointPayload:
    values = dict(
        run_identity_sha256=identity.identity_sha256,
        sequence=sequence,
        previous_checkpoint_sha256=previous,
        observed_at=NOW + timedelta(hours=hours),
        process_generation=sequence,
        provider_events_admitted=10 * sequence,
        cycles_completed=8 * sequence,
        candidates_seen=3 * sequence,
        terminal_outcomes=(("BLOCKED", sequence), ("NO_TRADE", sequence)),
        retries=sequence,
        duplicates=sequence,
        dead_letters=0,
        reservation_leaks=0,
        duplicate_capital_uses=0,
        unreconciled_outcomes=0,
        data_gaps=0,
        queue_depth=1,
        max_queue_depth=4,
        rss_bytes=100_000_000,
        fd_count=30,
        task_count=12,
        event_loop_lag_ms=4,
        memory_stability_passed=True,
        descriptor_stability_passed=True,
        queue_stability_passed=True,
        resource_limits_passed=True,
        live_enabled=False,
        sender_reachable=False,
        signer_reachable=False,
        signatures_observed=0,
        submissions_observed=0,
        fixture_rows_observed=0,
        drill_evidence=_all_drills() if sequence > 1 else (),
        resource_evidence_sha256="6" * 64,
    )
    values.update(overrides)
    return SoakCheckpointPayload(**values)


def _signed(payload: SoakCheckpointPayload, *, signature: str = "S" * 88):
    return SignedSoakCheckpoint(
        payload=payload,
        envelope=SignedEnvelope(
            domain=PR07_CHECKPOINT_DOMAIN,
            schema_version=PR07_CHECKPOINT_SCHEMA,
            environment="paper-mainnet",
            key_id="evidence-key-7",
            issued_at=payload.observed_at,
            expires_at=payload.observed_at + timedelta(days=30),
            payload_sha256=payload.checkpoint_sha256,
            signature_base58=signature,
        ),
    )


def _chain(identity: SoakRunIdentity):
    first_payload = _payload(
        identity,
        sequence=1,
        previous=PR07_GENESIS_CHECKPOINT,
        hours=1,
    )
    first = _signed(first_payload)
    final_payload = _payload(
        identity,
        sequence=2,
        previous=first_payload.checkpoint_sha256,
        hours=73,
    )
    return first, _signed(final_payload)


def test_ready_soak_requires_signed_72h_chain_and_all_drills() -> None:
    identity = _identity()
    report = evaluate_soak(
        identity,
        _chain(identity),
        FakeRegistry(),
        evaluated_at=NOW + timedelta(hours=74),
    )

    assert report.verdict is SoakVerdict.READY_FOR_REVIEW
    assert report.blockers == ()
    assert report.observed_duration_seconds == 73 * 60 * 60
    assert report.d2_soak_evidence["non_synthetic"] is True
    assert report.d2_soak_evidence["restart_recovery_passed"] is True
    assert report.to_dict()["live_enabled"] is False


def test_short_or_unsigned_soak_is_blocked() -> None:
    identity = _identity()
    first, final = _chain(identity)
    short_payload = replace(final.payload, observed_at=NOW + timedelta(hours=71))
    short = _signed(short_payload, signature="X" * 88)

    report = evaluate_soak(
        identity,
        (first, short),
        FakeRegistry(),
        evaluated_at=NOW + timedelta(hours=72),
    )

    assert report.verdict is SoakVerdict.BLOCKED
    assert "PR07_SOAK_DURATION_BELOW_72_HOURS" in report.blockers
    assert "CRYPTOGRAPHIC_SIGNATURE_INVALID" in report.blockers
    assert "PR07_CHECKPOINT_CHAIN_NOT_FULLY_VERIFIED" in report.blockers


def test_sender_fixture_and_duplicate_capital_contamination_blocks() -> None:
    identity = _identity()
    first, final = _chain(identity)
    contaminated_payload = replace(
        final.payload,
        sender_reachable=True,
        signatures_observed=1,
        fixture_rows_observed=2,
        duplicate_capital_uses=1,
    )
    contaminated = _signed(contaminated_payload)

    report = evaluate_soak(
        identity,
        (first, contaminated),
        FakeRegistry(),
        evaluated_at=NOW + timedelta(hours=74),
    )

    assert "PR07_SENDER_REACHABLE" in report.blockers
    assert "PR07_SIGNATURES_OBSERVED" in report.blockers
    assert "PR07_SYNTHETIC_OR_FIXTURE_ROWS_OBSERVED" in report.blockers
    assert "PR07_DUPLICATE_CAPITAL_USAGE" in report.blockers


def test_missing_fault_drill_blocks_final_artifact() -> None:
    identity = _identity()
    first, final = _chain(identity)
    drills = tuple(
        item
        for item in final.payload.drill_evidence
        if item[0] is not FaultDrill.ROLLBACK
    )
    incomplete = _signed(replace(final.payload, drill_evidence=drills))

    report = evaluate_soak(
        identity,
        (first, incomplete),
        FakeRegistry(),
        evaluated_at=NOW + timedelta(hours=74),
    )

    assert "PR07_DRILL_MISSING:rollback" in report.blockers


def test_store_is_append_only_resumable_and_exact_replay(tmp_path: Path) -> None:
    identity = _identity()
    first, final = _chain(identity)
    path = tmp_path / "soak.sqlite3"
    with SQLiteSoakCheckpointStore(path, identity, FakeRegistry()) as store:
        added = store.append(first, evaluated_at=NOW + timedelta(hours=2))
        replayed = store.append(first, evaluated_at=NOW + timedelta(hours=2))
        assert added.replayed is False
        assert replayed.replayed is True

    with SQLiteSoakCheckpointStore(path, identity, FakeRegistry()) as resumed:
        resumed.append(final, evaluated_at=NOW + timedelta(hours=74))
        report = resumed.evaluate(evaluated_at=NOW + timedelta(hours=74))
        assert report.verdict is SoakVerdict.READY_FOR_REVIEW
        assert len(resumed.checkpoints()) == 2


def test_store_rejects_conflicting_replay_and_counter_regression(
    tmp_path: Path,
) -> None:
    identity = _identity()
    first, final = _chain(identity)
    with SQLiteSoakCheckpointStore(
        tmp_path / "soak.sqlite3", identity, FakeRegistry()
    ) as store:
        store.append(first, evaluated_at=NOW + timedelta(hours=2))
        conflict = _signed(replace(first.payload, candidates_seen=99))
        with pytest.raises(SoakVerificationError, match="IMMUTABILITY_CONFLICT"):
            store.append(conflict, evaluated_at=NOW + timedelta(hours=2))

        regressed_payload = replace(final.payload, provider_events_admitted=0)
        with pytest.raises(SoakVerificationError, match="COUNTER_REGRESSION"):
            store.append(
                _signed(regressed_payload),
                evaluated_at=NOW + timedelta(hours=74),
            )


def test_chain_identity_and_previous_hash_drift_fail_closed() -> None:
    identity = _identity()
    first, final = _chain(identity)
    wrong_previous = _signed(
        replace(final.payload, previous_checkpoint_sha256="9" * 64)
    )

    report = evaluate_soak(
        identity,
        (first, wrong_previous),
        FakeRegistry(),
        evaluated_at=NOW + timedelta(hours=74),
    )

    assert "PR07_CHECKPOINT_CHAIN_DIVERGENCE" in report.blockers
