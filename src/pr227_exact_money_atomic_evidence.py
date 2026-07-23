"""PR-227 exact money, asset identity and atomic execution evidence gate.

This module is an offline/dependency-gated checkpoint for the Pass 8/9 PR-227
roadmap. It validates exact base-unit money, cluster-bound asset identity and
atomic plan/simulation evidence before any future signer/sender boundary may use
those artifacts. It never signs, submits, calls RPC/Jito, reads private keys or
enables live trading.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
import hashlib
import json
import math
import re
from typing import Mapping, Sequence

PR227_SCHEMA_VERSION = "pr227.exact-money-atomic-evidence.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_ALPHABET = frozenset(_B58)
_U64_MAX = (1 << 64) - 1
_U128_MAX = (1 << 128) - 1
_MAX_V0_ALT_ACCOUNTS = 64


class PR227Error(ValueError):
    """Raised when PR-227 evidence fails closed."""


class ReadinessStatus(StrEnum):
    READY_DEPENDENCY_GATED = "READY_DEPENDENCY_GATED"
    BLOCKED = "BLOCKED"


class RoundingPolicy(StrEnum):
    EXACT = "EXACT"
    FLOOR_WITH_REMAINDER = "FLOOR_WITH_REMAINDER"
    CEIL_WITH_REMAINDER = "CEIL_WITH_REMAINDER"


@dataclass(frozen=True, slots=True)
class ExactBaseUnit:
    """Non-coercive integer amount with an explicit wire/intermediate bound."""

    value: int
    bound: str = "u64"

    def __post_init__(self) -> None:
        _strict_int(self.value, "value")
        if self.value < 0:
            raise PR227Error("PR227_NEGATIVE_BASE_UNIT")
        if self.bound == "u64":
            if self.value > _U64_MAX:
                raise PR227Error("PR227_U64_AMOUNT_OVERFLOW")
        elif self.bound == "u128":
            if self.value > _U128_MAX:
                raise PR227Error("PR227_U128_AMOUNT_OVERFLOW")
        else:
            raise PR227Error("PR227_UNKNOWN_AMOUNT_BOUND")


@dataclass(frozen=True, slots=True)
class UiToBaseUnitConversion:
    """Auditable UI amount to base-unit conversion evidence."""

    numerator: int
    denominator: int
    decimals: int
    rounding_policy: RoundingPolicy
    base_units: ExactBaseUnit
    remainder_numerator: int

    def __post_init__(self) -> None:
        _strict_int(self.numerator, "numerator")
        _strict_positive_int(self.denominator, "denominator")
        _strict_decimal_count(self.decimals)
        _strict_int(self.remainder_numerator, "remainder_numerator")
        if self.numerator < 0 or self.remainder_numerator < 0:
            raise PR227Error("PR227_NEGATIVE_CONVERSION_VALUE")
        scaled = self.numerator * (10**self.decimals)
        quotient, remainder = divmod(scaled, self.denominator)
        if self.rounding_policy is RoundingPolicy.EXACT:
            if remainder != 0 or self.base_units.value != quotient:
                raise PR227Error("PR227_EXACT_CONVERSION_HAS_REMAINDER")
            if self.remainder_numerator != 0:
                raise PR227Error("PR227_EXACT_CONVERSION_REMAINDER_RECORDED")
        elif self.rounding_policy is RoundingPolicy.FLOOR_WITH_REMAINDER:
            if (
                self.base_units.value != quotient
                or self.remainder_numerator != remainder
            ):
                raise PR227Error("PR227_FLOOR_CONVERSION_MISMATCH")
        elif self.rounding_policy is RoundingPolicy.CEIL_WITH_REMAINDER:
            expected = quotient + (1 if remainder else 0)
            if (
                self.base_units.value != expected
                or self.remainder_numerator != remainder
            ):
                raise PR227Error("PR227_CEIL_CONVERSION_MISMATCH")
        else:
            raise PR227Error("PR227_UNKNOWN_ROUNDING_POLICY")


@dataclass(frozen=True, slots=True)
class AssetIdentity:
    """Cluster-bound asset identity."""

    cluster_genesis_hash: str
    mint_pubkey: str
    token_program_pubkey: str
    rooted_mint_bytes_hash: str
    decimals: int
    metadata_slot: int
    extensions: tuple[str, ...] = ()
    symbol: str | None = None

    def __post_init__(self) -> None:
        _digest(self.cluster_genesis_hash, "cluster_genesis_hash")
        _pubkey(self.mint_pubkey, "mint_pubkey")
        _pubkey(self.token_program_pubkey, "token_program_pubkey")
        _digest(self.rooted_mint_bytes_hash, "rooted_mint_bytes_hash")
        _strict_decimal_count(self.decimals)
        _strict_non_negative_int(self.metadata_slot, "metadata_slot")
        normalized_extensions = tuple(
            _require_text(ext, "extension") for ext in self.extensions
        )
        if len(normalized_extensions) != len(set(normalized_extensions)):
            raise PR227Error("PR227_DUPLICATE_TOKEN_EXTENSION")
        object.__setattr__(self, "extensions", normalized_extensions)
        if self.symbol is not None:
            _require_text(self.symbol, "symbol")

    @property
    def asset_hash(self) -> str:
        return _hash_json(_dataclass_payload(self))


@dataclass(frozen=True, slots=True)
class TokenAmount:
    asset: AssetIdentity
    amount: ExactBaseUnit

    def __post_init__(self) -> None:
        if not isinstance(self.asset, AssetIdentity):
            raise PR227Error("PR227_TOKEN_AMOUNT_ASSET_REQUIRED")
        if not isinstance(self.amount, ExactBaseUnit):
            raise PR227Error("PR227_TOKEN_AMOUNT_BASE_UNIT_REQUIRED")


@dataclass(frozen=True, slots=True)
class ProtocolPinEvidence:
    protocol: str
    program_pubkey: str
    materialized_program_bytes_hash: str
    materialized_program_bytes_len: int
    release_registry_hash: str
    source_slot: int

    def __post_init__(self) -> None:
        _require_text(self.protocol, "protocol")
        _pubkey(self.program_pubkey, "program_pubkey")
        _digest(self.materialized_program_bytes_hash, "materialized_program_bytes_hash")
        _strict_positive_int(
            self.materialized_program_bytes_len,
            "materialized_program_bytes_len",
        )
        _digest(self.release_registry_hash, "release_registry_hash")
        _strict_non_negative_int(self.source_slot, "source_slot")

    @property
    def pin_hash(self) -> str:
        return _hash_json(_dataclass_payload(self))


@dataclass(frozen=True, slots=True)
class AltSnapshotEvidence:
    account_pubkey: str
    raw_account_hash: str
    source_slot: int
    current_slot: int
    addresses: tuple[str, ...]
    deactivation_slot: int | None = None
    last_extended_slot: int | None = None
    last_extended_slot_start_index: int | None = None

    def __post_init__(self) -> None:
        _pubkey(self.account_pubkey, "account_pubkey")
        _digest(self.raw_account_hash, "raw_account_hash")
        _strict_non_negative_int(self.source_slot, "source_slot")
        _strict_non_negative_int(self.current_slot, "current_slot")
        if self.source_slot > self.current_slot:
            raise PR227Error("PR227_ALT_SOURCE_SLOT_IN_FUTURE")
        if len(self.addresses) > _MAX_V0_ALT_ACCOUNTS:
            raise PR227Error("PR227_ALT_V0_ACCOUNT_LIMIT_EXCEEDED")
        normalized_addresses = tuple(
            _pubkey(address, "alt_address") for address in self.addresses
        )
        if len(normalized_addresses) != len(set(normalized_addresses)):
            raise PR227Error("PR227_ALT_DUPLICATE_ADDRESS")
        object.__setattr__(self, "addresses", normalized_addresses)
        if self.deactivation_slot is not None:
            _strict_non_negative_int(self.deactivation_slot, "deactivation_slot")
            if self.deactivation_slot <= self.current_slot:
                raise PR227Error("PR227_ALT_DEACTIVATED")
        if self.last_extended_slot is not None:
            _strict_non_negative_int(self.last_extended_slot, "last_extended_slot")
            if self.last_extended_slot > self.current_slot:
                raise PR227Error("PR227_ALT_LAST_EXTENDED_IN_FUTURE")
        if self.last_extended_slot_start_index is not None:
            _strict_non_negative_int(
                self.last_extended_slot_start_index,
                "last_extended_slot_start_index",
            )
            if self.last_extended_slot_start_index > len(self.addresses):
                raise PR227Error("PR227_ALT_START_INDEX_OUT_OF_RANGE")

    @property
    def alt_hash(self) -> str:
        return _hash_json(_dataclass_payload(self))


@dataclass(frozen=True, slots=True)
class SimulationEnvelopeEvidence:
    rpc_endpoint_id: str
    cluster_genesis_hash: str
    request_id: str
    jsonrpc_version: str
    api_version: str
    raw_request_hash: str
    raw_response_hash: str
    context_slot: int
    blockhash: str
    fee_lamports: ExactBaseUnit
    sig_verify: bool
    loaded_accounts_data_size: int
    retryable_error: bool = False

    def __post_init__(self) -> None:
        _require_text(self.rpc_endpoint_id, "rpc_endpoint_id")
        _digest(self.cluster_genesis_hash, "cluster_genesis_hash")
        _require_text(self.request_id, "request_id")
        if self.jsonrpc_version != "2.0":
            raise PR227Error("PR227_JSONRPC_VERSION_MISMATCH")
        _require_text(self.api_version, "api_version")
        _digest(self.raw_request_hash, "raw_request_hash")
        _digest(self.raw_response_hash, "raw_response_hash")
        _strict_non_negative_int(self.context_slot, "context_slot")
        _require_text(self.blockhash, "blockhash")
        if not isinstance(self.fee_lamports, ExactBaseUnit):
            raise PR227Error("PR227_SIMULATION_FEE_REQUIRED")
        _strict_bool(self.sig_verify, "sig_verify")
        _strict_non_negative_int(
            self.loaded_accounts_data_size,
            "loaded_accounts_data_size",
        )
        _strict_bool(self.retryable_error, "retryable_error")
        if self.retryable_error:
            raise PR227Error("PR227_RETRYABLE_SIMULATION_ERROR_NOT_AUTHORITY")

    @property
    def simulation_hash(self) -> str:
        return _hash_json(_dataclass_payload(self))


@dataclass(frozen=True, slots=True)
class CapitalReservationEvidence:
    opportunity_id: str
    wallet_pubkey: str
    generation: int
    expiry_slot: int
    reserved_lamports: ExactBaseUnit
    plan_hash: str

    def __post_init__(self) -> None:
        _require_text(self.opportunity_id, "opportunity_id")
        _pubkey(self.wallet_pubkey, "wallet_pubkey")
        _strict_positive_int(self.generation, "generation")
        _strict_non_negative_int(self.expiry_slot, "expiry_slot")
        if not isinstance(self.reserved_lamports, ExactBaseUnit):
            raise PR227Error("PR227_RESERVATION_AMOUNT_REQUIRED")
        _digest(self.plan_hash, "plan_hash")


@dataclass(frozen=True, slots=True)
class AtomicPlanEvidence:
    plan_id: str
    input_amount: TokenAmount
    leg_a_guaranteed_output: TokenAmount
    leg_b_input: TokenAmount
    leg_b_guaranteed_output: TokenAmount
    flash_repayment_lamports: ExactBaseUnit
    max_network_fee_lamports: ExactBaseUnit
    max_jito_tip_lamports: ExactBaseUnit
    compute_unit_limit: int
    compute_unit_price_micro_lamports: int
    blockhash: str
    alt_hashes: tuple[str, ...]
    protocol_pin_hashes: tuple[str, ...]
    caller_sequence_fingerprint: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.plan_id, "plan_id")
        for amount in (
            self.input_amount,
            self.leg_a_guaranteed_output,
            self.leg_b_input,
            self.leg_b_guaranteed_output,
        ):
            if not isinstance(amount, TokenAmount):
                raise PR227Error("PR227_PLAN_TOKEN_AMOUNT_REQUIRED")
        if self.leg_a_guaranteed_output.asset != self.leg_b_input.asset:
            raise PR227Error("PR227_LEG_B_INPUT_ASSET_MISMATCH")
        if self.input_amount.asset != self.leg_b_guaranteed_output.asset:
            raise PR227Error("PR227_ROUNDTRIP_ASSET_MISMATCH")
        if self.leg_b_input.amount.value < self.leg_a_guaranteed_output.amount.value:
            raise PR227Error("PR227_LEG_B_DUST_ACCOUNTING_MISSING")
        for lamports in (
            self.flash_repayment_lamports,
            self.max_network_fee_lamports,
            self.max_jito_tip_lamports,
        ):
            if not isinstance(lamports, ExactBaseUnit):
                raise PR227Error("PR227_PLAN_LAMPORT_AMOUNT_REQUIRED")
        _strict_positive_int(self.compute_unit_limit, "compute_unit_limit")
        _strict_non_negative_int(
            self.compute_unit_price_micro_lamports,
            "compute_unit_price_micro_lamports",
        )
        if self.compute_unit_limit > 1_400_000:
            raise PR227Error("PR227_COMPUTE_UNIT_LIMIT_OVER_CAP")
        if self.compute_unit_price_micro_lamports > 1_000_000:
            raise PR227Error("PR227_COMPUTE_UNIT_PRICE_OVER_CAP")
        _require_text(self.blockhash, "blockhash")
        object.__setattr__(
            self,
            "alt_hashes",
            _unique_digests(self.alt_hashes, "alt_hash"),
        )
        object.__setattr__(
            self,
            "protocol_pin_hashes",
            _unique_digests(self.protocol_pin_hashes, "protocol_pin_hash"),
        )
        if self.caller_sequence_fingerprint is not None:
            raise PR227Error("PR227_CALLER_SUPPLIED_FINGERPRINT_FORBIDDEN")

    @property
    def plan_hash(self) -> str:
        payload = _dataclass_payload(self)
        payload.pop("caller_sequence_fingerprint", None)
        return _hash_json(payload)

    @property
    def conservative_surplus_lamports(self) -> int:
        return (
            self.leg_b_guaranteed_output.amount.value
            - self.input_amount.amount.value
            - self.flash_repayment_lamports.value
            - self.max_network_fee_lamports.value
            - self.max_jito_tip_lamports.value
        )


@dataclass(frozen=True, slots=True)
class PreSignerFreshnessEvidence:
    plan_hash: str
    simulation_hash: str
    reservation: CapitalReservationEvidence
    current_block_height: int
    last_valid_block_height: int
    remaining_height_margin: int
    current_slot: int
    revalidated_alt_hashes: tuple[str, ...]
    message_hash: str

    def __post_init__(self) -> None:
        _digest(self.plan_hash, "plan_hash")
        _digest(self.simulation_hash, "simulation_hash")
        if not isinstance(self.reservation, CapitalReservationEvidence):
            raise PR227Error("PR227_RESERVATION_REQUIRED")
        if self.reservation.plan_hash != self.plan_hash:
            raise PR227Error("PR227_RESERVATION_PLAN_MISMATCH")
        _strict_positive_int(self.current_block_height, "current_block_height")
        _strict_positive_int(self.last_valid_block_height, "last_valid_block_height")
        _strict_non_negative_int(
            self.remaining_height_margin,
            "remaining_height_margin",
        )
        if (
            self.current_block_height + self.remaining_height_margin
            > self.last_valid_block_height
        ):
            raise PR227Error("PR227_BLOCKHASH_NOT_FRESH_BEFORE_SIGNER")
        _strict_non_negative_int(self.current_slot, "current_slot")
        if self.reservation.expiry_slot <= self.current_slot:
            raise PR227Error("PR227_RESERVATION_EXPIRED_BEFORE_SIGNER")
        object.__setattr__(
            self,
            "revalidated_alt_hashes",
            _unique_digests(self.revalidated_alt_hashes, "revalidated_alt_hash"),
        )
        _digest(self.message_hash, "message_hash")


@dataclass(frozen=True, slots=True)
class PR227EvidenceBundle:
    plan: AtomicPlanEvidence
    protocol_pins: tuple[ProtocolPinEvidence, ...]
    alts: tuple[AltSnapshotEvidence, ...]
    simulation: SimulationEnvelopeEvidence
    freshness: PreSignerFreshnessEvidence
    provider_plane_ready: bool
    secret_release_ready: bool

    def __post_init__(self) -> None:
        if not isinstance(self.plan, AtomicPlanEvidence):
            raise PR227Error("PR227_PLAN_REQUIRED")
        if not isinstance(self.simulation, SimulationEnvelopeEvidence):
            raise PR227Error("PR227_SIMULATION_REQUIRED")
        if not isinstance(self.freshness, PreSignerFreshnessEvidence):
            raise PR227Error("PR227_FRESHNESS_REQUIRED")
        _strict_bool(self.provider_plane_ready, "provider_plane_ready")
        _strict_bool(self.secret_release_ready, "secret_release_ready")
        if not self.provider_plane_ready:
            raise PR227Error("PR227_PR225_PROVIDER_PLANE_NOT_READY")
        if not self.secret_release_ready:
            raise PR227Error("PR227_PR228_TRUST_PLANE_NOT_READY")
        pin_hashes = tuple(pin.pin_hash for pin in self.protocol_pins)
        alt_hashes = tuple(alt.alt_hash for alt in self.alts)
        if tuple(sorted(pin_hashes)) != tuple(sorted(self.plan.protocol_pin_hashes)):
            raise PR227Error("PR227_PROTOCOL_PIN_SET_MISMATCH")
        if tuple(sorted(alt_hashes)) != tuple(sorted(self.plan.alt_hashes)):
            raise PR227Error("PR227_ALT_SET_MISMATCH")
        if self.freshness.plan_hash != self.plan.plan_hash:
            raise PR227Error("PR227_FRESHNESS_PLAN_HASH_MISMATCH")
        if self.freshness.simulation_hash != self.simulation.simulation_hash:
            raise PR227Error("PR227_FRESHNESS_SIMULATION_HASH_MISMATCH")
        if self.simulation.blockhash != self.plan.blockhash:
            raise PR227Error("PR227_SIMULATION_BLOCKHASH_MISMATCH")
        if (
            self.simulation.cluster_genesis_hash
            != self.plan.input_amount.asset.cluster_genesis_hash
        ):
            raise PR227Error("PR227_SIMULATION_CLUSTER_MISMATCH")
        if self.plan.conservative_surplus_lamports <= 0:
            raise PR227Error("PR227_CONSERVATIVE_SURPLUS_NOT_POSITIVE")

    @property
    def bundle_hash(self) -> str:
        return _hash_json(_dataclass_payload(self))


def evaluate_bundle(bundle: PR227EvidenceBundle) -> Mapping[str, object]:
    """Return a deterministic dependency-gated readiness verdict."""

    return {
        "schema": PR227_SCHEMA_VERSION,
        "status": ReadinessStatus.READY_DEPENDENCY_GATED.value,
        "reason_codes": ("PR227_READY_BUT_DEPENDS_ON_PR225_PR228",),
        "plan_hash": bundle.plan.plan_hash,
        "simulation_hash": bundle.simulation.simulation_hash,
        "bundle_hash": bundle.bundle_hash,
        "surplus_lamports": bundle.plan.conservative_surplus_lamports,
    }


def _dataclass_payload(value: object) -> dict[str, object]:
    if not is_dataclass(value) or isinstance(value, type):
        raise PR227Error("PR227_DATACLASS_PAYLOAD_REQUIRED")
    payload: dict[str, object] = {}
    for field in fields(value):
        payload[field.name] = _canonicalize(getattr(value, field.name))
    return payload


def _canonicalize(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _dataclass_payload(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return tuple(_canonicalize(item) for item in value)
    if isinstance(value, Mapping):
        return {
            str(key): _canonicalize(raw_value)
            for key, raw_value in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, float):
        raise PR227Error("PR227_FLOAT_NOT_CANONICAL")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        _canonicalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _hash_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _strict_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PR227Error(f"{name} must be a non-bool integer")


def _strict_positive_int(value: int, name: str) -> None:
    _strict_int(value, name)
    if value <= 0:
        raise PR227Error(f"{name} must be positive")


def _strict_non_negative_int(value: int, name: str) -> None:
    _strict_int(value, name)
    if value < 0:
        raise PR227Error(f"{name} must be non-negative")


def _strict_decimal_count(value: int) -> None:
    _strict_int(value, "decimals")
    if value < 0 or value > 255:
        raise PR227Error("PR227_DECIMALS_OUT_OF_U8_RANGE")


def _strict_bool(value: bool, name: str) -> None:
    if type(value) is not bool:
        raise PR227Error(f"{name} must be bool")


def _digest(value: str, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise PR227Error(f"{name} must be lowercase sha256")
    if value == "0" * 64:
        raise PR227Error(f"{name} cannot be placeholder digest")
    return value


def _require_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PR227Error(f"{name} is required")
    return value.strip()


def _pubkey(value: str, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise PR227Error(f"{name} is required")
    if any(char not in _B58_ALPHABET for char in value):
        raise PR227Error(f"{name} must be base58")
    decoded = _decode_base58(value)
    if len(decoded) != 32:
        raise PR227Error(f"{name} must decode to 32 bytes")
    return value


def _decode_base58(value: str) -> bytes:
    number = 0
    for char in value:
        number = number * 58 + _B58.index(char)
    raw = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    leading_zeroes = len(value) - len(value.lstrip("1"))
    return (b"\x00" * leading_zeroes) + raw


def _unique_digests(values: Sequence[str], name: str) -> tuple[str, ...]:
    digests = tuple(_digest(value, name) for value in values)
    if len(digests) != len(set(digests)):
        raise PR227Error(f"duplicate {name}")
    return digests


def reject_non_finite_numeric(value: object, name: str) -> None:
    """Tiny public helper for callers that still handle numeric config."""

    if isinstance(value, float) and not math.isfinite(value):
        raise PR227Error(f"{name} must be finite")


__all__ = [
    "AltSnapshotEvidence",
    "AssetIdentity",
    "AtomicPlanEvidence",
    "CapitalReservationEvidence",
    "ExactBaseUnit",
    "PR227EvidenceBundle",
    "PR227Error",
    "PR227_SCHEMA_VERSION",
    "PreSignerFreshnessEvidence",
    "ProtocolPinEvidence",
    "ReadinessStatus",
    "RoundingPolicy",
    "SimulationEnvelopeEvidence",
    "TokenAmount",
    "UiToBaseUnitConversion",
    "evaluate_bundle",
    "reject_non_finite_numeric",
]
