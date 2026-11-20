"""R13-A2 Aftermath (Sui) quote adapter — offline, fail-closed, sender-free.

Closes the R13 audit row "Aftermath: adapter NONE" (``R13_GAP_NO_ADAPTER`` for
Aftermath) by producing kernel
:class:`~src.execution.quote_build_kernel.NormalizedProviderQuote` instances
from Aftermath ``POST /api/router/trade-route`` responses WITHOUT redefining
kernel types, without any network call, and without touching the GPR-03
checkpoint owner (``src/gpr_sui_shadow/providers/__init__.py`` — moved
verbatim from ``providers.py``; funnel/intake wiring is DEFERRED).

Pinned sources of truth:

- Wave-1 dossier: ``docs/integrations/offline/providers-wave1-2026-11-13/AFTERMATH_SUI.md``
  (router endpoint family, SDK semantics, fees, error shapes, correlation).
- Wave-2 dossier: ``docs/integrations/offline/sui-market-wave2-2026-11-14/AFTERMATH_ROUTER_WAVE2.md``
  (on-chain contract IDs, flash-lender verdict MISSING_PIN, per-pool fees
  BLOCKED_MISSING_PIN).
- Additive schema pin (this lane): ``docs/integrations/offline/aftermath-adapter-2026-11-19/``
  — the production OpenAPI document
  (``https://aftermath.finance/api/openapi/spec.json``, ``openapi: 3.1.0``,
  ``version: 1.0.0``, license ``MIT``, retrieved 2026-11-19) plus the official
  router SDK/auxiliary-endpoints/error-handling pages, all retrieved 2026-11-19.
  This pin RESOLVES the wave-1 typed gaps:
  1. ``/api/router/transactions/trade`` is now DECLARED (deprecated; legacy
     JSON-serialized transaction response) with ``/api/router/v1/transactions/trade``
     and ``/api/router/v1/transactions/add-trade`` as the documented
     ``TransactionKind`` replacements — the former BLOCKED_MISSING_PIN no
     longer applies. This adapter still never requests any transaction
     surface: it normalizes the QUOTE surface only (build ≠ quote).
  2. The integer wire encoding is now pinned: responses carry decimal strings
     with a trailing ``n`` (e.g. ``"5000000n"``); requests accept a JSON
     integer, a decimal string, or the ``n``-suffixed string.

Fail-closed stance:

1. DISABLED by default: this module ships NO transport. The transport is an
   injectable callable; ``normalize_via_transport(None, ...)`` refuses with a
   typed ``DISABLED`` error. The live-capture verdict is always
   ``BLOCKED / AFTERMATH_LIVE_CAPTURE_NOT_AUTHORIZED`` — no environment
   variable, credential or fixture can flip it (mirrors
   ``src/gpr_sui_shadow/providers`` ``LIVE_SUI_PROVIDERS_NOT_AUTHORIZED`` and
   the Titan adapter gate).
2. UNKNOWN is never zero: the pinned ``CompleteTradeRoute`` shape exposes no
   minimum-output field, no slot/checkpoint and no expiry, so
   ``minimum_output_raw`` stays ``None`` and freshness carries only the
   caller-supplied ``received_at_ns`` — never synthesized.
3. Never guess shapes: amounts decode ONLY through the pinned ``BigIntInput``
   forms (integer, decimal string, ``n``-suffixed string); ``poolId`` must be
   a valid Sui object id; ``portion`` must lie in the pinned 1e18-scaled
   fraction range; anything else is refused with a typed error.
4. Evidence states: every normalized quote is
   ``ADAPTER_BUILT_OFFLINE_UNQUALIFIED`` discovery evidence with literal
   ``execution_authority=False`` (kernel-inherited invariant).
5. Correlation: one ``trade-route`` response is ONE operator observation of
   the whole SOR (group ``aftermath-sor``). Aggregator lineage is
   ``("aftermath", *path protocol names lowercased)`` per the overlap notes:
   Aftermath routes over named venues (Cetus, BlueMove, ...), so each path's
   protocol joins the lineage and every path pool object id joins
   ``pool_ids`` — an Aftermath quote over a Cetus pool deduplicates against a
   direct Cetus capture via lineage/pool intersection.
6. HTTP-200 error payloads are failures, not successes: the pinned error
   page's ``{ error: ... }`` / ``{error_code, message}`` envelopes and bare
   string bodies are mapped to typed ``HTTP_ERROR`` failures before any
   quote parsing (``data.error`` is the primary signal).
7. Build-output separation: this module classifies the quote surface only.
   PTB composition (``/api/router/v1/transactions/add-trade`` →
   ``{ txKind, coinOutId }``) is a distinct builder surface owned by the
   R-03 lane; it is never built, decoded, signed or sent here.

No signing, no sending, no fee-account setup, no provider enablement, no
boot-path wiring. Fixtures under ``tests/fixtures/r13_aftermath_adapter/`` are
offline deterministic shapes built ONLY from the pinned schema.
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
    "AFTERMATH_CHAIN",
    "AFTERMATH_CORRELATION_GROUP",
    "AFTERMATH_ADAPTER_VERSION",
    "AFTERMATH_EVIDENCE_STATE",
    "AFTERMATH_LIVE_CAPTURE_BLOCKED",
    "AFTERMATH_OPENAPI_SPEC_URL",
    "AFTERMATH_PROVIDER_GENERATION",
    "AFTERMATH_TRADE_ROUTE_URL",
    "AftermathAdapterError",
    "AftermathExternalFee",
    "AftermathFailureCode",
    "AftermathLiveCaptureVerdict",
    "AftermathQuoteBatch",
    "AftermathQuoteEntry",
    "AftermathQuoteFailure",
    "AftermathSwapRouteRequest",
    "AftermathTransport",
    "build_kernel_race_request",
    "kernel_race_inputs",
    "map_http_status_failure",
    "normalize_aftermath_trade_route_response",
    "normalize_via_transport",
    "aftermath_live_capture_verdict",
]

# --------------------------------------------------------------------------
# Pinned identity constants (all values trace to the pinned dossiers)
# --------------------------------------------------------------------------

AFTERMATH_ADAPTER_VERSION = "r13.aftermath-adapter.v1"
#: Typed evidence state of every quote this adapter produces (offline,
#: unqualified; qualification requires user-gated live capture out of scope).
AFTERMATH_EVIDENCE_STATE = "ADAPTER_BUILT_OFFLINE_UNQUALIFIED"
#: Typed live-capture gate reason; mirrors LIVE_SUI_PROVIDERS_NOT_AUTHORIZED.
AFTERMATH_LIVE_CAPTURE_BLOCKED = "AFTERMATH_LIVE_CAPTURE_NOT_AUTHORIZED"
#: One operator correlation group for a whole trade-route response: the SOR's
#: single aggregated view, never independent per-path liquidity (overlap notes).
AFTERMATH_CORRELATION_GROUP = "aftermath-sor"
AFTERMATH_CHAIN = "sui"
AFTERMATH_PROVIDER_GENERATION = "aftermath.router-trade-route.openapi-2026-11-19"
#: Pinned production endpoint (evidence string only — this module never fetches).
AFTERMATH_TRADE_ROUTE_URL = "https://aftermath.finance/api/router/trade-route"
#: Pinned production OpenAPI document (the additive schema pin's source).
AFTERMATH_OPENAPI_SPEC_URL = "https://aftermath.finance/api/openapi/spec.json"

MAX_ROUTES = 32
MAX_PATHS_PER_ROUTE = 32  # kernel MAX_ROUTE_VENUES bound; wider fan-outs refused
MAX_FEE_BREAKDOWN = 64
MAX_TEXT = 256  # kernel text bound; longer coin types/ids are refused, not truncated
#: Pinned portion scale: "Fraction of the total input routed through this path,
#: as a fixed-point integer scaled by 1e18" (OpenAPI TradeRoute.portion).
_PORTION_SCALE = 10**18
#: Sui coin balances are u64 (chain type bound; judgment call documented in the
#: decoder docstring — wave-2 pins balances in smallest units, never decimals).
_U64_MAX = 2**64 - 1
#: Pinned SDK constant: Router.constants.maxExternalFeePercentage = 0.5.
_MAX_EXTERNAL_FEE_FRACTION = 0.5
#: Pinned slippage bounds on the v1 transaction surfaces: fraction in [0, 1],
#: "Missing or null defaults to 0.01" — the quote request shares the unit.
_MAX_SLIPPAGE_FRACTION = 1.0
_DEFAULT_SLIPPAGE_FRACTION = 0.01

_BIGINT_STRING_RE = re.compile(r"^[0-9]+n?$")
_SUI_OBJECT_ID_RE = re.compile(r"^0x[0-9a-fA-F]{1,64}$")


# --------------------------------------------------------------------------
# Typed failures and errors
# --------------------------------------------------------------------------


class AftermathFailureCode(StrEnum):
    """Typed adapter failure codes (kernel-mapped, never collapsed)."""

    REQUEST_INVALID = "request_invalid"
    DISABLED = "disabled"
    RATE_LIMITED = "rate_limited"
    UNAUTHORIZED = "unauthorized"
    HTTP_ERROR = "http_error"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    INVALID_SCHEMA = "invalid_schema"
    SCHEMA_MISSING_PIN = "schema_missing_pin"
    API_ERROR_ENVELOPE = "api_error_envelope"
    EMPTY_ROUTES = "empty_routes"
    COMPARABILITY_DRIFT = "comparability_drift"


class AftermathAdapterError(Exception):
    """Typed fail-closed adapter error (request-side and disabled stance)."""

    def __init__(self, code: AftermathFailureCode, detail: str) -> None:
        super().__init__(f"{code.value}: {detail}")
        self.code = code
        self.detail = detail


def _kernel_failure_class(code: AftermathFailureCode) -> ProviderReadFailureClass:
    """Frozen mapping AftermathFailureCode -> kernel ProviderReadFailureClass.

    Documented judgment calls: ``API_ERROR_ENVELOPE`` and ``EMPTY_ROUTES`` are
    valid HTTP-level business rejections (the pinned error page documents
    HTTP-200 error payloads and route-not-found responses), mapped to
    ``HTTP_ERROR`` with the typed detail preserved. ``SCHEMA_MISSING_PIN`` and
    ``COMPARABILITY_DRIFT`` map to ``INVALID_SCHEMA`` (the kernel has no wider
    refusal bucket; the typed AftermathFailureCode is always in the detail).
    """
    mapping: dict[AftermathFailureCode, ProviderReadFailureClass] = {
        AftermathFailureCode.REQUEST_INVALID: ProviderReadFailureClass.DISABLED,
        AftermathFailureCode.DISABLED: ProviderReadFailureClass.DISABLED,
        AftermathFailureCode.RATE_LIMITED: ProviderReadFailureClass.RATE_LIMITED,
        AftermathFailureCode.UNAUTHORIZED: ProviderReadFailureClass.UNAUTHORIZED,
        AftermathFailureCode.HTTP_ERROR: ProviderReadFailureClass.HTTP_ERROR,
        AftermathFailureCode.TIMEOUT: ProviderReadFailureClass.TRANSPORT,
        AftermathFailureCode.TRANSPORT: ProviderReadFailureClass.TRANSPORT,
        AftermathFailureCode.INVALID_SCHEMA: ProviderReadFailureClass.INVALID_SCHEMA,
        AftermathFailureCode.SCHEMA_MISSING_PIN: ProviderReadFailureClass.INVALID_SCHEMA,
        AftermathFailureCode.API_ERROR_ENVELOPE: ProviderReadFailureClass.HTTP_ERROR,
        AftermathFailureCode.EMPTY_ROUTES: ProviderReadFailureClass.HTTP_ERROR,
        AftermathFailureCode.COMPARABILITY_DRIFT: ProviderReadFailureClass.INVALID_SCHEMA,
    }
    return mapping[code]


# --------------------------------------------------------------------------
# Typed request construction (POST /api/router/trade-route, pinned body)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AftermathExternalFee:
    """Pinned ``ExternalFee`` request shape: recipient + fractional fee."""

    recipient: str
    fee_percentage: float

    def __post_init__(self) -> None:
        if not isinstance(self.recipient, str) or not _is_sui_address(self.recipient):
            raise AftermathAdapterError(
                AftermathFailureCode.REQUEST_INVALID,
                "externalFee.recipient must be a Sui address (0x + hex)",
            )
        if not isinstance(self.fee_percentage, (int, float)) or isinstance(
            self.fee_percentage, bool
        ):
            raise AftermathAdapterError(
                AftermathFailureCode.REQUEST_INVALID,
                "externalFee.feePercentage must be a number (fraction)",
            )
        if not 0 < float(self.fee_percentage) <= _MAX_EXTERNAL_FEE_FRACTION:
            raise AftermathAdapterError(
                AftermathFailureCode.REQUEST_INVALID,
                f"externalFee.feePercentage must be within (0, "
                f"{_MAX_EXTERNAL_FEE_FRACTION}] (pinned SDK maximum)",
            )

    def to_wire(self) -> dict[str, float | str]:
        return {
            "recipient": self.recipient,
            "feePercentage": float(self.fee_percentage),
        }


@dataclass(frozen=True, slots=True)
class AftermathSwapRouteRequest:
    """Typed ``POST /api/router/trade-route`` request (pinned body schema).

    ``trade-route`` requires ``coinInType``/``coinOutType`` and EXACTLY ONE
    amount: ``coinInAmount`` for a fixed-input (``ExactIn``) route or
    ``coinOutAmount`` for a fixed-output (``ExactOut``) route. Fixed-output
    routing REQUIRES ``slippage`` (fraction; 0.01 = 1%); the SDK's
    fixed-input signature carries no slippage parameter, so supplying one for
    ``ExactIn`` is refused rather than guessed. Amounts are emitted as exact
    base-unit integers (pinned ``BigIntInput`` integer form). Coin types are
    capped at the kernel's 256-character text bound — longer fully-qualified
    types are refused, never truncated.
    """

    coin_in_type: str
    coin_out_type: str
    amount_raw: int
    direction: QuoteDirection
    input_representation_id: str
    output_representation_id: str
    slippage: float | None = None
    external_fee: AftermathExternalFee | None = None
    referrer: str | None = None
    protocol_whitelist: tuple[str, ...] = ()
    protocol_blacklist: tuple[str, ...] = ()
    pool_whitelist: tuple[str, ...] = ()
    pool_blacklist: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for label, coin_type in (
            ("coinInType", self.coin_in_type),
            ("coinOutType", self.coin_out_type),
        ):
            if not _is_coin_type(coin_type):
                raise AftermathAdapterError(
                    AftermathFailureCode.REQUEST_INVALID,
                    f"{label} must be a fully-qualified Sui coin type",
                )
        if self.coin_in_type == self.coin_out_type:
            raise AftermathAdapterError(
                AftermathFailureCode.REQUEST_INVALID,
                "coinInType and coinOutType must differ",
            )
        if type(self.amount_raw) is not int or self.amount_raw <= 0:
            raise AftermathAdapterError(
                AftermathFailureCode.REQUEST_INVALID,
                "amount_raw must be an exact positive base-unit integer",
            )
        if self.amount_raw > _U64_MAX:
            raise AftermathAdapterError(
                AftermathFailureCode.REQUEST_INVALID,
                "amount_raw exceeds the Sui u64 balance bound",
            )
        if not isinstance(self.direction, QuoteDirection):
            raise AftermathAdapterError(
                AftermathFailureCode.REQUEST_INVALID,
                "direction must be a QuoteDirection",
            )
        for label, value in (
            ("input_representation_id", self.input_representation_id),
            ("output_representation_id", self.output_representation_id),
        ):
            if not isinstance(value, str) or not value or value != value.strip():
                raise AftermathAdapterError(
                    AftermathFailureCode.REQUEST_INVALID,
                    f"{label} is required (caller-owned canonical identity)",
                )
            if len(value) > MAX_TEXT:
                raise AftermathAdapterError(
                    AftermathFailureCode.REQUEST_INVALID,
                    f"{label} exceeds the kernel {MAX_TEXT}-character bound",
                )
        if self.input_representation_id == self.output_representation_id:
            raise AftermathAdapterError(
                AftermathFailureCode.REQUEST_INVALID,
                "input and output representation ids must differ",
            )
        if self.direction is QuoteDirection.EXACT_OUT:
            if self.slippage is None:
                raise AftermathAdapterError(
                    AftermathFailureCode.REQUEST_INVALID,
                    "fixed-output routing requires slippage (pinned)",
                )
            if not _is_slippage(self.slippage):
                raise AftermathAdapterError(
                    AftermathFailureCode.REQUEST_INVALID,
                    f"slippage must be a fraction within "
                    f"[0, {_MAX_SLIPPAGE_FRACTION}] (pinned)",
                )
        elif self.slippage is not None:
            raise AftermathAdapterError(
                AftermathFailureCode.SCHEMA_MISSING_PIN,
                "the pinned fixed-input SDK signature carries no slippage "
                "parameter; refusing rather than guessing the wire form",
            )
        if self.referrer is not None and not _is_sui_address(self.referrer):
            raise AftermathAdapterError(
                AftermathFailureCode.REQUEST_INVALID,
                "referrer must be a Sui address (0x + hex)",
            )
        for label, filters in (
            ("protocol_whitelist", self.protocol_whitelist),
            ("protocol_blacklist", self.protocol_blacklist),
        ):
            for name in filters:
                if not isinstance(name, str) or not name or name != name.strip():
                    raise AftermathAdapterError(
                        AftermathFailureCode.REQUEST_INVALID,
                        f"{label} entries must be non-empty protocol names",
                    )
        for label, filters in (
            ("pool_whitelist", self.pool_whitelist),
            ("pool_blacklist", self.pool_blacklist),
        ):
            for pool_id in filters:
                if not _is_sui_object_id(pool_id):
                    raise AftermathAdapterError(
                        AftermathFailureCode.REQUEST_INVALID,
                        f"{label} entries must be Sui object ids",
                    )
        if self.protocol_whitelist and self.protocol_blacklist:
            raise AftermathAdapterError(
                AftermathFailureCode.REQUEST_INVALID,
                "protocol whitelist and blacklist are mutually exclusive "
                "(pinned 'OR' shape)",
            )
        if self.pool_whitelist and self.pool_blacklist:
            raise AftermathAdapterError(
                AftermathFailureCode.REQUEST_INVALID,
                "pool whitelist and blacklist are mutually exclusive "
                "(pinned 'OR' shape)",
            )

    def body(self) -> dict[str, object]:
        """Exact pinned request body (deterministic key order)."""
        wire: dict[str, object] = {
            "coinInType": self.coin_in_type,
            "coinOutType": self.coin_out_type,
        }
        if self.direction is QuoteDirection.EXACT_IN:
            wire["coinInAmount"] = self.amount_raw
        else:
            wire["coinOutAmount"] = self.amount_raw
            wire["slippage"] = self.slippage
        if self.external_fee is not None:
            wire["externalFee"] = self.external_fee.to_wire()
        if self.referrer is not None:
            wire["referrer"] = self.referrer
        if self.protocol_whitelist:
            wire["protocolWhitelist"] = list(self.protocol_whitelist)
        if self.protocol_blacklist:
            wire["protocolBlacklist"] = list(self.protocol_blacklist)
        if self.pool_whitelist:
            wire["poolWhitelist"] = list(self.pool_whitelist)
        if self.pool_blacklist:
            wire["poolBlacklist"] = list(self.pool_blacklist)
        return wire

    @property
    def request_fingerprint(self) -> str:
        """Stable sha256 over the canonical request body mapping."""
        return _canonical_sha256(self.body())


AftermathTransport = Callable[[AftermathSwapRouteRequest], Mapping[str, object]]


# --------------------------------------------------------------------------
# Typed evidence records
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AftermathQuoteEntry:
    """One normalized SOR observation preserved as typed race evidence.

    ``normalized`` is a kernel ``NormalizedProviderQuote`` (never redefined).
    ``spot_price``/``net_trade_fee_percentage``/``slippage_echo`` are
    evidence-only pass-throughs of pinned response fields; nothing here is
    ever compiled, signed or sent.
    """

    normalized: NormalizedProviderQuote
    spot_price: float
    protocol_names: tuple[str, ...]
    net_trade_fee_percentage: float | None
    slippage_echo: float | None
    referrer: str | None
    evidence_state: str = AFTERMATH_EVIDENCE_STATE


@dataclass(frozen=True, slots=True)
class AftermathQuoteFailure:
    """One failed Aftermath read; preserved as evidence."""

    code: AftermathFailureCode
    detail: str
    kernel_failure_class: ProviderReadFailureClass
    raw_evidence_ref: str | None = None

    def to_kernel_failure(self) -> ProviderReadFailure:
        """Kernel-mapped typed negative for the quote race."""
        return ProviderReadFailure(
            provider_id="aftermath",
            failure_class=self.kernel_failure_class,
            detail=f"{self.code.value}: {self.detail}",
            raw_evidence_ref=self.raw_evidence_ref,
        )


@dataclass(frozen=True, slots=True)
class AftermathQuoteBatch:
    """Normalized outcome of one trade-route response (all evidence kept).

    One pinned response is ONE aggregated SOR observation, so a success batch
    carries exactly one entry; any batch-level drift collapses the whole
    response into a typed failure (a partially-understood aggregate quote is
    not evidence).
    """

    entries: tuple[AftermathQuoteEntry, ...]
    failures: tuple[AftermathQuoteFailure, ...]
    received_at_ns: int
    raw_payload_sha256: str
    request_fingerprint: str
    evidence_state: str = AFTERMATH_EVIDENCE_STATE

    @property
    def provider_id(self) -> str:
        """The adapter-level provider id used for batch-level failures."""
        return "aftermath"


@dataclass(frozen=True, slots=True)
class AftermathLiveCaptureVerdict:
    """Typed live-capture gate verdict: always BLOCKED in this slice."""

    status: str
    reason: str
    evidence_state: str
    adapter_version: str


def aftermath_live_capture_verdict() -> AftermathLiveCaptureVerdict:
    """Deterministic BLOCKED verdict; nothing can authorize live capture here.

    Mirrors ``src/gpr_sui_shadow/providers``: live provider authorization
    requires a human operator action outside this repository slice. No
    environment variable, credential, configuration or fixture can flip this
    verdict — there is no code path that returns an authorized verdict.
    """
    return AftermathLiveCaptureVerdict(
        status="BLOCKED",
        reason=AFTERMATH_LIVE_CAPTURE_BLOCKED,
        evidence_state=AFTERMATH_EVIDENCE_STATE,
        adapter_version=AFTERMATH_ADAPTER_VERSION,
    )


# --------------------------------------------------------------------------
# Strict pinned-shape decoders (never guess; unpinned shapes -> MISSING_PIN)
# --------------------------------------------------------------------------


def _is_coin_type(value: object) -> bool:
    """Fully-qualified Sui coin type: ``<pkg>::<module>::<NAME>``."""
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if len(value) > MAX_TEXT:
        return False
    parts = value.split("::")
    if len(parts) != 3 or not all(parts):
        return False
    return _is_sui_object_id(parts[0])


def _is_sui_object_id(value: object) -> bool:
    return isinstance(value, str) and _SUI_OBJECT_ID_RE.fullmatch(value) is not None


def _is_sui_address(value: object) -> bool:
    return _is_sui_object_id(value)


def _is_slippage(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return 0 <= float(value) <= _MAX_SLIPPAGE_FRACTION


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _parse_bigint(container: Mapping[str, object], key: str) -> int:
    """Decode a pinned ``BigIntInput`` amount into an exact integer.

    Pinned forms (production integer-encoding convention): a JSON integer, a
    decimal string, or a decimal string with a trailing ``n`` (what the API
    itself emits). Floats, negatives, empty strings, non-digit characters and
    anything else are typed ``INVALID_SCHEMA`` refusals (the API's own error
    convention for malformed BigInt fields is error code 2026). Coin amounts
    are additionally bounded by the Sui u64 balance type — a documented
    judgment call: the OpenAPI declares 64/128-bit integers generally, while
    Sui coin balances are u64 on-chain.
    """
    value = container.get(key)
    if type(value) is int and value >= 0:
        amount = value
    elif isinstance(value, str) and _BIGINT_STRING_RE.fullmatch(value):
        amount = int(value.rstrip("n"))
    else:
        raise AftermathAdapterError(
            AftermathFailureCode.INVALID_SCHEMA,
            f"{key} must be a pinned BigIntInput (integer, decimal string or "
            f"'...n' string); got {type(value).__name__}",
        )
    if amount > _U64_MAX:
        raise AftermathAdapterError(
            AftermathFailureCode.INVALID_SCHEMA,
            f"{key} exceeds the Sui u64 balance bound",
        )
    return amount


def _parse_trade_coin(container: object, label: str) -> tuple[str, int, int]:
    """Decode a pinned ``TradeCoin``: type, amount, tradeFee (all required)."""
    if not isinstance(container, Mapping):
        raise AftermathAdapterError(
            AftermathFailureCode.INVALID_SCHEMA, f"{label} must be an object"
        )
    coin_type = container.get("type")
    if not _is_coin_type(coin_type):
        raise AftermathAdapterError(
            AftermathFailureCode.INVALID_SCHEMA, f"{label}.type must be a coin type"
        )
    amount = _parse_bigint(container, "amount")
    if amount <= 0:
        raise AftermathAdapterError(
            AftermathFailureCode.INVALID_SCHEMA, f"{label}.amount must be positive"
        )
    trade_fee = _parse_bigint(container, "tradeFee")
    return str(coin_type), amount, trade_fee


def _parse_number(container: Mapping[str, object], key: str) -> float:
    value = container.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AftermathAdapterError(
            AftermathFailureCode.INVALID_SCHEMA, f"{key} must be a JSON number"
        )
    return float(value)


def _optional_number(container: Mapping[str, object], key: str) -> float | None:
    value = container.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AftermathAdapterError(
            AftermathFailureCode.INVALID_SCHEMA, f"{key} must be a JSON number"
        )
    return float(value)


def _optional_text(container: Mapping[str, object], key: str) -> str | None:
    value = container.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise AftermathAdapterError(
            AftermathFailureCode.INVALID_SCHEMA, f"{key} must be a string when present"
        )
    if len(value) > MAX_TEXT:
        raise AftermathAdapterError(
            AftermathFailureCode.INVALID_SCHEMA,
            f"{key} exceeds the kernel {MAX_TEXT}-character bound",
        )
    return value


def _parse_fee_breakdown(
    payload: Mapping[str, object],
) -> tuple[QuoteFeeComponent, ...]:
    """Decode pinned ``feeBreakdown[]`` entries into typed fee components.

    Each entry pins recipient/coinType/amount/feePercentage. The pinned fee
    page documents the SOR fee model but NOT whether ``feeBreakdown`` amounts
    are already deducted from ``coinOut.amount``, so ``inclusion_state`` stays
    UNKNOWN — never assumed proven.
    """
    raw = payload.get("feeBreakdown")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise AftermathAdapterError(
            AftermathFailureCode.INVALID_SCHEMA, "feeBreakdown must be an array"
        )
    if len(raw) > MAX_FEE_BREAKDOWN:
        raise AftermathAdapterError(
            AftermathFailureCode.INVALID_SCHEMA,
            f"feeBreakdown exceeds the {MAX_FEE_BREAKDOWN}-entry bound",
        )
    fees: list[QuoteFeeComponent] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, Mapping):
            raise AftermathAdapterError(
                AftermathFailureCode.INVALID_SCHEMA,
                f"feeBreakdown[{index}] must be an object",
            )
        recipient = _optional_text(entry, "recipient")
        coin_type = entry.get("coinType")
        if not _is_coin_type(coin_type):
            raise AftermathAdapterError(
                AftermathFailureCode.INVALID_SCHEMA,
                f"feeBreakdown[{index}].coinType must be a coin type",
            )
        amount = _parse_bigint(entry, "amount")
        fee_percentage = _optional_number(entry, "feePercentage")
        fees.append(
            QuoteFeeComponent(
                kind=f"fee_breakdown_{index}",
                amount_raw=amount,
                rate_text=None if fee_percentage is None else repr(fee_percentage),
                asset_id=str(coin_type),
                inclusion_state=FeeInclusionState.UNKNOWN,
            )
        )
        del recipient  # pinned evidence field; not carried by the kernel schema
    return tuple(fees)


def _parse_external_fee(container: object) -> QuoteFeeComponent | None:
    """Decode the pinned optional response ``externalFee`` (amount NOT given)."""
    if container is None:
        return None
    if not isinstance(container, Mapping):
        raise AftermathAdapterError(
            AftermathFailureCode.INVALID_SCHEMA, "externalFee must be an object"
        )
    recipient = _optional_text(container, "recipient")
    fee_percentage = _optional_number(container, "feePercentage")
    if recipient is None or fee_percentage is None:
        raise AftermathAdapterError(
            AftermathFailureCode.INVALID_SCHEMA,
            "externalFee requires recipient and feePercentage",
        )
    if not 0 < fee_percentage <= _MAX_EXTERNAL_FEE_FRACTION:
        raise AftermathAdapterError(
            AftermathFailureCode.INVALID_SCHEMA,
            f"externalFee.feePercentage outside the pinned (0, "
            f"{_MAX_EXTERNAL_FEE_FRACTION}] range",
        )
    return QuoteFeeComponent(
        kind="external_fee",
        amount_raw=None,  # the response pins NO fee amount; unknown stays None
        rate_text=repr(fee_percentage),
        asset_id=None,  # fee side (input vs output coin) is not pinned here
        inclusion_state=FeeInclusionState.UNKNOWN,
    )


def _parse_paths(
    route: Mapping[str, object],
) -> tuple[tuple[RouteVenue, ...], tuple[str, ...]]:
    """Decode one pinned ``TradeRoute``: parallel paths with pool identities.

    ``paths`` are the sequential hops of one portion; ``portion`` is the
    pinned 1e18-scaled fraction of the total input routed through it. Kernel
    ``share_bps`` is filled ONLY on an exact division (1e14 = 1bp), otherwise
    ``None`` (unknown share, never rounded). Every path pool id becomes a
    kernel ``POOL_OBJECT_ID`` pool identity; protocol names join the lineage.
    """
    raw_paths = route.get("paths")
    if not isinstance(raw_paths, list) or not raw_paths:
        raise AftermathAdapterError(
            AftermathFailureCode.INVALID_SCHEMA,
            "routes[].paths is a required non-empty pinned array",
        )
    if len(raw_paths) > MAX_PATHS_PER_ROUTE:
        raise AftermathAdapterError(
            AftermathFailureCode.INVALID_SCHEMA,
            f"routes[].paths exceed the kernel route-venue bound "
            f"({MAX_PATHS_PER_ROUTE})",
        )
    raw_portion = _parse_bigint(route, "portion")
    if not 0 < raw_portion <= _PORTION_SCALE:
        raise AftermathAdapterError(
            AftermathFailureCode.INVALID_SCHEMA,
            f"portion must be a positive fraction scaled by 1e18 "
            f"(got {raw_portion})",
        )
    share_bps: int | None = None
    if raw_portion % (_PORTION_SCALE // 10_000) == 0:
        share_bps = raw_portion // (_PORTION_SCALE // 10_000)
    venues: list[RouteVenue] = []
    protocols: list[str] = []
    for index, path in enumerate(raw_paths):
        if not isinstance(path, Mapping):
            raise AftermathAdapterError(
                AftermathFailureCode.INVALID_SCHEMA,
                f"paths[{index}] must be an object",
            )
        protocol_name = _optional_text(path, "protocolName")
        pool_id = path.get("poolId")
        if protocol_name is None:
            raise AftermathAdapterError(
                AftermathFailureCode.INVALID_SCHEMA,
                f"paths[{index}].protocolName is a required pinned string",
            )
        if not _is_sui_object_id(pool_id):
            raise AftermathAdapterError(
                AftermathFailureCode.INVALID_SCHEMA,
                f"paths[{index}].poolId must be a Sui object id",
            )
        _parse_trade_coin(path.get("coinIn"), f"paths[{index}].coinIn")
        _parse_trade_coin(path.get("coinOut"), f"paths[{index}].coinOut")
        _parse_number(path, "spotPrice")
        if "poolMetadata" not in path:
            raise AftermathAdapterError(
                AftermathFailureCode.INVALID_SCHEMA,
                f"paths[{index}].poolMetadata is a required pinned field",
            )
        protocols.append(protocol_name)
        venues.append(
            RouteVenue(
                venue_label=protocol_name,
                pool=PoolIdentity(PoolIdentityKind.POOL_OBJECT_ID, str(pool_id)),
                share_bps=share_bps,
            )
        )
    return tuple(venues), tuple(protocols)


def _route_venue_count(routes: Sequence[Mapping[str, object]]) -> int:
    total = 0
    for route in routes:
        paths = route.get("paths")
        if isinstance(paths, list):
            total += len(paths)
    return total


def _error_envelope_failure(
    payload: object, raw_payload_sha256: str
) -> AftermathQuoteFailure | None:
    """Typed HTTP-200/HTTP-error envelope detection (pinned error shapes).

    The pinned error page: ``{error_code, message, short_message?}``, ``{error:
    string}``, a bare string, or null; ``data.error`` is the primary signal —
    some routes return HTTP 200 with an error payload. Anything matching is a
    typed ``API_ERROR_ENVELOPE`` failure BEFORE any quote parsing.
    """
    if payload is None:
        return AftermathQuoteFailure(
            code=AftermathFailureCode.API_ERROR_ENVELOPE,
            detail="null response body (documented ApiErrorBody variant)",
            kernel_failure_class=_kernel_failure_class(
                AftermathFailureCode.API_ERROR_ENVELOPE
            ),
            raw_evidence_ref=raw_payload_sha256 or None,
        )
    if isinstance(payload, str):
        return AftermathQuoteFailure(
            code=AftermathFailureCode.API_ERROR_ENVELOPE,
            detail=f"string error body: {payload[:200]}",
            kernel_failure_class=_kernel_failure_class(
                AftermathFailureCode.API_ERROR_ENVELOPE
            ),
            raw_evidence_ref=raw_payload_sha256 or None,
        )
    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, str) and error:
            return AftermathQuoteFailure(
                code=AftermathFailureCode.API_ERROR_ENVELOPE,
                detail=f"documented error envelope: {error[:200]}",
                kernel_failure_class=_kernel_failure_class(
                    AftermathFailureCode.API_ERROR_ENVELOPE
                ),
                raw_evidence_ref=raw_payload_sha256 or None,
            )
        error_code = payload.get("error_code")
        message = payload.get("message")
        if (
            isinstance(error_code, int)
            and not isinstance(error_code, bool)
            and isinstance(message, str)
            and message
        ):
            return AftermathQuoteFailure(
                code=AftermathFailureCode.API_ERROR_ENVELOPE,
                detail=f"error_code {error_code}: {message[:200]}",
                kernel_failure_class=_kernel_failure_class(
                    AftermathFailureCode.API_ERROR_ENVELOPE
                ),
                raw_evidence_ref=raw_payload_sha256 or None,
            )
    return None


def _parse_route_entry(
    payload: Mapping[str, object],
    *,
    request: AftermathSwapRouteRequest,
    direction: QuoteDirection,
    received_at_ns: int,
) -> AftermathQuoteEntry:
    """Normalize one pinned ``CompleteTradeRoute`` into kernel evidence.

    Raises :class:`AftermathAdapterError` on any drift; the caller converts
    that into the typed failure batch.
    """
    raw_routes = payload.get("routes")
    if not isinstance(raw_routes, list):
        raise AftermathAdapterError(
            AftermathFailureCode.INVALID_SCHEMA,
            "routes is a required pinned array (CompleteTradeRoute)",
        )
    if not raw_routes:
        raise AftermathAdapterError(
            AftermathFailureCode.EMPTY_ROUTES,
            "no route returned (documented business rejection of the SOR)",
        )
    if len(raw_routes) > MAX_ROUTES:
        raise AftermathAdapterError(
            AftermathFailureCode.INVALID_SCHEMA,
            f"more than {MAX_ROUTES} route portions in one response",
        )
    routes = [route for route in raw_routes if isinstance(route, Mapping)]
    if len(routes) != len(raw_routes):
        raise AftermathAdapterError(
            AftermathFailureCode.INVALID_SCHEMA,
            "every routes[] entry must be an object",
        )
    if _route_venue_count(routes) > MAX_PATHS_PER_ROUTE:
        raise AftermathAdapterError(
            AftermathFailureCode.INVALID_SCHEMA,
            "flattened paths exceed the kernel route-venue bound",
        )

    coin_in_type, coin_in_amount, coin_in_fee = _parse_trade_coin(
        payload.get("coinIn"), "coinIn"
    )
    coin_out_type, coin_out_amount, coin_out_fee = _parse_trade_coin(
        payload.get("coinOut"), "coinOut"
    )
    spot_price = _parse_number(payload, "spotPrice")
    expected_in = request.coin_in_type
    expected_out = request.coin_out_type
    if coin_in_type != expected_in or coin_out_type != expected_out:
        raise AftermathAdapterError(
            AftermathFailureCode.COMPARABILITY_DRIFT,
            f"response coin types ({coin_in_type!r} -> {coin_out_type!r}) != "
            f"requested ({expected_in!r} -> {expected_out!r})",
        )
    # Exact amount binding: a response is evidence for exactly one amount.
    bound = coin_in_amount if direction is QuoteDirection.EXACT_IN else coin_out_amount
    if bound != request.amount_raw:
        raise AftermathAdapterError(
            AftermathFailureCode.COMPARABILITY_DRIFT,
            f"bound amount {bound} != requested amount {request.amount_raw} "
            "(no scaling, ever)",
        )

    venues: list[RouteVenue] = []
    pools: list[PoolIdentity] = []
    protocols: list[str] = []
    for route in routes:
        route_venues, route_protocols = _parse_paths(route)
        venues.extend(route_venues)
        protocols.extend(route_protocols)
    seen_pool_keys: set[tuple[str, str]] = set()
    unique_pools: list[PoolIdentity] = []
    for venue in venues:
        assert venue.pool is not None
        if venue.pool.key not in seen_pool_keys:
            seen_pool_keys.add(venue.pool.key)
            unique_pools.append(venue.pool)

    fees: list[QuoteFeeComponent] = list(_parse_fee_breakdown(payload))
    external_fee = _parse_external_fee(payload.get("externalFee"))
    if external_fee is not None:
        fees.append(external_fee)
    net_trade_fee_percentage = _optional_number(payload, "netTradeFeePercentage")
    if net_trade_fee_percentage is not None:
        fees.append(
            QuoteFeeComponent(
                kind="net_trade_fee",
                amount_raw=None,  # rate-only field; amount is unknown
                rate_text=repr(net_trade_fee_percentage),
                asset_id=None,
                inclusion_state=FeeInclusionState.UNKNOWN,
            )
        )
    # Pinned SOR fee model: "No protocol fee is taken on trades performed
    # through the Aftermath Smart-Order Router." A pinned-zero tradeFee is
    # therefore recorded as NOT_APPLICABLE-free (no component); a NONZERO
    # tradeFee is schema drift against the pinned fee model and is refused.
    for label, trade_fee in (
        ("coinIn.tradeFee", coin_in_fee),
        ("coinOut.tradeFee", coin_out_fee),
    ):
        if trade_fee != 0:
            raise AftermathAdapterError(
                AftermathFailureCode.COMPARABILITY_DRIFT,
                f"{label}={trade_fee} contradicts the pinned SOR fee model "
                "(no protocol fee on SOR trades); refusing rather than "
                "interpreting the drift",
            )
    slippage_echo = _optional_number(payload, "slippage")
    if slippage_echo is not None and not _is_slippage(slippage_echo):
        raise AftermathAdapterError(
            AftermathFailureCode.INVALID_SCHEMA,
            "response slippage must be a fraction within [0, 1] when present",
        )
    referrer = _optional_text(payload, "referrer")

    # The wire amounts are pinned exact base units, so the canonical
    # representation IS the base-unit integer: normalized == raw. No decimal
    # rescaling is fabricated here (unknown decimals are never guessed).
    correlation = ProviderCorrelation(
        correlation_group=AFTERMATH_CORRELATION_GROUP,
        aggregator_lineage=("aftermath", *(name.lower() for name in protocols)),
        pool_ids=tuple(unique_pools),
    )
    freshness = QuoteFreshness(
        received_at_ns=received_at_ns,
        provider_generated_at_ns=None,
        slot=None,
        checkpoint_sequence=None,
        expires_at_ns=None,
    )
    normalized = NormalizedProviderQuote(
        provider_id="aftermath",
        provider_generation=AFTERMATH_PROVIDER_GENERATION,
        chain=AFTERMATH_CHAIN,
        direction=direction,
        input_representation_id=request.input_representation_id,
        output_representation_id=request.output_representation_id,
        input_amount_raw=coin_in_amount,
        output_amount_raw=coin_out_amount,
        input_amount_normalized=coin_in_amount,
        output_amount_normalized=coin_out_amount,
        correlation=correlation,
        freshness=freshness,
        minimum_output_raw=None,
        fees=tuple(fees),
        compute_unit_estimate=None,
        route_venues=tuple(venues),
        taker=None,
        raw_response_hash=_canonical_sha256(payload),
        request_fingerprint=request.request_fingerprint,
    )
    return AftermathQuoteEntry(
        normalized=normalized,
        spot_price=spot_price,
        protocol_names=tuple(protocols),
        net_trade_fee_percentage=net_trade_fee_percentage,
        slippage_echo=slippage_echo,
        referrer=referrer,
    )


def normalize_aftermath_trade_route_response(
    payload: object,
    *,
    request: AftermathSwapRouteRequest,
    received_at_ns: int,
) -> AftermathQuoteBatch:
    """Normalize a decoded Aftermath trade-route payload into kernel evidence.

    ``payload`` is an ALREADY-DECODED value (the transport returns decoded
    JSON). This function performs no I/O of any kind. Error-envelope shapes
    (pinned) fail the whole response as typed negatives before any quote
    parsing; schema drift on the single aggregate quote also fails the whole
    response — a partially-understood aggregate is not evidence.
    """
    if type(received_at_ns) is not int or received_at_ns < 0:
        raise AftermathAdapterError(
            AftermathFailureCode.REQUEST_INVALID,
            "received_at_ns must be an exact non-negative integer",
        )
    raw_payload_sha256 = (
        _canonical_sha256(payload) if isinstance(payload, Mapping) else ""
    )

    def batch_failure(
        code: AftermathFailureCode,
        detail: str,
        raw_ref: str | None = raw_payload_sha256,
    ) -> AftermathQuoteBatch:
        return AftermathQuoteBatch(
            entries=(),
            failures=(
                AftermathQuoteFailure(
                    code=code,
                    detail=detail,
                    kernel_failure_class=_kernel_failure_class(code),
                    raw_evidence_ref=raw_ref or None,
                ),
            ),
            received_at_ns=received_at_ns,
            raw_payload_sha256=raw_payload_sha256,
            request_fingerprint=request.request_fingerprint,
        )

    envelope_failure = _error_envelope_failure(payload, raw_payload_sha256)
    if envelope_failure is not None:
        return AftermathQuoteBatch(
            entries=(),
            failures=(envelope_failure,),
            received_at_ns=received_at_ns,
            raw_payload_sha256=raw_payload_sha256,
            request_fingerprint=request.request_fingerprint,
        )
    if not isinstance(payload, Mapping):
        return batch_failure(
            AftermathFailureCode.INVALID_SCHEMA,
            "response payload must be a decoded mapping (pinned "
            "CompleteTradeRoute shape)",
        )
    try:
        entry = _parse_route_entry(
            payload,
            request=request,
            direction=request.direction,
            received_at_ns=received_at_ns,
        )
    except AftermathAdapterError as error:
        return batch_failure(error.code, error.detail)
    return AftermathQuoteBatch(
        entries=(entry,),
        failures=(),
        received_at_ns=received_at_ns,
        raw_payload_sha256=raw_payload_sha256,
        request_fingerprint=request.request_fingerprint,
    )


def normalize_via_transport(
    transport: AftermathTransport | None,
    request: AftermathSwapRouteRequest,
    *,
    received_at_ns: int,
) -> AftermathQuoteBatch:
    """Normalize through an INJECTED transport (this module ships none).

    The transport callable receives the typed request and returns an
    already-decoded value. Passing ``None`` is a typed ``DISABLED`` refusal:
    the adapter is disabled by default and live transports are only provided
    by a human-authorized capture lane (see :func:`aftermath_live_capture_verdict`).
    Any transport exception becomes a typed failure batch (timeout vs
    transport), preserving the negative as race evidence.
    """
    if transport is None:
        raise AftermathAdapterError(
            AftermathFailureCode.DISABLED,
            "no transport is shipped with this adapter; live capture is not "
            f"authorized ({AFTERMATH_LIVE_CAPTURE_BLOCKED}) and offline use must "
            "inject a pure callable (fixture) transport",
        )
    try:
        payload = transport(request)
    except TimeoutError as error:
        return _transport_failure_batch(request, received_at_ns, error)
    except Exception as error:  # noqa: BLE001 — typed negative for any transport
        return _transport_failure_batch(request, received_at_ns, error)
    return normalize_aftermath_trade_route_response(
        payload, request=request, received_at_ns=received_at_ns
    )


def _transport_failure_batch(
    request: AftermathSwapRouteRequest,
    received_at_ns: int,
    error: Exception,
) -> AftermathQuoteBatch:
    code = (
        AftermathFailureCode.TIMEOUT
        if isinstance(error, TimeoutError)
        else AftermathFailureCode.TRANSPORT
    )
    failure = AftermathQuoteFailure(
        code=code,
        detail=f"{type(error).__name__}: {error}",
        kernel_failure_class=_kernel_failure_class(code),
        raw_evidence_ref=None,
    )
    return AftermathQuoteBatch(
        entries=(),
        failures=(failure,),
        received_at_ns=received_at_ns,
        raw_payload_sha256="",
        request_fingerprint=request.request_fingerprint,
    )


def map_http_status_failure(status: int, detail: str) -> AftermathQuoteFailure:
    """Typed mapping of an HTTP status to an Aftermath failure record.

    Documented anchors: 429 for rate limiting, 401/403 for authorization, and
    the documented 5xx envelope bodies (`Error 2020: ...`). The router-family
    explicit 429 code list stays UNKNOWN beyond the pinned default quota
    (1000 requests / 10 seconds).
    """
    if status == 429:
        code = AftermathFailureCode.RATE_LIMITED
    elif status in (401, 403):
        code = AftermathFailureCode.UNAUTHORIZED
    else:
        code = AftermathFailureCode.HTTP_ERROR
    return AftermathQuoteFailure(
        code=code,
        detail=f"HTTP {status}: {detail}",
        kernel_failure_class=_kernel_failure_class(code),
        raw_evidence_ref=None,
    )


# --------------------------------------------------------------------------
# Kernel seam helpers (typed construction; no kernel type is redefined)
# --------------------------------------------------------------------------


def build_kernel_race_request(request: AftermathSwapRouteRequest) -> QuoteRaceRequest:
    """Typed kernel race request bound to the exact Aftermath request identity."""
    return QuoteRaceRequest(
        chain=AFTERMATH_CHAIN,
        input_representation_id=request.input_representation_id,
        output_representation_id=request.output_representation_id,
        direction=request.direction,
        amount_raw=request.amount_raw,
        taker=None,  # the pinned quote surface carries no wallet identity
    )


def kernel_race_inputs(
    batch: AftermathQuoteBatch,
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
