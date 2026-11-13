"""R02-CAP-A: read-only Jupiter Lend TokenReserve capacity reader tests.

Offline only: fixture account bytes are synthetic, built schema-driven from
the pinned dossier (docs/roadmap/r02-capacity-recovery-2026-10-08/offline/
jupiter_token_reserve_layout.json). No network, no live captures, no signing.
Unknown is not zero: every unproven constraint must surface as typed evidence.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest
from solders.pubkey import Pubkey

from src.assets.resolution.evidence import Evidence
from src.economics.flash_capital_graph.graph import FlashCapitalEdge
from src.lending.jupiter_lend import (
    FLASHLOAN_ADMIN_ACCOUNT_LEN,
    FLASHLOAN_ADMIN_DISCRIMINATOR,
    JUPITER_FLASHLOAN_ADMIN_BUMP,
    JUPITER_FLASHLOAN_ADMIN_PDA,
    JUPITER_LEND_FLASHLOAN_PROGRAM_ID,
    JUPITER_LEND_LIQUIDITY_IDL_BLOB,
    JUPITER_LEND_LIQUIDITY_IDL_NAME,
    JUPITER_LEND_LIQUIDITY_IDL_VERSION,
    JUPITER_LEND_LIQUIDITY_PROGRAM_ID,
    JUPITER_LEND_LIQUIDITY_UPSTREAM_COMMIT,
    JUPITER_TOKEN_RESERVE_SEED,
    JUPITER_TOKEN_RESERVE_SEED_SOURCE,
    READER_DECODER_GENERATION,
    READER_DECODER_IDENTITY,
    READER_EXECUTION_AUTHORITY,
    SPL_TOKEN_ACCOUNT_LEN,
    SPL_TOKEN_PROGRAM_ID,
    SYSTEM_PROGRAM_ID,
    TOKEN_RESERVE_ACCOUNT_LEN,
    TOKEN_RESERVE_DISCRIMINATOR,
    JupiterLendAdapterError,
    JupiterLendFlashloanAccounts,
    JupiterLendReserveCapacityObservation,
    admit_reserve_financing_snapshot,
    decode_flashloan_admin_state,
    decode_token_reserve_state,
    decode_vault_token_account,
    derive_token_reserve_pda,
    observe_token_reserve_capacity,
    reserve_capital_edge_gate,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PINNED_DOSSIER = (
    REPO_ROOT
    / "docs/roadmap/r02-capacity-recovery-2026-10-08/offline/jupiter_token_reserve_layout.json"
)


def _pk(seed: int) -> Pubkey:
    return Pubkey.from_bytes(bytes((seed,)) * 32)


def _pinned_layout() -> dict:
    return json.loads(PINNED_DOSSIER.read_text(encoding="utf-8"))


def _zero_pubkey_bytes() -> bytes:
    return bytes(32)


def _reserve_bytes(values: dict[str, bytes]) -> bytes:
    """Build account bytes schema-driven from the pinned dossier layout."""

    layout = _pinned_layout()
    raw = bytearray(layout["account_size_bytes"])
    raw[:8] = bytes(layout["discriminator"])
    for field in layout["fields"]:
        chunk = values[field["name"]]
        raw[field["offset"] : field["offset"] + field["bytes"]] = chunk
    return bytes(raw)


def _default_reserve_values(mint: Pubkey, vault: Pubkey) -> dict[str, bytes]:
    """Synthetic resource values; identities are NOT reviewed mainnet state."""

    return {
        "mint": bytes(mint),
        "vault": bytes(vault),
        "borrow_rate": (500).to_bytes(2, "little"),
        "fee_on_interest": (1000).to_bytes(2, "little"),
        "last_utilization": (4200).to_bytes(2, "little"),
        "last_update_timestamp": (1_764_000_000).to_bytes(8, "little"),
        "supply_exchange_price": (1_100_000_000_000_000_000).to_bytes(8, "little"),
        "borrow_exchange_price": (1_050_000_000_000_000_000).to_bytes(8, "little"),
        "max_utilization": (8500).to_bytes(2, "little"),
        "total_supply_with_interest": (6_000_000_000).to_bytes(8, "little"),
        "total_supply_interest_free": (500_000_000).to_bytes(8, "little"),
        "total_borrow_with_interest": (3_000_000_000).to_bytes(8, "little"),
        "total_borrow_interest_free": (100_000_000).to_bytes(8, "little"),
        "total_claim_amount": (42).to_bytes(8, "little"),
        "interacting_protocol": _zero_pubkey_bytes(),
        "interacting_timestamp": (0).to_bytes(8, "little"),
        "interacting_balance": (0).to_bytes(8, "little"),
    }


def _vault_bytes(
    mint: Pubkey,
    authority: Pubkey,
    amount: int,
    *,
    account_state: int = 1,
    delegate: bool = False,
    is_native: bool = False,
    close_authority: bool = False,
) -> bytes:
    raw = bytearray(SPL_TOKEN_ACCOUNT_LEN)
    raw[0:32] = bytes(mint)
    raw[32:64] = bytes(authority)
    raw[64:72] = amount.to_bytes(8, "little")
    if delegate:
        raw[72:76] = (1).to_bytes(4, "little")
        raw[76:108] = bytes(_pk(77))
    raw[108] = account_state
    if is_native:
        raw[109:113] = (1).to_bytes(4, "little")
        raw[113:121] = (1).to_bytes(8, "little")
    if close_authority:
        raw[129:133] = (1).to_bytes(4, "little")
        raw[133:165] = bytes(_pk(78))
    return bytes(raw)


def _admin_bytes(
    *,
    authority: Pubkey,
    liquidity_program: Pubkey,
    status: bool = True,
    fee: int = 0,
    timestamp: int = 0,
    active: bool = False,
    active_amount: int = 0,
    bump: int = JUPITER_FLASHLOAN_ADMIN_BUMP,
) -> bytes:
    raw = bytearray(FLASHLOAN_ADMIN_ACCOUNT_LEN)
    raw[:8] = FLASHLOAN_ADMIN_DISCRIMINATOR
    raw[8:40] = bytes(authority)
    raw[40:72] = bytes(liquidity_program)
    raw[72] = 1 if status else 0
    raw[73:75] = fee.to_bytes(2, "little")
    raw[75:83] = timestamp.to_bytes(8, "little")
    raw[83] = 1 if active else 0
    raw[84:92] = active_amount.to_bytes(8, "little")
    raw[92] = bump
    return bytes(raw)


class Fixture:
    def __init__(self) -> None:
        self.mint = _pk(3)
        self.reserve_pda, bump = derive_token_reserve_pda(self.mint)
        self.bump = bump
        self.vault = _pk(9)
        self.reserve_bytes = _reserve_bytes(
            _default_reserve_values(self.mint, self.vault)
        )
        self.vault_bytes = _vault_bytes(self.mint, self.reserve_pda, 5_000_000_000)
        self.observation = observe_token_reserve_capacity(
            mint=self.mint,
            reserve_bytes=self.reserve_bytes,
            reserve_owner=JUPITER_LEND_LIQUIDITY_PROGRAM_ID,
            reserve_address=self.reserve_pda,
            vault_bytes=self.vault_bytes,
            vault_address=self.vault,
            vault_owner_program=SPL_TOKEN_PROGRAM_ID,
        )


@pytest.fixture(scope="module")
def fixture() -> Fixture:
    return Fixture()


def test_capacity_reader_pins_liquidity_source_and_seeds() -> None:
    assert JUPITER_LEND_LIQUIDITY_UPSTREAM_COMMIT == (
        "a484ddcf9b34ef6f6d575ad10b0673a18d9c8f31"
    )
    assert JUPITER_LEND_LIQUIDITY_IDL_BLOB == (
        "09209f553900df7da61f84a106ad85767fdac71d"
    )
    assert JUPITER_LEND_LIQUIDITY_IDL_NAME == "liquidity"
    assert JUPITER_LEND_LIQUIDITY_IDL_VERSION == "0.1.8"
    assert str(JUPITER_LEND_LIQUIDITY_PROGRAM_ID) == (
        "jupeiUmn818Jg1ekPURTpr4mFo29p46vygyykFJ3wZC"
    )
    assert JUPITER_TOKEN_RESERVE_SEED == b"reserve"
    assert "fluid-solana-programs@626b177f235224bc5d074d39439cd2558f542886" in (
        JUPITER_TOKEN_RESERVE_SEED_SOURCE
    )
    assert "get_reserve" in JUPITER_TOKEN_RESERVE_SEED_SOURCE
    assert TOKEN_RESERVE_ACCOUNT_LEN == 192
    assert TOKEN_RESERVE_DISCRIMINATOR == bytes((21, 18, 59, 135, 120, 20, 31, 12))
    assert READER_EXECUTION_AUTHORITY == "NONE"
    assert READER_DECODER_IDENTITY == "jupiter-lend.tokenreserve.capacity-reader.v1"
    assert READER_DECODER_GENERATION == 1


def test_token_reserve_pda_uses_pinned_reserve_seed(fixture: Fixture) -> None:
    expected, bump = Pubkey.find_program_address(
        [b"reserve", bytes(fixture.mint)],
        JUPITER_LEND_LIQUIDITY_PROGRAM_ID,
    )
    assert fixture.reserve_pda == expected
    assert fixture.bump == bump
    other_pda, _ = derive_token_reserve_pda(_pk(23))
    assert other_pda != fixture.reserve_pda
    # The pinned seed must match exactly; any other seed must not be accepted
    # as the canonical reserve PDA derivation.
    wrong_seed_pda, _ = Pubkey.find_program_address(
        [b"reservX", bytes(fixture.mint)],
        JUPITER_LEND_LIQUIDITY_PROGRAM_ID,
    )
    assert wrong_seed_pda != fixture.reserve_pda
    with pytest.raises(
        JupiterLendAdapterError, match="R02CAPA_CAPACITY_STATE_INVALID"
    ):
        derive_token_reserve_pda(Pubkey.from_bytes(bytes(32)))


def test_token_reserve_decode_roundtrips_pinned_layout_fields(
    fixture: Fixture,
) -> None:
    state = decode_token_reserve_state(
        fixture.reserve_bytes,
        owner=JUPITER_LEND_LIQUIDITY_PROGRAM_ID,
        address=fixture.reserve_pda,
    )
    values = _default_reserve_values(fixture.mint, fixture.vault)
    assert state.mint == fixture.mint
    assert state.vault == fixture.vault
    assert state.borrow_rate == int.from_bytes(values["borrow_rate"], "little")
    assert state.fee_on_interest == int.from_bytes(values["fee_on_interest"], "little")
    assert state.last_utilization == int.from_bytes(values["last_utilization"], "little")
    assert state.last_update_timestamp == int.from_bytes(
        values["last_update_timestamp"], "little"
    )
    assert state.supply_exchange_price == int.from_bytes(
        values["supply_exchange_price"], "little"
    )
    assert state.borrow_exchange_price == int.from_bytes(
        values["borrow_exchange_price"], "little"
    )
    assert state.max_utilization == int.from_bytes(values["max_utilization"], "little")
    assert state.total_supply_with_interest == int.from_bytes(
        values["total_supply_with_interest"], "little"
    )
    assert state.total_supply_interest_free == int.from_bytes(
        values["total_supply_interest_free"], "little"
    )
    assert state.total_borrow_with_interest == int.from_bytes(
        values["total_borrow_with_interest"], "little"
    )
    assert state.total_borrow_interest_free == int.from_bytes(
        values["total_borrow_interest_free"], "little"
    )
    assert state.total_claim_amount == int.from_bytes(
        values["total_claim_amount"], "little"
    )
    assert bytes(state.interacting_protocol) == values["interacting_protocol"]
    assert state.interacting_timestamp == 0
    assert state.interacting_balance == 0

    vault = fixture.observation.vault
    assert vault.amount == 5_000_000_000
    assert vault.mint == fixture.mint
    assert vault.authority == fixture.reserve_pda
    assert vault.owner_program == SPL_TOKEN_PROGRAM_ID
    assert vault.account_state == 1
    assert vault.delegate is None
    assert vault.close_authority is None


def test_capacity_observation_reports_resource_state_without_effective_cap(
    fixture: Fixture,
) -> None:
    obs = fixture.observation
    # Raw resource state is proven from decoded account bytes, not TVL/API.
    assert obs.raw_vault_amount_base_units == 5_000_000_000
    assert obs.raw_total_supply_base_units == 6_500_000_000
    assert obs.raw_total_borrow_base_units == 3_100_000_000
    assert obs.mint == str(fixture.mint)
    assert obs.reserve_pda == str(fixture.reserve_pda)
    assert obs.reserve_owner == str(JUPITER_LEND_LIQUIDITY_PROGRAM_ID)
    assert obs.reserve_data_sha256 == hashlib.sha256(fixture.reserve_bytes).hexdigest()
    assert obs.vault_data_sha256 == hashlib.sha256(fixture.vault_bytes).hexdigest()
    # Unknown is not zero: effective capacity stays unknown with typed blockers.
    assert obs.effective_capacity_base_units is None
    assert obs.capacity_derivation.value == "R02CAPA_CAPACITY_DERIVATION_UNPROVEN"
    assert set(obs.blockers) == {
        "MISSING_EFFECTIVE_FLASH_CAP",
        "LIVE_ROOTED_RPC_NOT_AUTHORIZED",
    }
    assert "UTILIZATION_SCALE_UNPINNED" in obs.constraint_gaps
    assert "MAX_UTILIZATION_SEMANTICS_UNPINNED" in obs.constraint_gaps
    assert "EXCHANGE_PRICE_VALUATION_UNAUDITED" in obs.constraint_gaps
    assert "FLASH_BORROW_POSITION_DEBT_CEILING_UNDECODED" in obs.constraint_gaps
    assert "FEE_ROUNDING_RULE_UNPINNED" in obs.constraint_gaps
    assert "TOTAL_CLAIM_SEMANTICS_UNPINNED" in obs.constraint_gaps
    assert "VAULT_AUTHORITY_BINDING_UNPROVEN" in obs.constraint_gaps
    assert "MINT_DECIMALS_UNPROVEN" in obs.constraint_gaps
    assert obs.status == "BLOCKED_LIVE_STATE"
    # Strictly offline provenance; no rooted slot is claimed.
    assert obs.slot is None
    assert obs.slot_rooted is False
    assert obs.slot_provenance == "OFFLINE_FIXTURE_NOT_ROOTED"
    assert obs.fee_rounding == "UNPINNED"
    assert obs.execution_authority == "NONE"
    assert obs.sign_enabled is False
    assert obs.send_enabled is False
    # Supplying mint decimals removes only that one gap.
    with_decimals = observe_token_reserve_capacity(
        mint=fixture.mint,
        reserve_bytes=fixture.reserve_bytes,
        reserve_owner=JUPITER_LEND_LIQUIDITY_PROGRAM_ID,
        reserve_address=fixture.reserve_pda,
        vault_bytes=fixture.vault_bytes,
        vault_address=fixture.vault,
        vault_owner_program=SPL_TOKEN_PROGRAM_ID,
        mint_decimals=9,
    )
    assert with_decimals.mint_decimals == 9
    assert "MINT_DECIMALS_UNPROVEN" not in with_decimals.constraint_gaps
    assert "UTILIZATION_SCALE_UNPINNED" in with_decimals.constraint_gaps


def test_capacity_observation_digest_is_content_addressed(fixture: Fixture) -> None:
    obs = fixture.observation
    rebuilt = observe_token_reserve_capacity(
        mint=fixture.mint,
        reserve_bytes=fixture.reserve_bytes,
        reserve_owner=JUPITER_LEND_LIQUIDITY_PROGRAM_ID,
        reserve_address=fixture.reserve_pda,
        vault_bytes=fixture.vault_bytes,
        vault_address=fixture.vault,
        vault_owner_program=SPL_TOKEN_PROGRAM_ID,
    )
    assert obs.evidence_digest == rebuilt.evidence_digest
    record = obs.evidence_record()
    assert record["evidence_sha256"] == obs.evidence_digest
    assert record["decoder_identity"] == READER_DECODER_IDENTITY

    mutated = bytearray(fixture.reserve_bytes)
    mutated[104] = (mutated[104] + 1) & 0xFF  # total_supply_with_interest
    drifted = observe_token_reserve_capacity(
        mint=fixture.mint,
        reserve_bytes=bytes(mutated),
        reserve_owner=JUPITER_LEND_LIQUIDITY_PROGRAM_ID,
        reserve_address=fixture.reserve_pda,
        vault_bytes=fixture.vault_bytes,
        vault_address=fixture.vault,
        vault_owner_program=SPL_TOKEN_PROGRAM_ID,
    )
    assert drifted.evidence_digest != obs.evidence_digest
    assert (
        drifted.state.total_supply_with_interest
        == obs.state.total_supply_with_interest + 1
    )
    bad_discriminator = bytearray(fixture.reserve_bytes)
    bad_discriminator[0] ^= 0xFF
    with pytest.raises(
        JupiterLendAdapterError, match="R02CAPA_TOKEN_RESERVE_UNKNOWN_DISCRIMINATOR"
    ):
        decode_token_reserve_state(
            bytes(bad_discriminator),
            owner=JUPITER_LEND_LIQUIDITY_PROGRAM_ID,
            address=fixture.reserve_pda,
        )


def test_financing_admission_is_typed_blocked_with_unknown_liquidity(
    fixture: Fixture,
) -> None:
    accounts = _bound_accounts(fixture)
    admin = decode_flashloan_admin_state(
        _admin_bytes(
            authority=_pk(11),
            liquidity_program=JUPITER_LEND_LIQUIDITY_PROGRAM_ID,
        )
    )
    admission = admit_reserve_financing_snapshot(
        observation=fixture.observation,
        accounts=accounts,
        admin_state=admin,
        asset_id="synthetic:offline-fixture-asset",
        state_fingerprint=("c" * 64),
    )
    # Admin enabled + fee 0 is NOT capacity: admission stays blocked and the
    # liquidity amount is unknown (None), never fabricated zero.
    assert admission.snapshot is None
    assert admission.available_liquidity_base_units is None
    assert set(admission.blockers) == {
        "MISSING_EFFECTIVE_FLASH_CAP",
        "LIVE_ROOTED_RPC_NOT_AUTHORIZED",
    }
    assert admission.observation_digest == fixture.observation.evidence_digest


def test_financing_admission_adds_resource_binding_negatives(
    fixture: Fixture,
) -> None:
    accounts = _bound_accounts(fixture)
    admin = decode_flashloan_admin_state(
        _admin_bytes(authority=_pk(11), liquidity_program=JUPITER_LEND_LIQUIDITY_PROGRAM_ID)
    )
    wrong_mint = replace(accounts, mint=_pk(31))
    drifted = admit_reserve_financing_snapshot(
        observation=fixture.observation,
        accounts=wrong_mint,
        admin_state=admin,
        asset_id="synthetic:offline-fixture-asset",
        state_fingerprint=("c" * 64),
    )
    assert "R02CAPA_FINANCING_MINT_BINDING_MISMATCH" in drifted.blockers
    assert drifted.snapshot is None

    wrong_reserve = replace(
        accounts, flashloan_token_reserves_liquidity=_pk(32)
    )
    drifted = admit_reserve_financing_snapshot(
        observation=fixture.observation,
        accounts=wrong_reserve,
        admin_state=admin,
        asset_id="synthetic:offline-fixture-asset",
        state_fingerprint=("c" * 64),
    )
    assert "R02CAPA_FINANCING_RESERVE_BINDING_MISMATCH" in drifted.blockers

    wrong_vault = replace(accounts, vault=_pk(33))
    drifted = admit_reserve_financing_snapshot(
        observation=fixture.observation,
        accounts=wrong_vault,
        admin_state=admin,
        asset_id="synthetic:offline-fixture-asset",
        state_fingerprint=("c" * 64),
    )
    assert "R02CAPA_FINANCING_VAULT_BINDING_MISMATCH" in drifted.blockers

    wrong_program = replace(accounts, liquidity_program=_pk(34))
    drifted = admit_reserve_financing_snapshot(
        observation=fixture.observation,
        accounts=wrong_program,
        admin_state=admin,
        asset_id="synthetic:offline-fixture-asset",
        state_fingerprint=("c" * 64),
    )
    assert "R02CAPA_FINANCING_LIQUIDITY_PROGRAM_MISMATCH" in drifted.blockers


def test_admin_fee_zero_is_still_not_capacity_proof(fixture: Fixture) -> None:
    """The #585 historical blocker: enabled admin with fee 0 is not reserve capacity."""

    accounts = _bound_accounts(fixture)
    paused = decode_flashloan_admin_state(
        _admin_bytes(authority=_pk(11), liquidity_program=JUPITER_LEND_LIQUIDITY_PROGRAM_ID, status=False)
    )
    admission = admit_reserve_financing_snapshot(
        observation=fixture.observation,
        accounts=accounts,
        admin_state=paused,
        asset_id="synthetic:offline-fixture-asset",
        state_fingerprint=("c" * 64),
    )
    assert "JUPITER_LEND_PROTOCOL_PAUSED" in admission.blockers
    assert "MISSING_EFFECTIVE_FLASH_CAP" in admission.blockers
    assert admission.snapshot is None

    nonzero_fee = decode_flashloan_admin_state(
        _admin_bytes(authority=_pk(11), liquidity_program=JUPITER_LEND_LIQUIDITY_PROGRAM_ID, fee=5)
    )
    admission = admit_reserve_financing_snapshot(
        observation=fixture.observation,
        accounts=accounts,
        admin_state=nonzero_fee,
        asset_id="synthetic:offline-fixture-asset",
        state_fingerprint=("c" * 64),
    )
    assert "JUPITER_LEND_NONZERO_FEE_UNQUALIFIED" in admission.blockers
    assert "MISSING_EFFECTIVE_FLASH_CAP" in admission.blockers

    active = decode_flashloan_admin_state(
        _admin_bytes(
            authority=_pk(11),
            liquidity_program=JUPITER_LEND_LIQUIDITY_PROGRAM_ID,
            active=True,
            active_amount=7,
        )
    )
    admission = admit_reserve_financing_snapshot(
        observation=fixture.observation,
        accounts=accounts,
        admin_state=active,
        asset_id="synthetic:offline-fixture-asset",
        state_fingerprint=("c" * 64),
    )
    assert "JUPITER_LEND_FLASHLOAN_ALREADY_ACTIVE" in admission.blockers
    assert "JUPITER_LEND_ACTIVE_AMOUNT_NOT_ZERO" in admission.blockers
    assert admission.snapshot is None


def test_capital_edge_gate_never_emits_offline(fixture: Fixture) -> None:
    gate = reserve_capital_edge_gate(fixture.observation)
    assert gate.edge is None
    assert gate.blocker == "LIVE_ROOTED_RPC_NOT_AUTHORIZED"
    assert gate.note
    assert set(gate.blockers) == {
        "MISSING_EFFECTIVE_FLASH_CAP",
        "LIVE_ROOTED_RPC_NOT_AUTHORIZED",
    }


def test_rooted_slot_claim_without_capacity_still_blocked(fixture: Fixture) -> None:
    # Even a claimed rooted slot cannot pass: capacity remains unknown.
    rooted_claim = replace(
        fixture.observation,
        slot=454_401_539,
        slot_rooted=True,
        slot_provenance="LIVE_ROOTED_RPC",
        blockers=("MISSING_EFFECTIVE_FLASH_CAP",),
    )
    assert rooted_claim.slot_rooted is True
    assert rooted_claim.status == "BLOCKED_LIVE_STATE"
    gate = reserve_capital_edge_gate(rooted_claim)
    assert gate.edge is None
    assert gate.blocker == "MISSING_EFFECTIVE_FLASH_CAP"


def test_flash_capital_graph_whitelist_still_frozen_for_jupiter(
    fixture: Fixture,
) -> None:
    evidence = Evidence(
        source="offline-fixture",
        provider="jupiter-lend",
        correlation_group="r02-cap-a",
        generation="offline-fixture",
        observed_at=1000.0,
        response_hash=("a" * 64),
        request_hash=("b" * 64),
        slot_or_checkpoint=454_401_539,
    )
    with pytest.raises(ValueError, match="unqualified capital provider"):
        FlashCapitalEdge(
            chain="solana",
            provider="jupiter-lend",
            asset_id="synthetic-offline-asset",
            canonical_identifier=str(fixture.mint),
            resource_id=str(fixture.reserve_pda),
            max_amount_live=1,
            fee_numerator=0,
            fee_denominator=1,
            protocol_rounding=0,
            atomicity_class="LOCAL_ATOMIC_CANDIDATE",
            constraints=(),
            evidence=evidence,
            evidence_refs=("offline-fixture-ref",),
        )


def test_wrong_pda_seed_is_rejected(fixture: Fixture) -> None:
    wrong_seed_pda, _ = Pubkey.find_program_address(
        [b"reservX", bytes(fixture.mint)],
        JUPITER_LEND_LIQUIDITY_PROGRAM_ID,
    )
    assert wrong_seed_pda != fixture.reserve_pda
    with pytest.raises(
        JupiterLendAdapterError, match="R02CAPA_TOKEN_RESERVE_PDA_MISMATCH"
    ):
        decode_token_reserve_state(
            fixture.reserve_bytes,
            owner=JUPITER_LEND_LIQUIDITY_PROGRAM_ID,
            address=wrong_seed_pda,
        )


def test_bad_discriminator_truncated_and_unknown_field_fail_closed(
    fixture: Fixture,
) -> None:
    truncated = fixture.reserve_bytes[:-1]
    with pytest.raises(
        JupiterLendAdapterError, match="R02CAPA_TOKEN_RESERVE_LAYOUT_MISMATCH"
    ):
        decode_token_reserve_state(
            truncated,
            owner=JUPITER_LEND_LIQUIDITY_PROGRAM_ID,
            address=fixture.reserve_pda,
        )
    extended = fixture.reserve_bytes + b"\x00"
    with pytest.raises(
        JupiterLendAdapterError, match="R02CAPA_TOKEN_RESERVE_UNKNOWN_FIELD"
    ):
        decode_token_reserve_state(
            extended,
            owner=JUPITER_LEND_LIQUIDITY_PROGRAM_ID,
            address=fixture.reserve_pda,
        )
    bad_discriminator = bytearray(fixture.reserve_bytes)
    bad_discriminator[7] ^= 0xFF
    with pytest.raises(
        JupiterLendAdapterError, match="R02CAPA_TOKEN_RESERVE_UNKNOWN_DISCRIMINATOR"
    ):
        decode_token_reserve_state(
            bytes(bad_discriminator),
            owner=JUPITER_LEND_LIQUIDITY_PROGRAM_ID,
            address=fixture.reserve_pda,
        )


def test_wrong_owner_fails_closed(fixture: Fixture) -> None:
    with pytest.raises(
        JupiterLendAdapterError, match="R02CAPA_TOKEN_RESERVE_OWNER_MISMATCH"
    ):
        decode_token_reserve_state(
            fixture.reserve_bytes,
            owner=SYSTEM_PROGRAM_ID,
            address=fixture.reserve_pda,
        )


def test_vault_binding_negatives_fail_closed(fixture: Fixture) -> None:
    with pytest.raises(
        JupiterLendAdapterError, match="R02CAPA_VAULT_ADDRESS_BINDING_MISMATCH"
    ):
        observe_token_reserve_capacity(
            mint=fixture.mint,
            reserve_bytes=fixture.reserve_bytes,
            reserve_owner=JUPITER_LEND_LIQUIDITY_PROGRAM_ID,
            reserve_address=fixture.reserve_pda,
            vault_bytes=fixture.vault_bytes,
            vault_address=_pk(30),
            vault_owner_program=SPL_TOKEN_PROGRAM_ID,
        )
    with pytest.raises(
        JupiterLendAdapterError, match="R02CAPA_VAULT_MINT_BINDING_MISMATCH"
    ):
        decode_vault_token_account(
            _vault_bytes(_pk(12), fixture.reserve_pda, 5_000_000_000),
            address=fixture.vault,
            owner_program=SPL_TOKEN_PROGRAM_ID,
            expected_mint=fixture.mint,
        )
    with pytest.raises(
        JupiterLendAdapterError, match="R02CAPA_VAULT_TOKEN_ACCOUNT_LAYOUT_MISMATCH"
    ):
        decode_vault_token_account(
            fixture.vault_bytes[:-1],
            address=fixture.vault,
            owner_program=SPL_TOKEN_PROGRAM_ID,
            expected_mint=fixture.mint,
        )
    with pytest.raises(
        JupiterLendAdapterError, match="R02CAPA_VAULT_TOKEN_PROGRAM_MISMATCH"
    ):
        decode_vault_token_account(
            fixture.vault_bytes,
            address=fixture.vault,
            owner_program=SYSTEM_PROGRAM_ID,
            expected_mint=fixture.mint,
        )
    with pytest.raises(JupiterLendAdapterError, match="R02CAPA_VAULT_FROZEN"):
        decode_vault_token_account(
            _vault_bytes(
                fixture.mint, fixture.reserve_pda, 5_000_000_000, account_state=2
            ),
            address=fixture.vault,
            owner_program=SPL_TOKEN_PROGRAM_ID,
            expected_mint=fixture.mint,
        )
    with pytest.raises(
        JupiterLendAdapterError, match="R02CAPA_CAPACITY_STATE_INVALID"
    ):
        decode_vault_token_account(
            _vault_bytes(fixture.mint, fixture.reserve_pda, 5_000_000_000, account_state=0),
            address=fixture.vault,
            owner_program=SPL_TOKEN_PROGRAM_ID,
            expected_mint=fixture.mint,
        )
    with pytest.raises(
        JupiterLendAdapterError, match="R02CAPA_VAULT_DELEGATE_UNPROVEN"
    ):
        decode_vault_token_account(
            _vault_bytes(fixture.mint, fixture.reserve_pda, 5_000_000_000, delegate=True),
            address=fixture.vault,
            owner_program=SPL_TOKEN_PROGRAM_ID,
            expected_mint=fixture.mint,
        )
    with pytest.raises(
        JupiterLendAdapterError, match="R02CAPA_VAULT_CLOSE_AUTHORITY_UNPROVEN"
    ):
        decode_vault_token_account(
            _vault_bytes(
                fixture.mint, fixture.reserve_pda, 5_000_000_000, close_authority=True
            ),
            address=fixture.vault,
            owner_program=SPL_TOKEN_PROGRAM_ID,
            expected_mint=fixture.mint,
        )


def test_reserve_mint_binding_mismatch_fails_closed(fixture: Fixture) -> None:
    reviewed_mint = _pk(40)
    with pytest.raises(
        JupiterLendAdapterError, match="R02CAPA_TOKEN_RESERVE_MINT_BINDING_MISMATCH"
    ):
        observe_token_reserve_capacity(
            mint=reviewed_mint,
            reserve_bytes=fixture.reserve_bytes,
            reserve_owner=JUPITER_LEND_LIQUIDITY_PROGRAM_ID,
            reserve_address=fixture.reserve_pda,
            vault_bytes=fixture.vault_bytes,
            vault_address=fixture.vault,
            vault_owner_program=SPL_TOKEN_PROGRAM_ID,
        )


def test_interacting_state_fail_closed(fixture: Fixture) -> None:
    values = _default_reserve_values(fixture.mint, fixture.vault)
    interacting = _pk(41)
    values["interacting_protocol"] = bytes(interacting)
    values["interacting_timestamp"] = (1_764_000_100).to_bytes(8, "little")
    values["interacting_balance"] = (123).to_bytes(8, "little")
    obs = observe_token_reserve_capacity(
        mint=fixture.mint,
        reserve_bytes=_reserve_bytes(values),
        reserve_owner=JUPITER_LEND_LIQUIDITY_PROGRAM_ID,
        reserve_address=fixture.reserve_pda,
        vault_bytes=fixture.vault_bytes,
        vault_address=fixture.vault,
        vault_owner_program=SPL_TOKEN_PROGRAM_ID,
    )
    assert "R02CAPA_RESERVE_INTERACTING_STATE_SET" in obs.constraint_gaps
    assert obs.status == "BLOCKED_LIVE_STATE"

    inconsistent = dict(values)
    inconsistent["interacting_timestamp"] = (0).to_bytes(8, "little")
    inconsistent["interacting_balance"] = (0).to_bytes(8, "little")
    with pytest.raises(
        JupiterLendAdapterError, match="R02CAPA_CAPACITY_STATE_INVALID"
    ):
        observe_token_reserve_capacity(
            mint=fixture.mint,
            reserve_bytes=_reserve_bytes(inconsistent),
            reserve_owner=JUPITER_LEND_LIQUIDITY_PROGRAM_ID,
            reserve_address=fixture.reserve_pda,
            vault_bytes=fixture.vault_bytes,
            vault_address=fixture.vault,
            vault_owner_program=SPL_TOKEN_PROGRAM_ID,
        )

    orphan_state = _default_reserve_values(fixture.mint, fixture.vault)
    orphan_state["interacting_balance"] = (5).to_bytes(8, "little")
    with pytest.raises(
        JupiterLendAdapterError, match="R02CAPA_CAPACITY_STATE_INVALID"
    ):
        observe_token_reserve_capacity(
            mint=fixture.mint,
            reserve_bytes=_reserve_bytes(orphan_state),
            reserve_owner=JUPITER_LEND_LIQUIDITY_PROGRAM_ID,
            reserve_address=fixture.reserve_pda,
            vault_bytes=fixture.vault_bytes,
            vault_address=fixture.vault,
            vault_owner_program=SPL_TOKEN_PROGRAM_ID,
        )


def test_effective_capacity_cannot_be_fabricated(fixture: Fixture) -> None:
    obs = fixture.observation
    with pytest.raises(ValueError, match="unknown is not zero"):
        replace(obs, effective_capacity_base_units=100)
    with pytest.raises(ValueError, match="MISSING_EFFECTIVE_FLASH_CAP"):
        replace(obs, blockers=("LIVE_ROOTED_RPC_NOT_AUTHORIZED",))
    with pytest.raises(ValueError, match="constraint gaps"):
        replace(obs, constraint_gaps=())
    with pytest.raises(ValueError, match="cannot claim a slot"):
        replace(obs, slot=454_401_539)
    with pytest.raises(ValueError, match="rooted observation requires"):
        replace(obs, slot_rooted=True, slot_provenance="LIVE_ROOTED_RPC")


def _bound_accounts(fixture: Fixture) -> JupiterLendFlashloanAccounts:
    return JupiterLendFlashloanAccounts(
        signer=_pk(1),
        flashloan_admin=JUPITER_FLASHLOAN_ADMIN_PDA,
        signer_borrow_token_account=_pk(2),
        mint=fixture.mint,
        flashloan_token_reserves_liquidity=fixture.reserve_pda,
        flashloan_borrow_position_on_liquidity=_pk(5),
        rate_model=_pk(6),
        vault=fixture.vault,
        liquidity=_pk(8),
        liquidity_program=JUPITER_LEND_LIQUIDITY_PROGRAM_ID,
        token_program=SPL_TOKEN_PROGRAM_ID,
    )
