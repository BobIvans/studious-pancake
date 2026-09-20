"""AGG-06 sender-free Solana venue/arbitrage qualification seam."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from hashlib import sha256
import json
from typing import Mapping, Sequence

from src.mpr2621_lst_atomic_exit import (
    Decision as LstDecision,
    LstAtomicExitCandidate,
    QualificationResult as LstResult,
    qualify_candidate as qualify_lst_existing,
)
from src.providers.orderbook.models import (
    DepthQuote,
    OrderbookMarketSnapshot,
    OrderbookReject,
    TradeDirection,
)
from src.providers.orderbook.quote import OrderbookQuoteEngine
from src.strategies.stable_peg.math import LiquidityBand, ceil_div, traverse_bands_exact

SCHEMA = "agg06.solana-venue-expansion.v1"
PPM = 1_000_000
BPS = 10_000
NF_IDS = (
    "NF-070",
    "NF-073",
    "NF-117",
    "NF-119",
    "NF-120",
    "NF-121",
    "NF-122",
    "NF-138",
    "NF-139",
    "NF-140",
    "NF-141",
    "NF-142",
    "NF-143",
    "NF-151",
    "NF-153",
)
NF_FUNCTIONS = (
    "validate_clob_window",
    "qualify_redemption",
    "quote_clmm",
    "qualify_lifecycle",
    "quote_clob",
    "qualify_lst_conversion",
    "qualify_basket",
    "qualify_clob_amm",
    "qualify_lst_nav",
    "quote_dynamic_fee",
    "qualify_time_fee",
    "qualify_post_swap",
    "qualify_migration",
    "qualify_lp_parity",
    "apply_token2022_fee",
)


class Agg06Error(ValueError):
    def __init__(self, code: str, message: str, *, stage: str) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage


class Family(StrEnum):
    RAYDIUM_CLMM = "raydium-clmm"
    ORCA = "orca-whirlpool"
    PHOENIX = "phoenix"
    OPENBOOK = "openbook-v2"
    LST = "lst"
    DLMM = "meteora-dlmm"
    DAMM = "meteora-damm"
    DBC = "meteora-dbc"
    PUMP = "pump"


class Level(StrEnum):
    RESEARCH = "RESEARCH"
    OFFLINE_VERIFIED = "OFFLINE_VERIFIED"
    RECORDED_OFFLINE = "RECORDED_OFFLINE"


class Stage(StrEnum):
    TRADING = "TRADING"
    MIGRATING = "MIGRATING"
    GRADUATED = "GRADUATED"
    CLOSED = "CLOSED"


@dataclass(frozen=True, slots=True)
class Evidence:
    generation: str
    state_hash: str
    observed_at: int
    expires_at: int
    vector_hash: str | None = None
    license_decision: str | None = None

    def check(self, now: int) -> None:
        _text(self.generation, "generation")
        _hash(self.state_hash, "state_hash")
        if self.vector_hash is not None:
            _hash(self.vector_hash, "vector_hash")
        _uint(self.observed_at, "observed_at")
        _pos(self.expires_at, "expires_at")
        _uint(now, "now")
        if self.expires_at <= self.observed_at or now >= self.expires_at:
            raise Agg06Error("EVIDENCE_STALE", "evidence is stale", stage="evidence")


@dataclass(frozen=True, slots=True)
class Quote:
    amount_in: int
    amount_out: int
    fee: int
    transfer_fee: int
    touched: tuple[str, ...]
    state_hash: str
    level: Level
    blockers: tuple[str, ...] = ()
    live_enabled: bool = False


@dataclass(frozen=True, slots=True)
class Verdict:
    accepted: bool
    blockers: tuple[str, ...]
    level: Level
    value: int | Fraction | str | None = None
    live_enabled: bool = False


@dataclass(frozen=True, slots=True)
class Token2022:
    fee_bps: int = 0
    max_fee: int = 0
    unsupported_hooks: tuple[str, ...] = ()
    default_frozen: bool = False


@dataclass(frozen=True, slots=True)
class ClobQuote:
    quote: DepthQuote
    residual_input: int
    reference_match: bool
    level: Level
    live_enabled: bool = False


def validate_clob_window(
    previous: int | None,
    current: int,
    *,
    snapshot_complete: bool,
    l3_available: bool,
) -> Verdict:
    """NF-070: gaps require resync; L2 never invents L3 queue state."""
    _uint(current, "current")
    blockers: list[str] = []
    if previous is not None:
        _uint(previous, "previous")
        if current != previous + 1:
            blockers.append("CLOB_SEQUENCE_GAP_REQUIRES_RESYNC")
    if not snapshot_complete:
        blockers.append("CLOB_PARTIAL_SNAPSHOT")
    value = "L3" if l3_available else "L2_ONLY"
    return Verdict(not blockers, tuple(blockers), Level.RECORDED_OFFLINE, value)


def apply_token2022_fee(amount: int, policy: Token2022) -> tuple[int, int]:
    """NF-153: conservative exact transfer-fee application."""
    _uint(amount, "amount")
    _uint(policy.fee_bps, "fee_bps")
    _uint(policy.max_fee, "max_fee")
    if policy.fee_bps >= BPS:
        raise Agg06Error("TOKEN2022_FEE_INVALID", "fee out of range", stage="token2022")
    if policy.unsupported_hooks:
        raise Agg06Error(
            "TOKEN2022_UNSUPPORTED_HOOK",
            "unknown hook",
            stage="token2022",
        )
    if policy.default_frozen:
        raise Agg06Error(
            "TOKEN2022_DEFAULT_FROZEN",
            "frozen by default",
            stage="token2022",
        )
    if amount == 0 or policy.fee_bps == 0:
        return amount, 0
    fee = ceil_div(amount * policy.fee_bps, BPS)
    if policy.max_fee:
        fee = min(fee, policy.max_fee)
    fee = min(fee, amount)
    return amount - fee, fee


def quote_clmm(
    family: Family,
    bands: Sequence[tuple[str, LiquidityBand]],
    *,
    required_arrays: Sequence[str],
    loaded_arrays: Sequence[str],
    fee_ppm: int,
    evidence: Evidence,
    amount_in: int,
    now: int,
    reference_out: int | None = None,
    token2022: Token2022 = Token2022(),
) -> Quote:
    """NF-117: exact caller-decoded CLMM tick-array traversal."""
    _pos(amount_in, "amount_in")
    evidence.check(now)
    if family not in {Family.RAYDIUM_CLMM, Family.ORCA}:
        raise Agg06Error("CLMM_FAMILY_INVALID", "not CLMM", stage="clmm")
    if family is Family.ORCA and evidence.license_decision != "APPROVED":
        raise Agg06Error("ORCA_LICENSE_BLOCKED", "license not approved", stage="clmm")
    missing = set(required_arrays) - set(loaded_arrays)
    if missing:
        raise Agg06Error("CLMM_TICK_ARRAY_MISSING", repr(sorted(missing)), stage="clmm")
    if not bands:
        raise Agg06Error("CLMM_BANDS_EMPTY", "decoded bands required", stage="clmm")
    order = {name: index for index, name in enumerate(loaded_arrays)}
    last = -1
    decoded: list[LiquidityBand] = []
    arrays_by_digest: dict[str, str] = {}
    for array, band in bands:
        if array not in order or order[array] < last:
            raise Agg06Error("CLMM_ARRAY_ORDER_INVALID", array, stage="clmm")
        last = order[array]
        decoded.append(band)
        arrays_by_digest[band.digest] = array
    try:
        gross, fee, touched = traverse_bands_exact(
            amount_in,
            tuple(decoded),
            fee_numerator=fee_ppm,
            fee_denominator=PPM,
        )
    except Exception as exc:
        raise Agg06Error("CLMM_COVERAGE_INSUFFICIENT", str(exc), stage="clmm") from exc
    out, transfer_fee = apply_token2022_fee(gross, token2022)
    blockers = () if reference_out == out else ("CLMM_INDEPENDENT_VECTOR_REQUIRED",)
    level = (
        Level.OFFLINE_VERIFIED
        if not blockers and evidence.vector_hash
        else Level.RESEARCH
    )
    touched_arrays = tuple(arrays_by_digest[item] for item in touched)
    state_hash = _digest((family, evidence.state_hash, amount_in, touched_arrays))
    return Quote(
        amount_in,
        out,
        fee,
        transfer_fee,
        touched_arrays,
        state_hash,
        level,
        blockers,
    )


def quote_clob(
    snapshot: OrderbookMarketSnapshot,
    direction: TradeDirection,
    amount: int,
    *,
    account_ready: bool,
    settlement_ready: bool,
    reference_min_out: int | None = None,
    max_slot_skew: int = 0,
) -> ClobQuote:
    """NF-120: reuse exact integer-lot CLOB quote authority."""
    if not account_ready:
        raise Agg06Error("CLOB_ACCOUNT_NOT_READY", "account not ready", stage="clob")
    if not settlement_ready:
        raise Agg06Error(
            "CLOB_SETTLEMENT_UNPROVEN",
            "settlement unproven",
            stage="clob",
        )
    try:
        quote = OrderbookQuoteEngine().quote(
            snapshot,
            direction,
            amount,
            max_slot_skew=max_slot_skew,
        )
    except OrderbookReject as exc:
        raise Agg06Error(exc.code.value, str(exc), stage="clob") from exc
    residual = amount - quote.max_in
    if residual < 0:
        raise Agg06Error("CLOB_INPUT_INCREASED", "invalid quote", stage="clob")
    match = reference_min_out is not None and reference_min_out == quote.min_out
    level = Level.OFFLINE_VERIFIED if match else Level.RESEARCH
    return ClobQuote(quote, residual, match, level)


def qualify_clob_amm(
    clob: ClobQuote,
    *,
    terminal_out: int,
    repayment: int,
    independent_costs: int,
    same_message: bool,
    settlement_proven: bool,
    repayment_asset_matches: bool,
) -> Verdict:
    """NF-138: conservative CLOB↔AMM atomic admission."""
    _pos(terminal_out, "terminal_out")
    _pos(repayment, "repayment")
    _uint(independent_costs, "independent_costs")
    blockers: list[str] = []
    if not same_message:
        blockers.append("CLOB_AMM_NOT_ATOMIC")
    if not settlement_proven:
        blockers.append("CLOB_SETTLEMENT_UNPROVEN")
    if not repayment_asset_matches:
        blockers.append("CLOB_AMM_REPAYMENT_ASSET_MISMATCH")
    if not clob.reference_match:
        blockers.append("CLOB_REFERENCE_VECTOR_REQUIRED")
    net = terminal_out - repayment - independent_costs
    if net <= 0:
        blockers.append("CLOB_AMM_NONPOSITIVE_NET")
    level = Level.OFFLINE_VERIFIED if not blockers else Level.RESEARCH
    return Verdict(not blockers, tuple(blockers), level, net)


def qualify_redemption(
    *,
    immediate: bool,
    permissioned: bool,
    capacity: int,
    fee: int,
    paused: bool,
    evidence: Evidence,
    amount: int,
    now: int,
) -> Verdict:
    """NF-073: delayed/queued NAV is never atomic repayment liquidity."""
    _pos(amount, "amount")
    evidence.check(now)
    _uint(capacity, "capacity")
    _uint(fee, "fee")
    blockers: list[str] = []
    if paused:
        blockers.append("REDEMPTION_PAUSED")
    if not immediate:
        blockers.append("REDEMPTION_NOT_IMMEDIATE")
    if permissioned:
        blockers.append("REDEMPTION_PERMISSION_REQUIRED")
    if max(capacity - fee, 0) < amount:
        blockers.append("REDEMPTION_CAPACITY_INSUFFICIENT")
    return Verdict(not blockers, tuple(blockers), Level.OFFLINE_VERIFIED)


def qualify_lst_conversion(
    candidate: LstAtomicExitCandidate,
    redemption: Verdict,
) -> LstResult:
    """NF-121: bind MPR-2621 to fresh immediate-exit capacity."""
    result = qualify_lst_existing(candidate)
    if redemption.accepted:
        return result
    return LstResult(
        decision=LstDecision.BLOCKED,
        blockers=tuple(dict.fromkeys((*result.blockers, *redemption.blockers))),
        capability_id=result.capability_id,
        candidate_id=result.candidate_id,
        nav_lamports_per_lst_atomic_num=result.nav_lamports_per_lst_atomic_num,
        nav_lamports_per_lst_atomic_den=result.nav_lamports_per_lst_atomic_den,
        guaranteed_surplus_lamports=result.guaranteed_surplus_lamports,
        sender_allowed=False,
        signer_allowed=False,
        live_enabled=False,
        canary_eligible=False,
    )


def qualify_lst_nav(
    candidate: LstAtomicExitCandidate, redemption: Verdict
) -> LstResult:
    """NF-139: strategy alias preserving the MPR-2621 authority."""
    return qualify_lst_conversion(candidate, redemption)


def qualify_basket(
    *,
    input_units: int,
    input_num: int,
    input_den: int,
    output_units: int,
    output_num: int,
    output_den: int,
    fee_units: int,
    immediate: bool,
    complete: bool,
    evidence: Evidence,
    now: int,
) -> Verdict:
    """NF-122: immediate wrapper/basket right with exact rational value."""
    evidence.check(now)
    values = (input_units, input_num, input_den, output_units, output_num, output_den)
    for value in values:
        _pos(value, "basket_value")
    _uint(fee_units, "fee_units")
    blockers: list[str] = []
    if not immediate:
        blockers.append("BASKET_NOT_IMMEDIATE")
    if not complete:
        blockers.append("BASKET_COMPONENTS_INCOMPLETE")
    incoming = Fraction(input_units * input_num, input_den)
    outgoing = Fraction(output_units * output_num, output_den)
    delta = outgoing - fee_units - incoming
    level = Level.OFFLINE_VERIFIED if not blockers else Level.RESEARCH
    return Verdict(not blockers, tuple(blockers), level, delta)


def qualify_lp_parity(**kwargs: object) -> Verdict:
    """NF-151: LP/basket parity reuses the rights-aware proof."""
    return qualify_basket(**kwargs)  # type: ignore[arg-type]


def quote_dynamic_fee(
    *,
    base_fee_ppm: int,
    variable_fee_ppm: int,
    valid_until: int,
    evidence: Evidence,
    amount: int,
    bands: tuple[LiquidityBand, ...],
    now: int,
    token2022: Token2022 = Token2022(),
) -> Quote:
    """NF-140: DLMM dynamic-fee/bin signal on a controlled clock."""
    _pos(amount, "amount")
    evidence.check(now)
    if now > valid_until:
        raise Agg06Error("DLMM_FEE_CLOCK_STALE", "fee clock stale", stage="dlmm")
    fee_ppm = base_fee_ppm + variable_fee_ppm
    _uint(fee_ppm, "fee_ppm")
    if fee_ppm >= PPM:
        raise Agg06Error("DLMM_FEE_INVALID", "fee out of range", stage="dlmm")
    try:
        gross, fee, touched = traverse_bands_exact(
            amount,
            bands,
            fee_numerator=fee_ppm,
            fee_denominator=PPM,
        )
    except Exception as exc:
        raise Agg06Error(
            "DLMM_BIN_COVERAGE_INSUFFICIENT",
            str(exc),
            stage="dlmm",
        ) from exc
    out, transfer_fee = apply_token2022_fee(gross, token2022)
    level = Level.OFFLINE_VERIFIED if evidence.vector_hash else Level.RESEARCH
    return Quote(amount, out, fee, transfer_fee, touched, evidence.state_hash, level)


def qualify_time_fee(
    first: Quote,
    later: Quote,
    *,
    elapsed_seconds: int,
    loan_held_across_wait: bool,
) -> Verdict:
    """NF-141: time-fee crossing never authorizes holding a flashloan."""
    _pos(elapsed_seconds, "elapsed_seconds")
    blockers: list[str] = []
    if loan_held_across_wait:
        blockers.append("FLASH_LIQUIDITY_CANNOT_BE_HELD_ACROSS_TIME")
    if first.amount_in != later.amount_in:
        blockers.append("TIME_FEE_AMOUNT_MISMATCH")
    delta = later.amount_out - first.amount_out
    if delta <= 0:
        blockers.append("TIME_FEE_NO_POSITIVE_CROSSING")
    return Verdict(not blockers, tuple(blockers), Level.RECORDED_OFFLINE, delta)


def qualify_lifecycle(
    *,
    stage: Stage,
    fee_ppm: int,
    evidence: Evidence,
    now: int,
) -> Verdict:
    """NF-119: DAMM/DBC/Pump lifecycle admission."""
    evidence.check(now)
    _uint(fee_ppm, "fee_ppm")
    blockers: list[str] = []
    if stage is not Stage.TRADING:
        blockers.append(f"VENUE_STAGE_NOT_TRADING:{stage.value}")
    if fee_ppm >= PPM:
        blockers.append("VENUE_FEE_INVALID")
    return Verdict(not blockers, tuple(blockers), Level.OFFLINE_VERIFIED)


def qualify_migration(
    *,
    event_id: str,
    seen_event_ids: frozenset[str],
    old_generation: str,
    new_generation: str,
    finalized: bool,
    old_stage: Stage,
    new_stage: Stage,
    evidence: Evidence,
    now: int,
) -> Verdict:
    """NF-143: exactly one canonical market state after migration."""
    evidence.check(now)
    blockers: list[str] = []
    if event_id in seen_event_ids:
        blockers.append("MIGRATION_DUPLICATE")
    if not finalized:
        blockers.append("MIGRATION_NOT_FINALIZED")
    if old_generation == new_generation:
        blockers.append("MIGRATION_GENERATION_NOT_ADVANCED")
    if old_stage is Stage.TRADING:
        blockers.append("MIGRATION_OLD_STATE_STILL_TRADING")
    if new_stage is not Stage.TRADING:
        blockers.append("MIGRATION_NEW_STATE_NOT_TRADING")
    value = new_generation if not blockers else None
    return Verdict(not blockers, tuple(blockers), Level.RECORDED_OFFLINE, value)


def qualify_post_swap(
    *,
    pre_hash: str,
    post_hash: str,
    event_slot: int,
    post_slot: int,
    complete: bool,
    evidence: Evidence,
    now: int,
) -> Verdict:
    """NF-142: residual binds to complete post-event state."""
    evidence.check(now)
    _hash(pre_hash, "pre_hash")
    _hash(post_hash, "post_hash")
    blockers: list[str] = []
    if pre_hash == post_hash:
        blockers.append("POST_SWAP_STATE_UNCHANGED")
    if post_slot < event_slot:
        blockers.append("POST_SWAP_STATE_PRECEDES_EVENT")
    if not complete:
        blockers.append("POST_SWAP_STATE_INCOMPLETE")
    value = post_hash if not blockers else None
    return Verdict(not blockers, tuple(blockers), Level.RECORDED_OFFLINE, value)


def package_status(
    prerequisites: Mapping[str, bool],
    families: Mapping[Family, bool],
) -> dict[str, object]:
    required = ("AGG-01", "AGG-02", "AGG-04", "AGG-05")
    missing = [item for item in required if not prerequisites.get(item, False)]
    unqualified = [item.value for item in Family if not families.get(item, False)]
    operational = (
        "EXTERNALLY_QUALIFIED_FOR_PROFILE"
        if not missing and not unqualified
        else "UNQUALIFIED"
    )
    return {
        "schema_version": SCHEMA,
        "implementation_status": "IMPLEMENTED_OFFLINE",
        "operational_status": operational,
        "primary_nf": list(NF_IDS),
        "missing_prerequisites": missing,
        "unqualified_families": unqualified,
        "live_enabled": False,
    }


def coverage_manifest() -> dict[str, object]:
    if len(NF_IDS) != 15 or len(NF_FUNCTIONS) != 15:
        raise RuntimeError("AGG-06 NF coverage drift")
    return {
        "schema_version": SCHEMA,
        "agg_id": "AGG-06",
        "implementation_status": "IMPLEMENTED_OFFLINE",
        "operational_status": "UNQUALIFIED",
        "live_enabled": False,
        "nf": [
            {"id": nf, "owner_function": owner}
            for nf, owner in zip(NF_IDS, NF_FUNCTIONS, strict=True)
        ],
    }


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(raw.encode()).hexdigest()


def _hash(value: str, field: str) -> None:
    valid = isinstance(value, str) and len(value) == 64 and value != "0" * 64
    valid = valid and all(char in "0123456789abcdefABCDEF" for char in value)
    if not valid:
        raise Agg06Error("INVALID_HASH", field, stage="validation")


def _text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise Agg06Error("INVALID_TEXT", field, stage="validation")


def _uint(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise Agg06Error("INVALID_INTEGER", field, stage="validation")


def _pos(value: int, field: str) -> None:
    _uint(value, field)
    if value == 0:
        raise Agg06Error("INVALID_INTEGER", field, stage="validation")
