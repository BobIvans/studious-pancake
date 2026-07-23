from datetime import datetime, timezone

import pytest

from src.protocol_conformance_pr196 import (
    EvidenceStatus,
    HeliusWebhookEvent,
    JupiterBuildEvidence,
    MarginFiP0Evidence,
    ProgramAttestation,
    ProtocolConformanceError,
    ProviderRegistryEntry,
    ProviderRole,
    RootedRpcObservation,
    RootedRpcQuorum,
    VersionedEvidence,
    build_protocol_conformance_report,
    normalize_helius_events,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
NOW = datetime(2026, 7, 23, tzinfo=timezone.utc)


def evidence(evidence_id="evidence"):
    return VersionedEvidence(
        evidence_id=evidence_id,
        schema_version="v1",
        status=EvidenceStatus.ACCEPTED,
        collected_at="2026-07-22T00:00:00+00:00",
        expires_at="2026-08-22T00:00:00+00:00",
        source_hash=HASH_A,
        reviewer="reviewer-1",
    )


def program():
    return ProgramAttestation(
        program_id="MarginFiP0Program111111111111111111111111111",
        loader_program_id="BPFLoaderUpgradeab1e11111111111111111111111",
        programdata_address="ProgramData111111111111111111111111111111",
        executable=True,
        deployed_program_hash=HASH_A,
        programdata_hash=HASH_B,
        idl_hash=HASH_C,
    )


def marginfi():
    return MarginFiP0Evidence(
        evidence=evidence("marginfi"),
        sdk_package="@0dotxyz/p0-ts-sdk",
        sdk_version="1.0.0",
        sdk_deprecated=False,
        program=program(),
        golden_vector_hashes=(HASH_A, HASH_B),
        flashloan_begin_instruction_hash=HASH_C,
        flashloan_end_instruction_hash=HASH_D,
    )


def jupiter(route_plan=({"bps": 10_000, "programId": "JupiterV2"},)):
    return JupiterBuildEvidence(
        evidence=evidence("jupiter"),
        endpoint="https://api.jup.ag/swap/v2/build",
        response_hash=HASH_B,
        route_plan=tuple(route_plan),
        swap_instruction_hash=HASH_C,
        blockhash_metadata_hash=HASH_D,
    )


def quorum(state_hash=HASH_D):
    return RootedRpcQuorum(
        observations=(
            RootedRpcObservation(
                source_id="rpc-a",
                source_group="group-a",
                genesis_hash=HASH_A,
                slot=110,
                rooted_slot=105,
                min_context_slot=100,
                state_hash=state_hash,
            ),
            RootedRpcObservation(
                source_id="rpc-b",
                source_group="group-b",
                genesis_hash=HASH_A,
                slot=111,
                rooted_slot=105,
                min_context_slot=100,
                state_hash=state_hash,
            ),
        )
    )


def helius_event(signature="sig-a", slot=100, delivery="delivery-a"):
    return HeliusWebhookEvent(
        signature=signature,
        slot=slot,
        event_type="swap",
        source_delivery_id=delivery,
        payload_hash=HASH_A,
    )


def registry():
    return (
        ProviderRegistryEntry(
            provider_id="jupiter",
            role=ProviderRole.EXECUTION_COMPOSABLE,
            evidence=evidence("jupiter-provider"),
            allowed_endpoint_hosts=frozenset({"api.jup.ag"}),
        ),
        ProviderRegistryEntry(
            provider_id="okx",
            role=ProviderRole.DISCOVERY_ONLY,
            evidence=None,
            allowed_endpoint_hosts=frozenset({"web3.okx.com"}),
        ),
    )


def test_accepts_complete_sender_free_external_contract_bundle():
    report = build_protocol_conformance_report(
        marginfi=marginfi(),
        jupiter=jupiter(),
        rpc_quorum=quorum(),
        provider_registry=registry(),
        helius_events=[helius_event()],
        now=NOW,
    )

    assert report.live_execution_allowed is False
    assert report.signer_or_sender_allowed is False
    assert report.provider_roles["jupiter"] == "execution_composable"
    assert report.provider_roles["okx"] == "discovery_only"
    assert report.jupiter_route_bps == (10_000,)
    assert report.normalized_helius_events == 1
    assert report.external_contract_hash


def test_rejects_deprecated_marginfi_sdk():
    bad = MarginFiP0Evidence(
        evidence=evidence("marginfi"),
        sdk_package="@mrgnlabs/marginfi-client-v2",
        sdk_version="2.0.0",
        sdk_deprecated=True,
        program=program(),
        golden_vector_hashes=(HASH_A, HASH_B),
        flashloan_begin_instruction_hash=HASH_C,
        flashloan_end_instruction_hash=HASH_D,
    )

    with pytest.raises(ProtocolConformanceError) as exc:
        bad.validate(now=NOW)

    assert exc.value.reason_code == "PR196_MARGINFI_SDK_DEPRECATED"


def test_rejects_jupiter_legacy_percent_and_bad_bps_sum():
    with pytest.raises(ProtocolConformanceError) as exc:
        jupiter(route_plan=({"percent": 100},)).validate(now=NOW)
    assert exc.value.reason_code == "PR196_JUPITER_LEGACY_PERCENT_REJECTED"

    with pytest.raises(ProtocolConformanceError) as exc:
        jupiter(route_plan=({"bps": 9_999},)).validate(now=NOW)
    assert exc.value.reason_code == "PR196_JUPITER_BPS_SUM_NOT_10000"


def test_rejects_non_v2_jupiter_build_endpoint():
    bad = JupiterBuildEvidence(
        evidence=evidence("jupiter"),
        endpoint="https://api.jup.ag/swap/v1/swap",
        response_hash=HASH_B,
        route_plan=({"bps": 10_000},),
        swap_instruction_hash=HASH_C,
        blockhash_metadata_hash=HASH_D,
    )

    with pytest.raises(ProtocolConformanceError) as exc:
        bad.validate(now=NOW)

    assert exc.value.reason_code == "PR196_JUPITER_BUILD_V2_REQUIRED"


def test_rooted_rpc_requires_independent_quorum_and_matching_state():
    bad = RootedRpcQuorum(
        observations=(
            RootedRpcObservation(
                source_id="rpc-a",
                source_group="same-group",
                genesis_hash=HASH_A,
                slot=110,
                rooted_slot=105,
                min_context_slot=100,
                state_hash=HASH_B,
            ),
            RootedRpcObservation(
                source_id="rpc-b",
                source_group="same-group",
                genesis_hash=HASH_A,
                slot=111,
                rooted_slot=105,
                min_context_slot=100,
                state_hash=HASH_B,
            ),
        )
    )

    with pytest.raises(ProtocolConformanceError) as exc:
        bad.validate()

    assert exc.value.reason_code == "PR196_RPC_INDEPENDENT_GROUPS_REQUIRED"


def test_provider_registry_does_not_promote_discovery_provider_to_execution():
    bad_registry = (
        ProviderRegistryEntry(
            provider_id="jupiter",
            role=ProviderRole.DISCOVERY_ONLY,
            evidence=None,
        ),
    )

    with pytest.raises(ProtocolConformanceError) as exc:
        build_protocol_conformance_report(
            marginfi=marginfi(),
            jupiter=jupiter(),
            rpc_quorum=quorum(),
            provider_registry=bad_registry,
            helius_events=[helius_event()],
            now=NOW,
        )

    assert exc.value.reason_code == "PR196_JUPITER_MUST_BE_EXECUTION_PROVIDER"


def test_helius_deduplicates_and_marks_gap_backfill():
    result = normalize_helius_events(
        [
            helius_event("sig-a", 100, "delivery-a"),
            helius_event("sig-a", 100, "delivery-b"),
            helius_event("sig-c", 103, "delivery-c"),
        ]
    )

    assert result.duplicate_deliveries == 1
    assert result.normalized_events[0].slot == 100
    assert result.normalized_events[1].slot == 103
    assert result.requires_gap_backfill is True
