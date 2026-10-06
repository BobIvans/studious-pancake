"""Cheap indexed candidates only; exact state remains owned by QPR-02."""

from collections import Counter

from src.config.chain_registry import validate_pubkey
from src.qualification_campaign.sources import (
    Candidate,
    CatalogDiscoveryAdapter,
    SourceReadRequest,
)


class BatchRadarAdapter:
    """DEX Screener documented token batch endpoint, at most 30 exact mints."""

    def __init__(self, mints):
        self.mints = tuple(sorted(set(mints)))
        if not 1 <= len(self.mints) <= 30:
            raise ValueError("BOUNDED_DEXSCREENER_BATCH_REQUIRED")
        for mint in self.mints:
            validate_pubkey(mint)

    def request(self):
        return SourceReadRequest(
            "https://api.dexscreener.com/tokens/v1/solana/" + ",".join(self.mints)
        )

    def schema_contract(self):
        return {
            "request": "dexscreener.tokens.v1",
            "response": "solana-pairs.v1",
            "classification": "DISCOVERY_ONLY",
            "maximum_mints": 30,
        }

    def normalize(self, payload):
        if not isinstance(payload, list) or len(payload) > 1000:
            raise ValueError("BOUNDED_PAIR_ARRAY_REQUIRED")
        result = {}
        rejected: Counter[str] = Counter()
        for row in payload:
            try:
                if row["chainId"] != "solana":
                    raise ValueError("foreign chain")
                candidate = Candidate(
                    row["pairAddress"],
                    (row["baseToken"]["address"], row["quoteToken"]["address"]),
                    row["dexId"],
                )
                if not set(candidate.mints) <= set(self.mints):
                    rejected["outside-first-campaign"] += 1
                    continue
                result[candidate.identity] = candidate
            except (KeyError, ValueError, TypeError, AttributeError):
                rejected["candidate-schema-rejected"] += 1
        if len(result) > 512:
            rejected["candidate-cap"] += len(result) - 512
        return tuple(result[k] for k in sorted(result)[:512]), dict(rejected)


class ManifestRadarAdapter:
    """API confirmed in the upstream Manifest SDK; no whole-program scan."""

    def __init__(self, mints):
        self.mints = frozenset(mints)
        if not 2 <= len(self.mints) <= 30:
            raise ValueError("BOUNDED_TARGET_MINTS_REQUIRED")
        for mint in self.mints:
            validate_pubkey(mint)

    def request(self):
        return SourceReadRequest("https://mfx-stats-mainnet.fly.dev/tickers")

    def schema_contract(self):
        return {
            "request": "manifest.tickers.v1",
            "response": "ticker-array.v1",
            "classification": "DISCOVERY_ONLY",
            "maximum_rows": 1000,
        }

    def normalize(self, payload):
        if not isinstance(payload, list) or len(payload) > 1000:
            raise ValueError("BOUNDED_TICKER_ARRAY_REQUIRED")
        result = {}
        rejected: Counter[str] = Counter()
        for row in payload:
            try:
                c = Candidate(
                    row["ticker_id"],
                    (row["base_currency"], row["target_currency"]),
                    "manifest",
                )
                if not set(c.mints) <= self.mints:
                    rejected["outside-first-campaign"] += 1
                    continue
                result[c.identity] = c
            except (KeyError, TypeError, ValueError, AttributeError):
                rejected["candidate-schema-rejected"] += 1
        if len(result) > 512:
            rejected["candidate-cap"] += len(result) - 512
        return tuple(result[k] for k in sorted(result)[:512]), dict(rejected)


class TargetedCatalogAdapter(CatalogDiscoveryAdapter):
    """Reuse the existing Meteora/Raydium owners, with priority mint filtering."""

    def __init__(self, request, mints):
        super().__init__(request)
        self.mints = frozenset(mints)

    def schema_contract(self):
        return {**super().schema_contract(), "target_filter": "first-campaign.v1"}

    def normalize(self, payload):
        candidates, rejected = super().normalize(payload)
        keep = tuple(c for c in candidates if set(c.mints) <= self.mints)
        if len(candidates) != len(keep):
            rejected["outside-first-campaign"] = len(candidates) - len(keep)
        return tuple(sorted(keep, key=lambda c: c.identity))[:512], rejected
