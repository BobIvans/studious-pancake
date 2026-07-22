from __future__ import annotations

import pytest

from src.signer_authorization_pr141 import (
    AuthorizationFailure,
    DecodedUnsignedMessage,
    SOLANA_FULL_TRANSACTION_LIMIT_BYTES,
    SignerAuthorizationError,
    SignerAuthorizationRequest,
    authorize_transaction,
    sha256_json,
)

SYSTEM_PROGRAM = "11111111111111111111111111111111"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
PAYER = "Payer11111111111111111111111111111111111111"
SIGNER = "Signer1111111111111111111111111111111111111"


def _hash(name: str) -> str:
    return sha256_json({"fixture": name})


def _decoded(
    *,
    version: str = "v0",
    payer: str = PAYER,
    signers: tuple[str, ...] = (PAYER,),
    programs: tuple[str, ...] = (SYSTEM_PROGRAM,),
    message_bytes: int = 120,
    signature_count: int | None = None,
    alt_count: int = 0,
) -> DecodedUnsignedMessage:
    return DecodedUnsignedMessage(
        message_sha256=_hash("message"),
        version=version,
        payer=payer,
        required_signers=signers,
        program_ids=programs,
        message_byte_count=message_bytes,
        required_signature_count=(len(signers) if signature_count is None else signature_count),
        address_lookup_table_count=alt_count,
    )


def _request(**overrides: object) -> SignerAuthorizationRequest:
    values: dict[str, object] = {
        "authorization_id": "auth-1",
        "attempt_id": "attempt-1",
        "attempt_generation": 1,
        "logical_opportunity_id": "opp-1",
        "decoded_message": _decoded(),
        "expected_payer": PAYER,
        "expected_required_signers": (PAYER,),
        "allowed_program_ids": frozenset({SYSTEM_PROGRAM, TOKEN_PROGRAM}),
        "plan_hash": _hash("plan"),
        "policy_bundle_hash": _hash("policy"),
        "exact_simulation_hash": _hash("simulation"),
        "cpi_call_graph_hash": _hash("cpi"),
        "fee_compute_budget_hash": _hash("fee"),
        "blockhash_alt_fork_hash": _hash("blockhash-alt"),
        "nonce_digest": _hash("nonce"),
        "issued_at_ns": 100,
        "expires_at_ns": 200,
        "alt_evidence_hash": None,
    }
    values.update(overrides)
    return SignerAuthorizationRequest(**values)  # type: ignore[arg-type]


def test_pr141_authorizes_exact_v0_message_with_all_required_bindings() -> None:
    request = _request(
        decoded_message=_decoded(signers=(PAYER, SIGNER), programs=(TOKEN_PROGRAM,)),
        expected_required_signers=(PAYER, SIGNER),
    )

    authorization = authorize_transaction(request)

    assert authorization.signer_may_sign is True
    assert authorization.live_submission_allowed is False
    assert authorization.message_sha256 == request.decoded_message.message_sha256
    assert authorization.payer == PAYER
    assert authorization.required_signers == (PAYER, SIGNER)
    assert authorization.program_ids == (TOKEN_PROGRAM,)
    assert authorization.estimated_signed_wire_bytes <= SOLANA_FULL_TRANSACTION_LIMIT_BYTES
    assert len(authorization.envelope_hash) == 64


def test_pr141_decoded_programs_cannot_be_hidden_by_request_allowlist() -> None:
    request = _request(
        decoded_message=_decoded(programs=("Malicious111111111111111111111111111111111",)),
        allowed_program_ids=frozenset({SYSTEM_PROGRAM}),
    )

    with pytest.raises(SignerAuthorizationError) as exc_info:
        authorize_transaction(request)

    assert exc_info.value.failure is AuthorizationFailure.BAD_PROGRAM


def test_pr141_rejects_payer_mismatch_from_decoded_message() -> None:
    request = _request(expected_payer="OtherPayer111111111111111111111111111111111")

    with pytest.raises(SignerAuthorizationError) as exc_info:
        authorize_transaction(request)

    assert exc_info.value.failure is AuthorizationFailure.BAD_PAYER


def test_pr141_rejects_required_signer_set_mismatch() -> None:
    request = _request(expected_required_signers=(SIGNER,))

    with pytest.raises(SignerAuthorizationError) as exc_info:
        authorize_transaction(request)

    assert exc_info.value.failure is AuthorizationFailure.BAD_SIGNER_SET


def test_pr141_rejects_full_wire_size_not_only_message_size() -> None:
    request = _request(decoded_message=_decoded(message_bytes=1168, signature_count=1))

    with pytest.raises(SignerAuthorizationError) as exc_info:
        authorize_transaction(request)

    assert exc_info.value.failure is AuthorizationFailure.BAD_WIRE_SIZE


def test_pr141_rejects_legacy_or_unknown_message_version() -> None:
    request = _request(decoded_message=_decoded(version="legacy"))

    with pytest.raises(SignerAuthorizationError) as exc_info:
        authorize_transaction(request)

    assert exc_info.value.failure is AuthorizationFailure.BAD_VERSION


def test_pr141_rejects_missing_hash_binding() -> None:
    request = _request(exact_simulation_hash="not-a-sha256")

    with pytest.raises(SignerAuthorizationError) as exc_info:
        authorize_transaction(request)

    assert exc_info.value.failure is AuthorizationFailure.BAD_HASH


def test_pr141_alt_usage_requires_bound_resolved_account_evidence() -> None:
    request = _request(decoded_message=_decoded(alt_count=1))

    with pytest.raises(SignerAuthorizationError) as exc_info:
        authorize_transaction(request)

    assert exc_info.value.failure is AuthorizationFailure.BAD_ALT_EVIDENCE

    authorized = authorize_transaction(
        _request(decoded_message=_decoded(alt_count=1), alt_evidence_hash=_hash("alt"))
    )
    assert authorized.signer_may_sign is True


def test_pr141_rejects_bad_expiry_and_nonce() -> None:
    with pytest.raises(SignerAuthorizationError) as expiry_error:
        authorize_transaction(_request(expires_at_ns=100))
    assert expiry_error.value.failure is AuthorizationFailure.BAD_EXPIRY

    with pytest.raises(SignerAuthorizationError) as nonce_error:
        authorize_transaction(_request(nonce_digest="bad-nonce"))
    assert nonce_error.value.failure is AuthorizationFailure.BAD_NONCE
