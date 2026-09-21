from __future__ import annotations

import hashlib
import inspect

import src.mega8_01 as mega
from src.mega8_01 import Disposition


H40_A = "1" * 40
H40_B = "2" * 40
H64_A = "a" * 64
H64_B = "b" * 64
H64_C = "c" * 64


def test_manifest_has_exact_12_children_and_48_unique_nf_symbols() -> None:
    assert tuple(mega.CHILDREN) == tuple(f"PR-{number}" for number in range(151, 163))
    assert set(mega.NF_SYMBOLS) == {f"NF-{number}" for number in range(353, 401)}
    assert len(set(mega.NF_SYMBOLS.values())) == 48
    for symbol in mega.NF_SYMBOLS.values():
        assert callable(getattr(mega, symbol))


def test_effect_authority_is_hard_disabled() -> None:
    assert mega.SAFETY_INVARIANTS
    assert not any(mega.SAFETY_INVARIANTS.values())


def test_head_delta_is_deterministic_and_stale_evidence_fails_closed() -> None:
    first = mega.capture_head_delta(H40_A, H40_B, ["b.py", "a.py", "a.py"], 10, 50)
    second = mega.capture_head_delta(H40_A, H40_B, ["a.py", "b.py"], 10, 50)
    assert first.content_hash == second.content_hash
    stale = mega.invalidate_stale_evidence(H40_A, H40_B, 99, 20)
    assert stale.disposition is Disposition.BLOCKED
    assert stale.reason == "STALE_EVIDENCE"


def test_program_binary_drift_revokes_capabilities() -> None:
    drift = mega.detect_deployment_drift("program", H64_A, H64_B, "loader-v1", "loader-v1")
    assert drift.disposition is Disposition.BLOCKED
    revoked = mega.revoke_capabilities_on_program_change(
        "program", True, ["quote", "build", "quote"]
    )
    assert revoked.disposition is Disposition.BLOCKED
    assert revoked.payload["revoked_capabilities"] == ("build", "quote")


def test_schema_unknown_version_and_dependency_breaking_change_fail_closed() -> None:
    replay = mega.replay_schema_conformance("schema", H64_A, H64_B)
    assert replay.reason == "UNSUPPORTED_VERSION"
    gate = mega.gate_dependency_upgrade("sdk", "BREAKING", True)
    assert gate.disposition is Disposition.BLOCKED


def test_provider_consensus_requires_quorum_and_quarantines_disagreement() -> None:
    no_quorum = mega.reconstruct_consensus_state(
        "sample", {"a": H64_A, "b": H64_B}, minimum_quorum=2
    )
    assert no_quorum.disposition is Disposition.BLOCKED
    quorum = mega.reconstruct_consensus_state(
        "sample", {"a": H64_A, "b": H64_A, "c": H64_B}, minimum_quorum=2
    )
    assert quorum.disposition is Disposition.PASS
    quarantined = mega.quarantine_byzantine_source("c", 3, 10, 2_000)
    assert quarantined.reason == "QUARANTINED_SOURCE"


def test_temporal_ambiguity_propagates_fail_closed() -> None:
    latency = mega.estimate_source_latency("rpc", 100, 90, 110)
    assert latency.reason == "TEMPORALLY_AMBIGUOUS"
    frame = mega.reject_temporally_ambiguous_frame("frame", 51, 50)
    assert frame.disposition is Disposition.BLOCKED


def test_backfill_receipt_is_idempotent_and_compaction_requires_equivalence() -> None:
    first = mega.execute_idempotent_backfill("dataset", H64_A, "r2", "transform-v1")
    second = mega.execute_idempotent_backfill("dataset", H64_A, "r2", "transform-v1")
    assert first.content_hash == second.content_hash
    bad = mega.verify_compaction_equivalence("dataset", 3, 2, H64_A, H64_A)
    assert bad.disposition is Disposition.BLOCKED


def test_duplicate_event_identity_with_different_payload_is_rejected() -> None:
    result = mega.deduplicate_raw_events(
        "dataset",
        [
            {"event_id": "e1", "value": 1},
            {"event_id": "e1", "value": 2},
        ],
    )
    assert result.reason == "IDENTITY_MISMATCH"


def test_query_contract_is_read_only_and_reproducible() -> None:
    rejected = mega.register_query_contract("q", "DELETE FROM x", "r1")
    assert rejected.reason == "MALFORMED_INPUT"
    accepted = mega.register_query_contract("q", "SELECT * FROM x", "r1")
    assert accepted.disposition is Disposition.PASS
    replay = mega.reproduce_evidence_query("q", H64_A, H64_A)
    assert replay.disposition is Disposition.PASS


def test_quota_allocator_is_bounded_and_replayable() -> None:
    result = mega.allocate_source_quota_portfolio(
        "allocation", {"slow": 1, "fast": 10, "medium": 5}, 2
    )
    assert result.payload["allocation"] == {"fast": 1, "medium": 1, "slow": 0}
    assert result.payload["unallocated_quota_units"] == 0


def test_malformed_or_poisoned_stream_data_is_quarantined() -> None:
    oversized = mega.validate_stream_payload_limits("rpc", 101, 2, 5, 100, 4, 10)
    assert oversized.reason == "MALFORMED_INPUT"
    poisoned = mega.detect_data_poisoning_pattern("rpc", 501, 0, 500, 10)
    assert poisoned.reason == "QUARANTINED_SOURCE"


def test_benchmark_manifest_requires_real_workloads_and_cross_adapter_evidence() -> None:
    empty = mega.build_workload_manifest("bench", [], H64_A)
    assert empty.disposition is Disposition.BLOCKED
    single = mega.run_cross_adapter_benchmark("bench", {"a": 1})
    assert single.disposition is Disposition.BLOCKED
    passed = mega.run_cross_adapter_benchmark("bench", {"a": 1, "b": 2})
    assert passed.disposition is Disposition.PASS


def test_no_public_megafunction_accepts_signer_or_live_authority_parameters() -> None:
    forbidden = {"signer", "private_key", "send", "live", "capital_increase"}
    for symbol in mega.NF_SYMBOLS.values():
        signature = inspect.signature(getattr(mega, symbol))
        assert forbidden.isdisjoint(signature.parameters)


def test_content_hash_is_sha256() -> None:
    result = mega.freeze_benchmark_dataset("bench", "r1", 10, H64_C)
    digest = result.content_hash
    assert len(digest) == 64
    assert hashlib.sha256(bytes.fromhex(digest)).hexdigest()
