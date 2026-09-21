from __future__ import annotations

from typing import cast

import pytest
from solders.address_lookup_table_account import AddressLookupTableAccount
from solders.pubkey import Pubkey

from src.execution.alt_lifecycle import (
    ALT_UPSTREAM_COMMIT,
    ALT_UPSTREAM_LICENSE,
    AltAction,
    AltPreparationDisposition,
    AltPreparationPolicy,
    AltRetirementDisposition,
    OwnedAltError,
    OwnedAltState,
    build_owned_alt_instruction,
    plan_owned_alt_preparation,
    plan_owned_alt_retirement,
    publish_ready_alt_version,
)
from src.execution.models import (
    ADDRESS_LOOKUP_TABLE_PROGRAM_ID,
    ResolvedAddressLookupTable,
)
from src.execution.transaction_compiler import AltValidator

H = "a" * 64


def test_nf341_requires_v0_measured_benefit() -> None:
    authority = Pubkey.new_unique()
    payer = Pubkey.new_unique()
    addresses = (Pubkey.new_unique(), Pubkey.new_unique())
    blocked = plan_owned_alt_preparation(
        authority=authority,
        payer=payer,
        desired_addresses=addresses,
        existing=None,
        estimated_savings_bytes=100,
        policy=AltPreparationPolicy(
            format_id="v1",
            minimum_savings_bytes=10,
            preparation_budget_lamports=1_000,
            estimated_create_extend_cost_lamports=100,
        ),
    )
    assert blocked.disposition is AltPreparationDisposition.BLOCKED
    assert blocked.reason_code == "FORMAT_NOT_V0"

    no_benefit = plan_owned_alt_preparation(
        authority=authority,
        payer=payer,
        desired_addresses=addresses,
        existing=None,
        estimated_savings_bytes=1,
        policy=AltPreparationPolicy(
            format_id="v0",
            minimum_savings_bytes=10,
            preparation_budget_lamports=1_000,
            estimated_create_extend_cost_lamports=100,
        ),
    )
    assert no_benefit.disposition is AltPreparationDisposition.NO_BENEFIT


def test_nf342_create_builder_matches_pinned_web3_layout() -> None:
    authority = Pubkey.new_unique()
    payer = Pubkey.new_unique()
    slot = 123456
    built = build_owned_alt_instruction(
        action=AltAction.CREATE,
        authority=authority,
        payer=payer,
        recent_slot=slot,
    )
    expected_address, bump = Pubkey.find_program_address(
        [bytes(authority), slot.to_bytes(8, "little")],
        ADDRESS_LOOKUP_TABLE_PROGRAM_ID,
    )
    assert built.lookup_table == expected_address
    assert bytes(built.instruction.data) == (
        (0).to_bytes(4, "little")
        + slot.to_bytes(8, "little")
        + bytes([bump])
    )
    assert [meta.pubkey for meta in built.instruction.accounts][:3] == [
        expected_address,
        authority,
        payer,
    ]
    assert ALT_UPSTREAM_COMMIT == (
        "0b600488afc85bb1f4d41827c7b800fb31c034f5"
    )
    assert ALT_UPSTREAM_LICENSE == "MIT"


def test_nf342_extend_deactivate_close_layouts() -> None:
    authority = Pubkey.new_unique()
    payer = Pubkey.new_unique()
    table = Pubkey.new_unique()
    recipient = Pubkey.new_unique()
    addresses = (Pubkey.new_unique(), Pubkey.new_unique())
    extend = build_owned_alt_instruction(
        action=AltAction.EXTEND,
        authority=authority,
        payer=payer,
        lookup_table=table,
        addresses=addresses,
    )
    assert bytes(extend.instruction.data) == (
        (2).to_bytes(4, "little")
        + len(addresses).to_bytes(8, "little")
        + b"".join(bytes(item) for item in addresses)
    )
    deactivate = build_owned_alt_instruction(
        action=AltAction.DEACTIVATE,
        authority=authority,
        lookup_table=table,
    )
    close = build_owned_alt_instruction(
        action=AltAction.CLOSE,
        authority=authority,
        lookup_table=table,
        recipient=recipient,
    )
    assert bytes(deactivate.instruction.data) == (3).to_bytes(4, "little")
    assert bytes(close.instruction.data) == (4).to_bytes(4, "little")


def test_nf343_publication_delegates_to_canonical_alt_validator() -> None:
    address = Pubkey.new_unique()
    owner = ADDRESS_LOOKUP_TABLE_PROGRAM_ID
    addresses = (Pubkey.new_unique(), Pubkey.new_unique())

    class FakeValidator:
        def deserialize(self, *_args, **_kwargs):
            return ResolvedAddressLookupTable(
                address=address,
                owner=owner,
                addresses=addresses,
                deactivation_slot=2**64 - 1,
                last_extended_slot=10,
                last_extended_slot_start_index=0,
                source_slot=20,
                data_hash=H,
                account=AddressLookupTableAccount(address, addresses),
            )

    version = publish_ready_alt_version(
        address=address,
        raw_data=b"observed",
        owner=owner,
        source_slot=20,
        expected_addresses=addresses,
        finalized_operation_hash=H,
        validator=cast(AltValidator, FakeValidator()),
    )
    assert version.addresses == addresses
    assert version.version_hash != H


def test_nf344_outstanding_reference_blocks_retirement() -> None:
    authority = Pubkey.new_unique()
    table = Pubkey.new_unique()
    recipient = Pubkey.new_unique()
    active = OwnedAltState(
        table,
        authority,
        (Pubkey.new_unique(),),
        10,
        False,
    )
    blocked = plan_owned_alt_retirement(
        state=active,
        authority=authority,
        recipient=recipient,
        outstanding_reference_leases=1,
        unknown_submissions=0,
        protocol_close_eligible=False,
        recipient_allowed=True,
    )
    assert blocked.disposition is AltRetirementDisposition.BLOCKED
    assert blocked.reason_code == "OUTSTANDING_TRANSACTION"

    deactivated = OwnedAltState(
        table,
        authority,
        active.addresses,
        10,
        True,
    )
    close = plan_owned_alt_retirement(
        state=deactivated,
        authority=authority,
        recipient=recipient,
        outstanding_reference_leases=0,
        unknown_submissions=0,
        protocol_close_eligible=True,
        recipient_allowed=True,
    )
    assert close.disposition is AltRetirementDisposition.CLOSE

    with pytest.raises(OwnedAltError, match="INVALID_ACTION"):
        build_owned_alt_instruction(
            action=AltAction.CLOSE,
            authority=authority,
            lookup_table=table,
            recipient=recipient,
            payer=authority,
        )
