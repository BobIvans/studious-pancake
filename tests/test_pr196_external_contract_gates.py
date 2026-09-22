from datetime import datetime, timezone

import pytest

from src.external_contract_gates_pr196 import (
    LEGACY_SPL_TOKEN_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID,
    CycleBudgetEvidence,
    EndpointResolutionEvidence,
    ExternalContractGateBundle,
    ExternalContractGateError,
    FreshnessEvidence,
    RequestCostReservation,
    RetryOperationClass,
    RetryPolicyEvidence,
    RootedMintEvidence,
    TokenProgramPolicy,
    endpoint_pin_hash,
)

NOW = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
HASH_A = "a" * 64


def endpoint(provider_id="jupiter", host="api.jup.ag", ip="8.8.8.8"):
    return EndpointResolutionEvidence(
        provider_id=provider_id,
        url=f"https://{host}/swap/v2/build",
        resolved_ip=ip,
        allowed_hosts=frozenset({host}),
        pinned_ip_hash=endpoint_pin_hash(host, ip),
    )


def retry_policies():
    return (
        RetryPolicyEvidence(
            operation_class=RetryOperationClass.SAFE_READ,
            max_attempts=3,
            backoff_base_ms=50,
            full_jitter=True,
            idempotency_key_required=False,
        ),
        RetryPolicyEvidence(
            operation_class=RetryOperationClass.IDEMPOTENT_BUILD,
            max_attempts=2,
            backoff_base_ms=100,
            full_jitter=True,
            idempotency_key_required=True,
        ),
        RetryPolicyEvidence(
            operation_class=RetryOperationClass.NON_RETRYABLE_SEND,
            max_attempts=1,
            backoff_base_ms=0,
            full_jitter=False,
            idempotency_key_required=False,
        ),
    )


def freshness():
    return FreshnessEvidence(
        provider_id="jupiter",
        provider_observed_at="2026-07-23T11:59:58+00:00",
        trusted_received_at="2026-07-23T11:59:59+00:00",
        context_slot=100,
        rooted_slot=101,
        max_age_seconds=30,
        max_future_skew_seconds=1,
    )


def budget(reservations=None, authority="redis-provider-budget"):
    return CycleBudgetEvidence(
        provider_id="jupiter",
        cycle_id="cycle-1",
        shared_budget_authority=authority,
        monotonic_started_ns=1_000,
        monotonic_deadline_ns=2_000,
        max_request_cost_units=5,
        reservations=tuple(
            reservations
            or [
                RequestCostReservation(
                    provider_id="jupiter",
                    operation_id="quote-1",
                    operation_class=RetryOperationClass.SAFE_READ,
                    request_cost_units=1,
                ),
                RequestCostReservation(
                    provider_id="jupiter",
                    operation_id="build-1",
                    operation_class=RetryOperationClass.IDEMPOTENT_BUILD,
                    request_cost_units=2,
                ),
            ]
        ),
    )


def legacy_mint():
    return RootedMintEvidence(
        mint_address="So11111111111111111111111111111111111111112",
        owner_program_id=LEGACY_SPL_TOKEN_PROGRAM_ID,
        decimals=9,
        supply=1_000_000,
        account_hash=HASH_A,
        rooted_slot=101,
    )


def bundle(**overrides):
    values = {
        "endpoints": (endpoint(),),
        "retry_policies": retry_policies(),
        "freshness": (freshness(),),
        "budgets": (budget(),),
        "mints": (legacy_mint(),),
        "mint_policy": TokenProgramPolicy.TOKEN_2022_FAIL_CLOSED,
    }
    values.update(overrides)
    return ExternalContractGateBundle(**values)


def test_accepts_sender_free_external_contract_gate_bundle():
    report = bundle().validate(now=NOW)

    assert report.live_execution_allowed is False
    assert report.signer_or_sender_allowed is False
    assert report.endpoint_pins["jupiter"] == endpoint_pin_hash("api.jup.ag", "8.8.8.8")
    assert report.budget_cost_units["jupiter:cycle-1"] == 3
    assert report.evidence_hash


def test_rejects_private_or_rebound_endpoint_ip_before_connect():
    bad_endpoint = EndpointResolutionEvidence(
        provider_id="jupiter",
        url="https://api.jup.ag/swap/v2/build",
        resolved_ip="10.0.0.10",
        allowed_hosts=frozenset({"api.jup.ag"}),
        pinned_ip_hash="a" * 64,
    )

    with pytest.raises(ExternalContractGateError) as exc:
        bundle(endpoints=(bad_endpoint,)).validate(now=NOW)

    assert exc.value.reason_code == "PR196_RESOLVED_IP_NOT_GLOBAL"


def test_rejects_redirect_to_different_host():
    bad_endpoint = EndpointResolutionEvidence(
        provider_id="jupiter",
        url="https://api.jup.ag/swap/v2/build",
        resolved_ip="8.8.8.8",
        allowed_hosts=frozenset({"api.jup.ag"}),
        pinned_ip_hash=endpoint_pin_hash("api.jup.ag", "8.8.8.8"),
        redirect_urls=("https://metadata.google.internal/latest",),
    )

    with pytest.raises(ExternalContractGateError) as exc:
        bundle(endpoints=(bad_endpoint,)).validate(now=NOW)

    assert exc.value.reason_code == "PR196_REDIRECT_HOST_CHANGED"


def test_rejects_future_dated_provider_snapshot():
    future = FreshnessEvidence(
        provider_id="jupiter",
        provider_observed_at="2026-07-23T12:00:10+00:00",
        trusted_received_at="2026-07-23T12:00:00+00:00",
        context_slot=100,
        rooted_slot=101,
        max_age_seconds=30,
        max_future_skew_seconds=1,
    )

    with pytest.raises(ExternalContractGateError) as exc:
        bundle(freshness=(future,)).validate(now=NOW)

    assert exc.value.reason_code == "PR196_PROVIDER_TIMESTAMP_IN_FUTURE"


def test_rejects_process_local_or_exhausted_provider_budget():
    with pytest.raises(ExternalContractGateError) as exc:
        bundle(budgets=(budget(authority="process-local"),)).validate(now=NOW)
    assert exc.value.reason_code == "PR196_PROCESS_LOCAL_QUOTA_FORBIDDEN"

    exhausted = budget(
        reservations=[
            RequestCostReservation(
                provider_id="jupiter",
                operation_id="fanout-1",
                operation_class=RetryOperationClass.SAFE_READ,
                request_cost_units=6,
            )
        ]
    )
    with pytest.raises(ExternalContractGateError) as exc:
        bundle(budgets=(exhausted,)).validate(now=NOW)
    assert exc.value.reason_code == "PR196_CYCLE_BUDGET_EXHAUSTED"


def test_rejects_token_2022_owner_and_extensions_fail_closed():
    token_2022 = RootedMintEvidence(
        mint_address="MintWithToken2022Extensions111111111111111111",
        owner_program_id=TOKEN_2022_PROGRAM_ID,
        decimals=6,
        supply=10_000,
        account_hash=HASH_A,
        rooted_slot=101,
        token_extensions=("transfer_fee",),
    )

    with pytest.raises(ExternalContractGateError) as exc:
        bundle(mints=(token_2022,)).validate(now=NOW)

    assert exc.value.reason_code == "PR196_TOKEN2022_FAIL_CLOSED"


def test_rejects_retry_without_jitter_and_send_retry():
    no_jitter = RetryPolicyEvidence(
        operation_class=RetryOperationClass.SAFE_READ,
        max_attempts=2,
        backoff_base_ms=50,
        full_jitter=False,
        idempotency_key_required=False,
    )
    with pytest.raises(ExternalContractGateError) as exc:
        bundle(retry_policies=(no_jitter, *retry_policies()[1:])).validate(now=NOW)
    assert exc.value.reason_code == "PR196_RETRY_FULL_JITTER_REQUIRED"

    send_retry = RetryPolicyEvidence(
        operation_class=RetryOperationClass.NON_RETRYABLE_SEND,
        max_attempts=2,
        backoff_base_ms=0,
        full_jitter=False,
        idempotency_key_required=False,
    )
    with pytest.raises(ExternalContractGateError) as exc:
        bundle(retry_policies=(*retry_policies()[:2], send_retry)).validate(now=NOW)
    assert exc.value.reason_code == "PR196_SEND_RETRY_FORBIDDEN"
