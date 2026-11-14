"""R13-K frozen quote/build kernel contract (additive, offline, sender-free).

This module freezes ONE shared kernel contract for the R13 multi-provider
quote/build race, closing the two highest-ranked typed blockers of
``docs/roadmap/agent-execution-master-2026-11-13/reports/R13_QUOTE_BUILD_RACE_AUDIT_2026-11-14.md``:

- ``R13_GAP_NO_KERNEL``: there was no single NormalizedQuote/race/dedup/
  build-handoff contract; three partially-overlapping quote planes existed.
- ``R13_GAP_NO_POOL_DEDUP``: route legs and correlation labels were retained,
  but no pool-ID/aggregator-lineage intersection dedup was computed anywhere.

Package placement (deliberate): ``src/execution/`` is the existing execution
domain package and already hosts supported, mypy-governed owners such as
``src/execution/exact_simulation.py`` (the exact sender-free simulation owner,
see ``docs/roadmap/agent-execution-master-2026-11-13/PROJECT_KNOWLEDGE_BASE_MAP.md``
section 6). Only ``src/execution/senders/`` is quarantined legacy. The kernel
is the seam BETWEEN the quote planes and the R-03 builder plane and ends at
the same boundary exact simulation starts at, so the execution package is the
correct existing home. Rejected alternatives: ``src/routing/`` (one specific
plane's owner; the kernel must sit above all planes) and
``src/lending/unsigned_builders/`` (the frozen R-03 contract package, which
must not gain quote-race concerns). This module is consumed directly as
``src.execution.quote_build_kernel`` with no ``__init__`` registration change
(same pattern as ``src.lending.unsigned_builders.kamino_builder``).

Name mapping (UXE-00 documented contract -> frozen kernel owner):

======================================  =========================================
UXE-00 documented name                  Kernel owner (this module)
======================================  =========================================
``QuoteProvider``                       NOT defined here. Physical reads remain
                                        owned by the existing planes (governed
                                        ``GovernedReadPlane`` and routing
                                        ``DiscoveryProvider``). The kernel
                                        consumes their normalized outputs.
``NormalizedQuote``                     :class:`NormalizedProviderQuote`
``ProviderCorrelation``                 :class:`ProviderCorrelation`
correlation-aware ranking               :class:`QuoteRaceResult` +
                                        :class:`PoolIdentityDeduplicator`
``TransactionBuilder``                  NOT defined here. Construction stays
                                        owned by the R-03 builders
                                        (``src/lending/unsigned_builders/``).
                                        :class:`BuildHandoff` is only a typed
                                        reference seam.
``UnsignedExecutionPlan``               Referenced via the R-03 plan family
                                        (:data:`R03UnsignedPlan`), imported from
                                        ``src/lending/unsigned_builders/contract.py``.
======================================  =========================================

Existing-plane mapping (documented, no import coupling):

- routing plane ``SwapMode`` ("ExactIn"/"ExactOut") <-> :class:`QuoteDirection`
  (identical wire values).
- routing plane ``NonSelectionReason`` and governed negative receipt quality
  states <-> :class:`QuoteLossReason` / :class:`ProviderReadFailureClass`
  (kernel-local typed subsets; plane reasons map onto them, never around them).
- routing plane ``QuoteFeeComponent``/``SemanticState`` <-> kernel
  :class:`QuoteFeeComponent`/ :class:`FeeInclusionState` (same inclusion
  vocabulary).
- governed plane ``QuotePreview`` fields (slot/observed_at_ns/correlation_
  group/raw evidence) map onto :class:`QuoteFreshness` and
  :class:`ProviderCorrelation`.
- Sui ``CheckpointProviderBinding`` correlation governance
  (``SUI_CORRELATED_PROVIDERS_BLOCKED``) is the model for
  :class:`ProviderCorrelation` group equality = correlated.

Frozen invariants (fail closed):

1. Kernel quotes are DISCOVERY evidence only: ``execution_authority`` is a
   literal ``False`` field and a constructor invariant (governed-plane
   authority ceiling preserved; no promotion authority is added here).
2. UNKNOWN is never zero: ``minimum_output_raw=None`` means unknown and is
   preserved as unknown; a loser carries ``MINIMUM_OUTPUT_UNPROVEN`` instead
   of being coerced to a fake threshold.
3. Pool-identity dedup rule set: quotes sharing ANY underlying pool identity,
   ANY aggregator lineage member, or the SAME operator correlation group are
   CORRELATED observations, never independent liquidity. Independence
   requires positive disjoint-pool evidence on both sides plus disjoint
   lineage and different groups; anything less is ``UNKNOWN`` (unknown is
   never independent).
4. Race results preserve ALL provider observations: every quote (winner and
   losers, with typed loss reasons) and every failed read (typed failure
   class) is retained and deterministically ranked.
5. No-extrapolation invariant: every sizing point requires a re-quote at the
   exact amount. :func:`refuse_amount_extrapolation` refuses ANY other amount
   — including amount-neighborhood perturbations — with a typed error.
6. Build handoff is a typed reference, never construction logic: the kernel
   never builds instructions/PTBs; it binds a won quote to an EXISTING R-03
   plan object with fail-closed integrity parity checks (provider, chain,
   build status). Build/capacity status separation is inherited from the
   R-03 contract enums by import, not duplicated.

No network, no signing, no sending, no provider enablement, no boot-path
wiring: wiring a won quote through this seam into a live pipeline is DEFERRED
to a follow-up lane. Existing owners (``src/solana_parallel_radar/``,
``src/routing/``, ``src/lending/unsigned_builders/``, ``src/gpr_sui_shadow/``,
``src/planning/rent_sponsor_planner.py``) are untouched by this freeze.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Sequence, Union

from src.lending.unsigned_builders.contract import (
    BuildStatus,
    FinalizedUnsignedSolanaPlan,
    PtBuildResult,
    UnsignedBorrowPlan,
    UnsignedRepayPlan,
    canonical_hash,
)

__all__ = [
    "BuildHandoff",
    "BuildHandoffError",
    "FeeInclusionState",
    "IndependenceVerdict",
    "KernelContractError",
    "KernelErrorCode",
    "MAX_AGE_NS",
    "MAX_PROVIDERS",
    "MAX_ROUTE_VENUES",
    "MAX_SLOT_GAP",
    "NormalizedProviderQuote",
    "PoolIdentity",
    "PoolIdentityDeduplicator",
    "PoolIdentityKind",
    "ProviderCorrelation",
    "ProviderReadFailure",
    "ProviderReadFailureClass",
    "QUOTE_BUILD_KERNEL_VERSION",
    "QuoteComparabilityError",
    "QuoteCorrelationCluster",
    "QuoteDirection",
    "QuoteExtrapolationError",
    "QuoteFeeComponent",
    "QuoteFreshness",
    "QuoteLossReason",
    "QuoteRaceRequest",
    "QuoteRaceResult",
    "QuoteRaceStateError",
    "R03UnsignedPlan",
    "RaceVerdict",
    "RankedQuoteEntry",
    "RouteVenue",
    "refuse_amount_extrapolation",
]

# --------------------------------------------------------------------------
# Frozen kernel identity and hard bounds (mirroring governed-plane bounds)
# --------------------------------------------------------------------------

QUOTE_BUILD_KERNEL_VERSION = "r13.quote-build-kernel.v1"

#: Hard freshness argument bound, equal to the governed plane's
#: ``compare_quotes(max_age_ns=45_000_000_000)`` ceiling. Wider bounds are
#: refused, not accepted.
MAX_AGE_NS = 45_000_000_000
#: Hard context-slot skew bound, equal to the governed plane's
#: ``max_slot_gap=32`` ceiling.
MAX_SLOT_GAP = 32
MAX_ROUTE_VENUES = 32
MAX_POOL_IDENTITIES = 256
MAX_PROVIDERS = 64
MAX_TEXT = 256

_CHAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class KernelErrorCode(StrEnum):
    """Typed fail-closed kernel error codes."""

    INVALID_INPUT = "R13_KERNEL_INVALID_INPUT"
    EXECUTION_AUTHORITY_FORBIDDEN = "R13_KERNEL_EXECUTION_AUTHORITY_FORBIDDEN"
    COMPARABILITY_MISMATCH = "R13_KERNEL_QUOTE_COMPARABILITY_MISMATCH"
    FUTURE_OBSERVATION = "R13_KERNEL_QUOTE_FUTURE_OBSERVATION"
    RACE_INPUT_INVALID = "R13_KERNEL_QUOTE_RACE_INPUT_INVALID"
    RACE_NO_WINNER = "R13_KERNEL_QUOTE_RACE_NO_WINNER"
    EXTRAPOLATION_REFUSED = "R13_KERNEL_QUOTE_EXTRAPOLATION_REFUSED"
    HANDOFF_INTEGRITY = "R13_KERNEL_BUILD_HANDOFF_INTEGRITY"
    HANDOFF_NOT_WINNER = "R13_KERNEL_BUILD_HANDOFF_NOT_WINNER"


class KernelContractError(ValueError):
    """Base class for every fail-closed kernel contract error."""

    def __init__(self, code: KernelErrorCode, message: str) -> None:
        super().__init__(f"{code.value}: {message}")
        self.code = code
        self.message = message


class QuoteComparabilityError(KernelContractError):
    """Quotes are not comparable for one race (units/taker/time identity)."""


class QuoteRaceStateError(KernelContractError):
    """A race-state demand cannot be satisfied (e.g. no winner exists)."""


class QuoteExtrapolationError(KernelContractError):
    """An amount other than the quote's exact bound amount was requested."""


class BuildHandoffError(KernelContractError):
    """A build handoff failed its typed reference integrity checks."""


def _exact_positive_int(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise KernelContractError(
            KernelErrorCode.INVALID_INPUT,
            f"{label} must be an exact positive integer",
        )
    return value


def _exact_non_negative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise KernelContractError(
            KernelErrorCode.INVALID_INPUT,
            f"{label} must be an exact non-negative integer",
        )
    return value


def _optional_exact_int(value: object, label: str, *, positive: bool) -> int | None:
    if value is None:
        return None
    if positive:
        return _exact_positive_int(value, label)
    return _exact_non_negative_int(value, label)


def _require_text(value: object, label: str, *, max_len: int = MAX_TEXT) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise KernelContractError(KernelErrorCode.INVALID_INPUT, f"{label} is required")
    if len(value) > max_len:
        raise KernelContractError(
            KernelErrorCode.INVALID_INPUT, f"{label} exceeds {max_len} characters"
        )
    return value


def _optional_text(value: object, label: str, *, max_len: int = MAX_TEXT) -> str | None:
    if value is None:
        return None
    return _require_text(value, label, max_len=max_len)


# --------------------------------------------------------------------------
# Correlation and pool identity (R13_GAP_NO_POOL_DEDUP)
# --------------------------------------------------------------------------


class PoolIdentityKind(StrEnum):
    """Exact underlying pool identity kinds.

    Only POOL-level kinds establish or refute pool correlation. Venue-level
    attribution (dex label / program id) is evidence metadata and is carried
    on :class:`RouteVenue`, never on :class:`PoolIdentity`.
    """

    AMM_KEY = "amm_key"  # e.g. Jupiter V2 route-leg ``ammKey`` (base58)
    POOL_ADDRESS = "pool_address"  # pool account/contract address (case kept)
    POOL_OBJECT_ID = "pool_object_id"  # Sui shared pool object id (canonical)


class QuoteDirection(StrEnum):
    """Kernel direction, wire-value identical to routing ``SwapMode``."""

    EXACT_IN = "ExactIn"
    EXACT_OUT = "ExactOut"


@dataclass(frozen=True, slots=True)
class PoolIdentity:
    """One exact underlying pool identity in canonical provider-agnostic form.

    ``POOL_OBJECT_ID`` values are normalized to ``0x`` + 64 lowercase hex
    (shorthand Sui literals left-padded) so provider variants compare equal.
    ``AMM_KEY``/``POOL_ADDRESS`` keep their exact case (base58 is
    case-sensitive); equality is exact-string after strip.
    """

    kind: PoolIdentityKind
    identity: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PoolIdentityKind):
            raise KernelContractError(
                KernelErrorCode.INVALID_INPUT,
                "pool identity kind must be a PoolIdentityKind",
            )
        raw = _require_text(self.identity, "pool identity")
        if self.kind is PoolIdentityKind.POOL_OBJECT_ID:
            body = raw[2:] if raw.lower().startswith("0x") else raw
            if (
                not body
                or len(body) > 64
                or any(char not in "0123456789abcdefABCDEF" for char in body)
            ):
                raise KernelContractError(
                    KernelErrorCode.INVALID_INPUT,
                    "pool_object_id must be a 32-byte Sui object id",
                )
            object.__setattr__(self, "identity", "0x" + body.lower().rjust(64, "0"))
        elif len(raw) > 128:
            raise KernelContractError(
                KernelErrorCode.INVALID_INPUT, "pool identity exceeds 128 characters"
            )

    @property
    def key(self) -> tuple[str, str]:
        """Canonical cross-provider identity key."""
        return (self.kind.value, self.identity)


@dataclass(frozen=True, slots=True)
class ProviderCorrelation:
    """UXE-00 ``ProviderCorrelation``: operator + underlying identity.

    ``correlation_group`` is the operator-declared group (e.g. the governed
    plane's ``"jupiter-metis-router"``). ``aggregator_lineage`` is the
    aggregator chain that produced the quote (e.g. ``("openocean", "jupiter")``
    for an OpenOcean composite), already normalized to a sorted, deduplicated
    tuple. ``pool_ids`` are the exact underlying pool identities actually
    returned by the provider; empty means UNKNOWN, never "no pools".
    """

    correlation_group: str
    aggregator_lineage: tuple[str, ...] = ()
    pool_ids: tuple[PoolIdentity, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.correlation_group, "correlation_group", max_len=128)
        lineage = tuple(sorted(set(self.aggregator_lineage)))
        for member in lineage:
            _require_text(member, "aggregator lineage member", max_len=128)
        object.__setattr__(self, "aggregator_lineage", lineage)
        pools = tuple(sorted(set(self.pool_ids), key=lambda pool: pool.key))
        if len(pools) > MAX_POOL_IDENTITIES:
            raise KernelContractError(
                KernelErrorCode.INVALID_INPUT,
                f"more than {MAX_POOL_IDENTITIES} pool identities",
            )
        object.__setattr__(self, "pool_ids", pools)


@dataclass(frozen=True, slots=True)
class RouteVenue:
    """One route leg's venue attribution (topology order preserved).

    Venue-level labels/program ids never establish pool correlation nor
    independence; only :class:`PoolIdentity` does.
    """

    venue_label: str | None = None
    venue_program_id: str | None = None
    pool: PoolIdentity | None = None
    input_representation_id: str | None = None
    output_representation_id: str | None = None
    share_bps: int | None = None

    def __post_init__(self) -> None:
        _optional_text(self.venue_label, "route venue label", max_len=128)
        _optional_text(self.venue_program_id, "route venue program id", max_len=128)
        if self.share_bps is not None:
            share = _exact_non_negative_int(self.share_bps, "route venue share_bps")
            if share > 10_000:
                raise KernelContractError(
                    KernelErrorCode.INVALID_INPUT, "route venue share_bps exceeds 10000"
                )
        if (
            self.venue_label is None
            and self.venue_program_id is None
            and self.pool is None
        ):
            raise KernelContractError(
                KernelErrorCode.INVALID_INPUT,
                "route venue requires a label, program id or pool identity",
            )


class FeeInclusionState(StrEnum):
    """Fee inclusion vocabulary, mapped 1:1 from routing ``SemanticState``."""

    PROVEN = "proven"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class QuoteFeeComponent:
    """One fee component; unknown amounts stay ``None``, never coerced to 0."""

    kind: str
    amount_raw: int | None = None
    rate_text: str | None = None
    asset_id: str | None = None
    inclusion_state: FeeInclusionState = FeeInclusionState.UNKNOWN

    def __post_init__(self) -> None:
        _require_text(self.kind, "fee kind", max_len=128)
        _optional_exact_int(self.amount_raw, "fee amount_raw", positive=False)
        _optional_text(self.rate_text, "fee rate_text", max_len=128)
        _optional_text(self.asset_id, "fee asset_id")
        if not isinstance(self.inclusion_state, FeeInclusionState):
            raise KernelContractError(
                KernelErrorCode.INVALID_INPUT,
                "fee inclusion_state must be a FeeInclusionState",
            )


@dataclass(frozen=True, slots=True)
class QuoteFreshness:
    """Source generation timestamps and context; unknown stays ``None``.

    ``slot``/``checkpoint_sequence`` are recorded ONLY when the provider
    actually supplies them (governed-plane rule: never synthesized). This is
    the kernel mapping of the governed ``slot``/``observed_at_ns`` fields and
    the Sui checkpoint/object generation discipline.
    """

    received_at_ns: int
    provider_generated_at_ns: int | None = None
    slot: int | None = None
    checkpoint_sequence: int | None = None
    expires_at_ns: int | None = None

    def __post_init__(self) -> None:
        _exact_non_negative_int(self.received_at_ns, "freshness.received_at_ns")
        _optional_exact_int(
            self.provider_generated_at_ns,
            "freshness.provider_generated_at_ns",
            positive=False,
        )
        _optional_exact_int(self.slot, "freshness.slot", positive=False)
        _optional_exact_int(
            self.checkpoint_sequence, "freshness.checkpoint_sequence", positive=False
        )
        _optional_exact_int(
            self.expires_at_ns, "freshness.expires_at_ns", positive=False
        )


# --------------------------------------------------------------------------
# NormalizedProviderQuote (UXE-00 NormalizedQuote)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NormalizedProviderQuote:
    """One normalized provider quote preserved as typed race evidence.

    Every amount is an exact integer in base units. ``*_amount_raw`` is the
    provider's returned integer; ``*_amount_normalized`` is the canonical
    representation amount the adapter normalizes to BEFORE construction — the
    kernel refuses unnormalized quotes rather than guessing decimals
    (unknown is never guessed). ``minimum_output_raw=None`` is UNKNOWN and is
    preserved as unknown, never coerced to zero.
    """

    provider_id: str
    provider_generation: str
    chain: str
    direction: QuoteDirection
    input_representation_id: str
    output_representation_id: str
    input_amount_raw: int
    output_amount_raw: int
    input_amount_normalized: int
    output_amount_normalized: int
    correlation: ProviderCorrelation
    freshness: QuoteFreshness
    minimum_output_raw: int | None = None
    fees: tuple[QuoteFeeComponent, ...] = ()
    compute_unit_estimate: int | None = None
    route_venues: tuple[RouteVenue, ...] = ()
    taker: str | None = None
    raw_response_hash: str = ""
    request_fingerprint: str = ""
    execution_authority: bool = False

    def __post_init__(self) -> None:
        _require_text(self.provider_id, "provider_id", max_len=128)
        _require_text(self.provider_generation, "provider_generation", max_len=128)
        chain = _require_text(self.chain, "chain", max_len=64)
        if not _CHAIN_RE.fullmatch(chain):
            raise KernelContractError(
                KernelErrorCode.INVALID_INPUT,
                "chain must be a lowercase slug (e.g. 'solana', 'sui')",
            )
        if not isinstance(self.direction, QuoteDirection):
            raise KernelContractError(
                KernelErrorCode.INVALID_INPUT,
                "direction must be a QuoteDirection",
            )
        input_repr = _require_text(
            self.input_representation_id, "input_representation_id"
        )
        output_repr = _require_text(
            self.output_representation_id, "output_representation_id"
        )
        if input_repr == output_repr:
            raise KernelContractError(
                KernelErrorCode.INVALID_INPUT,
                "input and output representation ids must differ",
            )
        _exact_positive_int(self.input_amount_raw, "input_amount_raw")
        _exact_positive_int(self.output_amount_raw, "output_amount_raw")
        _exact_positive_int(self.input_amount_normalized, "input_amount_normalized")
        _exact_positive_int(self.output_amount_normalized, "output_amount_normalized")
        if self.minimum_output_raw is not None:
            minimum = _exact_positive_int(self.minimum_output_raw, "minimum_output_raw")
            if minimum > self.output_amount_raw:
                raise KernelContractError(
                    KernelErrorCode.INVALID_INPUT,
                    "minimum_output_raw cannot exceed output_amount_raw",
                )
        if not isinstance(self.correlation, ProviderCorrelation):
            raise KernelContractError(
                KernelErrorCode.INVALID_INPUT,
                "correlation must be a ProviderCorrelation",
            )
        if not isinstance(self.freshness, QuoteFreshness):
            raise KernelContractError(
                KernelErrorCode.INVALID_INPUT, "freshness must be a QuoteFreshness"
            )
        _optional_exact_int(
            self.compute_unit_estimate, "compute_unit_estimate", positive=True
        )
        venues = tuple(self.route_venues)
        if len(venues) > MAX_ROUTE_VENUES:
            raise KernelContractError(
                KernelErrorCode.INVALID_INPUT,
                f"more than {MAX_ROUTE_VENUES} route venues",
            )
        for venue in venues:
            if not isinstance(venue, RouteVenue):
                raise KernelContractError(
                    KernelErrorCode.INVALID_INPUT,
                    "route_venues entries must be RouteVenue",
                )
        object.__setattr__(self, "route_venues", venues)
        fees = tuple(self.fees)
        for fee in fees:
            if not isinstance(fee, QuoteFeeComponent):
                raise KernelContractError(
                    KernelErrorCode.INVALID_INPUT,
                    "fees entries must be QuoteFeeComponent",
                )
        object.__setattr__(self, "fees", fees)
        _optional_text(self.taker, "taker", max_len=128)
        if not _SHA256_RE.fullmatch(self.raw_response_hash):
            raise KernelContractError(
                KernelErrorCode.INVALID_INPUT,
                "raw_response_hash must be a lowercase sha256 hex digest",
            )
        _require_text(self.request_fingerprint, "request_fingerprint", max_len=128)
        if self.execution_authority is not False:
            raise KernelContractError(
                KernelErrorCode.EXECUTION_AUTHORITY_FORBIDDEN,
                "kernel quotes are discovery evidence only; execution authority "
                "is owned elsewhere (R-02/R-05)",
            )

    @property
    def bound_amount_raw(self) -> int:
        """The exact amount this quote is bound to (input for ExactIn)."""
        if self.direction is QuoteDirection.EXACT_IN:
            return self.input_amount_raw
        return self.output_amount_raw

    @property
    def quote_sort_key(self) -> tuple[int, str, str]:
        """Deterministic ranking key: best output first, then stable ids."""
        return (
            -self.output_amount_raw,
            self.provider_id,
            self.raw_response_hash,
        )


# --------------------------------------------------------------------------
# Failures (losing reads are preserved as typed negatives)
# --------------------------------------------------------------------------


class ProviderReadFailureClass(StrEnum):
    """Typed failure classes; maps routing ``ProviderFailureReason`` values
    plus the governed negative-receipt quality states."""

    RATE_LIMITED = "rate_limited"
    UNAUTHORIZED = "unauthorized"
    HTTP_ERROR = "http_error"
    INVALID_SCHEMA = "invalid_schema"
    CANCELLED = "cancelled"
    TRANSPORT = "transport"
    QUOTA_OR_TRANSPORT = "quota_or_transport_error"
    MISSING_CREDENTIAL = "missing_credential_binding"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class ProviderReadFailure:
    """One provider read that produced NO quote; preserved as evidence."""

    provider_id: str
    failure_class: ProviderReadFailureClass
    detail: str
    raw_evidence_ref: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.provider_id, "failure provider_id", max_len=128)
        if not isinstance(self.failure_class, ProviderReadFailureClass):
            raise KernelContractError(
                KernelErrorCode.INVALID_INPUT,
                "failure_class must be a ProviderReadFailureClass",
            )
        _require_text(self.detail, "failure detail")
        _optional_text(self.raw_evidence_ref, "failure raw_evidence_ref")


# --------------------------------------------------------------------------
# PoolIdentityDeduplicator (R13_GAP_NO_POOL_DEDUP, explicit typed rule set)
# --------------------------------------------------------------------------


class IndependenceVerdict(StrEnum):
    """Pairwise liquidity-independence verdict.

    ``UNKNOWN`` is deliberately distinct from ``INDEPENDENT``: missing pool
    evidence is unknown, and unknown is never treated as independent.
    """

    INDEPENDENT = "independent"
    CORRELATED = "correlated"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class QuoteCorrelationCluster:
    """One transitive correlation cluster of quotes (deterministic order)."""

    members: tuple[NormalizedProviderQuote, ...]

    @property
    def key(self) -> tuple[str, ...]:
        return tuple(
            f"{member.provider_id}:{member.raw_response_hash}"
            for member in self.members
        )


@dataclass(frozen=True, slots=True)
class PoolIdentityDeduplicator:
    """Explicit typed rule set for pool-identity dedup.

    Frozen rule: two quotes are CORRELATED observations of the same underlying
    liquidity — never two independent sources — when ANY of the following
    holds:

    1. they declare the SAME operator ``correlation_group``;
    2. their ``aggregator_lineage`` sets intersect (e.g. an OpenOcean composite
       over Jupiter vs a direct Jupiter quote);
    3. their exact underlying ``pool_ids`` intersect (same kind + canonical
       identity, e.g. a shared Jupiter ``ammKey``).

    They are INDEPENDENT only with positive evidence on both sides: disjoint
    non-empty pool-id sets, disjoint lineage, and different groups. Anything
    less (missing pool evidence on either side) is ``UNKNOWN`` — unknown is
    never independent. Venue-level labels/program ids never establish
    correlation nor independence.

    All outputs are deterministically ordered; identical inputs in any
    construction order produce identical cluster output.
    """

    rule_version: str = QUOTE_BUILD_KERNEL_VERSION

    @staticmethod
    def shared_pool_ids(
        a: NormalizedProviderQuote, b: NormalizedProviderQuote
    ) -> tuple[PoolIdentity, ...]:
        keys = {pool.key for pool in a.correlation.pool_ids}
        shared = sorted(
            (pool for pool in b.correlation.pool_ids if pool.key in keys),
            key=lambda pool: pool.key,
        )
        return tuple(shared)

    @staticmethod
    def shared_lineage(
        a: NormalizedProviderQuote, b: NormalizedProviderQuote
    ) -> tuple[str, ...]:
        return tuple(
            sorted(
                set(a.correlation.aggregator_lineage)
                & set(b.correlation.aggregator_lineage)
            )
        )

    @staticmethod
    def correlation_verdict(
        a: NormalizedProviderQuote, b: NormalizedProviderQuote
    ) -> IndependenceVerdict:
        """Typed pairwise verdict for two quotes."""
        if a.correlation.correlation_group == b.correlation.correlation_group:
            return IndependenceVerdict.CORRELATED
        if PoolIdentityDeduplicator.shared_lineage(a, b):
            return IndependenceVerdict.CORRELATED
        if PoolIdentityDeduplicator.shared_pool_ids(a, b):
            return IndependenceVerdict.CORRELATED
        if a.correlation.pool_ids and b.correlation.pool_ids:
            return IndependenceVerdict.INDEPENDENT
        return IndependenceVerdict.UNKNOWN

    @staticmethod
    def _correlation_keys(quote: NormalizedProviderQuote) -> set[tuple[str, ...]]:
        keys: set[tuple[str, ...]] = {("group", quote.correlation.correlation_group)}
        keys.update(
            ("lineage", member) for member in quote.correlation.aggregator_lineage
        )
        keys.update(
            ("pool", kind, identity)
            for kind, identity in (pool.key for pool in quote.correlation.pool_ids)
        )
        return keys

    @classmethod
    def group_quotes(
        cls, quotes: Sequence[NormalizedProviderQuote]
    ) -> tuple[QuoteCorrelationCluster, ...]:
        """Transitive group-by over shared identity keys (deterministic).

        Quotes are clustered by union-find over group/lineage/pool identity
        keys; clusters and members are emitted in deterministic order.
        """
        ordered = sorted(quotes, key=lambda quote: quote.quote_sort_key)
        parent = list(range(len(ordered)))

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left: int, right: int) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parent[max(left_root, right_root)] = min(left_root, right_root)

        first_by_key: dict[tuple[str, ...], int] = {}
        for index, quote in enumerate(ordered):
            for key in cls._correlation_keys(quote):
                prior = first_by_key.setdefault(key, index)
                if prior != index:
                    union(prior, index)

        clusters: dict[int, list[NormalizedProviderQuote]] = {}
        for index, quote in enumerate(ordered):
            clusters.setdefault(find(index), []).append(quote)
        grouped = tuple(
            QuoteCorrelationCluster(members=tuple(members))
            for members in clusters.values()
        )
        return tuple(sorted(grouped, key=lambda cluster: cluster.key))

    @classmethod
    def independence_set(
        cls, quotes: Sequence[NormalizedProviderQuote]
    ) -> tuple[NormalizedProviderQuote, ...]:
        """Deterministic maximal mutually-independent representative set.

        Quotes are considered best-first by :meth:`NormalizedProviderQuote.
        quote_sort_key`; a quote joins only if it is pairwise INDEPENDENT with
        every already-selected member. UNKNOWN never joins (unknown is never
        independent).
        """
        chosen: list[NormalizedProviderQuote] = []
        for quote in sorted(quotes, key=lambda item: item.quote_sort_key):
            if all(
                cls.correlation_verdict(quote, member)
                is IndependenceVerdict.INDEPENDENT
                for member in chosen
            ):
                chosen.append(quote)
        return tuple(chosen)


# --------------------------------------------------------------------------
# QuoteRaceResult (all providers preserved, losers ranked with typed reasons)
# --------------------------------------------------------------------------


class RaceVerdict(StrEnum):
    WON = "won"
    LOST = "lost"


class QuoteLossReason(StrEnum):
    """Typed loss reasons; maps routing ``NonSelectionReason`` semantics."""

    INFERIOR_OUTPUT = "inferior_output"
    CORRELATED_OBSERVATION = "correlated_observation"
    STALE = "stale"
    MINIMUM_OUTPUT_UNPROVEN = "minimum_output_unproven"
    DETERMINISTIC_TIEBREAK = "deterministic_tiebreak"


@dataclass(frozen=True, slots=True)
class RankedQuoteEntry:
    """One raced quote: rank, verdict and typed loss reasons (losers kept)."""

    quote: NormalizedProviderQuote
    rank: int
    verdict: RaceVerdict
    loss_reasons: tuple[QuoteLossReason, ...] = ()

    def __post_init__(self) -> None:
        _exact_non_negative_int(self.rank, "rank")
        if self.verdict is RaceVerdict.WON and self.loss_reasons:
            raise KernelContractError(
                KernelErrorCode.RACE_INPUT_INVALID,
                "the winner must not carry loss reasons",
            )
        if self.verdict is RaceVerdict.LOST and not self.loss_reasons:
            raise KernelContractError(
                KernelErrorCode.RACE_INPUT_INVALID,
                "every loser must carry at least one typed loss reason",
            )
        reasons = tuple(self.loss_reasons)
        if len(reasons) != len(set(reasons)):
            raise KernelContractError(
                KernelErrorCode.RACE_INPUT_INVALID,
                "loss reasons must be unique",
            )
        object.__setattr__(self, "loss_reasons", reasons)


@dataclass(frozen=True, slots=True)
class QuoteRaceRequest:
    """Canonical comparability identity every raced quote must match exactly.

    Hard argument bounds mirror the governed plane: ``max_age_ns`` must stay
    within ``(0, 45_000_000_000]`` and ``max_slot_gap`` within ``[0, 32]``;
    wider bounds are refused, never accepted.
    """

    chain: str
    input_representation_id: str
    output_representation_id: str
    direction: QuoteDirection
    amount_raw: int
    taker: str | None = None
    max_age_ns: int = MAX_AGE_NS
    max_slot_gap: int = MAX_SLOT_GAP

    def __post_init__(self) -> None:
        chain = _require_text(self.chain, "race request chain", max_len=64)
        if not _CHAIN_RE.fullmatch(chain):
            raise KernelContractError(
                KernelErrorCode.INVALID_INPUT, "chain must be a lowercase slug"
            )
        input_repr = _require_text(
            self.input_representation_id, "race input_representation_id"
        )
        output_repr = _require_text(
            self.output_representation_id, "race output_representation_id"
        )
        if input_repr == output_repr:
            raise KernelContractError(
                KernelErrorCode.INVALID_INPUT,
                "race representation ids must differ",
            )
        if not isinstance(self.direction, QuoteDirection):
            raise KernelContractError(
                KernelErrorCode.INVALID_INPUT, "direction must be a QuoteDirection"
            )
        _exact_positive_int(self.amount_raw, "race amount_raw")
        _optional_text(self.taker, "race taker", max_len=128)
        if not 0 < self.max_age_ns <= MAX_AGE_NS:
            raise KernelContractError(
                KernelErrorCode.INVALID_INPUT,
                f"max_age_ns must be within (0, {MAX_AGE_NS}]",
            )
        if not 0 <= self.max_slot_gap <= MAX_SLOT_GAP:
            raise KernelContractError(
                KernelErrorCode.INVALID_INPUT,
                f"max_slot_gap must be within [0, {MAX_SLOT_GAP}]",
            )


@dataclass(frozen=True, slots=True)
class QuoteRaceResult:
    """Ranked race outcome preserving ALL provider observations.

    Entries are in deterministic rank order (fresh quotes by output desc, then
    provider id, then response hash; stale quotes preserved after fresh ones
    in the same order). ``winner`` is rank 0 among fresh quotes or ``None``
    when no fresh quote exists; failures are preserved alongside.
    """

    request: QuoteRaceRequest
    entries: tuple[RankedQuoteEntry, ...]
    failures: tuple[ProviderReadFailure, ...]
    built_at_ns: int

    @property
    def winner(self) -> NormalizedProviderQuote | None:
        if not self.entries or self.entries[0].verdict is not RaceVerdict.WON:
            return None
        return self.entries[0].quote

    def require_winner(self) -> NormalizedProviderQuote:
        winner = self.winner
        if winner is None:
            raise QuoteRaceStateError(
                KernelErrorCode.RACE_NO_WINNER,
                "race has no fresh winning quote; losers and failures are "
                "preserved as evidence",
            )
        return winner

    @property
    def race_fingerprint(self) -> str:
        payload = {
            "kernel_version": QUOTE_BUILD_KERNEL_VERSION,
            "request": self.request,
            "entries": [
                {
                    "quote": entry.quote,
                    "rank": entry.rank,
                    "verdict": entry.verdict,
                    "loss_reasons": entry.loss_reasons,
                }
                for entry in self.entries
            ],
            "failures": self.failures,
            "built_at_ns": self.built_at_ns,
        }
        return canonical_hash(payload)

    @classmethod
    def build(
        cls,
        *,
        request: QuoteRaceRequest,
        quotes: Sequence[NormalizedProviderQuote],
        failures: Sequence[ProviderReadFailure] = (),
        now_ns: int,
    ) -> "QuoteRaceResult":
        """Deterministically rank a race; refuse non-comparable inputs."""
        _exact_non_negative_int(now_ns, "now_ns")
        quote_list = list(quotes)
        failure_list = list(failures)
        if len(quote_list) > MAX_PROVIDERS:
            raise QuoteRaceStateError(
                KernelErrorCode.RACE_INPUT_INVALID,
                f"more than {MAX_PROVIDERS} quotes in one race",
            )
        quote_providers = [quote.provider_id for quote in quote_list]
        if len(set(quote_providers)) != len(quote_providers):
            raise QuoteRaceStateError(
                KernelErrorCode.RACE_INPUT_INVALID,
                "each provider may contribute at most one quote per race",
            )
        failure_providers = [failure.provider_id for failure in failure_list]
        if len(set(failure_providers)) != len(failure_providers):
            raise QuoteRaceStateError(
                KernelErrorCode.RACE_INPUT_INVALID,
                "each provider may contribute at most one failure per race",
            )
        overlap = set(quote_providers) & set(failure_providers)
        if overlap:
            raise QuoteRaceStateError(
                KernelErrorCode.RACE_INPUT_INVALID,
                f"a provider cannot both quote and fail: {sorted(overlap)}",
            )
        for quote in quote_list:
            cls._check_comparability(request, quote, now_ns)

        stale_flags = cls._stale_flags(request, quote_list, now_ns)
        eligible = [quote for quote in quote_list if not stale_flags[id(quote)]]
        ranked = sorted(eligible, key=lambda quote: quote.quote_sort_key)
        stale_ranked = sorted(
            (quote for quote in quote_list if stale_flags[id(quote)]),
            key=lambda quote: quote.quote_sort_key,
        )
        ordered = ranked + stale_ranked

        entries: list[RankedQuoteEntry] = []
        winner_quote = ranked[0] if ranked else None
        for rank, quote in enumerate(ordered):
            if quote is winner_quote:
                entries.append(
                    RankedQuoteEntry(quote=quote, rank=rank, verdict=RaceVerdict.WON)
                )
                continue
            reasons: list[QuoteLossReason] = []
            if stale_flags[id(quote)]:
                reasons.append(QuoteLossReason.STALE)
            if winner_quote is not None:
                if quote.output_amount_raw < winner_quote.output_amount_raw:
                    reasons.append(QuoteLossReason.INFERIOR_OUTPUT)
                elif (
                    not stale_flags[id(quote)]
                    and quote.output_amount_raw == winner_quote.output_amount_raw
                ):
                    reasons.append(QuoteLossReason.DETERMINISTIC_TIEBREAK)
                higher = [entry.quote for entry in entries]
                if any(
                    PoolIdentityDeduplicator.correlation_verdict(quote, prior)
                    is IndependenceVerdict.CORRELATED
                    for prior in higher
                ):
                    reasons.append(QuoteLossReason.CORRELATED_OBSERVATION)
            if quote.minimum_output_raw is None:
                reasons.append(QuoteLossReason.MINIMUM_OUTPUT_UNPROVEN)
            entries.append(
                RankedQuoteEntry(
                    quote=quote,
                    rank=rank,
                    verdict=RaceVerdict.LOST,
                    loss_reasons=tuple(reasons),
                )
            )
        sorted_failures = tuple(
            sorted(
                failure_list,
                key=lambda failure: (
                    failure.provider_id,
                    failure.failure_class.value,
                    failure.detail,
                ),
            )
        )
        return cls(
            request=request,
            entries=tuple(entries),
            failures=sorted_failures,
            built_at_ns=now_ns,
        )

    @staticmethod
    def _check_comparability(
        request: QuoteRaceRequest, quote: NormalizedProviderQuote, now_ns: int
    ) -> None:
        if quote.chain != request.chain:
            raise QuoteComparabilityError(
                KernelErrorCode.COMPARABILITY_MISMATCH,
                f"quote chain {quote.chain!r} != request chain {request.chain!r}",
            )
        if (
            quote.input_representation_id,
            quote.output_representation_id,
        ) != (request.input_representation_id, request.output_representation_id):
            raise QuoteComparabilityError(
                KernelErrorCode.COMPARABILITY_MISMATCH,
                "quote representation pair does not match the race request "
                "(governed QUOTE_UNITS_OR_REPRESENTATION_MISMATCH analog)",
            )
        if quote.direction is not request.direction:
            raise QuoteComparabilityError(
                KernelErrorCode.COMPARABILITY_MISMATCH,
                "quote direction does not match the race request",
            )
        if quote.bound_amount_raw != request.amount_raw:
            raise QuoteComparabilityError(
                KernelErrorCode.COMPARABILITY_MISMATCH,
                f"quote bound amount {quote.bound_amount_raw} != race amount "
                f"{request.amount_raw}; quotes must bind the exact amount "
                "(no scaling)",
            )
        if quote.taker != request.taker:
            raise QuoteComparabilityError(
                KernelErrorCode.COMPARABILITY_MISMATCH,
                "taker parity mismatch (governed QUOTE_TAKER_PARITY_MISMATCH "
                "analog)",
            )
        if quote.freshness.received_at_ns > now_ns:
            raise QuoteComparabilityError(
                KernelErrorCode.FUTURE_OBSERVATION,
                "quote observed in the future; evidence timestamps are never "
                "synthesized",
            )

    @staticmethod
    def _stale_flags(
        request: QuoteRaceRequest,
        quotes: Sequence[NormalizedProviderQuote],
        now_ns: int,
    ) -> dict[int, bool]:
        flags: dict[int, bool] = {}
        supplied_slots = [
            quote.freshness.slot for quote in quotes if quote.freshness.slot is not None
        ]
        max_slot = max(supplied_slots) if supplied_slots else None
        for quote in quotes:
            stale = now_ns - quote.freshness.received_at_ns > request.max_age_ns
            if (
                not stale
                and max_slot is not None
                and quote.freshness.slot is not None
                and max_slot - quote.freshness.slot > request.max_slot_gap
            ):
                stale = True
            flags[id(quote)] = stale
        return flags


# --------------------------------------------------------------------------
# Build handoff (typed reference seam; no construction logic)
# --------------------------------------------------------------------------


#: The R-03 ``UnsignedBorrowPlan`` family referenced by :class:`BuildHandoff`.
#: Types are IMPORTED from the frozen R-03 contract; the kernel duplicates none.
R03UnsignedPlan = Union[
    UnsignedBorrowPlan,
    UnsignedRepayPlan,
    PtBuildResult,
    FinalizedUnsignedSolanaPlan,
]


def _plan_build_status(plan: R03UnsignedPlan) -> BuildStatus:
    if isinstance(plan, FinalizedUnsignedSolanaPlan):
        return plan.borrow_plan.build_status
    return plan.build_status


def _plan_chain(plan: R03UnsignedPlan) -> str | None:
    if isinstance(plan, (UnsignedBorrowPlan, UnsignedRepayPlan)):
        return plan.chain
    if isinstance(plan, FinalizedUnsignedSolanaPlan):
        return plan.borrow_plan.chain
    return None


@dataclass(frozen=True, slots=True)
class BuildHandoff:
    """Explicit seam from a won quote to an EXISTING R-03 unsigned build.

    Typed reference only: the kernel never constructs instructions, PTBs or
    plans — construction stays owned by the R-03 builders. Integrity is
    fail-closed at construction:

    - ``won_quote`` must be the race winner (identity-checked);
    - ``plan.provider`` must equal ``builder_provider``;
    - ``builder_build_status`` (an imported R-03 :class:`BuildStatus`) must
      equal the plan's actual status — a handoff cannot fake a build;
    - the plan's chain must equal the won quote's chain whenever the plan
      carries one.
    """

    race_result: QuoteRaceResult
    won_quote: NormalizedProviderQuote
    builder_provider: str
    builder_build_status: BuildStatus
    plan: R03UnsignedPlan

    def __post_init__(self) -> None:
        _require_text(self.builder_provider, "builder_provider", max_len=128)
        if not isinstance(self.builder_build_status, BuildStatus):
            raise BuildHandoffError(
                KernelErrorCode.HANDOFF_INTEGRITY,
                "builder_build_status must be an imported R-03 BuildStatus",
            )
        winner = self.race_result.winner
        if winner is None:
            raise BuildHandoffError(
                KernelErrorCode.HANDOFF_NOT_WINNER,
                "handoff requires a race with a fresh winning quote",
            )
        if (
            self.won_quote.provider_id,
            self.won_quote.raw_response_hash,
            self.won_quote.output_amount_raw,
        ) != (
            winner.provider_id,
            winner.raw_response_hash,
            winner.output_amount_raw,
        ):
            raise BuildHandoffError(
                KernelErrorCode.HANDOFF_NOT_WINNER,
                "won_quote is not the race winner; only the winner hands off",
            )
        if self.plan.provider != self.builder_provider:
            raise BuildHandoffError(
                KernelErrorCode.HANDOFF_INTEGRITY,
                f"plan provider {self.plan.provider!r} != builder_provider "
                f"{self.builder_provider!r}",
            )
        actual_status = _plan_build_status(self.plan)
        if actual_status is not self.builder_build_status:
            raise BuildHandoffError(
                KernelErrorCode.HANDOFF_INTEGRITY,
                f"builder_build_status {self.builder_build_status.value} does "
                f"not match the plan's actual status "
                f"{actual_status.value} (no fake PASS)",
            )
        plan_chain = _plan_chain(self.plan)
        if plan_chain is not None and plan_chain != self.won_quote.chain:
            raise BuildHandoffError(
                KernelErrorCode.HANDOFF_INTEGRITY,
                f"plan chain {plan_chain!r} != won quote chain "
                f"{self.won_quote.chain!r}",
            )

    @property
    def handoff_fingerprint(self) -> str:
        return canonical_hash(
            {
                "kernel_version": QUOTE_BUILD_KERNEL_VERSION,
                "race_fingerprint": self.race_result.race_fingerprint,
                "won_quote": self.won_quote,
                "builder_provider": self.builder_provider,
                "builder_build_status": self.builder_build_status,
                "plan": self.plan,
            }
        )

    def require_sizing_amount(self, proposed_amount_raw: int, *, purpose: str) -> int:
        """No-extrapolation guard bound to this handoff's won quote."""
        return refuse_amount_extrapolation(
            self.won_quote, proposed_amount_raw, purpose=purpose
        )


def refuse_amount_extrapolation(
    quote: NormalizedProviderQuote,
    proposed_amount_raw: int,
    *,
    purpose: str,
) -> int:
    """Typed no-extrapolation invariant: every sizing point requires a re-quote.

    Returns the quote's exact bound amount ONLY when ``proposed_amount_raw``
    equals it. ANY other amount is refused with :class:`QuoteExtrapolationError`
    — including amount-neighborhood perturbations (+/-1 raw unit, ±0.1%
    rescales, 'close enough' sizes): a quote is evidence for exactly one
    amount, never an interpolation seed.
    """
    _require_text(purpose, "purpose", max_len=128)
    if type(proposed_amount_raw) is not int or proposed_amount_raw <= 0:
        raise QuoteExtrapolationError(
            KernelErrorCode.EXTRAPOLATION_REFUSED,
            f"proposed sizing amount for {purpose!r} must be an exact positive "
            "integer",
        )
    bound = quote.bound_amount_raw
    if proposed_amount_raw == bound:
        return bound
    raise QuoteExtrapolationError(
        KernelErrorCode.EXTRAPOLATION_REFUSED,
        f"refusing amount-neighborhood extrapolation for {purpose!r}: quote "
        f"{quote.provider_id}/{quote.raw_response_hash[:12]} is bound to "
        f"{bound} raw units, proposed {proposed_amount_raw}; every sizing "
        "point requires a fresh quote at the exact amount",
    )
