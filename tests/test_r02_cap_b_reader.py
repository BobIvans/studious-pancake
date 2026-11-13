"""R02-CAP-B: read-only Kamino klend reserve capacity reader tests.

Offline only: fixture account bytes are synthetic, built schema-driven from
the pinned vendored klend-sdk 13.0.2 layouts (docs/roadmap/
r02-capacity-recovery-2026-10-08/offline/vendor/kamino/) and cross-checked
against offline/kamino_reserve_prefix_layout.json. No network, no live
captures, no signing, no Obligation. Unknown is not zero: every unproven
constraint must surface as typed evidence, never as a fabricated capacity.
"""

from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from pathlib import Path

import pytest
from solders.pubkey import Pubkey

from src.assets.resolution.evidence import Evidence
from src.economics.flash_capital_graph.graph import (
    FlashCapitalEdge,
    KaminoCapitalProvider,
)
from src.lending.kamino import (
    KAMINO_FLASH_BORROW_INSTRUCTION_NAME,
    KAMINO_FLASH_IX_OBLIGATION_ACCOUNT_REQUIRED,
    KAMINO_FLASH_REPAY_CARRIES_BORROW_INSTRUCTION_INDEX_U8,
    KAMINO_FLASH_REPAY_INSTRUCTION_NAME,
    KAMINO_RESERVE_ACCOUNT_DISCRIMINATOR,
    KAMINO_RESERVE_PINNED_FIELDS,
    KAMINO_RESERVE_PINNED_PREFIX_LEN,
    KAMINO_SPL_TOKEN_ACCOUNT_LEN,
    KAMINO_UNPINNED_CAPACITY_GAPS,
    KLEND_FRACTION_SCALE_BITS,
    KLEND_ONE_SF,
    KLEND_PROGRAM_ID,
    KLEND_PROGRAM_SOURCE_COMMIT,
    KLEND_PROGRAM_SOURCE_VERSION,
    KLEND_SDK_PACKAGE,
    KLEND_SDK_UPSTREAM_COMMIT,
    KLEND_SDK_VERSION,
    READER_DECODER_GENERATION,
    READER_DECODER_IDENTITY,
    READER_EXECUTION_AUTHORITY,
    SPL_TOKEN_2022_PROGRAM_ID,
    SPL_TOKEN_PROGRAM_ID,
    KaminoCapacityDerivation,
    KaminoCapacityReaderError,
    KaminoCapacityRejectionCode,
    KaminoReserveCapacityObservation,
    build_kamino_capital_reader_result,
    decode_kamino_reserve,
    decode_kamino_vault_token_account,
    kamino_flash_loan_fee_rational,
    kamino_reserve_capital_edge_gate,
    observe_kamino_reserve_capacity,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PINNED_PREFIX_SCHEMA = (
    REPO_ROOT
    / "docs/roadmap/r02-capacity-recovery-2026-10-08/offline/kamino_reserve_prefix_layout.json"
)


def _pk(seed: int) -> Pubkey:
    return Pubkey.from_bytes(bytes((seed,)) * 32)


def _reserve_bytes(values: dict[str, bytes], *, tail_len: int = 2816) -> bytes:
    """Build reserve bytes schema-driven from the pinned offset map."""

    raw = bytearray(KAMINO_RESERVE_PINNED_PREFIX_LEN + tail_len)
    raw[:8] = KAMINO_RESERVE_ACCOUNT_DISCRIMINATOR
    for name, (offset, size) in KAMINO_RESERVE_PINNED_FIELDS.items():
        chunk = values[name]
        assert len(chunk) == size, f"fixture width mismatch for {name}"
        raw[offset : offset + size] = chunk
    return bytes(raw)


def _default_reserve_values(
    mint: Pubkey,
    market: Pubkey,
    supply_vault: Pubkey,
    fee_vault: Pubkey,
    token_program: Pubkey,
) -> dict[str, bytes]:
    """Synthetic resource values; identities are NOT reviewed mainnet state."""

    return {
        "version": (0).to_bytes(8, "little"),
        "last_update_slot": (30_000_000).to_bytes(8, "little"),
        "last_update_stale": (0).to_bytes(1, "little"),
        "last_update_price_status": (1).to_bytes(1, "little"),
        "last_update_pad": bytes(2),
        "last_update_timestamp": (1_764_000_000).to_bytes(4, "little"),
        "lending_market": bytes(market),
        "farm_collateral": bytes(_pk(41)),
        "farm_debt": bytes(_pk(42)),
        "liquidity_mint": bytes(mint),
        "liquidity_supply_vault": bytes(supply_vault),
        "liquidity_fee_vault": bytes(fee_vault),
        "total_available_amount": (5_000_000_000).to_bytes(8, "little"),
        "borrowed_amount_sf": (3_100_000_000 * KLEND_ONE_SF).to_bytes(16, "little"),
        "market_price_sf": (1).to_bytes(16, "little"),
        "market_price_last_updated_ts": (1_763_999_900).to_bytes(8, "little"),
        "mint_decimals": (6).to_bytes(8, "little"),
        "deposit_limit_crossed_ts": (0).to_bytes(8, "little"),
        "borrow_limit_crossed_ts": (0).to_bytes(8, "little"),
        "cumulative_borrow_rate_bsf": (1).to_bytes(8, "little") + bytes(24),
        "accumulated_protocol_fees_sf": (1_000 * KLEND_ONE_SF).to_bytes(16, "little"),
        "accumulated_referrer_fees_sf": (0).to_bytes(16, "little"),
        "pending_referrer_fees_sf": (0).to_bytes(16, "little"),
        "absolute_referral_rate_sf": (0).to_bytes(16, "little"),
        "liquidity_token_program": bytes(token_program),
        "rewards_amount_available": (0).to_bytes(8, "little"),
        "liquidity_padding2": bytes(400),
        "liquidity_padding3": bytes(512),
        "reserve_liquidity_padding": bytes(1200),
        "collateral_mint": bytes(_pk(43)),
        "collateral_mint_total_supply": (8_000_000_000).to_bytes(8, "little"),
        "collateral_supply_vault": bytes(_pk(44)),
        "collateral_padding1": bytes(512),
        "collateral_padding2": bytes(512),
        "reserve_collateral_padding": bytes(1200),
        "config_status": (0).to_bytes(1, "little"),
        "config_padding_deprecated_asset_tier": (0).to_bytes(1, "little"),
        "config_host_fixed_interest_rate_bps": (0).to_bytes(2, "little"),
        "config_min_deleveraging_bonus_bps": (400).to_bytes(2, "little"),
        "config_block_ctoken_usage": (0).to_bytes(1, "little"),
        "config_early_repay_remaining_interest_pct": (0).to_bytes(1, "little"),
        "config_emergency_mode": (0).to_bytes(1, "little"),
        "config_interest_rate_basis": (0).to_bytes(1, "little"),
        "config_reserved1": bytes(3),
        "config_protocol_order_execution_fee_pct": (0).to_bytes(1, "little"),
        "config_protocol_take_rate_pct": (10).to_bytes(1, "little"),
        "config_protocol_liquidation_fee_pct": (5).to_bytes(1, "little"),
        "config_loan_to_value_pct": (80).to_bytes(1, "little"),
        "config_liquidation_threshold_pct": (90).to_bytes(1, "little"),
        "config_min_liquidation_bonus_bps": (100).to_bytes(2, "little"),
        "config_max_liquidation_bonus_bps": (1000).to_bytes(2, "little"),
        "config_bad_debt_liquidation_bonus_bps": (500).to_bytes(2, "little"),
        "config_deleveraging_margin_call_period_secs": (86_400).to_bytes(8, "little"),
        "config_deleveraging_threshold_decrease_bps_per_day": (100).to_bytes(
            8, "little"
        ),
        "config_origination_fee_sf": (0).to_bytes(8, "little"),
        "config_flash_loan_fee_sf": (3 * (KLEND_ONE_SF >> 2)).to_bytes(8, "little"),
        "config_fees_padding": bytes(8),
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
    raw = bytearray(KAMINO_SPL_TOKEN_ACCOUNT_LEN)
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


class Fixture:
    def __init__(self) -> None:
        self.mint = _pk(3)
        self.market = _pk(7)
        self.reserve_address = _pk(8)
        self.supply_vault = _pk(9)
        self.fee_vault = _pk(10)
        self.token_program = SPL_TOKEN_PROGRAM_ID
        self.reserve_bytes = _reserve_bytes(
            _default_reserve_values(
                self.mint,
                self.market,
                self.supply_vault,
                self.fee_vault,
                self.token_program,
            )
        )
        self.supply_vault_bytes = _vault_bytes(self.mint, self.market, 5_250_000_000)
        self.fee_vault_bytes = _vault_bytes(self.mint, self.market, 1_000_000)
        self.observation = observe_kamino_reserve_capacity(
            reserve_bytes=self.reserve_bytes,
            reserve_owner=KLEND_PROGRAM_ID,
            reserve_address=self.reserve_address,
            lending_market=self.market,
            supply_vault_bytes=self.supply_vault_bytes,
            supply_vault_address=self.supply_vault,
            supply_vault_owner_program=self.token_program,
            fee_vault_bytes=self.fee_vault_bytes,
            fee_vault_address=self.fee_vault,
            fee_vault_owner_program=self.token_program,
            reviewed_mint=self.mint,
        )


@pytest.fixture(scope="module")
def fixture() -> Fixture:
    return Fixture()


def test_capacity_reader_pins_klend_sdk_source_program_and_flash_pair() -> None:
    assert KLEND_SDK_PACKAGE == "@kamino-finance/klend-sdk"
    assert KLEND_SDK_VERSION == "13.0.2"
    assert KLEND_SDK_UPSTREAM_COMMIT == "3c3a38d4ff9d7cf7b0380a383b81c9cd4f0f58b8"
    assert str(KLEND_PROGRAM_ID) == "KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD"
    assert KLEND_PROGRAM_SOURCE_COMMIT == "a08760976f51a3a58c4a0c6ea27b4a0e565bca79"
    assert KLEND_PROGRAM_SOURCE_VERSION == "1.25.0"
    assert KLEND_FRACTION_SCALE_BITS == 60
    assert KLEND_ONE_SF == 1 << 60
    assert KAMINO_RESERVE_ACCOUNT_DISCRIMINATOR == bytes(
        (43, 242, 204, 202, 26, 247, 59, 127)
    )
    assert KAMINO_RESERVE_PINNED_PREFIX_LEN == 4904
    assert READER_EXECUTION_AUTHORITY == "NONE"
    assert READER_DECODER_IDENTITY == "kamino.klend.reserve.capacity-reader.v1"
    assert READER_DECODER_GENERATION == 1
    # Distinct flash borrow/repay pair, separate from obligation borrow.
    assert KAMINO_FLASH_BORROW_INSTRUCTION_NAME == "flash_borrow_reserve_liquidity"
    assert KAMINO_FLASH_REPAY_INSTRUCTION_NAME == "flash_repay_reserve_liquidity"
    assert KAMINO_FLASH_REPAY_CARRIES_BORROW_INSTRUCTION_INDEX_U8 is True
    assert KAMINO_FLASH_IX_OBLIGATION_ACCOUNT_REQUIRED is False


def test_pinned_offset_map_matches_prefix_dossier() -> None:
    schema = json.loads(PINNED_PREFIX_SCHEMA.read_text(encoding="utf-8"))
    assert (
        bytes(schema["reserve_discriminator"]) == KAMINO_RESERVE_ACCOUNT_DISCRIMINATOR
    )
    assert schema["sdk_version"] == KLEND_SDK_VERSION
    assert schema["official_program_id"] == str(KLEND_PROGRAM_ID)
    # The dossier names the liquidity fields without the "liquidity_" prefix.
    dossier_name = {
        "mint": "liquidity_mint",
        "supply_vault": "liquidity_supply_vault",
        "fee_vault": "liquidity_fee_vault",
    }
    for field in schema["prefix_fields"]:
        name = dossier_name.get(field["name"], field["name"])
        offset, size = KAMINO_RESERVE_PINNED_FIELDS[name]
        assert offset == field["offset"], name
        assert size == field["bytes"], name
    # The dossier prefix (280 bytes) is a strict subset of the pinned layout.
    assert schema["prefix_len_bytes"] == 280
    assert schema["prefix_len_bytes"] <= KAMINO_RESERVE_PINNED_PREFIX_LEN


def test_reserve_decode_roundtrips_all_pinned_fields(fixture: Fixture) -> None:
    state = decode_kamino_reserve(
        fixture.reserve_bytes, owner=KLEND_PROGRAM_ID, lending_market=fixture.market
    )
    assert state.version_raw == 0
    assert state.last_update.slot == 30_000_000
    assert state.last_update.stale == 0
    assert state.last_update.price_status == 1
    assert state.last_update.timestamp == 1_764_000_000
    assert state.lending_market == fixture.market
    assert state.liquidity.mint == fixture.mint
    assert state.liquidity.supply_vault == fixture.supply_vault
    assert state.liquidity.fee_vault == fixture.fee_vault
    assert state.liquidity.total_available_amount == 5_000_000_000
    assert state.liquidity.borrowed_amount_sf == 3_100_000_000 * KLEND_ONE_SF
    assert state.liquidity.mint_decimals_raw == 6
    assert state.liquidity.token_program == SPL_TOKEN_PROGRAM_ID
    assert state.liquidity.cumulative_borrow_rate_bsf_limbs == (1, 0, 0, 0)
    assert state.liquidity.accumulated_protocol_fees_sf == 1_000 * KLEND_ONE_SF
    assert state.collateral.mint_total_supply == 8_000_000_000
    assert state.config.status_raw == 0
    assert state.config.emergency_mode == 0
    assert state.config.loan_to_value_pct == 80
    assert state.config.liquidation_threshold_pct == 90
    assert state.config.flash_loan_fee_sf == 3 * (KLEND_ONE_SF >> 2)
    assert state.config.origination_fee_sf == 0
    assert state.unpinned_tail_len == 2816
    assert (
        state.unpinned_tail_sha256
        == hashlib.sha256(
            fixture.reserve_bytes[KAMINO_RESERVE_PINNED_PREFIX_LEN:]
        ).hexdigest()
    )


def test_reserve_decode_rejects_bad_discriminator(fixture: Fixture) -> None:
    mutated = bytearray(fixture.reserve_bytes)
    mutated[0] ^= 0xFF
    with pytest.raises(
        KaminoCapacityReaderError, match="R02CAPB_RESERVE_UNKNOWN_DISCRIMINATOR"
    ):
        decode_kamino_reserve(
            bytes(mutated), owner=KLEND_PROGRAM_ID, lending_market=fixture.market
        )


def test_reserve_decode_rejects_truncated_layout(fixture: Fixture) -> None:
    truncated = fixture.reserve_bytes[: KAMINO_RESERVE_PINNED_PREFIX_LEN - 1]
    with pytest.raises(
        KaminoCapacityReaderError, match="R02CAPB_RESERVE_TRUNCATED_LAYOUT"
    ):
        decode_kamino_reserve(
            truncated, owner=KLEND_PROGRAM_ID, lending_market=fixture.market
        )
    with pytest.raises(
        KaminoCapacityReaderError, match="R02CAPB_RESERVE_TRUNCATED_LAYOUT"
    ):
        decode_kamino_reserve(
            b"", owner=KLEND_PROGRAM_ID, lending_market=fixture.market
        )


def test_reserve_decode_rejects_wrong_owner(fixture: Fixture) -> None:
    with pytest.raises(
        KaminoCapacityReaderError, match="R02CAPB_RESERVE_OWNER_MISMATCH"
    ):
        decode_kamino_reserve(
            fixture.reserve_bytes,
            owner=SPL_TOKEN_PROGRAM_ID,
            lending_market=fixture.market,
        )


def test_reserve_decode_rejects_wrong_market_binding(fixture: Fixture) -> None:
    with pytest.raises(
        KaminoCapacityReaderError, match="R02CAPB_RESERVE_MARKET_BINDING_MISMATCH"
    ):
        decode_kamino_reserve(
            fixture.reserve_bytes, owner=KLEND_PROGRAM_ID, lending_market=_pk(99)
        )


def test_reserve_decode_rejects_stale_last_update(fixture: Fixture) -> None:
    values = _default_reserve_values(
        fixture.mint,
        fixture.market,
        fixture.supply_vault,
        fixture.fee_vault,
        fixture.token_program,
    )
    values["last_update_stale"] = (1).to_bytes(1, "little")
    with pytest.raises(
        KaminoCapacityReaderError, match="R02CAPB_RESERVE_LAST_UPDATE_STALE"
    ):
        decode_kamino_reserve(
            _reserve_bytes(values),
            owner=KLEND_PROGRAM_ID,
            lending_market=fixture.market,
        )


def test_reserve_decode_rejects_unknown_config_status_flag(fixture: Fixture) -> None:
    values = _default_reserve_values(
        fixture.mint,
        fixture.market,
        fixture.supply_vault,
        fixture.fee_vault,
        fixture.token_program,
    )
    values["config_status"] = (1).to_bytes(1, "little")
    with pytest.raises(
        KaminoCapacityReaderError, match="R02CAPB_RESERVE_CONFIG_STATUS_UNKNOWN"
    ):
        decode_kamino_reserve(
            _reserve_bytes(values),
            owner=KLEND_PROGRAM_ID,
            lending_market=fixture.market,
        )


def test_reserve_decode_rejects_nonzero_emergency_mode(fixture: Fixture) -> None:
    values = _default_reserve_values(
        fixture.mint,
        fixture.market,
        fixture.supply_vault,
        fixture.fee_vault,
        fixture.token_program,
    )
    values["config_emergency_mode"] = (1).to_bytes(1, "little")
    with pytest.raises(
        KaminoCapacityReaderError, match="R02CAPB_RESERVE_EMERGENCY_MODE_NONZERO"
    ):
        decode_kamino_reserve(
            _reserve_bytes(values),
            owner=KLEND_PROGRAM_ID,
            lending_market=fixture.market,
        )


def test_reserve_decode_rejects_zero_mint_and_unknown_token_program(
    fixture: Fixture,
) -> None:
    zero_mint = _default_reserve_values(
        Pubkey.from_bytes(bytes(32)),
        fixture.market,
        fixture.supply_vault,
        fixture.fee_vault,
        fixture.token_program,
    )
    with pytest.raises(KaminoCapacityReaderError, match="R02CAPB_RESERVE_ZERO_MINT"):
        decode_kamino_reserve(
            _reserve_bytes(zero_mint),
            owner=KLEND_PROGRAM_ID,
            lending_market=fixture.market,
        )
    unknown_program = _default_reserve_values(
        fixture.mint,
        fixture.market,
        fixture.supply_vault,
        fixture.fee_vault,
        _pk(55),
    )
    with pytest.raises(
        KaminoCapacityReaderError, match="R02CAPB_VAULT_TOKEN_PROGRAM_MISMATCH"
    ):
        decode_kamino_reserve(
            _reserve_bytes(unknown_program),
            owner=KLEND_PROGRAM_ID,
            lending_market=fixture.market,
        )


def test_vault_decode_binds_pinned_token_program_and_fails_closed(
    fixture: Fixture,
) -> None:
    supply = decode_kamino_vault_token_account(
        fixture.supply_vault_bytes,
        address=fixture.supply_vault,
        owner_program=SPL_TOKEN_PROGRAM_ID,
        expected_mint=fixture.mint,
        expected_token_program=SPL_TOKEN_PROGRAM_ID,
        role="supply",
    )
    assert supply.amount == 5_250_000_000
    assert supply.mint == fixture.mint
    assert supply.authority == fixture.market
    assert supply.role == "supply"
    assert supply.delegate is None
    assert supply.close_authority is None

    fee = decode_kamino_vault_token_account(
        fixture.fee_vault_bytes,
        address=fixture.fee_vault,
        owner_program=SPL_TOKEN_PROGRAM_ID,
        expected_mint=fixture.mint,
        expected_token_program=SPL_TOKEN_PROGRAM_ID,
        role="fee",
    )
    assert fee.role == "fee"
    assert fee.amount == 1_000_000

    wrong_length = fixture.supply_vault_bytes[:-1]
    with pytest.raises(
        KaminoCapacityReaderError, match="R02CAPB_VAULT_LAYOUT_MISMATCH"
    ):
        decode_kamino_vault_token_account(
            wrong_length,
            address=fixture.supply_vault,
            owner_program=SPL_TOKEN_PROGRAM_ID,
            expected_mint=fixture.mint,
            expected_token_program=SPL_TOKEN_PROGRAM_ID,
            role="supply",
        )
    with pytest.raises(
        KaminoCapacityReaderError, match="R02CAPB_VAULT_TOKEN_PROGRAM_MISMATCH"
    ):
        decode_kamino_vault_token_account(
            fixture.supply_vault_bytes,
            address=fixture.supply_vault,
            owner_program=SPL_TOKEN_2022_PROGRAM_ID,
            expected_mint=fixture.mint,
            expected_token_program=SPL_TOKEN_PROGRAM_ID,
            role="supply",
        )
    with pytest.raises(
        KaminoCapacityReaderError, match="R02CAPB_VAULT_MINT_BINDING_MISMATCH"
    ):
        decode_kamino_vault_token_account(
            fixture.supply_vault_bytes,
            address=fixture.supply_vault,
            owner_program=SPL_TOKEN_PROGRAM_ID,
            expected_mint=_pk(66),
            expected_token_program=SPL_TOKEN_PROGRAM_ID,
            role="supply",
        )
    with pytest.raises(KaminoCapacityReaderError, match="R02CAPB_VAULT_FROZEN"):
        decode_kamino_vault_token_account(
            _vault_bytes(fixture.mint, fixture.market, 5, account_state=2),
            address=fixture.supply_vault,
            owner_program=SPL_TOKEN_PROGRAM_ID,
            expected_mint=fixture.mint,
            expected_token_program=SPL_TOKEN_PROGRAM_ID,
            role="supply",
        )
    with pytest.raises(
        KaminoCapacityReaderError, match="R02CAPB_VAULT_ACCOUNT_STATE_UNKNOWN"
    ):
        decode_kamino_vault_token_account(
            _vault_bytes(fixture.mint, fixture.market, 5, account_state=3),
            address=fixture.supply_vault,
            owner_program=SPL_TOKEN_PROGRAM_ID,
            expected_mint=fixture.mint,
            expected_token_program=SPL_TOKEN_PROGRAM_ID,
            role="supply",
        )
    with pytest.raises(
        KaminoCapacityReaderError, match="R02CAPB_VAULT_DELEGATE_UNPROVEN"
    ):
        decode_kamino_vault_token_account(
            _vault_bytes(fixture.mint, fixture.market, 5, delegate=True),
            address=fixture.supply_vault,
            owner_program=SPL_TOKEN_PROGRAM_ID,
            expected_mint=fixture.mint,
            expected_token_program=SPL_TOKEN_PROGRAM_ID,
            role="supply",
        )
    with pytest.raises(
        KaminoCapacityReaderError, match="R02CAPB_VAULT_CLOSE_AUTHORITY_UNPROVEN"
    ):
        decode_kamino_vault_token_account(
            _vault_bytes(fixture.mint, fixture.market, 5, close_authority=True),
            address=fixture.supply_vault,
            owner_program=SPL_TOKEN_PROGRAM_ID,
            expected_mint=fixture.mint,
            expected_token_program=SPL_TOKEN_PROGRAM_ID,
            role="supply",
        )
    with pytest.raises(
        KaminoCapacityReaderError, match="R02CAPB_CAPACITY_STATE_INVALID"
    ):
        decode_kamino_vault_token_account(
            fixture.supply_vault_bytes,
            address=fixture.supply_vault,
            owner_program=SPL_TOKEN_PROGRAM_ID,
            expected_mint=fixture.mint,
            expected_token_program=SPL_TOKEN_PROGRAM_ID,
            role="unknown-role",
        )


def test_flash_loan_fee_rational_is_exact_pinned_scale(fixture: Fixture) -> None:
    raw = fixture.observation.flash_loan_fee_sf_raw
    assert raw == 3 * (KLEND_ONE_SF >> 2)
    # Exact rational raw/2^60: 3 * 2^58 / 2^60 reduces to exactly 3/4. No
    # float, and no invented ceil/floor transfer rule.
    assert kamino_flash_loan_fee_rational(raw) == Fraction(3, 4)
    assert kamino_flash_loan_fee_rational(KLEND_ONE_SF >> 1) == Fraction(1, 2)
    assert kamino_flash_loan_fee_rational(0) == Fraction(0)
    assert fixture.observation.fee_rounding == "UNPINNED"
    assert "FEE_ROUNDING_RULE_UNPINNED" in fixture.observation.constraint_gaps
    with pytest.raises(KaminoCapacityReaderError):
        kamino_flash_loan_fee_rational(-1)


def test_observation_types_blocked_unknown_capacity_not_zero(
    fixture: Fixture,
) -> None:
    obs = fixture.observation
    assert obs.effective_capacity_base_units is None
    assert obs.capacity_derivation is KaminoCapacityDerivation.UNPROVEN
    assert set(obs.blockers) == {
        "MISSING_EFFECTIVE_FLASH_CAP",
        "LIVE_ROOTED_RPC_NOT_AUTHORIZED",
    }
    for gap in (
        "BORROW_LIMIT_UNDECODABLE_OFFLINE",
        "UTILIZATION_CONFIG_UNDECODABLE_OFFLINE",
        "CONFIG_TAIL_LAYOUT_UNPINNED",
        "LENDING_MARKET_LAYOUT_UNPINNED",
        "ORACLE_HEALTH_ELIGIBILITY_UNPINNED",
        "ORACLE_PRICE_STATUS_SEMANTICS_UNPINNED",
        "FEE_ROUNDING_RULE_UNPINNED",
        "ORIGINATION_FEE_PAYABLE_AMOUNT_UNPINNED",
        "INTEREST_ACCRUAL_LAZY_UPDATE_UNAUDITED",
        "SUPPLY_VAULT_AUTHORITY_BINDING_UNPROVEN",
        "MINT_ACCOUNT_NOT_DECODED_OFFLINE",
        "FLASH_FEE_DEDUCTION_SEMANTICS_UNAUDITED",
    ):
        assert gap in obs.constraint_gaps, gap
    assert "REVIEWED_MINT_BINDING_ABSENT" not in obs.constraint_gaps
    assert set(KAMINO_UNPINNED_CAPACITY_GAPS) <= set(obs.constraint_gaps)
    assert obs.status == "BLOCKED_LIVE_STATE"
    # Raw resource state is proven from decoded bytes; capacity is not.
    assert obs.raw_total_available_amount == 5_000_000_000
    assert obs.raw_borrowed_amount_sf == 3_100_000_000 * KLEND_ONE_SF
    assert obs.raw_supply_vault_amount == 5_250_000_000
    assert obs.raw_fee_vault_amount == 1_000_000
    assert obs.mint == str(fixture.mint)
    assert obs.reserve_address == str(fixture.reserve_address)
    assert obs.reserve_owner == str(KLEND_PROGRAM_ID)
    assert obs.lending_market == str(fixture.market)
    assert obs.mint_decimals == 6
    assert obs.reserve_data_sha256 == hashlib.sha256(fixture.reserve_bytes).hexdigest()
    assert (
        obs.supply_vault_data_sha256
        == hashlib.sha256(fixture.supply_vault_bytes).hexdigest()
    )
    assert (
        obs.fee_vault_data_sha256 == hashlib.sha256(fixture.fee_vault_bytes).hexdigest()
    )
    # Strictly offline provenance: the decoded last-update slot is recorded
    # as resource state, never claimed as a rooted read slot.
    assert obs.last_update.slot == 30_000_000
    assert obs.slot is None
    assert obs.slot_rooted is False
    assert obs.slot_provenance == "OFFLINE_FIXTURE_NOT_ROOTED"
    assert obs.execution_authority == "NONE"
    assert obs.sign_enabled is False
    assert obs.send_enabled is False


def test_observation_digest_is_content_addressed(fixture: Fixture) -> None:
    rebuilt = observe_kamino_reserve_capacity(
        reserve_bytes=fixture.reserve_bytes,
        reserve_owner=KLEND_PROGRAM_ID,
        reserve_address=fixture.reserve_address,
        lending_market=fixture.market,
        supply_vault_bytes=fixture.supply_vault_bytes,
        supply_vault_address=fixture.supply_vault,
        supply_vault_owner_program=SPL_TOKEN_PROGRAM_ID,
        fee_vault_bytes=fixture.fee_vault_bytes,
        fee_vault_address=fixture.fee_vault,
        fee_vault_owner_program=SPL_TOKEN_PROGRAM_ID,
        reviewed_mint=fixture.mint,
    )
    assert fixture.observation.evidence_digest == rebuilt.evidence_digest

    mutated = bytearray(fixture.reserve_bytes)
    mutated[KAMINO_RESERVE_PINNED_FIELDS["total_available_amount"][0]] ^= 0x01
    drifted = observe_kamino_reserve_capacity(
        reserve_bytes=bytes(mutated),
        reserve_owner=KLEND_PROGRAM_ID,
        reserve_address=fixture.reserve_address,
        lending_market=fixture.market,
        supply_vault_bytes=fixture.supply_vault_bytes,
        supply_vault_address=fixture.supply_vault,
        supply_vault_owner_program=SPL_TOKEN_PROGRAM_ID,
        reviewed_mint=fixture.mint,
    )
    assert drifted.evidence_digest != fixture.observation.evidence_digest
    assert (
        drifted.raw_total_available_amount
        == fixture.observation.raw_total_available_amount + 1
    )

    # Tail bytes are hashed for provenance but never interpreted: mutating
    # the unpinned tail changes the tail hash only, not any decoded field.
    tail_mutated = bytearray(fixture.reserve_bytes)
    tail_mutated[KAMINO_RESERVE_PINNED_PREFIX_LEN + 5] ^= 0xFF
    tail_obs = observe_kamino_reserve_capacity(
        reserve_bytes=bytes(tail_mutated),
        reserve_owner=KLEND_PROGRAM_ID,
        reserve_address=fixture.reserve_address,
        lending_market=fixture.market,
        supply_vault_bytes=fixture.supply_vault_bytes,
        supply_vault_address=fixture.supply_vault,
        supply_vault_owner_program=SPL_TOKEN_PROGRAM_ID,
        reviewed_mint=fixture.mint,
    )
    assert tail_obs.state.unpinned_tail_sha256 != (
        fixture.observation.state.unpinned_tail_sha256
    )
    assert tail_obs.raw_total_available_amount == (
        fixture.observation.raw_total_available_amount
    )


def test_observation_binds_reviewed_mint_when_supplied(fixture: Fixture) -> None:
    bound = observe_kamino_reserve_capacity(
        reserve_bytes=fixture.reserve_bytes,
        reserve_owner=KLEND_PROGRAM_ID,
        reserve_address=fixture.reserve_address,
        lending_market=fixture.market,
        supply_vault_bytes=fixture.supply_vault_bytes,
        supply_vault_address=fixture.supply_vault,
        supply_vault_owner_program=SPL_TOKEN_PROGRAM_ID,
        reviewed_mint=fixture.mint,
    )
    assert "REVIEWED_MINT_BINDING_ABSENT" not in bound.constraint_gaps
    with pytest.raises(
        KaminoCapacityReaderError, match="R02CAPB_RESERVE_MINT_BINDING_MISMATCH"
    ):
        observe_kamino_reserve_capacity(
            reserve_bytes=fixture.reserve_bytes,
            reserve_owner=KLEND_PROGRAM_ID,
            reserve_address=fixture.reserve_address,
            lending_market=fixture.market,
            supply_vault_bytes=fixture.supply_vault_bytes,
            supply_vault_address=fixture.supply_vault,
            supply_vault_owner_program=SPL_TOKEN_PROGRAM_ID,
            reviewed_mint=_pk(21),
        )


def test_observation_requires_supply_and_fee_vault_bindings(
    fixture: Fixture,
) -> None:
    with pytest.raises(
        KaminoCapacityReaderError, match="R02CAPB_VAULT_ADDRESS_BINDING_MISMATCH"
    ):
        observe_kamino_reserve_capacity(
            reserve_bytes=fixture.reserve_bytes,
            reserve_owner=KLEND_PROGRAM_ID,
            reserve_address=fixture.reserve_address,
            lending_market=fixture.market,
            supply_vault_bytes=fixture.supply_vault_bytes,
            supply_vault_address=_pk(88),
            supply_vault_owner_program=SPL_TOKEN_PROGRAM_ID,
            reviewed_mint=fixture.mint,
        )
    with pytest.raises(
        KaminoCapacityReaderError, match="R02CAPB_VAULT_ADDRESS_BINDING_MISMATCH"
    ):
        observe_kamino_reserve_capacity(
            reserve_bytes=fixture.reserve_bytes,
            reserve_owner=KLEND_PROGRAM_ID,
            reserve_address=fixture.reserve_address,
            lending_market=fixture.market,
            supply_vault_bytes=fixture.supply_vault_bytes,
            supply_vault_address=fixture.supply_vault,
            supply_vault_owner_program=SPL_TOKEN_PROGRAM_ID,
            fee_vault_bytes=fixture.fee_vault_bytes,
            fee_vault_address=_pk(89),
            fee_vault_owner_program=SPL_TOKEN_PROGRAM_ID,
            reviewed_mint=fixture.mint,
        )
    with pytest.raises(
        KaminoCapacityReaderError, match="R02CAPB_CAPACITY_STATE_INVALID"
    ):
        observe_kamino_reserve_capacity(
            reserve_bytes=fixture.reserve_bytes,
            reserve_owner=KLEND_PROGRAM_ID,
            reserve_address=fixture.reserve_address,
            lending_market=fixture.market,
            supply_vault_bytes=fixture.supply_vault_bytes,
            supply_vault_address=fixture.supply_vault,
            supply_vault_owner_program=SPL_TOKEN_PROGRAM_ID,
            fee_vault_bytes=fixture.fee_vault_bytes,
            reviewed_mint=fixture.mint,
        )


def test_edge_gate_never_emits_edge_offline(fixture: Fixture) -> None:
    gate = kamino_reserve_capital_edge_gate(fixture.observation)
    assert gate.edge is None
    assert gate.blocker == "LIVE_ROOTED_RPC_NOT_AUTHORIZED"
    assert gate.blockers == fixture.observation.blockers
    assert "offline fixture evidence never qualifies an edge" in gate.note


def test_reader_result_feeds_existing_kamino_capital_provider_port(
    fixture: Fixture,
) -> None:
    payload, evidence = build_kamino_capital_reader_result(
        fixture.observation,
        observed_at=1_000.0,
        generation="offline-generation",
    )
    assert payload["schema"] == "dynamic-universe.capital.v1"
    assert payload["provider"] == "kamino"
    assert payload["assets"] == []
    assert payload["blockers"] == [
        "MISSING_EFFECTIVE_FLASH_CAP",
        "LIVE_ROOTED_RPC_NOT_AUTHORIZED",
    ]
    assert evidence.negative_reason == "LIVE_ROOTED_RPC_NOT_AUTHORIZED"
    assert evidence.slot_or_checkpoint is None
    assert evidence.response_hash == fixture.observation.evidence_digest

    provider = KaminoCapitalProvider(
        reader=lambda: (payload, evidence),
        assets=(),
    )
    # Existing frozen graph port: negative evidence is recorded, zero edges.
    assert provider.discover_assets() == ()
    assert provider.negative_evidence == ["LIVE_ROOTED_RPC_NOT_AUTHORIZED"]
    with pytest.raises(ValueError, match="no live lender capacity"):
        provider.refresh("asset", 1)


def test_flash_capital_edge_cannot_be_fabricated_from_offline_evidence(
    fixture: Fixture,
) -> None:
    _, evidence = build_kamino_capital_reader_result(
        fixture.observation,
        observed_at=1_000.0,
        generation="offline-generation",
    )
    # Even a hand-built edge cannot pass the frozen graph validation with
    # negative (unrooted, unqualified) evidence.
    with pytest.raises(ValueError, match="current observed fee/capacity provenance"):
        FlashCapitalEdge(
            "solana",
            "kamino",
            "synthetic-asset",
            str(fixture.mint),
            str(fixture.reserve_address),
            5_000_000_000,
            fixture.observation.flash_loan_fee_sf_raw,
            KLEND_ONE_SF,
            0,
            "LOCAL_ATOMIC_CANDIDATE",
            (),
            evidence,
            (fixture.observation.evidence_digest,),
        )
    # And the observation itself structurally carries no usable capacity.
    assert fixture.observation.effective_capacity_base_units is None
