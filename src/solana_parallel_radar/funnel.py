"""Integer read-only quote comparisons and explicit qualification boundaries."""

from dataclasses import asdict, dataclass

from src.qualification_campaign.identity import digest
from src.research_economic_graph import ExecutionClass, VerificationTarget

PRIORITY_PAIRS = (
    ("USDG", "USDC"),
    ("USD1", "USDT"),
    ("USD1", "USDC"),
    ("xBTC_OKX", "cbBTC"),
    ("JLP", "USDC"),
    ("BNSOL", "WSOL"),
    ("bbSOL", "WSOL"),
    ("hSOL", "WSOL"),
    ("dSOL", "WSOL"),
)


def priority_pairs(registry):
    # Native SOL and SPL WSOL remain distinct. Quotes use WSOL explicitly.
    return tuple(
        tuple(registry.resolve("solana-mainnet:" + k) for k in pair)
        for pair in PRIORITY_PAIRS
    )


def uint(value, *, positive=True):
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        value = int(value)
    if type(value) is not int or not (1 if positive else 0) <= value <= 2**64 - 1:
        raise ValueError("EXACT_BOUNDED_INTEGER_REQUIRED")
    return value


@dataclass(frozen=True)
class QuotePreview:
    input_mint: str
    output_mint: str
    input_amount: int
    output_amount: int
    minimum_output_amount: int
    slot: int | None
    observed_at_ns: int
    source_id: str
    provider_generation: str
    correlation_group: str
    raw_evidence_ref: str
    route_mints: tuple[str, ...]
    direct: bool
    evidence_state: str = "DISCOVERY_ONLY"

    def __post_init__(self):
        from src.config.chain_registry import validate_pubkey

        for mint in (self.input_mint, self.output_mint, *self.route_mints):
            validate_pubkey(mint)
        for n in (
            self.input_amount,
            self.output_amount,
            self.minimum_output_amount,
            self.observed_at_ns,
        ):
            uint(n)
        if self.slot is not None:
            uint(self.slot)
        if (
            self.input_mint == self.output_mint
            or self.minimum_output_amount > self.output_amount
            or not all(
                (
                    self.source_id,
                    self.provider_generation,
                    self.correlation_group,
                    self.raw_evidence_ref,
                )
            )
            or self.evidence_state != "DISCOVERY_ONLY"
            or not 1 <= len(self.route_mints) <= 32
            or type(self.direct) is not bool
        ):
            raise ValueError("QUOTE_PREVIEW_IDENTITY_OR_AUTHORITY_INVALID")


def normalize_jupiter(
    payload,
    *,
    request,
    observed_at_ns,
    source_id,
    provider_generation,
    correlation_group,
    raw_evidence_ref,
):
    params = dict(request.params)
    if (
        payload.get("inputMint") != params["inputMint"]
        or payload.get("outputMint") != params["outputMint"]
        or uint(payload.get("inAmount")) != uint(params["amount"])
        or payload.get("swapMode") != "ExactIn"
    ):
        raise ValueError("QUOTE_REQUEST_RESPONSE_IDENTITY_MISMATCH")
    routes = payload.get("routePlan")
    if not isinstance(routes, list) or not 1 <= len(routes) <= 16:
        raise ValueError("BOUNDED_QUOTE_ROUTE_REQUIRED")
    mints = tuple(
        sorted(
            {
                mint
                for step in routes
                for mint in (
                    step["swapInfo"]["inputMint"],
                    step["swapInfo"]["outputMint"],
                )
            }
        )
    )
    if not {params["inputMint"], params["outputMint"]} <= set(mints):
        raise ValueError("QUOTE_ROUTE_ENDPOINTS_MISSING")
    direct = all(
        {s["swapInfo"]["inputMint"], s["swapInfo"]["outputMint"]}
        == {params["inputMint"], params["outputMint"]}
        for s in routes
    )
    return QuotePreview(
        params["inputMint"],
        params["outputMint"],
        uint(payload["inAmount"]),
        uint(payload["outAmount"]),
        uint(payload["otherAmountThreshold"]),
        uint(payload["contextSlot"]),
        observed_at_ns,
        source_id,
        provider_generation,
        correlation_group,
        raw_evidence_ref,
        mints,
        direct,
    )


def compare_quotes(a, b, *, now_ns, max_age_ns=45_000_000_000, max_slot_gap=32):
    if (a.input_mint, a.output_mint, a.input_amount) != (
        b.input_mint,
        b.output_mint,
        b.input_amount,
    ):
        raise ValueError("QUOTE_UNITS_OR_REPRESENTATION_MISMATCH")
    if not 0 < max_age_ns <= 45_000_000_000 or not 0 <= max_slot_gap <= 32:
        raise ValueError("BOUNDED_QUOTE_FRESHNESS_REQUIRED")
    if any(not 0 <= now_ns - q.observed_at_ns <= max_age_ns for q in (a, b)):
        raise ValueError("QUOTE_STALE_OR_FUTURE")
    if (
        a.slot is not None
        and b.slot is not None
        and abs(a.slot - b.slot) > max_slot_gap
    ):
        raise ValueError("QUOTE_CONTEXT_SLOT_GAP")
    return {
        "kind": "gpr02_quote_comparison",
        "disagreement_bps": (b.output_amount - a.output_amount)
        * 10_000
        // a.output_amount,
        "direct_vs_synthetic": a.direct != b.direct,
        "independent": a.correlation_group != b.correlation_group,
        "slot_alignment": (
            "UNKNOWN" if a.slot is None or b.slot is None else "WITHIN_BOUND"
        ),
        "raw_evidence_refs": sorted({a.raw_evidence_ref, b.raw_evidence_ref}),
        "execution_authority": False,
        "production_promotion": False,
    }


def qualification_blockers(
    request, registry, *, zero_x_preview=None, jupiter_final=None, receipt_refs=()
):
    reasons = []
    if (
        request.target != VerificationTarget.SOLANA_QPR02_DIRECT_STATE
        or request.execution_class != ExecutionClass.LOCAL_ATOMIC
    ):
        reasons.append("NON_ATOMIC_RESEARCH_ONLY")
    if not request.pool_or_book_ids:
        reasons.append("EXACT_POOL_BINDING_REQUIRED")
    if zero_x_preview is None:
        reasons.append("0X_REFERENCE_PREVIEW_REQUIRED")
    if jupiter_final is None:
        reasons.append("JUPITER_REFERENCE_FINAL_QUOTE_REQUIRED")
    if not receipt_refs:
        reasons.append("STARTUP_HARD_BOUND_RECEIPTS_REQUIRED")
    if any(
        registry.resolve(a).standard == "Token-2022" for a in request.representations
    ):
        reasons.append("TOKEN_2022_QPR02_DECODER_UNSUPPORTED")
    return tuple(reasons)


def persist_funnel_plan(evidence, requests, registry):
    rows = [
        {
            "request_id": r.identity,
            "relation_id": r.relation_id,
            "heat": r.heat,
            "execution_class": r.execution_class,
            "evidence_state": "DISCOVERY_ONLY",
            "stage_order": [
                "0X_READ_ONLY_PREVIEW",
                "JUPITER_REFERENCE",
                "JUPITER_FINAL",
                "SANCTUM_STRUCTURAL_IF_LST",
                "QPR02_INDEPENDENT_DIRECT_STATE",
                "STARTUP_HARD_BOUND",
                "EXISTING_SHADOW_INGEST",
            ],
            "blockers": qualification_blockers(r, registry),
            "live_authorization": False,
        }
        for r in requests
    ]
    return evidence.append(
        "gpr02-funnel",
        {"kind": "gpr02_funnel_plan", "rows": rows, "rows_hash": digest(rows)},
        observed_at_ns=evidence.wall_ns(),
    )
