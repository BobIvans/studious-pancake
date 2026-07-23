"""Rooted finalized wallet evidence and solvency admission for MPR-15."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
from typing import Mapping, Sequence

from .mpr15_common import (
    AssetAmount, AssetIdentity, BalanceSource, MPR15_HASH_DOMAIN, MPR15_SCHEMA,
    TokenAccountSnapshot, TreasuryAccountingError, VerifiedRpcProviderRegistry,
    WALLET_RPC_BUNDLE_SCHEMA, WalletRegistryEntry, _MAX_RAW_RPC_BYTES, _as_int,
    _as_mapping, _as_str, _ensure_mapping, _require_int, _require_pubkey,
    _require_same_asset, _require_sha256, _require_text, _require_unique,
    domain_hash,
)

@dataclass(frozen=True, slots=True)
class ObservationPolicy:
    minimum_quorum: int
    max_age_ns: int
    max_future_skew_ns: int
    max_collection_span_ns: int
    max_root_slot_skew: int
    max_root_lag_slots: int

    def __post_init__(self) -> None:
        _require_int(self.minimum_quorum, "minimum_quorum", lower=2)
        _require_int(self.max_age_ns, "max_age_ns", lower=1)
        _require_int(self.max_future_skew_ns, "max_future_skew_ns", lower=0)
        _require_int(self.max_collection_span_ns, "max_collection_span_ns", lower=1)
        _require_int(self.max_root_slot_skew, "max_root_slot_skew", lower=0)
        _require_int(self.max_root_lag_slots, "max_root_lag_slots", lower=0)


@dataclass(frozen=True, slots=True)
class RpcEndpointEvidence:
    provider_id: str
    request_hash: str
    raw_response_json: str
    response_hash: str
    transport_evidence_hash: str
    commitment: str
    context_slot: int
    root_slot: int
    collected_at_ns: int

    def __post_init__(self) -> None:
        _require_text(self.provider_id, "provider_id")
        _require_sha256(self.request_hash, "request_hash")
        _require_text(self.raw_response_json, "raw_response_json")
        if len(self.raw_response_json.encode("utf-8")) > _MAX_RAW_RPC_BYTES:
            raise TreasuryAccountingError(
                "raw RPC response exceeds bounded evidence size"
            )
        _require_sha256(self.response_hash, "response_hash")
        actual_hash = hashlib.sha256(self.raw_response_json.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(actual_hash, self.response_hash):
            raise TreasuryAccountingError("raw RPC response hash mismatch")
        _require_sha256(self.transport_evidence_hash, "transport_evidence_hash")
        if self.commitment != "finalized":
            raise TreasuryAccountingError("wallet observations require finalized RPC")
        _require_int(self.context_slot, "context_slot", lower=0)
        _require_int(self.root_slot, "root_slot", lower=0)
        _require_int(self.collected_at_ns, "collected_at_ns", lower=0)
        if self.root_slot < self.context_slot:
            raise TreasuryAccountingError("root_slot must cover context_slot")

    def to_json(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "request_hash": self.request_hash,
            "response_hash": self.response_hash,
            "transport_evidence_hash": self.transport_evidence_hash,
            "commitment": self.commitment,
            "context_slot": self.context_slot,
            "root_slot": self.root_slot,
            "collected_at_ns": self.collected_at_ns,
        }


@dataclass(frozen=True, slots=True)
class _DecodedWalletState:
    cluster_genesis: str
    wallet_pubkey: str
    native_balance: AssetAmount
    token_accounts: tuple[TokenAccountSnapshot, ...]
    context_slot: int
    root_slot: int

    @property
    def state_hash(self) -> str:
        return domain_hash(
            "mpr15/decoded-wallet-state",
            {
                "cluster_genesis": self.cluster_genesis,
                "wallet_pubkey": self.wallet_pubkey,
                "native_balance": self.native_balance.to_json(),
                "token_accounts": [item.to_json() for item in self.token_accounts],
            },
        )


@dataclass(frozen=True, slots=True, init=False)
class WalletObservationPackage:
    registry_entry: WalletRegistryEntry
    provider_registry: VerifiedRpcProviderRegistry
    native_balance: AssetAmount
    token_accounts: tuple[TokenAccountSnapshot, ...]
    endpoint_evidence: tuple[RpcEndpointEvidence, ...]
    observed_at_ns: int
    policy_hash: str
    decoder_version: str
    decoded_state_hash: str
    observation_policy: ObservationPolicy
    source: BalanceSource

    def __init__(self) -> None:
        raise TypeError(
            "WalletObservationPackage must be built by from_rpc_quorum()"
        )

    @classmethod
    def from_rpc_quorum(
        cls,
        *,
        registry_entry: WalletRegistryEntry,
        provider_registry: VerifiedRpcProviderRegistry,
        endpoint_evidence: Sequence[RpcEndpointEvidence],
        policy_hash: str,
        decoder_version: str,
        observation_policy: ObservationPolicy,
    ) -> WalletObservationPackage:
        _require_sha256(policy_hash, "policy_hash")
        _require_text(decoder_version, "decoder_version")
        evidence = tuple(endpoint_evidence)
        if len(evidence) < observation_policy.minimum_quorum:
            raise TreasuryAccountingError("wallet observation requires RPC quorum")
        provider_ids = [item.provider_id for item in evidence]
        _require_unique(provider_ids, "RPC provider IDs")
        request_hashes = {item.request_hash for item in evidence}
        if len(request_hashes) != 1:
            raise TreasuryAccountingError("RPC quorum did not execute the same request")
        collected = [item.collected_at_ns for item in evidence]
        if max(collected) - min(collected) > observation_policy.max_collection_span_ns:
            raise TreasuryAccountingError("RPC quorum collection span exceeds policy")

        registry_entries = [
            provider_registry.entry(item.provider_id) for item in evidence
        ]
        for provider in registry_entries:
            if not provider.active:
                raise TreasuryAccountingError("inactive RPC provider used in quorum")
            if provider.allowed_cluster_genesis != registry_entry.cluster_genesis:
                raise TreasuryAccountingError("RPC provider registry cluster mismatch")
        _require_unique(
            [item.operator_group_hash for item in registry_entries],
            "RPC operator groups",
        )
        _require_unique(
            [item.network_path_group_hash for item in registry_entries],
            "RPC network path groups",
        )

        decoded = tuple(
            _decode_wallet_rpc_bundle(
                item,
                registry_entry=registry_entry,
                decoder_version=decoder_version,
            )
            for item in evidence
        )
        state_hashes = {item.state_hash for item in decoded}
        if len(state_hashes) != 1:
            raise TreasuryAccountingError("RPC quorum decoded different wallet states")
        root_slots = [item.root_slot for item in decoded]
        if max(root_slots) - min(root_slots) > observation_policy.max_root_slot_skew:
            raise TreasuryAccountingError("RPC quorum root-slot skew exceeds policy")

        canonical = decoded[0]
        token_pubkeys = [item.account_pubkey for item in canonical.token_accounts]
        _require_unique(token_pubkeys, "token account inventory")
        approved = set(registry_entry.approved_token_accounts)
        if set(token_pubkeys) != approved:
            raise TreasuryAccountingError(
                "token account inventory differs from registry"
            )
        for token in canonical.token_accounts:
            if token.owner_pubkey != registry_entry.wallet_pubkey:
                raise TreasuryAccountingError("token account owner mismatch")
            if token.delegated_authority or token.close_authority:
                raise TreasuryAccountingError("token account authority drift detected")

        instance = object.__new__(cls)
        object.__setattr__(instance, "registry_entry", registry_entry)
        object.__setattr__(instance, "provider_registry", provider_registry)
        object.__setattr__(instance, "native_balance", canonical.native_balance)
        object.__setattr__(instance, "token_accounts", canonical.token_accounts)
        object.__setattr__(instance, "endpoint_evidence", evidence)
        object.__setattr__(instance, "observed_at_ns", max(collected))
        object.__setattr__(instance, "policy_hash", policy_hash)
        object.__setattr__(instance, "decoder_version", decoder_version)
        object.__setattr__(instance, "decoded_state_hash", canonical.state_hash)
        object.__setattr__(instance, "observation_policy", observation_policy)
        object.__setattr__(
            instance,
            "source",
            BalanceSource.RUNTIME_FINALIZED_RPC_QUORUM,
        )
        return instance

    @property
    def observation_hash(self) -> str:
        return domain_hash(MPR15_HASH_DOMAIN, self.to_json())

    @property
    def minimum_root_slot(self) -> int:
        return min(item.root_slot for item in self.endpoint_evidence)

    def validate_freshness(
        self,
        *,
        trusted_now_ns: int,
        current_finalized_root_slot: int,
    ) -> None:
        _require_int(trusted_now_ns, "trusted_now_ns", lower=0)
        _require_int(
            current_finalized_root_slot,
            "current_finalized_root_slot",
            lower=0,
        )
        if (
            self.observed_at_ns
            > trusted_now_ns + self.observation_policy.max_future_skew_ns
        ):
            raise TreasuryAccountingError("wallet observation is future-dated")
        if trusted_now_ns - self.observed_at_ns > self.observation_policy.max_age_ns:
            raise TreasuryAccountingError("wallet observation is stale")
        if self.minimum_root_slot > current_finalized_root_slot:
            raise TreasuryAccountingError(
                "wallet observation root is ahead of trusted root"
            )
        if (
            current_finalized_root_slot - self.minimum_root_slot
            > self.observation_policy.max_root_lag_slots
        ):
            raise TreasuryAccountingError("wallet observation root is too old")

    def to_json(self) -> dict[str, object]:
        return {
            "schema": MPR15_SCHEMA,
            "source": self.source.value,
            "registry_entry": self.registry_entry.to_json(),
            "provider_registry_manifest_hash": (
                self.provider_registry.manifest.manifest_hash
            ),
            "provider_registry_generation": self.provider_registry.manifest.generation,
            "native_balance": self.native_balance.to_json(),
            "token_accounts": [item.to_json() for item in self.token_accounts],
            "endpoint_evidence": [item.to_json() for item in self.endpoint_evidence],
            "observed_at_ns": self.observed_at_ns,
            "policy_hash": self.policy_hash,
            "decoder_version": self.decoder_version,
            "decoded_state_hash": self.decoded_state_hash,
        }


@dataclass(frozen=True, slots=True)
class SolvencyInputs:
    finalized_wallet_assets: AssetAmount
    protected_treasury_reserve: AssetAmount
    active_capital_reservations: AssetAmount
    pending_submission_max_debit: AssetAmount
    unresolved_ambiguous_attempt_reserve: AssetAmount
    rent_liabilities: AssetAmount
    estimated_failure_charges: AssetAmount
    provider_network_fee_buffer: AssetAmount
    withdrawal_sweep_holds: AssetAmount

    def __post_init__(self) -> None:
        amounts = (
            self.finalized_wallet_assets,
            self.protected_treasury_reserve,
            self.active_capital_reservations,
            self.pending_submission_max_debit,
            self.unresolved_ambiguous_attempt_reserve,
            self.rent_liabilities,
            self.estimated_failure_charges,
            self.provider_network_fee_buffer,
            self.withdrawal_sweep_holds,
        )
        first = amounts[0]
        for amount in amounts:
            _require_same_asset(first, amount)
            amount.require_non_negative()
        if (
            self.pending_submission_max_debit.base_units
            < self.unresolved_ambiguous_attempt_reserve.base_units
        ):
            raise TreasuryAccountingError(
                "unresolved attempt reserve must be covered by pending max debit"
            )

    def total_deductions(self) -> AssetAmount:
        total = AssetAmount(self.finalized_wallet_assets.asset, 0)
        for amount in (
            self.protected_treasury_reserve,
            self.active_capital_reservations,
            self.pending_submission_max_debit,
            self.rent_liabilities,
            self.estimated_failure_charges,
            self.provider_network_fee_buffer,
            self.withdrawal_sweep_holds,
        ):
            total += amount
        return total


@dataclass(frozen=True, slots=True)
class SolvencyReport:
    asset: AssetIdentity
    finalized_wallet_assets: int
    total_deductions: int
    available_base_units: int
    deficit_base_units: int
    observation_hash: str
    policy_hash: str

    @property
    def admission_allowed(self) -> bool:
        return self.deficit_base_units == 0 and self.available_base_units > 0

    def to_json(self) -> dict[str, object]:
        return {
            "asset": self.asset.to_json(),
            "finalized_wallet_assets": str(self.finalized_wallet_assets),
            "total_deductions": str(self.total_deductions),
            "available_base_units": str(self.available_base_units),
            "deficit_base_units": str(self.deficit_base_units),
            "observation_hash": self.observation_hash,
            "policy_hash": self.policy_hash,
            "admission_allowed": self.admission_allowed,
        }


def compute_solvency_report(
    observation: WalletObservationPackage,
    inputs: SolvencyInputs,
    *,
    trusted_now_ns: int,
    current_finalized_root_slot: int,
) -> SolvencyReport:
    observation.validate_freshness(
        trusted_now_ns=trusted_now_ns,
        current_finalized_root_slot=current_finalized_root_slot,
    )
    _require_same_asset(observation.native_balance, inputs.finalized_wallet_assets)
    if (
        observation.native_balance.base_units
        != inputs.finalized_wallet_assets.base_units
    ):
        raise TreasuryAccountingError(
            "solvency input does not match decoded observation"
        )
    deductions = inputs.total_deductions().base_units
    raw_available = inputs.finalized_wallet_assets.base_units - deductions
    return SolvencyReport(
        asset=inputs.finalized_wallet_assets.asset,
        finalized_wallet_assets=inputs.finalized_wallet_assets.base_units,
        total_deductions=deductions,
        available_base_units=max(0, raw_available),
        deficit_base_units=max(0, -raw_available),
        observation_hash=observation.observation_hash,
        policy_hash=observation.policy_hash,
    )


def _decode_wallet_rpc_bundle(
    evidence: RpcEndpointEvidence,
    *,
    registry_entry: WalletRegistryEntry,
    decoder_version: str,
) -> _DecodedWalletState:
    if decoder_version != "wallet-rpc-decoder-v1":
        raise TreasuryAccountingError("unsupported wallet RPC decoder version")
    try:
        payload = json.loads(evidence.raw_response_json)
    except json.JSONDecodeError as exc:
        raise TreasuryAccountingError("raw RPC evidence is not valid JSON") from exc
    mapping = _ensure_mapping(payload, "wallet RPC bundle")
    if _as_str(mapping, "schema") != WALLET_RPC_BUNDLE_SCHEMA:
        raise TreasuryAccountingError("unsupported wallet RPC bundle schema")
    if _as_str(mapping, "cluster_genesis") != registry_entry.cluster_genesis:
        raise TreasuryAccountingError("wallet RPC bundle cluster mismatch")
    if _as_str(mapping, "wallet_pubkey") != registry_entry.wallet_pubkey:
        raise TreasuryAccountingError("wallet RPC bundle wallet mismatch")
    if _as_int(mapping, "context_slot") != evidence.context_slot:
        raise TreasuryAccountingError("wallet RPC context slot mismatch")
    if _as_int(mapping, "root_slot") != evidence.root_slot:
        raise TreasuryAccountingError("wallet RPC root slot mismatch")
    native_balance = AssetAmount(
        registry_entry.protected_reserve.asset,
        _as_int(mapping, "native_balance_base_units"),
    )
    native_balance.require_non_negative("decoded native balance")
    raw_accounts = mapping.get("token_accounts")
    if not isinstance(raw_accounts, list):
        raise TreasuryAccountingError("token_accounts must be a list")
    token_accounts: list[TokenAccountSnapshot] = []
    for raw in raw_accounts:
        account = _ensure_mapping(raw, "token account")
        mint = _as_str(account, "mint")
        token_program = _as_str(account, "token_program")
        decimals = _as_int(account, "decimals")
        asset = AssetIdentity(
            cluster_genesis=registry_entry.cluster_genesis,
            symbol=_as_str(account, "symbol"),
            mint=mint,
            token_program=token_program,
            decimals=decimals,
        )
        delegated = account.get("delegated_authority")
        close = account.get("close_authority")
        if delegated is not None and not isinstance(delegated, str):
            raise TreasuryAccountingError("delegated_authority must be text or null")
        if close is not None and not isinstance(close, str):
            raise TreasuryAccountingError("close_authority must be text or null")
        token_accounts.append(
            TokenAccountSnapshot(
                account_pubkey=_as_str(account, "account_pubkey"),
                owner_pubkey=_as_str(account, "owner_pubkey"),
                amount=AssetAmount(asset, _as_int(account, "amount_base_units")),
                mint=mint,
                token_program=token_program,
                layout_version=_as_str(account, "layout_version"),
                account_hash=_as_str(account, "account_hash"),
                delegated_authority=delegated,
                close_authority=close,
            )
        )
    return _DecodedWalletState(
        cluster_genesis=registry_entry.cluster_genesis,
        wallet_pubkey=registry_entry.wallet_pubkey,
        native_balance=native_balance,
        token_accounts=tuple(
            sorted(token_accounts, key=lambda item: item.account_pubkey)
        ),
        context_slot=evidence.context_slot,
        root_slot=evidence.root_slot,
    )
