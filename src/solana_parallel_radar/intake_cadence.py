"""Bounded multi-round intake cadence over the governed QPR intake plane.

One campaign may walk a reviewed source across several admitted physical
requests (pagination and repeat rounds). The scheduler owns only pacing and
conservative stop rules: quota admission, dossier/profile generation checks,
evidence journaling and secret redaction remain owned by ``SourceIntakePlane``
and ``ProviderGovernance``. Indexed pages are never a complete snapshot; pool
retirement stays a ``DynamicUniverse`` decision fed by complete live snapshots.

It also bridges retained indexed observations into the existing
``DynamicUniverse`` owners: only chain-proven mints become ``CandidateAsset``
records and only fully proven pairs become research-only ``MarketIdentity``
rows. Unproven identities are counted rejections, never silently dropped and
never promoted.
"""

from collections import Counter
from dataclasses import dataclass, field
import math
from typing import Callable

from src.assets.resolution.evidence import Evidence
from src.assets.resolution.resolver import CandidateAsset, ChainAssetProof
from src.discovery.dynamic_universe.universe import DiscoveryEnvelope, MarketIdentity
from src.qualification_campaign.sources import (
    Candidate,
    DiscoveryAdapter,
    SourceDossier,
    SourceIntakePlane,
)

# Quality states emitted by the canonical intake plane.
POSITIVE_STATES = frozenset({"accepted", "accepted-with-rejections"})
STOP_STATES = frozenset({"empty-response", "schema-drift"})
# A denied attempt is permanent for the campaign: the cap is already spent.
EXHAUSTED_STATES = frozenset({"quota-or-admission-denied"})
BACKOFF_STATES = frozenset(
    {
        "rate-limited",
        "unauthorized",
        "http-error",
        "timeout",
        "transport-error",
        "schema-or-admission-error",
    }
)

# Indexed provider labels mapped to canonical venue families so one pool seen
# through two sources produces one research identity. An unmapped label is an
# explicit rejection, never a guessed family binding.
VENUE_FAMILY = {
    "raydium": "raydium",
    "meteora": "meteora-dlmm",
    "meteora-dlmm": "meteora-dlmm",
    "manifest": "manifest",
}


@dataclass(frozen=True)
class CadencePolicy:
    """Per-source pacing bounds. Every value is configuration-pinned."""

    round_interval_ns: int
    max_pages_per_round: int = 1
    backoff_multiplier: int = 4
    max_backoff_ns: int = 3_600_000_000_000
    retry_after_cap_ns: int = 3_600_000_000_000

    def __post_init__(self) -> None:
        for name in (
            "round_interval_ns",
            "max_pages_per_round",
            "backoff_multiplier",
            "max_backoff_ns",
            "retry_after_cap_ns",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError("positive cadence bound required: " + name)
        if self.max_pages_per_round > 8:
            raise ValueError("page walk outside the typed request bound 1..8")
        if self.backoff_multiplier > 60:
            raise ValueError("unbounded backoff multiplier rejected")
        if self.max_backoff_ns < self.round_interval_ns:
            raise ValueError("backoff ceiling below the base interval")


@dataclass
class IntakeRun:
    """Everything one bounded cadence run produced, evidence-bound."""

    records: list = field(default_factory=list)
    observation_receipts: list[dict] = field(default_factory=list)
    round_receipts: list[dict] = field(default_factory=list)
    physical_requests_spent: int = 0


class IntakeScheduler:
    """Deterministic bounded paging/rounds over reviewed discovery sources.

    The scheduler never walks past a failing page inside a round, applies
    bounded backoff (honoring a bounded Retry-After) between rounds, and stops
    a source permanently once its campaign attempt cap is denied. Physical
    requests always flow through the governed intake plane.
    """

    def __init__(
        self,
        plane: SourceIntakePlane,
        sources: dict[
            str, tuple[SourceDossier, Callable[[int], DiscoveryAdapter], CadencePolicy]
        ],
        *,
        clock_ns: Callable[[], int],
        max_physical_requests: int,
    ):
        if type(max_physical_requests) is not int or max_physical_requests <= 0:
            raise ValueError("positive physical request budget required")
        if not sources or not all(
            isinstance(source_id, str) and source_id for source_id in sources
        ):
            raise ValueError("identified cadence sources required")
        self.plane = plane
        self.sources = {key: sources[key] for key in sorted(sources)}
        self.clock_ns = clock_ns
        self.max_physical_requests = max_physical_requests
        self.next_due_ns = {key: 0 for key in self.sources}
        self.exhausted: set[str] = set()

    def _delay_ns(self, policy: CadencePolicy, envelope: dict) -> int:
        retry_after = envelope.get("retry_after")
        delay = policy.round_interval_ns
        if retry_after is not None:
            try:
                bounded = min(
                    int(float(retry_after)) * 10**9, policy.retry_after_cap_ns
                )
                delay = max(delay, bounded)
            except (TypeError, ValueError):
                delay = policy.round_interval_ns
        return min(delay, policy.max_backoff_ns)

    async def run_rounds(self, rounds: int) -> IntakeRun:
        """Run at most ``rounds`` pacing rounds.

        Records are ``(candidate, provenance)`` pairs exactly as produced by
        the canonical intake plane; observation envelopes are retained inside
        it as campaign evidence and surfaced here as redacted receipts.
        """
        if type(rounds) is not int or not 1 <= rounds <= 64:
            raise ValueError("round count outside 1..64")
        run = IntakeRun()
        for round_index in range(1, rounds + 1):
            if not self.max_physical_requests:
                break
            per_source: dict[str, dict] = {}
            now_ns = self.clock_ns()
            for source_id, (dossier, adapter_factory, policy) in self.sources.items():
                entry: dict = {"pages_attempted": 0, "accepted_candidates": 0}
                if now_ns < self.next_due_ns[source_id]:
                    entry["skipped"] = "backoff-not-due"
                elif source_id in self.exhausted:
                    entry["skipped"] = "campaign-attempt-cap-exhausted"
                elif not self.max_physical_requests:
                    entry["skipped"] = "physical-request-budget-exhausted"
                else:
                    rejections: Counter[str] = Counter()
                    for page in range(1, policy.max_pages_per_round + 1):
                        if not self.max_physical_requests:
                            entry["skipped"] = "physical-request-budget-exhausted"
                            break
                        candidates, envelope = await self.plane.collect(
                            dossier, adapter_factory(page)
                        )
                        self.max_physical_requests -= 1
                        entry["pages_attempted"] += 1
                        state = envelope.get("quality_state")
                        entry["last_quality_state"] = state
                        entry["last_page"] = page
                        run.observation_receipts.append(
                            {
                                "source_id": source_id,
                                "page": page,
                                **{
                                    key: value
                                    for key, value in envelope.items()
                                    if key != "raw_payload"
                                },
                            }
                        )
                        for reason, count in (envelope.get("rejections") or {}).items():
                            rejections[reason] += count
                        if state in POSITIVE_STATES:
                            run.records.extend(candidates)
                            entry["accepted_candidates"] += len(candidates)
                            if not candidates:
                                # A healthy page yielding no rows ends the walk
                                # conservatively; a later round may resume it.
                                entry["stopped"] = "empty-page"
                                break
                        elif state in EXHAUSTED_STATES:
                            self.exhausted.add(source_id)
                            entry["stopped"] = state
                            break
                        elif state in BACKOFF_STATES or state in STOP_STATES:
                            entry["stopped"] = state
                            if state in BACKOFF_STATES:
                                self.next_due_ns[source_id] = (
                                    self.clock_ns() + self._delay_ns(policy, envelope)
                                )
                            break
                    entry["rejections"] = dict(sorted(rejections.items()))
                per_source[source_id] = entry
            run.round_receipts.append(
                {
                    "round_index": round_index,
                    "started_at_ns": now_ns,
                    "per_source": per_source,
                    "physical_requests_remaining": self.max_physical_requests,
                }
            )
        run.physical_requests_spent = len(run.observation_receipts)
        return run


def radar_universe_envelopes(
    observations,
    mint_proofs: dict[str, ChainAssetProof],
    *,
    generation: str,
):
    """Bridge retained indexed observations into ``DiscoveryEnvelope`` rows.

    ``observations`` are dicts with ``source_id``, ``provider``,
    ``correlation_group``, ``observed_at_ns``, ``response_hash``,
    ``request_fingerprint`` and ``candidates``. A market row is emitted only
    when every mint of the pair has a matching current chain proof; anything
    else is counted as an explicit ``identity_unverified`` rejection. Emitted
    rows stay DISCOVERED research records: indexed pages are never complete
    snapshots, so no retirement can follow from them.
    """
    if not isinstance(generation, str) or not generation.strip():
        raise ValueError("universe generation binding required")
    envelopes: list[DiscoveryEnvelope] = []
    rejections: Counter[str] = Counter()
    for observation in observations:
        required = {
            "source_id",
            "provider",
            "correlation_group",
            "observed_at_ns",
            "response_hash",
            "request_fingerprint",
            "candidates",
        }
        if set(observation) != required:
            raise ValueError("radar observation contract mismatch")
        observed_at = observation["observed_at_ns"] / 10**9
        if not math.isfinite(observed_at) or observed_at <= 0:
            raise ValueError("observation timestamp required")
        evidence = Evidence(
            observation["source_id"],
            observation["provider"],
            observation["correlation_group"],
            generation,
            observed_at,
            observation["response_hash"],
            observation["request_fingerprint"],
        )
        assets: dict[str, CandidateAsset] = {}
        markets: dict[str, MarketIdentity] = {}
        for candidate in observation["candidates"]:
            if not isinstance(candidate, Candidate):
                raise ValueError("canonical radar candidate required")
            family = VENUE_FAMILY.get(candidate.venue_label)
            if family is None:
                rejections["unknown-venue-family"] += 1
            pair_proven = family is not None
            for mint in candidate.mints:
                if mint in assets:
                    continue
                proof = mint_proofs.get(mint)
                if proof is None:
                    rejections["identity_unverified_mints"] += 1
                    pair_proven = False
                    continue
                if proof.chain != "solana" or proof.identifier != mint:
                    rejections["identity_proof_mismatch"] += 1
                    pair_proven = False
                    continue
                assets[mint] = CandidateAsset(
                    "solana",
                    mint,
                    "UNKNOWN",
                    proof.decimals,
                    proof.program_or_package,
                    evidence,
                    True,
                    extensions=proof.extensions,
                )
            if family is not None and pair_proven:
                base, quote = candidate.mints
                market = MarketIdentity(
                    "solana",
                    family,
                    "indexed:" + family,
                    candidate.market_id,
                    base,
                    quote,
                    "unverified",
                    f"solana:{candidate.market_id}",
                    (f"solana:{candidate.market_id}",),
                    evidence,
                )
                markets[market.identity] = market
        envelopes.append(
            DiscoveryEnvelope(
                evidence,
                tuple(assets[key] for key in sorted(assets)),
                tuple(markets[key] for key in sorted(markets)),
                False,
                False,
                None,
            )
        )
    return tuple(envelopes), dict(sorted(rejections.items()))


def coverage_report(
    *,
    hot_pair_target: int | None,
    sources: dict[str, dict],
    blocked_sources: list[dict],
    round_receipts: list[dict],
    candidate_receipts: int,
    unique_identities: int,
    identity_verified_mints: int,
    identity_unverified_mints: int,
    blockers: list[str],
) -> dict:
    """Machine-readable per-source coverage receipt for one campaign.

    The hot-pair target is a research reference only: the report states the
    measured coverage against it and never fabricates rows or promotes
    candidates to satisfy a configured number.
    """
    if hot_pair_target is not None and (
        type(hot_pair_target) is not int or not 1 <= hot_pair_target <= 100_000
    ):
        raise ValueError("bounded hot-pair research target required")
    physical_calls = 0
    quality_counts: dict[str, Counter] = {key: Counter() for key in sources}
    for receipt in round_receipts:
        for source_id, entry in receipt["per_source"].items():
            if source_id not in quality_counts:
                raise ValueError("coverage source not reviewed: " + str(source_id))
            pages = entry.get("pages_attempted", 0)
            physical_calls += pages
            if pages:
                state = entry.get("last_quality_state")
                if state is not None:
                    quality_counts[source_id][state] += 1
    per_source: dict[str, dict] = {}
    for source_id, counts in quality_counts.items():
        reviewed = sources[source_id]
        per_source[source_id] = {
            "physical_calls": sum(
                receipt["per_source"].get(source_id, {}).get("pages_attempted", 0)
                for receipt in round_receipts
            ),
            "quality_states": dict(sorted(counts.items())),
            "correlation_group": reviewed["correlation_group"],
            "docs_pin_checked_at": reviewed["docs_pin_checked_at"],
            "snapshot_completeness": "PARTIAL_INDEXED_PAGES_ONLY",
            "stale_rows_accepted": 0,
        }
    if hot_pair_target is None:
        target_block: dict = {"status": "TARGET_NOT_CONFIGURED"}
    else:
        supported = unique_identities >= hot_pair_target
        target_block = {
            "configured_target": hot_pair_target,
            "measured_unique_identities": unique_identities,
            "status": (
                "TARGET_WITHIN_MEASURED_COVERAGE"
                if supported
                else "TARGET_NOT_SUPPORTED_BY_MEASURED_COVERAGE"
            ),
            "note": "research reference only; rows are never fabricated",
        }
    return {
        "schema_version": "p01.source-coverage.v1",
        "physical_calls": physical_calls,
        "candidate_receipts": candidate_receipts,
        "unique_identities": unique_identities,
        "duplicate_rows_merged": candidate_receipts - unique_identities,
        "identity_verified_mints": identity_verified_mints,
        "identity_unverified_mints": identity_unverified_mints,
        "classification": "DISCOVERY_ONLY",
        "per_source": per_source,
        "blocked_sources": blocked_sources,
        "hot_pair_target": target_block,
        "exact_status": "BLOCKED",
        "paper_status": "BLOCKED",
        "production_status": "BLOCKED",
        "blockers": blockers,
    }
