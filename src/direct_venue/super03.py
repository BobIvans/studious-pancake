"""SUPER-03 venue conformance and qualification-support contracts.

This module closes only repository-internal gaps that can be proven offline. It
does not perform RPC/HTTP calls, compile transactions, sign, submit, mutate
capital, or grant live authority. Existing MPR-2617, AGG-04 and AGG-05 owners
remain canonical.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Iterable, Mapping

from src.direct_venue.mpr2617 import (\n    CapabilityState,\n    DirectRouteLeg,\n    VenueCapability,\n    VenueFamily,\n)
from src.strategies.stable_peg.math import LiquidityBand, ceil_div, traverse_bands_exact


SUPER03_SCHEMA = "super-03.venue-conformance.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

_ALLOWED_VENUES = frozenset(
    {
        VenueFamily.RAYDIUM_CPMM,
        VenueFamily.RAYDIUM_CLMM,
        VenueFamily.METEORA_DLMM,
    }
)


class Super03Error(ValueError):
    """Malformed, incomplete, or unsafe SUPER-03 evidence."""


class ConformanceStatus(StrEnum):
    OFFLINE_VERIFIED = "offline-verified"
    BLOCKED_EXTERNAL = "blocked-external"


@dataclass(frozen=True, slots=True)
class UpstreamAdmission:
    repository: str
    commit: str
    symbol: str
    license_decision: str
    reuse_mode: str
    license_review_approved: bool

    def __post_init__(self) -> None:
        _text(self.repository, "repository")
        _git_sha(self.commit, "commit")
        _text(self.symbol, "symbol")
        _text(self.license_decision, "license_decision")
        if self.reuse_mode not in {"WRAP", "REFERENCE", "PORT+DIFF"}:
            raise Super03Error("unsupported reuse_mode")
        if not isinstance(self.license_review_approved, bool):
            raise Super03Error("license_review_approved must be bool")


@dataclass(frozen=True, slots=True)
class VenueIdentityEvidence:
    venue: VenueFamily
    program_id: str
    pool_or_market: str
    input_mint: str
    output_mint: str
    genesis_sha256: str
    deployment_generation: str
    account_layout_version: str
    state_generation: str
    state_sha256: str
    dependency_account_sha256: tuple[str, ...]
    deployment_verified: bool
    dependency_closure_complete: bool

    def __post_init__(self) -> None:
        if self.venue not in _ALLOWED_VENUES:
            raise Super03Error("SUPER-03 protocol proof only supports Raydium/Meteora")
        for field in ("program_id", "pool_or_market", "input_mint", "output_mint"):
            _pubkey(getattr(self, field), field)
        if self.input_mint == self.output_mint:
            raise Super03Error("input and output mint must differ")
        _sha256(self.genesis_sha256, "genesis_sha256")
        _sha256(self.state_sha256, "state_sha256")
        for field in (
            "deployment_generation",
            "account_layout_version",
            "state_generation",
        ):
            _text(getattr(self, field), field)
        if not self.dependency_account_sha256:
            raise Super03Error("dependency account evidence is required")
        if len(set(self.dependency_account_sha256)) != len(
            self.dependency_account_sha256
        ):
            raise Super03Error("dependency account digests must be unique")
        for digest in self.dependency_account_sha256:
            _sha256(digest, "dependency_account_sha256")
        if not isinstance(self.deployment_verified, bool):
            raise Super03Error("deployment_verified must be bool")
        if not isinstance(self.dependency_closure_complete, bool):
            raise Super03Error("dependency_closure_complete must be bool")


@dataclass(frozen=True, slots=True)
class InstructionConformance:
    instruction_data_sha256: str
    instruction_accounts_sha256: str
    reference_instruction_data_sha256: str
    reference_instruction_accounts_sha256: str
    unknown_signer_present: bool = False
    unknown_writable_present: bool = False

    def __post_init__(self) -> None:
        for field in (
            "instruction_data_sha256",
            "instruction_accounts_sha256",
            "reference_instruction_data_sha256",
            "reference_instruction_accounts_sha256",
        ):
            _sha256(getattr(self, field), field)
        if not isinstance(self.unknown_signer_present, bool):
            raise Super03Error("unknown_signer_present must be bool")
        if not isinstance(self.unknown_writable_present, bool):
            raise Super03Error("unknown_writable_present must be bool")

    @property
    def matches_reference(self) -> bool:
        return (
            self.instruction_data_sha256 == self.reference_instruction_data_sha256
            and self.instruction_accounts_sha256
            == self.reference_instruction_accounts_sha256
            and not self.unknown_signer_present
            and not self.unknown_writable_present
        )


@dataclass(frozen=True, slots=True)
class CpmmQuoteVector:
    amount_in: int
    reserve_in: int
    reserve_out: int
    trade_fee_numerator: int
    trade_fee_denominator: int
    input_transfer_fee: int
    output_transfer_fee: int
    reference_amount_out: int
    reference_trade_fee: int
    reference_vector_sha256: str

    def __post_init__(self) -> None:
        for field in (
            "amount_in",
            "reserve_in",
            "reserve_out",
            "trade_fee_denominator",
        ):
            _positive_int(getattr(self, field), field)
        for field in (
            "trade_fee_numerator",
            "input_transfer_fee",
            "output_transfer_fee",
            "reference_amount_out",
            "reference_trade_fee",
        ):
            _nonnegative_int(getattr(self, field), field)
        if self.trade_fee_numerator >= self.trade_fee_denominator:
            raise Super03Error("trade fee must be below denominator")
        if self.input_transfer_fee >= self.amount_in:
            raise Super03Error("input transfer fee consumes the whole input")
        _sha256(self.reference_vector_sha256, "reference_vector_sha256")

    def local_quote(self) -> tuple[int, int]:
        pool_input = self.amount_in - self.input_transfer_fee
        trade_fee = ceil_div(
            pool_input * self.trade_fee_numerator, self.trade_fee_denominator
        )
        swap_input = pool_input - trade_fee
        if swap_input <= 0:
            return 0, trade_fee
        gross_out = (swap_input * self.reserve_out) // (self.reserve_in + swap_input)
        if self.output_transfer_fee > gross_out:
            raise Super03Error("output transfer fee exceeds gross output")
        return gross_out - self.output_transfer_fee, trade_fee


@dataclass(frozen=True, slots=True)
class BandQuoteVector:
    amount_in: int
    bands: tuple[LiquidityBand, ...]
    fee_numerator: int
    fee_denominator: int
    reference_amount_out: int
    reference_fee: int
    reference_consumed_input: int
    reference_vector_sha256: str
    dynamic_fee_verified: bool
    arrays_complete: bool

    def __post_init__(self) -> None:
        _positive_int(self.amount_in, "amount_in")
        if not self.bands:
            raise Super03Error("at least one decoded tick/bin band is required")
        _nonnegative_int(self.fee_numerator, "fee_numerator")
        _positive_int(self.fee_denominator, "fee_denominator")
        if self.fee_numerator >= self.fee_denominator:
            raise Super03Error("fee must be below denominator")
        _nonnegative_int(self.reference_amount_out, "reference_amount_out")
        _nonnegative_int(self.reference_fee, "reference_fee")
        _nonnegative_int(self.reference_consumed_input, "reference_consumed_input")
        _sha256(self.reference_vector_sha256, "reference_vector_sha256")
        if not isinstance(self.dynamic_fee_verified, bool):
            raise Super03Error("dynamic_fee_verified must be bool")
        if not isinstance(self.arrays_complete, bool):
            raise Super03Error("arrays_complete must be bool")

    def local_quote(self) -> tuple[int, int, tuple[str, ...]]:
        return traverse_bands_exact(
            self.amount_in,
            self.bands,
            fee_numerator=self.fee_numerator,
            fee_denominator=self.fee_denominator,
        )


@dataclass(frozen=True, slots=True)
class VenueConformanceResult:
    status: ConformanceStatus
    blockers: tuple[str, ...]
    evidence_sha256: str
    amount_in: int
    guaranteed_min_out: int
    capability: VenueCapability | None
    live_enabled: bool = False


def qualify_cpmm_offline(
    *,
    upstream: UpstreamAdmission,
    identity: VenueIdentityEvidence,
    quote: CpmmQuoteVector,
    instruction: InstructionConformance,
    expires_at_unix: int,
) -> VenueConformanceResult:
    """Qualify a Raydium CPMM vector without claiming deployed/live readiness."""
    if identity.venue is not VenueFamily.RAYDIUM_CPMM:
        raise Super03Error("CPMM proof must use RAYDIUM_CPMM identity")
    local_out, local_fee = quote.local_quote()
    blockers = _common_blockers(upstream, identity, instruction)
    if (local_out, local_fee) != (
        quote.reference_amount_out,
        quote.reference_trade_fee,
    ):
        blockers.append("RAYDIUM_CPMM_REFERENCE_VECTOR_MISMATCH")
    return _finish(
        upstream=upstream,
        identity=identity,
        instruction=instruction,
        quote_payload={
            "model": "constant-product-exact-input",
            "amount_in": quote.amount_in,
            "local_amount_out": local_out,
            "local_trade_fee": local_fee,
            "reference_vector_sha256": quote.reference_vector_sha256,
        },
        blockers=blockers,
        amount_in=quote.amount_in,
        guaranteed_min_out=min(local_out, quote.reference_amount_out),
        expires_at_unix=expires_at_unix,
        quote_math_version="super03-cpmm-integer-v1",
        instruction_family="raydium-cpmm-swap-exact-in",
    )


def qualify_band_venue_offline(
    *,
    upstream: UpstreamAdmission,
    identity: VenueIdentityEvidence,
    quote: BandQuoteVector,
    instruction: InstructionConformance,
    expires_at_unix: int,
) -> VenueConformanceResult:
    """Qualify already-decoded CLMM/DLMM state against an independent vector."""
    if identity.venue not in {
        VenueFamily.RAYDIUM_CLMM,
        VenueFamily.METEORA_DLMM,
    }:
        raise Super03Error("band proof must use Raydium CLMM or Meteora DLMM")
    blockers = _common_blockers(upstream, identity, instruction)
    if not quote.arrays_complete:
        blockers.append("VENUE_TICK_BIN_ARRAY_CLOSURE_INCOMPLETE")
    if not quote.dynamic_fee_verified:
        blockers.append("VENUE_DYNAMIC_FEE_UNVERIFIED")
    if quote.reference_consumed_input != quote.amount_in:
        blockers.append("VENUE_PARTIAL_INPUT_CONSUMPTION")
    try:
        local_out, local_fee, used = quote.local_quote()
    except ValueError:
        local_out, local_fee, used = 0, 0, ()
        blockers.append("VENUE_LOCAL_BAND_COVERAGE_INSUFFICIENT")
    if (local_out, local_fee) != (quote.reference_amount_out, quote.reference_fee):
        blockers.append("VENUE_REFERENCE_VECTOR_MISMATCH")
    return _finish(
        upstream=upstream,
        identity=identity,
        instruction=instruction,
        quote_payload={
            "model": "decoded-band-exact-input",
            "amount_in": quote.amount_in,
            "local_amount_out": local_out,
            "local_fee": local_fee,
            "used_bands": list(used),
            "reference_vector_sha256": quote.reference_vector_sha256,
        },
        blockers=blockers,
        amount_in=quote.amount_in,
        guaranteed_min_out=min(local_out, quote.reference_amount_out),
        expires_at_unix=expires_at_unix,
        quote_math_version="super03-decoded-band-v1",
        instruction_family=(
            "raydium-clmm-swap-exact-in"
            if identity.venue is VenueFamily.RAYDIUM_CLMM
            else "meteora-dlmm-swap-exact-in"
        ),
    )


@dataclass(frozen=True, slots=True)
class SolverCacheKey:
    route_sha256: str
    amount_atomic: int
    state_generation: str
    adapter_revision: str
    policy_sha256: str

    def __post_init__(self) -> None:
        _sha256(self.route_sha256, "route_sha256")
        _positive_int(self.amount_atomic, "amount_atomic")
        _text(self.state_generation, "state_generation")
        _text(self.adapter_revision, "adapter_revision")
        _sha256(self.policy_sha256, "policy_sha256")

    @property
    def digest(self) -> str:
        return _digest(
            {
                "route_sha256": self.route_sha256,
                "amount_atomic": str(self.amount_atomic),
                "state_generation": self.state_generation,
                "adapter_revision": self.adapter_revision,
                "policy_sha256": self.policy_sha256,
            }
        )


@dataclass(frozen=True, slots=True)
class SolverCacheEntry:
    key: SolverCacheKey
    value_sha256: str
    negative: bool
    created_ns: int
    expires_ns: int | None

    def __post_init__(self) -> None:
        _sha256(self.value_sha256, "value_sha256")
        _nonnegative_int(self.created_ns, "created_ns")
        if self.expires_ns is not None:
            _positive_int(self.expires_ns, "expires_ns")
            if self.expires_ns <= self.created_ns:
                raise Super03Error("expires_ns must be after created_ns")
        if not isinstance(self.negative, bool):
            raise Super03Error("negative must be bool")


class GenerationBoundSolverCache:
    """Pure cache; canonical durable state remains with existing owners."""

    def __init__(self) -> None:
        self._entries: dict[str, SolverCacheEntry] = {}

    def put(
        self,
        key: SolverCacheKey,
        *,
        value_sha256: str,
        negative: bool,
        now_ns: int,
        negative_ttl_ns: int | None = None,
    ) -> SolverCacheEntry:
        _nonnegative_int(now_ns, "now_ns")
        if negative:
            if negative_ttl_ns is None:
                raise Super03Error("negative cache entries require a bounded TTL")
            _positive_int(negative_ttl_ns, "negative_ttl_ns")
            expires = now_ns + negative_ttl_ns
        else:
            expires = None
        entry = SolverCacheEntry(key, value_sha256, negative, now_ns, expires)
        self._entries[key.digest] = entry
        return entry

    def get(self, key: SolverCacheKey, *, now_ns: int) -> SolverCacheEntry | None:
        _nonnegative_int(now_ns, "now_ns")
        entry = self._entries.get(key.digest)
        if entry is None:
            return None
        if entry.expires_ns is not None and now_ns >= entry.expires_ns:
            self._entries.pop(key.digest, None)
            return None
        return entry

    def invalidate_state_generation(self, state_generation: str) -> int:
        _text(state_generation, "state_generation")
        doomed = [
            digest
            for digest, entry in self._entries.items()
            if entry.key.state_generation == state_generation
        ]
        for digest in doomed:
            self._entries.pop(digest, None)
        return len(doomed)


@dataclass(frozen=True, slots=True)
class BenchmarkObservation:
    case_id: str
    state_generation: str
    feasible: bool
    positive_net: bool
    exact_net_atomic: int | None
    provider_calls: int
    work_units: int

    def __post_init__(self) -> None:
        _text(self.case_id, "case_id")
        _text(self.state_generation, "state_generation")
        if not isinstance(self.feasible, bool) or not isinstance(self.positive_net, bool):
            raise Super03Error("benchmark booleans must be bool")
        if self.exact_net_atomic is not None and (
            isinstance(self.exact_net_atomic, bool)
            or not isinstance(self.exact_net_atomic, int)
        ):
            raise Super03Error("exact_net_atomic must be integer or null")
        _nonnegative_int(self.provider_calls, "provider_calls")
        _nonnegative_int(self.work_units, "work_units")
        if self.positive_net and (not self.feasible or self.exact_net_atomic is None):
            raise Super03Error("positive result requires feasible exact evidence")


@dataclass(frozen=True, slots=True)
class FixedWorkloadBenchmark:
    workload_sha256: str
    baseline_sha256: str
    challenger_sha256: str
    case_count: int
    baseline_feasible: int
    challenger_feasible: int
    baseline_positive: int
    challenger_positive: int
    baseline_provider_calls: int
    challenger_provider_calls: int
    baseline_work_units: int
    challenger_work_units: int


def build_fixed_workload_benchmark(
    baseline: Iterable[BenchmarkObservation],
    challenger: Iterable[BenchmarkObservation],
) -> FixedWorkloadBenchmark:
    """Compare solvers only when they saw the exact same case/state workload."""
    left = tuple(sorted(tuple(baseline), key=lambda item: item.case_id))
    right = tuple(sorted(tuple(challenger), key=lambda item: item.case_id))
    left_ids = tuple((item.case_id, item.state_generation) for item in left)
    right_ids = tuple((item.case_id, item.state_generation) for item in right)
    if not left or left_ids != right_ids:
        raise Super03Error("benchmark requires identical non-empty workload")
    if len(set(left_ids)) != len(left_ids):
        raise Super03Error("benchmark workload contains duplicate cases")
    workload_sha = _digest(list(left_ids))

    def summarize(rows: tuple[BenchmarkObservation, ...]) -> Mapping[str, int]:
        return {
            "feasible": sum(item.feasible for item in rows),
            "positive": sum(item.positive_net for item in rows),
            "provider_calls": sum(item.provider_calls for item in rows),
            "work_units": sum(item.work_units for item in rows),
        }

    lsum = summarize(left)
    rsum = summarize(right)
    return FixedWorkloadBenchmark(
        workload_sha256=workload_sha,
        baseline_sha256=_digest([_benchmark_row(item) for item in left]),
        challenger_sha256=_digest([_benchmark_row(item) for item in right]),
        case_count=len(left),
        baseline_feasible=lsum["feasible"],
        challenger_feasible=rsum["feasible"],
        baseline_positive=lsum["positive"],
        challenger_positive=rsum["positive"],
        baseline_provider_calls=lsum["provider_calls"],
        challenger_provider_calls=rsum["provider_calls"],
        baseline_work_units=lsum["work_units"],
        challenger_work_units=rsum["work_units"],
    )


def _common_blockers(
    upstream: UpstreamAdmission,
    identity: VenueIdentityEvidence,
    instruction: InstructionConformance,
) -> list[str]:
    blockers: list[str] = []
    if not upstream.license_review_approved:
        blockers.append("UPSTREAM_LICENSE_REUSE_NOT_APPROVED")
    if not identity.deployment_verified:
        blockers.append("DEPLOYMENT_IDENTITY_NOT_VERIFIED")
    if not identity.dependency_closure_complete:
        blockers.append("STATE_DEPENDENCY_CLOSURE_INCOMPLETE")
    if not instruction.matches_reference:
        blockers.append("INSTRUCTION_REFERENCE_MISMATCH")
    return blockers


def _finish(
    *,
    upstream: UpstreamAdmission,
    identity: VenueIdentityEvidence,
    instruction: InstructionConformance,
    quote_payload: Mapping[str, object],
    blockers: list[str],
    amount_in: int,
    guaranteed_min_out: int,
    expires_at_unix: int,
    quote_math_version: str,
    instruction_family: str,
) -> VenueConformanceResult:
    _positive_int(amount_in, "amount_in")
    _nonnegative_int(guaranteed_min_out, "guaranteed_min_out")
    _positive_int(expires_at_unix, "expires_at_unix")
    unique = tuple(dict.fromkeys(blockers))
    payload = {
        "schema": SUPER03_SCHEMA,
        "venue": identity.venue.value,
        "upstream": {
            "repository": upstream.repository,
            "commit": upstream.commit,
            "symbol": upstream.symbol,
            "license_decision": upstream.license_decision,
            "reuse_mode": upstream.reuse_mode,
        },
        "identity": {
            "program_id": identity.program_id,
            "pool_or_market": identity.pool_or_market,
            "input_mint": identity.input_mint,
            "output_mint": identity.output_mint,
            "genesis_sha256": identity.genesis_sha256,
            "deployment_generation": identity.deployment_generation,
            "account_layout_version": identity.account_layout_version,
            "state_generation": identity.state_generation,
            "state_sha256": identity.state_sha256,
            "dependency_account_sha256": list(identity.dependency_account_sha256),
        },
        "quote": dict(quote_payload),
        "instruction": {
            "data": instruction.instruction_data_sha256,
            "accounts": instruction.instruction_accounts_sha256,
        },
    }
    evidence_sha = _digest(payload)
    if unique:
        return VenueConformanceResult(
            ConformanceStatus.BLOCKED_EXTERNAL,
            unique,
            evidence_sha,
            amount_in,
            guaranteed_min_out,
            None,
            False,
        )
    capability = VenueCapability(
        capability_id=(
            f"super03:{identity.venue.value}:{identity.pool_or_market}:"
            f"{identity.input_mint}->{identity.output_mint}"
        ),
        venue=identity.venue,
        cluster="mainnet-beta",
        genesis_sha256=identity.genesis_sha256,
        pool_or_market=identity.pool_or_market,
        input_mint=identity.input_mint,
        output_mint=identity.output_mint,
        deployment_generation=identity.deployment_generation,
        account_layout_version=identity.account_layout_version,
        instruction_family=instruction_family,
        quote_math_version=(
            f"{quote_math_version}:amount={amount_in}:evidence={evidence_sha[:16]}"
        ),
        evidence_sha256=evidence_sha,
        instruction_data_sha256=instruction.instruction_data_sha256,
        instruction_accounts_sha256=instruction.instruction_accounts_sha256,
        state=CapabilityState.OFFLINE_VERIFIED,
        expires_at_unix=expires_at_unix,
    )
    return VenueConformanceResult(
        ConformanceStatus.OFFLINE_VERIFIED,
        (),
        evidence_sha,
        amount_in,
        guaranteed_min_out,
        capability,
        False,
    )


def build_amount_bound_leg(result: VenueConformanceResult) -> DirectRouteLeg:
    """Build the only supported MPR-2617 leg from one exact conformance vector."""
    if (
        result.status is not ConformanceStatus.OFFLINE_VERIFIED
        or result.capability is None
    ):
        raise Super03Error("blocked conformance result cannot build a route leg")
    if result.guaranteed_min_out <= 0:
        raise Super03Error("amount-bound route leg requires positive guaranteed output")
    capability = result.capability
    return DirectRouteLeg(
        venue=capability.venue,
        capability_hash=capability.capability_hash,
        pool_or_market=capability.pool_or_market,
        input_mint=capability.input_mint,
        output_mint=capability.output_mint,
        amount_in=result.amount_in,
        guaranteed_min_out=result.guaranteed_min_out,
        evidence_generation=capability.deployment_generation,
        instruction_data_sha256=capability.instruction_data_sha256,
        instruction_accounts_sha256=capability.instruction_accounts_sha256,
    )


def _benchmark_row(item: BenchmarkObservation) -> Mapping[str, object]:
    return {
        "case_id": item.case_id,
        "state_generation": item.state_generation,
        "feasible": item.feasible,
        "positive_net": item.positive_net,
        "exact_net_atomic": item.exact_net_atomic,
        "provider_calls": item.provider_calls,
        "work_units": item.work_units,
    }


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _text(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise Super03Error(f"{field} is required")


def _sha256(value: object, field: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise Super03Error(f"{field} must be lowercase sha256")


def _git_sha(value: object, field: str) -> None:
    if not isinstance(value, str) or _GIT_SHA.fullmatch(value) is None:
        raise Super03Error(f"{field} must be 40-char git sha")


def _pubkey(value: object, field: str) -> None:
    if not isinstance(value, str) or _B58.fullmatch(value) is None:
        raise Super03Error(f"{field} must be a base58 public key")


def _positive_int(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise Super03Error(f"{field} must be a positive integer")


def _nonnegative_int(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise Super03Error(f"{field} must be a non-negative integer")


__all__ = [
    "BandQuoteVector",
    "BenchmarkObservation",
    "ConformanceStatus",
    "CpmmQuoteVector",
    "FixedWorkloadBenchmark",
    "GenerationBoundSolverCache",
    "InstructionConformance",
    "SolverCacheEntry",
    "SolverCacheKey",
    "Super03Error",
    "UpstreamAdmission",
    "VenueConformanceResult",
    "VenueIdentityEvidence",
    "build_amount_bound_leg",
    "build_fixed_workload_benchmark",
    "qualify_band_venue_offline",
    "qualify_cpmm_offline",
]
