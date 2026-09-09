"""MPR-2602 prepared-plan identity sensitivity regressions."""

from __future__ import annotations

import base64
from dataclasses import replace
import math

import pytest

from src.durability import AttemptKey
from src.durability.unified_authority_pr02 import UnifiedAuthorityError
from src.kernel import canonical_json_bytes
from src.kernel.canonical_json import CanonicalJsonError
from src.paper_shadow.mpr2602_runtime import (
    _prepared_plan_hash,
    _semantic_value,
    begin_prepared_attempt_intent,
    validate_prepared_plan_hash,
)
from tests.test_mpr2602_full_flashloan_vertical import offline_vertical_fixture
from tests.test_pr02_unified_lifecycle_authority import authority, digest

pytestmark = pytest.mark.unit


def _candidate():
    _vertical, candidate, _rpc = offline_vertical_fixture()
    return candidate


def _with_leg_a(candidate, leg_a):
    return replace(candidate, request=replace(candidate.request, leg_a=leg_a))


def test_acquisition_timestamp_does_not_break_deterministic_terminal_replay():
    candidate = _candidate()
    changed = _with_leg_a(
        candidate,
        replace(
            candidate.request.leg_a,
            received_at=candidate.request.leg_a.received_at + 9,
        ),
    )
    assert _prepared_plan_hash(changed) == _prepared_plan_hash(candidate)


def test_route_mutation_cannot_reuse_old_terminal_identity():
    candidate = _candidate()
    leg = candidate.request.leg_a
    changed = _with_leg_a(
        candidate,
        replace(leg, route_plan=(*leg.route_plan, {"label": "mutated-route"})),
    )
    assert _prepared_plan_hash(changed) != _prepared_plan_hash(candidate)


def test_cleanup_mutation_cannot_reuse_old_terminal_identity():
    candidate = _candidate()
    leg = candidate.request.leg_a
    cleanup = replace(
        leg.swap_instruction,
        data_b64=base64.b64encode(b"mpr2602-cleanup-mutation").decode("ascii"),
        name="cleanup-mutation",
    )
    changed = _with_leg_a(candidate, replace(leg, cleanup_instruction=cleanup))
    assert _prepared_plan_hash(changed) != _prepared_plan_hash(candidate)


def test_alt_contents_mutation_cannot_reuse_old_terminal_identity():
    candidate = _candidate()
    leg = candidate.request.leg_a
    addresses = dict(leg.addresses_by_lookup_table_address)
    addresses["alt-mutated"] = ("resolved-address-mutated",)
    changed = _with_leg_a(
        candidate,
        replace(leg, addresses_by_lookup_table_address=addresses),
    )
    assert _prepared_plan_hash(changed) != _prepared_plan_hash(candidate)


def test_capital_lifecycle_proof_mutation_cannot_reuse_old_terminal_identity():
    candidate = _candidate()
    capital = replace(candidate.request.capital, decision_hash="f" * 64)
    changed = replace(candidate, request=replace(candidate.request, capital=capital))
    assert _prepared_plan_hash(changed) != _prepared_plan_hash(candidate)


def test_decoder_policy_mutation_cannot_reuse_old_terminal_identity():
    candidate = _candidate()
    assert candidate.decode_policy is not None
    changed = replace(
        candidate,
        decode_policy=replace(
            candidate.decode_policy,
            max_account_data_bytes=candidate.decode_policy.max_account_data_bytes + 1,
        ),
    )
    assert _prepared_plan_hash(changed) != _prepared_plan_hash(candidate)


def test_raw_pre_state_mutation_cannot_reuse_old_terminal_identity():
    candidate = _candidate()
    assert candidate.pre_state_accounts is not None
    states = list(candidate.pre_state_accounts)
    assert states and states[0] is not None
    first = dict(states[0])
    first["lamports"] = int(first.get("lamports", 0)) + 1
    states[0] = first
    changed = replace(candidate, pre_state_accounts=tuple(states))
    assert _prepared_plan_hash(changed) != _prepared_plan_hash(candidate)


def test_required_accounts_and_tip_are_terminal_identity_semantics():
    candidate = _candidate()
    required = replace(
        candidate,
        required_accounts=(*candidate.required_accounts, "required-account-mutated"),
    )
    tipped = replace(candidate, tip_lamports=candidate.tip_lamports + 1)
    baseline = _prepared_plan_hash(candidate)
    assert _prepared_plan_hash(required) != baseline
    assert _prepared_plan_hash(tipped) != baseline


def test_settlement_and_approved_assets_are_terminal_identity_semantics():
    candidate = _candidate()
    assert candidate.approved_assets
    baseline = _prepared_plan_hash(candidate)
    reversed_assets = replace(
        candidate,
        approved_assets=tuple(reversed(candidate.approved_assets)),
    )
    assert _prepared_plan_hash(reversed_assets) != baseline
    if len(candidate.approved_assets) > 1:
        settlement = replace(candidate, settlement_asset=candidate.approved_assets[1])
        assert _prepared_plan_hash(settlement) != baseline


def test_validator_rejects_old_terminal_hash_after_semantic_mutation():
    candidate = _candidate()
    terminal_hash = _prepared_plan_hash(candidate)
    validate_prepared_plan_hash(candidate, terminal_hash)
    changed = replace(candidate, tip_lamports=candidate.tip_lamports + 1)
    with pytest.raises(ValueError, match="MPR2602_PREPARED_PLAN_IDENTITY_MISMATCH"):
        validate_prepared_plan_hash(changed, terminal_hash)


def test_unified_authority_replays_identical_plan_and_rejects_semantic_drift(
    tmp_path,
):
    store, _clock = authority(tmp_path)
    try:
        candidate = _candidate()
        attempt = store.lifecycle.create_attempt(
            AttemptKey("mpr2602-source-vertical", digest("pre-reserve-plan"), 1),
            idempotency_key="mpr2602-plan-identity-create",
            reservation_id="mpr2602-plan-identity-reservation",
            candidate_id="mpr2602-source-vertical",
            reserved_lamports=123,
        )
        first, plan_hash = begin_prepared_attempt_intent(
            store,
            attempt_id=attempt.attempt_id,
            attempt_generation=1,
            candidate=candidate,
        )
        replay, replay_hash = begin_prepared_attempt_intent(
            store,
            attempt_id=attempt.attempt_id,
            attempt_generation=1,
            candidate=candidate,
        )
        assert replay_hash == plan_hash
        assert replay.intent_id == first.intent_id
        assert replay.replayed

        changed = replace(candidate, tip_lamports=candidate.tip_lamports + 1)
        with pytest.raises(
            UnifiedAuthorityError,
            match="PR02_INTENT_IMMUTABILITY_CONFLICT",
        ):
            begin_prepared_attempt_intent(
                store,
                attempt_id=attempt.attempt_id,
                attempt_generation=1,
                candidate=changed,
            )
        assert (
            store.db.execute(
                "SELECT COUNT(*) FROM pr02_intents WHERE intent_kind='paper_attempt'"
            ).fetchone()[0]
            == 1
        )
    finally:
        store.close()


@pytest.mark.parametrize(
    "value", [0.0, -0.0, 0.1, math.nextafter(1.0, 2.0), 1e300, 5e-324]
)
def test_finite_float_metadata_is_lossless_and_canonical_json_safe(value):
    encoded = _semantic_value(value)
    assert encoded == {"__float_hex__": value.hex()}
    assert float.fromhex(encoded["__float_hex__"]).hex() == value.hex()
    assert canonical_json_bytes(encoded)
    # Identity adaptation must not weaken the global integer-only format.
    with pytest.raises(CanonicalJsonError, match="floating-point values are forbidden"):
        canonical_json_bytes({"value": value})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_plan_metadata_remains_fail_closed(value):
    candidate = _candidate()
    leg = replace(candidate.request.leg_a, route_plan=({"impact": value},))
    with pytest.raises(ValueError, match="MPR2602_NONFINITE_PLAN_VALUE"):
        _prepared_plan_hash(_with_leg_a(candidate, leg))


def test_adjacent_float_route_metadata_cannot_reuse_plan_identity():
    candidate = _candidate()
    leg = replace(candidate.request.leg_a, route_plan=({"impact": 0.1},))
    changed = replace(leg, route_plan=({"impact": math.nextafter(0.1, 1.0)},))
    assert _prepared_plan_hash(_with_leg_a(candidate, leg)) != _prepared_plan_hash(
        _with_leg_a(candidate, changed)
    )


def test_float_identity_cannot_alias_integer_string_or_mapping():
    encoded = _semantic_value(1.0)
    for other in (1, "0x1.0000000000000p+0", {"__float_hex__": (1.0).hex()}):
        assert canonical_json_bytes(encoded) != canonical_json_bytes(
            _semantic_value(other)
        )
    assert canonical_json_bytes(_semantic_value(0.0)) != canonical_json_bytes(
        _semantic_value(-0.0)
    )
