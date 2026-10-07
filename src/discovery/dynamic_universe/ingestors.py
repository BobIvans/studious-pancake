"""Read-only bounded adapters. Registries supply candidates, never chain truth."""

from dataclasses import replace
import json
import math
import re
import time
import tomllib
from typing import Callable, Protocol
import urllib.error
import urllib.parse
import urllib.request

from src.assets.resolution.evidence import Evidence, EvidenceStore, digest
from src.assets.resolution.resolver import (
    AssetResolutionJob,
    CandidateAsset,
    ChainAssetProof,
    canonical_identifier,
    resolve,
)
from .universe import DiscoveryEnvelope, MarketIdentity

SANCTUM_URL = "https://raw.githubusercontent.com/igneous-labs/sanctum-lst-list/master/sanctum-lst-list.toml"
DEEPBOOK_URL = "https://raw.githubusercontent.com/MystenLabs/ts-sdks/main/packages/deepbook-v3/src/utils/constants.ts"


class ReadOnlyFetcher:
    def __init__(
        self,
        store: EvidenceStore,
        generation: str,
        *,
        timeout: float = 15,
        max_bytes: int = 8_000_000,
        clock: Callable[[], float] = time.time,
    ):
        if (
            not math.isfinite(timeout)
            or timeout <= 0
            or type(max_bytes) is not int
            or not 1 <= max_bytes <= 16_000_000
        ):
            raise ValueError("bounded fetch limits required")
        self.store, self.generation, self.timeout, self.max_bytes, self.clock = (
            store,
            generation,
            timeout,
            max_bytes,
            clock,
        )

    def fetch(
        self, url: str, provider: str, *, body: dict | None = None
    ) -> tuple[dict, Evidence]:
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("credential-free HTTPS source required")
        request = {"url": url, "body": body}
        reason = None
        try:
            req = urllib.request.Request(
                url,
                data=None if body is None else json.dumps(body).encode(),
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "studious-pancake-read-only/1",
                },
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read(self.max_bytes + 1)
                if len(raw) > self.max_bytes:
                    raise ValueError("response_size_limit")
                content = raw.decode("utf-8")
                payload = {"body": content, "status": response.status}
        except urllib.error.HTTPError as exc:
            reason = f"http_{exc.code}"
            payload = {"negative_reason": reason}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            # Never copy provider error bodies/URLs containing credentials.
            reason = "transport_" + type(exc).__name__
            payload = {"negative_reason": reason}
        evidence = Evidence(
            url,
            provider,
            provider,
            self.generation,
            self.clock(),
            digest(payload),
            digest(request),
            negative_reason=reason,
        )
        self.store.append(evidence, payload)
        return payload, evidence


class UniverseIngestor(Protocol):
    def poll(
        self, cursor: str | None, budget: int
    ) -> tuple[DiscoveryEnvelope, ...]: ...


class RegistryIngestor:
    def __init__(
        self,
        fetcher: ReadOnlyFetcher,
        url: str,
        provider: str,
        parser: Callable,
        *,
        max_rows: int = 4096,
    ):
        if type(max_rows) is not int or not 1 <= max_rows <= 4096:
            raise ValueError("invalid row bound")
        self.fetcher, self.url, self.provider, self.parser, self.max_rows = (
            fetcher,
            url,
            provider,
            parser,
            max_rows,
        )

    def poll(
        self, cursor: str | None = None, budget: int = 1
    ) -> tuple[DiscoveryEnvelope, ...]:
        if type(budget) is not int or budget < 0:
            raise ValueError("invalid polling budget")
        if budget == 0:
            return ()
        payload, evidence = self.fetcher.fetch(self.url, self.provider)
        if evidence.negative_reason:
            return (DiscoveryEnvelope(evidence),)
        try:
            assets, markets = self.parser(payload["body"], evidence)
            offset = 0 if cursor is None else int(cursor)
            total = max(len(assets), len(markets))
            if offset < 0 or offset > total:
                raise ValueError("invalid cursor")
            end = min(total, offset + self.max_rows)
            # Paging an independently changing registry is discovery only. Only
            # a single full response may assert disappearance/retirement.
            complete = offset == 0 and end == total
            envelope = DiscoveryEnvelope(
                evidence,
                tuple(assets[offset:end]),
                tuple(markets[offset:end]),
                complete,
                not complete,
                str(end) if end < total else None,
            )
            return (envelope,)
        except (ValueError, KeyError, TypeError, OverflowError):
            negative = replace(
                evidence, negative_reason="schema_drift_or_invalid_cursor"
            )
            return (DiscoveryEnvelope(negative),)


def sanctum_parser(body: str, evidence: Evidence):
    rows = tomllib.loads(body)["sanctum_lst_list"]
    if not isinstance(rows, list) or len(rows) > 65536:
        raise ValueError("invalid registry rows")
    return (
        tuple(
            CandidateAsset(
                "solana",
                r["mint"],
                r["symbol"],
                r["decimals"],
                r["token_program"],
                evidence,
                True,
                "SOL",
                "LST",
            )
            for r in rows
        ),
        (),
    )


def jupiter_parser(body: str, evidence: Evidence):
    rows = json.loads(body)
    if not isinstance(rows, list) or len(rows) > 65536:
        raise ValueError("invalid token response")
    # Jupiter corroborates; issuer/protocol authority is still required.
    return (
        tuple(
            CandidateAsset(
                "solana",
                r["id"],
                r["symbol"],
                r["decimals"],
                r["tokenProgram"],
                evidence,
                False,
            )
            for r in rows
        ),
        (),
    )


def _typescript_map(body: str, name: str) -> dict[str, dict]:
    match = re.search(r"export const " + name + r": \w+ = \{(.*?)\n\};", body, re.S)
    if not match:
        raise ValueError("SDK map schema changed")
    section = re.sub(r"//[^\n]*", "", match[1])
    entries = re.findall(r"([A-Za-z_0-9]+):\s*\{([^{}]*)\}", section)
    rows = {}
    for key, fields in entries:
        row = {}
        for field, quoted, number in re.findall(
            r"(\w+):\s*(?:[`'\"]([^`'\"]*)[`'\"]|(\d+))\s*,", fields
        ):
            row[field] = quoted if quoted else int(number)
        rows[key] = row
    if not rows:
        raise ValueError("empty SDK map")
    return rows


def deepbook_parser(body: str, evidence: Evidence):
    coins = _typescript_map(body, "mainnetCoins")
    pools = _typescript_map(body, "mainnetPools")
    assets = []
    for symbol, row in sorted(coins.items()):
        scalar = row["scalar"]
        decimals = len(str(scalar)) - 1
        if scalar != 10**decimals:
            raise ValueError("nondecimal SDK scalar")
        coin = canonical_identifier("sui", row["type"])
        assets.append(
            CandidateAsset(
                "sui", coin, symbol, decimals, coin.rsplit("::", 1)[0], evidence, True
            )
        )
    markets = tuple(
        MarketIdentity(
            "sui",
            "deepbook",
            "deepbook-v3",
            r["address"],
            coins[r["baseCoin"]]["type"],
            coins[r["quoteCoin"]]["type"],
            "unverified",
            f"sui:{r['address']}",
            (f"sui:{r['address']}",),
            evidence,
        )
        for r in pools.values()
    )
    return tuple(assets), markets


def venue_parser(body: str, evidence: Evidence):
    """Normalized protocol adapter contract; raw indexer formats cannot bypass it."""
    data = json.loads(body)
    if (
        data["schema"] != "dynamic-universe.markets.v1"
        or not isinstance(data["markets"], list)
        or len(data["markets"]) > 65536
    ):
        raise ValueError("unknown venue schema")
    return (), tuple(
        MarketIdentity(**dict(row, evidence=evidence)) for row in data["markets"]
    )


class SanctumLstIngestor(RegistryIngestor):
    def __init__(self, fetcher: ReadOnlyFetcher, **kwargs):
        super().__init__(fetcher, SANCTUM_URL, "sanctum", sanctum_parser, **kwargs)


class JupiterTokensIngestor(RegistryIngestor):
    def __init__(self, fetcher: ReadOnlyFetcher, query: str):
        super().__init__(
            fetcher,
            "https://api.jup.ag/tokens/v2/search?"
            + urllib.parse.urlencode({"query": query}),
            "jupiter-tokens",
            jupiter_parser,
        )


class DeepBookIngestor(RegistryIngestor):
    def __init__(self, fetcher: ReadOnlyFetcher, **kwargs):
        super().__init__(
            fetcher, DEEPBOOK_URL, "deepbook-registry", deepbook_parser, **kwargs
        )


class LiveAssetResolver:
    """Runtime discover -> chain verify -> durable receipt; no guessed addresses."""

    def __init__(
        self,
        ingestors: tuple[RegistryIngestor, ...],
        verifier: Callable[[CandidateAsset], tuple[ChainAssetProof, ...]],
        store: EvidenceStore,
    ):
        self.ingestors, self.verifier, self.store = ingestors, verifier, store

    def discover(
        self, query: str, context: AssetResolutionJob
    ) -> tuple[CandidateAsset, ...]:
        found: list[CandidateAsset] = []
        for ingestor in self.ingestors:
            for envelope in ingestor.poll(None, 1):
                found.extend(
                    c
                    for c in envelope.assets
                    if c.chain == context.chain
                    and (
                        c.identifier == context.seed_identifier
                        or c.symbol == query
                        or c.identifier == query
                    )
                )
        return tuple(found)

    def run(self, job: AssetResolutionJob, *, now: float):
        candidates = self.discover(job.query, job)
        ids = {c.identifier for c in candidates if c.authoritative}
        proofs = (
            self.verifier(next(c for c in candidates if c.authoritative))
            if len(ids) == 1
            else ()
        )
        return resolve(job, candidates, proofs, now=now, store=self.store)

    def verify(
        self, candidate: CandidateAsset, chain_state: tuple[ChainAssetProof, ...]
    ):
        job = AssetResolutionJob(
            candidate.chain, candidate.identifier, candidate.evidence.generation
        )
        return resolve(
            job,
            (candidate,),
            chain_state,
            now=candidate.evidence.observed_at,
            store=self.store,
        )
