"""GPR-05: evidence progression and existing-owner handoff, QPR fail-closed."""

from dataclasses import asdict, dataclass
from enum import StrEnum
import importlib
import time
from typing import Callable

from src.asset_mint_registry_pr117 import TOKEN_2022_PROGRAM_ID
from src.assets.resolution.evidence import Evidence, EvidenceStore, digest
from src.assets.resolution.resolver import AssetIdentity
from src.discovery.dynamic_universe.universe import MarketIdentity
from src.economics.non_monotonic_sizing import PR118TypedCostLedger
from src.market.observations import MarketObservationV2
from src.strategy.market_graph_ingest import ShadowMarketGraphIngest
from src.strategy.arbitrage_graph import CircularShadowRoute


class PromotionStage(StrEnum):
    DISCOVERY_ONLY = "DISCOVERY_ONLY"
    IDENTIFIER_VERIFIED = "IDENTIFIER_VERIFIED"
    MARKET_VERIFIED = "MARKET_VERIFIED"
    RPC_EXACT = "RPC_EXACT"
    PAPER_QUALIFIED = "PAPER_QUALIFIED"


@dataclass(frozen=True)
class QPRReadiness:
    campaign: str
    generation: str
    verdict: str
    handoff_ref: str


class ExistingQPRReadiness:
    """Delegate to qualification_campaign.cli.report, never create QPR PASS.

    The QPR branches are not merged into this checkout. Once available, this
    bridge retains their replay-derived handoff without changing its verdict.
    QPR-03's stop_before=QPR-04 continues to deny later graph promotion.
    """

    def __init__(self, qpr_evidence, store: EvidenceStore):
        self.qpr_evidence, self.store = qpr_evidence, store

    def __call__(self) -> QPRReadiness | None:
        try:
            owner = importlib.import_module("src.qualification_campaign.cli")
        except ModuleNotFoundError:
            return None
        payload = owner.report(self.qpr_evidence)
        generation = self.qpr_evidence.manifest.campaign_id
        if (
            payload["campaign_id"] != generation
            or payload["journal_head"] != self.qpr_evidence.head
        ):
            return None
        now = time.time()
        ref = self.store.append(
            Evidence(
                "existing-qpr-handoff",
                "qualification-campaign",
                "qpr-authority",
                generation,
                now,
                digest(payload),
                digest(self.qpr_evidence.head),
            ),
            payload,
        )
        readiness = payload["campaign_readiness"]
        return QPRReadiness(readiness["target"], generation, readiness["status"], ref)


@dataclass(frozen=True)
class MarketProof:
    market: MarketIdentity
    evidence: Evidence
    base_identifier: str
    quote_identifier: str
    decoded_state_hash: str


@dataclass(frozen=True)
class PromotionReceipt:
    market_id: str
    generation: str
    stage: PromotionStage
    reasons: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    observation_id: str | None
    paper_net: int | None
    durable_ref: str


class PromotionBoundary:
    def __init__(
        self,
        generation: str,
        store: EvidenceStore,
        *,
        readiness_evaluator: Callable[[], QPRReadiness | None] | None = None,
    ):
        self.generation, self.store, self.readiness_evaluator = (
            generation,
            store,
            readiness_evaluator,
        )

    def readiness(self) -> bool:
        # This checkout has no QPR readiness owner/artifact. A future integration
        # must delegate to that owner; neither a flag nor this campaign sets PASS.
        if self.readiness_evaluator is None:
            return False
        receipt = self.readiness_evaluator()
        valid = (
            isinstance(receipt, QPRReadiness)
            and receipt.campaign == "READ_ONLY_REAL_DATA_CAMPAIGN_V1"
            and receipt.generation == self.generation
            and receipt.verdict == "PASS"
            and bool(receipt.handoff_ref)
        )
        if not valid or receipt is None:
            return False
        try:
            record = self.store.replay(receipt.handoff_ref)
            payload = record["payload"]
            manifest = payload["manifest"]
            readiness = payload["campaign_readiness"]
            safety = manifest["safety"]
            return (
                payload["schema_version"] == "prequal.campaign-handoff.v1"
                and payload["campaign_id"] == self.generation
                and record["evidence"]["generation"] == self.generation
                and readiness["target"] == receipt.campaign
                and readiness["status"] == "PASS"
                and manifest["mode"] == "CAPTURE_ONLY"
                and payload["qualification_verdict"] == "PASS"
                and payload.get("stop_before") is None
                and safety
                == {
                    "signer_reachable": False,
                    "sender_reachable": False,
                    "transaction_submission_allowed": False,
                    "live_authorization": False,
                }
            )
        except (OSError, KeyError, ValueError, TypeError):
            return False

    def evaluate(
        self,
        market: MarketIdentity,
        assets: tuple[AssetIdentity, ...],
        proofs: tuple[MarketProof, ...],
        observation: MarketObservationV2 | None,
        *,
        now: float,
        max_age: float = 5,
    ) -> PromotionReceipt:
        stage = PromotionStage.DISCOVERY_ONLY
        reasons = []
        refs: set[str] = set()
        net = None
        ids = {
            (a.chain, a.canonical_identifier): a
            for a in assets
            if a.resolver_generation == self.generation
        }
        pair = (
            ids.get((market.chain, market.base)),
            ids.get((market.chain, market.quote)),
        )
        if any(a is None for a in pair):
            reasons.append("missing_canonical_identity")
        else:
            stage = PromotionStage.IDENTIFIER_VERIFIED
            refs.update(ref for a in pair if a is not None for ref in a.evidence_refs)
        if market.chain == "ton":
            reasons.append("ton_async_research_only")
        if any(
            a is not None and a.program_or_package == TOKEN_2022_PROGRAM_ID
            for a in pair
        ):
            reasons.append("existing_token2022_execution_gate_closed")
        current = tuple(
            p
            for p in proofs
            if p.market == market
            and p.evidence.fresh(now=now, max_age=max_age, generation=self.generation)
        )
        if not current or any(
            (p.base_identifier, p.quote_identifier) != (market.base, market.quote)
            or not p.decoded_state_hash
            or p.evidence.slot_or_checkpoint is None
            for p in current
        ):
            reasons.append("missing_or_mismatched_market_proof")
        elif not reasons:
            stage = PromotionStage.MARKET_VERIFIED
            refs.update(digest(asdict(p.evidence)) for p in current)
        if len({p.evidence.correlation_group for p in current}) < 2:
            reasons.append("missing_independent_exact_verifiers")
        if (
            len(
                {(p.decoded_state_hash, p.evidence.slot_or_checkpoint) for p in current}
            )
            != 1
        ):
            reasons.append("exact_state_provider_disagreement")
        if not self.readiness():
            reasons.append("QPR_READ_ONLY_REAL_DATA_CAMPAIGN_V1_NOT_PASS")
        if not isinstance(observation, MarketObservationV2):
            reasons.append("missing_canonical_exact_observation")
        else:
            quote = observation
            positions = {p.evidence.slot_or_checkpoint for p in current}
            if (
                market.chain != "solana"
                or (quote.input_mint, quote.output_mint) != (market.base, market.quote)
                or positions != {quote.slot}
                or quote.observed_at > now
                or not quote.is_fresh(now=now, max_age_seconds=max_age)
                or quote.commitment not in ("confirmed", "finalized")
                or not quote.response_hash
                or not quote.request_fingerprint
                or quote.generation.asset_generation != self.generation
                or quote.generation.policy_generation != self.generation
                or "unknown"
                in (
                    quote.generation.code_generation,
                    quote.generation.provider_generation,
                    quote.generation.genesis_hash,
                )
            ):
                reasons.append("quote_identity_state_or_freshness_mismatch")
        # All evidence must be replayable from retained provider envelopes.
        for ref in sorted(refs):
            try:
                self.store.evidence_record(ref)
            except (OSError, ValueError, KeyError):
                reasons.append("missing_durable_provider_evidence")
                break
        if not reasons:
            stage = PromotionStage.RPC_EXACT
        payload = {
            "market_id": market.identity,
            "generation": self.generation,
            "stage": stage,
            "reasons": sorted(set(reasons)),
            "evidence_refs": sorted(refs),
            "observation_id": (
                observation.observation_id if observation is not None else None
            ),
            "observation_hash": (
                digest(asdict(observation)) if observation is not None else None
            ),
            "paper_net": net,
        }
        ref = self.store.append(
            Evidence(
                "promotion-receipt",
                "promotion-boundary",
                "promotion",
                self.generation,
                now,
                digest(payload),
                digest(market.identity),
            ),
            payload,
        )
        return PromotionReceipt(
            market.identity,
            self.generation,
            stage,
            tuple(sorted(set(reasons))),
            tuple(sorted(refs)),
            observation.observation_id if observation is not None else None,
            net,
            ref,
        )

    def qualify_route(
        self,
        route: CircularShadowRoute,
        receipts: tuple[PromotionReceipt, ...],
        ledger: PR118TypedCostLedger,
        *,
        capital_ref: str,
        now: float,
    ) -> str:
        """Paper economics applies to a closed amount-coupled route, not A/B price."""
        if not isinstance(route, CircularShadowRoute) or not self.readiness():
            raise ValueError("closed canonical route and QPR PASS required")
        by_observation = {r.observation_id: r for r in receipts}
        for edge in route.edges:
            receipt = by_observation.get(edge.observation.observation_id)
            if receipt is None:
                raise ValueError("missing exact edge receipt")
            record = self.store.replay(receipt.durable_ref)["payload"]
            if (
                record["stage"] != PromotionStage.RPC_EXACT
                or record["generation"] != self.generation
                or record["reasons"]
                or record["observation_hash"] != digest(asdict(edge.observation))
                or edge.observation.observed_at > now
                or not edge.observation.is_fresh(now=now, max_age_seconds=5)
            ):
                raise ValueError("route edge not currently RPC exact")
        capital_record = self.store.replay(capital_ref)
        capital = capital_record["payload"]
        e = Evidence(**capital["evidence"])
        first, last = route.edges[0].observation, route.edges[-1].observation
        principal = first.input_amount
        fee = (
            principal * capital["fee_numerator"] + capital["fee_denominator"] - 1
        ) // capital["fee_denominator"]
        ledger_asset = "ASSET:" + capital["asset_id"][:58].upper()
        resources = {edge.venue.market_id for edge in route.edges}
        if (
            not e.fresh(now=now, max_age=30, generation=self.generation)
            or capital["chain"] != "solana"
            or capital["canonical_identifier"] != first.input_mint
            or principal > capital["max_amount_live"]
            or not set(capital["constraints"]) <= resources
            or ledger.min_out.asset_id != ledger_asset
            or ledger.min_out.amount != last.guaranteed_output
            or ledger.flash_repayment.principal_amount != principal
            or ledger.flash_repayment.flash_fee_amount != fee
            or ledger.flash_repayment.protocol_rounding_amount
            != capital["protocol_rounding"]
            or ledger.route_provenance_hash != digest(capital)
            or ledger.conservative_net_amount() <= 0
        ):
            raise ValueError(
                "capital, route amounts or exact economics do not reconcile"
            )
        payload = {
            "route": route.identity,
            "stage": PromotionStage.PAPER_QUALIFIED,
            "generation": self.generation,
            "edge_receipts": [r.durable_ref for r in receipts],
            "capital_ref": capital_ref,
            "ledger": ledger.to_json(),
            "net": ledger.conservative_net_amount(),
            "executable": False,
        }
        return self.store.append(
            Evidence(
                "paper-route",
                "promotion-boundary",
                "promotion",
                self.generation,
                now,
                digest(payload),
                digest(route.identity),
            ),
            payload,
        )

    def handoff(
        self,
        receipt: PromotionReceipt,
        *,
        ingest: ShadowMarketGraphIngest,
        binding_id: str,
        observation: MarketObservationV2,
        now: float,
    ) -> bool:
        stored = self.store.replay(receipt.durable_ref)["payload"]
        if (
            stored["stage"] != PromotionStage.RPC_EXACT
            or stored["generation"] != self.generation
            or stored["reasons"]
            or stored["observation_id"] != observation.observation_id
            or stored["observation_hash"] != digest(asdict(observation))
            or receipt.observation_id != observation.observation_id
            or observation.observed_at > now
            or not observation.is_fresh(now=now, max_age_seconds=5)
            or not self.readiness()
        ):
            raise ValueError("promotion/QPR gate closed")
        # Preserve the existing binding/cursor/chain/fanout/graph owner checks.
        return ingest.ingest(binding_id, observation)
