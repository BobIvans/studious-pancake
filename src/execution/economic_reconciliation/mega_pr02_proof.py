"""MEGA-PR-02 raw-state-owned economic proof qualification.

This additive, live-disabled boundary qualifies legacy reconciliation reports only
when raw simulation state, decoded account identity, MarginFi registry admission,
and conservative cross-asset valuation all agree.  It intentionally does not
sign, submit, book PnL, release capital, or enable live execution.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Any

from .models import (
    AssetKey,
    MarginfiRepaymentObservation,
    NativeObservation,
    ReconciliationEvidence,
    ReconciliationReport,
    ReconciliationStatus,
    TokenObservation,
)

_HASH = re.compile(r"^[0-9a-f]{64}$")


class QualificationStatus(str, Enum):
    QUALIFIED_PROFIT = "qualified_profit"
    PROVEN_LOSS = "proven_loss"
    BREAK_EVEN = "break_even"
    INDETERMINATE = "indeterminate"


class QualificationReason(str, Enum):
    QUALIFIED_STRICT_POSITIVE_VALUE = "qualified_strict_positive_value"
    REPORT_NOT_COMPLETE = "report_not_complete"
    REPORT_NOT_PROFIT = "report_not_profit"
    CORE_EVIDENCE_MISMATCH = "core_evidence_mismatch"
    RAW_ACCOUNT_MISSING = "raw_account_missing"
    RAW_ACCOUNT_SLOT_MISMATCH = "raw_account_slot_mismatch"
    RAW_DECODE_BINDING_MISMATCH = "raw_decode_binding_mismatch"
    MARGINFI_REGISTRY_MISMATCH = "marginfi_registry_mismatch"
    VALUATION_MISSING = "valuation_missing"
    VALUATION_STALE = "valuation_stale"
    NET_NOT_STRICTLY_POSITIVE = "net_not_strictly_positive"
    NET_BELOW_MINIMUM_THRESHOLD = "net_below_minimum_threshold"
    NEGATIVE_CROSS_ASSET_NET = "negative_cross_asset_net"


@dataclass(frozen=True, slots=True)
class RawAccountBinding:
    address: str
    owner: str
    slot: int
    raw_hash: str
    decoded_hash: str

    def __post_init__(self) -> None:
        if not self.address or not self.owner:
            raise ValueError("raw account identity is incomplete")
        _require_positive(self.slot, "slot")
        _require_hash(self.raw_hash, "raw_hash")
        _require_hash(self.decoded_hash, "decoded_hash")


@dataclass(frozen=True, slots=True)
class RawSimulationStateProof:
    expected_message_hash: str
    response_hash: str
    logs_hash: str
    simulation_slot: int
    accounts: tuple[RawAccountBinding, ...]

    def __post_init__(self) -> None:
        _require_hash(self.expected_message_hash, "expected_message_hash")
        _require_hash(self.response_hash, "response_hash")
        _require_hash(self.logs_hash, "logs_hash")
        _require_positive(self.simulation_slot, "simulation_slot")
        seen: set[str] = set()
        for account in self.accounts:
            if account.address in seen:
                raise ValueError(f"duplicate raw account binding: {account.address}")
            seen.add(account.address)

    def by_address(self) -> dict[str, RawAccountBinding]:
        return {account.address: account for account in self.accounts}


@dataclass(frozen=True, slots=True)
class MarginfiRegistrySnapshot:
    program_id: str
    banks: frozenset[str]
    liquidity_vaults: frozenset[str]
    margin_accounts: frozenset[str]
    registry_hash: str

    def __post_init__(self) -> None:
        if not self.program_id:
            raise ValueError("MarginFi program id is required")
        if not self.banks or not self.liquidity_vaults or not self.margin_accounts:
            raise ValueError("MarginFi registry snapshot is incomplete")
        _require_hash(self.registry_hash, "registry_hash")

    @classmethod
    def build(
        cls,
        *,
        program_id: str,
        banks: set[str] | frozenset[str],
        liquidity_vaults: set[str] | frozenset[str],
        margin_accounts: set[str] | frozenset[str],
    ) -> "MarginfiRegistrySnapshot":
        payload = {
            "program_id": program_id,
            "banks": sorted(banks),
            "liquidity_vaults": sorted(liquidity_vaults),
            "margin_accounts": sorted(margin_accounts),
        }
        return cls(
            program_id=program_id,
            banks=frozenset(banks),
            liquidity_vaults=frozenset(liquidity_vaults),
            margin_accounts=frozenset(margin_accounts),
            registry_hash=_hash_json(payload),
        )


@dataclass(frozen=True, slots=True)
class ConservativeAssetQuote:
    asset: AssetKey
    quote_units_per_base_unit: int
    source_hash: str
    slot: int

    def __post_init__(self) -> None:
        _require_positive(self.quote_units_per_base_unit, "quote_units_per_base_unit")
        _require_hash(self.source_hash, "source_hash")
        _require_positive(self.slot, "slot")


@dataclass(frozen=True, slots=True)
class ConservativeValuationSnapshot:
    quote_currency: str
    quotes: tuple[ConservativeAssetQuote, ...]
    slot: int
    max_slot_lag: int
    min_profit_quote_units: int

    def __post_init__(self) -> None:
        if not self.quote_currency:
            raise ValueError("quote currency is required")
        _require_positive(self.slot, "slot")
        _require_non_negative(self.max_slot_lag, "max_slot_lag")
        _require_non_negative(self.min_profit_quote_units, "min_profit_quote_units")
        seen: set[AssetKey] = set()
        for quote in self.quotes:
            if quote.asset in seen:
                raise ValueError(f"duplicate valuation quote: {quote.asset.stable_id()}")
            seen.add(quote.asset)

    @property
    def valuation_hash(self) -> str:
        return _hash_json(_plain(self))

    def quote_for(self, asset: AssetKey) -> ConservativeAssetQuote | None:
        for quote in self.quotes:
            if quote.asset == asset:
                return quote
        return None


@dataclass(frozen=True, slots=True)
class EconomicProofQualification:
    status: QualificationStatus
    reason: QualificationReason
    qualified: bool
    report_status: ReconciliationStatus
    quote_currency: str
    quote_net: int | None
    min_profit_quote_units: int
    valuation_hash: str | None
    registry_hash: str | None
    diagnostic: str


class _RejectedQualification(Exception):
    def __init__(self, reason: QualificationReason, diagnostic: str) -> None:
        super().__init__(diagnostic)
        self.reason = reason
        self.diagnostic = diagnostic


class RawStateEconomicProofAuthority:
    """Fail-closed production qualification wrapper for economic reconciliation."""

    def qualify(
        self,
        *,
        evidence: ReconciliationEvidence,
        report: ReconciliationReport,
        raw_state: RawSimulationStateProof,
        registry: MarginfiRegistrySnapshot,
        valuation: ConservativeValuationSnapshot,
    ) -> EconomicProofQualification:
        try:
            self._core_identity(evidence, report, raw_state)
            raw_accounts = raw_state.by_address()
            self._bind_required_accounts(evidence, raw_accounts)
            self._bind_decoded_state(evidence, raw_accounts)
            self._registry_bound_marginfi(evidence.marginfi, registry, raw_accounts)
            quote_net = self._quote_report(report, valuation, evidence.simulation_slot)
        except _RejectedQualification as exc:
            return EconomicProofQualification(
                status=QualificationStatus.INDETERMINATE,
                reason=exc.reason,
                qualified=False,
                report_status=report.status,
                quote_currency=valuation.quote_currency,
                quote_net=None,
                min_profit_quote_units=valuation.min_profit_quote_units,
                valuation_hash=valuation.valuation_hash,
                registry_hash=registry.registry_hash,
                diagnostic=exc.diagnostic,
            )

        if report.status != ReconciliationStatus.PROVEN_PROFIT:
            status = (
                QualificationStatus.PROVEN_LOSS
                if report.status == ReconciliationStatus.PROVEN_LOSS
                else QualificationStatus.INDETERMINATE
            )
            return self._result(
                status,
                QualificationReason.REPORT_NOT_PROFIT,
                False,
                report,
                valuation,
                registry,
                quote_net,
                f"reconciliation status is {report.status.value}",
            )
        if quote_net < 0:
            return self._result(
                QualificationStatus.PROVEN_LOSS,
                QualificationReason.NEGATIVE_CROSS_ASSET_NET,
                False,
                report,
                valuation,
                registry,
                quote_net,
                "conservative cross-asset net is negative",
            )
        if quote_net == 0:
            return self._result(
                QualificationStatus.BREAK_EVEN,
                QualificationReason.NET_NOT_STRICTLY_POSITIVE,
                False,
                report,
                valuation,
                registry,
                quote_net,
                "zero total value is not profit",
            )
        if quote_net <= valuation.min_profit_quote_units:
            return self._result(
                QualificationStatus.BREAK_EVEN,
                QualificationReason.NET_BELOW_MINIMUM_THRESHOLD,
                False,
                report,
                valuation,
                registry,
                quote_net,
                "total value does not clear policy threshold",
            )
        return self._result(
            QualificationStatus.QUALIFIED_PROFIT,
            QualificationReason.QUALIFIED_STRICT_POSITIVE_VALUE,
            True,
            report,
            valuation,
            registry,
            quote_net,
            "all raw-state, registry and valuation invariants were proven",
        )

    def _core_identity(
        self,
        evidence: ReconciliationEvidence,
        report: ReconciliationReport,
        raw_state: RawSimulationStateProof,
    ) -> None:
        if not report.complete:
            raise _RejectedQualification(
                QualificationReason.REPORT_NOT_COMPLETE,
                "incomplete reconciliation cannot be production-qualified",
            )
        expected = (
            evidence.expected_message_hash,
            evidence.simulated_message_hash,
            evidence.response_hash,
            evidence.logs_hash,
            evidence.simulation_slot,
        )
        observed = (
            report.message_hash,
            raw_state.expected_message_hash,
            raw_state.response_hash,
            raw_state.logs_hash,
            raw_state.simulation_slot,
        )
        if expected != observed or report.response_hash != evidence.response_hash:
            raise _RejectedQualification(
                QualificationReason.CORE_EVIDENCE_MISMATCH,
                "message, response, logs or slot identity differs across evidence",
            )

    def _bind_required_accounts(
        self,
        evidence: ReconciliationEvidence,
        raw_accounts: dict[str, RawAccountBinding],
    ) -> None:
        required = set(evidence.required_accounts)
        required.update(item.address for item in evidence.native)
        required.update(item.address for item in evidence.tokens)
        if evidence.marginfi is not None:
            required.update(
                {
                    evidence.marginfi.margin_account,
                    evidence.marginfi.bank,
                    evidence.marginfi.liquidity_vault,
                }
            )
        missing = sorted(required - set(raw_accounts))
        if missing:
            raise _RejectedQualification(
                QualificationReason.RAW_ACCOUNT_MISSING,
                f"raw state is missing accounts: {missing}",
            )
        stale = sorted(
            address
            for address in required
            if raw_accounts[address].slot != evidence.simulation_slot
        )
        if stale:
            raise _RejectedQualification(
                QualificationReason.RAW_ACCOUNT_SLOT_MISMATCH,
                f"raw account slots differ from simulation slot: {stale}",
            )

    def _bind_decoded_state(
        self,
        evidence: ReconciliationEvidence,
        raw_accounts: dict[str, RawAccountBinding],
    ) -> None:
        for native_observation in evidence.native:
            self._require_decoded_hash(
                raw_accounts[native_observation.address],
                decoded_observation_hash(native_observation),
            )
        for token_observation in evidence.tokens:
            self._require_decoded_hash(
                raw_accounts[token_observation.address],
                decoded_observation_hash(token_observation),
            )

    def _registry_bound_marginfi(
        self,
        item: MarginfiRepaymentObservation | None,
        registry: MarginfiRegistrySnapshot,
        raw_accounts: dict[str, RawAccountBinding],
    ) -> None:
        if item is None:
            raise _RejectedQualification(
                QualificationReason.MARGINFI_REGISTRY_MISMATCH,
                "MarginFi repayment observation is required",
            )
        if (
            item.program_id != registry.program_id
            or item.bank not in registry.banks
            or item.liquidity_vault not in registry.liquidity_vaults
            or item.margin_account not in registry.margin_accounts
        ):
            raise _RejectedQualification(
                QualificationReason.MARGINFI_REGISTRY_MISMATCH,
                "MarginFi account/program identity is not in the admitted registry",
            )
        marginfi_hash = decoded_marginfi_hash(item)
        for address in (item.margin_account, item.bank):
            self._require_decoded_hash(raw_accounts[address], marginfi_hash)

    def _quote_report(
        self,
        report: ReconciliationReport,
        valuation: ConservativeValuationSnapshot,
        simulation_slot: int,
    ) -> int:
        total = 0
        for item in report.breakdowns:
            quote = valuation.quote_for(item.asset)
            if quote is None:
                raise _RejectedQualification(
                    QualificationReason.VALUATION_MISSING,
                    f"missing valuation for {item.asset.stable_id()}",
                )
            if abs(simulation_slot - quote.slot) > valuation.max_slot_lag:
                raise _RejectedQualification(
                    QualificationReason.VALUATION_STALE,
                    f"stale valuation for {item.asset.stable_id()}",
                )
            total += item.net * quote.quote_units_per_base_unit
        return total

    @staticmethod
    def _require_decoded_hash(binding: RawAccountBinding, decoded_hash: str) -> None:
        if binding.decoded_hash != decoded_hash:
            raise _RejectedQualification(
                QualificationReason.RAW_DECODE_BINDING_MISMATCH,
                f"decoded state is not bound to raw account {binding.address}",
            )

    @staticmethod
    def _result(
        status: QualificationStatus,
        reason: QualificationReason,
        qualified: bool,
        report: ReconciliationReport,
        valuation: ConservativeValuationSnapshot,
        registry: MarginfiRegistrySnapshot,
        quote_net: int,
        diagnostic: str,
    ) -> EconomicProofQualification:
        return EconomicProofQualification(
            status=status,
            reason=reason,
            qualified=qualified,
            report_status=report.status,
            quote_currency=valuation.quote_currency,
            quote_net=quote_net,
            min_profit_quote_units=valuation.min_profit_quote_units,
            valuation_hash=valuation.valuation_hash,
            registry_hash=registry.registry_hash,
            diagnostic=diagnostic,
        )


def decoded_observation_hash(observation: NativeObservation | TokenObservation) -> str:
    return _hash_json(_plain(observation))


def decoded_marginfi_hash(observation: MarginfiRepaymentObservation) -> str:
    return _hash_json(_plain(observation))


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, AssetKey):
        return {
            "mint": value.mint,
            "token_program": value.token_program,
            "decimals": value.decimals,
        }
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, (frozenset, set)):
        return sorted(_plain(item) for item in value)
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in sorted(value.items())}
    return value


def _hash_json(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _require_hash(value: str, name: str) -> None:
    if not _HASH.fullmatch(value):
        raise ValueError(f"{name} must be lower-case sha256")


def _require_positive(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _require_non_negative(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


__all__ = [
    "ConservativeAssetQuote",
    "ConservativeValuationSnapshot",
    "EconomicProofQualification",
    "MarginfiRegistrySnapshot",
    "QualificationReason",
    "QualificationStatus",
    "RawAccountBinding",
    "RawSimulationStateProof",
    "RawStateEconomicProofAuthority",
    "decoded_marginfi_hash",
    "decoded_observation_hash",
]
