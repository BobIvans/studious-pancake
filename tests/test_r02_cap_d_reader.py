"""R02-CAP-D: wallet-free Project 0 (MarginFi) bank reader tests.

Offline only: fixture account bytes are synthetic, built schema-driven from the
pinned PR-028 binary layout (src/resources/marginfi_pr028.json) and the pinned
PR-055 main-group pin. No network, no live captures, no signing, no account
creation. Unknown is not zero: every unproven constraint surfaces as typed
evidence and effective capacity is never fabricated.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest
from solders.pubkey import Pubkey

from src.economics.flash_capital_graph.graph import FlashCapitalEdge
from src.assets.resolution.evidence import Evidence
from src.providers.marginfi.accounts import RpcAccount
from src.providers.marginfi.bank_discovery import (
    BANK_TOKEN_2022_FLAG,
    BLOCKER_FINANCING_PORT_NOT_PRESCRIBED,
    BLOCKER_GROUP_PAUSED,
    BLOCKER_LIVE_ENUMERATION_NOT_AUTHORIZED,
    BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED,
    BLOCKER_MISSING_EFFECTIVE_FLASH_CAP,
    BLOCKER_OPERATOR_ACCOUNT_INPUT_REQUIRED,
    FEE_ROUNDING_RULE,
    GAP_ACCOUNT_PDA_SEED_UNPINNED,
    GAP_ASSET_SHARE_VALUE_UNPINNED,
    GAP_BANK_PDA_SEED_UNPINNED,
    GAP_EMISSIONS_UNPINNED,
    GAP_GROUP_PAUSE_UNPROVEN,
    GAP_LAST_UPDATE_UNPINNED,
    GAP_LIABILITY_SHARE_VALUE_UNPINNED,
    GAP_LIQUIDITY_SHARES_UNPINNED,
    GAP_ORACLE_PRICE_UNPROVEN,
    LIQUIDITY_VAULT_AUTHORITY_SEED,
    READER_CAPACITY_DERIVATION_UNPROVEN,
    READER_DECODER_GENERATION,
    READER_DECODER_IDENTITY,
    READER_EXECUTION_AUTHORITY,
    READER_WALLETLESS_MODE,
    MarginfiBankDiscoveryError,
    MarginfiBankDiscoveryRejectionCode,
    MarginfiCapture,
    admit_bank_financing_snapshot,
    bank_capital_edge_gate,
    compute_origination_fee,
    compute_share_valuation,
    decode_bank_capture,
    derive_bank_liquidity_vault_authority,
    discover_banks,
    evaluate_existing_account_eligibility,
    load_bank_reader_pins,
    observe_bank_capacity,
    plan_live_bank_enumeration,
)
from src.providers.marginfi.errors import MarginfiRejection, MarginfiRejectionCode
from src.providers.marginfi.layouts import decode_group

REPO_ROOT = Path(__file__).resolve().parents[1]
PR028_PIN = REPO_ROOT / "src/resources/marginfi_pr028.json"
MAIN_GROUP = "4qp6Fx6tnZkY5Wropq9wUYgtFxXKwE6viZxFHg3rdAG8"
PROGRAM_ID = "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"


def _pk(seed: int) -> Pubkey:
    return Pubkey.from_bytes(bytes((seed,)) * 32)


def _pinned_bank_layout() -> dict:
    raw = json.loads(PR028_PIN.read_text(encoding="utf-8"))
    return raw["account_layouts"]["bank"]


def _bank_bytes(values: dict[str, bytes]) -> bytes:
    """Build bank account bytes schema-driven from the pinned PR-028 layout.

    Pinned offsets are struct-body offsets, so every write is shifted by the
    8-byte Anchor discriminator prefix.
    """

    layout = _pinned_bank_layout()
    raw = bytearray(8 + layout["struct_size"])
    raw[:8] = bytes.fromhex(layout["discriminator_hex"])
    offsets = layout["offsets"]
    base = 8

    def _chunk(name: str, size: int) -> slice:
        return slice(base + offsets[name], base + offsets[name] + size)

    raw[_chunk("mint", 32)] = values["mint"]
    raw[base + offsets["mint_decimals"]] = values["mint_decimals"][0]
    raw[_chunk("group", 32)] = values["group"]
    raw[_chunk("liquidity_vault", 32)] = values["liquidity_vault"]
    raw[_chunk("protocol_origination_fee", 16)] = values["protocol_origination_fee"]
    raw[base + offsets["operational_state"]] = values["operational_state"][0]
    raw[base + offsets["oracle_setup"]] = values["oracle_setup"][0]
    raw[_chunk("oracle_keys", 32)] = values["oracle_keys"]
    raw[_chunk("borrow_limit", 8)] = values["borrow_limit"]
    raw[base + offsets["risk_tier"]] = values["risk_tier"][0]
    raw[base + offsets["asset_tag"]] = values["asset_tag"][0]
    raw[_chunk("flags", 8)] = values["flags"]
    return bytes(raw)


def _default_bank_values(mint: Pubkey, vault: Pubkey) -> dict[str, bytes]:
    """Synthetic resource values; identities are NOT reviewed mainnet state."""

    group = Pubkey.from_string(MAIN_GROUP)
    return {
        "mint": bytes(mint),
        "mint_decimals": bytes((6,)),
        "group": bytes(group),
        "liquidity_vault": bytes(vault),
        "protocol_origination_fee": (1 << 46).to_bytes(16, "little"),
        "operational_state": bytes((1,)),
        "oracle_setup": bytes((3,)),
        "oracle_keys": bytes(_pk(21)),
        "borrow_limit": (10_000_000).to_bytes(8, "little"),
        "risk_tier": bytes((0,)),
        "asset_tag": bytes((0,)),
        "flags": (0).to_bytes(8, "little"),
    }


def _vault_bytes(mint: Pubkey, authority: Pubkey, amount: int) -> bytes:
    raw = bytearray(165)
    raw[0:32] = bytes(mint)
    raw[32:64] = bytes(authority)
    raw[64:72] = amount.to_bytes(8, "little")
    raw[108] = 1  # initialized, not frozen
    return bytes(raw)


def _group_bytes(
    *,
    admin: Pubkey,
    paused: bool = False,
    pause_start: int = 0,
    cache_updated: int = 0,
) -> bytes:
    raw_pin = json.loads(PR028_PIN.read_text(encoding="utf-8"))
    layout = raw_pin["account_layouts"]["marginfi_group"]
    offsets = layout["offsets"]
    base = 8
    raw = bytearray(base + layout["struct_size"])
    raw[:8] = bytes.fromhex(layout["discriminator_hex"])
    raw[base + offsets["admin"] : base + offsets["admin"] + 32] = bytes(admin)
    if paused:
        raw[base + offsets["panic_pause_flags"]] = 1
        start = base + offsets["panic_pause_start_timestamp"]
        raw[start : start + 8] = pause_start.to_bytes(8, "little", signed=True)
        cache = base + offsets["panic_last_cache_update"]
        raw[cache : cache + 8] = cache_updated.to_bytes(8, "little", signed=True)
    return bytes(raw)


class Fixture:
    def __init__(self) -> None:
        self.pins = load_bank_reader_pins()
        self.mint = _pk(3)
        self.bank = _pk(2)
        self.vault = _pk(9)
        self.bank_values = _default_bank_values(self.mint, self.vault)
        self.bank_bytes = _bank_bytes(self.bank_values)
        self.vault_authority, _ = Pubkey.find_program_address(
            [LIQUIDITY_VAULT_AUTHORITY_SEED, bytes(self.bank)],
            Pubkey.from_string(PROGRAM_ID),
        )
        self.vault_bytes = _vault_bytes(self.mint, self.vault_authority, 5_000_000)
        self.group_bytes = _group_bytes(admin=_pk(5))
        self.bank_capture = MarginfiCapture(
            address=str(self.bank), owner=PROGRAM_ID, data=self.bank_bytes
        )
        self.vault_capture = MarginfiCapture(
            address=str(self.vault),
            owner=self.pins.contract_pin.raw["programs"]["token"],
            data=self.vault_bytes,
        )
        self.group_capture = MarginfiCapture(
            address=MAIN_GROUP, owner=PROGRAM_ID, data=self.group_bytes
        )
        self.observation = observe_bank_capacity(
            self.pins,
            self.bank_capture,
            self.vault_capture,
        )


@pytest.fixture(scope="module")
def fixture() -> Fixture:
    return Fixture()


def test_reader_pins_program_group_and_p0_facts(fixture: Fixture) -> None:
    assert fixture.pins.program_id == PROGRAM_ID
    assert fixture.pins.main_group == MAIN_GROUP
    assert fixture.pins.contract_pin.source_commit == (
        "d4c70c84f8a9692405a2c32cbd7095bb1fe3f428"
    )
    facts = fixture.pins.facts
    assert (
        facts.source_pin == "0dotxyz/p0-ts-sdk@8a8353bb662459e5957b0cbbd2121f4fddb37fc3"
    )
    assert facts.source_git_version == "2.10.0"
    assert facts.bank_only_reads_allowed is True
    assert facts.status_without_public_wallet == (
        "P0_EXISTING_ACCOUNT_UNKNOWN_READ_BANKS_ONLY"
    )
    for method in ("createMarginfiAccountTx", "sendTransaction", "signTransaction"):
        assert method in facts.forbidden
    assert facts.execution_authority == "NONE"
    assert READER_EXECUTION_AUTHORITY == "NONE"
    assert READER_DECODER_IDENTITY == "project0.bank.capacity-reader.v1"
    assert READER_DECODER_GENERATION == 1
    assert READER_WALLETLESS_MODE == "WALLETLESS_BANK_DISCOVERY_ONLY"


def test_bank_liquidity_vault_authority_uses_pinned_seed(fixture: Fixture) -> None:
    derived, bump = Pubkey.find_program_address(
        [LIQUIDITY_VAULT_AUTHORITY_SEED, bytes(fixture.bank)],
        Pubkey.from_string(PROGRAM_ID),
    )
    assert fixture.vault_authority == derived
    assert derive_bank_liquidity_vault_authority(fixture.pins, fixture.bank) == (
        derived,
        bump,
    )
    wrong_seed_pda, _ = Pubkey.find_program_address(
        [b"liquidity_vault_autX", bytes(fixture.bank)],
        Pubkey.from_string(PROGRAM_ID),
    )
    assert wrong_seed_pda != derived
    with pytest.raises(
        MarginfiBankDiscoveryError,
        match="R02CAPD_CAPTURE_STATE_INVALID",
    ):
        derive_bank_liquidity_vault_authority(
            fixture.pins, Pubkey.from_bytes(bytes(32))
        )


def test_bank_capture_decode_roundtrips_pinned_layout(fixture: Fixture) -> None:
    decoded = decode_bank_capture(fixture.pins, fixture.bank_capture)
    values = fixture.bank_values
    assert decoded.mint == str(fixture.mint)
    assert decoded.mint_decimals == 6
    assert decoded.group == MAIN_GROUP
    assert decoded.liquidity_vault == str(fixture.vault)
    assert decoded.origination_fee_raw_i80f48 == 1 << 46
    assert decoded.operational_state == 1
    assert decoded.oracle_setup == 3
    assert decoded.oracle_keys == (str(_pk(21)),)
    assert decoded.borrow_limit == 10_000_000
    assert decoded.asset_tag == 0
    assert decoded.flags == 0
    assert decoded.token_program == (fixture.pins.contract_pin.raw["programs"]["token"])
    # token_2022 flag must select the pinned token-2022 program when set.
    token_2022_values = dict(values)
    token_2022_values["flags"] = (BANK_TOKEN_2022_FLAG).to_bytes(8, "little")
    token_2022_bytes = _bank_bytes(token_2022_values)
    decoded_2022 = decode_bank_capture(
        fixture.pins,
        MarginfiCapture(address=str(_pk(12)), owner=PROGRAM_ID, data=token_2022_bytes),
    )
    assert decoded_2022.token_program == (
        fixture.pins.contract_pin.raw["programs"]["token_2022"]
    )


def test_capacity_observation_reports_resource_state_without_effective_cap(
    fixture: Fixture,
) -> None:
    obs = fixture.observation
    # Raw resource state is proven from decoded pinned-layout bytes only.
    assert obs.raw_vault_amount_base_units == 5_000_000
    assert obs.raw_borrow_limit == 10_000_000
    assert obs.origination_fee_raw_i80f48 == 1 << 46
    assert obs.fee_rounding == FEE_ROUNDING_RULE
    assert obs.bank == str(_pk(2))
    assert obs.group == MAIN_GROUP
    assert obs.mint == str(fixture.mint)
    assert obs.mint_decimals == 6
    assert obs.token_program == fixture.pins.contract_pin.raw["programs"]["token"]
    assert obs.liquidity_vault == str(fixture.vault)
    assert obs.liquidity_vault_authority == str(fixture.vault_authority)
    assert obs.oracle_setup == 3
    assert obs.oracle_keys == (str(_pk(21)),)
    assert obs.operational is True
    assert obs.bank_data_sha256 == hashlib.sha256(fixture.bank_bytes).hexdigest()
    assert obs.vault_data_sha256 == hashlib.sha256(fixture.vault_bytes).hexdigest()
    assert obs.group_data_sha256 is None
    # Unknown is not zero: effective capacity and share fields stay unknown.
    assert obs.effective_capacity_base_units is None
    assert obs.raw_asset_share_value_i80f48 is None
    assert obs.raw_liability_share_value_i80f48 is None
    assert obs.raw_liquidity_shares_i80f48 is None
    assert obs.raw_liability_shares_i80f48 is None
    assert obs.capacity_derivation == READER_CAPACITY_DERIVATION_UNPROVEN
    assert set(obs.blockers) == {
        BLOCKER_MISSING_EFFECTIVE_FLASH_CAP,
        BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED,
    }
    for gap in (
        GAP_BANK_PDA_SEED_UNPINNED,
        GAP_ACCOUNT_PDA_SEED_UNPINNED,
        GAP_ASSET_SHARE_VALUE_UNPINNED,
        GAP_LIABILITY_SHARE_VALUE_UNPINNED,
        GAP_LIQUIDITY_SHARES_UNPINNED,
        GAP_LAST_UPDATE_UNPINNED,
        GAP_EMISSIONS_UNPINNED,
        GAP_ORACLE_PRICE_UNPROVEN,
        GAP_GROUP_PAUSE_UNPROVEN,
    ):
        assert gap in obs.constraint_gaps
    assert obs.status == "BLOCKED_LIVE_STATE"
    assert obs.slot is None
    assert obs.slot_rooted is False
    assert obs.slot_provenance == "OFFLINE_FIXTURE_NOT_ROOTED"
    assert obs.execution_authority == "NONE"
    assert obs.sign_enabled is False
    assert obs.send_enabled is False
    assert obs.account_creation_attempted is False


def test_origination_fee_uses_exact_dpr_ceil_rounding() -> None:
    # fee_raw = 0.25 in i80F48 -> exact and ceil cases at scale 2^48.
    assert compute_origination_fee(400, 1 << 46) == 100
    assert compute_origination_fee(401, 1 << 46) == 101
    assert compute_origination_fee(0, 1 << 46) == 0
    assert compute_origination_fee(1, 0) == 0
    with pytest.raises(MarginfiRejection) as negative_amount:
        compute_origination_fee(-1, 1 << 46)
    assert negative_amount.value.code == MarginfiRejectionCode.UNPROVEN_FEE
    with pytest.raises(MarginfiRejection) as negative_fee:
        compute_origination_fee(10, -(1 << 46))
    assert negative_fee.value.code == MarginfiRejectionCode.UNPROVEN_FEE


def test_share_valuation_math_is_exact_and_fail_closed() -> None:
    # shares_raw = 3.0 i80F48, share_value_raw = 1.0 i80F48 -> exactly 3 tokens.
    exact = compute_share_valuation(
        asset_shares_raw=3 << 48,
        asset_share_value_raw=1 << 48,
        liability_shares_raw=2 << 48,
        liability_share_value_raw=1 << 48,
    )
    assert exact.raw_asset_total == 3
    assert exact.raw_liability_total == 2
    # Assets floor: fractional token part is floored, never rounded up.
    floored = compute_share_valuation(
        asset_shares_raw=3 << 48,
        asset_share_value_raw=(1 << 48) + (1 << 47),  # 1.5
        liability_shares_raw=1 << 48,
        liability_share_value_raw=1 << 48,
    )
    assert floored.raw_asset_total == 4  # 3 * 1.5 = 4.5 -> floor 4
    # Liabilities ceil: fractional debt part ceils, never rounded down.
    ceiled = compute_share_valuation(
        asset_shares_raw=1 << 48,
        asset_share_value_raw=1 << 48,
        liability_shares_raw=1 << 48,
        liability_share_value_raw=(1 << 48) + (1 << 24),
    )
    assert ceiled.raw_liability_total == 2  # 1.0000000149 -> ceil 2
    for kwargs in (
        {
            "asset_shares_raw": -1,
            "asset_share_value_raw": 1 << 48,
            "liability_shares_raw": 1 << 48,
            "liability_share_value_raw": 1 << 48,
        },
        {
            "asset_shares_raw": 1 << 48,
            "asset_share_value_raw": 1 << 48,
            "liability_shares_raw": -1,
            "liability_share_value_raw": 1 << 48,
        },
        {
            "asset_shares_raw": 1 << 48,
            "asset_share_value_raw": -1,
            "liability_shares_raw": 1 << 48,
            "liability_share_value_raw": 1 << 48,
        },
    ):
        with pytest.raises(
            MarginfiBankDiscoveryError, match="R02CAPD_SHARE_MATH_INVALID"
        ):
            compute_share_valuation(**kwargs)


def test_group_pause_blocks_bank_capacity() -> None:
    pins = load_bank_reader_pins()
    mint, bank, vault = _pk(3), _pk(2), _pk(9)
    bank_capture = MarginfiCapture(
        address=str(bank),
        owner=PROGRAM_ID,
        data=_bank_bytes(_default_bank_values(mint, vault)),
    )
    authority, _ = Pubkey.find_program_address(
        [LIQUIDITY_VAULT_AUTHORITY_SEED, bytes(bank)],
        Pubkey.from_string(PROGRAM_ID),
    )
    vault_capture = MarginfiCapture(
        address=str(vault),
        owner=pins.contract_pin.raw["programs"]["token"],
        data=_vault_bytes(mint, authority, 1),
    )
    now = 1_764_000_000
    paused_capture = MarginfiCapture(
        address=MAIN_GROUP,
        owner=PROGRAM_ID,
        data=_group_bytes(
            admin=_pk(5),
            paused=True,
            pause_start=now - 100,
            cache_updated=now - 50,
        ),
    )
    paused = observe_bank_capacity(
        pins,
        bank_capture,
        vault_capture,
        group_capture=paused_capture,
        now_timestamp=now,
    )
    assert BLOCKER_GROUP_PAUSED in paused.blockers
    assert paused.status == "BLOCKED_LIVE_STATE"
    live_group = decode_group(
        RpcAccount(address=MAIN_GROUP, owner=PROGRAM_ID, data=paused_capture.data),
        pins.contract_pin,
        now_timestamp=now,
    )
    assert live_group.paused is True

    unpaused_capture = MarginfiCapture(
        address=MAIN_GROUP,
        owner=PROGRAM_ID,
        data=_group_bytes(admin=_pk(5)),
    )
    unpaused = observe_bank_capacity(
        pins,
        bank_capture,
        vault_capture,
        group_capture=unpaused_capture,
        now_timestamp=now,
    )
    assert BLOCKER_GROUP_PAUSED not in unpaused.blockers
    assert (
        unpaused.group_data_sha256 == hashlib.sha256(unpaused_capture.data).hexdigest()
    )

    # A group capture at an address other than the pinned main group fails.
    wrong_group = MarginfiCapture(
        address=str(_pk(30)),
        owner=PROGRAM_ID,
        data=_group_bytes(admin=_pk(5)),
    )
    with pytest.raises(
        MarginfiBankDiscoveryError, match="R02CAPD_CAPTURE_STATE_INVALID"
    ):
        observe_bank_capacity(
            pins,
            bank_capture,
            vault_capture,
            group_capture=wrong_group,
            now_timestamp=now,
        )


def test_group_capture_absent_records_pause_gap(fixture: Fixture) -> None:
    assert GAP_GROUP_PAUSE_UNPROVEN in fixture.observation.constraint_gaps
    assert fixture.observation.group_data_sha256 is None


def test_non_operational_bank_carries_typed_blocker() -> None:
    pins = load_bank_reader_pins()
    mint, bank, vault = _pk(3), _pk(2), _pk(9)
    values = _default_bank_values(mint, vault)
    values["operational_state"] = bytes((0,))
    bank_capture = MarginfiCapture(
        address=str(bank), owner=PROGRAM_ID, data=_bank_bytes(values)
    )
    authority, _ = Pubkey.find_program_address(
        [LIQUIDITY_VAULT_AUTHORITY_SEED, bytes(bank)],
        Pubkey.from_string(PROGRAM_ID),
    )
    vault_capture = MarginfiCapture(
        address=str(vault),
        owner=pins.contract_pin.raw["programs"]["token"],
        data=_vault_bytes(mint, authority, 7),
    )
    obs = observe_bank_capacity(pins, bank_capture, vault_capture)
    assert obs.operational is False
    assert "R02CAPD_BANK_NOT_OPERATIONAL" in obs.blockers
    assert BLOCKER_MISSING_EFFECTIVE_FLASH_CAP in obs.blockers


def test_bank_group_binding_negative() -> None:
    pins = load_bank_reader_pins()
    values = _default_bank_values(_pk(3), _pk(9))
    values["group"] = bytes(_pk(40))
    capture = MarginfiCapture(
        address=str(_pk(2)), owner=PROGRAM_ID, data=_bank_bytes(values)
    )
    with pytest.raises(
        MarginfiBankDiscoveryError, match="R02CAPD_BANK_GROUP_BINDING_MISMATCH"
    ):
        decode_bank_capture(pins, capture)


def test_bank_owner_mismatch_negative() -> None:
    pins = load_bank_reader_pins()
    capture = MarginfiCapture(
        address=str(_pk(2)),
        owner=str(_pk(41)),
        data=_bank_bytes(_default_bank_values(_pk(3), _pk(9))),
    )
    with pytest.raises(MarginfiBankDiscoveryError, match="R02CAPD_BANK_OWNER_MISMATCH"):
        decode_bank_capture(pins, capture)


def test_bank_discriminator_negative() -> None:
    pins = load_bank_reader_pins()
    raw = bytearray(_bank_bytes(_default_bank_values(_pk(3), _pk(9))))
    raw[0] ^= 0xFF
    capture = MarginfiCapture(address=str(_pk(2)), owner=PROGRAM_ID, data=bytes(raw))
    with pytest.raises(MarginfiRejection) as rejection:
        decode_bank_capture(pins, capture)
    assert rejection.value.code == MarginfiRejectionCode.DISCRIMINATOR_MISMATCH


def test_bank_truncated_and_overlong_layout_fail_closed() -> None:
    pins = load_bank_reader_pins()
    raw = _bank_bytes(_default_bank_values(_pk(3), _pk(9)))
    with pytest.raises(MarginfiRejection) as truncated:
        decode_bank_capture(
            pins,
            MarginfiCapture(address=str(_pk(2)), owner=PROGRAM_ID, data=raw[:-1]),
        )
    assert truncated.value.code == MarginfiRejectionCode.DATA_LENGTH_MISMATCH
    with pytest.raises(MarginfiRejection) as overlong:
        decode_bank_capture(
            pins,
            MarginfiCapture(address=str(_pk(2)), owner=PROGRAM_ID, data=raw + b"\x00"),
        )
    assert overlong.value.code == MarginfiRejectionCode.DATA_LENGTH_MISMATCH


def test_bank_oracle_nonconformance_negative() -> None:
    pins = load_bank_reader_pins()
    values = _default_bank_values(_pk(3), _pk(9))
    values["oracle_setup"] = bytes((7,))
    capture = MarginfiCapture(
        address=str(_pk(2)), owner=PROGRAM_ID, data=_bank_bytes(values)
    )
    with pytest.raises(MarginfiRejection) as rejection:
        decode_bank_capture(pins, capture)
    assert rejection.value.code == MarginfiRejectionCode.ORACLE_INVALID


def test_negative_fee_raw_fails_closed() -> None:
    pins = load_bank_reader_pins()
    values = _default_bank_values(_pk(3), _pk(9))
    values["protocol_origination_fee"] = (-(1 << 46)).to_bytes(
        16, "little", signed=True
    )
    capture = MarginfiCapture(
        address=str(_pk(2)), owner=PROGRAM_ID, data=_bank_bytes(values)
    )
    with pytest.raises(MarginfiRejection) as rejection:
        decode_bank_capture(pins, capture)
    assert rejection.value.code == MarginfiRejectionCode.UNPROVEN_FEE


def test_stale_capture_slot_coherence_negative(fixture: Fixture) -> None:
    stale_vault = replace(fixture.vault_capture, slot=90)
    fresh_bank = replace(fixture.bank_capture, slot=100)
    with pytest.raises(
        MarginfiBankDiscoveryError, match="R02CAPD_CAPTURE_SLOT_INCOHERENT"
    ):
        observe_bank_capacity(fixture.pins, fresh_bank, stale_vault)
    # A coherent declared slot is still NOT a rooted slot claim offline.
    coherent = observe_bank_capacity(
        fixture.pins,
        replace(fixture.bank_capture, slot=100),
        replace(fixture.vault_capture, slot=100),
    )
    assert coherent.slot is None
    assert coherent.slot_rooted is False
    assert coherent.slot_provenance == "OFFLINE_FIXTURE_NOT_ROOTED"


def test_discovery_requires_captures_and_rejects_duplicates(fixture: Fixture) -> None:
    with pytest.raises(
        MarginfiBankDiscoveryError, match="R02CAPD_CAPTURE_STATE_INVALID"
    ):
        discover_banks(fixture.pins, [], [])
    duplicate = replace(fixture.bank_capture, data=fixture.bank_bytes)
    with pytest.raises(
        MarginfiBankDiscoveryError, match="R02CAPD_CAPTURE_STATE_INVALID"
    ):
        discover_banks(
            fixture.pins,
            [fixture.bank_capture, duplicate],
            [fixture.vault_capture, fixture.vault_capture],
        )
    with pytest.raises(
        MarginfiBankDiscoveryError, match="R02CAPD_CAPTURE_STATE_INVALID"
    ):
        discover_banks(fixture.pins, [fixture.bank_capture], [])


def test_discovery_binds_vault_captures_by_decoded_bank_address(
    fixture: Fixture,
) -> None:
    # A vault capture at the wrong address is rejected before any decode.
    wrong_vault = replace(fixture.vault_capture, address=str(_pk(50)))
    with pytest.raises(
        MarginfiBankDiscoveryError,
        match="R02CAPD_VAULT_CAPTURE_ADDRESS_MISMATCH",
    ):
        discover_banks(fixture.pins, [fixture.bank_capture], [wrong_vault])


def test_vault_binding_negatives() -> None:
    pins = load_bank_reader_pins()
    mint, bank, vault = _pk(3), _pk(2), _pk(9)
    decoded = decode_bank_capture(
        pins,
        MarginfiCapture(
            address=str(bank),
            owner=PROGRAM_ID,
            data=_bank_bytes(_default_bank_values(mint, vault)),
        ),
    )
    # Vault authority that does not match the pinned-seed PDA fails closed.
    bad_authority = _vault_bytes(mint, _pk(60), 1)
    with pytest.raises(
        MarginfiBankDiscoveryError,
        match="R02CAPD_VAULT_AUTHORITY_BINDING_MISMATCH",
    ):
        observe_bank_capacity(
            pins,
            MarginfiCapture(
                address=str(bank),
                owner=PROGRAM_ID,
                data=_bank_bytes(_default_bank_values(mint, vault)),
            ),
            MarginfiCapture(
                address=str(vault),
                owner=pins.contract_pin.raw["programs"]["token"],
                data=bad_authority,
            ),
        )
    # Vault owned by a different token program fails closed.
    with pytest.raises(
        MarginfiBankDiscoveryError, match="R02CAPD_CAPTURE_STATE_INVALID"
    ):
        observe_bank_capacity(
            pins,
            MarginfiCapture(
                address=str(bank),
                owner=PROGRAM_ID,
                data=_bank_bytes(_default_bank_values(mint, vault)),
            ),
            MarginfiCapture(
                address=str(vault),
                owner=str(_pk(61)),
                data=_vault_bytes(mint, _pk(60), 1),
            ),
        )
    # Vault mint that differs from the bank mint fails closed.
    with pytest.raises(MarginfiRejection) as mint_mismatch:
        observe_bank_capacity(
            pins,
            MarginfiCapture(
                address=str(bank),
                owner=PROGRAM_ID,
                data=_bank_bytes(_default_bank_values(mint, vault)),
            ),
            MarginfiCapture(
                address=str(vault),
                owner=pins.contract_pin.raw["programs"]["token"],
                data=_vault_bytes(_pk(62), _pk(60), 1),
            ),
        )
    assert mint_mismatch.value.code == MarginfiRejectionCode.LIQUIDITY_VAULT_MISMATCH
    assert decoded is not None


def test_discovery_aggregates_multiple_banks() -> None:
    pins = load_bank_reader_pins()
    bank_one, bank_two = _pk(2), _pk(12)
    vault_one, vault_two = _pk(9), _pk(13)
    captures = []
    vaults = []
    for bank, vault in ((bank_one, vault_one), (bank_two, vault_two)):
        captures.append(
            MarginfiCapture(
                address=str(bank),
                owner=PROGRAM_ID,
                data=_bank_bytes(_default_bank_values(_pk(3), vault)),
            )
        )
        authority, _ = Pubkey.find_program_address(
            [LIQUIDITY_VAULT_AUTHORITY_SEED, bytes(bank)],
            Pubkey.from_string(PROGRAM_ID),
        )
        vaults.append(
            MarginfiCapture(
                address=str(vault),
                owner=pins.contract_pin.raw["programs"]["token"],
                data=_vault_bytes(_pk(3), authority, 42),
            )
        )
    discovery = discover_banks(pins, captures, vaults)
    assert discovery.mode == "WALLETLESS_BANK_DISCOVERY_ONLY"
    assert len(discovery.banks) == 2
    assert all(
        observation.raw_vault_amount_base_units == 42 for observation in discovery.banks
    )
    assert discovery.account_eligibility_status == (
        "P0_EXISTING_ACCOUNT_UNKNOWN_READ_BANKS_ONLY"
    )
    assert discovery.account_eligibility_blockers == (
        BLOCKER_OPERATOR_ACCOUNT_INPUT_REQUIRED,
    )
    assert BLOCKER_MISSING_EFFECTIVE_FLASH_CAP in discovery.blockers
    assert BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED in discovery.blockers
    assert discovery.evidence_record()["mode"] == "WALLETLESS_BANK_DISCOVERY_ONLY"


def test_unknown_is_not_zero_invariants(fixture: Fixture) -> None:
    with pytest.raises(ValueError, match="must stay unknown"):
        replace(fixture.observation, raw_asset_share_value_i80f48=1 << 48)
    with pytest.raises(ValueError, match="unknown is not zero"):
        replace(fixture.observation, effective_capacity_base_units=5_000_000)
    with pytest.raises(ValueError, match="execution authority"):
        replace(fixture.observation, execution_authority="SOME")
    with pytest.raises(ValueError, match="never sign"):
        replace(fixture.observation, sign_enabled=True)
    with pytest.raises(ValueError, match="account creation"):
        replace(fixture.observation, account_creation_attempted=True)
    with pytest.raises(ValueError, match="MISSING_EFFECTIVE_FLASH_CAP"):
        replace(fixture.observation, blockers=("OTHER",))


def test_evidence_digest_is_content_addressed(fixture: Fixture) -> None:
    rebuilt = observe_bank_capacity(
        fixture.pins, fixture.bank_capture, fixture.vault_capture
    )
    assert fixture.observation.evidence_digest == rebuilt.evidence_digest
    record = fixture.observation.evidence_record()
    assert record["evidence_sha256"] == fixture.observation.evidence_digest
    assert record["decoder_identity"] == READER_DECODER_IDENTITY
    mutated = bytearray(fixture.bank_bytes)
    borrow_offset = (
        8
        + json.loads(PR028_PIN.read_text(encoding="utf-8"))["account_layouts"]["bank"][
            "offsets"
        ]["borrow_limit"]
    )
    mutated[borrow_offset : borrow_offset + 1] = (99).to_bytes(1, "little")
    drifted = observe_bank_capacity(
        fixture.pins,
        MarginfiCapture(
            address=str(fixture.bank), owner=PROGRAM_ID, data=bytes(mutated)
        ),
        fixture.vault_capture,
    )
    assert drifted.evidence_digest != fixture.observation.evidence_digest
    assert drifted.raw_borrow_limit != fixture.observation.raw_borrow_limit


def test_account_eligibility_blocked_without_operator_input(fixture: Fixture) -> None:
    eligibility = evaluate_existing_account_eligibility(fixture.pins)
    assert eligibility.status == "BLOCKED_OPERATOR_ACCOUNT_INPUT_REQUIRED"
    assert eligibility.blockers == (BLOCKER_OPERATOR_ACCOUNT_INPUT_REQUIRED,)
    assert eligibility.walletless_status == (
        "P0_EXISTING_ACCOUNT_UNKNOWN_READ_BANKS_ONLY"
    )
    assert eligibility.account_creation_attempted is False
    assert eligibility.derived_pdas == ()
    assert any("createMarginfiAccountTx" in note for note in eligibility.notes)


def test_account_eligibility_with_operator_input_still_blocked(
    fixture: Fixture,
) -> None:
    eligibility = evaluate_existing_account_eligibility(
        fixture.pins, operator_authority=str(_pk(70))
    )
    assert eligibility.status == "BLOCKED_LIVE_STATE"
    assert BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED in eligibility.blockers
    assert GAP_ACCOUNT_PDA_SEED_UNPINNED in eligibility.blockers
    assert eligibility.account_creation_attempted is False
    assert eligibility.derived_pdas == ()
    with pytest.raises(MarginfiBankDiscoveryError, match="CAPTURE_STATE_INVALID"):
        evaluate_existing_account_eligibility(fixture.pins, operator_account="not-a-pk")


def test_live_enumeration_plan_is_typed_blocked(fixture: Fixture) -> None:
    plan = plan_live_bank_enumeration(fixture.pins)
    assert plan.performed is False
    assert plan.accounts_returned == ()
    assert BLOCKER_LIVE_ENUMERATION_NOT_AUTHORIZED in plan.blockers
    assert BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED in plan.blockers
    assert MAIN_GROUP in plan.method
    assert PROGRAM_ID in plan.method


def test_financing_admission_typed_blocked(fixture: Fixture) -> None:
    admission = admit_bank_financing_snapshot(
        observation=fixture.observation,
        asset_id="synthetic:offline-fixture-asset",
        state_fingerprint=("c" * 64),
    )
    assert admission.snapshot is None
    assert admission.available_liquidity_base_units is None
    assert admission.observation_digest == fixture.observation.evidence_digest
    assert BLOCKER_MISSING_EFFECTIVE_FLASH_CAP in admission.blockers
    assert BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED in admission.blockers
    assert BLOCKER_FINANCING_PORT_NOT_PRESCRIBED in admission.blockers


def test_capital_edge_gate_never_emits_offline(fixture: Fixture) -> None:
    gate = bank_capital_edge_gate(fixture.observation)
    assert gate.edge is None
    assert gate.blocker == BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED
    assert gate.note
    assert set(gate.blockers) == {
        BLOCKER_MISSING_EFFECTIVE_FLASH_CAP,
        BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED,
    }


def test_rooted_slot_claim_without_capacity_still_blocked(fixture: Fixture) -> None:
    rooted_claim = replace(
        fixture.observation,
        slot=454_401_539,
        slot_rooted=True,
        slot_provenance="LIVE_ROOTED_RPC",
        blockers=(BLOCKER_MISSING_EFFECTIVE_FLASH_CAP,),
    )
    assert rooted_claim.slot_rooted is True
    assert rooted_claim.status == "BLOCKED_LIVE_STATE"
    gate = bank_capital_edge_gate(rooted_claim)
    assert gate.edge is None
    assert gate.blocker == BLOCKER_MISSING_EFFECTIVE_FLASH_CAP


def test_forged_flash_capital_edge_still_fails_closed(fixture: Fixture) -> None:
    # graph.py is frozen and whitelists marginfi/project0, so a forged edge
    # would type-check; the graph itself still refuses fabricated provenance,
    # and the reader gate never constructs one.
    def evidence(**overrides: object) -> Evidence:
        base = dict(
            source="offline-fixture",
            provider="marginfi",
            correlation_group="r02-cap-d",
            generation="offline-fixture",
            observed_at=1000.0,
            response_hash=("a" * 64),
            request_hash=("b" * 64),
            slot_or_checkpoint=None,
            negative_reason=None,
        )
        base.update(overrides)
        return Evidence(**base)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="provenance required"):
        FlashCapitalEdge(
            chain="solana",
            provider="marginfi",
            asset_id="synthetic-offline-asset",
            canonical_identifier=str(fixture.mint),
            resource_id=str(fixture.bank),
            max_amount_live=1,
            fee_numerator=0,
            fee_denominator=1000,
            protocol_rounding=0,
            atomicity_class="LOCAL_ATOMIC_CANDIDATE",
            constraints=("offline-fixture",),
            evidence=evidence(),
            evidence_refs=("offline-fixture",),
        )
    with pytest.raises(ValueError, match="provenance required"):
        FlashCapitalEdge(
            chain="solana",
            provider="project0",
            asset_id="synthetic-offline-asset",
            canonical_identifier=str(fixture.mint),
            resource_id=str(fixture.bank),
            max_amount_live=1,
            fee_numerator=0,
            fee_denominator=1000,
            protocol_rounding=0,
            atomicity_class="LOCAL_ATOMIC_CANDIDATE",
            constraints=("offline-fixture",),
            evidence=evidence(
                slot_or_checkpoint=454_401_539,
                negative_reason=BLOCKER_MISSING_EFFECTIVE_FLASH_CAP,
            ),
            evidence_refs=("offline-fixture",),
        )
    # The reader-side gate remains the control point: edge is always None.
    assert bank_capital_edge_gate(fixture.observation).edge is None


def test_marginfi_rejection_code_alias_guard() -> None:
    assert MarginfiBankDiscoveryRejectionCode.BANK_OWNER_MISMATCH.value == (
        "R02CAPD_BANK_OWNER_MISMATCH"
    )
