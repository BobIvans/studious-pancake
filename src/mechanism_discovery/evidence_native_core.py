"""Shared exact, sender-free contracts for PR-355 evidence-native research."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from .core import MechanismDiscoveryError, stable_hash


class EvidenceNativeError(MechanismDiscoveryError):
    """Typed fail-closed PR-355 research-contract error."""


def require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceNativeError(f"{field_name.upper()}_REQUIRED")
    return value.strip()


def require_int(value: object, field_name: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvidenceNativeError(f"{field_name.upper()}_INTEGER_REQUIRED")
    if minimum is not None and value < minimum:
        raise EvidenceNativeError(f"{field_name.upper()}_OUT_OF_RANGE")
    return value


def require_ppm(value: object, field_name: str) -> int:
    parsed = require_int(value, field_name, minimum=0)
    if parsed > 1_000_000:
        raise EvidenceNativeError(f"{field_name.upper()}_PPM_OUT_OF_RANGE")
    return parsed


def require_digest(value: object, field_name: str, *, length: int = 64) -> str:
    text = require_text(value, field_name)
    if len(text) != length or any(ch not in "0123456789abcdef" for ch in text):
        raise EvidenceNativeError(f"{field_name.upper()}_DIGEST_INVALID")
    return text


def require_clock_order(*values: tuple[str, int]) -> None:
    previous = -1
    for name, value in values:
        parsed = require_int(value, name, minimum=0)
        if parsed < previous:
            raise EvidenceNativeError("AVAILABILITY_CLOCK_ORDER_INVALID")
        previous = parsed


def _freeze_map(value: Mapping[str, int]) -> Mapping[str, int]:
    result: dict[str, int] = {}
    for key, item in value.items():
        result[require_text(key, "parameter_key")] = require_int(item, str(key))
    return MappingProxyType(dict(sorted(result.items())))


@dataclass(frozen=True, slots=True)
class CashflowSpec:
    cashflow_id: str
    instrument_id: str
    payer_role: str
    receiver_role: str
    payment_asset: str
    payment_unit: str
    fixed_or_floating: str
    index_id: str
    observation_schedule: tuple[int, ...]
    settlement_schedule: tuple[int, ...]
    maturity: int
    margin_atoms: int
    collateral_asset: str
    eligibility: tuple[str, ...]
    transferable: bool
    event_time: int
    published_at: int
    received_at: int
    available_at: int
    revision: int
    provenance: str

    def __post_init__(self) -> None:
        for field_name in (
            "cashflow_id", "instrument_id", "payer_role", "receiver_role",
            "payment_asset", "payment_unit", "index_id", "collateral_asset",
            "provenance",
        ):
            require_text(getattr(self, field_name), field_name)
        if self.fixed_or_floating not in {"FIXED", "FLOATING"}:
            raise EvidenceNativeError("CASHFLOW_RATE_MODE_INVALID")
        require_int(self.margin_atoms, "margin_atoms", minimum=0)
        maturity = require_int(self.maturity, "maturity", minimum=0)
        require_int(self.revision, "revision", minimum=0)
        if not self.observation_schedule or not self.settlement_schedule:
            raise EvidenceNativeError("CASHFLOW_SCHEDULE_REQUIRED")
        if any(require_int(x, "schedule_time", minimum=0) > maturity for x in (*self.observation_schedule, *self.settlement_schedule)):
            raise EvidenceNativeError("CASHFLOW_AFTER_MATURITY")
        require_clock_order(
            ("event_time", self.event_time),
            ("published_at", self.published_at),
            ("received_at", self.received_at),
            ("available_at", self.available_at),
        )


@dataclass(frozen=True, slots=True)
class ClaimRightSpec:
    right_id: str
    holder_role: str
    beneficiary_role: str
    issuer: str
    counterparty: str
    underlying_claim: str
    redemption_rule: str
    transferable: bool
    expiry: int
    maturity: int
    settlement_asset: str
    jurisdiction: str
    allowlist_required: bool
    custody_required: bool
    capacity_atoms: int
    version: str

    def __post_init__(self) -> None:
        for field_name in (
            "right_id", "holder_role", "beneficiary_role", "issuer",
            "counterparty", "underlying_claim", "redemption_rule",
            "settlement_asset", "jurisdiction", "version",
        ):
            require_text(getattr(self, field_name), field_name)
        if require_int(self.expiry, "expiry", minimum=0) < require_int(self.maturity, "maturity", minimum=0):
            raise EvidenceNativeError("CLAIM_EXPIRES_BEFORE_MATURITY")
        require_int(self.capacity_atoms, "capacity_atoms", minimum=0)


@dataclass(frozen=True, slots=True)
class LiquidityShapeSpec:
    shape_id: str
    deployment_id: str
    shape_family: str
    parameters: Mapping[str, int]
    support_low_atoms: int
    support_high_atoms: int
    total_liquidity_atoms: int
    withdrawable_liquidity_atoms: int
    dynamic_fee_ppm: int
    contexts: tuple[str, ...]
    transition_at: int
    shared_dependencies: tuple[str, ...]
    available_at: int
    revision: int

    def __post_init__(self) -> None:
        for field_name in ("shape_id", "deployment_id", "shape_family"):
            require_text(getattr(self, field_name), field_name)
        low = require_int(self.support_low_atoms, "support_low_atoms")
        high = require_int(self.support_high_atoms, "support_high_atoms")
        if high < low:
            raise EvidenceNativeError("LIQUIDITY_SUPPORT_INVERTED")
        total = require_int(self.total_liquidity_atoms, "total_liquidity_atoms", minimum=0)
        withdrawable = require_int(self.withdrawable_liquidity_atoms, "withdrawable_liquidity_atoms", minimum=0)
        if withdrawable > total:
            raise EvidenceNativeError("WITHDRAWABLE_EXCEEDS_TOTAL")
        require_ppm(self.dynamic_fee_ppm, "dynamic_fee_ppm")
        require_int(self.transition_at, "transition_at", minimum=0)
        require_int(self.available_at, "available_at", minimum=0)
        require_int(self.revision, "revision", minimum=0)
        if not self.contexts:
            raise EvidenceNativeError("LIQUIDITY_CONTEXT_REQUIRED")
        object.__setattr__(self, "parameters", _freeze_map(self.parameters))


@dataclass(frozen=True, slots=True)
class AccessAndCustodySpec:
    access_id: str
    issuer: str
    fund: str
    custodian: str
    rights: tuple[str, ...]
    jurisdictions: tuple[str, ...]
    allowlist_required: bool
    transfer_restricted: bool
    nav_atoms: int
    nav_published_at: int
    nav_available_at: int
    nav_revision: int
    subscription_open: int
    redemption_open: int
    redemption_capacity_atoms: int
    custody_receipt_state: str
    synchronized: bool

    def __post_init__(self) -> None:
        for field_name in ("access_id", "issuer", "fund", "custodian", "custody_receipt_state"):
            require_text(getattr(self, field_name), field_name)
        if not self.rights or not self.jurisdictions:
            raise EvidenceNativeError("ACCESS_RIGHTS_AND_JURISDICTION_REQUIRED")
        require_int(self.nav_atoms, "nav_atoms", minimum=0)
        require_int(self.nav_revision, "nav_revision", minimum=0)
        require_int(self.redemption_capacity_atoms, "redemption_capacity_atoms", minimum=0)
        require_clock_order(
            ("nav_published_at", self.nav_published_at),
            ("nav_available_at", self.nav_available_at),
        )


@dataclass(frozen=True, slots=True)
class ResearchResourceSpec:
    resource_uri: str
    input_schema: str
    output_schema: str
    price_atoms: int
    payment_scheme: str
    latency_ms: int
    error_rate_ppm: int
    trust_evidence: str
    provenance: str
    budget_cap_atoms: int
    expiry: int
    response_hash: str | None = None
    information_value_ppm: int | None = None
    real_purchase_allowed: bool = False

    def __post_init__(self) -> None:
        for field_name in ("resource_uri", "input_schema", "output_schema", "payment_scheme", "trust_evidence", "provenance"):
            require_text(getattr(self, field_name), field_name)
        price = require_int(self.price_atoms, "price_atoms", minimum=0)
        cap = require_int(self.budget_cap_atoms, "budget_cap_atoms", minimum=0)
        if price > cap:
            raise EvidenceNativeError("RESOURCE_PRICE_EXCEEDS_CAP")
        require_int(self.latency_ms, "latency_ms", minimum=0)
        require_ppm(self.error_rate_ppm, "error_rate_ppm")
        require_int(self.expiry, "expiry", minimum=0)
        if self.response_hash is not None:
            require_digest(self.response_hash, "response_hash")
        if self.information_value_ppm is not None:
            require_ppm(self.information_value_ppm, "information_value_ppm")
        if self.real_purchase_allowed:
            raise EvidenceNativeError("REAL_RESOURCE_PURCHASE_FORBIDDEN")
        if self.payment_scheme not in {"ZERO_COST", "MOCK", "TESTNET"}:
            raise EvidenceNativeError("RESOURCE_PAYMENT_SCHEME_NOT_ALLOWED")


@dataclass(frozen=True, slots=True)
class ResearchReceipt:
    source_snapshot_ids: tuple[str, ...]
    raw_hashes: tuple[str, ...]
    code_commit: str
    tree_hash: str
    config_hash: str
    model_hash: str
    environment_lock_hash: str
    deterministic_seed: int
    command: str
    output_hashes: tuple[str, ...]
    verdict: str
    redaction_policy: str
    proof_backend: str | None = None
    proof_version: str | None = None
    receipt_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.source_snapshot_ids or not self.raw_hashes or not self.output_hashes:
            raise EvidenceNativeError("RECEIPT_LINEAGE_REQUIRED")
        for digest in (*self.raw_hashes, *self.output_hashes):
            require_digest(digest, "receipt_hash")
        require_digest(self.code_commit, "code_commit", length=40)
        for name in ("tree_hash", "config_hash", "model_hash", "environment_lock_hash"):
            require_digest(getattr(self, name), name)
        require_int(self.deterministic_seed, "deterministic_seed", minimum=0)
        require_text(self.command, "command")
        require_text(self.verdict, "verdict")
        require_text(self.redaction_policy, "redaction_policy")
        if (self.proof_backend is None) != (self.proof_version is None):
            raise EvidenceNativeError("PROOF_BACKEND_VERSION_PAIR_REQUIRED")
        payload = {
            "source_snapshot_ids": self.source_snapshot_ids,
            "raw_hashes": self.raw_hashes,
            "code_commit": self.code_commit,
            "tree_hash": self.tree_hash,
            "config_hash": self.config_hash,
            "model_hash": self.model_hash,
            "environment_lock_hash": self.environment_lock_hash,
            "deterministic_seed": self.deterministic_seed,
            "command": self.command,
            "output_hashes": self.output_hashes,
            "verdict": self.verdict,
            "redaction_policy": self.redaction_policy,
            "proof_backend": self.proof_backend,
            "proof_version": self.proof_version,
        }
        object.__setattr__(self, "receipt_hash", stable_hash("pr355:research-receipt", payload))


def record(contract: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
    normalized = dict(payload)
    normalized.update(
        {
            "contract": contract,
            "research_only": True,
            "execution_right": False,
            "live_authority": False,
            "automatic_promotion": False,
        }
    )
    normalized["evidence_hash"] = stable_hash(f"pr355:{contract}", normalized)
    return MappingProxyType(normalized)
