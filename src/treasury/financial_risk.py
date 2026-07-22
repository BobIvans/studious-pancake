"""PR-163 treasury, wallet solvency and financial-risk accounting boundary.

The code in this module is intentionally offline and side-effect free. It does
not call Solana RPC, sign transactions, mutate wallets, or enable live canary.
It defines the evidence contract that a future runtime-owned observation service
and durable ledger must satisfy before money can be considered available.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Mapping, Sequence


PR163_SCHEMA = "pr163.treasury-wallet-solvency.v1"
PR163_HASH_DOMAIN = "flashloan-bot/pr163-treasury-risk"
_NANOSECONDS_PER_SECOND = 1_000_000_000
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class TreasuryAccountingError(ValueError):
    """Raised when treasury/accounting evidence is unsafe or inconsistent."""


class BalanceSource(StrEnum):
    CALLER_SUPPLIED = "caller_supplied"
    RUNTIME_FINALIZED_RPC_QUORUM = "runtime_finalized_rpc_quorum"


class WalletClassification(StrEnum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


class AccountingStage(StrEnum):
    PREDICTED = "predicted"
    SIMULATED = "simulated"
    CONFIRMED = "confirmed"
    FINALIZED = "finalized"
    RECONCILED = "reconciled"
    BOOKED = "booked"


class RiskWindowKind(StrEnum):
    UTC_DAY = "utc_day"
    ROLLING_24H = "rolling_24h"
    DEPLOYMENT = "deployment"
    CANARY = "canary"


class LedgerEntryKind(StrEnum):
    REALIZED_PNL = "realized_pnl"
    FEE = "fee"
    RENT_LOCKED = "rent_locked"
    RENT_REFUNDED = "rent_refunded"
    TIP = "tip"
    TRANSFER_FEE = "transfer_fee"
    FAILED_ATTEMPT_CHARGE = "failed_attempt_charge"
    UNRESOLVED_MAX_LOSS = "unresolved_max_loss"
    PROVIDER_SPEND = "provider_spend"


@dataclass(frozen=True, slots=True)
class AssetIdentity:
    """Unique integer-accounting identity for one asset on one cluster."""

    cluster_genesis: str
    symbol: str
    mint: str
    token_program: str
    decimals: int

    def __post_init__(self) -> None:
        _require_text(self.cluster_genesis, "cluster_genesis")
        _require_text(self.symbol, "symbol")
        _require_text(self.mint, "mint")
        _require_text(self.token_program, "token_program")
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


@dataclass(frozen=True, slots=True)
class AssetAmount:
    """Integer base-unit amount for exactly one asset."""

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
        return {
            "asset": self.asset.to_json(),
            "base_units": str(self.base_units),
        }


@dataclass(frozen=True, slots=True)
class WalletRegistryEntry:
    """Authoritative wallet inventory and treasury ownership declaration."""

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
    retirement_state: str = "active"

    def __post_init__(self) -> None:
        for field, value in (
            ("cluster_genesis", self.cluster_genesis),
            ("wallet_pubkey", self.wallet_pubkey),
            ("purpose", self.purpose),
            ("signer_backend", self.signer_backend),
            ("owner_custodian", self.owner_custodian),
            ("funding_policy_id", self.funding_policy_id),
            ("sweep_policy_id", self.sweep_policy_id),
            ("retirement_state", self.retirement_state),
        ):
            _require_text(value, field)
        if not self.approved_programs:
            raise TreasuryAccountingError("approved_programs is required")
        if self.protected_reserve.asset != self.maximum_exposure.asset:
            raise TreasuryAccountingError("reserve and exposure assets differ")
        if self.protected_reserve.asset.cluster_genesis != self.cluster_genesis:
            raise TreasuryAccountingError("wallet cluster differs from asset cluster")
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
            "retirement_state": self.retirement_state,
        }


@dataclass(frozen=True, slots=True)
class TokenAccountSnapshot:
    """One observed token account in the wallet inventory."""

    account_pubkey: str
    owner_pubkey: str
    amount: AssetAmount
    delegated_authority: str | None = None
    close_authority: str | None = None
    account_hash: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.account_pubkey, "account_pubkey")
        _require_text(self.owner_pubkey, "owner_pubkey")
        self.amount.require_non_negative("token_amount")
        if self.delegated_authority:
            _require_text(self.delegated_authority, "delegated_authority")
        if self.close_authority:
            _require_text(self.close_authority, "close_authority")
        if self.account_hash:
            _require_text(self.account_hash, "account_hash")

    def to_json(self) -> dict[str, object]:
        return {
            "account_pubkey": self.account_pubkey,
            "owner_pubkey": self.owner_pubkey,
            "amount": self.amount.to_json(),
            "delegated_authority": self.delegated_authority,
            "close_authority": self.close_authority,
            "account_hash": self.account_hash,
        }


@dataclass(frozen=True, slots=True)
class RpcEndpointEvidence:
    """Rooted/finalized identity evidence for a balance observation."""

    endpoint_id: str
    endpoint_identity_hash: str
    commitment: str
    context_slot: int
    root_slot: int
    response_hash: str

    def __post_init__(self) -> None:
        for field, value in (
            ("endpoint_id", self.endpoint_id),
            ("endpoint_identity_hash", self.endpoint_identity_hash),
            ("commitment", self.commitment),
            ("response_hash", self.response_hash),
        ):
            _require_text(value, field)
        _require_int(self.context_slot, "context_slot", lower=0)
        _require_int(self.root_slot, "root_slot", lower=0)
        if self.commitment != "finalized":
            raise TreasuryAccountingError("wallet observations require finalized RPC")
        if self.root_slot < self.context_slot:
            raise TreasuryAccountingError("root_slot must cover context_slot")

    def to_json(self) -> dict[str, object]:
        return {
            "endpoint_id": self.endpoint_id,
            "endpoint_identity_hash": self.endpoint_identity_hash,
            "commitment": self.commitment,
            "context_slot": self.context_slot,
            "root_slot": self.root_slot,
            "response_hash": self.response_hash,
        }


@dataclass(frozen=True, slots=True)
class WalletObservationPackage:
    """Runtime-owned wallet evidence admitted by treasury accounting."""

    registry_entry: WalletRegistryEntry
    native_balance: AssetAmount
    token_accounts: tuple[TokenAccountSnapshot, ...]
    endpoint_evidence: tuple[RpcEndpointEvidence, ...]
    observed_at_ns: int
    policy_hash: str
    source: BalanceSource = BalanceSource.RUNTIME_FINALIZED_RPC_QUORUM

    def __post_init__(self) -> None:
        self.native_balance.require_non_negative("native_balance")
        _require_int(self.observed_at_ns, "observed_at_ns", lower=0)
        _require_text(self.policy_hash, "policy_hash")
        if self.source is not BalanceSource.RUNTIME_FINALIZED_RPC_QUORUM:
            raise TreasuryAccountingError("caller-supplied wallet balance is untrusted")
        if self.native_balance.asset != self.registry_entry.protected_reserve.asset:
            raise TreasuryAccountingError("native balance asset not in wallet registry")
        if len(self.endpoint_evidence) < 2:
            raise TreasuryAccountingError("wallet observation requires RPC quorum")
        endpoint_ids = {item.endpoint_id for item in self.endpoint_evidence}
        identity_hashes = {
            item.endpoint_identity_hash for item in self.endpoint_evidence
        }
        if len(endpoint_ids) != len(self.endpoint_evidence):
            raise TreasuryAccountingError("duplicate RPC endpoint IDs")
        if len(identity_hashes) != len(self.endpoint_evidence):
            raise TreasuryAccountingError("correlated RPC endpoint identities")
        for token in self.token_accounts:
            if token.owner_pubkey != self.registry_entry.wallet_pubkey:
                raise TreasuryAccountingError("token account owner mismatch")
            if token.account_pubkey not in self.registry_entry.approved_token_accounts:
                raise TreasuryAccountingError("unregistered token account observed")
            if token.delegated_authority or token.close_authority:
                raise TreasuryAccountingError("token account authority drift detected")

    @property
    def observation_hash(self) -> str:
        return domain_hash(PR163_HASH_DOMAIN, self.to_json())

    @property
    def minimum_root_slot(self) -> int:
        return min(item.root_slot for item in self.endpoint_evidence)

    def to_json(self) -> dict[str, object]:
        return {
            "schema": PR163_SCHEMA,
            "source": self.source.value,
            "registry_entry": self.registry_entry.to_json(),
            "native_balance": self.native_balance.to_json(),
            "token_accounts": [item.to_json() for item in self.token_accounts],
            "endpoint_evidence": [item.to_json() for item in self.endpoint_evidence],
            "observed_at_ns": self.observed_at_ns,
            "policy_hash": self.policy_hash,
        }


@dataclass(frozen=True, slots=True)
class SolvencyInputs:
    """Conservative deductions before capital is considered available."""

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
    """Authoritative available balance report for one asset."""

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
) -> SolvencyReport:
    """Compute available funds from finalized observation and reservations."""

    _require_same_asset(observation.native_balance, inputs.finalized_wallet_assets)
    if (
        observation.native_balance.base_units
        != inputs.finalized_wallet_assets.base_units
    ):
        raise TreasuryAccountingError("solvency input does not match observation")
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


@dataclass(frozen=True, slots=True)
class RiskWindow:
    """Explicit accounting window; no unbucketed daily counters."""

    kind: RiskWindowKind
    key: str
    start_ns: int
    end_ns: int

    def __post_init__(self) -> None:
        _require_text(self.key, "window key")
        _require_int(self.start_ns, "window start", lower=0)
        _require_int(self.end_ns, "window end", lower=0)
        if self.end_ns <= self.start_ns:
            raise TreasuryAccountingError("window end must be after start")
        if self.kind is RiskWindowKind.UTC_DAY and not _DAY_RE.match(self.key):
            raise TreasuryAccountingError("UTC day window key must be YYYY-MM-DD")

    @staticmethod
    def utc_day(day: str) -> RiskWindow:
        if not _DAY_RE.match(day):
            raise TreasuryAccountingError("UTC day must be YYYY-MM-DD")
        start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        return RiskWindow(
            kind=RiskWindowKind.UTC_DAY,
            key=day,
            start_ns=_datetime_to_ns(start),
            end_ns=_datetime_to_ns(end),
        )

    @staticmethod
    def rolling_24h(*, end_ns: int) -> RiskWindow:
        _require_int(end_ns, "rolling window end", lower=0)
        return RiskWindow(
            kind=RiskWindowKind.ROLLING_24H,
            key=f"rolling_24h:{end_ns}",
            start_ns=end_ns - 24 * 60 * 60 * _NANOSECONDS_PER_SECOND,
            end_ns=end_ns,
        )

    def to_json(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "key": self.key,
            "start_ns": self.start_ns,
            "end_ns": self.end_ns,
        }


@dataclass(frozen=True, slots=True)
class RiskLedgerEntry:
    """Signed integer financial movement with explicit stage and windows."""

    entry_id: str
    asset: AssetIdentity
    kind: LedgerEntryKind
    stage: AccountingStage
    amount_delta_base_units: int
    observed_at_ns: int
    window_keys: tuple[str, ...]
    attempt_id: str | None = None
    finalized_slot: int | None = None
    idempotency_key: str | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        _require_text(self.entry_id, "entry_id")
        _require_int(self.amount_delta_base_units, "amount_delta_base_units")
        _require_int(self.observed_at_ns, "observed_at_ns", lower=0)
        if not self.window_keys:
            raise TreasuryAccountingError("ledger entry requires accounting windows")
        if self.stage in {
            AccountingStage.FINALIZED,
            AccountingStage.RECONCILED,
            AccountingStage.BOOKED,
        }:
            if self.finalized_slot is None:
                raise TreasuryAccountingError(
                    "finalized accounting requires slot proof"
                )
            _require_int(self.finalized_slot, "finalized_slot", lower=0)
        if self.attempt_id is not None:
            _require_text(self.attempt_id, "attempt_id")
        if self.idempotency_key is not None:
            _require_text(self.idempotency_key, "idempotency_key")

    def to_json(self) -> dict[str, object]:
        return {
            "entry_id": self.entry_id,
            "asset": self.asset.to_json(),
            "kind": self.kind.value,
            "stage": self.stage.value,
            "amount_delta_base_units": str(self.amount_delta_base_units),
            "observed_at_ns": self.observed_at_ns,
            "window_keys": list(self.window_keys),
            "attempt_id": self.attempt_id,
            "finalized_slot": self.finalized_slot,
            "idempotency_key": self.idempotency_key,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class RiskCounterSnapshot:
    """Restart-safe risk counters for one asset and one explicit window."""

    asset: AssetIdentity
    window: RiskWindow
    realized_pnl_base_units: int = 0
    fees_base_units: int = 0
    rent_locked_base_units: int = 0
    tips_base_units: int = 0
    transfer_fees_base_units: int = 0
    failed_attempt_charges_base_units: int = 0
    unresolved_max_loss_base_units: int = 0
    provider_spend_base_units: int = 0
    consecutive_failures: int = 0

    def __post_init__(self) -> None:
        for field in (
            "realized_pnl_base_units",
            "fees_base_units",
            "rent_locked_base_units",
            "tips_base_units",
            "transfer_fees_base_units",
            "failed_attempt_charges_base_units",
            "unresolved_max_loss_base_units",
            "provider_spend_base_units",
        ):
            _require_int(getattr(self, field), field)
        _require_int(self.consecutive_failures, "consecutive_failures", lower=0)

    def to_json(self) -> dict[str, object]:
        return {
            "asset": self.asset.to_json(),
            "window": self.window.to_json(),
            "realized_pnl_base_units": str(self.realized_pnl_base_units),
            "fees_base_units": str(self.fees_base_units),
            "rent_locked_base_units": str(self.rent_locked_base_units),
            "tips_base_units": str(self.tips_base_units),
            "transfer_fees_base_units": str(self.transfer_fees_base_units),
            "failed_attempt_charges_base_units": str(
                self.failed_attempt_charges_base_units
            ),
            "unresolved_max_loss_base_units": str(self.unresolved_max_loss_base_units),
            "provider_spend_base_units": str(self.provider_spend_base_units),
            "consecutive_failures": self.consecutive_failures,
        }


@dataclass(frozen=True, slots=True)
class DurableRiskState:
    """Serializable state that keeps risk counters across restarts/failover."""

    schema: str
    snapshots: tuple[RiskCounterSnapshot, ...]
    ledger_hash: str

    def __post_init__(self) -> None:
        if self.schema != PR163_SCHEMA:
            raise TreasuryAccountingError("unsupported durable risk state schema")
        _require_text(self.ledger_hash, "ledger_hash")

    @classmethod
    def from_entries(
        cls,
        *,
        entries: Sequence[RiskLedgerEntry],
        windows: Sequence[RiskWindow],
        asset: AssetIdentity,
    ) -> DurableRiskState:
        snapshots = tuple(
            fold_risk_counters(entries=entries, window=window, asset=asset)
            for window in windows
        )
        return cls(
            schema=PR163_SCHEMA,
            snapshots=snapshots,
            ledger_hash=domain_hash(
                PR163_HASH_DOMAIN,
                [entry.to_json() for entry in entries],
            ),
        )

    def to_json(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "snapshots": [snapshot.to_json() for snapshot in self.snapshots],
            "ledger_hash": self.ledger_hash,
        }


def fold_risk_counters(
    *,
    entries: Sequence[RiskLedgerEntry],
    window: RiskWindow,
    asset: AssetIdentity,
) -> RiskCounterSnapshot:
    """Fold finalized/reconciled/booked ledger entries into one window."""

    totals = {kind: 0 for kind in LedgerEntryKind}
    consecutive_failures = 0
    for entry in sorted(
        entries,
        key=lambda item: (item.observed_at_ns, item.entry_id),
    ):
        if entry.asset != asset or window.key not in entry.window_keys:
            continue
        if entry.stage not in {
            AccountingStage.FINALIZED,
            AccountingStage.RECONCILED,
            AccountingStage.BOOKED,
        }:
            continue
        totals[entry.kind] += entry.amount_delta_base_units
        if entry.kind is LedgerEntryKind.FAILED_ATTEMPT_CHARGE:
            consecutive_failures += 1
        elif (
            entry.kind is LedgerEntryKind.REALIZED_PNL
            and entry.amount_delta_base_units > 0
        ):
            consecutive_failures = 0
    return RiskCounterSnapshot(
        asset=asset,
        window=window,
        realized_pnl_base_units=totals[LedgerEntryKind.REALIZED_PNL],
        fees_base_units=totals[LedgerEntryKind.FEE],
        rent_locked_base_units=totals[LedgerEntryKind.RENT_LOCKED],
        tips_base_units=totals[LedgerEntryKind.TIP],
        transfer_fees_base_units=totals[LedgerEntryKind.TRANSFER_FEE],
        failed_attempt_charges_base_units=totals[
            LedgerEntryKind.FAILED_ATTEMPT_CHARGE
        ],
        unresolved_max_loss_base_units=totals[LedgerEntryKind.UNRESOLVED_MAX_LOSS],
        provider_spend_base_units=totals[LedgerEntryKind.PROVIDER_SPEND],
        consecutive_failures=consecutive_failures,
    )


@dataclass(frozen=True, slots=True)
class TreasuryAuthorization:
    """Funding/sweep authorization bound to a request and treasury policy."""

    authorization_hash: str
    request_hash: str
    approver_principal_hash: str
    policy_hash: str
    scope: str
    issued_at_ns: int
    expires_at_ns: int
    revoked: bool = False

    def __post_init__(self) -> None:
        for field, value in (
            ("authorization_hash", self.authorization_hash),
            ("request_hash", self.request_hash),
            ("approver_principal_hash", self.approver_principal_hash),
            ("policy_hash", self.policy_hash),
            ("scope", self.scope),
        ):
            _require_text(value, field)
        _require_int(self.issued_at_ns, "issued_at_ns", lower=0)
        _require_int(self.expires_at_ns, "expires_at_ns", lower=0)
        if self.expires_at_ns <= self.issued_at_ns:
            raise TreasuryAccountingError("authorization must expire after issue time")


@dataclass(frozen=True, slots=True)
class FundingSweepRequest:
    """Governed funding/sweep request; never automatic runtime withdrawal."""

    source_wallet: str
    destination_wallet: str
    amount: AssetAmount
    request_hash: str
    destination_allowlisted: bool
    simulated_message_hash: str
    isolated_signer_required: bool
    authorization: TreasuryAuthorization | None = None

    def __post_init__(self) -> None:
        _require_text(self.source_wallet, "source_wallet")
        _require_text(self.destination_wallet, "destination_wallet")
        _require_text(self.request_hash, "request_hash")
        _require_text(self.simulated_message_hash, "simulated_message_hash")
        self.amount.require_non_negative("funding_sweep_amount")

    def validate(self, *, now_ns: int, policy_hash: str) -> None:
        _require_int(now_ns, "now_ns", lower=0)
        _require_text(policy_hash, "policy_hash")
        if not self.destination_allowlisted:
            raise TreasuryAccountingError(
                "funding/sweep destination is not allowlisted"
            )
        if not self.isolated_signer_required:
            raise TreasuryAccountingError("funding/sweep requires isolated signer")
        if self.authorization is None:
            raise TreasuryAccountingError("treasury authorization is required")
        if self.authorization.revoked:
            raise TreasuryAccountingError("treasury authorization is revoked")
        if now_ns > self.authorization.expires_at_ns:
            raise TreasuryAccountingError("treasury authorization expired")
        if self.authorization.request_hash != self.request_hash:
            raise TreasuryAccountingError("authorization is bound to another request")
        if self.authorization.policy_hash != policy_hash:
            raise TreasuryAccountingError("authorization policy hash mismatch")


@dataclass(frozen=True, slots=True)
class DailyTreasuryReport:
    """Machine-readable ledger-to-chain reconciliation for one UTC day."""

    window: RiskWindow
    opening_finalized_balance: AssetAmount
    funding: AssetAmount
    withdrawals: AssetAmount
    realized_pnl: AssetAmount
    fees: AssetAmount
    ending_finalized_balance: AssetAmount
    unresolved_exposure: AssetAmount
    tolerance_base_units: int = 0

    def __post_init__(self) -> None:
        if self.window.kind is not RiskWindowKind.UTC_DAY:
            raise TreasuryAccountingError("daily treasury report requires UTC day")
        amounts = (
            self.opening_finalized_balance,
            self.funding,
            self.withdrawals,
            self.realized_pnl,
            self.fees,
            self.ending_finalized_balance,
            self.unresolved_exposure,
        )
        first = amounts[0]
        for amount in amounts:
            _require_same_asset(first, amount)
        _require_int(self.tolerance_base_units, "tolerance_base_units", lower=0)

    @property
    def expected_ending_balance(self) -> AssetAmount:
        expected = (
            self.opening_finalized_balance
            + self.funding
            - self.withdrawals
            + self.realized_pnl
            - self.fees
        )
        return expected

    @property
    def ledger_to_chain_variance_base_units(self) -> int:
        return abs(
            self.ending_finalized_balance.base_units
            - self.expected_ending_balance.base_units
        )

    @property
    def hard_latch_required(self) -> bool:
        return self.ledger_to_chain_variance_base_units > self.tolerance_base_units

    def assert_balanced(self) -> None:
        if self.hard_latch_required:
            raise TreasuryAccountingError("ledger-to-chain variance exceeds tolerance")


def reject_caller_supplied_wallet_balance(value: object) -> None:
    """Always fail-close unverified caller-owned balance snapshots."""

    raise TreasuryAccountingError(
        "caller-supplied wallet balances cannot be used for live admission"
    )


def domain_hash(domain: str, payload: object) -> str:
    _require_text(domain, "hash domain")
    raw = json.dumps(
        _jsonable(payload),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(domain.encode("utf-8") + b"\0" + raw).hexdigest()


def _jsonable(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
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
    if not value or not value.strip():
        raise TreasuryAccountingError(f"{field} is required")


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


def _require_same_asset(first: AssetAmount, second: AssetAmount) -> None:
    if first.asset != second.asset:
        raise TreasuryAccountingError("cannot mix different assets")


def _datetime_to_ns(value: datetime) -> int:
    if value.tzinfo != timezone.utc:
        raise TreasuryAccountingError("datetime must be UTC")
    return calendar.timegm(value.utctimetuple()) * _NANOSECONDS_PER_SECOND


__all__ = [
    "PR163_SCHEMA",
    "AccountingStage",
    "AssetAmount",
    "AssetIdentity",
    "BalanceSource",
    "DailyTreasuryReport",
    "DurableRiskState",
    "FundingSweepRequest",
    "LedgerEntryKind",
    "RiskCounterSnapshot",
    "RiskLedgerEntry",
    "RiskWindow",
    "RiskWindowKind",
    "RpcEndpointEvidence",
    "SolvencyInputs",
    "SolvencyReport",
    "TokenAccountSnapshot",
    "TreasuryAccountingError",
    "TreasuryAuthorization",
    "WalletClassification",
    "WalletObservationPackage",
    "WalletRegistryEntry",
    "compute_solvency_report",
    "domain_hash",
    "fold_risk_counters",
    "reject_caller_supplied_wallet_balance",
]
