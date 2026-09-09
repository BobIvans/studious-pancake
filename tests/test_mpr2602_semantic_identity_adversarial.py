"""Fail-closed identity and full Jupiter/ALT sensitivity, without network effects."""

from __future__ import annotations

import base64
from dataclasses import dataclass, replace
from enum import IntEnum, StrEnum

import pytest
from solders.address_lookup_table_account import AddressLookupTableAccount
from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from src.durability import AttemptKey
from src.durability.unified_authority_pr02 import UnifiedAuthorityError
from src.execution.models import (
    ADDRESS_LOOKUP_TABLE_PROGRAM_ID,
    ResolvedAddressLookupTable,
)
from src.kernel import canonical_json_bytes
from src.paper_shadow.mpr2602_runtime import (
    MPR2602_PREPARED_PLAN_SCHEMA,
    _prepared_plan_hash,
    _semantic_value,
    begin_prepared_attempt_intent,
    validate_prepared_plan_hash,
)
from tests.test_mpr2602_full_flashloan_vertical import offline_vertical_fixture
from tests.test_pr02_unified_lifecycle_authority import authority, digest

pytestmark = pytest.mark.unit


def candidate():
    return offline_vertical_fixture()[1]


def pubkey(byte):
    return Pubkey.from_bytes(bytes([byte]) * 32)


def encoded(value):
    return canonical_json_bytes(_semantic_value(value))


class PolicyA(StrEnum):
    SAFE = "safe"


class PolicyB(StrEnum):
    SAFE = "safe"


class NumericPolicyA(IntEnum):
    SAFE = 1


class NumericPolicyB(IntEnum):
    SAFE = 1


@pytest.mark.parametrize(
    "left,right,scalar",
    [
        (PolicyA.SAFE, PolicyB.SAFE, "safe"),
        (NumericPolicyA.SAFE, NumericPolicyB.SAFE, 1),
    ],
)
def test_enum_policy_identity_cannot_alias_another_type_or_scalar(left, right, scalar):
    assert len({encoded(left), encoded(right), encoded(scalar)}) == 3
    assert len({encoded({left: 7}), encoded({right: 7}), encoded({scalar: 7})}) == 3


def test_pubkey_mapping_key_cannot_alias_string_or_depend_on_insertion_order():
    key = pubkey(17)
    assert encoded({key: 1}) != encoded({str(key): 1})
    first = {key: "sdk-key", str(key): "text-key"}
    reverse = {str(key): "text-key", key: "sdk-key"}
    assert encoded(first) == encoded(reverse)
    assert encoded(first) != encoded({key: "text-key", str(key): "sdk-key"})


class OpaquePolicy:
    def __init__(self, permitted):
        self._permitted = permitted
        self.name = "same-visible-policy"


class SlotPolicy:
    __slots__ = ("_permitted", "name")

    def __init__(self, permitted):
        self._permitted = permitted
        self.name = "same-visible-policy"


@pytest.mark.parametrize(
    "value",
    [
        OpaquePolicy(True),
        OpaquePolicy(False),
        SlotPolicy(True),
        SlotPolicy(False),
        lambda: 1,
    ],
)
def test_opaque_private_or_callable_state_is_rejected_instead_of_omitted(value):
    with pytest.raises(TypeError, match="MPR2602_UNSUPPORTED_PLAN_VALUE"):
        encoded(value)
    plan = candidate()
    leg = replace(plan.request.leg_a, route_plan=({"decoder_policy": value},))
    with pytest.raises(TypeError, match="MPR2602_UNSUPPORTED_PLAN_VALUE"):
        _prepared_plan_hash(replace(plan, request=replace(plan.request, leg_a=leg)))


@dataclass(frozen=True)
class ExplicitPolicy:
    _permitted: bool
    name: str = "same-visible-policy"


def test_private_dataclass_execution_fields_are_bound_not_filtered():
    assert encoded(ExplicitPolicy(True)) != encoded(ExplicitPolicy(False))


def test_canonical_set_identity_is_order_independent_and_member_sensitive():
    assert encoded(frozenset(("one", "two"))) == encoded(set(("two", "one")))
    assert encoded({"one", "two"}) != encoded({"one", "three"})


@pytest.mark.parametrize("leg_name", ["leg_a", "leg_b"])
@pytest.mark.parametrize(
    "bucket",
    [
        "compute_unit_price_instructions",
        "setup_instructions",
        "swap_instruction",
        "cleanup_instruction",
        "other_instructions",
        "tip_instruction",
    ],
)
def test_each_instruction_bucket_on_each_leg_invalidates_old_identity(leg_name, bucket):
    plan = candidate()
    leg = getattr(plan.request, leg_name)
    instruction = replace(
        leg.swap_instruction,
        data_b64=base64.b64encode(b"identity-adversarial-instruction").decode("ascii"),
    )
    replacement = instruction if bucket.endswith("_instruction") else (instruction,)
    leg = replace(leg, **{bucket: replacement})
    changed = replace(plan, request=replace(plan.request, **{leg_name: leg}))
    with pytest.raises(ValueError, match="MPR2602_PREPARED_PLAN_IDENTITY_MISMATCH"):
        validate_prepared_plan_hash(changed, _prepared_plan_hash(plan))


@pytest.mark.parametrize("leg_name", ["leg_a", "leg_b"])
def test_nested_route_metadata_and_route_order_are_bound(leg_name):
    plan = candidate()
    leg = getattr(plan.request, leg_name)
    first = {"swapInfo": {"ammKey": "one", "feeAmount": "1"}, "percent": 50}
    second = {"swapInfo": {"ammKey": "two", "feeAmount": "2"}, "percent": 50}

    def with_route(route):
        return replace(
            plan,
            request=replace(plan.request, **{leg_name: replace(leg, route_plan=route)}),
        )

    baseline = _prepared_plan_hash(with_route((first, second)))
    assert _prepared_plan_hash(with_route((second, first))) != baseline
    changed = {**first, "swapInfo": {**first["swapInfo"], "feeAmount": "3"}}
    assert _prepared_plan_hash(with_route((changed, second))) != baseline


@pytest.mark.parametrize("flag", ["is_signer", "is_writable"])
def test_actual_solders_account_privileges_are_bound(flag):
    key = pubkey(18)
    original = Instruction(pubkey(19), b"payload", [AccountMeta(key, False, False)])
    meta = AccountMeta(key, flag == "is_signer", flag == "is_writable")
    changed = Instruction(pubkey(19), b"payload", [meta])
    assert encoded(original) != encoded(changed)


def resolved_alt():
    key = pubkey(20)
    addresses = (pubkey(21), pubkey(22))
    return ResolvedAddressLookupTable(
        address=key,
        owner=ADDRESS_LOOKUP_TABLE_PROGRAM_ID,
        addresses=addresses,
        deactivation_slot=None,
        last_extended_slot=99,
        last_extended_slot_start_index=0,
        source_slot=100,
        data_hash="a" * 64,
        account=AddressLookupTableAccount(key, list(addresses)),
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("address", pubkey(23)),
        ("owner", pubkey(24)),
        ("addresses", (pubkey(22), pubkey(21))),
        ("deactivation_slot", 101),
        ("last_extended_slot", 98),
        ("last_extended_slot_start_index", 1),
        ("source_slot", 102),
        ("data_hash", "b" * 64),
        ("account", AddressLookupTableAccount(pubkey(20), [pubkey(21), pubkey(25)])),
        ("library_deserialized", False),
    ],
)
def test_resolved_alt_contents_and_all_provenance_fields_are_bound(field, value):
    plan = replace(candidate(), lookup_tables=(resolved_alt(),))
    changed = replace(
        plan, lookup_tables=(replace(plan.lookup_tables[0], **{field: value}),)
    )
    assert _prepared_plan_hash(changed) != _prepared_plan_hash(plan)


@pytest.mark.parametrize(
    "field,value",
    [
        ("payer", pubkey(26)),
        ("destination_token_account", pubkey(27)),
        ("repayment_source_token_account", pubkey(28)),
        ("oracle_slot", 987654321),
        ("discovery_slot", 987654322),
        ("safety_surplus", 987654323),
        ("monitored_accounts", (pubkey(29),)),
        ("jupiter_contract_pin", "c" * 64),
    ],
)
def test_planner_accounts_slots_and_safety_are_bound(field, value):
    plan = candidate()
    assert getattr(plan.request, field) != value
    changed = replace(plan, request=replace(plan.request, **{field: value}))
    assert _prepared_plan_hash(changed) != _prepared_plan_hash(plan)


@pytest.mark.parametrize("value", ["F" * 64, "+" + "1" * 63, " " + "1" * 63, "g" * 64])
def test_noncanonical_digest_is_invalid_not_a_replay_candidate(value):
    with pytest.raises(ValueError, match="MPR2602_PREPARED_PLAN_HASH_INVALID"):
        validate_prepared_plan_hash(candidate(), value)


def test_v1_intent_is_not_silently_relabelled_as_v2(tmp_path):
    assert MPR2602_PREPARED_PLAN_SCHEMA == "mpr2602.prepared-plan-identity.v2"
    store, _clock = authority(tmp_path)
    try:
        plan = candidate()
        attempt = store.lifecycle.create_attempt(
            AttemptKey("mpr2602-source-vertical", digest("v1-bound-plan"), 1),
            idempotency_key="semantic-v1-create",
            reservation_id="semantic-v1-reservation",
            candidate_id="mpr2602-source-vertical",
            reserved_lamports=123,
        )
        payload = {
            "schema": "mpr2602.prepared-plan-identity.v1",
            "opportunity_id": plan.request.opportunity_id,
            "prepared_plan_hash": _prepared_plan_hash(plan),
        }
        store.begin_attempt_intent(
            attempt_id=attempt.attempt_id, attempt_generation=1, request_payload=payload
        )
        with pytest.raises(
            UnifiedAuthorityError, match="PR02_INTENT_IMMUTABILITY_CONFLICT"
        ):
            begin_prepared_attempt_intent(
                store,
                attempt_id=attempt.attempt_id,
                attempt_generation=1,
                candidate=plan,
            )
    finally:
        store.close()


@pytest.mark.parametrize("mutation", ["cleanup", "route", "alt", "decoder", "capital"])
def test_committed_terminal_cannot_be_reused_after_prepared_semantic_drift(
    tmp_path, mutation
):
    from src.durability.unified_authority_pr02 import ReservationTerminalState
    from src.execution.models import ExecutionState

    store, _clock = authority(tmp_path)
    try:
        plan = replace(candidate(), lookup_tables=(resolved_alt(),))
        attempt = store.lifecycle.create_attempt(
            AttemptKey("mpr2602-source-vertical", digest("terminal-identity"), 1),
            idempotency_key="semantic-terminal-create",
            reservation_id="semantic-terminal-reservation",
            candidate_id="mpr2602-source-vertical",
            reserved_lamports=123,
        )
        fence, plan_hash = begin_prepared_attempt_intent(
            store, attempt_id=attempt.attempt_id, attempt_generation=1, candidate=plan
        )
        arguments = dict(
            target_state=ExecutionState.REJECTED,
            reservation_terminal_state=ReservationTerminalState.RELEASED,
            outcome="BLOCKED",
            reason_code="OFFLINE_IDENTITY_REJECTION",
            report_hash=digest({"prepared_plan_hash": plan_hash}),
            report_payload={"prepared_plan_hash": plan_hash},
        )
        terminal = store.commit_attempt_terminal(fence, **arguments)
        same = store.commit_attempt_terminal(fence, **arguments)
        assert same.replayed and same.terminal_id == terminal.terminal_id

        if mutation == "cleanup":
            leg = replace(
                plan.request.leg_a,
                cleanup_instruction=plan.request.leg_a.swap_instruction,
            )
            changed = replace(plan, request=replace(plan.request, leg_a=leg))
        elif mutation == "route":
            leg = replace(plan.request.leg_b, route_plan=({"mutated": "route"},))
            changed = replace(plan, request=replace(plan.request, leg_b=leg))
        elif mutation == "alt":
            alt = replace(plan.lookup_tables[0], addresses=(pubkey(31),))
            changed = replace(plan, lookup_tables=(alt,))
        elif mutation == "decoder":
            changed = replace(
                plan,
                decode_policy=replace(
                    plan.decode_policy,
                    max_account_data_bytes=plan.decode_policy.max_account_data_bytes
                    + 1,
                ),
            )
        else:
            capital = replace(plan.request.capital, decision_hash="f" * 64)
            changed = replace(plan, request=replace(plan.request, capital=capital))
        with pytest.raises(ValueError, match="MPR2602_PREPARED_PLAN_IDENTITY_MISMATCH"):
            validate_prepared_plan_hash(changed, plan_hash)
        with pytest.raises(
            UnifiedAuthorityError, match="PR02_INTENT_IMMUTABILITY_CONFLICT"
        ):
            begin_prepared_attempt_intent(
                store,
                attempt_id=attempt.attempt_id,
                attempt_generation=1,
                candidate=changed,
            )
        assert (
            store.db.execute("SELECT COUNT(*) FROM pr02_terminal_records").fetchone()[0]
            == 1
        )
        assert (
            store.db.execute("SELECT COUNT(*) FROM pr02_outbox_event").fetchone()[0]
            == 1
        )
    finally:
        store.close()
