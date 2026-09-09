"""MPR-2602 prepared-plan identity sensitivity regressions."""

from __future__ import annotations

import base64
from dataclasses import replace

import pytest

from src.paper_shadow.mpr2602_runtime import (
    _prepared_plan_hash,
    validate_prepared_plan_hash,
)
from tests.test_mpr2602_full_flashloan_vertical import offline_vertical_fixture

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
        replace(candidate.request.leg_a, received_at=candidate.request.leg_a.received_at + 9),
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
    reversed_assets = replace(candidate, approved_assets=tuple(reversed(candidate.approved_assets)))
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
