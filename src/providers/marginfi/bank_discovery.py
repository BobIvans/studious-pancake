"""R02-CAP-D: wallet-free Project 0 (MarginFi) bank discovery + capacity reader.

Strictly read-only research reader for the pinned MarginFi deployment
(``src/resources/marginfi_pr028.json``, source commit ``d4c70c84f8a9692405a2c32c
bd7095bb1fe3f428``, mainnet program ``MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVa
cA``) with the wallet-optional protocol mode pinned by the R-02 offline SDK pack
(``docs/roadmap/r02-capacity-recovery-2026-10-08/offline/p0_public_discovery_facts
.json``, source pin ``0dotxyz/p0-ts-sdk@8a8353bb662459e5957b0cbbd2121f4fddb37fc3``).

Wallet-free mode (the only mode this wave):
- bank-level discovery from caller-supplied account captures (offline fixtures
  or, in a later authorized wave, live rooted reads). No wallet, no authority,
  no marginfi account and no PDA for a user account is ever derived here.
- the liquidity-vault-authority PDA is derived from the pinned seed
  ``liquidity_vault_auth`` (PR-028 constants); the bank PDA seed itself and the
  marginfi-account PDA seed are NOT pinned offline, so bank/account addresses
  are never fabricated and stay typed UNKNOWN gaps instead.
- bank layout decode is limited to the PR-028 pinned offsets: mint, decimals,
  group binding, liquidity vault, origination fee (i80F48 raw), operational
  state, oracle setup/keys, borrow limit, risk tier, asset tag, flags/token
  program. Bank share-value / liquidity-share / last-update / emissions
  offsets are UNPINNED and therefore stay structurally unknown.
- effective per-bank borrowable capacity is UNKNOWN (never zero) until audited
  program math is proven on a live rooted-RPC snapshot with independent
  quorum: raw vault cash, decoded borrow caps and raw share fields are never
  capacity by themselves (R02_UNBLOCK_MATRIX.md / R02_ACCEPTANCE.md).
- account-based user eligibility requires an operator-supplied pre-existing
  public account; none is supplied this wave, so it is typed
  ``OPERATOR_ACCOUNT_INPUT_REQUIRED``. No account-creation instruction is ever
  built, signed, or sent; execution authority is NONE.

Fail-closed: unknown owner/discriminator/length/group/vault binding, non-
coherent capture slots, unknown oracle conformance, paused group, non-
operational bank, or any unpinned layout gap surfaces as typed negative
evidence. Zero network, zero signer/sender imports, ``graph.py`` untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, fields as dataclass_fields, is_dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
from importlib import resources
import re
from typing import Any, Sequence

from solders.pubkey import Pubkey

from .accounts import RpcAccount
from .errors import MarginfiRejection, MarginfiRejectionCode
from .layouts import (
    DecodedBank,
    DecodedTokenAccount,
    ceil_i80f48_product,
    decode_bank,
    decode_group,
    decode_token_account,
)
from .pin import MarginfiContractPin, load_marginfi_contract_pin

REPO_ROOT = Path(__file__).resolve().parents[3]

P0_OFFLINE_FACTS_PATH = (
    REPO_ROOT
    / "docs/roadmap/r02-capacity-recovery-2026-10-08/offline/p0_public_discovery_facts.json"
)
PR055_RESOURCE_NAME = "marginfi_pr055.json"

P0_SOURCE_PIN = "0dotxyz/p0-ts-sdk@8a8353bb662459e5957b0cbbd2121f4fddb37fc3"
P0_SOURCE_GIT_VERSION = "2.10.0"
P0_PACKAGE = "@0dotxyz/p0-ts-sdk"
P0_PROTOCOL_IDL = "src/idl/marginfi_0.1.12.json"
P0_WALLETLESS_STATUS = "P0_EXISTING_ACCOUNT_UNKNOWN_READ_BANKS_ONLY"
P0_FORBIDDEN_METHODS = (
    "createMarginfiAccountTx",
    "sendTransaction",
    "signTransaction",
)

# Pinned PR-028 constants (cross-checked against the packaged pin at load time).
LIQUIDITY_VAULT_AUTHORITY_SEED = b"liquidity_vault_auth"
I80F48_FRACTIONAL_BITS = 48
BANK_TOKEN_2022_FLAG = 128

# Exact pinned DPR rule for the decoded protocol origination fee: the fee for a
# borrow of ``amount`` is ceil(amount * fee_raw / 2^48) — the PR-028 conformance
# math (``ceil_i80f48_product``) over the pinned i80F48 fractional bits.
FEE_ROUNDING_RULE = "I80F48_CEIL_SCALE_2POW48"

READER_DECODER_IDENTITY = "project0.bank.capacity-reader.v1"
READER_DECODER_GENERATION = 1
READER_EXECUTION_AUTHORITY = "NONE"
READER_WALLETLESS_MODE = "WALLETLESS_BANK_DISCOVERY_ONLY"
READER_SLOT_PROVENANCE_OFFLINE = "OFFLINE_FIXTURE_NOT_ROOTED"
READER_SLOT_PROVENANCE_LIVE = "LIVE_ROOTED_RPC"
READER_CAPACITY_DERIVATION_UNPROVEN = "R02CAPD_CAPACITY_DERIVATION_UNPROVEN"
READER_ACCOUNT_ELIGIBILITY_UNKNOWN = P0_WALLETLESS_STATUS

# Typed constraint gaps. Each is a fact that is unknown offline because its
# layout, semantics or authorization is not pinned in this repository. Unknown
# is not zero: none of these may be defaulted.
GAP_BANK_PDA_SEED_UNPINNED = "BANK_PDA_SEED_UNPINNED"
GAP_ACCOUNT_PDA_SEED_UNPINNED = "MARGINFI_ACCOUNT_PDA_SEED_UNPINNED"
GAP_ASSET_SHARE_VALUE_UNPINNED = "BANK_ASSET_SHARE_VALUE_LAYOUT_UNPINNED"
GAP_LIABILITY_SHARE_VALUE_UNPINNED = "BANK_LIABILITY_SHARE_VALUE_LAYOUT_UNPINNED"
GAP_LIQUIDITY_SHARES_UNPINNED = "BANK_LIQUIDITY_SHARES_LAYOUT_UNPINNED"
GAP_LAST_UPDATE_UNPINNED = "BANK_LAST_UPDATE_SLOT_LAYOUT_UNPINNED"
GAP_EMISSIONS_UNPINNED = "BANK_EMISSIONS_LAYOUT_UNPINNED"
GAP_BORROW_LIMIT_SEMANTICS_UNPINNED = "BANK_BORROW_LIMIT_SEMANTICS_UNPINNED"
GAP_ORACLE_PRICE_UNPROVEN = "ORACLE_PRICE_UNPROVEN"
GAP_GROUP_PAUSE_UNPROVEN = "GROUP_PAUSE_STATE_UNPROVEN"
GAP_BANK_SOURCE_PROVENANCE_UNPROVEN = "BANK_ADDRESS_PROVENANCE_UNPROVEN"

BLOCKER_MISSING_EFFECTIVE_FLASH_CAP = "MISSING_EFFECTIVE_FLASH_CAP"
BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED = "LIVE_ROOTED_RPC_NOT_AUTHORIZED"
BLOCKER_OPERATOR_ACCOUNT_INPUT_REQUIRED = "OPERATOR_ACCOUNT_INPUT_REQUIRED"
BLOCKER_GROUP_PAUSED = "R02CAPD_PROTOCOL_PAUSED"
BLOCKER_BANK_NOT_OPERATIONAL = "R02CAPD_BANK_NOT_OPERATIONAL"
BLOCKER_GRAPH_ALLOWANCE_PENDING = (
    "R02CAPD_FLASH_CAPITAL_GRAPH_ALLOWANCE_PENDING_INDEPENDENT_QUORUM"
)
BLOCKER_FINANCING_PORT_NOT_PRESCRIBED = "R02CAPD_FINANCING_PORT_NOT_PRESCRIBED_IN_AGG03"
BLOCKER_LIVE_ENUMERATION_NOT_AUTHORIZED = "R02CAPD_LIVE_BANK_ENUMERATION_NOT_AUTHORIZED"

_ZERO_PUBKEY = Pubkey.from_bytes(bytes(32))
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class MarginfiBankDiscoveryRejectionCode(StrEnum):
    """Typed R02-CAP-D fail-closed negatives (structural and discovery)."""

    P0_FACTS_SCHEMA_DRIFT = "R02CAPD_P0_FACTS_SCHEMA_DRIFT"
    PIN_CROSS_CHECK_FAILED = "R02CAPD_PIN_CROSS_CHECK_FAILED"
    CAPTURE_STATE_INVALID = "R02CAPD_CAPTURE_STATE_INVALID"
    BANK_OWNER_MISMATCH = "R02CAPD_BANK_OWNER_MISMATCH"
    BANK_GROUP_BINDING_MISMATCH = "R02CAPD_BANK_GROUP_BINDING_MISMATCH"
    VAULT_CAPTURE_ADDRESS_MISMATCH = "R02CAPD_VAULT_CAPTURE_ADDRESS_MISMATCH"
    VAULT_AUTHORITY_BINDING_MISMATCH = "R02CAPD_VAULT_AUTHORITY_BINDING_MISMATCH"
    CAPTURE_SLOT_INCOHERENT = "R02CAPD_CAPTURE_SLOT_INCOHERENT"
    SHARE_MATH_INVALID = "R02CAPD_SHARE_MATH_INVALID"
    LIVE_ENUMERATION_NOT_AUTHORIZED = "R02CAPD_LIVE_BANK_ENUMERATION_NOT_AUTHORIZED"


class MarginfiBankDiscoveryError(ValueError):
    def __init__(
        self,
        code: MarginfiBankDiscoveryRejectionCode,
        message: str,
    ) -> None:
        super().__init__(f"{code.value}: {message}")
        self.code = code
        self.diagnostic = message


def _require_pubkey(value: str, label: str) -> Pubkey:
    try:
        return Pubkey.from_string(value)
    except (ValueError, TypeError) as exc:
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.CAPTURE_STATE_INVALID,
            f"{label} is not a base58 public key",
        ) from exc


@dataclass(frozen=True, slots=True)
class MarginfiCapture:
    """One caller-supplied account capture (offline fixture or later live read).

    ``slot`` is the observed RPC context slot of the capture when the capture
    source declares one. Offline fixtures may leave it unset; the reader never
    upgrades a fixture slot into a rooted slot claim.
    """

    address: str
    owner: str
    data: bytes
    slot: int | None = None

    def __post_init__(self) -> None:
        _require_pubkey(self.address, "capture address")
        _require_pubkey(self.owner, "capture owner")
        if not isinstance(self.data, bytes):
            raise MarginfiBankDiscoveryError(
                MarginfiBankDiscoveryRejectionCode.CAPTURE_STATE_INVALID,
                "capture data must be raw bytes",
            )
        if self.slot is not None and (type(self.slot) is not int or self.slot < 0):
            raise MarginfiBankDiscoveryError(
                MarginfiBankDiscoveryRejectionCode.CAPTURE_STATE_INVALID,
                "capture slot must be a non-negative integer when supplied",
            )

    def as_rpc_account(self) -> RpcAccount:
        return RpcAccount(address=self.address, owner=self.owner, data=bytes(self.data))


@dataclass(frozen=True, slots=True)
class P0DiscoveryFacts:
    """Validated wallet-free mode facts from the pinned offline SDK pack."""

    source_pin: str
    source_git_version: str
    package: str
    protocol_idl: str
    walletless_mode: str
    bank_only_reads_allowed: bool
    public_wallet_address_optional: bool
    public_marginfi_account_optional: bool
    status_without_public_wallet: str
    forbidden: tuple[str, ...]
    execution_authority: str
    raw: dict[str, Any]


def load_p0_discovery_facts(path: Path | None = None) -> P0DiscoveryFacts:
    """Load and fail-closed validate the pinned p0 wallet-free discovery facts."""

    source = path or P0_OFFLINE_FACTS_PATH
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.P0_FACTS_SCHEMA_DRIFT,
            f"pinned p0 discovery facts are unreadable: {source}",
        ) from exc
    if not isinstance(raw, dict):
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.P0_FACTS_SCHEMA_DRIFT,
            "p0 discovery facts root must be an object",
        )
    if str(raw.get("source_pin")) != P0_SOURCE_PIN:
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.P0_FACTS_SCHEMA_DRIFT,
            "p0 discovery facts source pin drift",
        )
    if str(raw.get("source_git_version")) != P0_SOURCE_GIT_VERSION:
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.P0_FACTS_SCHEMA_DRIFT,
            "p0 discovery facts source version drift",
        )
    if str(raw.get("package")) != P0_PACKAGE:
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.P0_FACTS_SCHEMA_DRIFT,
            "p0 discovery facts package drift",
        )
    if str(raw.get("protocol_idl")) != P0_PROTOCOL_IDL:
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.P0_FACTS_SCHEMA_DRIFT,
            "p0 discovery facts protocol IDL drift",
        )
    if bool(raw.get("bank_only_reads_allowed")) is not True:
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.P0_FACTS_SCHEMA_DRIFT,
            "wallet-free mode must be bank-reads-only",
        )
    for key in ("public_wallet_address_optional", "public_marginfi_account_optional"):
        if bool(raw.get(key)) is not True:
            raise MarginfiBankDiscoveryError(
                MarginfiBankDiscoveryRejectionCode.P0_FACTS_SCHEMA_DRIFT,
                f"p0 wallet/public-account optionality drift: {key}",
            )
    if str(raw.get("status_without_public_wallet")) != P0_WALLETLESS_STATUS:
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.P0_FACTS_SCHEMA_DRIFT,
            "p0 walletless status drift",
        )
    forbidden = tuple(str(item) for item in raw.get("forbidden") or ())
    for method in P0_FORBIDDEN_METHODS:
        if method not in forbidden:
            raise MarginfiBankDiscoveryError(
                MarginfiBankDiscoveryRejectionCode.P0_FACTS_SCHEMA_DRIFT,
                f"p0 facts must forbid {method}",
            )
    if str(raw.get("execution_authority")) != "NONE":
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.P0_FACTS_SCHEMA_DRIFT,
            "p0 execution authority drift",
        )
    if bool(raw.get("account_init_required_if_missing")) is not True:
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.P0_FACTS_SCHEMA_DRIFT,
            "p0 facts must require account init when missing (never performed here)",
        )
    return P0DiscoveryFacts(
        source_pin=str(raw["source_pin"]),
        source_git_version=str(raw["source_git_version"]),
        package=str(raw["package"]),
        protocol_idl=str(raw["protocol_idl"]),
        walletless_mode=str(raw.get("walletless_mode", "")),
        bank_only_reads_allowed=True,
        public_wallet_address_optional=True,
        public_marginfi_account_optional=True,
        status_without_public_wallet=P0_WALLETLESS_STATUS,
        forbidden=forbidden,
        execution_authority="NONE",
        raw=raw,
    )


@dataclass(frozen=True, slots=True)
class BankReaderPins:
    """Cross-checked PR-028/PR-055/p0 pins for the wallet-free bank reader."""

    contract_pin: MarginfiContractPin
    program_id: str
    main_group: str
    bank_offsets: dict[str, Any]
    facts: P0DiscoveryFacts


def load_bank_reader_pins() -> BankReaderPins:
    """Load the PR-028 contract pin, the PR-055 group pin and the p0 facts.

    Every layer must agree on the program identity and the pinned seeds, or the
    reader fails closed. Missing pinned bank offsets are a hard pin failure:
    the reader never guesses a layout offset that the repository does not pin.
    """

    contract_pin = load_marginfi_contract_pin()
    try:
        pr055 = json.loads(
            resources.files("src.resources")
            .joinpath(PR055_RESOURCE_NAME)
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, ModuleNotFoundError, json.JSONDecodeError) as exc:
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.PIN_CROSS_CHECK_FAILED,
            "PR-055 MarginFi authoritative conformance resource is unreadable",
        ) from exc
    if not isinstance(pr055, dict) or str(pr055.get("program_id")) != (
        contract_pin.program_id
    ):
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.PIN_CROSS_CHECK_FAILED,
            "PR-055 program id disagrees with the PR-028 contract pin",
        )
    layout_manifest = str(
        (pr055.get("source") or {}).get("layout_manifest", ""),
    )
    if layout_manifest != "src/resources/marginfi_pr028.json":
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.PIN_CROSS_CHECK_FAILED,
            "PR-055 layout manifest does not reference the PR-028 pin",
        )
    main_group = str(pr055.get("main_group", ""))
    _require_pubkey(main_group, "PR-055 main group")
    try:
        bank_layout = contract_pin.raw["account_layouts"]["bank"]
        offsets = bank_layout["offsets"]
    except (KeyError, TypeError) as exc:
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.PIN_CROSS_CHECK_FAILED,
            "PR-028 pin has no bank layout offsets",
        ) from exc
    required_offsets = (
        "mint",
        "mint_decimals",
        "group",
        "liquidity_vault",
        "protocol_origination_fee",
        "operational_state",
        "oracle_setup",
        "oracle_keys",
        "borrow_limit",
        "risk_tier",
        "asset_tag",
        "flags",
    )
    for key in required_offsets:
        if key not in offsets:
            raise MarginfiBankDiscoveryError(
                MarginfiBankDiscoveryRejectionCode.PIN_CROSS_CHECK_FAILED,
                f"PR-028 bank layout is missing pinned offset: {key}",
            )
    constants = contract_pin.raw.get("constants") or {}
    if str(constants.get("liquidity_vault_authority_seed")) != (
        LIQUIDITY_VAULT_AUTHORITY_SEED.decode()
    ):
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.PIN_CROSS_CHECK_FAILED,
            "liquidity vault authority seed drift against the PR-028 pin",
        )
    if int(constants.get("i80f48_fractional_bits", -1)) != I80F48_FRACTIONAL_BITS:
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.PIN_CROSS_CHECK_FAILED,
            "pinned i80F48 fractional bits drift",
        )
    facts = load_p0_discovery_facts()
    return BankReaderPins(
        contract_pin=contract_pin,
        program_id=contract_pin.program_id,
        main_group=main_group,
        bank_offsets=dict(offsets),
        facts=facts,
    )


def derive_bank_liquidity_vault_authority(
    pins: BankReaderPins, bank: Pubkey
) -> tuple[Pubkey, int]:
    """Canonical liquidity-vault-authority PDA from the pinned PR-028 seed.

    Seeds are ``[b"liquidity_vault_auth", bank]`` under the pinned program. Any
    other seed or a zero bank is rejected; this derivation binds the bank
    address to the vault authority but is NOT a proof that the bank address
    itself is the canonical Bank PDA (that seed is unpinned offline).
    """

    if bytes(bank) == bytes(_ZERO_PUBKEY):
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.CAPTURE_STATE_INVALID,
            "zero bank address cannot bind a liquidity vault authority",
        )
    seed = LIQUIDITY_VAULT_AUTHORITY_SEED
    if str(pins.contract_pin.raw["constants"]["liquidity_vault_authority_seed"]) != (
        seed.decode()
    ):
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.PIN_CROSS_CHECK_FAILED,
            "liquidity vault authority seed drift",
        )
    return Pubkey.find_program_address([seed, bytes(bank)], _program_pubkey(pins))


def _program_pubkey(pins: BankReaderPins) -> Pubkey:
    return Pubkey.from_string(pins.program_id)


def _assert_slots_coherent(captures: Sequence[MarginfiCapture]) -> None:
    declared = [capture.slot for capture in captures if capture.slot is not None]
    if declared and len(set(declared)) != 1:
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.CAPTURE_SLOT_INCOHERENT,
            "capture batch spans more than one RPC context slot; refusing a "
            "stale or mixed-slot snapshot",
        )


def decode_bank_capture(pins: BankReaderPins, capture: MarginfiCapture) -> DecodedBank:
    """Fail-closed decode of one caller-supplied Bank account capture.

    The capture must be owned by the pinned program and must decode exactly at
    the PR-028 pinned layout (discriminator, exact 1856-byte struct size,
    supported oracle setup/asset tag, non-negative fee). The decoded group
    field must equal the PR-055 pinned main group. Unknown or stale data fails
    closed instead of decoding a prefix.
    """

    if capture.owner != pins.program_id:
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.BANK_OWNER_MISMATCH,
            "bank capture owner differs from the pinned MarginFi program",
        )
    decoded = decode_bank(
        capture.as_rpc_account(), pins.contract_pin, bank_address=capture.address
    )
    if decoded.group != pins.main_group:
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.BANK_GROUP_BINDING_MISMATCH,
            "decoded bank group differs from the pinned PR-055 main group",
        )
    return decoded


def decode_liquidity_vault_capture(
    pins: BankReaderPins,
    capture: MarginfiCapture,
    decoded_bank: DecodedBank,
) -> DecodedTokenAccount:
    """Decode and bind the bank's liquidity vault SPL token account capture.

    The vault capture address must equal the bank's decoded liquidity vault,
    the token program must match the bank's pinned token-program resolution,
    the vault mint must equal the bank mint, and the vault SPL authority must
    equal the PDA derived from the pinned ``liquidity_vault_auth`` seed.
    """

    if capture.address != decoded_bank.liquidity_vault:
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.VAULT_CAPTURE_ADDRESS_MISMATCH,
            "vault capture address differs from the decoded bank liquidity vault",
        )
    if capture.owner != decoded_bank.token_program:
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.CAPTURE_STATE_INVALID,
            "vault capture owner differs from the bank's pinned token program",
        )
    vault = decode_token_account(
        capture.as_rpc_account(),
        token_program=decoded_bank.token_program,
        expected_mint=decoded_bank.mint,
    )
    # decode_bank derives the vault authority PDA from the BANK address under
    # the pinned seed; the vault's SPL authority field must match it exactly.
    if vault.authority != decoded_bank.liquidity_vault_authority:
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.VAULT_AUTHORITY_BINDING_MISMATCH,
            "liquidity vault authority does not match the pinned seed PDA",
        )
    return vault


def compute_origination_fee(
    amount: int,
    origination_fee_raw_i80f48: int,
    *,
    fractional_bits: int = I80F48_FRACTIONAL_BITS,
) -> int:
    """Exact pinned DPR fee: ceil(amount * fee_raw / 2^fractional_bits).

    Reuses the PR-028 conformance math (``ceil_i80f48_product``); negative
    inputs are rejected instead of being interpreted as zero.
    """

    return ceil_i80f48_product(
        amount, origination_fee_raw_i80f48, fractional_bits=fractional_bits
    )


@dataclass(frozen=True, slots=True)
class BankShareValuation:
    """Exact i80F48 share math for caller-supplied raw bank share fields.

    The bank offsets for asset/liability share values and liquidity shares are
    NOT pinned in this repository, so these inputs can never be auto-decoded
    from bank bytes by this reader; a future authorized full-layout reader must
    supply them and accept this math. Totals are the integer token-amount view
    of ``shares * share_value`` over i80F48 raw inputs (product scaled down by
    ``2^(2 * fractional_bits)``): assets use floor and liabilities use ceil so
    that neither direction can overstate borrowable capacity.
    """

    raw_asset_total: int
    raw_liability_total: int
    fractional_bits: int


def compute_share_valuation(
    *,
    asset_shares_raw: int,
    asset_share_value_raw: int,
    liability_shares_raw: int,
    liability_share_value_raw: int,
    fractional_bits: int = I80F48_FRACTIONAL_BITS,
) -> BankShareValuation:
    """Floor(assets) / ceil(liabilities) share valuation, fail-closed."""

    for name, value in (
        ("asset_shares_raw", asset_shares_raw),
        ("asset_share_value_raw", asset_share_value_raw),
        ("liability_shares_raw", liability_shares_raw),
        ("liability_share_value_raw", liability_share_value_raw),
    ):
        if type(value) is not int or value < 0:
            raise MarginfiBankDiscoveryError(
                MarginfiBankDiscoveryRejectionCode.SHARE_MATH_INVALID,
                f"{name} must be a non-negative integer",
            )
    denominator = 1 << (2 * fractional_bits)
    asset_total = (asset_shares_raw * asset_share_value_raw) // denominator
    liability_product = liability_shares_raw * liability_share_value_raw
    liability_total = (liability_product + denominator - 1) // denominator
    return BankShareValuation(
        raw_asset_total=asset_total,
        raw_liability_total=liability_total,
        fractional_bits=fractional_bits,
    )


def _canonical_json(value: object) -> str:
    def normalize(node: object) -> object:
        if is_dataclass(node) and not isinstance(node, type):
            return {
                field.name: normalize(getattr(node, field.name))
                for field in dataclass_fields(node)
            }
        if isinstance(node, Pubkey):
            return str(node)
        if isinstance(node, StrEnum):
            return str(node.value)
        if isinstance(node, (tuple, list)):
            return [normalize(item) for item in node]
        if isinstance(node, dict):
            return {key: normalize(item) for key, item in node.items()}
        return node

    return json.dumps(
        normalize(value), sort_keys=True, separators=(",", ":"), allow_nan=False
    )


@dataclass(frozen=True, slots=True)
class MarginfiBankCapacityObservation:
    """Typed read-only capacity observation for one decoded MarginFi bank.

    Raw resource state proven from decoded pinned-layout bytes:
    ``raw_vault_amount_base_units`` (SPL vault balance), ``raw_borrow_limit``
    (pinned u64 borrow cap) and ``origination_fee_raw_i80f48`` (pinned i80F48
    fee state). ``effective_capacity_base_units`` stays ``None`` while the
    derivation is UNPROVEN: unknown is not zero. Bank share-value / liquidity
    share / last-update / emissions raw fields stay ``None`` (layout unpinned).
    """

    bank: str
    group: str
    mint: str
    mint_decimals: int
    token_program: str
    liquidity_vault: str
    liquidity_vault_authority: str
    oracle_setup: int
    oracle_keys: tuple[str, ...]
    asset_tag: int
    operational_state: int
    operational: bool
    bank_data_sha256: str
    vault_data_sha256: str
    group_data_sha256: str | None
    raw_vault_amount_base_units: int
    raw_borrow_limit: int
    origination_fee_raw_i80f48: int
    fee_rounding: str
    raw_asset_share_value_i80f48: int | None
    raw_liability_share_value_i80f48: int | None
    raw_liquidity_shares_i80f48: int | None
    raw_liability_shares_i80f48: int | None
    capacity_derivation: str
    effective_capacity_base_units: int | None
    constraint_gaps: tuple[str, ...]
    blockers: tuple[str, ...]
    walletless_mode: str
    decoder_identity: str = READER_DECODER_IDENTITY
    decoder_generation: int = READER_DECODER_GENERATION
    execution_authority: str = READER_EXECUTION_AUTHORITY
    slot: int | None = None
    slot_rooted: bool = False
    slot_provenance: str = READER_SLOT_PROVENANCE_OFFLINE
    sign_enabled: bool = False
    send_enabled: bool = False
    account_creation_attempted: bool = False

    def __post_init__(self) -> None:
        for name in (
            "bank",
            "group",
            "mint",
            "token_program",
            "liquidity_vault",
            "liquidity_vault_authority",
        ):
            _require_pubkey(getattr(self, name), name)
        for key in self.oracle_keys:
            _require_pubkey(key, "oracle key")
        for name in ("bank_data_sha256", "vault_data_sha256"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                raise ValueError(f"{name} must be lowercase sha256")
        if self.group_data_sha256 is not None and (
            not isinstance(self.group_data_sha256, str)
            or not _SHA256_RE.fullmatch(self.group_data_sha256)
        ):
            raise ValueError("group_data_sha256 must be lowercase sha256 or None")
        if type(self.mint_decimals) is not int or not 0 <= self.mint_decimals <= 255:
            raise ValueError("mint decimals must be an integer in [0, 255]")
        for name in ("raw_vault_amount_base_units", "raw_borrow_limit"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.capacity_derivation != READER_CAPACITY_DERIVATION_UNPROVEN:
            raise ValueError("unsupported capacity derivation")
        if self.effective_capacity_base_units is not None:
            raise ValueError(
                "effective capacity without proven derivation is forbidden; "
                "unknown is not zero"
            )
        for name in (
            "raw_asset_share_value_i80f48",
            "raw_liability_share_value_i80f48",
            "raw_liquidity_shares_i80f48",
            "raw_liability_shares_i80f48",
        ):
            if getattr(self, name) is not None:
                raise ValueError(
                    f"{name} is unpinned offline and must stay unknown (None)"
                )
        if BLOCKER_MISSING_EFFECTIVE_FLASH_CAP not in self.blockers:
            raise ValueError("unproven capacity must carry MISSING_EFFECTIVE_FLASH_CAP")
        if not self.constraint_gaps:
            raise ValueError("unproven capacity must enumerate constraint gaps")
        if not self.slot_rooted:
            if self.slot is not None:
                raise ValueError("unrooted observation cannot claim a slot")
            if self.slot_provenance != READER_SLOT_PROVENANCE_OFFLINE:
                raise ValueError("unrooted observation must use offline provenance")
            if BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED not in self.blockers:
                raise ValueError(
                    "unrooted observation must carry LIVE_ROOTED_RPC_NOT_AUTHORIZED"
                )
        else:
            if (
                self.slot is None
                or type(self.slot) is not int
                or self.slot < 0
                or self.slot_provenance != READER_SLOT_PROVENANCE_LIVE
            ):
                raise ValueError("rooted observation requires an integer rooted slot")
        if self.fee_rounding != FEE_ROUNDING_RULE:
            raise ValueError("fee rounding rule must be the pinned DPR rule")
        if self.execution_authority != READER_EXECUTION_AUTHORITY:
            raise ValueError("execution authority must stay NONE")
        if self.sign_enabled or self.send_enabled or self.account_creation_attempted:
            raise ValueError(
                "reader must never sign, send, or attempt account creation"
            )
        if self.walletless_mode != READER_WALLETLESS_MODE:
            raise ValueError("wallet-free mode drift")

    @property
    def status(self) -> str:
        return "BLOCKED_LIVE_STATE" if self.blockers else "PARTIAL_DECODED"

    @property
    def evidence_digest(self) -> str:
        return hashlib.sha256(_canonical_json(self).encode("utf-8")).hexdigest()

    def evidence_record(self) -> dict[str, Any]:
        return {
            "decoder_identity": self.decoder_identity,
            "decoder_generation": self.decoder_generation,
            "evidence_sha256": self.evidence_digest,
            "status": self.status,
            "observation": json.loads(_canonical_json(self)),
        }


def observe_bank_capacity(
    pins: BankReaderPins,
    bank_capture: MarginfiCapture,
    vault_capture: MarginfiCapture,
    *,
    group_capture: MarginfiCapture | None = None,
    now_timestamp: int | None = None,
) -> MarginfiBankCapacityObservation:
    """Decode bank + vault captures offline and return typed capacity evidence.

    Every input is caller-supplied (offline fixture or, in a later authorized
    wave, a live rooted read). No network, no signing, no account creation, no
    wallet, no marginfi account. Capture slots must be coherent when declared.
    """

    batch: list[MarginfiCapture] = [bank_capture, vault_capture]
    if group_capture is not None:
        batch.append(group_capture)
    _assert_slots_coherent(batch)
    decoded_bank = decode_bank_capture(pins, bank_capture)
    decoded_vault = decode_liquidity_vault_capture(pins, vault_capture, decoded_bank)

    operational = decoded_bank.operational_state == 1
    gaps = [
        GAP_BANK_PDA_SEED_UNPINNED,
        GAP_ACCOUNT_PDA_SEED_UNPINNED,
        GAP_ASSET_SHARE_VALUE_UNPINNED,
        GAP_LIABILITY_SHARE_VALUE_UNPINNED,
        GAP_LIQUIDITY_SHARES_UNPINNED,
        GAP_LAST_UPDATE_UNPINNED,
        GAP_EMISSIONS_UNPINNED,
        GAP_BORROW_LIMIT_SEMANTICS_UNPINNED,
        GAP_ORACLE_PRICE_UNPROVEN,
        GAP_BANK_SOURCE_PROVENANCE_UNPROVEN,
    ]
    blockers = [
        BLOCKER_MISSING_EFFECTIVE_FLASH_CAP,
        BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED,
    ]
    group_sha: str | None = None
    if group_capture is not None:
        if group_capture.owner != pins.program_id:
            raise MarginfiBankDiscoveryError(
                MarginfiBankDiscoveryRejectionCode.CAPTURE_STATE_INVALID,
                "group capture owner differs from the pinned MarginFi program",
            )
        decoded_group = decode_group(
            group_capture.as_rpc_account(),
            pins.contract_pin,
            now_timestamp=now_timestamp if now_timestamp is not None else 0,
        )
        if group_capture.address != pins.main_group:
            raise MarginfiBankDiscoveryError(
                MarginfiBankDiscoveryRejectionCode.CAPTURE_STATE_INVALID,
                "group capture address differs from the pinned main group",
            )
        group_sha = hashlib.sha256(bytes(group_capture.data)).hexdigest()
        if decoded_group.paused:
            blockers.append(BLOCKER_GROUP_PAUSED)
        else:
            gaps.append(GAP_GROUP_PAUSE_UNPROVEN)
    else:
        gaps.append(GAP_GROUP_PAUSE_UNPROVEN)
    if not operational:
        blockers.append(BLOCKER_BANK_NOT_OPERATIONAL)
    return MarginfiBankCapacityObservation(
        bank=bank_capture.address,
        group=decoded_bank.group,
        mint=decoded_bank.mint,
        mint_decimals=decoded_bank.mint_decimals,
        token_program=decoded_bank.token_program,
        liquidity_vault=decoded_bank.liquidity_vault,
        liquidity_vault_authority=decoded_bank.liquidity_vault_authority,
        oracle_setup=decoded_bank.oracle_setup,
        oracle_keys=tuple(decoded_bank.oracle_keys),
        asset_tag=decoded_bank.asset_tag,
        operational_state=decoded_bank.operational_state,
        operational=operational,
        bank_data_sha256=hashlib.sha256(bytes(bank_capture.data)).hexdigest(),
        vault_data_sha256=hashlib.sha256(bytes(vault_capture.data)).hexdigest(),
        group_data_sha256=group_sha,
        raw_vault_amount_base_units=decoded_vault.amount,
        raw_borrow_limit=decoded_bank.borrow_limit,
        origination_fee_raw_i80f48=decoded_bank.origination_fee_raw_i80f48,
        fee_rounding=FEE_ROUNDING_RULE,
        raw_asset_share_value_i80f48=None,
        raw_liability_share_value_i80f48=None,
        raw_liquidity_shares_i80f48=None,
        raw_liability_shares_i80f48=None,
        capacity_derivation=READER_CAPACITY_DERIVATION_UNPROVEN,
        effective_capacity_base_units=None,
        constraint_gaps=tuple(sorted(gaps)),
        blockers=tuple(sorted(set(blockers))),
        walletless_mode=READER_WALLETLESS_MODE,
    )


@dataclass(frozen=True, slots=True)
class WalletFreeBankDiscovery:
    """Typed wallet-free discovery result over caller-supplied captures."""

    mode: str
    banks: tuple[MarginfiBankCapacityObservation, ...]
    group_paused: bool | None
    group_data_sha256: str | None
    account_eligibility_status: str
    account_eligibility_blockers: tuple[str, ...]
    blockers: tuple[str, ...]
    constraint_gaps: tuple[str, ...]
    evidence_digest: str

    def evidence_record(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "evidence_sha256": self.evidence_digest,
            "walletless_status": self.account_eligibility_status,
            "bank_observations": [bank.evidence_record() for bank in self.banks],
            "blockers": list(self.blockers),
            "constraint_gaps": list(self.constraint_gaps),
        }


def discover_banks(
    pins: BankReaderPins,
    bank_captures: Sequence[MarginfiCapture],
    vault_captures: Sequence[MarginfiCapture],
    *,
    group_capture: MarginfiCapture | None = None,
    now_timestamp: int | None = None,
) -> WalletFreeBankDiscovery:
    """Wallet-free bank discovery over caller-supplied account captures.

    Enumerating live banks (``get_program_accounts`` filtered on the pinned
    group, as the pinned p0 SDK does) requires an authorized live transport and
    is typed blocked; this wave only decodes caller-supplied captures. Empty
    input is ambiguous and fails closed instead of decoding to an empty pass.
    """

    if not bank_captures:
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.CAPTURE_STATE_INVALID,
            "wallet-free discovery requires caller-supplied bank captures; "
            "live enumeration is not authorized and empty is not evidence",
        )
    addresses = [capture.address for capture in bank_captures]
    if len(set(addresses)) != len(addresses):
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.CAPTURE_STATE_INVALID,
            "duplicate bank captures in one discovery batch",
        )
    if len(vault_captures) != len(bank_captures):
        raise MarginfiBankDiscoveryError(
            MarginfiBankDiscoveryRejectionCode.CAPTURE_STATE_INVALID,
            "each bank capture requires exactly one liquidity vault capture",
        )
    batch: list[MarginfiCapture] = [*bank_captures, *vault_captures]
    if group_capture is not None:
        batch.append(group_capture)
    _assert_slots_coherent(batch)
    vault_by_address = {capture.address: capture for capture in vault_captures}
    observations: list[MarginfiBankCapacityObservation] = []
    for bank_capture in bank_captures:
        decoded_bank = decode_bank_capture(pins, bank_capture)
        vault_capture = vault_by_address.get(decoded_bank.liquidity_vault)
        if vault_capture is None:
            raise MarginfiBankDiscoveryError(
                MarginfiBankDiscoveryRejectionCode.VAULT_CAPTURE_ADDRESS_MISMATCH,
                "no vault capture matches the decoded bank liquidity vault",
            )
        observations.append(
            observe_bank_capacity(
                pins,
                bank_capture,
                vault_capture,
                group_capture=group_capture,
                now_timestamp=now_timestamp,
            )
        )
    group_paused: bool | None = None
    group_sha: str | None = None
    if group_capture is not None and observations:
        first = observations[0]
        group_paused = BLOCKER_GROUP_PAUSED in first.blockers
        group_sha = first.group_data_sha256
    eligibility_blockers = (BLOCKER_OPERATOR_ACCOUNT_INPUT_REQUIRED,)
    blockers = tuple(
        sorted(
            {
                blocker
                for observation in observations
                for blocker in observation.blockers
            }
        )
    )
    gaps = tuple(
        sorted(
            {gap for observation in observations for gap in observation.constraint_gaps}
        )
    )
    digest = hashlib.sha256(
        _canonical_json(
            {
                "mode": READER_WALLETLESS_MODE,
                "banks": [observation.evidence_digest for observation in observations],
                "group_paused": group_paused,
                "account_eligibility_blockers": list(eligibility_blockers),
            }
        ).encode("utf-8")
    ).hexdigest()
    return WalletFreeBankDiscovery(
        mode=READER_WALLETLESS_MODE,
        banks=tuple(observations),
        group_paused=group_paused,
        group_data_sha256=group_sha,
        account_eligibility_status=READER_ACCOUNT_ELIGIBILITY_UNKNOWN,
        account_eligibility_blockers=eligibility_blockers,
        blockers=blockers,
        constraint_gaps=gaps,
        evidence_digest=digest,
    )


@dataclass(frozen=True, slots=True)
class MarginfiAccountEligibility:
    """Typed account-based eligibility verdict; always blocked offline."""

    status: str
    walletless_status: str
    blockers: tuple[str, ...]
    notes: tuple[str, ...]
    account_creation_attempted: bool
    derived_pdas: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.account_creation_attempted or self.derived_pdas:
            raise ValueError(
                "account eligibility must never create accounts or derive "
                "user-account PDAs"
            )


def evaluate_existing_account_eligibility(
    pins: BankReaderPins,
    *,
    operator_authority: str | None = None,
    operator_account: str | None = None,
) -> MarginfiAccountEligibility:
    """Report user-account eligibility without any account-side action.

    Without operator-supplied public inputs the verdict is typed
    ``OPERATOR_ACCOUNT_INPUT_REQUIRED`` (acceptance matrix alias
    ``P0_ACCOUNT_BINDING_PENDING_USER``). Even with inputs supplied, verifying a
    pre-existing account needs a live rooted read and an unpinned account-PDA
    seed, so the verdict stays blocked. No initialization, no creation, no
    signing: the pinned p0 facts forbid ``createMarginfiAccountTx``.
    """

    notes = [
        "wallet-free bank-level capability is reported separately from user "
        "eligibility; absence of a supplied account is never inferred from "
        "another wallet",
        "pinned p0 facts forbid createMarginfiAccountTx/sendTransaction/"
        "signTransaction and no account-creation path exists in this reader",
    ]
    if operator_authority is None and operator_account is None:
        return MarginfiAccountEligibility(
            status="BLOCKED_OPERATOR_ACCOUNT_INPUT_REQUIRED",
            walletless_status=pins.facts.status_without_public_wallet,
            blockers=(BLOCKER_OPERATOR_ACCOUNT_INPUT_REQUIRED,),
            notes=tuple(notes),
            account_creation_attempted=False,
            derived_pdas=(),
        )
    for label, value in (
        ("operator authority", operator_authority),
        ("operator account", operator_account),
    ):
        if value is not None:
            _require_pubkey(value, label)
    return MarginfiAccountEligibility(
        status="BLOCKED_LIVE_STATE",
        walletless_status=pins.facts.status_without_public_wallet,
        blockers=(
            BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED,
            GAP_ACCOUNT_PDA_SEED_UNPINNED,
        ),
        notes=tuple(
            notes
            + [
                "operator-supplied public inputs require a live rooted-RPC "
                "read of the pre-existing account before any eligibility "
                "claim; no such transport is authorized this wave",
            ]
        ),
        account_creation_attempted=False,
        derived_pdas=(),
    )


@dataclass(frozen=True, slots=True)
class MarginfiLiveEnumerationPlan:
    """Typed plan for the blocked live wallet-free enumeration."""

    method: str
    reads: tuple[str, ...]
    blockers: tuple[str, ...]
    performed: bool
    accounts_returned: tuple[str, ...]


def plan_live_bank_enumeration(pins: BankReaderPins) -> MarginfiLiveEnumerationPlan:
    """Document the pinned live enumeration path without performing any I/O.

    The pinned p0 SDK enumerates banks by ``get_program_accounts`` on the
    program filtered by the group address; the vault and emissions state are
    then fetched per bank. That transport is not authorized this wave, so the
    plan returns no accounts and carries typed blockers.
    """

    return MarginfiLiveEnumerationPlan(
        method=(
            f"p0-ts-sdk Project0Client.initialize -> MarginfiGroup.fetchBanks "
            f"(get_program_accounts filtered by group {pins.main_group}), "
            f"read-only against program {pins.program_id}"
        ),
        reads=(
            "bank accounts (owner = pinned program, group = pinned main group)",
            "per-bank liquidity vault SPL token accounts",
            "per-bank share-value/liquidity/last-update/emissions state",
        ),
        blockers=(
            BLOCKER_LIVE_ENUMERATION_NOT_AUTHORIZED,
            BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED,
        ),
        performed=False,
        accounts_returned=(),
    )


@dataclass(frozen=True, slots=True)
class MarginfiFinancingAdmission:
    """Typed outcome of wiring an observation into the financing ports."""

    observation_digest: str
    snapshot: object | None
    available_liquidity_base_units: int | None
    blockers: tuple[str, ...]


def admit_bank_financing_snapshot(
    *,
    observation: MarginfiBankCapacityObservation,
    asset_id: str,
    state_fingerprint: str,
) -> MarginfiFinancingAdmission:
    """Bind a bank observation into the existing financing ports fail-closed.

    Read-only import of ``src.lending.agg03_financing_ports`` (never edited
    here): the registered lender ports this wave are Jupiter Lend and Slumlord;
    no MarginFi/Project 0 lender port is prescribed, so even a fully proven
    observation could not be admitted yet. Offline the observation is blocked
    anyway: the snapshot stays None and liquidity stays unknown (None), never
    fabricated zero.
    """

    from src.lending.agg03_financing_ports import (
        JupiterLendFinancingPort,  # noqa: F401  (read-only registry check)
        SlumlordFinancingPort,  # noqa: F401
    )

    registered_lender_ids = {
        JupiterLendFinancingPort.lender_id,
        SlumlordFinancingPort.lender_id,
    }
    blockers = list(observation.blockers)
    if not asset_id.strip():
        blockers.append("FINANCING_ASSET_ID_REQUIRED")
    if not state_fingerprint.strip():
        blockers.append("FINANCING_STATE_FINGERPRINT_REQUIRED")
    if "marginfi" not in registered_lender_ids:
        blockers.append(BLOCKER_FINANCING_PORT_NOT_PRESCRIBED)
    digest = observation.evidence_digest
    return MarginfiFinancingAdmission(
        observation_digest=digest,
        snapshot=None,
        available_liquidity_base_units=None,
        blockers=tuple(sorted(set(blockers))),
    )


@dataclass(frozen=True, slots=True)
class MarginfiBankCapitalEdgeGate:
    """Capacity-edge emission verdict; ``edge`` is None until fully proven."""

    edge: None
    blocker: str
    blockers: tuple[str, ...]
    note: str


def bank_capital_edge_gate(
    observation: MarginfiBankCapacityObservation,
) -> MarginfiBankCapitalEdgeGate:
    """Gate edge emission behind rooted-RPC proof; the graph owner is frozen.

    The FlashCapitalGraph whitelist contains ``marginfi``/``project0``, so a
    forged edge could type-check; this gate is the control point that refuses
    to construct one offline and never returns an edge.
    """

    if BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED in observation.blockers:
        return MarginfiBankCapitalEdgeGate(
            edge=None,
            blocker=BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED,
            blockers=observation.blockers,
            note=(
                "no live rooted-RPC snapshot with independent quorum was "
                "authorized; offline fixture evidence never qualifies an edge"
            ),
        )
    if observation.effective_capacity_base_units is None:
        return MarginfiBankCapitalEdgeGate(
            edge=None,
            blocker=BLOCKER_MISSING_EFFECTIVE_FLASH_CAP,
            blockers=observation.blockers,
            note="effective flash borrow cap is unknown, not zero",
        )
    return MarginfiBankCapitalEdgeGate(
        edge=None,
        blocker=BLOCKER_GRAPH_ALLOWANCE_PENDING,
        blockers=observation.blockers,
        note=(
            "FlashCapitalGraph positive emission for project0/marginfi "
            "requires full evidence and independent quorum; graph owner is "
            "frozen this wave"
        ),
    )


__all__ = [
    "BANK_TOKEN_2022_FLAG",
    "BLOCKER_FINANCING_PORT_NOT_PRESCRIBED",
    "BLOCKER_GRAPH_ALLOWANCE_PENDING",
    "BLOCKER_GROUP_PAUSED",
    "BLOCKER_LIVE_ENUMERATION_NOT_AUTHORIZED",
    "BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED",
    "BLOCKER_MISSING_EFFECTIVE_FLASH_CAP",
    "BLOCKER_OPERATOR_ACCOUNT_INPUT_REQUIRED",
    "BankReaderPins",
    "BankShareValuation",
    "FEE_ROUNDING_RULE",
    "GAP_ACCOUNT_PDA_SEED_UNPINNED",
    "GAP_ASSET_SHARE_VALUE_UNPINNED",
    "GAP_BANK_PDA_SEED_UNPINNED",
    "GAP_BANK_SOURCE_PROVENANCE_UNPROVEN",
    "GAP_BORROW_LIMIT_SEMANTICS_UNPINNED",
    "GAP_EMISSIONS_UNPINNED",
    "GAP_GROUP_PAUSE_UNPROVEN",
    "GAP_LAST_UPDATE_UNPINNED",
    "GAP_LIABILITY_SHARE_VALUE_UNPINNED",
    "GAP_LIQUIDITY_SHARES_UNPINNED",
    "GAP_ORACLE_PRICE_UNPROVEN",
    "I80F48_FRACTIONAL_BITS",
    "LIQUIDITY_VAULT_AUTHORITY_SEED",
    "MarginfiAccountEligibility",
    "MarginfiBankCapacityObservation",
    "MarginfiBankCapitalEdgeGate",
    "MarginfiBankDiscoveryError",
    "MarginfiBankDiscoveryRejectionCode",
    "MarginfiCapture",
    "MarginfiFinancingAdmission",
    "MarginfiLiveEnumerationPlan",
    "P0DiscoveryFacts",
    "P0_OFFLINE_FACTS_PATH",
    "P0_SOURCE_GIT_VERSION",
    "P0_SOURCE_PIN",
    "READER_CAPACITY_DERIVATION_UNPROVEN",
    "READER_DECODER_GENERATION",
    "READER_DECODER_IDENTITY",
    "READER_EXECUTION_AUTHORITY",
    "READER_WALLETLESS_MODE",
    "admit_bank_financing_snapshot",
    "bank_capital_edge_gate",
    "compute_origination_fee",
    "compute_share_valuation",
    "decode_bank_capture",
    "decode_liquidity_vault_capture",
    "derive_bank_liquidity_vault_authority",
    "discover_banks",
    "evaluate_existing_account_eligibility",
    "load_bank_reader_pins",
    "load_p0_discovery_facts",
    "observe_bank_capacity",
    "plan_live_bank_enumeration",
]
