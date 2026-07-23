from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from src.submission.mpr13_authority import (
    AbsenceProof,
    DecodedMessageIdentity,
    IntentState,
    MPR13AuthorityError,
    MPR13SignerPolicy,
    MPR13SubmissionAuthority,
    MPR13_SCHEMA_VERSION,
    ObservationFinality,
    ObservationKind,
    ProviderReceiptEnvelope,
    SignedWireIdentity,
    SignerReviewArtifact,
    StatusAuthority,
    TransportStage,
    TransportWriteEvidence,
)

PAYER = "5" * 32
PROGRAM = "4" * 32
GENESIS = "6" * 32
BLOCKHASH = "3" * 32
SIGNATURE_A = "2" * 64
SIGNATURE_B = "7" * 64
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64


class FakeDecoder:
    decoder_version = "fake-decoder.v1"

    def decode(self, message_bytes: bytes, lookup_snapshots=()):
        del lookup_snapshots
        program = PROGRAM if message_bytes == b"reviewed" else "8" * 32
        return DecodedMessageIdentity(
            schema_version=MPR13_SCHEMA_VERSION,
            decoder_version=self.decoder_version,
            message_sha256=sha256(message_bytes).hexdigest(),
            payer=PAYER,
            required_signers=(PAYER,),
            writable_accounts=(PAYER,),
            readonly_accounts=(program,),
            program_ids=(program,),
            recent_blockhash=BLOCKHASH,
            instruction_data_hashes=(HASH_A,),
            lookup_snapshot_hashes=(),
        )


def identity_for(message: bytes = b"reviewed") -> DecodedMessageIdentity:
    return FakeDecoder().decode(message)


def review_for(
    identity: DecodedMessageIdentity,
    *,
    issued_at_ns: int = 100,
    expires_at_ns: int = 1_000,
    last_valid_block_height: int = 200,
) -> SignerReviewArtifact:
    return SignerReviewArtifact.build(
        identity=identity,
        cluster_genesis_hash=GENESIS,
        policy_generation=1,
        min_context_slot=10,
        last_valid_block_height=last_valid_block_height,
        issued_at_ns=issued_at_ns,
        expires_at_ns=expires_at_ns,
    )


def authority(path: Path, *, now: int = 200) -> MPR13SubmissionAuthority:
    return MPR13SubmissionAuthority(
        path,
        signer_policy=MPR13SignerPolicy(
            allowed_program_ids=frozenset({PROGRAM}),
            allowed_payers=frozenset({PAYER}),
            allowed_required_signers=frozenset({PAYER}),
            max_permit_ttl_ns=500,
            block_height_safety_margin=2,
        ),
        cluster_genesis_hash=GENESIS,
        policy_generation=1,
        revocation_generation=1,
        decoder=FakeDecoder(),
        clock_ns=lambda: now,
    )


def issue(authority_store: MPR13SubmissionAuthority, *, transport: str = "rpc"):
    identity = identity_for()
    review = review_for(identity)
    return authority_store.issue_permit(
        attempt_id="attempt-1",
        transport=transport,
        message_bytes=b"reviewed",
        review=review,
        requested_expires_at_ns=600,
        now_ns=200,
    )


def single_wire() -> SignedWireIdentity:
    message_hash = sha256(b"reviewed").hexdigest()
    return SignedWireIdentity(
        payload_digest=HASH_B,
        message_hashes=(message_hash,),
        transaction_digests=(HASH_C,),
        signatures=(SIGNATURE_A,),
    )


def prepared_intent(store: MPR13SubmissionAuthority):
    permit = issue(store)
    return store.commit_intent(
        permit_id=permit.permit_id,
        wire=single_wire(),
        current_rooted_block_height=100,
        now_ns=250,
    )


def acknowledged_intent(store: MPR13SubmissionAuthority):
    intent = prepared_intent(store)
    store.record_dispatch(
        intent.intent_id,
        TransportWriteEvidence(
            stage=TransportStage.BODY_COMPLETE,
            request_hash=HASH_A,
            endpoint_identity_hash=HASH_D,
            observed_at_ns=260,
        ),
    )
    return store.record_ack(
        intent.intent_id,
        ProviderReceiptEnvelope(
            provider="rpc-a",
            request_hash=HASH_A,
            response_hash=HASH_B,
            signatures=(SIGNATURE_A,),
            bundle_id=None,
            received_at_ns=270,
        ),
    )


def observation(
    store: MPR13SubmissionAuthority,
    intent_id,
    status_authority: StatusAuthority,
    *,
    kind: ObservationKind,
    finality: ObservationFinality,
    slot: int | None = None,
    root_slot: int | None = None,
    provider_status: str | None = None,
):
    intent = store.get_intent(intent_id)
    return status_authority.issue(
        intent_id=intent_id,
        kind=kind,
        finality=finality,
        provider="provider-a",
        message_hash=intent.message_hash,
        signatures=intent.wire.signatures,
        bundle_id=intent.bundle_id,
        cluster_genesis_hash=GENESIS,
        request_hash=sha256(f"request:{kind.value}".encode()).hexdigest(),
        response_hash=sha256(
            f"response:{kind.value}:{finality.value}".encode()
        ).hexdigest(),
        slot=slot,
        root_slot=root_slot,
        collected_at_ns=300,
        provider_status=provider_status,
    )


def test_false_caller_metadata_cannot_override_decoded_message(tmp_path: Path) -> None:
    store = authority(tmp_path / "authority.sqlite")
    reviewed = identity_for(b"reviewed")
    review = review_for(reviewed)

    with pytest.raises(MPR13AuthorityError, match="differs from review") as exc:
        store.issue_permit(
            attempt_id="attempt-1",
            transport="rpc",
            message_bytes=b"different-bytes",
            review=review,
            requested_expires_at_ns=600,
            now_ns=200,
        )

    assert exc.value.code == "IDENTITY_MISMATCH"


def test_permit_ttl_and_rooted_blockheight_fail_closed(tmp_path: Path) -> None:
    store = authority(tmp_path / "authority.sqlite")
    review = review_for(identity_for())
    with pytest.raises(MPR13AuthorityError) as exc:
        store.issue_permit(
            attempt_id="attempt-1",
            transport="rpc",
            message_bytes=b"reviewed",
            review=review,
            requested_expires_at_ns=900,
            now_ns=200,
        )
    assert exc.value.code == "PERMIT_TTL_EXCEEDED"

    permit = issue(store)
    with pytest.raises(MPR13AuthorityError) as block_exc:
        store.commit_intent(
            permit_id=permit.permit_id,
            wire=single_wire(),
            current_rooted_block_height=199,
            now_ns=250,
        )
    assert block_exc.value.code == "BLOCKHASH_EXPIRED"


def test_consume_and_intent_are_atomic_and_survive_restart(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite"
    first = authority(database)
    permit = issue(first)
    intent = first.commit_intent(
        permit_id=permit.permit_id,
        wire=single_wire(),
        current_rooted_block_height=100,
        now_ns=250,
    )

    restarted = authority(database)
    assert restarted.get_intent(intent.intent_id).state is IntentState.PREPARED
    with pytest.raises(MPR13AuthorityError) as exc:
        restarted.commit_intent(
            permit_id=permit.permit_id,
            wire=single_wire(),
            current_rooted_block_height=100,
            now_ns=260,
        )
    assert exc.value.code == "PERMIT_NOT_ISSUED"
    assert restarted.event_chain(intent.intent_id)[0]["kind"] == "INTENT_PREPARED"


def test_bundle_intent_persists_every_signature_and_wire_digest(tmp_path: Path) -> None:
    store = authority(tmp_path / "authority.sqlite")
    permit = issue(store, transport="jito_bundle")
    message_hash = sha256(b"reviewed").hexdigest()
    wire = SignedWireIdentity(
        payload_digest=HASH_B,
        message_hashes=(message_hash, HASH_A),
        transaction_digests=(HASH_C, HASH_D),
        signatures=(SIGNATURE_A, SIGNATURE_B),
    )
    intent = store.commit_intent(
        permit_id=permit.permit_id,
        wire=wire,
        current_rooted_block_height=100,
        now_ns=250,
    )

    recovered = authority(tmp_path / "authority.sqlite").get_intent(intent.intent_id)
    assert recovered.wire.signatures == (SIGNATURE_A, SIGNATURE_B)
    assert recovered.wire.transaction_digests == (HASH_C, HASH_D)


def test_ack_requires_identity_bound_receipt(tmp_path: Path) -> None:
    store = authority(tmp_path / "authority.sqlite")
    intent = prepared_intent(store)
    store.record_dispatch(
        intent.intent_id,
        TransportWriteEvidence(
            stage=TransportStage.BODY_COMPLETE,
            request_hash=HASH_A,
            endpoint_identity_hash=HASH_D,
            observed_at_ns=260,
        ),
    )
    with pytest.raises(MPR13AuthorityError) as exc:
        store.record_ack(
            intent.intent_id,
            ProviderReceiptEnvelope(
                provider="rpc-a",
                request_hash=HASH_A,
                response_hash=HASH_B,
                signatures=(SIGNATURE_B,),
                bundle_id=None,
                received_at_ns=270,
            ),
        )
    assert exc.value.code == "ACK_IDENTITY_MISMATCH"


def test_jito_inflight_landed_is_advisory_and_confirmed_is_not_finalized(
    tmp_path: Path,
) -> None:
    store = authority(tmp_path / "authority.sqlite")
    intent = acknowledged_intent(store)
    status = StatusAuthority("status-a", b"x" * 32)

    inflight = observation(
        store,
        intent.intent_id,
        status,
        kind=ObservationKind.JITO_INFLIGHT,
        finality=ObservationFinality.ADVISORY,
        provider_status="Landed",
    )
    assert (
        store.record_observation(inflight, verifier=status).state
        is IntentState.OBSERVED
    )

    confirmed = observation(
        store,
        intent.intent_id,
        status,
        kind=ObservationKind.RPC_SIGNATURE,
        finality=ObservationFinality.CONFIRMED,
        slot=50,
        root_slot=40,
    )
    assert (
        store.record_observation(confirmed, verifier=status).state
        is IntentState.CONFIRMED
    )

    finalized = observation(
        store,
        intent.intent_id,
        status,
        kind=ObservationKind.ROOTED_TRANSACTION,
        finality=ObservationFinality.FINALIZED,
        slot=50,
        root_slot=50,
    )
    assert (
        store.record_observation(finalized, verifier=status).state
        is IntentState.FINALIZED
    )


def test_self_reported_or_tampered_observation_is_rejected(tmp_path: Path) -> None:
    store = authority(tmp_path / "authority.sqlite")
    intent = acknowledged_intent(store)
    status = StatusAuthority("status-a", b"x" * 32)
    signed = observation(
        store,
        intent.intent_id,
        status,
        kind=ObservationKind.RPC_SIGNATURE,
        finality=ObservationFinality.CONFIRMED,
        slot=50,
        root_slot=40,
    )
    tampered = replace(signed, provider_status="caller-created")

    with pytest.raises(MPR13AuthorityError) as exc:
        store.record_observation(tampered, verifier=status)
    assert exc.value.code == "OBSERVATION_UNAUTHENTICATED"


def test_transport_failure_is_ambiguous_only_after_body_complete(
    tmp_path: Path,
) -> None:
    store = authority(tmp_path / "authority.sqlite")
    intent = prepared_intent(store)
    pre_send = TransportWriteEvidence(
        stage=TransportStage.CONNECTED,
        request_hash=HASH_A,
        endpoint_identity_hash=HASH_D,
        observed_at_ns=260,
    )
    assert (
        store.classify_transport_failure(intent.intent_id, pre_send, reason="tls")
        is None
    )
    assert store.get_intent(intent.intent_id).state is IntentState.PREPARED

    body_complete = replace(pre_send, stage=TransportStage.BODY_COMPLETE)
    ambiguous = store.classify_transport_failure(
        intent.intent_id, body_complete, reason="timeout"
    )
    assert ambiguous is not None
    assert ambiguous.state is IntentState.AMBIGUOUS


def test_rebuild_requires_archive_quorum_expiry_and_freeze(tmp_path: Path) -> None:
    store = authority(tmp_path / "authority.sqlite")
    intent = prepared_intent(store)
    store.classify_transport_failure(
        intent.intent_id,
        TransportWriteEvidence(
            stage=TransportStage.BODY_COMPLETE,
            request_hash=HASH_A,
            endpoint_identity_hash=HASH_D,
            observed_at_ns=260,
        ),
        reason="timeout",
    )
    incomplete = AbsenceProof(
        intent_id=intent.intent_id,
        current_rooted_block_height=201,
        archive_complete=False,
        independent_authority_ids=("rpc-a", "rpc-b"),
        all_absent=True,
        late_landing_freeze_until_ns=300,
        collected_at_ns=320,
    )
    with pytest.raises(MPR13AuthorityError) as exc:
        store.authorize_rebuild(incomplete, now_ns=320)
    assert exc.value.code == "RESUBMISSION_FORBIDDEN"

    complete = replace(incomplete, archive_complete=True)
    lineage = store.authorize_rebuild(complete, now_ns=320)
    assert len(lineage) == 64
    assert store.event_chain(intent.intent_id)[-1]["kind"] == "REBUILD_AUTHORIZED"
