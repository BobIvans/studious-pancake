"""Exact sender-free evidence models for MPR-2622 stable-peg qualification."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
from typing import Any, Iterable

U64_MAX = (1 << 64) - 1

class StablePegError(ValueError):
    pass

class CandidateClass(StrEnum):
    NO_TRADE = "NO_TRADE"
    CANDIDATE = "CANDIDATE"
    BLOCKED = "BLOCKED"
    RECORDED_OFFLINE = "RECORDED_OFFLINE"

class Reason(StrEnum):
    ASSET_UNQUALIFIED = "MPR2622_ASSET_UNQUALIFIED"
    REFERENCE_STALE = "MPR2622_REFERENCE_STALE"
    REFERENCE_CONFIDENCE_WIDE = "MPR2622_REFERENCE_CONFIDENCE_WIDE"
    REFERENCE_DISAGREEMENT = "MPR2622_REFERENCE_DISAGREEMENT"
    POOL_IDENTITY_UNVERIFIED = "MPR2622_POOL_IDENTITY_UNVERIFIED"
    POOL_STATE_STALE = "MPR2622_POOL_STATE_STALE"
    TICK_ARRAY_MISSING = "MPR2622_TICK_ARRAY_MISSING"
    BIN_ARRAY_MISSING = "MPR2622_BIN_ARRAY_MISSING"
    DYNAMIC_FEE_UNKNOWN = "MPR2622_DYNAMIC_FEE_UNKNOWN"
    TOKEN_PROGRAM_UNSUPPORTED = "MPR2622_TOKEN_PROGRAM_UNSUPPORTED"
    AMOUNT_COUPLING_BROKEN = "MPR2622_AMOUNT_COUPLING_BROKEN"
    STATE_DRIFT = "MPR2622_STATE_DRIFT"
    MESSAGE_LIMIT_EXCEEDED = "MPR2622_MESSAGE_LIMIT_EXCEEDED"
    CU_LIMIT_EXCEEDED = "MPR2622_CU_LIMIT_EXCEEDED"
    EXACT_SIMULATION_FAILED = "MPR2622_EXACT_SIMULATION_FAILED"
    ECONOMICS_NON_POSITIVE = "MPR2622_ECONOMICS_NON_POSITIVE"
    MULTI_ASSET_UNVALUED = "MPR2622_MULTI_ASSET_UNVALUED"
    EXTERNAL_CONTRACT_BLOCKED = "MPR2622_EXTERNAL_CONTRACT_BLOCKED"
    INTEGRATION_BLOCKED = "MPR2622_INTEGRATION_BLOCKED"


def strict_int(value: object, *, field: str, minimum: int = 0, maximum: int = U64_MAX) -> int:
    if type(value) is not int:
        raise StablePegError(f"{field} must be a non-bool integer")
    if not minimum <= value <= maximum:
        raise StablePegError(f"{field} out of bounds")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StablePegError(f"{field} must be non-empty text")
    return value


def canonical_digest(domain: str, payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(domain.encode() + b"\0" + raw).hexdigest()

@dataclass(frozen=True, slots=True)
class StableAssetEvidence:
    mint: str
    token_program: str
    decimals: int
    asset_class: str
    registry_generation: str
    admission_digest: str
    authority_policy: str
    identity_source: str
    executable_allowed: bool

    def __post_init__(self) -> None:
        for field in ("mint", "token_program", "asset_class", "registry_generation", "admission_digest", "authority_policy", "identity_source"):
            _text(getattr(self, field), field)
        strict_int(self.decimals, field="decimals", maximum=255)
        if type(self.executable_allowed) is not bool:
            raise StablePegError("executable_allowed must be bool")

@dataclass(frozen=True, slots=True)
class PegReferenceEvidence:
    source_id: str
    feed_id: str
    source_generation: str
    publish_time_ns: int
    rooted_slot: int
    price: int
    exponent: int
    confidence: int
    fresh: bool
    confidence_ok: bool
    reference_digest: str

    def __post_init__(self) -> None:
        for field in ("source_id", "feed_id", "source_generation", "reference_digest"):
            _text(getattr(self, field), field)
        strict_int(self.publish_time_ns, field="publish_time_ns")
        strict_int(self.rooted_slot, field="rooted_slot")
        strict_int(self.confidence, field="confidence")
        if type(self.price) is not int or type(self.exponent) is not int:
            raise StablePegError("price/exponent must be integer")
        if type(self.fresh) is not bool or type(self.confidence_ok) is not bool:
            raise StablePegError("reference verdicts must be bool")

@dataclass(frozen=True, slots=True)
class PoolStateEvidence:
    venue: str
    program_id: str
    pool_id: str
    token_mints: tuple[str, str]
    token_programs: tuple[str, str]
    vaults: tuple[str, str]
    rooted_slot: int
    fork_digest: str
    raw_account_digests: tuple[str, ...]
    schema_generation: str
    fee_numerator: int
    fee_denominator: int
    state_digest: str
    curve: str
    sqrt_price_x64: int | None = None
    tick_current: int | None = None
    active_liquidity: int | None = None
    tick_spacing: int | None = None
    tick_array_digests: tuple[str, ...] = ()
    active_bin: int | None = None
    bin_step: int | None = None
    bin_array_digests: tuple[str, ...] = ()
    dynamic_fee_numerator: int | None = None

    def __post_init__(self) -> None:
        for field in ("venue", "program_id", "pool_id", "fork_digest", "schema_generation", "state_digest", "curve"):
            _text(getattr(self, field), field)
        if len(self.token_mints) != 2 or len(self.token_programs) != 2 or len(self.vaults) != 2:
            raise StablePegError("pool token/vault identities must be pairs")
        strict_int(self.rooted_slot, field="rooted_slot")
        strict_int(self.fee_numerator, field="fee_numerator")
        strict_int(self.fee_denominator, field="fee_denominator", minimum=1)
        if self.dynamic_fee_numerator is not None:
            strict_int(self.dynamic_fee_numerator, field="dynamic_fee_numerator")
        if self.curve == "CLMM":
            for field in ("sqrt_price_x64", "active_liquidity", "tick_spacing"):
                value = getattr(self, field)
                if value is None:
                    raise StablePegError(f"CLMM requires {field}")
                strict_int(value, field=field, minimum=1)
            if type(self.tick_current) is not int:
                raise StablePegError("CLMM requires integer tick_current")
            if not self.tick_array_digests:
                raise StablePegError(Reason.TICK_ARRAY_MISSING)
        elif self.curve == "DLMM":
            if type(self.active_bin) is not int:
                raise StablePegError("DLMM requires active_bin")
            if self.bin_step is None:
                raise StablePegError("DLMM requires bin_step")
            strict_int(self.bin_step, field="bin_step", minimum=1)
            if not self.bin_array_digests:
                raise StablePegError(Reason.BIN_ARRAY_MISSING)
        else:
            raise StablePegError("curve must be CLMM or DLMM")

@dataclass(frozen=True, slots=True)
class ExecutableLegQuote:
    venue: str
    input_mint: str
    output_mint: str
    amount_in: int
    guaranteed_out: int
    fee: int
    pool_state_digest: str
    account_set_digest: str
    instruction_semantic_digest: str
    expiry_slot: int
    source_label: str

    def __post_init__(self) -> None:
        for field in ("venue", "input_mint", "output_mint", "pool_state_digest", "account_set_digest", "instruction_semantic_digest", "source_label"):
            _text(getattr(self, field), field)
        strict_int(self.amount_in, field="amount_in", minimum=1)
        strict_int(self.guaranteed_out, field="guaranteed_out")
        strict_int(self.fee, field="fee")
        strict_int(self.expiry_slot, field="expiry_slot")

@dataclass(frozen=True, slots=True)
class StablePegCandidate:
    principal_mint: str
    repayment_mint: str
    legs: tuple[ExecutableLegQuote, ...]
    asset_admission_digests: tuple[str, ...]
    reference_digests: tuple[str, ...]
    pool_state_digests: tuple[str, ...]
    conservative_surplus: int
    blockers: tuple[str, ...]
    classification: CandidateClass
    candidate_hash: str


def make_candidate(*, principal_mint: str, repayment_mint: str, legs: Iterable[ExecutableLegQuote], asset_digests: Iterable[str], reference_digests: Iterable[str], pool_digests: Iterable[str], conservative_surplus: int, blockers: Iterable[str] = (), recorded_offline: bool = False) -> StablePegCandidate:
    legs_t = tuple(legs)
    blockers_t = tuple(sorted(set(blockers)))
    if not legs_t:
        raise StablePegError("candidate requires at least one leg")
    for previous, following in zip(legs_t, legs_t[1:]):
        if previous.output_mint != following.input_mint or previous.guaranteed_out != following.amount_in:
            blockers_t += (Reason.AMOUNT_COUPLING_BROKEN,)
    if legs_t[0].input_mint != principal_mint or legs_t[-1].output_mint != repayment_mint:
        blockers_t += (Reason.AMOUNT_COUPLING_BROKEN,)
    strict_int(conservative_surplus, field="conservative_surplus")
    if blockers_t:
        classification = CandidateClass.BLOCKED
    elif conservative_surplus <= 0:
        classification = CandidateClass.NO_TRADE
        blockers_t = (Reason.ECONOMICS_NON_POSITIVE,)
    elif recorded_offline:
        classification = CandidateClass.RECORDED_OFFLINE
    else:
        classification = CandidateClass.CANDIDATE
    payload = {
        "principal_mint": principal_mint,
        "repayment_mint": repayment_mint,
        "legs": [asdict(leg) for leg in legs_t],
        "asset_digests": tuple(asset_digests),
        "reference_digests": tuple(reference_digests),
        "pool_digests": tuple(pool_digests),
        "surplus": conservative_surplus,
        "blockers": blockers_t,
        "classification": classification,
    }
    return StablePegCandidate(principal_mint, repayment_mint, legs_t, tuple(payload["asset_digests"]), tuple(payload["reference_digests"]), tuple(payload["pool_digests"]), conservative_surplus, blockers_t, classification, canonical_digest("mpr2622.candidate.v1", payload))
