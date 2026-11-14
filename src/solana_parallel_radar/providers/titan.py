"""R13-A1 Titan quote adapter — offline, fail-closed, sender-free.

Closes the R13 audit row "Titan: adapter NONE"
(``R13_GAP_NO_ADAPTER`` for Titan) by producing kernel
:class:`~src.execution.quote_build_kernel.NormalizedProviderQuote` instances
from Titan quote responses WITHOUT ever redefining kernel types, without any
network call, and without touching the P0-2 quote owners
(``probes.py``/``funnel.py`` wiring is DEFERRED to a follow-up lane).

Pinned source of truth (see
``docs/integrations/offline/titan-adapter-2026-11-14/``):

- Wave-1 dossier: ``docs/integrations/offline/providers-wave1-2026-11-13/TITAN_SOLANA.md``
  (portal REST endpoint/auth, fee asymmetry, build-output semantics).
- Additive schema pin (this lane): exact ``SwapQuotes``/``SwapRoute``/
  ``RoutePlanStep``/``PlatformFee``/``Instruction``/``AccountMeta`` wire shapes
  transcribed from the official Titan developer docs
  (titan-exchange.gitbook.io ``swap-api/reference/direct/new-swap-quote-stream.md``
  and ``swap-api/reference/types.md``, retrieved 2026-11-14).

Fail-closed stance:

1. DISABLED by default: this module ships NO transport. The transport is an
   injectable callable; ``normalize_via_transport(None, ...)`` refuses with a
   typed ``DISABLED`` error. The live-capture verdict is always
   ``BLOCKED / TITAN_LIVE_CAPTURE_NOT_AUTHORIZED`` — no environment variable,
   credential or fixture can flip it (mirrors ``src/gpr_sui_shadow/providers.py``).
2. UNKNOWN is never zero: missing ``contextSlot``/``expiresAtMs``/fee amounts
   stay ``None``; ``minimum_output_raw`` is ``None`` (Titan exposes no
   minimum-output field on this surface) — never coerced to a fake threshold.
3. Never guess shapes: fields whose wire encoding is NOT pinned (portal JSON
   u64-as-string encodings, non-integer instruction ``d`` bytes, raw
   ``transaction`` byte encodings other than opaque strings) are refused with
   the typed ``SCHEMA_MISSING_PIN`` failure, never interpreted.
4. Evidence states: every normalized quote is
   ``ADAPTER_BUILT_OFFLINE_UNQUALIFIED`` discovery evidence with literal
   ``execution_authority=False`` (kernel-inherited invariant).
5. Correlation: ALL entries of one Titan response are one operator
   observation (group ``titan-argos-router``). Per ``PROVIDER_OVERLAP_NOTES.md``
   Titan's quote map carries ``Metis``/``Okx`` entries: each entry's
   aggregator lineage is ``("titan", <entry-name-lowercase>)`` so a Titan
   ``Okx`` entry deduplicates against an OKX DEX capture via lineage
   intersection, and OpenOcean composites (documented over Jupiter+Titan)
   correlate via the shared ``titan`` lineage member. Pool identities come
   ONLY from ``steps[].ammKey`` when the response supplies them.
6. Build-output classification (pinned dossier: Titan returns an unsigned
   INSTRUCTION BUNDLE + ALTs, not a serialized transaction, on this surface):
   ``INSTRUCTION_BUNDLE`` (non-empty ``instructions``), ``UNSIGNED_TRANSACTION``
   (opaque ``transaction`` present; bytes are evidence-only, never decoded,
   compiled, signed or sent), or ``QUOTE_ONLY`` (no build output at all).
   ``instructions`` and ``transaction`` together are schema drift (official
   contract: instructions are not provided when a transaction is provided).

No signing, no sending, no fee-account/ATA setup, no provider enablement,
no boot-path wiring. Fixtures under ``tests/fixtures/r13_titan_adapter/`` are
offline deterministic captures built ONLY from the pinned schema.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
import hashlib
import json
import re

from src.execution.quote_build_kernel import (
    FeeInclusionState,
    NormalizedProviderQuote,
    PoolIdentity,
    PoolIdentityKind,
    ProviderCorrelation,
    ProviderReadFailure,
    ProviderReadFailureClass,
    QuoteDirection,
    QuoteFeeComponent,
    QuoteFreshness,
    QuoteRaceRequest,
    RouteVenue,
)

__all__ = [
    "MAX_BATCH_ENTRIES",
    "MAX_STEPS",
    "TITAN_ADAPTER_VERSION",
    "TITAN_CHAIN",
    "TITAN_CORRELATION_GROUP",
    "TITAN_EVIDENCE_STATE",
    "TITAN_LIVE_CAPTURE_BLOCKED",
    "TITAN_PORTAL_QUOTE_URL",
    "TITAN_PROVIDER_GENERATION",
    "TitanAdapterError",
    "TitanBuildOutputClass",
    "TitanFailureCode",
    "TitanLiveCaptureVerdict",
    "TitanQuoteBatch",
    "TitanQuoteEntry",
    "TitanQuoteFailure",
    "TitanSwapQuoteRequest",
    "TitanTransport",
    "build_kernel_race_request",
    "kernel_race_inputs",
    "map_http_status_failure",
    "normalize_titan_quote_response",
    "normalize_via_transport",
    "titan_live_capture_verdict",
]

# --------------------------------------------------------------------------
# Pinned identity constants (all values trace to the pinned dossiers)
# --------------------------------------------------------------------------

TITAN_ADAPTER_VERSION = "r13.titan-adapter.v1"
#: Typed evidence state of every quote this adapter produces (offline,
#: unqualified; qualification requires user-gated live capture out of scope).
TITAN_EVIDENCE_STATE = "ADAPTER_BUILT_OFFLINE_UNQUALIFIED"
#: Typed live-capture gate reason; mirrors LIVE_SUI_PROVIDERS_NOT_AUTHORIZED.
TITAN_LIVE_CAPTURE_BLOCKED = "TITAN_LIVE_CAPTURE_NOT_AUTHORIZED"
#: One operator correlation group for the whole Titan response: every entry of
#: one capture is Argos' view, never independent liquidity (overlap notes).
TITAN_CORRELATION_GROUP = "titan-argos-router"
TITAN_CHAIN = "solana"
TITAN_PROVIDER_GENERATION = "titan.swap-quote-api.wave1-2026-11-14"
#: Pinned portal endpoint (evidence string only — this module never fetches).
TITAN_PORTAL_QUOTE_URL = "https://portal.api.titan.exchange/api/v1/quote/swap"

MAX_BATCH_ENTRIES = 64
MAX_STEPS = 32  # kernel MAX_ROUTE_VENUES bound; wider routes are refused
MAX_FEE_BPS = 10_000  # documented Titan fee limit ("does not depend on tier")
MAX_SLIPPAGE_BPS = 10_000
_U64_MAX = 2**64 - 1
_U32_MAX = 2**32 - 1
#: parts-per-billion -> basis points conversion denominator; non-exact
#: conversions stay UNKNOWN (share_bps=None) instead of rounding.
_PPB_PER_BPS = 100_000

_BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

_EXACT_IN_WIRE = "ExactIn"
_EXACT_OUT_WIRE = "ExactOut"


# --------------------------------------------------------------------------
# Typed failures and errors
# --------------------------------------------------------------------------


class TitanFailureCode(StrEnum):
    """Typed adapter failure codes (kernel-mapped, never collapsed)."""

    REQUEST_INVALID = "request_invalid"
    DISABLED = "disabled"
    MISSING_CREDENTIAL = "missing_credential"
    RATE_LIMITED = "rate_limited"
    UNAUTHORIZED = "unauthorized"
    HTTP_ERROR = "http_error"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    INVALID_SCHEMA = "invalid_schema"
    SCHEMA_MISSING_PIN = "schema_missing_pin"
    EMPTY_QUOTES = "empty_quotes"
    COMPARABILITY_DRIFT = "comparability_drift"


class TitanBuildOutputClass(StrEnum):
    """Pinned build-output classification for one Titan ``SwapRoute``."""

    QUOTE_ONLY = "quote_only"
    INSTRUCTION_BUNDLE = "instruction_bundle"
    UNSIGNED_TRANSACTION = "unsigned_transaction"


class TitanAdapterError(Exception):
    """Typed fail-closed adapter error (request-side and disabled stance)."""

    def __init__(self, code: TitanFailureCode, detail: str) -> None:
        super().__init__(f"{code.value}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class TitanQuoteFailure:
    """One failed Titan read or drifted entry; preserved as evidence."""

    provider_entry: str
    code: TitanFailureCode
    detail: str
    kernel_failure_class: ProviderReadFailureClass
    raw_evidence_ref: str | None = None

    def to_kernel_failure(self) -> ProviderReadFailure:
        """Kernel-mapped typed negative for the quote race."""
        return ProviderReadFailure(
            provider_id=self.provider_entry,
            failure_class=self.kernel_failure_class,
            detail=f"{self.code.value}: {self.detail}",
            raw_evidence_ref=self.raw_evidence_ref,
        )


def _kernel_failure_class(code: TitanFailureCode) -> ProviderReadFailureClass:
    """Frozen mapping TitanFailureCode -> kernel ProviderReadFailureClass.

    Documented judgment calls: ``EMPTY_QUOTES`` is a valid HTTP-level
    business rejection (documented "no quotes returned" cases), mapped to
    ``HTTP_ERROR`` with the typed detail preserved; ``SCHEMA_MISSING_PIN``
    and ``COMPARABILITY_DRIFT`` are refusal classes mapped to
    ``INVALID_SCHEMA`` (the kernel has no wider refusal bucket; the typed
    TitanFailureCode is always carried in the detail).
    """
    mapping: dict[TitanFailureCode, ProviderReadFailureClass] = {
        TitanFailureCode.REQUEST_INVALID: ProviderReadFailureClass.DISABLED,
        TitanFailureCode.DISABLED: ProviderReadFailureClass.DISABLED,
        TitanFailureCode.MISSING_CREDENTIAL: ProviderReadFailureClass.MISSING_CREDENTIAL,
        TitanFailureCode.RATE_LIMITED: ProviderReadFailureClass.RATE_LIMITED,
        TitanFailureCode.UNAUTHORIZED: ProviderReadFailureClass.UNAUTHORIZED,
        TitanFailureCode.HTTP_ERROR: ProviderReadFailureClass.HTTP_ERROR,
        TitanFailureCode.TIMEOUT: ProviderReadFailureClass.TRANSPORT,
        TitanFailureCode.TRANSPORT: ProviderReadFailureClass.TRANSPORT,
        TitanFailureCode.INVALID_SCHEMA: ProviderReadFailureClass.INVALID_SCHEMA,
        TitanFailureCode.SCHEMA_MISSING_PIN: ProviderReadFailureClass.INVALID_SCHEMA,
        TitanFailureCode.EMPTY_QUOTES: ProviderReadFailureClass.HTTP_ERROR,
        TitanFailureCode.COMPARABILITY_DRIFT: ProviderReadFailureClass.INVALID_SCHEMA,
    }
    return mapping[code]


# --------------------------------------------------------------------------
# Typed request construction (portal REST, pinned query-param schema)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TitanSwapQuoteRequest:
    """Typed Titan portal quote request (GET /api/v1/quote/swap).

    Only portal-documented parameters are emitted
    (``inputMint``/``outputMint``/``amount``/``userPublicKey``/``slippageBps``
    plus the fee triple). The ``swapMode`` parameter is NOT pinned for the
    portal surface: requesting ``ExactOut`` there is refused with
    ``SCHEMA_MISSING_PIN`` instead of guessing the parameter name.
    """

    input_mint: str
    output_mint: str
    amount_raw: int
    user_public_key: str
    input_representation_id: str
    output_representation_id: str
    slippage_bps: int | None = None
    swap_direction: QuoteDirection = QuoteDirection.EXACT_IN
    fee_account: str | None = None
    fee_bps: int | None = None
    fee_from_input_mint: bool | None = None

    def __post_init__(self) -> None:
        if not _is_base58(self.input_mint) or not _is_base58(self.output_mint):
            raise TitanAdapterError(
                TitanFailureCode.REQUEST_INVALID,
                "input/output mints must be base58 Solana public keys",
            )
        if self.input_mint == self.output_mint:
            raise TitanAdapterError(
                TitanFailureCode.REQUEST_INVALID, "input and output mints must differ"
            )
        if type(self.amount_raw) is not int or self.amount_raw <= 0:
            raise TitanAdapterError(
                TitanFailureCode.REQUEST_INVALID,
                "amount_raw must be an exact positive base-unit integer",
            )
        if not _is_base58(self.user_public_key):
            raise TitanAdapterError(
                TitanFailureCode.REQUEST_INVALID,
                "userPublicKey is required and must be a base58 public key",
            )
        for label, value in (
            ("input_representation_id", self.input_representation_id),
            ("output_representation_id", self.output_representation_id),
        ):
            if not isinstance(value, str) or not value or value != value.strip():
                raise TitanAdapterError(
                    TitanFailureCode.REQUEST_INVALID,
                    f"{label} is required (caller-owned canonical identity)",
                )
        if self.input_representation_id == self.output_representation_id:
            raise TitanAdapterError(
                TitanFailureCode.REQUEST_INVALID,
                "input and output representation ids must differ",
            )
        if self.slippage_bps is not None and not _is_bps(self.slippage_bps):
            raise TitanAdapterError(
                TitanFailureCode.REQUEST_INVALID,
                f"slippage_bps must be within [1, {MAX_SLIPPAGE_BPS}]",
            )
        if self.fee_account is not None and not _is_base58(self.fee_account):
            raise TitanAdapterError(
                TitanFailureCode.REQUEST_INVALID,
                "fee_account must be a base58 token-account public key",
            )
        if self.fee_bps is not None and (
            type(self.fee_bps) is not int or not 0 <= self.fee_bps <= MAX_FEE_BPS
        ):
            raise TitanAdapterError(
                TitanFailureCode.REQUEST_INVALID,
                f"fee_bps must be within [0, {MAX_FEE_BPS}] (documented Titan "
                "limit; higher values return no quotes)",
            )
        if (
            self.fee_from_input_mint is not None
            and type(self.fee_from_input_mint) is not bool
        ):
            raise TitanAdapterError(
                TitanFailureCode.REQUEST_INVALID,
                "fee_from_input_mint must be a bool",
            )

    def query_params(self) -> dict[str, str]:
        """Exact pinned portal query parameters (deterministic order)."""
        if self.swap_direction is not QuoteDirection.EXACT_IN:
            # TITAN-U5: the portal param table pins no swapMode query
            # parameter; emitting one would guess an unpinned shape.
            raise TitanAdapterError(
                TitanFailureCode.SCHEMA_MISSING_PIN,
                "portal swapMode query parameter is not pinned; ExactOut "
                "requests are refused rather than guessed",
            )
        params: dict[str, str] = {
            "inputMint": self.input_mint,
            "outputMint": self.output_mint,
            "amount": str(self.amount_raw),
            "userPublicKey": self.user_public_key,
        }
        if self.slippage_bps is not None:
            params["slippageBps"] = str(self.slippage_bps)
        if self.fee_account is not None:
            params["feeAccount"] = self.fee_account
        if self.fee_bps is not None:
            params["feeBps"] = str(self.fee_bps)
        if self.fee_from_input_mint is not None:
            params["feeFromInputMint"] = "true" if self.fee_from_input_mint else "false"
        return params

    @property
    def request_fingerprint(self) -> str:
        """Stable sha256 over the canonical query-parameter mapping."""
        return _canonical_sha256(self.query_params())


TitanTransport = Callable[[TitanSwapQuoteRequest], Mapping[str, object]]


# --------------------------------------------------------------------------
# Typed evidence records
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TitanQuoteEntry:
    """One provider-keyed Titan route preserved as typed race evidence.

    ``normalized`` is a kernel ``NormalizedProviderQuote`` (never redefined).
    ``instruction_program_ids`` / ``alt_addresses`` are evidence-only
    attribution per the overlap notes ("instructions program IDs (route venue
    identity)"); nothing here is ever compiled, signed or sent.
    """

    provider_entry: str
    normalized: NormalizedProviderQuote
    build_output: TitanBuildOutputClass
    instruction_program_ids: tuple[str, ...]
    alt_addresses: tuple[str, ...]
    slippage_bps: int
    compute_units: int | None
    compute_units_safe: int | None
    expires_after_slot: int | None
    reference_id: str | None
    recommended_winner: bool
    evidence_state: str = TITAN_EVIDENCE_STATE


@dataclass(frozen=True, slots=True)
class TitanQuoteBatch:
    """Normalized outcome of one Titan quote response (all evidence kept)."""

    batch_id: str | None
    expected_winner: str | None
    entries: tuple[TitanQuoteEntry, ...]
    failures: tuple[TitanQuoteFailure, ...]
    received_at_ns: int
    raw_payload_sha256: str
    request_fingerprint: str
    evidence_state: str = TITAN_EVIDENCE_STATE

    @property
    def provider_id(self) -> str:
        """The adapter-level provider id used for batch-level failures."""
        return "titan"


@dataclass(frozen=True, slots=True)
class TitanLiveCaptureVerdict:
    """Typed live-capture gate verdict: always BLOCKED in this slice."""

    status: str
    reason: str
    evidence_state: str
    adapter_version: str


def titan_live_capture_verdict() -> TitanLiveCaptureVerdict:
    """Deterministic BLOCKED verdict; nothing can authorize live capture here.

    Mirrors ``src/gpr_sui_shadow/providers.py``: live provider authorization
    requires a human operator action outside this repository slice. No
    environment variable, credential, configuration or fixture can flip this
    verdict — there is no code path that returns an authorized verdict.
    """
    return TitanLiveCaptureVerdict(
        status="BLOCKED",
        reason=TITAN_LIVE_CAPTURE_BLOCKED,
        evidence_state=TITAN_EVIDENCE_STATE,
        adapter_version=TITAN_ADAPTER_VERSION,
    )


# --------------------------------------------------------------------------
# Strict pinned-shape decoders (never guess; unpinned shapes -> MISSING_PIN)
# --------------------------------------------------------------------------


def _is_base58(value: object) -> bool:
    return isinstance(value, str) and _BASE58_RE.fullmatch(value) is not None


def _is_bps(value: object) -> bool:
    return type(value) is int and 1 <= value <= MAX_SLIPPAGE_BPS


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _exact_u64(container: Mapping[str, object], key: str, *, positive: bool) -> int:
    """Decode a pinned u64 JSON integer; string encodings are MISSING_PIN.

    The MessagePack wire type is pinned u64 (official Rust struct). The portal
    JSON encoding of u64 values (number vs string) is NOT pinned anywhere, so
    a string-encoded amount is refused with ``SCHEMA_MISSING_PIN`` (needs a
    new dossier version) instead of being parsed as a guess.
    """
    value = container.get(key)
    if isinstance(value, str):
        raise _entry_error(
            TitanFailureCode.SCHEMA_MISSING_PIN,
            f"{key} arrived string-encoded; portal JSON u64 encoding is not "
            "pinned (refuse, never guess)",
        )
    if type(value) is not int or value < 0 or value > _U64_MAX:
        raise _entry_error(
            TitanFailureCode.INVALID_SCHEMA,
            f"{key} must be a pinned u64 JSON integer",
        )
    if positive and value <= 0:
        raise _entry_error(
            TitanFailureCode.INVALID_SCHEMA, f"{key} must be a positive u64"
        )
    return value


def _optional_u64(
    container: Mapping[str, object], key: str, *, positive: bool = False
) -> int | None:
    if key not in container or container[key] is None:
        return None
    return _exact_u64(container, key, positive=positive)


def _require_base58(container: Mapping[str, object], key: str) -> str:
    value = container.get(key)
    if not _is_base58(value):
        raise _entry_error(
            TitanFailureCode.INVALID_SCHEMA, f"{key} must be a base58 public key"
        )
    return str(value)


def _entry_error(code: TitanFailureCode, detail: str) -> TitanAdapterError:
    return TitanAdapterError(code, detail)


def _parse_platform_fee(route: Mapping[str, object]) -> QuoteFeeComponent | None:
    raw = route.get("platformFee")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise _entry_error(
            TitanFailureCode.INVALID_SCHEMA, "platformFee must be an object"
        )
    amount = _exact_u64(raw, "amount", positive=False)
    fee_bps = raw.get("fee_bps")
    if type(fee_bps) is not int or not 0 <= fee_bps <= 255:
        raise _entry_error(
            TitanFailureCode.INVALID_SCHEMA,
            "platformFee.fee_bps must be a u8 basis-point integer "
            "(documented request/response name asymmetry: request feeBps, "
            "response fee_bps)",
        )
    # Official fee-collection doc: the fee is deducted FROM the swap amount
    # (included in the quoted amounts) -> PROVEN inclusion. The fee SIDE
    # (input vs output mint) is not carried by the response, so asset_id
    # stays None = UNKNOWN, never assumed.
    return QuoteFeeComponent(
        kind="platform_fee",
        amount_raw=amount,
        rate_text=f"{fee_bps}bps",
        asset_id=None,
        inclusion_state=FeeInclusionState.PROVEN,
    )


def _parse_steps(
    route: Mapping[str, object],
) -> tuple[
    tuple[RouteVenue, ...], tuple[PoolIdentity, ...], tuple[QuoteFeeComponent, ...]
]:
    raw_steps = route.get("steps")
    if not isinstance(raw_steps, list):
        raise _entry_error(
            TitanFailureCode.INVALID_SCHEMA,
            "steps is a required pinned Vec<RoutePlanStep>",
        )
    if len(raw_steps) > MAX_STEPS:
        raise _entry_error(
            TitanFailureCode.INVALID_SCHEMA,
            f"steps exceed the kernel route-venue bound ({MAX_STEPS})",
        )
    venues: list[RouteVenue] = []
    pools: list[PoolIdentity] = []
    fees: list[QuoteFeeComponent] = []
    seen_pool_keys: set[tuple[str, str]] = set()
    for index, step in enumerate(raw_steps):
        if not isinstance(step, Mapping):
            raise _entry_error(
                TitanFailureCode.INVALID_SCHEMA, f"steps[{index}] must be an object"
            )
        amm_key = _require_base58(step, "ammKey")
        label = step.get("label")
        if not isinstance(label, str) or not label or label != label.strip():
            raise _entry_error(
                TitanFailureCode.INVALID_SCHEMA,
                f"steps[{index}].label is a required string",
            )
        _require_base58(step, "inputMint")
        _require_base58(step, "outputMint")
        _exact_u64(step, "inAmount", positive=True)
        _exact_u64(step, "outAmount", positive=True)
        alloc_ppb = _exact_u64(step, "allocPpb", positive=False)
        if alloc_ppb > _U32_MAX:
            raise _entry_error(
                TitanFailureCode.INVALID_SCHEMA,
                f"steps[{index}].allocPpb must be a u32 parts-per-billion value",
            )
        pool = PoolIdentity(PoolIdentityKind.AMM_KEY, amm_key)
        if pool.key not in seen_pool_keys:
            seen_pool_keys.add(pool.key)
            pools.append(pool)
        share_bps: int | None = None
        if alloc_ppb % _PPB_PER_BPS == 0:
            share_bps = alloc_ppb // _PPB_PER_BPS
        venue = RouteVenue(
            venue_label=label,
            pool=pool,
            share_bps=share_bps,
        )
        venues.append(venue)
        fee_amount = step.get("feeAmount")
        fee_mint = step.get("feeMint")
        if fee_amount is not None or fee_mint is not None:
            if fee_amount is None or fee_mint is None:
                raise _entry_error(
                    TitanFailureCode.INVALID_SCHEMA,
                    f"steps[{index}] feeMint/feeAmount must be provided together",
                )
            if not _is_base58(fee_mint):
                raise _entry_error(
                    TitanFailureCode.INVALID_SCHEMA,
                    f"steps[{index}].feeMint must be a base58 public key",
                )
            if type(fee_amount) is not int or fee_amount < 0 or fee_amount > _U64_MAX:
                raise _entry_error(
                    TitanFailureCode.INVALID_SCHEMA,
                    f"steps[{index}].feeAmount must be a u64 integer",
                )
            fees.append(
                QuoteFeeComponent(
                    kind=f"route_step_{index}_venue_fee",
                    amount_raw=fee_amount,
                    asset_id=str(fee_mint),
                    inclusion_state=FeeInclusionState.UNKNOWN,
                )
            )
    return tuple(venues), tuple(pools), tuple(fees)


def _parse_instructions(
    route: Mapping[str, object],
) -> tuple[tuple[str, ...], TitanBuildOutputClass]:
    """Parse pinned ``Instruction {p,a,d}`` records and classify build output.

    The opaque ``transaction`` field (when present) is evidence-only: its
    bytes are NEVER decoded, compiled, signed or sent. Its exact portal JSON
    encoding is unpinned, so only an opaque string is accepted; any other
    shape is ``SCHEMA_MISSING_PIN``.
    """
    raw_instructions = route.get("instructions")
    raw_transaction = route.get("transaction")
    has_transaction = raw_transaction is not None
    if has_transaction and not isinstance(raw_transaction, (str, bytes)):
        raise _entry_error(
            TitanFailureCode.SCHEMA_MISSING_PIN,
            "transaction arrived in an unpinned encoding; only an opaque "
            "string/bytes value is accepted as evidence",
        )
    if raw_instructions is None:
        if not has_transaction:
            raise _entry_error(
                TitanFailureCode.INVALID_SCHEMA,
                "instructions is required unless a transaction is provided "
                "(official contract: instructions are not provided when a "
                "transaction is provided)",
            )
        return (), TitanBuildOutputClass.UNSIGNED_TRANSACTION
    if not isinstance(raw_instructions, list):
        raise _entry_error(
            TitanFailureCode.INVALID_SCHEMA, "instructions must be an array"
        )
    if has_transaction and raw_instructions:
        raise _entry_error(
            TitanFailureCode.INVALID_SCHEMA,
            "instructions and transaction are mutually exclusive per the "
            "official contract; both present is schema drift",
        )
    program_ids: list[str] = []
    for index, instruction in enumerate(raw_instructions):
        if not isinstance(instruction, Mapping):
            raise _entry_error(
                TitanFailureCode.INVALID_SCHEMA,
                f"instructions[{index}] must be an object",
            )
        program_id = _require_base58(instruction, "p")
        accounts = instruction.get("a")
        if not isinstance(accounts, list):
            raise _entry_error(
                TitanFailureCode.INVALID_SCHEMA,
                f"instructions[{index}].a must be an array of AccountMeta",
            )
        for account_index, account in enumerate(accounts):
            if not isinstance(account, Mapping):
                raise _entry_error(
                    TitanFailureCode.INVALID_SCHEMA,
                    f"instructions[{index}].a[{account_index}] must be an object",
                )
            _require_base58(account, "p")
            if type(account.get("s")) is not bool or type(account.get("w")) is not bool:
                raise _entry_error(
                    TitanFailureCode.INVALID_SCHEMA,
                    f"instructions[{index}].a[{account_index}] must carry bool "
                    "s (isSigner) and w (isWritable)",
                )
        data = instruction.get("d")
        if not isinstance(data, list):
            raise _entry_error(
                TitanFailureCode.INVALID_SCHEMA,
                f"instructions[{index}].d must be an array (Vec<u8>)",
            )
        for byte in data:
            if type(byte) is not int or not 0 <= byte <= 255:
                raise _entry_error(
                    TitanFailureCode.SCHEMA_MISSING_PIN,
                    f"instructions[{index}].d byte encoding is unpinned; only "
                    "an integer array in [0, 255] is accepted",
                )
        program_ids.append(program_id)
    if has_transaction:
        return tuple(program_ids), TitanBuildOutputClass.UNSIGNED_TRANSACTION
    if raw_instructions:
        return tuple(program_ids), TitanBuildOutputClass.INSTRUCTION_BUNDLE
    return (), TitanBuildOutputClass.QUOTE_ONLY


def _parse_alts(payload: Mapping[str, object]) -> None:
    """Validate the optional pinned ``alts`` contents (evidence-only)."""
    raw_alts = payload.get("alts")
    if raw_alts is None:
        return
    if not isinstance(raw_alts, list):
        raise _entry_error(TitanFailureCode.INVALID_SCHEMA, "alts must be an array")
    for index, alt in enumerate(raw_alts):
        if not isinstance(alt, Mapping):
            raise _entry_error(
                TitanFailureCode.INVALID_SCHEMA, f"alts[{index}] must be an object"
            )
        _require_base58(alt, "p")
        addresses = alt.get("a")
        if not isinstance(addresses, list):
            raise _entry_error(
                TitanFailureCode.INVALID_SCHEMA, f"alts[{index}].a must be an array"
            )
        for address in addresses:
            if not _is_base58(address):
                raise _entry_error(
                    TitanFailureCode.INVALID_SCHEMA,
                    f"alts[{index}].a entries must be base58 public keys",
                )


def _parse_route_entry(
    provider_entry: str,
    route: Mapping[str, object],
    *,
    request: TitanSwapQuoteRequest,
    direction: QuoteDirection,
    received_at_ns: int,
    expected_winner: str | None,
) -> TitanQuoteEntry:
    """Normalize one provider-keyed ``SwapRoute`` into kernel evidence.

    Raises :class:`TitanAdapterError` on any drift; the caller converts that
    into a typed :class:`TitanQuoteFailure` so the remaining entries are
    preserved.
    """
    try:
        in_amount = _exact_u64(route, "inAmount", positive=True)
        out_amount = _exact_u64(route, "outAmount", positive=True)
        slippage_bps = _exact_u64(route, "slippageBps", positive=False)
        if slippage_bps > MAX_SLIPPAGE_BPS:
            raise _entry_error(
                TitanFailureCode.INVALID_SCHEMA,
                "slippageBps exceeds 10000 basis points",
            )
        venues, pools, step_fees = _parse_steps(route)
        program_ids, build_output = _parse_instructions(route)
        raw_alts = route.get("addressLookupTables")
        if not isinstance(raw_alts, list):
            raise _entry_error(
                TitanFailureCode.INVALID_SCHEMA,
                "addressLookupTables is a required pinned array",
            )
        for alt in raw_alts:
            if not _is_base58(alt):
                raise _entry_error(
                    TitanFailureCode.INVALID_SCHEMA,
                    "addressLookupTables entries must be base58 public keys",
                )
        platform_fee = _parse_platform_fee(route)
        context_slot = _optional_u64(route, "contextSlot")
        expires_at_ms = _optional_u64(route, "expiresAtMs")
        expires_after_slot = _optional_u64(route, "expiresAfterSlot")
        compute_units = _optional_u64(route, "computeUnits", positive=True)
        compute_units_safe = _optional_u64(route, "computeUnitsSafe", positive=True)
        reference_id = route.get("reference_id")
        if reference_id is not None and (
            not isinstance(reference_id, str)
            or not reference_id
            or len(reference_id) > 256
        ):
            raise _entry_error(
                TitanFailureCode.INVALID_SCHEMA,
                "reference_id must be a short string when present",
            )
        # Exact amount binding: a route is evidence for exactly one amount.
        bound = in_amount if direction is QuoteDirection.EXACT_IN else out_amount
        if bound != request.amount_raw:
            raise _entry_error(
                TitanFailureCode.COMPARABILITY_DRIFT,
                f"route bound amount {bound} != requested amount "
                f"{request.amount_raw} (no scaling, ever)",
            )
        # The wire amounts are pinned exact base units ("Raw number of tokens
        # to swap, not scaled by decimals"), so the canonical representation
        # IS the base-unit integer: normalized == raw. No decimal rescaling
        # is fabricated here (unknown decimals are never guessed).
        correlation = ProviderCorrelation(
            correlation_group=TITAN_CORRELATION_GROUP,
            aggregator_lineage=("titan", provider_entry.lower()),
            pool_ids=pools,
        )
        freshness = QuoteFreshness(
            received_at_ns=received_at_ns,
            provider_generated_at_ns=None,
            slot=context_slot,
            checkpoint_sequence=None,
            expires_at_ns=None if expires_at_ms is None else expires_at_ms * 1_000_000,
        )
        fees = list(step_fees)
        if platform_fee is not None:
            fees.append(platform_fee)
        normalized = NormalizedProviderQuote(
            provider_id=f"titan:{provider_entry}",
            provider_generation=TITAN_PROVIDER_GENERATION,
            chain=TITAN_CHAIN,
            direction=direction,
            input_representation_id=request.input_representation_id,
            output_representation_id=request.output_representation_id,
            input_amount_raw=in_amount,
            output_amount_raw=out_amount,
            input_amount_normalized=in_amount,
            output_amount_normalized=out_amount,
            correlation=correlation,
            freshness=freshness,
            minimum_output_raw=None,
            fees=tuple(fees),
            compute_unit_estimate=(
                compute_units_safe if compute_units_safe is not None else compute_units
            ),
            route_venues=venues,
            taker=request.user_public_key,
            raw_response_hash=_canonical_sha256(route),
            request_fingerprint=request.request_fingerprint,
        )
        return TitanQuoteEntry(
            provider_entry=provider_entry,
            normalized=normalized,
            build_output=build_output,
            instruction_program_ids=program_ids,
            alt_addresses=tuple(str(alt) for alt in raw_alts),
            slippage_bps=slippage_bps,
            compute_units=compute_units,
            compute_units_safe=compute_units_safe,
            expires_after_slot=expires_after_slot,
            reference_id=reference_id,
            recommended_winner=(
                expected_winner is not None and expected_winner == provider_entry
            ),
        )
    except TitanAdapterError as error:
        raise _entry_error(
            error.code,
            f"entry {provider_entry!r}: {error.detail}",
        ) from error


def normalize_titan_quote_response(
    payload: Mapping[str, object],
    *,
    request: TitanSwapQuoteRequest,
    received_at_ns: int,
) -> TitanQuoteBatch:
    """Normalize a decoded Titan quote payload into typed kernel evidence.

    ``payload`` is an ALREADY-DECODED mapping (portal JSON shape). This
    function performs no I/O of any kind. Batch-level drift (envelope shape,
    mint/amount/swapMode mismatches) fails the whole batch; per-entry drift
    fails only that entry and the remaining entries are preserved — race
    evidence is never discarded.
    """
    if type(received_at_ns) is not int or received_at_ns < 0:
        raise TitanAdapterError(
            TitanFailureCode.REQUEST_INVALID,
            "received_at_ns must be an exact non-negative integer",
        )
    raw_payload_sha256 = _canonical_sha256(payload)

    def batch_failure(code: TitanFailureCode, detail: str) -> TitanQuoteBatch:
        return TitanQuoteBatch(
            batch_id=None,
            expected_winner=None,
            entries=(),
            failures=(
                TitanQuoteFailure(
                    provider_entry="titan",
                    code=code,
                    detail=detail,
                    kernel_failure_class=_kernel_failure_class(code),
                    raw_evidence_ref=raw_payload_sha256,
                ),
            ),
            received_at_ns=received_at_ns,
            raw_payload_sha256=raw_payload_sha256,
            request_fingerprint=request.request_fingerprint,
        )

    if not isinstance(payload, Mapping):
        return batch_failure(
            TitanFailureCode.INVALID_SCHEMA,
            "response payload must be a decoded mapping (pinned SwapQuotes shape)",
        )
    quotes = payload.get("quotes")
    if not isinstance(quotes, Mapping):
        return batch_failure(
            TitanFailureCode.INVALID_SCHEMA,
            "response must carry a quotes map keyed by provider ID "
            "(pinned SwapQuotes shape)",
        )
    batch_id = payload.get("id")
    if not isinstance(batch_id, str) or not batch_id or len(batch_id) > 256:
        return batch_failure(
            TitanFailureCode.INVALID_SCHEMA,
            "SwapQuotes.id is a required pinned string",
        )
    for key, expected in (
        ("inputMint", request.input_mint),
        ("outputMint", request.output_mint),
    ):
        supplied = payload.get(key)
        if supplied != expected:
            return batch_failure(
                TitanFailureCode.COMPARABILITY_DRIFT,
                f"{key} {supplied!r} != requested mint {expected!r}",
            )
    try:
        top_amount = _exact_u64(payload, "amount", positive=True)
    except TitanAdapterError as error:
        return batch_failure(error.code, error.detail)
    if top_amount != request.amount_raw:
        return batch_failure(
            TitanFailureCode.COMPARABILITY_DRIFT,
            f"response amount {top_amount} != requested amount "
            f"{request.amount_raw}",
        )
    swap_mode = payload.get("swapMode")
    expected_wire = (
        _EXACT_IN_WIRE
        if request.swap_direction is QuoteDirection.EXACT_IN
        else _EXACT_OUT_WIRE
    )
    if swap_mode not in (_EXACT_IN_WIRE, _EXACT_OUT_WIRE):
        return batch_failure(
            TitanFailureCode.SCHEMA_MISSING_PIN,
            f"swapMode {swap_mode!r} is not a pinned SwapMode wire value",
        )
    if swap_mode != expected_wire:
        return batch_failure(
            TitanFailureCode.COMPARABILITY_DRIFT,
            f"response swapMode {swap_mode!r} != requested direction",
        )
    if not quotes:
        return batch_failure(
            TitanFailureCode.EMPTY_QUOTES,
            "no quotes returned (documented Titan rejections: feeBps above "
            "the 10000 limit or a read-only userPublicKey return no quotes)",
        )
    metadata = payload.get("metadata")
    expected_winner: str | None = None
    if metadata is not None:
        if not isinstance(metadata, Mapping):
            return batch_failure(
                TitanFailureCode.INVALID_SCHEMA, "metadata must be an object"
            )
        raw_winner = metadata.get("ExpectedWinner")
        if raw_winner is not None:
            if not isinstance(raw_winner, str) or not raw_winner:
                return batch_failure(
                    TitanFailureCode.INVALID_SCHEMA,
                    "metadata.ExpectedWinner must be a provider key string",
                )
            if raw_winner not in quotes:
                return batch_failure(
                    TitanFailureCode.INVALID_SCHEMA,
                    f"metadata.ExpectedWinner {raw_winner!r} is not a quotes key "
                    "(official selection rule is quotes[metadata.ExpectedWinner])",
                )
            expected_winner = raw_winner
    try:
        _parse_alts(payload)
    except TitanAdapterError as error:
        return batch_failure(error.code, error.detail)

    if len(quotes) > MAX_BATCH_ENTRIES:
        return batch_failure(
            TitanFailureCode.INVALID_SCHEMA,
            f"more than {MAX_BATCH_ENTRIES} provider entries in one response",
        )
    entries: list[TitanQuoteEntry] = []
    entry_failures: list[TitanQuoteFailure] = []
    for provider_entry, route in quotes.items():
        if not isinstance(provider_entry, str) or not provider_entry:
            entry_failures.append(
                TitanQuoteFailure(
                    provider_entry="<unnamed>",
                    code=TitanFailureCode.INVALID_SCHEMA,
                    detail="quotes keys must be provider ID strings",
                    kernel_failure_class=_kernel_failure_class(
                        TitanFailureCode.INVALID_SCHEMA
                    ),
                    raw_evidence_ref=raw_payload_sha256,
                )
            )
            continue
        if not isinstance(route, Mapping):
            entry_failures.append(
                TitanQuoteFailure(
                    provider_entry=provider_entry,
                    code=TitanFailureCode.INVALID_SCHEMA,
                    detail="route entry must be an object (pinned SwapRoute)",
                    kernel_failure_class=_kernel_failure_class(
                        TitanFailureCode.INVALID_SCHEMA
                    ),
                    raw_evidence_ref=raw_payload_sha256,
                )
            )
            continue
        try:
            entries.append(
                _parse_route_entry(
                    provider_entry,
                    route,
                    request=request,
                    direction=request.swap_direction,
                    received_at_ns=received_at_ns,
                    expected_winner=expected_winner,
                )
            )
        except TitanAdapterError as error:
            entry_failures.append(
                TitanQuoteFailure(
                    provider_entry=provider_entry,
                    code=error.code,
                    detail=error.detail,
                    kernel_failure_class=_kernel_failure_class(error.code),
                    raw_evidence_ref=raw_payload_sha256,
                )
            )
    return TitanQuoteBatch(
        batch_id=batch_id,
        expected_winner=expected_winner,
        entries=tuple(entries),
        failures=tuple(entry_failures),
        received_at_ns=received_at_ns,
        raw_payload_sha256=raw_payload_sha256,
        request_fingerprint=request.request_fingerprint,
    )


def normalize_via_transport(
    transport: TitanTransport | None,
    request: TitanSwapQuoteRequest,
    *,
    received_at_ns: int,
) -> TitanQuoteBatch:
    """Normalize through an INJECTED transport (this module ships none).

    The transport callable receives the typed request and returns an
    already-decoded mapping. Passing ``None`` is a typed ``DISABLED`` refusal:
    the adapter is disabled by default and live transports are only provided
    by a human-authorized capture lane (see :func:`titan_live_capture_verdict`).
    Any transport exception becomes a typed failure batch (timeout vs
    transport), preserving the negative as race evidence.
    """
    if transport is None:
        raise TitanAdapterError(
            TitanFailureCode.DISABLED,
            "no transport is shipped with this adapter; live capture is not "
            f"authorized ({TITAN_LIVE_CAPTURE_BLOCKED}) and offline use must "
            "inject a pure callable (fixture) transport",
        )
    try:
        payload = transport(request)
    except TimeoutError as error:
        return _transport_failure_batch(request, received_at_ns, error)
    except Exception as error:  # noqa: BLE001 — typed negative for any transport
        return _transport_failure_batch(request, received_at_ns, error)
    return normalize_titan_quote_response(
        payload, request=request, received_at_ns=received_at_ns
    )


def _transport_failure_batch(
    request: TitanSwapQuoteRequest,
    received_at_ns: int,
    error: Exception,
) -> TitanQuoteBatch:
    code = (
        TitanFailureCode.TIMEOUT
        if isinstance(error, TimeoutError)
        else TitanFailureCode.TRANSPORT
    )
    failure = TitanQuoteFailure(
        provider_entry="titan",
        code=code,
        detail=f"{type(error).__name__}: {error}",
        kernel_failure_class=_kernel_failure_class(code),
        raw_evidence_ref=None,
    )
    return TitanQuoteBatch(
        batch_id=None,
        expected_winner=None,
        entries=(),
        failures=(failure,),
        received_at_ns=received_at_ns,
        raw_payload_sha256="",
        request_fingerprint=request.request_fingerprint,
    )


def map_http_status_failure(status: int, detail: str) -> TitanQuoteFailure:
    """Typed mapping of an HTTP status to a Titan failure record.

    Documented anchors: 401 for credential/host mismatch, 429 for rate
    limiting, "no quotes returned" for fee-limit rejections. The rest of the
    taxonomy is officially undocumented (UNKNOWN) and maps to HTTP_ERROR.
    """
    if status == 429:
        code = TitanFailureCode.RATE_LIMITED
    elif status in (401, 403):
        code = TitanFailureCode.UNAUTHORIZED
    else:
        code = TitanFailureCode.HTTP_ERROR
    return TitanQuoteFailure(
        provider_entry="titan",
        code=code,
        detail=f"HTTP {status}: {detail}",
        kernel_failure_class=_kernel_failure_class(code),
        raw_evidence_ref=None,
    )


# --------------------------------------------------------------------------
# Kernel seam helpers (typed construction; no kernel type is redefined)
# --------------------------------------------------------------------------


def build_kernel_race_request(request: TitanSwapQuoteRequest) -> QuoteRaceRequest:
    """Typed kernel race request bound to the exact Titan request identity."""
    return QuoteRaceRequest(
        chain=TITAN_CHAIN,
        input_representation_id=request.input_representation_id,
        output_representation_id=request.output_representation_id,
        direction=request.swap_direction,
        amount_raw=request.amount_raw,
        taker=request.user_public_key,
    )


def kernel_race_inputs(
    batch: TitanQuoteBatch,
) -> tuple[Sequence[NormalizedProviderQuote], Sequence[ProviderReadFailure]]:
    """Split a batch into kernel race inputs (all evidence preserved)."""
    return (
        tuple(entry.normalized for entry in batch.entries),
        tuple(failure.to_kernel_failure() for failure in batch.failures),
    )


def _stale_copy(
    quote: NormalizedProviderQuote, received_at_ns: int
) -> NormalizedProviderQuote:
    """Evidence-preserving freshness rewrite used by offline replay only."""
    return replace(
        quote, freshness=replace(quote.freshness, received_at_ns=received_at_ns)
    )
