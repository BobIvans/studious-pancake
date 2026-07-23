"""SUPER-MPR-A canonical runtime and trusted provider gateway contracts.

This module is intentionally standard-library-only and side-effect-free.  It
does not open sockets, read wallets, sign transactions, submit transactions or
enable live/Jito execution.  It gives the installed runtime a concrete contract
for:

* one canonical production-facing command surface;
* legacy/source-only execution quarantine;
* provider/RPC evidence normalization through one trusted gateway boundary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "super-mpr-a.canonical-runtime-gateway.v1"
CANONICAL_ENTRYPOINT = "flashloan-bot"
CANONICAL_MAIN_TARGET = "src.cli_pr189:main"
CANONICAL_ALLOWED_COMMANDS = ("status", "paper", "shadow", "verify")

LEGACY_EXECUTION_SURFACES = (
    "arb_bot.py",
    "src.cli",
    "src.legacy_arb_bot",
    "src.ingest.execution_router",
    "src.ingest.jito_shotgun",
    "src.ingest.wsol_manager",
    "src.ingest.dust_sweeper",
    "src.execution.senders",
)

PAPER_FORBIDDEN_IMPORT_PREFIXES = (
    "src.execution.senders",
    "src.isolated_signer",
    "src.ingest.jito_shotgun",
    "src.execution.live_control",
)

_PROVIDER_NAME = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PUBKEYISH = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,64}$")


class SuperMprAError(ValueError):
    """Raised when SUPER-MPR-A evidence fails closed."""


@dataclass(frozen=True, slots=True)
class ProviderGatewayPolicy:
    """Bounded provider/RPC admission policy for already-fetched bytes."""

    provider_id: str
    min_context_slot: int
    max_response_bytes: int = 512_000
    max_json_depth: int = 24
    max_json_nodes: int = 20_000
    retry_budget: int = 2
    quota_budget: int = 1
    timeout_ms: int = 1_500
    max_slot_lag: int = 32
    require_provider_echo: bool = True

    def __post_init__(self) -> None:
        _provider_id(self.provider_id)
        _non_negative_int(self.min_context_slot, "min_context_slot")
        _positive_int(self.max_response_bytes, "max_response_bytes")
        _positive_int(self.max_json_depth, "max_json_depth")
        _positive_int(self.max_json_nodes, "max_json_nodes")
        _non_negative_int(self.retry_budget, "retry_budget")
        _positive_int(self.quota_budget, "quota_budget")
        _positive_int(self.timeout_ms, "timeout_ms")
        _non_negative_int(self.max_slot_lag, "max_slot_lag")


@dataclass(frozen=True, slots=True)
class ProviderGatewayBudget:
    """Per-cycle deterministic retry/quota accounting evidence."""

    requests_consumed: int
    retries_consumed: int

    def __post_init__(self) -> None:
        _non_negative_int(self.requests_consumed, "requests_consumed")
        _non_negative_int(self.retries_consumed, "retries_consumed")


@dataclass(frozen=True, slots=True)
class ProviderGatewayRequest:
    """Canonical provider request identity before network transport."""

    provider_id: str
    method: str
    url_fingerprint: str
    body_sha256: str
    purpose: str

    def __post_init__(self) -> None:
        _provider_id(self.provider_id)
        _text(self.method, "method")
        _sha256(self.url_fingerprint, "url_fingerprint")
        _sha256(self.body_sha256, "body_sha256")
        _text(self.purpose, "purpose")

    @property
    def digest(self) -> str:
        return _hash_json(asdict(self))


@dataclass(frozen=True, slots=True)
class NormalizedProviderQuote:
    """Provider-neutral quote/route evidence consumed by paper/shadow."""

    schema_version: str
    provider_id: str
    provider_capability: str
    route_id: str
    input_mint: str
    output_mint: str
    in_amount_base_units: int
    out_amount_base_units: int
    context_slot: int
    observed_at_unix_ms: int
    expires_at_unix_ms: int
    slippage_bps: int
    provider_confidence_bps: int
    request_digest: str
    response_digest: str
    route_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise SuperMprAError("BAD_NORMALIZED_QUOTE_SCHEMA")
        _provider_id(self.provider_id)
        _text(self.provider_capability, "provider_capability")
        _text(self.route_id, "route_id")
        _pubkeyish(self.input_mint, "input_mint")
        _pubkeyish(self.output_mint, "output_mint")
        _non_negative_int(self.in_amount_base_units, "in_amount_base_units")
        _non_negative_int(self.out_amount_base_units, "out_amount_base_units")
        _non_negative_int(self.context_slot, "context_slot")
        _non_negative_int(self.observed_at_unix_ms, "observed_at_unix_ms")
        _non_negative_int(self.expires_at_unix_ms, "expires_at_unix_ms")
        _non_negative_int(self.slippage_bps, "slippage_bps")
        _non_negative_int(self.provider_confidence_bps, "provider_confidence_bps")
        if self.provider_confidence_bps > 10_000:
            raise SuperMprAError("PROVIDER_CONFIDENCE_TOO_HIGH")
        if self.slippage_bps > 10_000:
            raise SuperMprAError("SLIPPAGE_TOO_HIGH")
        if self.expires_at_unix_ms <= self.observed_at_unix_ms:
            raise SuperMprAError("QUOTE_EXPIRY_NOT_AFTER_OBSERVATION")
        _sha256(self.request_digest, "request_digest")
        _sha256(self.response_digest, "response_digest")
        _sha256(self.route_digest, "route_digest")


@dataclass(frozen=True, slots=True)
class RuntimeAuthorityReport:
    schema_version: str
    canonical_entrypoint: str
    canonical_target: str
    allowed_commands: tuple[str, ...]
    legacy_surfaces: tuple[str, ...]
    paper_forbidden_import_prefixes: tuple[str, ...]
    live_trading_enabled: bool
    signer_available_from_paper: bool
    sender_available_from_paper: bool
    jito_available_from_paper: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def canonical_runtime_report() -> RuntimeAuthorityReport:
    """Return the supported installed runtime contract for SUPER-MPR-A."""

    return RuntimeAuthorityReport(
        schema_version=SCHEMA_VERSION,
        canonical_entrypoint=CANONICAL_ENTRYPOINT,
        canonical_target=CANONICAL_MAIN_TARGET,
        allowed_commands=CANONICAL_ALLOWED_COMMANDS,
        legacy_surfaces=LEGACY_EXECUTION_SURFACES,
        paper_forbidden_import_prefixes=PAPER_FORBIDDEN_IMPORT_PREFIXES,
        live_trading_enabled=False,
        signer_available_from_paper=False,
        sender_available_from_paper=False,
        jito_available_from_paper=False,
    )


def rewrite_canonical_command(argv: Sequence[str]) -> list[str]:
    """Map the public SUPER-MPR-A command surface to the active installed CLI.

    The aliases are intentionally one-way wrappers around the installed runtime.
    There is no alias to ``live``.
    """

    args = list(argv)
    if not args:
        return args
    command = args[0]
    tail = args[1:]
    if command == "paper":
        return ["run", "--mode", "paper", *tail]
    if command == "shadow":
        return ["run", "--mode", "shadow", *tail]
    if command == "verify":
        return ["readiness", *tail]
    if command == "status":
        return args
    return args


def assert_paper_source_guard(module_name: str, imported_modules: Sequence[str]) -> None:
    """Fail closed if paper/shadow code reaches signer/sender/Jito surfaces."""

    normalized = tuple(str(item) for item in imported_modules)
    for imported in normalized:
        for prefix in PAPER_FORBIDDEN_IMPORT_PREFIXES:
            if imported == prefix or imported.startswith(f"{prefix}."):
                raise SuperMprAError(
                    f"PAPER_RUNTIME_FORBIDDEN_IMPORT:{module_name}:{imported}"
                )


def assert_legacy_surface_quarantined(surface: str, *, explicit_manual_flag: bool) -> None:
    """Legacy execution surfaces must require explicit unsafe/manual use."""

    if surface in LEGACY_EXECUTION_SURFACES and not explicit_manual_flag:
        raise SuperMprAError(f"LEGACY_SURFACE_NOT_QUARANTINED:{surface}")


def validate_gateway_budget(
    policy: ProviderGatewayPolicy,
    budget: ProviderGatewayBudget,
) -> None:
    if budget.requests_consumed >= policy.quota_budget:
        raise SuperMprAError("PROVIDER_QUOTA_BUDGET_EXHAUSTED")
    if budget.retries_consumed > policy.retry_budget:
        raise SuperMprAError("PROVIDER_RETRY_BUDGET_EXHAUSTED")


def normalize_provider_quote(
    *,
    policy: ProviderGatewayPolicy,
    budget: ProviderGatewayBudget,
    request: ProviderGatewayRequest,
    raw_response: bytes,
    received_at_unix_ms: int,
) -> NormalizedProviderQuote:
    """Normalize already-fetched provider bytes into the internal quote model."""

    if request.provider_id != policy.provider_id:
        raise SuperMprAError("PROVIDER_REQUEST_POLICY_MISMATCH")
    validate_gateway_budget(policy, budget)
    _non_negative_int(received_at_unix_ms, "received_at_unix_ms")
    if len(raw_response) > policy.max_response_bytes:
        raise SuperMprAError("PROVIDER_RESPONSE_TOO_LARGE")
    payload = _load_bounded_json(
        raw_response,
        max_depth=policy.max_json_depth,
        max_nodes=policy.max_json_nodes,
    )
    if not isinstance(payload, dict):
        raise SuperMprAError("PROVIDER_RESPONSE_NOT_OBJECT")
    if policy.require_provider_echo and payload.get("provider_id") != policy.provider_id:
        raise SuperMprAError("PROVIDER_ID_ECHO_MISMATCH")

    context_slot = _json_int(payload, "context_slot")
    if context_slot < policy.min_context_slot:
        raise SuperMprAError("PROVIDER_CONTEXT_SLOT_TOO_OLD")
    if context_slot + policy.max_slot_lag < policy.min_context_slot:
        raise SuperMprAError("PROVIDER_SLOT_LAG_EXCEEDED")

    route_id = _json_text(payload, "route_id")
    input_mint = _json_text(payload, "input_mint")
    output_mint = _json_text(payload, "output_mint")
    in_amount = _json_int(payload, "in_amount_base_units")
    out_amount = _json_int(payload, "out_amount_base_units")
    expires_at = _json_int(payload, "expires_at_unix_ms")
    slippage_bps = _json_int(payload, "slippage_bps")
    confidence_bps = _json_int(payload, "provider_confidence_bps")
    capability = str(payload.get("provider_capability", "quote_route"))

    response_digest = hashlib.sha256(raw_response).hexdigest()
    route_digest = _hash_json(
        {
            "provider_id": policy.provider_id,
            "route_id": route_id,
            "input_mint": input_mint,
            "output_mint": output_mint,
            "in_amount_base_units": in_amount,
            "out_amount_base_units": out_amount,
            "context_slot": context_slot,
            "expires_at_unix_ms": expires_at,
            "response_digest": response_digest,
        }
    )
    return NormalizedProviderQuote(
        schema_version=SCHEMA_VERSION,
        provider_id=policy.provider_id,
        provider_capability=capability,
        route_id=route_id,
        input_mint=input_mint,
        output_mint=output_mint,
        in_amount_base_units=in_amount,
        out_amount_base_units=out_amount,
        context_slot=context_slot,
        observed_at_unix_ms=received_at_unix_ms,
        expires_at_unix_ms=expires_at,
        slippage_bps=slippage_bps,
        provider_confidence_bps=confidence_bps,
        request_digest=request.digest,
        response_digest=response_digest,
        route_digest=route_digest,
    )


def _load_bounded_json(raw: bytes, *, max_depth: int, max_nodes: int) -> Any:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SuperMprAError("PROVIDER_RESPONSE_INVALID_JSON") from exc
    node_count = _count_json_nodes(value, max_depth=max_depth, depth=0)
    if node_count > max_nodes:
        raise SuperMprAError("PROVIDER_RESPONSE_JSON_TOO_WIDE")
    return value


def _count_json_nodes(value: Any, *, max_depth: int, depth: int) -> int:
    if depth > max_depth:
        raise SuperMprAError("PROVIDER_RESPONSE_JSON_TOO_DEEP")
    if isinstance(value, dict):
        count = 1
        for key, child in value.items():
            if not isinstance(key, str):
                raise SuperMprAError("PROVIDER_RESPONSE_NON_STRING_KEY")
            count += _count_json_nodes(child, max_depth=max_depth, depth=depth + 1)
        return count
    if isinstance(value, list):
        return 1 + sum(
            _count_json_nodes(item, max_depth=max_depth, depth=depth + 1)
            for item in value
        )
    if value is None or isinstance(value, (str, bool)):
        return 1
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise SuperMprAError("PROVIDER_RESPONSE_NON_FINITE_NUMBER")
        return 1
    raise SuperMprAError("PROVIDER_RESPONSE_UNSUPPORTED_JSON_VALUE")


def _hash_json(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise SuperMprAError(f"PROVIDER_FIELD_REQUIRED:{key}")
    return value


def _json_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SuperMprAError(f"PROVIDER_INTEGER_FIELD_REQUIRED:{key}")
    return value


def _provider_id(value: str) -> None:
    if not isinstance(value, str) or not _PROVIDER_NAME.fullmatch(value):
        raise SuperMprAError("BAD_PROVIDER_ID")


def _sha256(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise SuperMprAError(f"BAD_SHA256:{name}")


def _pubkeyish(value: str, name: str) -> None:
    if not isinstance(value, str) or not _PUBKEYISH.fullmatch(value):
        raise SuperMprAError(f"BAD_PUBKEY:{name}")


def _text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SuperMprAError(f"TEXT_REQUIRED:{name}")


def _positive_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SuperMprAError(f"POSITIVE_INTEGER_REQUIRED:{name}")


def _non_negative_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SuperMprAError(f"NON_NEGATIVE_INTEGER_REQUIRED:{name}")
