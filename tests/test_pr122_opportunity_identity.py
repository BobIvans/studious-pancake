from __future__ import annotations

import pytest

from src.strategy.opportunity_identity import (
    IDENTITY_SCHEMA_VERSION,
    LOGICAL_ID_PREFIX,
    OpportunityIdentityError,
    PersistentOpportunityDedupLedger,
    build_logical_opportunity_identity,
)


def _leg(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "provider": "jupiter_router",
        "input_mint": "So11111111111111111111111111111111111111112",
        "output_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "in_amount": 100_000,
        "out_amount": 110_000,
        "slot": 42,
        "request_fingerprint": "request-a",
        "response_hash": "response-a",
        "quote_id": "quote-a",
        "source": "runtime-discovery",
        "commitment": "confirmed",
        "correlation_labels": ["cycle:one", "underlying:raydium"],
    }
    values.update(overrides)
    return values


def _identity(**overrides: object):
    values = {
        "strategy_name": "circular_arbitrage",
        "opportunity_type": "two_leg_circular_snapshot",
        "pair_id": "sol-usdc-loop",
        "exact_amount_base_units": 100_000,
        "first_leg": _leg(),
        "second_leg": _leg(
            input_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            output_mint="So11111111111111111111111111111111111111112",
            in_amount=110_000,
            out_amount=101_000,
            request_fingerprint="request-b",
            response_hash="response-b",
        ),
        "policy_version": "detector-policy-v1",
        "slot_bucket": 42,
    }
    values.update(overrides)
    return build_logical_opportunity_identity(**values)


def test_same_exact_market_evidence_replays_same_logical_id() -> None:
    first = _identity()
    second = _identity()

    assert first.schema_version == IDENTITY_SCHEMA_VERSION
    assert first.logical_opportunity_id == second.logical_opportunity_id
    assert first.logical_opportunity_id.startswith(LOGICAL_ID_PREFIX)
    assert first.evidence_hash == second.evidence_hash


def test_material_route_change_changes_logical_id() -> None:
    first = _identity()
    second = _identity(second_leg=_leg(response_hash="response-c"))

    assert first.logical_opportunity_id != second.logical_opportunity_id


def test_blockhash_is_not_part_of_identity_payload() -> None:
    identity = _identity()

    assert "blockhash" not in identity.identity_payload
    assert "recent_blockhash" not in identity.identity_payload


def test_missing_request_or_response_hash_is_rejected() -> None:
    bad_leg = _leg(response_hash=None)

    with pytest.raises(OpportunityIdentityError, match="response_hash"):
        _identity(first_leg=bad_leg)


def test_zero_output_quote_can_still_be_identity_evidence() -> None:
    identity = _identity(first_leg=_leg(out_amount=0))

    assert identity.logical_opportunity_id.startswith(LOGICAL_ID_PREFIX)


def test_persistent_ledger_blocks_same_evidence_after_restart(tmp_path) -> None:
    db = tmp_path / "dedup.sqlite3"
    identity = _identity()

    with PersistentOpportunityDedupLedger(db, clock_ns=lambda: 100) as ledger:
        admitted = ledger.admit(
            identity,
            strategy_name="circular_arbitrage",
            pair_id="sol-usdc-loop",
            exact_amount_base_units=100_000,
            policy_version="detector-policy-v1",
        )
        assert admitted.admitted is True

    with PersistentOpportunityDedupLedger(db, clock_ns=lambda: 200) as ledger:
        duplicate = ledger.admit(
            identity,
            strategy_name="circular_arbitrage",
            pair_id="sol-usdc-loop",
            exact_amount_base_units=100_000,
            policy_version="detector-policy-v1",
        )

    assert duplicate.admitted is False
    assert duplicate.reason_code == "duplicate_logical_opportunity_blocked"
    assert duplicate.first_seen_ns == 100
    assert duplicate.last_seen_ns == 200
    assert duplicate.attempts_seen == 2


def test_material_invalidation_can_admit_same_logical_id(tmp_path) -> None:
    db = tmp_path / "dedup.sqlite3"
    identity = _identity()

    with PersistentOpportunityDedupLedger(db) as ledger:
        ledger.admit(
            identity,
            strategy_name="circular_arbitrage",
            pair_id="sol-usdc-loop",
            exact_amount_base_units=100_000,
            policy_version="detector-policy-v1",
        )
        admitted = ledger.admit(
            identity,
            strategy_name="circular_arbitrage",
            pair_id="sol-usdc-loop",
            exact_amount_base_units=100_000,
            policy_version="detector-policy-v1",
            invalidation_reason="quote_hash_changed",
        )

    assert admitted.admitted is True
    assert admitted.reason_code.endswith("quote_hash_changed")


def test_unknown_invalidation_reason_is_rejected(tmp_path) -> None:
    db = tmp_path / "dedup.sqlite3"

    with PersistentOpportunityDedupLedger(db) as ledger:
        with pytest.raises(OpportunityIdentityError, match="unsupported"):
            ledger.admit(
                _identity(),
                strategy_name="circular_arbitrage",
                pair_id="sol-usdc-loop",
                exact_amount_base_units=100_000,
                policy_version="detector-policy-v1",
                invalidation_reason="new_blockhash_only",
            )
