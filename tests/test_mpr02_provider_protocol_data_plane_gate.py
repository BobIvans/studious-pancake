from __future__ import annotations

from dataclasses import replace

from src.mpr02_provider_protocol_data_plane_gate import (
    DISCOVERY_PROVIDERS,
    DiscoveryOnlyBoundaries,
    EvidenceRef,
    HeliusIngressEvidence,
    JupiterV2BuildEvidence,
    KaminoKLendAdmissionEvidence,
    MPR02Evidence,
    MPR02State,
    MarginFiV2ConformanceEvidence,
    ProviderDriftProbeEvidence,
    REQUIRED_DEBT_IDS,
    SolanaV0RPCFinalityEvidence,
    evaluate_mpr02_evidence,
    report_to_dict,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64
SHA_1 = "1" * 64


def evidence_ref(label: str, digest: str = SHA_A) -> EvidenceRef:
    return EvidenceRef(label, digest, f"src/resources/contracts/{label}.json")


def valid_evidence() -> MPR02Evidence:
    return MPR02Evidence(
        schema_version="mpr-02.provider-protocol-rooted-data-plane.v1",
        covered_debt_ids=REQUIRED_DEBT_IDS,
        solana_rpc=SolanaV0RPCFinalityEvidence(
            True, True, True, True, True, True, True, True, True, True, True, True
        ),
        jupiter=JupiterV2BuildEvidence(True, True, True, True, True, True, True, True, True),
        marginfi=MarginFiV2ConformanceEvidence(
            "fixture_only_blocked", False, False, False, False, False, False, False, False
        ),
        kamino=KaminoKLendAdmissionEvidence(
            "disabled_fail_closed", False, False, True, True
        ),
        helius=HeliusIngressEvidence(True, True, True, True, True, True, True),
        discovery_boundaries=DiscoveryOnlyBoundaries(
            True, True, True, True, True, ("jupiter_v2_build",)
        ),
        drift_probes=ProviderDriftProbeEvidence(True, True, True, SHA_B, True, True),
        evidence_refs=(
            evidence_ref("solana-v0-rpc", SHA_A),
            evidence_ref("jupiter-v2-build", SHA_B),
            evidence_ref("helius-ingress", SHA_C),
            evidence_ref("marginfi-v2-blocked", SHA_D),
            evidence_ref("kamino-klend-disabled", SHA_E),
            evidence_ref("discovery-boundaries", SHA_F),
            evidence_ref("provider-drift", SHA_1),
        ),
    )


def codes(report):
    return {blocker.code for blocker in report.blockers}


def test_valid_fixture_only_path_allows_review_but_not_paper_or_live() -> None:
    report = evaluate_mpr02_evidence(valid_evidence())

    assert report.state is MPR02State.READY_FOR_PROVIDER_PROTOCOL_REVIEW
    assert report.provider_protocol_review_allowed is True
    assert report.operational_paper_ready_allowed is False
    assert report.live_execution_allowed is False
    assert report.sender_allowed is False
    assert report.blockers == ()


def test_report_serialization_is_stable() -> None:
    first = report_to_dict(evaluate_mpr02_evidence(valid_evidence()))
    second = report_to_dict(evaluate_mpr02_evidence(valid_evidence()))

    assert first == second
    assert first["state"] == "ready_for_provider_protocol_review"
    assert len(first["evidence_hash"]) == 64


def test_missing_debt_coverage_blocks_review() -> None:
    report = evaluate_mpr02_evidence(
        replace(valid_evidence(), covered_debt_ids=REQUIRED_DEBT_IDS[:-1])
    )

    assert "MPR02_MISSING_DEBT_COVERAGE" in codes(report)
    assert report.provider_protocol_review_allowed is False


def test_bad_evidence_refs_block_review() -> None:
    evidence = replace(
        valid_evidence(),
        evidence_refs=(
            EvidenceRef("solana-v0-rpc", "0" * 64, "src/resources/contracts/solana.json"),
            EvidenceRef("provider-drift", SHA_A, "/tmp/provider.json"),
            EvidenceRef("jupiter-secret-token", SHA_B, "src/resources/contracts/jupiter.json"),
            EvidenceRef("helius", SHA_C, "src/resources/contracts/helius.json", redacted=False),
            evidence_ref("marginfi", SHA_D),
            evidence_ref("kamino", SHA_E),
            evidence_ref("odos", SHA_F),
        ),
    )

    assert {
        "MPR02_BAD_EVIDENCE_DIGEST",
        "MPR02_BAD_EVIDENCE_PATH",
        "MPR02_SECRET_LIKE_EVIDENCE_REF",
        "MPR02_UNREDACTED_EVIDENCE",
    }.issubset(codes(evaluate_mpr02_evidence(evidence)))


def test_solana_rooted_quorum_and_finalized_evidence_are_required() -> None:
    solana = replace(
        valid_evidence().solana_rpc,
        rooted_quorum_proven=False,
        oracle_slot_coherence_proven=False,
        finalized_commitment_only_for_settlement=False,
    )
    report = evaluate_mpr02_evidence(replace(valid_evidence(), solana_rpc=solana))

    assert {
        "MPR02_SOLANA_ROOTED_QUORUM_PROVEN_MISSING",
        "MPR02_SOLANA_ORACLE_SLOT_COHERENCE_PROVEN_MISSING",
        "MPR02_SOLANA_FINALIZED_COMMITMENT_ONLY_FOR_SETTLEMENT_MISSING",
    }.issubset(codes(report))


def test_jupiter_v2_build_must_be_only_execution_path() -> None:
    jupiter = replace(
        valid_evidence().jupiter,
        v2_build_only_execution_composable_path=False,
        v1_execution_claims_disabled=False,
        canonical_transaction_proof_compatible=False,
    )
    report = evaluate_mpr02_evidence(replace(valid_evidence(), jupiter=jupiter))

    assert {
        "MPR02_JUPITER_V2_BUILD_ONLY_EXECUTION_COMPOSABLE_PATH_MISSING",
        "MPR02_JUPITER_V1_EXECUTION_CLAIMS_DISABLED_MISSING",
        "MPR02_JUPITER_CANONICAL_TRANSACTION_PROOF_COMPATIBLE_MISSING",
    }.issubset(codes(report))


def test_marginfi_and_kamino_fixture_or_disabled_states_cannot_be_promoted() -> None:
    evidence = replace(
        valid_evidence(),
        marginfi=replace(valid_evidence().marginfi, product_capability_promoted=True),
        kamino=replace(
            valid_evidence().kamino,
            product_capability_promoted=True,
            no_guessed_market_or_reserve_ids=False,
        ),
    )
    report = evaluate_mpr02_evidence(evidence)

    assert {
        "MPR02_MARGINFI_FIXTURE_PROMOTED",
        "MPR02_KAMINO_DISABLED_PROMOTED",
        "MPR02_KAMINO_GUESSED_IDS",
    }.issubset(codes(report))


def test_conformance_ready_marginfi_and_kamino_require_full_proof() -> None:
    evidence = replace(
        valid_evidence(),
        marginfi=replace(valid_evidence().marginfi, status="conformance_ready"),
        kamino=replace(valid_evidence().kamino, status="conformance_ready"),
    )
    report = evaluate_mpr02_evidence(evidence)

    assert {
        "MPR02_MARGINFI_INCOMPLETE_CONFORMANCE",
        "MPR02_KAMINO_UNPROVEN_COMBINATIONS",
    }.issubset(codes(report))


def test_helius_ingress_requires_auth_replay_gap_and_handoff() -> None:
    helius = replace(
        valid_evidence().helius,
        auth_header_validation=False,
        replay_dedup=False,
        gap_recovery=False,
        durable_handoff=False,
    )
    report = evaluate_mpr02_evidence(replace(valid_evidence(), helius=helius))

    assert {
        "MPR02_HELIUS_AUTH_HEADER_VALIDATION_MISSING",
        "MPR02_HELIUS_REPLAY_DEDUP_MISSING",
        "MPR02_HELIUS_GAP_RECOVERY_MISSING",
        "MPR02_HELIUS_DURABLE_HANDOFF_MISSING",
    }.issubset(codes(report))


def test_discovery_providers_cannot_be_execution_composable() -> None:
    discovery = replace(
        valid_evidence().discovery_boundaries,
        odos_immutable_transaction_marked_incompatible=False,
        execution_provider_allowlist=("jupiter_v2_build", *sorted(DISCOVERY_PROVIDERS)),
    )
    report = evaluate_mpr02_evidence(
        replace(valid_evidence(), discovery_boundaries=discovery)
    )

    assert {
        "MPR02_DISCOVERY_ODOS_IMMUTABLE_TRANSACTION_MARKED_INCOMPATIBLE_MISSING",
        "MPR02_DISCOVERY_EXECUTION_ALLOWLISTED",
    }.issubset(codes(report))


def test_drift_and_live_sender_secrets_are_fail_closed() -> None:
    evidence = replace(
        valid_evidence(),
        drift_probes=replace(
            valid_evidence().drift_probes,
            committed_fixture_validation_in_ci=False,
            refresh_never_commits_secrets=False,
            redaction_policy_hash="not-a-sha",
        ),
        operational_paper_ready_requested=True,
        live_execution_requested=True,
        sender_requested=True,
        secrets_committed=True,
    )
    report = evaluate_mpr02_evidence(evidence)

    assert {
        "MPR02_DRIFT_COMMITTED_FIXTURE_VALIDATION_IN_CI_MISSING",
        "MPR02_DRIFT_REFRESH_NEVER_COMMITS_SECRETS_MISSING",
        "MPR02_DRIFT_REDACTION_POLICY_HASH_BAD",
        "MPR02_PAPER_READY_PROMOTION_FORBIDDEN",
        "MPR02_LIVE_EXECUTION_FORBIDDEN",
        "MPR02_SENDER_FORBIDDEN",
        "MPR02_SECRETS_COMMITTED",
    }.issubset(codes(report))
