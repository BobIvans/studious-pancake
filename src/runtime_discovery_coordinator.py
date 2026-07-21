"""Bounded discovery/snapshot/detector cycle for PR-056."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import time
from typing import Any, Sequence
from uuid import uuid4

from src.market.snapshots import MarketQuoteSnapshot, SnapshotSet
from src.providers.jupiter.quota import JupiterQuotaManager
from src.routing.models import DiscoveryBatch, QuoteRequest
from src.strategy.detectors import CircularArbitrageDetector
from src.strategy.domain import Opportunity

from src.runtime_discovery_models import (
    DiscoveryClient,
    RuntimeDiscoveryEvidence,
    RuntimeDiscoveryPair,
    RuntimeDiscoveryReport,
    RuntimeDiscoveryUniverse,
    _PairCycleResult,
)


class RuntimeDiscoveryCoordinator:
    """Run one bounded discovery/snapshot/detector cycle."""

    def __init__(
        self,
        *,
        plane: DiscoveryClient,
        universe: RuntimeDiscoveryUniverse,
        user_wallet: str | None,
        commitment: str,
        jupiter_quota: JupiterQuotaManager | None = None,
        clock: Any = time.time,
    ) -> None:
        self.plane = plane
        self.universe = universe
        self.user_wallet = user_wallet
        self.commitment = commitment
        self.jupiter_quota = jupiter_quota
        self._clock = clock
        self._detector = CircularArbitrageDetector(
            tuple(item.pair for item in universe.pairs)
        )

    async def run_cycle(self) -> RuntimeDiscoveryReport:
        started_at = float(self._clock())
        cycle_id = uuid4().hex
        required = tuple(
            item.pair.pair_id for item in self.universe.pairs if item.required
        )
        if not self.user_wallet:
            return self._blocked_report(
                cycle_id=cycle_id,
                started_at=started_at,
                required_pairs=required,
                reason="blocked_missing_wallet_public_key",
            )

        semaphore = asyncio.Semaphore(self.universe.max_concurrent_pairs)

        async def bounded(item: RuntimeDiscoveryPair) -> _PairCycleResult:
            async with semaphore:
                return await self._discover_pair(cycle_id, item)

        tasks = [asyncio.create_task(bounded(item)) for item in self.universe.pairs]
        degraded: list[str] = []
        try:
            pair_results = await asyncio.wait_for(
                asyncio.gather(*tasks),
                timeout=self.universe.cycle_timeout_seconds,
            )
        except asyncio.TimeoutError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            return self._blocked_report(
                cycle_id=cycle_id,
                started_at=started_at,
                required_pairs=required,
                reason="blocked_discovery_cycle_timeout",
            )
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            raise
        except Exception as exc:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            return self._blocked_report(
                cycle_id=cycle_id,
                started_at=started_at,
                required_pairs=required,
                reason="blocked_discovery_cycle_failure",
                degraded_reasons=(f"{type(exc).__name__}:{exc}",),
            )

        all_snapshots = tuple(
            snapshot for result in pair_results for snapshot in result.snapshots
        )
        snapshots, duplicate_snapshots = self._deduplicate_snapshots(all_snapshots)
        snapshot_set = SnapshotSet(snapshots)
        detected = self._detector.detect(snapshot_set, now=float(self._clock()))
        opportunities, duplicate_candidates = self._deduplicate_candidates(detected)
        dropped_backpressure = max(0, len(opportunities) - self.universe.max_candidates)
        opportunities = opportunities[: self.universe.max_candidates]

        completed_required = tuple(
            result.pair_id
            for result in pair_results
            if result.required and result.complete
        )
        provider_failures: dict[str, int] = {}
        for result in pair_results:
            degraded.extend(result.degraded_reasons)
            for provider, count in result.provider_failures.items():
                provider_failures[provider] = provider_failures.get(provider, 0) + count
        cycle_succeeded = set(completed_required) == set(required)
        terminal_reason = (
            "discovery_cycle_completed"
            if cycle_succeeded
            else "blocked_required_discovery_incomplete"
        )
        completed_at = float(self._clock())
        evidence = RuntimeDiscoveryEvidence(
            cycle_id=cycle_id,
            cycle_succeeded=cycle_succeeded,
            terminal_reason=terminal_reason,
            commitment=self.commitment,
            started_at=started_at,
            completed_at=completed_at,
            configured_pairs=len(self.universe.pairs),
            required_pairs=required,
            completed_required_pairs=completed_required,
            requests_attempted=sum(item.requests_attempted for item in pair_results),
            batches_completed=sum(item.batches_completed for item in pair_results),
            snapshots_created=len(snapshots),
            candidates_created=len(opportunities),
            duplicate_snapshots_dropped=duplicate_snapshots,
            duplicate_candidates_dropped=duplicate_candidates,
            candidates_dropped_backpressure=dropped_backpressure,
            provider_failures=provider_failures,
            detector_rejections={
                pair_id: rejection.reason_code
                for pair_id, rejection in self._detector.last_rejections.items()
            },
            degraded_reasons=tuple(sorted(set(degraded))),
        )
        return RuntimeDiscoveryReport(opportunities, snapshot_set, evidence)

    async def _discover_pair(
        self, cycle_id: str, item: RuntimeDiscoveryPair
    ) -> _PairCycleResult:
        pair = item.pair
        failures: dict[str, int] = {}
        degraded: list[str] = []
        first_request = QuoteRequest(
            input_mint=pair.base_mint,
            output_mint=pair.intermediate_mint,
            amount_base_units=pair.probe_amount_base_units,
            user_wallet=str(self.user_wallet),
            slippage_bps=self.universe.slippage_bps,
            input_decimals=item.base_decimals,
            output_decimals=item.intermediate_decimals,
        )
        first_batch = await self.plane.discover(first_request)
        self._count_failures(first_batch, failures)
        first = self._snapshots_from_batch(
            cycle_id=cycle_id,
            pair_id=pair.pair_id,
            leg=1,
            batch=first_batch,
        )
        if not first:
            degraded.append(f"{pair.pair_id}:missing_first_leg")
            return _PairCycleResult(
                pair_id=pair.pair_id,
                required=item.required,
                snapshots=(),
                requests_attempted=1,
                batches_completed=1,
                complete=False,
                provider_failures=failures,
                degraded_reasons=tuple(degraded),
            )

        second_snapshots: list[MarketQuoteSnapshot] = []
        requests_attempted = 1
        batches_completed = 1
        requested_second_amounts: set[int] = set()

        for first_snapshot in first:
            intermediate_amount = first_snapshot.out_amount
            if intermediate_amount <= 0:
                degraded.append(f"{pair.pair_id}:zero_intermediate_amount")
                continue
            if intermediate_amount in requested_second_amounts:
                continue
            requested_second_amounts.add(intermediate_amount)

            second_request = QuoteRequest(
                input_mint=pair.intermediate_mint,
                output_mint=pair.base_mint,
                amount_base_units=intermediate_amount,
                user_wallet=str(self.user_wallet),
                slippage_bps=self.universe.slippage_bps,
                input_decimals=item.intermediate_decimals,
                output_decimals=item.base_decimals,
            )
            second_batch = await self.plane.discover(second_request)
            requests_attempted += 1
            batches_completed += 1
            self._count_failures(second_batch, failures)
            second = self._snapshots_from_batch(
                cycle_id=cycle_id,
                pair_id=pair.pair_id,
                leg=2,
                batch=second_batch,
            )
            if not second:
                degraded.append(
                    f"{pair.pair_id}:missing_second_leg_amount:{intermediate_amount}"
                )
                continue
            second_snapshots.extend(second)

        if not second_snapshots:
            degraded.append(f"{pair.pair_id}:missing_second_leg")
        return _PairCycleResult(
            pair_id=pair.pair_id,
            required=item.required,
            snapshots=(*first, *tuple(second_snapshots)),
            requests_attempted=requests_attempted,
            batches_completed=batches_completed,
            complete=bool(first and second_snapshots),
            provider_failures=failures,
            degraded_reasons=tuple(degraded),
        )

    def _snapshots_from_batch(
        self,
        *,
        cycle_id: str,
        pair_id: str,
        leg: int,
        batch: DiscoveryBatch,
    ) -> tuple[MarketQuoteSnapshot, ...]:
        now = datetime.now(timezone.utc)
        snapshots: list[MarketQuoteSnapshot] = []
        for quote in batch.quotes:
            if quote.context_slot is None or not quote.is_fresh(now):
                continue
            labels = tuple(
                dict.fromkeys(
                    (
                        *quote.correlation_labels,
                        *(
                            quote.provenance.correlation_labels
                            if quote.provenance
                            else ()
                        ),
                        *(
                            f"route:{source.lower()}"
                            for source in quote.route_provenance
                        ),
                        f"cycle:{cycle_id}",
                        f"pair:{pair_id}",
                        f"leg:{leg}",
                        f"request_amount:{quote.input_amount}",
                    )
                )
            )
            snapshots.append(
                MarketQuoteSnapshot(
                    provider=quote.provider,
                    input_mint=quote.input_mint,
                    output_mint=quote.output_mint,
                    in_amount=quote.input_amount,
                    out_amount=quote.expected_output,
                    slot=quote.context_slot,
                    observed_at=quote.received_at.timestamp(),
                    source=(
                        quote.provenance.endpoint
                        if quote.provenance is not None
                        else quote.provider
                    ),
                    quote_id=quote.external_id,
                    confidence="provider-normalized",
                    commitment=self.commitment,
                    expires_at=(
                        quote.expires_at.timestamp()
                        if quote.expires_at is not None
                        else None
                    ),
                    request_fingerprint=batch.request_fingerprint,
                    response_hash=quote.raw_response_hash,
                    correlation_labels=labels,
                    provider_timestamp=(
                        quote.provider_timestamp.timestamp()
                        if quote.provider_timestamp is not None
                        else None
                    ),
                )
            )
        return tuple(snapshots)

    @staticmethod
    def _count_failures(batch: DiscoveryBatch, counts: dict[str, int]) -> None:
        for failure in batch.failures:
            counts[failure.provider] = counts.get(failure.provider, 0) + 1

    @staticmethod
    def _deduplicate_snapshots(
        snapshots: Sequence[MarketQuoteSnapshot],
    ) -> tuple[tuple[MarketQuoteSnapshot, ...], int]:
        unique: list[MarketQuoteSnapshot] = []
        seen: set[tuple[Any, ...]] = set()
        for snapshot in snapshots:
            key = (
                snapshot.request_fingerprint,
                snapshot.provider,
                snapshot.input_mint,
                snapshot.output_mint,
                snapshot.in_amount,
                snapshot.out_amount,
                snapshot.slot,
                snapshot.response_hash,
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(snapshot)
        return tuple(unique), len(snapshots) - len(unique)

    @staticmethod
    def _deduplicate_candidates(
        opportunities: Sequence[Opportunity],
    ) -> tuple[tuple[Opportunity, ...], int]:
        unique: list[Opportunity] = []
        seen: set[str] = set()
        for opportunity in opportunities:
            route = opportunity.metadata.get("route", ())
            fingerprint = json.dumps(
                {
                    "pair": opportunity.metadata.get("detector_pair_id"),
                    "slot": opportunity.detection_slot,
                    "route": route,
                    "amount": opportunity.proposed_amount_base_units,
                    "route_identity": opportunity.metadata.get("route_identity"),
                },
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            unique.append(opportunity)
        return tuple(unique), len(opportunities) - len(unique)

    def _blocked_report(
        self,
        *,
        cycle_id: str,
        started_at: float,
        required_pairs: tuple[str, ...],
        reason: str,
        degraded_reasons: tuple[str, ...] = (),
    ) -> RuntimeDiscoveryReport:
        completed_at = float(self._clock())
        evidence = RuntimeDiscoveryEvidence(
            cycle_id=cycle_id,
            cycle_succeeded=False,
            terminal_reason=reason,
            commitment=self.commitment,
            started_at=started_at,
            completed_at=completed_at,
            configured_pairs=len(self.universe.pairs),
            required_pairs=required_pairs,
            completed_required_pairs=(),
            requests_attempted=0,
            batches_completed=0,
            snapshots_created=0,
            candidates_created=0,
            degraded_reasons=degraded_reasons,
        )
        return RuntimeDiscoveryReport((), SnapshotSet(), evidence)
