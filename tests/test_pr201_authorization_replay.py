from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import threading

import pytest

from src.authorization_replay_pr201 import (
    AuthorizationChallenge,
    AuthorizationDomain,
    AuthorizationReplayService,
    AuthorizationResult,
    ChallengeState,
    ReplayFailure,
    ReplayProtectionError,
    SQLiteAuthorizationReplayLedger,
    authorize_pr141_once,
)
from src.signer_authorization_pr141 import (
    AuthorizationFailure,
    DecodedUnsignedMessage,
    SignerAuthorizationError,
    SignerAuthorizationRequest,
    authorize_transaction,
    sha256_json,
)

SYSTEM_PROGRAM = "11111111111111111111111111111111"
PAYER = "Payer11111111111111111111111111111111111111"
KEY = b"k" * 32


class Clock:
    def __init__(self, value: int = 1_000_000_000) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


def _hash(name: str) -> str:
    return sha256_json({"fixture": name})


def _service(tmp_path: Path, clock: Clock | None = None) -> AuthorizationReplayService:
    return AuthorizationReplayService(
        SQLiteAuthorizationReplayLedger(tmp_path / "authorization.sqlite"),
        issuer_id="issuer.prod.signer",
        issuer_key_id="issuer-key-v1",
        mac_key=KEY,
        environment="production",
        cluster="solana-mainnet-beta",
        clock_ns=clock or Clock(),
    )


def _issue(
    service: AuthorizationReplayService,
    *,
    domain: AuthorizationDomain = AuthorizationDomain.SIGNER_TRANSACTION,
    operation_hash: str | None = None,
) -> AuthorizationChallenge:
    return service.issue(
        domain=domain,
        purpose="sign-exact-v0-message",
        release_id="release-201",
        policy_bundle_hash=_hash("policy"),
        attempt_id="attempt-201",
        attempt_generation=3,
        operation_hash=operation_hash or _hash("message"),
        ttl_ns=60_000_000_000,
    )


def _request(challenge: AuthorizationChallenge) -> SignerAuthorizationRequest:
    return SignerAuthorizationRequest(
        authorization_id=challenge.challenge_id,
        attempt_id=challenge.attempt_id,
        attempt_generation=challenge.attempt_generation,
        logical_opportunity_id="opportunity-201",
        decoded_message=DecodedUnsignedMessage(
            message_sha256=challenge.operation_hash,
            version="v0",
            payer=PAYER,
            required_signers=(PAYER,),
            program_ids=(SYSTEM_PROGRAM,),
            message_byte_count=120,
            required_signature_count=1,
        ),
        expected_payer=PAYER,
        expected_required_signers=(PAYER,),
        allowed_program_ids=frozenset({SYSTEM_PROGRAM}),
        plan_hash=_hash("plan"),
        policy_bundle_hash=challenge.policy_bundle_hash,
        exact_simulation_hash=_hash("simulation"),
        cpi_call_graph_hash=_hash("cpi"),
        fee_compute_budget_hash=_hash("fee"),
        blockhash_alt_fork_hash=_hash("fork"),
        nonce_digest=challenge.nonce_digest,
        issued_at_ns=challenge.issued_at_ns,
        expires_at_ns=challenge.expires_at_ns,
    )


def test_pr201_legacy_all_zero_nonce_is_rejected() -> None:
    challenge = AuthorizationChallenge(
        schema_version="pr201.authorization-replay.v1",
        challenge_id="authz_placeholder",
        issuer_id="issuer.prod.signer",
        issuer_key_id="issuer-key-v1",
        domain=AuthorizationDomain.SIGNER_TRANSACTION,
        purpose="sign-exact-v0-message",
        release_id="release-201",
        policy_bundle_hash=_hash("policy"),
        attempt_id="attempt-201",
        attempt_generation=3,
        operation_hash=_hash("message"),
        environment="production",
        cluster="solana-mainnet-beta",
        nonce_b64="A" * 43,
        nonce_digest="0" * 64,
        issued_at_ns=1,
        expires_at_ns=2,
        authority_tag="0" * 64,
    )
    request = _request(challenge)

    with pytest.raises(SignerAuthorizationError) as exc_info:
        authorize_transaction(request)

    assert exc_info.value.failure is AuthorizationFailure.BAD_NONCE


def test_pr201_trusted_issuer_creates_unique_durable_challenges(tmp_path: Path) -> None:
    service = _service(tmp_path)

    first = _issue(service)
    second = _issue(service)

    assert first.nonce_digest != second.nonce_digest
    assert first.authority_tag != second.authority_tag
    first_record = service.ledger.get(first.challenge_id)
    second_record = service.ledger.get(second.challenge_id)
    assert first_record is not None
    assert second_record is not None
    assert first_record.state is ChallengeState.ISSUED
    assert second_record.state is ChallengeState.ISSUED


def test_pr201_rejects_placeholder_nonce_factory(tmp_path: Path) -> None:
    service = AuthorizationReplayService(
        SQLiteAuthorizationReplayLedger(tmp_path / "authorization.sqlite"),
        issuer_id="issuer.prod.signer",
        issuer_key_id="issuer-key-v1",
        mac_key=KEY,
        environment="production",
        cluster="solana-mainnet-beta",
        nonce_factory=lambda size: b"\x00" * size,
    )

    with pytest.raises(ReplayProtectionError) as exc_info:
        _issue(service)

    assert exc_info.value.failure is ReplayFailure.BAD_NONCE


def test_pr201_tampered_domain_fails_authority_tag(tmp_path: Path) -> None:
    service = _service(tmp_path)
    challenge = _issue(service)
    tampered = replace(challenge, domain=AuthorizationDomain.TREASURY_TRANSFER)

    with pytest.raises(ReplayProtectionError) as exc_info:
        service.verify(tampered)

    assert exc_info.value.failure is ReplayFailure.BAD_AUTHORITY


def test_pr201_same_nonce_cannot_be_inserted_under_another_domain(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    challenge = _issue(service)
    replay = replace(
        challenge,
        challenge_id="authz_other",
        domain=AuthorizationDomain.OPERATOR_APPROVAL,
    )

    with pytest.raises(ReplayProtectionError) as exc_info:
        service.ledger.record_issued(replay, now_ns=replay.issued_at_ns)

    assert exc_info.value.failure is ReplayFailure.NONCE_REUSED


def test_pr201_pr141_authorization_is_single_use_and_retry_is_idempotent(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    challenge = _issue(service)
    request = _request(challenge)

    first = authorize_pr141_once(service, challenge, request)
    second = authorize_pr141_once(service, challenge, request)
    record = service.ledger.get(challenge.challenge_id)

    assert first.envelope_hash == second.envelope_hash
    assert record is not None
    assert record.state is ChallengeState.CONSUMED
    assert record.result is not None


def test_pr201_same_nonce_cannot_authorize_second_envelope(tmp_path: Path) -> None:
    service = _service(tmp_path)
    challenge = _issue(service)
    request = _request(challenge)
    authorize_pr141_once(service, challenge, request)

    changed = replace(request, logical_opportunity_id="opportunity-other")
    with pytest.raises(ReplayProtectionError) as exc_info:
        authorize_pr141_once(service, challenge, changed)

    assert exc_info.value.failure is ReplayFailure.REPLAYED


def test_pr201_expired_and_revoked_challenges_fail_closed(tmp_path: Path) -> None:
    clock = Clock()
    service = _service(tmp_path, clock)
    expired = _issue(service)
    clock.value = expired.expires_at_ns

    with pytest.raises(ReplayProtectionError) as expiry_error:
        authorize_pr141_once(service, expired, _request(expired))
    assert expiry_error.value.failure is ReplayFailure.EXPIRED

    clock.value = 2_000_000_000
    revoked = _issue(service)
    service.ledger.revoke(
        revoked.challenge_id,
        now_ns=clock.value,
        reason="issuer-key-revoked",
    )
    with pytest.raises(ReplayProtectionError) as revoked_error:
        authorize_pr141_once(service, revoked, _request(revoked))
    assert revoked_error.value.failure is ReplayFailure.REVOKED


def test_pr201_backend_failure_leaves_reserved_unknown_and_never_blindly_retries(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    challenge = _issue(service, domain=AuthorizationDomain.OPERATOR_APPROVAL)
    request_hash = _hash("operator-request")
    calls = 0

    def failing(_: str) -> AuthorizationResult:
        nonlocal calls
        calls += 1
        raise RuntimeError("backend failed after an unknown side effect")

    with pytest.raises(ReplayProtectionError) as first_error:
        service.execute_once(
            challenge,
            request_hash=request_hash,
            executor=failing,
        )
    assert first_error.value.failure is ReplayFailure.EXECUTION_UNKNOWN

    with pytest.raises(ReplayProtectionError) as retry_error:
        service.execute_once(
            challenge,
            request_hash=request_hash,
            executor=failing,
        )
    assert retry_error.value.failure is ReplayFailure.IN_PROGRESS
    assert calls == 1
    record = service.ledger.get(challenge.challenge_id)
    assert record is not None
    assert record.state is ChallengeState.RESERVED


def test_pr201_reserved_operation_can_recover_backend_result_after_restart(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    challenge = _issue(service, domain=AuthorizationDomain.RELEASE_ACTIVATION)
    request_hash = _hash("release-request")

    def unknown(_: str) -> AuthorizationResult:
        raise OSError("connection lost")

    with pytest.raises(ReplayProtectionError):
        service.execute_once(challenge, request_hash=request_hash, executor=unknown)

    restarted = _service(tmp_path)
    recovered = AuthorizationResult.from_payload(
        "release.activation.v1",
        {"release_id": challenge.release_id, "activated": False},
    )
    execution = restarted.recover_result(
        challenge,
        request_hash=request_hash,
        result=recovered,
    )

    assert execution.replayed is False
    record = restarted.ledger.get(challenge.challenge_id)
    assert record is not None
    assert record.state is ChallengeState.CONSUMED


def test_pr201_concurrent_calls_execute_backend_once(tmp_path: Path) -> None:
    service = _service(tmp_path)
    challenge = _issue(service, domain=AuthorizationDomain.SUBMISSION_PERMIT)
    request_hash = _hash("permit-request")
    entered = threading.Event()
    release = threading.Event()
    calls = 0
    errors: list[ReplayFailure] = []

    def executor(_: str) -> AuthorizationResult:
        nonlocal calls
        calls += 1
        entered.set()
        release.wait(timeout=2)
        return AuthorizationResult.from_payload(
            "submission.permit.v1",
            {"permit": "review-only", "submission_allowed": False},
        )

    def run() -> None:
        try:
            service.execute_once(
                challenge,
                request_hash=request_hash,
                executor=executor,
            )
        except ReplayProtectionError as exc:
            errors.append(exc.failure)

    first = threading.Thread(target=run)
    second = threading.Thread(target=run)
    first.start()
    assert entered.wait(timeout=2)
    second.start()
    second.join(timeout=2)
    release.set()
    first.join(timeout=2)

    assert calls == 1
    assert errors == [ReplayFailure.IN_PROGRESS]
    record = service.ledger.get(challenge.challenge_id)
    assert record is not None
    assert record.state is ChallengeState.CONSUMED


def test_pr201_pr141_wrapper_rejects_cross_domain_and_binding_changes(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    wrong_domain = _issue(service, domain=AuthorizationDomain.OPERATOR_APPROVAL)

    with pytest.raises(ReplayProtectionError) as domain_error:
        authorize_pr141_once(service, wrong_domain, _request(wrong_domain))
    assert domain_error.value.failure is ReplayFailure.BAD_BINDING

    challenge = _issue(service)
    wrong_policy = replace(
        _request(challenge), policy_bundle_hash=_hash("other-policy")
    )
    with pytest.raises(ReplayProtectionError) as binding_error:
        authorize_pr141_once(service, challenge, wrong_policy)
    assert binding_error.value.failure is ReplayFailure.BAD_BINDING
