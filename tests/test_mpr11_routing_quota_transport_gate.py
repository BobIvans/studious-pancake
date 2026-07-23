from __future__ import annotations

import math

import pytest

from src.mpr11_routing_quota_transport_gate import (
    MPR11_FINDINGS,
    MPR11_SCHEMA_VERSION,
    IdempotentQuotaReservation,
    canonical_cache_key,
    evaluate_mpr11_routing_quota_gate,
    validate_attempt_timing,
)

pytestmark = pytest.mark.unit


def _good_evidence() -> dict[str, object]:
    return {
        "schema_version": MPR11_SCHEMA_VERSION,
        "covered_findings": list(MPR11_FINDINGS),
        "cache_identity": {
            "canonical_typed_hash": True,
            "collision_vectors_rejected": True,
            "descriptor_hash_verified_on_read": True,
            "generation_aware": True,
            "max_entries": 1_000,
            "max_bytes": 2_000_000,
        },
        "quota": {
            "idempotent_mark_used": True,
            "concurrent_mark_used_single_winner": True,
            "account_wide_authority": True,
            "reservation_identity_persisted": True,
        },
        "scheduler": {
            "finite_time_validation": True,
            "causal_quote_time_validation": True,
            "atomic_plan_reservations": True,
            "profile_failure_resurrection_blocked": True,
            "remaining_quota_slots": 1,
            "planned_attempts": 1,
        },
        "public_keys": {
            "canonical_solana_decode": True,
            "round_trip_normalization": True,
            "regex_only_vectors_rejected": True,
        },
        "quote_freshness": {
            "trusted_current_time_or_slot": True,
            "no_expiry_execution_rejected": True,
            "stale_replay_rejected": True,
            "blockhash_or_provider_validity_bound": True,
        },
        "transport": {
            "actual_client_policy_attested": True,
            "injected_insecure_client_rejected": True,
            "tls_verify_bound_to_evidence": True,
            "proxy_redirect_policy_bound": True,
        },
        "adapters": {
            "jupiter_slippage_not_widened": True,
            "jupiter_swap_mode_echo_verified": True,
            "openocean_mint_echo_verified": True,
            "odos_token_amount_echo_verified": True,
            "okx_request_response_bound": True,
            "cross_request_substitution_rejected": True,
        },
        "route_identity": {
            "program_pool_account_identity": True,
            "blockhash_validity_bound": True,
            "schema_generation_bound": True,
            "expired_blockhash_rejected": True,
        },
        "live_execution_enabled": False,
        "provider_network_enabled": False,
        "signer_enabled": False,
    }


def test_mpr11_accepts_complete_sender_free_evidence() -> None:
    report = evaluate_mpr11_routing_quota_gate(_good_evidence())

    assert report.accepted is True
    assert report.blockers == ()
    assert report.covered_findings == MPR11_FINDINGS
    assert report.live_execution_allowed is False
    assert report.provider_network_allowed is False
    assert report.signer_allowed is False
    assert len(report.evidence_hash) == 64


def test_mpr11_fails_closed_without_complete_finding_coverage() -> None:
    evidence = _good_evidence()
    evidence["covered_findings"] = ["F-304"]

    report = evaluate_mpr11_routing_quota_gate(evidence)

    assert report.accepted is False
    assert "FINDING_COVERAGE_INCOMPLETE" in report.blockers


def test_cache_identity_is_not_delimiter_joined() -> None:
    left = canonical_cache_key("a|b", "c")
    right = canonical_cache_key("a", "b|c")

    assert left != right
    assert len(left) == 64
    assert len(right) == 64


def test_gate_rejects_cache_without_descriptor_and_bounds() -> None:
    evidence = _good_evidence()
    evidence["cache_identity"] = {
        "canonical_typed_hash": False,
        "collision_vectors_rejected": False,
        "descriptor_hash_verified_on_read": False,
        "generation_aware": False,
        "max_entries": 0,
        "max_bytes": 0,
    }

    report = evaluate_mpr11_routing_quota_gate(evidence)

    assert "CACHE_KEY_NOT_CANONICAL" in report.blockers
    assert "CACHE_COLLISION_PROBE_NOT_REJECTED" in report.blockers
    assert "CACHE_DESCRIPTOR_NOT_VERIFIED" in report.blockers
    assert "CACHE_ENTRY_BOUND_MISSING" in report.blockers


def test_quota_mark_used_is_idempotent() -> None:
    reservation = IdempotentQuotaReservation("token-1")

    assert reservation.mark_used() is True
    assert reservation.mark_used() is False
    assert reservation.issued is True


def test_gate_rejects_non_idempotent_quota_evidence() -> None:
    evidence = _good_evidence()
    evidence["quota"] = {
        "idempotent_mark_used": False,
        "concurrent_mark_used_single_winner": False,
        "account_wide_authority": False,
        "reservation_identity_persisted": False,
    }

    report = evaluate_mpr11_routing_quota_gate(evidence)

    assert "QUOTA_MARK_USED_NOT_IDEMPOTENT" in report.blockers
    assert "QUOTA_CONCURRENT_MARK_USED_UNSAFE" in report.blockers
    assert "QUOTA_ACCOUNT_AUTHORITY_MISSING" in report.blockers


@pytest.mark.parametrize(
    ("now", "created", "deadline", "reason"),
    [
        (math.nan, 10.0, 20.0, "TIME_VALUE_NOT_FINITE"),
        (10.0, math.inf, 20.0, "TIME_VALUE_NOT_FINITE"),
        (10.0, 12.0, 20.0, "QUOTE_CREATED_IN_FUTURE"),
        (30.0, 10.0, 20.0, "DEADLINE_EXPIRED"),
        (100.0, 10.0, 200.0, "QUOTE_STALE"),
    ],
)
def test_attempt_timing_rejects_non_finite_and_non_causal_inputs(
    now: float,
    created: float,
    deadline: float,
    reason: str,
) -> None:
    ok, actual = validate_attempt_timing(
        now_unix_s=now,
        quote_created_at_unix_s=created,
        deadline_unix_s=deadline,
        max_quote_age_s=30.0,
    )

    assert ok is False
    assert actual == reason


def test_attempt_timing_accepts_finite_causal_fresh_quote() -> None:
    ok, reason = validate_attempt_timing(
        now_unix_s=15.0,
        quote_created_at_unix_s=10.0,
        deadline_unix_s=20.0,
        max_quote_age_s=30.0,
    )

    assert ok is True
    assert reason == "READY"


def test_gate_rejects_scheduler_overplanning_and_profile_resurrection() -> None:
    evidence = _good_evidence()
    evidence["scheduler"] = {
        "finite_time_validation": True,
        "causal_quote_time_validation": True,
        "atomic_plan_reservations": False,
        "profile_failure_resurrection_blocked": False,
        "remaining_quota_slots": 1,
        "planned_attempts": 4,
    }

    report = evaluate_mpr11_routing_quota_gate(evidence)

    assert "SCHEDULER_PLAN_RESERVATION_MISSING" in report.blockers
    assert "SCHEDULER_PROFILE_RESURRECTION" in report.blockers
    assert "SCHEDULER_OVERPLANS_QUOTA" in report.blockers


def test_gate_rejects_regex_only_public_key_validation() -> None:
    evidence = _good_evidence()
    evidence["public_keys"] = {
        "canonical_solana_decode": False,
        "round_trip_normalization": False,
        "regex_only_vectors_rejected": False,
    }

    report = evaluate_mpr11_routing_quota_gate(evidence)

    assert "PUBLIC_KEY_REGEX_ONLY" in report.blockers
    assert "PUBLIC_KEY_REGEX_VECTOR_ACCEPTED" in report.blockers


def test_gate_rejects_no_expiry_or_stale_quotes() -> None:
    evidence = _good_evidence()
    evidence["quote_freshness"] = {
        "trusted_current_time_or_slot": False,
        "no_expiry_execution_rejected": False,
        "stale_replay_rejected": False,
        "blockhash_or_provider_validity_bound": False,
    }

    report = evaluate_mpr11_routing_quota_gate(evidence)

    assert "QUOTE_TRUSTED_TIME_MISSING" in report.blockers
    assert "QUOTE_NO_EXPIRY_EXECUTABLE" in report.blockers
    assert "QUOTE_STALE_REPLAY_ACCEPTED" in report.blockers


def test_gate_rejects_insecure_injected_transport_claims() -> None:
    evidence = _good_evidence()
    evidence["transport"] = {
        "actual_client_policy_attested": False,
        "injected_insecure_client_rejected": False,
        "tls_verify_bound_to_evidence": False,
        "proxy_redirect_policy_bound": False,
    }

    report = evaluate_mpr11_routing_quota_gate(evidence)

    assert "TRANSPORT_CLIENT_NOT_ATTESTED" in report.blockers
    assert "TRANSPORT_INSECURE_CLIENT_ACCEPTED" in report.blockers
    assert "TRANSPORT_TLS_EVIDENCE_NOT_ACTUAL" in report.blockers


def test_gate_rejects_adapter_risk_widening_and_substitution() -> None:
    evidence = _good_evidence()
    evidence["adapters"] = {
        "jupiter_slippage_not_widened": False,
        "jupiter_swap_mode_echo_verified": False,
        "openocean_mint_echo_verified": False,
        "odos_token_amount_echo_verified": False,
        "okx_request_response_bound": False,
        "cross_request_substitution_rejected": False,
    }

    report = evaluate_mpr11_routing_quota_gate(evidence)

    assert "JUPITER_SLIPPAGE_WIDENING" in report.blockers
    assert "JUPITER_SWAP_MODE_UNBOUND" in report.blockers
    assert "ADAPTER_SUBSTITUTION_ACCEPTED" in report.blockers


def test_gate_rejects_label_only_route_identity_and_live_surfaces() -> None:
    evidence = _good_evidence()
    evidence["route_identity"] = {
        "program_pool_account_identity": False,
        "blockhash_validity_bound": False,
        "schema_generation_bound": False,
        "expired_blockhash_rejected": False,
    }
    evidence["live_execution_enabled"] = True
    evidence["provider_network_enabled"] = True
    evidence["signer_enabled"] = True

    report = evaluate_mpr11_routing_quota_gate(evidence)

    assert "ROUTE_LABEL_ONLY_IDENTITY" in report.blockers
    assert "ROUTE_EXPIRED_BLOCKHASH_ACCEPTED" in report.blockers
    assert "LIVE_EXECUTION_FORBIDDEN" in report.blockers
    assert "PROVIDER_NETWORK_FORBIDDEN" in report.blockers
    assert "SIGNER_FORBIDDEN" in report.blockers
