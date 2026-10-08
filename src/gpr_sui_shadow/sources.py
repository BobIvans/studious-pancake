"""Bounded public indexes and finite, checkpoint-scoped GraphQL reads."""

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction

from .models import SuiCandidate, SuiReadRequest, coin_type, uint

CHECKPOINT_QUERY = """query GprCheckpoint {
  chainIdentifier
  checkpoint { sequenceNumber digest timestamp epoch { epochId } }
}"""

OBJECT_QUERY = """query GprObject($checkpoint: UInt53!, $pool: SuiAddress!, $a: String!, $b: String!) {
  chainIdentifier
  checkpoint(sequenceNumber: $checkpoint) {
    sequenceNumber digest timestamp epoch { epochId }
    query {
      object(address: $pool) {
        address version digest
        asMoveObject { contents { type { repr } bcs json } }
      }
      a: coinMetadata(coinType: $a) { address version digest decimals contents { type { repr } bcs json } }
      b: coinMetadata(coinType: $b) { address version digest decimals contents { type { repr } bcs json } }
    }
  }
}"""


def checkpoint_request(endpoint):
    return SuiReadRequest(
        "POST", endpoint, "checkpoint", body={"query": CHECKPOINT_QUERY}
    )


def object_request(endpoint, candidate, checkpoint):
    uint(checkpoint, "checkpoint")
    return SuiReadRequest(
        "POST",
        endpoint,
        "checkpoint-object",
        body={
            "query": OBJECT_QUERY,
            "variables": {
                "checkpoint": checkpoint,
                "pool": candidate.pool_id,
                "a": candidate.coin_types[0],
                "b": candidate.coin_types[1],
            },
        },
    )


def rational(value, *, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("SUI_EXACT_FINITE_RATE_REQUIRED")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("SUI_EXACT_FINITE_RATE_REQUIRED") from None
    if (
        not number.is_finite()
        or number < 0
        or (number == 0 and not allow_zero)
        or len(str(number)) > 64
        or abs(number.adjusted()) > 76
        or abs(int(number.as_tuple().exponent)) > 76
    ):
        raise ValueError("SUI_EXACT_FINITE_RATE_REQUIRED")
    return Fraction(number)


@dataclass(frozen=True)
class StructuralRate:
    coin_type: str
    rate_numerator: int
    rate_denominator: int
    rate_kind: str
    source_time: str | None
    exact_state_ready: bool = False

    def __post_init__(self):
        object.__setattr__(self, "coin_type", coin_type(self.coin_type))
        uint(
            self.rate_numerator,
            "rate_numerator",
            1 if self.rate_kind == "conversionRate" else 0,
            2**256 - 1,
        )
        uint(self.rate_denominator, "rate_denominator", 1, 2**256 - 1)
        if (
            self.rate_kind not in ("conversionRate", "supplyApy", "borrowApy")
            or self.exact_state_ready is not False
        ):
            raise ValueError("SUI_STRUCTURAL_REFERENCE_ONLY")


class PoolIndexAdapter:
    """Each source has its own shape; missing coin types stay rejected evidence."""

    def __init__(self, venue):
        if venue not in ("deepbook", "aftermath", "cetus"):
            raise ValueError("SUI_INDEXER_UNSUPPORTED")
        self.venue = venue

    def normalize(self, payload):
        if self.venue == "aftermath":
            rows = payload
        elif self.venue == "deepbook":
            rows = payload if isinstance(payload, list) else payload.get("pools")
        else:
            if not isinstance(payload, dict) or payload.get("code") not in (0, 200):
                raise ValueError("CETUS_RESPONSE_SCHEMA_REJECTED")
            rows = (
                payload["data"]["lp_list"]
                if payload["code"] == 0
                else payload["data"]["pools"]
            )
        if not isinstance(rows, list) or len(rows) > (
            5000 if self.venue == "aftermath" else 512
        ):
            raise ValueError("SUI_BOUNDED_POOL_INDEX_REQUIRED")
        candidates = []
        rejected: Counter[str] = Counter()
        if len(rows) > 512:
            rejected["bounded-row-scan-truncated"] = len(rows) - 512
        for row in rows[:512]:
            try:
                if self.venue == "aftermath":
                    types, pool = tuple(row["coins"]), row["objectId"]
                elif self.venue == "deepbook":
                    types, pool = (row["base_asset_id"], row["quote_asset_id"]), row[
                        "pool_id"
                    ]
                else:
                    types, pool = (row["coin_a_address"], row["coin_b_address"]), (
                        row["address"] if payload["code"] == 0 else row["swap_account"]
                    )
                candidates.append(SuiCandidate(pool, types, self.venue))
            except (ValueError, KeyError, TypeError, AttributeError):
                rejected["missing-or-invalid-exact-pool-coin-types"] += 1
        return tuple(candidates), (), dict(rejected)


class ScallopRateAdapter:
    def normalize(self, payload):
        rows = payload["pools"]
        if isinstance(rows, dict):
            rows = list(rows.values())
        if not isinstance(rows, list) or len(rows) > 128:
            raise ValueError("SCALLOP_BOUNDED_RATE_INDEX_REQUIRED")
        result = []
        rejected: Counter[str] = Counter()
        for row in rows:
            for kind in ("conversionRate", "supplyApy", "borrowApy"):
                if kind not in row:
                    continue
                try:
                    rate = rational(
                        row[kind], allow_zero=kind in ("supplyApy", "borrowApy")
                    )
                    result.append(
                        StructuralRate(
                            row["coinType"],
                            rate.numerator,
                            rate.denominator,
                            kind,
                            payload.get("updatedAt"),
                        )
                    )
                except (ValueError, KeyError, TypeError):
                    rejected["rate-or-exact-coin-type-invalid"] += 1
        return (), tuple(result), dict(rejected)


def residual_bps(
    market_numerator, market_denominator, reference_numerator, reference_denominator
):
    """Research residual only; callers must prove matching units/time/provenance."""
    for value in (
        market_numerator,
        market_denominator,
        reference_numerator,
        reference_denominator,
    ):
        uint(value, "comparison_rate", 1, 2**256 - 1)
    return (
        Fraction(market_numerator, market_denominator)
        / Fraction(reference_numerator, reference_denominator)
        - 1
    ) * 10_000


def indexed_book_reference(payload):
    """Source-pinned indicative public snapshot; never checkpoint/depth proof."""
    if not isinstance(payload, dict):
        raise ValueError("DEEPBOOK_BOUNDED_REFERENCE_REQUIRED")
    timestamp = payload.get("timestamp")
    if (
        not isinstance(timestamp, str)
        or not timestamp.isascii()
        or not timestamp.isdecimal()
        or len(timestamp) > 16
    ):
        raise ValueError("DEEPBOOK_INDEXED_TIMESTAMP_REQUIRED")
    uint(int(timestamp), "indexed_timestamp", 1)
    sides = {}
    if sum(len(payload.get(side, [])) for side in ("bids", "asks")) > 20:
        raise ValueError("DEEPBOOK_REQUESTED_DEPTH_LIMIT")
    for side in ("bids", "asks"):
        rows = payload.get(side)
        if not isinstance(rows, list) or not rows:
            raise ValueError("DEEPBOOK_TWO_SIDED_REFERENCE_REQUIRED")
        levels = []
        for row in rows:
            if (
                not isinstance(row, list)
                or len(row) != 2
                or any(not isinstance(v, str) for v in row)
            ):
                raise ValueError("DEEPBOOK_EXACT_PRICE_SIZE_STRINGS_REQUIRED")
            price, size = (rational(v) for v in row)
            for value in (price, size):
                uint(value.numerator, "book_numerator", 1, 2**256 - 1)
                uint(value.denominator, "book_denominator", 1, 2**256 - 1)
            levels.append((price, size))
        prices = [level[0] for level in levels]
        if prices != sorted(prices, reverse=side == "bids"):
            raise ValueError("DEEPBOOK_SORTED_REFERENCE_REQUIRED")
        sides[side] = levels
    bid, ask = sides["bids"][0][0], sides["asks"][0][0]
    if bid >= ask:
        raise ValueError("DEEPBOOK_NONCROSSED_REFERENCE_REQUIRED")
    spread = (ask - bid) * 20_000 / (ask + bid)
    return {
        "source_timestamp_ms": timestamp,
        "bid_levels": len(sides["bids"]),
        "ask_levels": len(sides["asks"]),
        "best_bid": payload["bids"][0],
        "best_ask": payload["asks"][0],
        "indicative_mid_spread_bps": {
            "numerator": spread.numerator,
            "denominator": spread.denominator,
        },
        "evidence_state": "DISCOVERY_ONLY",
        "execution_class": "LOCAL_SIGNAL",
        "book_depth_state": "BOOK_DEPTH_UNQUALIFIED",
        "exact_state_ready": False,
        "units_and_fee_state": "UNQUALIFIED_INDEXER_REFERENCE",
    }
