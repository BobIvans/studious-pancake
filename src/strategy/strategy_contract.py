"""Canonical typed strategy contract (SX-01) — advisory schema, not a runtime.

This module is the additive, typed implementation of the 13-section canonical
strategy contract from
``docs/strategy-expansion/2026-11-14/STRATEGY_CATALOG_AND_EXECUTION_CLASSES_RU.md``
(section 3), the execution classes of section 2, the economics invariants of
section 4 and the promotion ladder of section 5.

Hard rules enforced here (do not weaken them):

1. **No runtime registry.** The module has no module-level mutable store and
   no registration API; it never imports ``src.strategy.registry`` or any
   other runtime owner. Contracts are inert, immutable values that ride along
   with existing runtime objects; nothing is "activated" by their existence.
2. **UNKNOWN stays None, never 0.** Every optional amount, cost, timestamp and
   proof field uses ``None`` for unknown. No code path coerces unknown to
   zero, and vector conservation refuses to evaluate unknown amounts instead
   of assuming zero.
3. **EXCLUDED cannot be upgraded.** A contract with ``ExecutionClass.EXCLUDED``
   pins the promotion tier at ``RESEARCH_SEED``. All dataclasses are frozen,
   so no upgrade path exists at all; promotion claims additionally require
   prefix evidence with no skipped tiers.
4. **Advisory schema only.** Holding, building or validating a contract grants
   no execution, signing, sending, borrowing, deployment or promotion rights.
   Execution rights remain with the separately gated runtime owners; evidence
   gates and governance remain the only promotion authority.

Parsing is fail closed in both directions: unknown payload fields raise
``UnknownContractFieldError`` and missing required fields raise
``MissingContractFieldError`` at every nesting level.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Any, TypeVar

__all__ = (
    "SCHEMA_VERSION",
    "AssetClaim",
    "ConservationError",
    "ContractStatus",
    "ContractTypeError",
    "CostLedger",
    "ExecutionClass",
    "ExpectedSign",
    "FundingRequirement",
    "MarketDependency",
    "MissingContractFieldError",
    "PROMOTION_LADDER",
    "PromotionEvidence",
    "PromotionTier",
    "PromotionTierError",
    "QuoteRequirement",
    "ReplaySpec",
    "ResourceManifest",
    "RiskFlag",
    "SharedResourceCost",
    "StrategyContractError",
    "StrategyContractV1",
    "TierEvidence",
    "TypedBlocker",
    "TypedBlockerReason",
    "UnknownContractFieldError",
    "claims_conserved",
    "strictest_execution_class",
)

SCHEMA_VERSION = "studious-pancake.strategy-contract.v1"
_MAX_ATOMS = 2**63 - 1

_E = TypeVar("_E", bound=Enum)
_T = TypeVar("_T")


# ---------------------------------------------------------------------------
# Errors — every rejection is typed; there is no silent acceptance.
# ---------------------------------------------------------------------------


class StrategyContractError(ValueError):
    """Base error for every fail-closed contract violation."""


class UnknownContractFieldError(StrategyContractError):
    """Raised when a payload carries a field the schema does not define."""

    def __init__(self, field_path: str) -> None:
        super().__init__(f"unknown contract field: {field_path}")
        self.field_path = field_path


class MissingContractFieldError(StrategyContractError):
    """Raised when a required contract field is absent."""

    def __init__(self, field_path: str) -> None:
        super().__init__(f"missing required contract field: {field_path}")
        self.field_path = field_path


class ContractTypeError(StrategyContractError):
    """Raised when a field value has the wrong type or vocabulary."""


class PromotionTierError(StrategyContractError):
    """Raised when a promotion claim skips tiers, exceeds its evidence,
    or tries to upgrade an EXCLUDED execution class."""


class ConservationError(StrategyContractError):
    """Raised when asset/claim vectors do not conserve per asset, or carry
    unknown amounts that make conservation unverifiable."""


# ---------------------------------------------------------------------------
# Typed vocabularies (catalog section 2; STRATEGY_ACCEPTANCE_MATRIX.json).
# ---------------------------------------------------------------------------


class ExecutionClass(str, Enum):
    """Mandatory, mutually explicit execution classes (catalog section 2)."""

    LOCAL_ATOMIC_CANDIDATE = "LOCAL_ATOMIC_CANDIDATE"
    CONDITIONAL_HYPEREDGE = "CONDITIONAL_HYPEREDGE"
    HEDGED_NON_ATOMIC = "HEDGED_NON_ATOMIC"
    SIGNAL_ONLY = "SIGNAL_ONLY"
    CONTROL_PLANE = "CONTROL_PLANE"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    EXCLUDED = "EXCLUDED"

    @property
    def strictness_rank(self) -> int:
        """Position on the restriction ladder; higher means more restricted.

        Each step up either adds obligations or removes capabilities:
        hyperedge conditions restrict plain atomic legs, hedged/non-atomic
        routes add inventory, funding, settlement and failure obligations,
        control-plane classes produce no standalone alpha, signal-only legs
        can never execute, research-only legs cannot even join the runtime,
        and EXCLUDED is prohibited outright. A route therefore inherits the
        strictest (highest-rank) class of all of its legs.
        """
        return _EXECUTION_CLASS_RESTRICTION_ORDER.index(self)


_EXECUTION_CLASS_RESTRICTION_ORDER: tuple[ExecutionClass, ...] = (
    ExecutionClass.LOCAL_ATOMIC_CANDIDATE,
    ExecutionClass.CONDITIONAL_HYPEREDGE,
    ExecutionClass.HEDGED_NON_ATOMIC,
    ExecutionClass.CONTROL_PLANE,
    ExecutionClass.SIGNAL_ONLY,
    ExecutionClass.RESEARCH_ONLY,
    ExecutionClass.EXCLUDED,
)


class PromotionTier(str, Enum):
    """Promotion ladder in strict order (catalog section 5).

    The ladder is per strategy/venue/protocol/asset/chain revision; a proof
    for one pool, amount, chain or code revision never promotes another.
    """

    RESEARCH_SEED = "RESEARCH_SEED"
    IDENTITY_VERIFIED = "IDENTITY_VERIFIED"
    STATE_READ_PROVEN = "STATE_READ_PROVEN"
    EXACT_QUOTE = "EXACT_QUOTE"
    CAPACITY_PROVEN = "CAPACITY_PROVEN"
    BUILD_CONFORMANT = "BUILD_CONFORMANT"
    SIMULATION_PASS = "SIMULATION_PASS"
    PAPER_QUALIFIED = "PAPER_QUALIFIED"

    @property
    def ladder_rank(self) -> int:
        return PROMOTION_LADDER.index(self)


PROMOTION_LADDER: tuple[PromotionTier, ...] = (
    PromotionTier.RESEARCH_SEED,
    PromotionTier.IDENTITY_VERIFIED,
    PromotionTier.STATE_READ_PROVEN,
    PromotionTier.EXACT_QUOTE,
    PromotionTier.CAPACITY_PROVEN,
    PromotionTier.BUILD_CONFORMANT,
    PromotionTier.SIMULATION_PASS,
    PromotionTier.PAPER_QUALIFIED,
)


class ContractStatus(str, Enum):
    """Status vocabulary mirrored from STRATEGY_ACCEPTANCE_MATRIX.json."""

    EXISTING_RESEARCH = "EXISTING_RESEARCH"
    PARTIAL_OWNER = "PARTIAL_OWNER"
    FIXTURE_ONLY = "FIXTURE_ONLY"
    STUB = "STUB"
    PLANNED = "PLANNED"
    NEW_GAP = "NEW_GAP"
    BLOCKED = "BLOCKED"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    EXCLUDED = "EXCLUDED"


class ExpectedSign(str, Enum):
    """Hypothesis sign (catalog section 2). UNKNOWN is distinct from ZERO."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    ZERO = "zero"
    UNKNOWN = "unknown"


class TypedBlockerReason(str, Enum):
    """Typed rejection/blocker vocabulary (catalog sections 4, 11, 12, 13)."""

    IDENTITY_UNVERIFIED = "IDENTITY_UNVERIFIED"
    STATE_GENERATION_UNKNOWN = "STATE_GENERATION_UNKNOWN"
    STATE_READ_UNPROVEN = "STATE_READ_UNPROVEN"
    EXACT_QUOTE_MISSING = "EXACT_QUOTE_MISSING"
    CAPACITY_UNPROVEN = "CAPACITY_UNPROVEN"
    FUNDING_INELIGIBLE = "FUNDING_INELIGIBLE"
    REPAYMENT_UNPROVEN = "REPAYMENT_UNPROVEN"
    BUILD_NONCONFORMANT = "BUILD_NONCONFORMANT"
    SIMULATION_NOT_RUN = "SIMULATION_NOT_RUN"
    PAPER_EVALUATION_MISSING = "PAPER_EVALUATION_MISSING"
    COSTS_UNKNOWN = "COSTS_UNKNOWN"
    RESOURCE_CONFLICT = "RESOURCE_CONFLICT"
    FINALITY_UNPROVEN = "FINALITY_UNPROVEN"
    STALE_OR_REORG_RISK = "STALE_OR_REORG_RISK"
    ORACLE_RISK_UNMODELLED = "ORACLE_RISK_UNMODELLED"
    DEPEG_RISK_UNMODELLED = "DEPEG_RISK_UNMODELLED"
    PARTIAL_FILL_UNMODELLED = "PARTIAL_FILL_UNMODELLED"
    LIQUIDATION_RISK_UNMODELLED = "LIQUIDATION_RISK_UNMODELLED"
    BRIDGE_WITHDRAWAL_FINALITY_RISK = "BRIDGE_WITHDRAWAL_FINALITY_RISK"
    MEV_COMPETITION_UNMODELLED = "MEV_COMPETITION_UNMODELLED"
    NO_TRADE_EVIDENCE_MISSING = "NO_TRADE_EVIDENCE_MISSING"
    POLICY_EXCLUDED = "POLICY_EXCLUDED"


class RiskFlag(str, Enum):
    """Typed risk-model flags (catalog section 11)."""

    STALE_OR_REORG = "STALE_OR_REORG"
    DEPEG = "DEPEG"
    ORACLE = "ORACLE"
    SLASHING = "SLASHING"
    PAUSE = "PAUSE"
    CAP = "CAP"
    QUEUE = "QUEUE"
    MATURITY = "MATURITY"
    ADVERSE_SELECTION = "ADVERSE_SELECTION"
    PARTIAL_FILL = "PARTIAL_FILL"
    LIQUIDATION = "LIQUIDATION"
    BRIDGE_WITHDRAWAL_FINALITY = "BRIDGE_WITHDRAWAL_FINALITY"
    MEV_COMPETITION = "MEV_COMPETITION"


# ---------------------------------------------------------------------------
# Fail-closed validation helpers (shared by direct construction and from_dict).
# ---------------------------------------------------------------------------


def _require_text(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractTypeError(f"{path} must be a non-empty string")
    return value


def _optional_text(value: object, path: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, path)


def _require_int(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractTypeError(
            f"{path} must be an integer; got {type(value).__name__}"
        )
    return value


def _optional_int(value: object, path: str) -> int | None:
    if value is None:
        return None
    return _require_int(value, path)


def _optional_amount(
    value: object,
    path: str,
    *,
    non_negative: bool = False,
) -> int | None:
    """Integer base-unit amount; ``None`` is UNKNOWN and never becomes zero."""
    number = _optional_int(value, path)
    if number is None:
        return None
    if non_negative and number < 0:
        raise ContractTypeError(f"{path} must be non-negative when known")
    if not -_MAX_ATOMS <= number <= _MAX_ATOMS:
        raise ContractTypeError(f"{path} outside supported atomic range")
    return number


def _optional_bool(value: object, path: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ContractTypeError(f"{path} must be a boolean or null")
    return value


def _string_tuple(
    value: object, path: str, *, non_empty: bool = False
) -> tuple[str, ...]:
    """Normalize a set-like string field: dedupe and sort for determinism."""
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ContractTypeError(f"{path} must be a sequence of non-empty strings")
    items: list[str] = []
    for item in value:
        items.append(_require_text(item, f"{path}[]"))
    unique = sorted(set(items))
    if non_empty and not unique:
        raise ContractTypeError(f"{path} must contain at least one entry")
    return tuple(unique)


def _parse_enum(value: object, enum_cls: type[_E], path: str) -> _E:
    if not isinstance(value, str):
        raise ContractTypeError(f"{path} must be a string enum value")
    try:
        return enum_cls(value)
    except ValueError:
        allowed = "|".join(item.value for item in enum_cls)
        raise ContractTypeError(
            f"{path} must be one of: {allowed}; got {value!r}"
        ) from None


def _require_enum_instance(value: object, enum_cls: type[_E], path: str) -> _E:
    if not isinstance(value, enum_cls):
        raise ContractTypeError(
            f"{path} must be a {enum_cls.__name__} member; "
            f"use from_dict for string payloads"
        )
    return value


def _require_instance(value: object, cls: type[_T], path: str) -> _T:
    if not isinstance(value, cls):
        raise ContractTypeError(
            f"{path} must be a {cls.__name__} instance; "
            f"use {cls.__name__}.from_dict for dict payloads"
        )
    return value


def _optional_instance(value: object, cls: type[_T], path: str) -> _T | None:
    if value is None:
        return None
    return _require_instance(value, cls, path)


def _normalize_instances(value: object, cls: type[_T], path: str) -> tuple[_T, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ContractTypeError(f"{path} must be a sequence of {cls.__name__}")
    items: list[_T] = []
    for index, item in enumerate(value):
        items.append(_require_instance(item, cls, f"{path}[{index}]"))
    return tuple(items)


def _require_mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractTypeError(f"{path} must be a mapping/object")
    return value


def _check_payload_keys(
    payload: Mapping[str, Any],
    allowed: frozenset[str],
    required: tuple[str, ...],
    path: str,
) -> None:
    """Fail closed on unknown keys before looking at any value."""
    for key in payload:
        if not isinstance(key, str) or key not in allowed:
            raise UnknownContractFieldError(f"{path}.{key}")
    for key in required:
        if key not in payload:
            raise MissingContractFieldError(f"{path}.{key}")


def _object_list(
    value: object,
    item_from_dict: Callable[..., _T],
    path: str,
) -> tuple[_T, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ContractTypeError(f"{path} must be a list of objects")
    items: list[_T] = []
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        items.append(item_from_dict(_require_mapping(item, item_path), path=item_path))
    return tuple(items)


def _optional_nested_dict(
    value: object,
    item_from_dict: Callable[..., _T],
    path: str,
) -> _T | None:
    if value is None:
        return None
    return item_from_dict(_require_mapping(value, path), path=path)


def _enum_tuple(value: object, enum_cls: type[_E], path: str) -> tuple[_E, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ContractTypeError(f"{path} must be a list of {enum_cls.__name__} values")
    items = [_parse_enum(item, enum_cls, f"{path}[]") for item in value]
    return tuple(sorted(set(items), key=lambda item: item.value))


# ---------------------------------------------------------------------------
# Supporting dataclasses (catalog sections 3, 5, 6, 7, 8, 10, 12, 13).
# ---------------------------------------------------------------------------

_ALLOWED_ASSET_CLAIM_KEYS: frozenset[str] = frozenset(
    {"chain", "address", "decimals", "representation_kind", "issuer", "amount"}
)
_REQUIRED_ASSET_CLAIM_KEYS: tuple[str, ...] = (
    "chain",
    "address",
    "representation_kind",
)


@dataclass(frozen=True, slots=True)
class AssetClaim:
    """One canonical asset/claim in a strategy vector (catalog section 3).

    ``address`` is the canonical mint/contract address on ``chain``.
    ``amount`` is a signed integer in base units (liabilities may be
    negative). ``None`` means UNKNOWN and is never treated as zero.
    ``decimals``/``issuer`` carry representation provenance; conservation
    treats claims with differing provenance as distinct rather than merging
    them silently.
    """

    chain: str
    address: str
    representation_kind: str
    decimals: int | None = None
    issuer: str | None = None
    amount: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "chain", _require_text(self.chain, "AssetClaim.chain"))
        object.__setattr__(
            self, "address", _require_text(self.address, "AssetClaim.address")
        )
        object.__setattr__(
            self,
            "representation_kind",
            _require_text(self.representation_kind, "AssetClaim.representation_kind"),
        )
        decimals = _optional_int(self.decimals, "AssetClaim.decimals")
        if decimals is not None and not 0 <= decimals <= 255:
            raise ContractTypeError("AssetClaim.decimals must be in 0..255 when known")
        object.__setattr__(self, "decimals", decimals)
        object.__setattr__(
            self, "issuer", _optional_text(self.issuer, "AssetClaim.issuer")
        )
        object.__setattr__(
            self, "amount", _optional_amount(self.amount, "AssetClaim.amount")
        )

    @property
    def claim_key(self) -> tuple[str, str, str]:
        """Canonical identity bucket for vector conservation (no scalarization)."""
        return (self.chain, self.address, self.representation_kind)

    @property
    def provenance(self) -> tuple[int | None, str | None]:
        return (self.decimals, self.issuer)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "address": self.address,
            "decimals": self.decimals,
            "representation_kind": self.representation_kind,
            "issuer": self.issuer,
            "amount": self.amount,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any], *, path: str = "AssetClaim"
    ) -> "AssetClaim":
        mapping = _require_mapping(payload, path)
        _check_payload_keys(
            mapping, _ALLOWED_ASSET_CLAIM_KEYS, _REQUIRED_ASSET_CLAIM_KEYS, path
        )
        return cls(
            chain=_require_text(mapping["chain"], f"{path}.chain"),
            address=_require_text(mapping["address"], f"{path}.address"),
            representation_kind=_require_text(
                mapping["representation_kind"], f"{path}.representation_kind"
            ),
            decimals=_optional_int(mapping.get("decimals"), f"{path}.decimals"),
            issuer=_optional_text(mapping.get("issuer"), f"{path}.issuer"),
            amount=_optional_amount(mapping.get("amount"), f"{path}.amount"),
        )


_ALLOWED_MARKET_DEPENDENCY_KEYS: frozenset[str] = frozenset(
    {
        "venue",
        "program_revision",
        "pool_or_book_id",
        "underlying_resource_ids",
        "state_generation",
        "max_freshness_seconds",
    }
)
_REQUIRED_MARKET_DEPENDENCY_KEYS: tuple[str, ...] = ("venue",)


@dataclass(frozen=True, slots=True)
class MarketDependency:
    """Catalog section 5: venue, revision, pool/book id, state generation.

    ``state_generation`` is a content-addressed generation identifier of the
    exact market state the strategy was evaluated against; ``None`` means the
    state generation is unknown, which is a typed blocker, not a default.
    Every tested size must re-quote every affected leg in coherent state
    (catalog section 9); the revision fields here pin which proofs apply.
    """

    venue: str
    program_revision: str | None = None
    pool_or_book_id: str | None = None
    underlying_resource_ids: tuple[str, ...] = ()
    state_generation: str | None = None
    max_freshness_seconds: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "venue", _require_text(self.venue, "MarketDependency.venue")
        )
        object.__setattr__(
            self,
            "program_revision",
            _optional_text(self.program_revision, "MarketDependency.program_revision"),
        )
        object.__setattr__(
            self,
            "pool_or_book_id",
            _optional_text(self.pool_or_book_id, "MarketDependency.pool_or_book_id"),
        )
        object.__setattr__(
            self,
            "underlying_resource_ids",
            _string_tuple(
                self.underlying_resource_ids, "MarketDependency.underlying_resource_ids"
            ),
        )
        object.__setattr__(
            self,
            "state_generation",
            _optional_text(self.state_generation, "MarketDependency.state_generation"),
        )
        object.__setattr__(
            self,
            "max_freshness_seconds",
            _optional_amount(
                self.max_freshness_seconds,
                "MarketDependency.max_freshness_seconds",
                non_negative=True,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "program_revision": self.program_revision,
            "pool_or_book_id": self.pool_or_book_id,
            "underlying_resource_ids": list(self.underlying_resource_ids),
            "state_generation": self.state_generation,
            "max_freshness_seconds": self.max_freshness_seconds,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any], *, path: str = "MarketDependency"
    ) -> "MarketDependency":
        mapping = _require_mapping(payload, path)
        _check_payload_keys(
            mapping,
            _ALLOWED_MARKET_DEPENDENCY_KEYS,
            _REQUIRED_MARKET_DEPENDENCY_KEYS,
            path,
        )
        return cls(
            venue=_require_text(mapping["venue"], f"{path}.venue"),
            program_revision=_optional_text(
                mapping.get("program_revision"), f"{path}.program_revision"
            ),
            pool_or_book_id=_optional_text(
                mapping.get("pool_or_book_id"), f"{path}.pool_or_book_id"
            ),
            underlying_resource_ids=_string_tuple(
                mapping.get("underlying_resource_ids", ()),
                f"{path}.underlying_resource_ids",
            ),
            state_generation=_optional_text(
                mapping.get("state_generation"), f"{path}.state_generation"
            ),
            max_freshness_seconds=_optional_amount(
                mapping.get("max_freshness_seconds"),
                f"{path}.max_freshness_seconds",
                non_negative=True,
            ),
        )


_ALLOWED_QUOTE_REQUIREMENT_KEYS: frozenset[str] = frozenset(
    {
        "side",
        "input_asset",
        "output_asset",
        "exact_input_amount",
        "exact_output_amount",
        "fee_bps",
        "max_slippage_bps",
        "rounding",
        "partial_fill_allowed",
        "dust_tolerance",
        "ttl_seconds",
        "consumed_input_assets",
        "residual_assets",
    }
)
_REQUIRED_QUOTE_REQUIREMENT_KEYS: tuple[str, ...] = (
    "side",
    "input_asset",
    "output_asset",
)


@dataclass(frozen=True, slots=True)
class QuoteRequirement:
    """Catalog section 6: side, exact amounts, fees, rounding, dust, TTL.

    ``exact_input_amount``/``exact_output_amount`` are amount-specific; a
    quote is never scaled by a multiplier (catalog section 4). Only declare
    ``fee_bps`` when the fee is NOT already embedded in
    ``exact_output_amount`` — fees embedded in the quoted output must not be
    double-charged in the cost ledger.
    """

    side: str
    input_asset: AssetClaim
    output_asset: AssetClaim
    exact_input_amount: int | None = None
    exact_output_amount: int | None = None
    fee_bps: int | None = None
    max_slippage_bps: int | None = None
    rounding: str | None = None
    partial_fill_allowed: bool | None = None
    dust_tolerance: int | None = None
    ttl_seconds: int | None = None
    consumed_input_assets: tuple[AssetClaim, ...] = ()
    residual_assets: tuple[AssetClaim, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "side", _require_text(self.side, "QuoteRequirement.side")
        )
        object.__setattr__(
            self,
            "input_asset",
            _require_instance(
                self.input_asset, AssetClaim, "QuoteRequirement.input_asset"
            ),
        )
        object.__setattr__(
            self,
            "output_asset",
            _require_instance(
                self.output_asset, AssetClaim, "QuoteRequirement.output_asset"
            ),
        )
        for field_name in (
            "exact_input_amount",
            "exact_output_amount",
            "fee_bps",
            "max_slippage_bps",
            "dust_tolerance",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_amount(
                    getattr(self, field_name),
                    f"QuoteRequirement.{field_name}",
                    non_negative=True,
                ),
            )
        object.__setattr__(
            self, "rounding", _optional_text(self.rounding, "QuoteRequirement.rounding")
        )
        object.__setattr__(
            self,
            "partial_fill_allowed",
            _optional_bool(
                self.partial_fill_allowed, "QuoteRequirement.partial_fill_allowed"
            ),
        )
        ttl = _optional_amount(
            self.ttl_seconds, "QuoteRequirement.ttl_seconds", non_negative=True
        )
        if ttl == 0:
            raise ContractTypeError(
                "QuoteRequirement.ttl_seconds must be positive when known"
            )
        object.__setattr__(self, "ttl_seconds", ttl)
        object.__setattr__(
            self,
            "consumed_input_assets",
            _normalize_instances(
                self.consumed_input_assets,
                AssetClaim,
                "QuoteRequirement.consumed_input_assets",
            ),
        )
        object.__setattr__(
            self,
            "residual_assets",
            _normalize_instances(
                self.residual_assets, AssetClaim, "QuoteRequirement.residual_assets"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "input_asset": self.input_asset.to_dict(),
            "output_asset": self.output_asset.to_dict(),
            "exact_input_amount": self.exact_input_amount,
            "exact_output_amount": self.exact_output_amount,
            "fee_bps": self.fee_bps,
            "max_slippage_bps": self.max_slippage_bps,
            "rounding": self.rounding,
            "partial_fill_allowed": self.partial_fill_allowed,
            "dust_tolerance": self.dust_tolerance,
            "ttl_seconds": self.ttl_seconds,
            "consumed_input_assets": [
                claim.to_dict() for claim in self.consumed_input_assets
            ],
            "residual_assets": [claim.to_dict() for claim in self.residual_assets],
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any], *, path: str = "QuoteRequirement"
    ) -> "QuoteRequirement":
        mapping = _require_mapping(payload, path)
        _check_payload_keys(
            mapping,
            _ALLOWED_QUOTE_REQUIREMENT_KEYS,
            _REQUIRED_QUOTE_REQUIREMENT_KEYS,
            path,
        )
        return cls(
            side=_require_text(mapping["side"], f"{path}.side"),
            input_asset=AssetClaim.from_dict(
                mapping["input_asset"], path=f"{path}.input_asset"
            ),
            output_asset=AssetClaim.from_dict(
                mapping["output_asset"], path=f"{path}.output_asset"
            ),
            exact_input_amount=_optional_amount(
                mapping.get("exact_input_amount"),
                f"{path}.exact_input_amount",
                non_negative=True,
            ),
            exact_output_amount=_optional_amount(
                mapping.get("exact_output_amount"),
                f"{path}.exact_output_amount",
                non_negative=True,
            ),
            fee_bps=_optional_amount(
                mapping.get("fee_bps"), f"{path}.fee_bps", non_negative=True
            ),
            max_slippage_bps=_optional_amount(
                mapping.get("max_slippage_bps"),
                f"{path}.max_slippage_bps",
                non_negative=True,
            ),
            rounding=_optional_text(mapping.get("rounding"), f"{path}.rounding"),
            partial_fill_allowed=_optional_bool(
                mapping.get("partial_fill_allowed"), f"{path}.partial_fill_allowed"
            ),
            dust_tolerance=_optional_amount(
                mapping.get("dust_tolerance"),
                f"{path}.dust_tolerance",
                non_negative=True,
            ),
            ttl_seconds=_optional_amount(
                mapping.get("ttl_seconds"), f"{path}.ttl_seconds", non_negative=True
            ),
            consumed_input_assets=_object_list(
                mapping.get("consumed_input_assets", ()),
                AssetClaim.from_dict,
                f"{path}.consumed_input_assets",
            ),
            residual_assets=_object_list(
                mapping.get("residual_assets", ()),
                AssetClaim.from_dict,
                f"{path}.residual_assets",
            ),
        )


_ALLOWED_FUNDING_REQUIREMENT_KEYS: frozenset[str] = frozenset(
    {
        "provider",
        "asset",
        "caller_eligible",
        "borrow_amount",
        "fee_amount",
        "capacity_amount",
        "repayment_asset",
        "repayment_amount",
        "callback_required",
        "atomicity_proof",
    }
)


@dataclass(frozen=True, slots=True)
class FundingRequirement:
    """Catalog section 7: provider, eligibility, borrow/fee/capacity, repay.

    Capacity is lender-evidenced capacity, never a TVL proxy. Unknown fields
    stay ``None``; ``atomicity_proof`` is a reference to an offline proof and
    stays ``None`` until that proof exists.
    """

    provider: str | None = None
    asset: AssetClaim | None = None
    caller_eligible: bool | None = None
    borrow_amount: int | None = None
    fee_amount: int | None = None
    capacity_amount: int | None = None
    repayment_asset: AssetClaim | None = None
    repayment_amount: int | None = None
    callback_required: bool | None = None
    atomicity_proof: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider",
            _optional_text(self.provider, "FundingRequirement.provider"),
        )
        object.__setattr__(
            self,
            "asset",
            _optional_instance(self.asset, AssetClaim, "FundingRequirement.asset"),
        )
        object.__setattr__(
            self,
            "caller_eligible",
            _optional_bool(self.caller_eligible, "FundingRequirement.caller_eligible"),
        )
        for field_name in (
            "borrow_amount",
            "fee_amount",
            "capacity_amount",
            "repayment_amount",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_amount(
                    getattr(self, field_name),
                    f"FundingRequirement.{field_name}",
                    non_negative=True,
                ),
            )
        object.__setattr__(
            self,
            "repayment_asset",
            _optional_instance(
                self.repayment_asset, AssetClaim, "FundingRequirement.repayment_asset"
            ),
        )
        object.__setattr__(
            self,
            "callback_required",
            _optional_bool(
                self.callback_required, "FundingRequirement.callback_required"
            ),
        )
        object.__setattr__(
            self,
            "atomicity_proof",
            _optional_text(self.atomicity_proof, "FundingRequirement.atomicity_proof"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "asset": self.asset.to_dict() if self.asset is not None else None,
            "caller_eligible": self.caller_eligible,
            "borrow_amount": self.borrow_amount,
            "fee_amount": self.fee_amount,
            "capacity_amount": self.capacity_amount,
            "repayment_asset": (
                self.repayment_asset.to_dict()
                if self.repayment_asset is not None
                else None
            ),
            "repayment_amount": self.repayment_amount,
            "callback_required": self.callback_required,
            "atomicity_proof": self.atomicity_proof,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any], *, path: str = "FundingRequirement"
    ) -> "FundingRequirement":
        mapping = _require_mapping(payload, path)
        _check_payload_keys(mapping, _ALLOWED_FUNDING_REQUIREMENT_KEYS, (), path)
        return cls(
            provider=_optional_text(mapping.get("provider"), f"{path}.provider"),
            asset=_optional_nested_dict(
                mapping.get("asset"), AssetClaim.from_dict, f"{path}.asset"
            ),
            caller_eligible=_optional_bool(
                mapping.get("caller_eligible"), f"{path}.caller_eligible"
            ),
            borrow_amount=_optional_amount(
                mapping.get("borrow_amount"), f"{path}.borrow_amount", non_negative=True
            ),
            fee_amount=_optional_amount(
                mapping.get("fee_amount"), f"{path}.fee_amount", non_negative=True
            ),
            capacity_amount=_optional_amount(
                mapping.get("capacity_amount"),
                f"{path}.capacity_amount",
                non_negative=True,
            ),
            repayment_asset=_optional_nested_dict(
                mapping.get("repayment_asset"),
                AssetClaim.from_dict,
                f"{path}.repayment_asset",
            ),
            repayment_amount=_optional_amount(
                mapping.get("repayment_amount"),
                f"{path}.repayment_amount",
                non_negative=True,
            ),
            callback_required=_optional_bool(
                mapping.get("callback_required"), f"{path}.callback_required"
            ),
            atomicity_proof=_optional_text(
                mapping.get("atomicity_proof"), f"{path}.atomicity_proof"
            ),
        )


_ALLOWED_SHARED_RESOURCE_COST_KEYS: frozenset[str] = frozenset(
    {"resource_id", "amount", "unit"}
)
_REQUIRED_SHARED_RESOURCE_COST_KEYS: tuple[str, ...] = ("resource_id",)


@dataclass(frozen=True, slots=True)
class SharedResourceCost:
    """One shared fixed cost line attached to a shared resource.

    A split path applies shared fixed costs once and variable costs per path
    (catalog section 4). ``amount`` stays ``None`` while unknown; when the
    amount is known, ``unit`` is required so numbers are never unitless.
    """

    resource_id: str
    amount: int | None = None
    unit: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "resource_id",
            _require_text(self.resource_id, "SharedResourceCost.resource_id"),
        )
        amount = _optional_amount(
            self.amount, "SharedResourceCost.amount", non_negative=True
        )
        object.__setattr__(self, "amount", amount)
        unit = _optional_text(self.unit, "SharedResourceCost.unit")
        if amount is not None and unit is None:
            raise ContractTypeError(
                "SharedResourceCost.unit is required when amount is known; "
                "unknown costs stay None and are never coerced to zero"
            )
        object.__setattr__(self, "unit", unit)

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "amount": self.amount,
            "unit": self.unit,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any], *, path: str = "SharedResourceCost"
    ) -> "SharedResourceCost":
        mapping = _require_mapping(payload, path)
        _check_payload_keys(
            mapping,
            _ALLOWED_SHARED_RESOURCE_COST_KEYS,
            _REQUIRED_SHARED_RESOURCE_COST_KEYS,
            path,
        )
        return cls(
            resource_id=_require_text(mapping["resource_id"], f"{path}.resource_id"),
            amount=_optional_amount(
                mapping.get("amount"), f"{path}.amount", non_negative=True
            ),
            unit=_optional_text(mapping.get("unit"), f"{path}.unit"),
        )


_ALLOWED_COST_LEDGER_KEYS: frozenset[str] = frozenset(
    {
        "unit",
        "dex_fee",
        "maker_fee",
        "taker_fee",
        "flash_fee",
        "network_fee",
        "priority_fee",
        "tip_amount",
        "compute_cost",
        "rent_cost",
        "provider_api_cost",
        "hedge_cost",
        "funding_cost",
        "borrow_cost",
        "inventory_markout",
        "failed_attempt_cost",
    }
)

_COST_FIELDS: tuple[str, ...] = (
    "dex_fee",
    "maker_fee",
    "taker_fee",
    "flash_fee",
    "network_fee",
    "priority_fee",
    "tip_amount",
    "compute_cost",
    "rent_cost",
    "provider_api_cost",
    "hedge_cost",
    "funding_cost",
    "borrow_cost",
    "inventory_markout",
    "failed_attempt_cost",
)


@dataclass(frozen=True, slots=True)
class CostLedger:
    """Catalog section 8: full cost ledger.

    Catalog mapping: DEX fee -> ``dex_fee``; maker/taker -> ``maker_fee``/
    ``taker_fee``; flash fee -> ``flash_fee``; network/priority/tip ->
    ``network_fee``/``priority_fee``/``tip_amount``; compute -> ``compute_cost``;
    rent -> ``rent_cost``; provider/API -> ``provider_api_cost``; hedge ->
    ``hedge_cost``; funding -> ``funding_cost``; borrow -> ``borrow_cost``;
    inventory markout -> ``inventory_markout`` (may be negative); failed
    attempts -> ``failed_attempt_cost``.

    Every cost field is ``Optional[int]``: ``None`` means UNKNOWN and is
    never coerced to 0. An explicit 0 is a measured zero and is distinct from
    unknown. When any cost is known, ``unit`` is required.
    """

    unit: str | None = None
    dex_fee: int | None = None
    maker_fee: int | None = None
    taker_fee: int | None = None
    flash_fee: int | None = None
    network_fee: int | None = None
    priority_fee: int | None = None
    tip_amount: int | None = None
    compute_cost: int | None = None
    rent_cost: int | None = None
    provider_api_cost: int | None = None
    hedge_cost: int | None = None
    funding_cost: int | None = None
    borrow_cost: int | None = None
    inventory_markout: int | None = None
    failed_attempt_cost: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "unit", _optional_text(self.unit, "CostLedger.unit"))
        known: list[int] = []
        for field_name in _COST_FIELDS:
            # inventory_markout may be adverse (negative) by definition; all
            # other costs are payments and must be non-negative when known.
            allow_negative = field_name == "inventory_markout"
            value = _optional_amount(
                getattr(self, field_name),
                f"CostLedger.{field_name}",
                non_negative=not allow_negative,
            )
            if value is not None:
                known.append(value)
            object.__setattr__(self, field_name, value)
        if known and self.unit is None:
            raise ContractTypeError(
                "CostLedger.unit is required when any cost amount is known; "
                "unknown costs stay None and are never coerced to zero"
            )

    def total(self) -> int | None:
        """Sum of all costs in ``unit``; ``None`` while any cost is UNKNOWN.

        A single unknown component keeps the total unknown so downstream
        economics can never pretend all costs were paid.
        """
        total = 0
        for field_name in _COST_FIELDS:
            value: int | None = getattr(self, field_name)
            if value is None:
                return None
            total += value
        return total

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"unit": self.unit}
        for field_name in _COST_FIELDS:
            payload[field_name] = getattr(self, field_name)
        return payload

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any], *, path: str = "CostLedger"
    ) -> "CostLedger":
        mapping = _require_mapping(payload, path)
        _check_payload_keys(mapping, _ALLOWED_COST_LEDGER_KEYS, (), path)
        return cls(
            unit=_optional_text(mapping.get("unit"), f"{path}.unit"),
            **{
                field_name: _optional_amount(
                    mapping.get(field_name), f"{path}.{field_name}", non_negative=True
                )
                for field_name in _COST_FIELDS
            },
        )


_ALLOWED_RESOURCE_MANIFEST_KEYS: frozenset[str] = frozenset(
    {"read_resources", "consumed_resources", "exclusive_resources", "shared_costs"}
)


@dataclass(frozen=True, slots=True)
class ResourceManifest:
    """Catalog section 10: shared resource set (SX-12 will consume this).

    ``read_resources`` are resources read during evaluation (state reads do
    not consume). ``consumed_resources`` are resources whose state the
    strategy consumes (pools, books, collateral, lender capacity, quota,
    blockspace). ``exclusive_resources`` require exclusive access during
    execution and must never be shared with concurrent strategies (shared
    resources cannot be consumed twice). ``shared_costs`` carry the fixed
    costs of shared resources, applied once per joint execution.
    """

    read_resources: tuple[str, ...] = ()
    consumed_resources: tuple[str, ...] = ()
    exclusive_resources: tuple[str, ...] = ()
    shared_costs: tuple[SharedResourceCost, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "read_resources",
            "consumed_resources",
            "exclusive_resources",
        ):
            object.__setattr__(
                self,
                field_name,
                _string_tuple(
                    getattr(self, field_name), f"ResourceManifest.{field_name}"
                ),
            )
        costs = _normalize_instances(
            self.shared_costs, SharedResourceCost, "ResourceManifest.shared_costs"
        )
        ordered_costs = tuple(
            sorted(costs, key=lambda cost: (cost.resource_id, cost.unit or ""))
        )
        object.__setattr__(self, "shared_costs", ordered_costs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "read_resources": list(self.read_resources),
            "consumed_resources": list(self.consumed_resources),
            "exclusive_resources": list(self.exclusive_resources),
            "shared_costs": [cost.to_dict() for cost in self.shared_costs],
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any], *, path: str = "ResourceManifest"
    ) -> "ResourceManifest":
        mapping = _require_mapping(payload, path)
        _check_payload_keys(mapping, _ALLOWED_RESOURCE_MANIFEST_KEYS, (), path)
        return cls(
            read_resources=_string_tuple(
                mapping.get("read_resources", ()), f"{path}.read_resources"
            ),
            consumed_resources=_string_tuple(
                mapping.get("consumed_resources", ()), f"{path}.consumed_resources"
            ),
            exclusive_resources=_string_tuple(
                mapping.get("exclusive_resources", ()), f"{path}.exclusive_resources"
            ),
            shared_costs=_object_list(
                mapping.get("shared_costs", ()),
                SharedResourceCost.from_dict,
                f"{path}.shared_costs",
            ),
        )


_ALLOWED_REPLAY_SPEC_KEYS: frozenset[str] = frozenset(
    {
        "corpus_hash",
        "replay_inputs",
        "data_lineage",
        "source_rights",
        "test_refs",
        "no_trade_reasons",
        "holdout",
    }
)


@dataclass(frozen=True, slots=True)
class ReplaySpec:
    """Catalog section 12: deterministic replay, lineage, no-trade corpus.

    ``corpus_hash`` addresses the evaluation corpus (input side).
    ``no_trade_reasons`` is the typed no-trade/rejection corpus;
    ``holdout`` names the held-out evaluation slices. All set-like fields
    are deduplicated and sorted for deterministic serialization.
    """

    corpus_hash: str | None = None
    replay_inputs: tuple[str, ...] = ()
    data_lineage: tuple[str, ...] = ()
    source_rights: tuple[str, ...] = ()
    test_refs: tuple[str, ...] = ()
    no_trade_reasons: tuple[str, ...] = ()
    holdout: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "corpus_hash",
            _optional_text(self.corpus_hash, "ReplaySpec.corpus_hash"),
        )
        for field_name in (
            "replay_inputs",
            "data_lineage",
            "source_rights",
            "test_refs",
            "no_trade_reasons",
            "holdout",
        ):
            object.__setattr__(
                self,
                field_name,
                _string_tuple(getattr(self, field_name), f"ReplaySpec.{field_name}"),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_hash": self.corpus_hash,
            "replay_inputs": list(self.replay_inputs),
            "data_lineage": list(self.data_lineage),
            "source_rights": list(self.source_rights),
            "test_refs": list(self.test_refs),
            "no_trade_reasons": list(self.no_trade_reasons),
            "holdout": list(self.holdout),
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any], *, path: str = "ReplaySpec"
    ) -> "ReplaySpec":
        mapping = _require_mapping(payload, path)
        _check_payload_keys(mapping, _ALLOWED_REPLAY_SPEC_KEYS, (), path)
        return cls(
            corpus_hash=_optional_text(
                mapping.get("corpus_hash"), f"{path}.corpus_hash"
            ),
            replay_inputs=_string_tuple(
                mapping.get("replay_inputs", ()), f"{path}.replay_inputs"
            ),
            data_lineage=_string_tuple(
                mapping.get("data_lineage", ()), f"{path}.data_lineage"
            ),
            source_rights=_string_tuple(
                mapping.get("source_rights", ()), f"{path}.source_rights"
            ),
            test_refs=_string_tuple(mapping.get("test_refs", ()), f"{path}.test_refs"),
            no_trade_reasons=_string_tuple(
                mapping.get("no_trade_reasons", ()), f"{path}.no_trade_reasons"
            ),
            holdout=_string_tuple(mapping.get("holdout", ()), f"{path}.holdout"),
        )


_ALLOWED_TYPED_BLOCKER_KEYS: frozenset[str] = frozenset({"reason", "detail"})
_REQUIRED_TYPED_BLOCKER_KEYS: tuple[str, ...] = ("reason",)


@dataclass(frozen=True, slots=True)
class TypedBlocker:
    """One typed blocker/rejection reason (catalog sections 12, 13)."""

    reason: TypedBlockerReason
    detail: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reason",
            _require_enum_instance(
                self.reason, TypedBlockerReason, "TypedBlocker.reason"
            ),
        )
        object.__setattr__(
            self, "detail", _optional_text(self.detail, "TypedBlocker.detail")
        )

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason.value, "detail": self.detail}

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any], *, path: str = "TypedBlocker"
    ) -> "TypedBlocker":
        mapping = _require_mapping(payload, path)
        _check_payload_keys(
            mapping, _ALLOWED_TYPED_BLOCKER_KEYS, _REQUIRED_TYPED_BLOCKER_KEYS, path
        )
        return cls(
            reason=_parse_enum(mapping["reason"], TypedBlockerReason, f"{path}.reason"),
            detail=_optional_text(mapping.get("detail"), f"{path}.detail"),
        )


_ALLOWED_TIER_EVIDENCE_KEYS: frozenset[str] = frozenset({"tier", "proof_ref"})
_REQUIRED_TIER_EVIDENCE_KEYS: tuple[str, ...] = ("tier", "proof_ref")


@dataclass(frozen=True, slots=True)
class TierEvidence:
    """One offline evidence reference for one promotion tier."""

    tier: PromotionTier
    proof_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "tier",
            _require_enum_instance(self.tier, PromotionTier, "TierEvidence.tier"),
        )
        object.__setattr__(
            self, "proof_ref", _require_text(self.proof_ref, "TierEvidence.proof_ref")
        )

    def to_dict(self) -> dict[str, Any]:
        return {"tier": self.tier.value, "proof_ref": self.proof_ref}

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any], *, path: str = "TierEvidence"
    ) -> "TierEvidence":
        mapping = _require_mapping(payload, path)
        _check_payload_keys(
            mapping, _ALLOWED_TIER_EVIDENCE_KEYS, _REQUIRED_TIER_EVIDENCE_KEYS, path
        )
        return cls(
            tier=_parse_enum(mapping["tier"], PromotionTier, f"{path}.tier"),
            proof_ref=_require_text(mapping["proof_ref"], f"{path}.proof_ref"),
        )


_ALLOWED_PROMOTION_EVIDENCE_KEYS: frozenset[str] = frozenset(
    {"claimed_tier", "evidence", "blockers", "issued_by", "issued_at"}
)
_REQUIRED_PROMOTION_EVIDENCE_KEYS: tuple[str, ...] = ("claimed_tier", "evidence")


@dataclass(frozen=True, slots=True)
class PromotionEvidence:
    """Catalog section 13: typed promotion evidence and explicit blockers.

    Monotonicity rule: claiming tier ``T`` requires evidence for every tier
    up to and including ``T`` — no skipped tiers, no evidence above the
    claim. There is no self-promotion: evidence is offline references and
    issuance attribution is recorded in ``issued_by``/``issued_at`` (pin all
    timestamps deterministically).
    """

    claimed_tier: PromotionTier
    evidence: tuple[TierEvidence, ...]
    blockers: tuple[TypedBlocker, ...] = ()
    issued_by: str | None = None
    issued_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "claimed_tier",
            _require_enum_instance(
                self.claimed_tier, PromotionTier, "PromotionEvidence.claimed_tier"
            ),
        )
        evidence = _normalize_instances(
            self.evidence, TierEvidence, "PromotionEvidence.evidence"
        )
        by_tier: dict[PromotionTier, TierEvidence] = {}
        for item in evidence:
            if item.tier in by_tier:
                raise ContractTypeError(
                    f"duplicate promotion evidence for tier {item.tier.value}"
                )
            by_tier[item.tier] = item
        expected = PROMOTION_LADDER[: self.claimed_tier.ladder_rank + 1]
        missing = [tier.value for tier in expected if tier not in by_tier]
        if missing:
            raise PromotionTierError(
                "promotion claims require prefix evidence with no skipped tiers; "
                f"claiming {self.claimed_tier.value} is missing evidence for: "
                f"{', '.join(missing)}"
            )
        unexpected = [tier.value for tier in by_tier if tier not in expected]
        if unexpected:
            raise PromotionTierError(
                "promotion evidence above claimed tier "
                f"{self.claimed_tier.value}: {', '.join(sorted(unexpected))}"
            )
        object.__setattr__(self, "evidence", tuple(by_tier[tier] for tier in expected))
        blockers = _normalize_instances(
            self.blockers, TypedBlocker, "PromotionEvidence.blockers"
        )
        blocker_keys = sorted(
            {(blocker.reason.value, blocker.detail or "") for blocker in blockers}
        )
        object.__setattr__(
            self,
            "blockers",
            tuple(
                TypedBlocker(TypedBlockerReason(reason), detail or None)
                for reason, detail in blocker_keys
            ),
        )
        object.__setattr__(
            self,
            "issued_by",
            _optional_text(self.issued_by, "PromotionEvidence.issued_by"),
        )
        object.__setattr__(
            self,
            "issued_at",
            _optional_text(self.issued_at, "PromotionEvidence.issued_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "claimed_tier": self.claimed_tier.value,
            "evidence": [item.to_dict() for item in self.evidence],
            "blockers": [blocker.to_dict() for blocker in self.blockers],
            "issued_by": self.issued_by,
            "issued_at": self.issued_at,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any], *, path: str = "PromotionEvidence"
    ) -> "PromotionEvidence":
        mapping = _require_mapping(payload, path)
        _check_payload_keys(
            mapping,
            _ALLOWED_PROMOTION_EVIDENCE_KEYS,
            _REQUIRED_PROMOTION_EVIDENCE_KEYS,
            path,
        )
        return cls(
            claimed_tier=_parse_enum(
                mapping["claimed_tier"], PromotionTier, f"{path}.claimed_tier"
            ),
            evidence=_object_list(
                mapping["evidence"], TierEvidence.from_dict, f"{path}.evidence"
            ),
            blockers=_object_list(
                mapping.get("blockers", ()), TypedBlocker.from_dict, f"{path}.blockers"
            ),
            issued_by=_optional_text(mapping.get("issued_by"), f"{path}.issued_by"),
            issued_at=_optional_text(mapping.get("issued_at"), f"{path}.issued_at"),
        )


# ---------------------------------------------------------------------------
# StrategyContractV1 — the 13-section canonical contract.
# ---------------------------------------------------------------------------

_ALLOWED_CONTRACT_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "strategy_id",
        "family_id",
        "version",
        "owner",
        "status",
        "source_task_ids",
        "hypothesis",
        "expected_sign",
        "null_hypothesis",
        "controls",
        "counterexamples",
        "input_claims",
        "output_claims",
        "execution_class",
        "settlement_domain",
        "transaction_boundary",
        "finality",
        "max_holding_horizon_seconds",
        "market_dependencies",
        "quote_requirements",
        "funding_requirements",
        "cost_ledger",
        "capacity_curve_ref",
        "sizing_owner",
        "resources",
        "risk_flags",
        "replay",
        "promotion",
    }
)

_REQUIRED_CONTRACT_KEYS: tuple[str, ...] = (
    "schema_version",
    "strategy_id",
    "family_id",
    "version",
    "owner",
    "status",
    "source_task_ids",
    "hypothesis",
    "expected_sign",
    "null_hypothesis",
    "input_claims",
    "output_claims",
    "execution_class",
    "market_dependencies",
    "cost_ledger",
    "resources",
    "replay",
    "promotion",
)


@dataclass(frozen=True, slots=True)
class StrategyContractV1:
    """Canonical strategy contract, version 1 (catalog sections 1-13).

    Catalog section -> fields:

    1. identity: ``strategy_id``, ``family_id``, ``version``, ``owner``,
       ``status``, ``source_task_ids``
    2. hypothesis: ``hypothesis``, ``expected_sign``, ``null_hypothesis``,
       ``controls``, ``counterexamples``
    3. asset/claim vectors: ``input_claims``, ``output_claims`` (AssetClaim)
    4. execution: ``execution_class``, ``settlement_domain``,
       ``transaction_boundary``, ``finality``, ``max_holding_horizon_seconds``
    5. market dependencies: ``market_dependencies`` (MarketDependency)
    6. quote requirements: ``quote_requirements`` (QuoteRequirement)
    7. funding requirements: ``funding_requirements`` (FundingRequirement)
    8. full costs: ``cost_ledger`` (CostLedger)
    9. capacity/sizing: ``capacity_curve_ref``, ``sizing_owner``; every
       tested size re-quotes every affected leg in coherent state
    10. shared resources: ``resources`` (ResourceManifest)
    11. risk model: ``risk_flags`` (RiskFlag)
    12. deterministic replay: ``replay`` (ReplaySpec)
    13. promotion: ``promotion`` (PromotionEvidence); no self-promotion

    Instances are frozen and content-addressed via :attr:`corpus_hash`. The
    contract is an advisory schema: it carries obligations and evidence, and
    grants no execution rights of any kind.
    """

    # 1. identity
    strategy_id: str
    family_id: str
    version: str
    owner: str
    status: ContractStatus
    source_task_ids: tuple[str, ...]
    # 2. hypothesis
    hypothesis: str
    expected_sign: ExpectedSign
    null_hypothesis: str
    # 3. asset/claim vectors
    input_claims: tuple[AssetClaim, ...]
    output_claims: tuple[AssetClaim, ...]
    # 4. execution
    execution_class: ExecutionClass
    # 5. market dependencies
    market_dependencies: tuple[MarketDependency, ...]
    # 8. full costs
    cost_ledger: CostLedger
    # 10. shared resources
    resources: ResourceManifest
    # 12. deterministic replay
    replay: ReplaySpec
    # 13. promotion evidence
    promotion: PromotionEvidence
    # 2. hypothesis (optional parts)
    controls: tuple[str, ...] = ()
    counterexamples: tuple[str, ...] = ()
    # 4. execution (optional parts)
    settlement_domain: str | None = None
    transaction_boundary: str | None = None
    finality: str | None = None
    max_holding_horizon_seconds: int | None = None
    # 6. quote requirements
    quote_requirements: tuple[QuoteRequirement, ...] = ()
    # 7. funding requirements
    funding_requirements: tuple[FundingRequirement, ...] = ()
    # 9. capacity/sizing
    capacity_curve_ref: str | None = None
    sizing_owner: str | None = None
    # 11. risk model
    risk_flags: tuple[RiskFlag, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "strategy_id",
            _require_text(self.strategy_id, "StrategyContractV1.strategy_id"),
        )
        object.__setattr__(
            self,
            "family_id",
            _require_text(self.family_id, "StrategyContractV1.family_id"),
        )
        object.__setattr__(
            self, "version", _require_text(self.version, "StrategyContractV1.version")
        )
        object.__setattr__(
            self, "owner", _require_text(self.owner, "StrategyContractV1.owner")
        )
        object.__setattr__(
            self,
            "status",
            _require_enum_instance(
                self.status, ContractStatus, "StrategyContractV1.status"
            ),
        )
        object.__setattr__(
            self,
            "source_task_ids",
            _string_tuple(
                self.source_task_ids,
                "StrategyContractV1.source_task_ids",
                non_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "hypothesis",
            _require_text(self.hypothesis, "StrategyContractV1.hypothesis"),
        )
        object.__setattr__(
            self,
            "expected_sign",
            _require_enum_instance(
                self.expected_sign, ExpectedSign, "StrategyContractV1.expected_sign"
            ),
        )
        object.__setattr__(
            self,
            "null_hypothesis",
            _require_text(self.null_hypothesis, "StrategyContractV1.null_hypothesis"),
        )
        object.__setattr__(
            self,
            "input_claims",
            _normalize_instances(
                self.input_claims, AssetClaim, "StrategyContractV1.input_claims"
            ),
        )
        object.__setattr__(
            self,
            "output_claims",
            _normalize_instances(
                self.output_claims, AssetClaim, "StrategyContractV1.output_claims"
            ),
        )
        object.__setattr__(
            self,
            "execution_class",
            _require_enum_instance(
                self.execution_class,
                ExecutionClass,
                "StrategyContractV1.execution_class",
            ),
        )
        object.__setattr__(
            self,
            "settlement_domain",
            _optional_text(
                self.settlement_domain, "StrategyContractV1.settlement_domain"
            ),
        )
        object.__setattr__(
            self,
            "transaction_boundary",
            _optional_text(
                self.transaction_boundary, "StrategyContractV1.transaction_boundary"
            ),
        )
        object.__setattr__(
            self,
            "finality",
            _optional_text(self.finality, "StrategyContractV1.finality"),
        )
        object.__setattr__(
            self,
            "max_holding_horizon_seconds",
            _optional_amount(
                self.max_holding_horizon_seconds,
                "StrategyContractV1.max_holding_horizon_seconds",
                non_negative=True,
            ),
        )
        object.__setattr__(
            self,
            "market_dependencies",
            _normalize_instances(
                self.market_dependencies,
                MarketDependency,
                "StrategyContractV1.market_dependencies",
            ),
        )
        object.__setattr__(
            self,
            "quote_requirements",
            _normalize_instances(
                self.quote_requirements,
                QuoteRequirement,
                "StrategyContractV1.quote_requirements",
            ),
        )
        object.__setattr__(
            self,
            "funding_requirements",
            _normalize_instances(
                self.funding_requirements,
                FundingRequirement,
                "StrategyContractV1.funding_requirements",
            ),
        )
        object.__setattr__(
            self,
            "cost_ledger",
            _require_instance(
                self.cost_ledger, CostLedger, "StrategyContractV1.cost_ledger"
            ),
        )
        object.__setattr__(
            self,
            "capacity_curve_ref",
            _optional_text(
                self.capacity_curve_ref, "StrategyContractV1.capacity_curve_ref"
            ),
        )
        object.__setattr__(
            self,
            "sizing_owner",
            _optional_text(self.sizing_owner, "StrategyContractV1.sizing_owner"),
        )
        object.__setattr__(
            self,
            "resources",
            _require_instance(
                self.resources, ResourceManifest, "StrategyContractV1.resources"
            ),
        )
        object.__setattr__(
            self,
            "controls",
            _string_tuple(self.controls, "StrategyContractV1.controls"),
        )
        object.__setattr__(
            self,
            "counterexamples",
            _string_tuple(self.counterexamples, "StrategyContractV1.counterexamples"),
        )
        risk_flags = _normalize_instances(
            self.risk_flags, RiskFlag, "StrategyContractV1.risk_flags"
        )
        object.__setattr__(
            self,
            "risk_flags",
            tuple(sorted(set(risk_flags), key=lambda flag: flag.value)),
        )
        object.__setattr__(
            self,
            "replay",
            _require_instance(self.replay, ReplaySpec, "StrategyContractV1.replay"),
        )
        object.__setattr__(
            self,
            "promotion",
            _require_instance(
                self.promotion, PromotionEvidence, "StrategyContractV1.promotion"
            ),
        )
        if (
            self.execution_class is ExecutionClass.EXCLUDED
            and self.promotion.claimed_tier is not PromotionTier.RESEARCH_SEED
        ):
            raise PromotionTierError(
                "EXCLUDED execution class cannot be upgraded; "
                "promotion tier must remain RESEARCH_SEED"
            )

    def to_dict(self) -> dict[str, Any]:
        """Stable plain-dict serialization; ``from_dict(to_dict(c)) == c``."""
        return {
            "schema_version": SCHEMA_VERSION,
            "strategy_id": self.strategy_id,
            "family_id": self.family_id,
            "version": self.version,
            "owner": self.owner,
            "status": self.status.value,
            "source_task_ids": list(self.source_task_ids),
            "hypothesis": self.hypothesis,
            "expected_sign": self.expected_sign.value,
            "null_hypothesis": self.null_hypothesis,
            "controls": list(self.controls),
            "counterexamples": list(self.counterexamples),
            "input_claims": [claim.to_dict() for claim in self.input_claims],
            "output_claims": [claim.to_dict() for claim in self.output_claims],
            "execution_class": self.execution_class.value,
            "settlement_domain": self.settlement_domain,
            "transaction_boundary": self.transaction_boundary,
            "finality": self.finality,
            "max_holding_horizon_seconds": self.max_holding_horizon_seconds,
            "market_dependencies": [dep.to_dict() for dep in self.market_dependencies],
            "quote_requirements": [
                quote.to_dict() for quote in self.quote_requirements
            ],
            "funding_requirements": [
                funding.to_dict() for funding in self.funding_requirements
            ],
            "cost_ledger": self.cost_ledger.to_dict(),
            "capacity_curve_ref": self.capacity_curve_ref,
            "sizing_owner": self.sizing_owner,
            "resources": self.resources.to_dict(),
            "risk_flags": [flag.value for flag in self.risk_flags],
            "replay": self.replay.to_dict(),
            "promotion": self.promotion.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StrategyContractV1":
        """Fail-closed parse: unknown fields raise UnknownContractFieldError
        and missing required fields raise MissingContractFieldError."""
        mapping = _require_mapping(payload, "contract")
        _check_payload_keys(
            mapping, _ALLOWED_CONTRACT_KEYS, _REQUIRED_CONTRACT_KEYS, "contract"
        )
        if mapping["schema_version"] != SCHEMA_VERSION:
            raise ContractTypeError(
                f"contract.schema_version must be {SCHEMA_VERSION!r}; "
                f"got {mapping['schema_version']!r}"
            )
        return cls(
            strategy_id=_require_text(mapping["strategy_id"], "contract.strategy_id"),
            family_id=_require_text(mapping["family_id"], "contract.family_id"),
            version=_require_text(mapping["version"], "contract.version"),
            owner=_require_text(mapping["owner"], "contract.owner"),
            status=_parse_enum(mapping["status"], ContractStatus, "contract.status"),
            source_task_ids=_string_tuple(
                mapping["source_task_ids"], "contract.source_task_ids", non_empty=True
            ),
            hypothesis=_require_text(mapping["hypothesis"], "contract.hypothesis"),
            expected_sign=_parse_enum(
                mapping["expected_sign"], ExpectedSign, "contract.expected_sign"
            ),
            null_hypothesis=_require_text(
                mapping["null_hypothesis"], "contract.null_hypothesis"
            ),
            controls=_string_tuple(mapping.get("controls", ()), "contract.controls"),
            counterexamples=_string_tuple(
                mapping.get("counterexamples", ()), "contract.counterexamples"
            ),
            input_claims=_object_list(
                mapping["input_claims"], AssetClaim.from_dict, "contract.input_claims"
            ),
            output_claims=_object_list(
                mapping["output_claims"], AssetClaim.from_dict, "contract.output_claims"
            ),
            execution_class=_parse_enum(
                mapping["execution_class"], ExecutionClass, "contract.execution_class"
            ),
            settlement_domain=_optional_text(
                mapping.get("settlement_domain"), "contract.settlement_domain"
            ),
            transaction_boundary=_optional_text(
                mapping.get("transaction_boundary"), "contract.transaction_boundary"
            ),
            finality=_optional_text(mapping.get("finality"), "contract.finality"),
            max_holding_horizon_seconds=_optional_amount(
                mapping.get("max_holding_horizon_seconds"),
                "contract.max_holding_horizon_seconds",
                non_negative=True,
            ),
            market_dependencies=_object_list(
                mapping["market_dependencies"],
                MarketDependency.from_dict,
                "contract.market_dependencies",
            ),
            quote_requirements=_object_list(
                mapping.get("quote_requirements", ()),
                QuoteRequirement.from_dict,
                "contract.quote_requirements",
            ),
            funding_requirements=_object_list(
                mapping.get("funding_requirements", ()),
                FundingRequirement.from_dict,
                "contract.funding_requirements",
            ),
            cost_ledger=CostLedger.from_dict(
                mapping["cost_ledger"], path="contract.cost_ledger"
            ),
            capacity_curve_ref=_optional_text(
                mapping.get("capacity_curve_ref"), "contract.capacity_curve_ref"
            ),
            sizing_owner=_optional_text(
                mapping.get("sizing_owner"), "contract.sizing_owner"
            ),
            resources=ResourceManifest.from_dict(
                mapping["resources"], path="contract.resources"
            ),
            risk_flags=_enum_tuple(
                mapping.get("risk_flags", ()), RiskFlag, "contract.risk_flags"
            ),
            replay=ReplaySpec.from_dict(mapping["replay"], path="contract.replay"),
            promotion=PromotionEvidence.from_dict(
                mapping["promotion"], path="contract.promotion"
            ),
        )

    def canonical_json(self) -> str:
        """Deterministic JSON (sorted keys, compact separators, ASCII-safe)."""
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )

    @property
    def corpus_hash(self) -> str:
        """SHA-256 of the canonical serialization.

        Equal contracts serialize to equal dicts and therefore hash equally;
        any semantic change produces a different hash.
        """
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Economics helpers (catalog sections 2 and 4).
# ---------------------------------------------------------------------------


def strictest_execution_class(classes: Sequence[ExecutionClass]) -> ExecutionClass:
    """Return the strictest execution class of all legs (catalog section 2).

    "Each candidate route inherits the strictest class of all legs and must
    satisfy all obligations." An empty leg set has no route class and fails
    closed. An EXCLUDED leg makes the whole route EXCLUDED; there is no
    upgrade path away from EXCLUDED.
    """
    if not classes:
        raise StrategyContractError(
            "cannot derive the strictest execution class of an empty leg set"
        )
    return max(classes, key=lambda item: item.strictness_rank)


def claims_conserved(
    inputs: Sequence[AssetClaim],
    outputs: Sequence[AssetClaim],
    fees: Sequence[AssetClaim] = (),
) -> bool:
    """Per-asset vector conservation (catalog section 4).

    Groups claims by canonical identity ``(chain, address,
    representation_kind)`` and requires, for every group::

        sum(inputs) == sum(outputs) + sum(fees)

    Fee legs are explicit participants, not hidden deductions. Claims with
    differing provenance (``decimals``/``issuer``) inside one identity group
    are never silently merged. Assets are conserved separately — no
    scalarization and no cross-asset netting.

    Raises ``ConservationError`` when a group does not balance, when
    provenance conflicts within a group, or when any amount is UNKNOWN
    (``None``): unknown is never treated as zero. Returns ``True`` when every
    group balances (a vacuous empty vector set is conserved).
    """
    balances: dict[tuple[str, str, str], int | None] = {}
    provenance: dict[tuple[str, str, str], tuple[int | None, str | None]] = {}
    for side, claims, sign in (
        ("input", inputs, 1),
        ("output", outputs, -1),
        ("fee", fees, -1),
    ):
        for claim in claims:
            if not isinstance(claim, AssetClaim):
                raise ConservationError(
                    f"{side} claims must be AssetClaim instances; "
                    f"got {type(claim).__name__}"
                )
            key = claim.claim_key
            previous = provenance.get(key)
            if previous is not None and previous != claim.provenance:
                raise ConservationError(
                    f"claim provenance mismatch for {key}: "
                    f"{previous} vs {claim.provenance}; refusing to merge"
                )
            provenance[key] = claim.provenance
            if key not in balances:
                balances[key] = 0
            current = balances[key]
            if claim.amount is None or current is None:
                balances[key] = None
            else:
                balances[key] = current + sign * claim.amount
    for key in sorted(provenance):
        delta = balances.get(key)
        if delta is None:
            raise ConservationError(
                f"unknown claim amount for {key}; cannot verify conservation "
                f"(unknown is not zero)"
            )
        if delta != 0:
            raise ConservationError(
                f"claims not conserved for {key}: net delta {delta}"
            )
    return True
