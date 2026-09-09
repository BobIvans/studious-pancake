from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path

from src.release_gate.mpr29_continuous_shadow_soak import (
    ContinuousShadowSoakBundle,
    DataLineageEvidence,
    InstalledCommandSurfaceEvidence,
    LifecycleOutcomeEvidence,
    MPR29_EVIDENCE_KIND,
    MPR29_ID,
    MPR29_SCHEMA_VERSION,
    ProviderSnapshotEvidence,
    SloEvidence,
    bundle_from_mapping,
    evaluate_mpr29_soak,
    signed_artifact_payload,
)
from src.release_gate.mpr31_final_promotion_gate import (
    SignedEvidenceArtifact,
    UpstreamMprEvidence,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
HASH_F = "f" * 64
HASH_1 = "1" * 64
HASH_2 = "2" * 64
HASH_3 = "3" * 64
HASH_4 = "4" * 64
HASH_5 = "5" * 64
HASH_6 = "6" * 64
HASH_7 = "7" * 64
HASH_8 = "8" * 64
HASH_9 = "9" * 64


def command_surface() -> InstalledCommandSurfaceEvidence:
    return InstalledCommandSurfaceEvidence(
        installed_wheel_sha256=HASH_A,
        command_surface_sha256=HASH_B,
        console_command="flashloan-bot",
        source_checkout_used=False,
        installed_artifact_used=True,
        runtime_modes=("paper", "shadow"),
        live_enabled=False,
        signer_loaded=False,
        sender_loaded=False,
    )


def provider_snapshot(provider: str, replay_hash: str) -> ProviderSnapshotEvidence:
    return ProviderSnapshotEvidence(
        provider=provider,
        endpoint_generation_sha256=HASH_C,
        request_sha256=HASH_D,
        response_sha256=HASH_E,
        normalized_quote_sha256=HASH_F,
        context_slot=123,
        observed_at_unix_ns=1_000,
        non_synthetic=True,
        replay_hash=replay_hash,
    )


def lifecycle(
    cycle_id: str,
    mode: str,
    replay_hash: str,
    provider_snapshot_hash: str,
) -> LifecycleOutcomeEvidence:
    return LifecycleOutcomeEvidence(
        cycle_id=cycle_id,
        mode=mode,
        status="PAPER_ACCEPTED",
        lifecycle_db_sha256=HASH_1,
        replay_hash=replay_hash,
        provider_snapshot_hash=provider_snapshot_hash,
        latency_ms=100,
        finalized_settlement_observed=True,
        ready_for_next_cycle=True,
        sender_imported=False,
        submission_allowed=False,
        live_enabled=False,
    )


def valid_bundle() -> ContinuousShadowSoakBundle:
    snap_a = provider_snapshot("jupiter", HASH_2)
    snap_b = provider_snapshot("okx", HASH_3)
    return ContinuousShadowSoakBundle(
        schema_version=MPR29_SCHEMA_VERSION,
        command_surface=command_surface(),
        provider_snapshots=(snap_a, snap_b),
        lifecycle_outcomes=(
            lifecycle("cycle-1", "paper", HASH_4, snap_a.replay_hash),
            lifecycle("cycle-2", "shadow", HASH_5, snap_b.replay_hash),
            lifecycle("cycle-3", "paper", HASH_6, snap_a.replay_hash),
        ),
        slo=SloEvidence(
            p50_latency_ms=100,
            p95_latency_ms=250,
            max_latency_ms=400,
            data_loss_events=0,
            provider_error_events=0,
            reconciliation_gap_events=0,
            queue_backlog_max=1,
        ),
        lineage=DataLineageEvidence(
            synthetic_namespace_sha256=HASH_7,
            recorded_namespace_sha256=HASH_8,
            finalized_namespace_sha256=HASH_9,
            quarantine_policy_sha256=HASH_A,
            synthetic_record_count=0,
            finalized_record_count=3,
            namespaces_disjoint=True,
            replay_separates_recorded_and_finalized=True,
        ),
        issued_at_ns=1_000,
        expires_at_ns=2_000,
        immutable_uri="file://release_artifacts/mpr29/soak.json",
        reviewer_digests=(HASH_B,),
    )


def test_valid_installed_soak_is_default_off_accepted() -> None:
    decision = evaluate_mpr29_soak(valid_bundle())

    assert decision.accepted
    assert decision.evidence_kind == MPR29_EVIDENCE_KIND
    assert decision.live_enabled is False
    assert decision.signer_loaded is False
    assert decision.sender_loaded is False
    assert decision.to_dict()["production_ready"] is False
    assert "MPR29_CONTINUOUS_SOAK_ACCEPTED_DEFAULT_OFF" in decision.reason_codes


def test_source_checkout_or_missing_installed_artifact_blocks() -> None:
    bundle = valid_bundle()
    command = replace(
        bundle.command_surface,
        source_checkout_used=True,
        installed_artifact_used=False,
    )

    decision = evaluate_mpr29_soak(replace(bundle, command_surface=command))

    assert not decision.accepted
    assert "MPR29_SOURCE_CHECKOUT_NOT_ALLOWED" in decision.reason_codes
    assert "MPR29_INSTALLED_ARTIFACT_REQUIRED" in decision.reason_codes


def test_live_signer_sender_or_live_mode_advertising_blocks() -> None:
    bundle = valid_bundle()
    command = replace(
        bundle.command_surface,
        runtime_modes=("paper", "shadow", "live"),
        live_enabled=True,
        signer_loaded=True,
        sender_loaded=True,
    )

    decision = evaluate_mpr29_soak(replace(bundle, command_surface=command))

    assert not decision.accepted
    assert "MPR29_LIVE_SIGNER_OR_SENDER_FORBIDDEN" in decision.reason_codes
    assert "MPR29_LIVE_MODE_MUST_NOT_BE_ADVERTISED" in decision.reason_codes


def test_provider_snapshots_must_be_non_synthetic_and_diverse() -> None:
    bundle = valid_bundle()
    first = replace(bundle.provider_snapshots[0], non_synthetic=False)
    second = replace(bundle.provider_snapshots[1], provider="jupiter")

    decision = evaluate_mpr29_soak(
        replace(bundle, provider_snapshots=(first, second))
    )

    assert not decision.accepted
    assert "MPR29_SYNTHETIC_PROVIDER_SNAPSHOT" in decision.reason_codes
    assert "MPR29_PROVIDER_DIVERSITY_REQUIRED" in decision.reason_codes


def test_lifecycle_outcomes_must_remain_sender_free() -> None:
    bundle = valid_bundle()
    bad = replace(
        bundle.lifecycle_outcomes[0],
        sender_imported=True,
        submission_allowed=True,
        live_enabled=True,
    )

    decision = evaluate_mpr29_soak(
        replace(bundle, lifecycle_outcomes=(bad, *bundle.lifecycle_outcomes[1:]))
    )

    assert not decision.accepted
    assert "MPR29_UNSAFE_LIFECYCLE_SURFACE" in decision.reason_codes


def test_lineage_and_slo_gaps_block_acceptance() -> None:
    bundle = valid_bundle()
    lineage = replace(
        bundle.lineage,
        namespaces_disjoint=False,
        synthetic_record_count=1,
    )
    slo = replace(bundle.slo, p95_latency_ms=9_999, data_loss_events=1)

    decision = evaluate_mpr29_soak(replace(bundle, lineage=lineage, slo=slo))

    assert not decision.accepted
    assert "MPR29_LINEAGE_NAMESPACES_NOT_DISJOINT" in decision.reason_codes
    assert "MPR29_SYNTHETIC_RECORDS_PRESENT" in decision.reason_codes
    assert "MPR29_P95_LATENCY_SLO_BREACH" in decision.reason_codes
    assert "MPR29_DATA_LOSS_EVENTS" in decision.reason_codes


def test_signed_artifact_payload_is_mpr31_compatible() -> None:
    payload = signed_artifact_payload(valid_bundle())
    artifact = SignedEvidenceArtifact(
        kind=str(payload["kind"]),
        digest=str(payload["digest"]),
        signature_digest=str(payload["signature_digest"]),
        reviewer_digests=tuple(str(item) for item in payload["reviewer_digests"]),
        issued_at_ns=int(payload["issued_at_ns"]),
        expires_at_ns=int(payload["expires_at_ns"]),
        size_bytes=int(payload["size_bytes"]),
        immutable_uri=str(payload["immutable_uri"]),
    )
    upstream = UpstreamMprEvidence(mpr_id=str(payload["mpr_id"]), artifact=artifact)

    assert upstream.mpr_id == MPR29_ID
    assert upstream.artifact.kind == MPR29_EVIDENCE_KIND
    assert payload["live_enabled"] is False
    assert payload["signer_loaded"] is False
    assert payload["sender_loaded"] is False


def test_json_decoder_preserves_default_off_contract(tmp_path: Path) -> None:
    bundle = valid_bundle()
    payload = asdict(bundle)
    payload["command_surface"]["runtime_modes"] = list(
        payload["command_surface"]["runtime_modes"]
    )
    payload["reviewer_digests"] = list(payload["reviewer_digests"])
    path = tmp_path / "mpr29.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    decoded = bundle_from_mapping(json.loads(path.read_text(encoding="utf-8")))
    decision = evaluate_mpr29_soak(decoded)

    assert decision.accepted


def test_packaged_contract_matches_runtime_constants() -> None:
    path = Path("src/resources/mpr29_continuous_shadow_soak_contract.json")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["mpr_id"] == MPR29_ID
    assert payload["evidence_kind"] == MPR29_EVIDENCE_KIND
    assert payload["installed_artifact_required"] is True
    assert payload["source_checkout_allowed"] is False
    assert payload["live_enabled"] is False
    assert payload["signer_loaded"] is False
    assert payload["sender_loaded"] is False
