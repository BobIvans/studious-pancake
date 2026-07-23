"""Shared identities and cryptographic primitives for MPR-15."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum, StrEnum
import hashlib
import hmac
import json
import re
from typing import Iterable, Mapping

MPR15_SCHEMA = "mpr15.rooted-treasury-accounting.v1"
PR163_SCHEMA = MPR15_SCHEMA
MPR15_HASH_DOMAIN = "flashloan-bot/mpr15-rooted-treasury"
PR163_HASH_DOMAIN = MPR15_HASH_DOMAIN
WALLET_RPC_BUNDLE_SCHEMA = "mpr15.wallet-rpc-bundle.v1"
SIGNATURE_ALGORITHM = "hmac-sha256-hsm-v1"
_NANOSECONDS_PER_SECOND = 1_000_000_000
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_INDEX = {character: index for index, character in enumerate(_BASE58_ALPHABET)}
_MAX_RAW_RPC_BYTES = 1_000_000

class TreasuryAccountingError(ValueError):
    """Raised when treasury/accounting evidence is unsafe or inconsistent."""


class BalanceSource(StrEnum):
    CALLER_SUPPLIED = "caller_supplied"
    RUNTIME_FINALIZED_RPC_QUORUM = "runtime_finalized_rpc_quorum"


class WalletClassification(StrEnum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


class AccountingStage(IntEnum):
    PREDICTED = 10
    SIMULATED = 20
    CONFIRMED = 30
    FINALIZED = 40
    RECONCILED = 50
    BOOKED = 60

    @property
    def label(self) -> str:
        return self.name.lower()


_ALLOWED_STAGE_TRANSITIONS: dict[AccountingStage, AccountingStage] = {
    AccountingStage.PREDICTED: AccountingStage.SIMULATED,
    AccountingStage.SIMULATED: AccountingStage.CONFIRMED,
    AccountingStage.CONFIRMED: AccountingStage.FINALIZED,
    AccountingStage.FINALIZED: AccountingStage.RECONCILED,
    AccountingStage.RECONCILED: AccountingStage.BOOKED,
}


class RiskWindowKind(StrEnum):
    UTC_DAY = "utc_day"
    ROLLING_24H = "rolling_24h"
    DEPLOYMENT = "deployment"
    CANARY = "canary"


class LedgerEntryKind(StrEnum):
    FUNDING = "funding"
    WITHDRAWAL = "withdrawal"
    REALIZED_PNL = "realized_pnl"
    FEE = "fee"
    RENT_LOCKED = "rent_locked"
    RENT_REFUNDED = "rent_refunded"
    TIP = "tip"
    TRANSFER_FEE = "transfer_fee"
    FAILED_ATTEMPT_CHARGE = "failed_attempt_charge"
    UNRESOLVED_MAX_LOSS = "unresolved_max_loss"
    PROVIDER_SPEND = "provider_spend"


class PostingSide(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class LedgerAccountKind(StrEnum):
    CHAIN_WALLET = "chain_wallet"
    FUNDING_SOURCE = "funding_source"
    WITHDRAWAL_DESTINATION = "withdrawal_destination"
    PNL_INCOME = "pnl_income"
    PNL_LOSS = "pnl_loss"
    FEE_EXPENSE = "fee_expense"
    RENT_ASSET = "rent_asset"
    TIP_EXPENSE = "tip_expense"
    TRANSFER_FEE_EXPENSE = "transfer_fee_expense"
    FAILED_ATTEMPT_EXPENSE = "failed_attempt_expense"
    PROVIDER_EXPENSE = "provider_expense"
    UNRESOLVED_RESERVE = "unresolved_reserve"
    RISK_CONTRA = "risk_contra"


class AttemptOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class TreasuryScope(StrEnum):
    FUNDING = "treasury-funding"
    SWEEP = "treasury-sweep"


@dataclass(frozen=True, slots=True)
class AssetIdentity:
    """Canonical integer-accounting identity for one Solana asset."""

    cluster_genesis: str
    symbol: str
    mint: str
    token_program: str
    decimals: int

    def __post_init__(self) -> None:
        _require_pubkey(self.cluster_genesis, "cluster_genesis")
        _require_text(self.symbol, "symbol")
        _require_pubkey(self.mint, "mint")
        _require_pubkey(self.token_program, "token_program")
        _require_int(self.decimals, "decimals", lower=0, upper=18)

    @property
    def asset_key(self) -> str:
        return "|".join(
            (
                self.cluster_genesis,
                self.token_program,
                self.mint,
                str(self.decimals),
            )
        )

    def to_json(self) -> dict[str, object]:
        return {
            "cluster_genesis": self.cluster_genesis,
            "symbol": self.symbol,
            "mint": self.mint,
            "token_program": self.token_program,
            "decimals": self.decimals,
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, object]) -> AssetIdentity:
        return cls(
            cluster_genesis=_as_str(payload, "cluster_genesis"),
            symbol=_as_str(payload, "symbol"),
            mint=_as_str(payload, "mint"),
            token_program=_as_str(payload, "token_program"),
            decimals=_as_int(payload, "decimals"),
        )


@dataclass(frozen=True, slots=True)
class AssetAmount:
    asset: AssetIdentity
    base_units: int

    def __post_init__(self) -> None:
        _require_int(self.base_units, "base_units")

    def require_non_negative(self, field: str = "base_units") -> None:
        _require_int(self.base_units, field, lower=0)

    def __add__(self, other: AssetAmount) -> AssetAmount:
        _require_same_asset(self, other)
        return AssetAmount(self.asset, self.base_units + other.base_units)

    def __sub__(self, other: AssetAmount) -> AssetAmount:
        _require_same_asset(self, other)
        return AssetAmount(self.asset, self.base_units - other.base_units)

    def to_json(self) -> dict[str, object]:
        return {"asset": self.asset.to_json(), "base_units": str(self.base_units)}


@dataclass(frozen=True, slots=True)
class ProgramDeploymentAttestation:
    program_id: str
    program_data_hash: str
    deployment_slot: int
    authority_policy_hash: str

    def __post_init__(self) -> None:
        _require_pubkey(self.program_id, "program_id")
        _require_sha256(self.program_data_hash, "program_data_hash")
        _require_int(self.deployment_slot, "deployment_slot", lower=0)
        _require_sha256(self.authority_policy_hash, "authority_policy_hash")

    def to_json(self) -> dict[str, object]:
        return {
            "program_id": self.program_id,
            "program_data_hash": self.program_data_hash,
            "deployment_slot": self.deployment_slot,
            "authority_policy_hash": self.authority_policy_hash,
        }


@dataclass(frozen=True, slots=True)
class ChainRegistryManifest:
    cluster_genesis: str
    generation: int
    policy_hash: str
    created_at_ns: int
    programs: tuple[ProgramDeploymentAttestation, ...]

    def __post_init__(self) -> None:
        _require_pubkey(self.cluster_genesis, "cluster_genesis")
        _require_int(self.generation, "chain registry generation", lower=1)
        _require_sha256(self.policy_hash, "chain registry policy_hash")
        _require_int(self.created_at_ns, "created_at_ns", lower=0)
        if not self.programs:
            raise TreasuryAccountingError("chain registry programs are required")
        program_ids = [item.program_id for item in self.programs]
        _require_unique(program_ids, "chain registry program IDs")

    @property
    def manifest_hash(self) -> str:
        return domain_hash("mpr15/chain-registry", self.to_json())

    def to_json(self) -> dict[str, object]:
        return {
            "cluster_genesis": self.cluster_genesis,
            "generation": self.generation,
            "policy_hash": self.policy_hash,
            "created_at_ns": self.created_at_ns,
            "programs": [item.to_json() for item in self.programs],
        }


@dataclass(frozen=True, slots=True, init=False)
class VerifiedChainRegistry:
    manifest: ChainRegistryManifest
    signer_key_id: str
    signature: str
    signature_algorithm: str

    @classmethod
    def verify(
        cls,
        *,
        manifest: ChainRegistryManifest,
        signer_key_id: str,
        signature: str,
        trusted_keys: Mapping[str, bytes],
    ) -> VerifiedChainRegistry:
        _require_text(signer_key_id, "chain registry signer_key_id")
        key = _trusted_key(trusted_keys, signer_key_id)
        _verify_hmac(
            key=key,
            domain="mpr15/chain-registry-signature",
            payload_hash=manifest.manifest_hash,
            signature=signature,
        )
        instance = object.__new__(cls)
        object.__setattr__(instance, "manifest", manifest)
        object.__setattr__(instance, "signer_key_id", signer_key_id)
        object.__setattr__(instance, "signature", signature)
        object.__setattr__(instance, "signature_algorithm", SIGNATURE_ALGORITHM)
        return instance

    def require_program(self, program_id: str) -> None:
        if program_id not in {item.program_id for item in self.manifest.programs}:
            raise TreasuryAccountingError(
                "program is absent from signed chain registry"
            )


@dataclass(frozen=True, slots=True)
class RpcProviderRegistryEntry:
    provider_id: str
    endpoint_identity_hash: str
    operator_group_hash: str
    network_path_group_hash: str
    allowed_cluster_genesis: str
    active: bool = True

    def __post_init__(self) -> None:
        _require_text(self.provider_id, "provider_id")
        _require_sha256(self.endpoint_identity_hash, "endpoint_identity_hash")
        _require_sha256(self.operator_group_hash, "operator_group_hash")
        _require_sha256(self.network_path_group_hash, "network_path_group_hash")
        _require_pubkey(self.allowed_cluster_genesis, "allowed_cluster_genesis")

    def to_json(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "endpoint_identity_hash": self.endpoint_identity_hash,
            "operator_group_hash": self.operator_group_hash,
            "network_path_group_hash": self.network_path_group_hash,
            "allowed_cluster_genesis": self.allowed_cluster_genesis,
            "active": self.active,
        }


@dataclass(frozen=True, slots=True)
class RpcProviderRegistryManifest:
    generation: int
    policy_hash: str
    created_at_ns: int
    entries: tuple[RpcProviderRegistryEntry, ...]

    def __post_init__(self) -> None:
        _require_int(self.generation, "provider registry generation", lower=1)
        _require_sha256(self.policy_hash, "provider registry policy_hash")
        _require_int(self.created_at_ns, "provider registry created_at_ns", lower=0)
        if len(self.entries) < 2:
            raise TreasuryAccountingError(
                "provider registry requires at least two entries"
            )
        _require_unique([item.provider_id for item in self.entries], "provider IDs")

    @property
    def manifest_hash(self) -> str:
        return domain_hash("mpr15/provider-registry", self.to_json())

    def to_json(self) -> dict[str, object]:
        return {
            "generation": self.generation,
            "policy_hash": self.policy_hash,
            "created_at_ns": self.created_at_ns,
            "entries": [item.to_json() for item in self.entries],
        }


@dataclass(frozen=True, slots=True, init=False)
class VerifiedRpcProviderRegistry:
    manifest: RpcProviderRegistryManifest
    signer_key_id: str
    signature: str
    signature_algorithm: str

    @classmethod
    def verify(
        cls,
        *,
        manifest: RpcProviderRegistryManifest,
        signer_key_id: str,
        signature: str,
        trusted_keys: Mapping[str, bytes],
    ) -> VerifiedRpcProviderRegistry:
        _require_text(signer_key_id, "provider registry signer_key_id")
        key = _trusted_key(trusted_keys, signer_key_id)
        _verify_hmac(
            key=key,
            domain="mpr15/provider-registry-signature",
            payload_hash=manifest.manifest_hash,
            signature=signature,
        )
        instance = object.__new__(cls)
        object.__setattr__(instance, "manifest", manifest)
        object.__setattr__(instance, "signer_key_id", signer_key_id)
        object.__setattr__(instance, "signature", signature)
        object.__setattr__(instance, "signature_algorithm", SIGNATURE_ALGORITHM)
        return instance

    def entry(self, provider_id: str) -> RpcProviderRegistryEntry:
        for entry in self.manifest.entries:
            if entry.provider_id == provider_id:
                return entry
        raise TreasuryAccountingError("RPC provider is absent from signed registry")


@dataclass(frozen=True, slots=True)
class WalletRegistryEntry:
    cluster_genesis: str
    wallet_pubkey: str
    purpose: str
    signer_backend: str
    owner_custodian: str
    classification: WalletClassification
    approved_programs: tuple[str, ...]
    approved_token_accounts: tuple[str, ...]
    protected_reserve: AssetAmount
    maximum_exposure: AssetAmount
    funding_policy_id: str
    sweep_policy_id: str
    registry_generation: int
    registry_manifest_hash: str
    chain_registry: VerifiedChainRegistry
    retirement_state: str = "active"

    def __post_init__(self) -> None:
        _require_pubkey(self.cluster_genesis, "cluster_genesis")
        _require_pubkey(self.wallet_pubkey, "wallet_pubkey")
        for field, value in (
            ("purpose", self.purpose),
            ("signer_backend", self.signer_backend),
            ("owner_custodian", self.owner_custodian),
            ("retirement_state", self.retirement_state),
        ):
            _require_text(value, field)
        _require_sha256(self.funding_policy_id, "funding_policy_id")
        _require_sha256(self.sweep_policy_id, "sweep_policy_id")
        _require_int(self.registry_generation, "registry_generation", lower=1)
        _require_sha256(self.registry_manifest_hash, "registry_manifest_hash")
        if self.cluster_genesis != self.chain_registry.manifest.cluster_genesis:
            raise TreasuryAccountingError("wallet registry cluster is not chain-bound")
        if self.registry_generation < self.chain_registry.manifest.generation:
            raise TreasuryAccountingError("wallet registry generation is stale")
        if not self.approved_programs:
            raise TreasuryAccountingError("approved_programs is required")
        for program_id in self.approved_programs:
            _require_pubkey(program_id, "approved program")
            self.chain_registry.require_program(program_id)
        for account in self.approved_token_accounts:
            _require_pubkey(account, "approved token account")
        _require_unique(self.approved_programs, "approved programs")
        _require_unique(self.approved_token_accounts, "approved token accounts")
        if self.protected_reserve.asset != self.maximum_exposure.asset:
            raise TreasuryAccountingError("reserve and exposure assets differ")
        if self.protected_reserve.asset.cluster_genesis != self.cluster_genesis:
            raise TreasuryAccountingError("wallet cluster differs from asset cluster")
        self.chain_registry.require_program(self.protected_reserve.asset.token_program)
        self.protected_reserve.require_non_negative("protected_reserve")
        self.maximum_exposure.require_non_negative("maximum_exposure")
        if self.maximum_exposure.base_units < self.protected_reserve.base_units:
            raise TreasuryAccountingError("maximum_exposure below protected reserve")

    def to_json(self) -> dict[str, object]:
        return {
            "cluster_genesis": self.cluster_genesis,
            "wallet_pubkey": self.wallet_pubkey,
            "purpose": self.purpose,
            "signer_backend": self.signer_backend,
            "owner_custodian": self.owner_custodian,
            "classification": self.classification.value,
            "approved_programs": list(self.approved_programs),
            "approved_token_accounts": list(self.approved_token_accounts),
            "protected_reserve": self.protected_reserve.to_json(),
            "maximum_exposure": self.maximum_exposure.to_json(),
            "funding_policy_id": self.funding_policy_id,
            "sweep_policy_id": self.sweep_policy_id,
            "registry_generation": self.registry_generation,
            "registry_manifest_hash": self.registry_manifest_hash,
            "chain_registry_manifest_hash": self.chain_registry.manifest.manifest_hash,
            "retirement_state": self.retirement_state,
        }


@dataclass(frozen=True, slots=True)
class TokenAccountSnapshot:
    account_pubkey: str
    owner_pubkey: str
    amount: AssetAmount
    mint: str
    token_program: str
    layout_version: str
    account_hash: str
    delegated_authority: str | None = None
    close_authority: str | None = None

    def __post_init__(self) -> None:
        _require_pubkey(self.account_pubkey, "account_pubkey")
        _require_pubkey(self.owner_pubkey, "owner_pubkey")
        _require_pubkey(self.mint, "mint")
        _require_pubkey(self.token_program, "token_program")
        _require_text(self.layout_version, "layout_version")
        _require_sha256(self.account_hash, "account_hash")
        self.amount.require_non_negative("token_amount")
        if self.amount.asset.mint != self.mint:
            raise TreasuryAccountingError("token account mint mismatch")
        if self.amount.asset.token_program != self.token_program:
            raise TreasuryAccountingError("token account program mismatch")
        if self.delegated_authority is not None:
            _require_pubkey(self.delegated_authority, "delegated_authority")
        if self.close_authority is not None:
            _require_pubkey(self.close_authority, "close_authority")

    def to_json(self) -> dict[str, object]:
        return {
            "account_pubkey": self.account_pubkey,
            "owner_pubkey": self.owner_pubkey,
            "amount": self.amount.to_json(),
            "mint": self.mint,
            "token_program": self.token_program,
            "layout_version": self.layout_version,
            "account_hash": self.account_hash,
            "delegated_authority": self.delegated_authority,
            "close_authority": self.close_authority,
        }


def reject_caller_supplied_wallet_balance(value: object) -> None:
    del value
    raise TreasuryAccountingError(
        "caller-supplied wallet balances cannot be used for live admission"
    )


def sign_hmac_payload(*, key: bytes, domain: str, payload_hash: str) -> str:
    if not isinstance(key, bytes) or len(key) < 32:
        raise TreasuryAccountingError(
            "trusted signing key must contain at least 32 bytes"
        )
    _require_text(domain, "signature domain")
    _require_sha256(payload_hash, "signature payload_hash")
    return hmac.new(
        key,
        domain.encode("utf-8") + b"\0" + payload_hash.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def domain_hash(domain: str, payload: object) -> str:
    _require_text(domain, "hash domain")
    raw = _canonical_json(_jsonable(payload)).encode("utf-8")
    return hashlib.sha256(domain.encode("utf-8") + b"\0" + raw).hexdigest()


def _verify_hmac(*, key: bytes, domain: str, payload_hash: str, signature: str) -> None:
    _require_sha256(signature, "signature")
    expected = sign_hmac_payload(key=key, domain=domain, payload_hash=payload_hash)
    if not hmac.compare_digest(expected, signature):
        raise TreasuryAccountingError("cryptographic signature verification failed")


def _trusted_key(trusted_keys: Mapping[str, bytes], key_id: str) -> bytes:
    key = trusted_keys.get(key_id)
    if key is None:
        raise TreasuryAccountingError("signer key is absent from trusted registry")
    if not isinstance(key, bytes) or len(key) < 32:
        raise TreasuryAccountingError("trusted key material is invalid")
    return key


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _jsonable(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, IntEnum):
        return value.name.lower()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if hasattr(value, "to_json"):
        return _jsonable(value.to_json())
    raise TreasuryAccountingError(f"unsupported JSON value: {type(value).__name__}")


def _require_text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise TreasuryAccountingError(f"{field} is required")


def _require_sha256(value: str, field: str) -> None:
    if not isinstance(value, str) or _HEX_64_RE.fullmatch(value) is None:
        raise TreasuryAccountingError(f"{field} must be lowercase sha256 hex")


def _require_pubkey(value: str, field: str) -> None:
    _require_text(value, field)
    try:
        decoded = _base58_decode(value)
    except TreasuryAccountingError as exc:
        raise TreasuryAccountingError(
            f"{field} must be canonical base58 encoding of exactly 32 bytes"
        ) from exc
    if len(decoded) != 32 or _base58_encode(decoded) != value:
        raise TreasuryAccountingError(
            f"{field} must be canonical base58 encoding of exactly 32 bytes"
        )


def _base58_decode(value: str) -> bytes:
    number = 0
    for character in value:
        index = _BASE58_INDEX.get(character)
        if index is None:
            raise TreasuryAccountingError("invalid base58 character")
        number = number * 58 + index
    body = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    leading_zeroes = len(value) - len(value.lstrip("1"))
    return b"\0" * leading_zeroes + body


def _base58_encode(value: bytes) -> str:
    leading_zeroes = len(value) - len(value.lstrip(b"\0"))
    number = int.from_bytes(value, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = _BASE58_ALPHABET[remainder] + encoded
    return "1" * leading_zeroes + encoded


def _require_int(
    value: int,
    field: str,
    *,
    lower: int | None = None,
    upper: int | None = None,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TreasuryAccountingError(f"{field} must be an integer")
    if lower is not None and value < lower:
        raise TreasuryAccountingError(f"{field} below minimum")
    if upper is not None and value > upper:
        raise TreasuryAccountingError(f"{field} above maximum")


def _require_unique(values: Iterable[str], field: str) -> None:
    materialized = tuple(values)
    if len(materialized) != len(set(materialized)):
        raise TreasuryAccountingError(f"duplicate {field}")


def _require_same_asset(first: AssetAmount, second: AssetAmount) -> None:
    if first.asset != second.asset:
        raise TreasuryAccountingError("cannot mix different assets")


def _datetime_to_ns(value: datetime) -> int:
    if value.tzinfo != timezone.utc:
        raise TreasuryAccountingError("datetime must be UTC")
    return int(value.timestamp()) * _NANOSECONDS_PER_SECOND


def _as_mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    return _ensure_mapping(payload.get(key), key)


def _ensure_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise TreasuryAccountingError(f"{field} must be an object")
    return value


def _as_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise TreasuryAccountingError(f"{key} must be text")
    return value


def _as_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TreasuryAccountingError(f"{key} must be integer")
    return value
