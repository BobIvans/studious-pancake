"""Deterministic bounded verification work. Scores are scheduling units, not PnL."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum

from src.qualification_campaign.identity import digest
from .graph import retained_records, require_generation
from .models import ExecutionClass, Heat, integer

POSITIVE_INPUTS = (
    "inter_source_divergence",
    "structural_anchor_deviation",
    "route_topology_change",
    "liquidity_change",
    "volume_acceleration",
    "orderbook_amm_gap",
    "oracle_market_gap",
    "representation_basis",
    "cross_chain_basis",
    "historical_recurrence",
    "size_convexity",
)
PENALTY_INPUTS = (
    "source_correlation_penalty",
    "staleness_penalty",
    "unresolved_identity_penalty",
    "rebalance_latency_penalty",
)


@dataclass(frozen=True)
class CandidateScore:
    inputs: tuple[tuple[str, int], ...] = ()

    def __post_init__(self):
        values = dict(self.inputs)
        if len(values) != len(self.inputs) or set(values) - set(
            POSITIVE_INPUTS + PENALTY_INPUTS
        ):
            raise ValueError("unknown or duplicate scheduling score input")
        for value in values.values():
            integer(value, "scheduling score")
            if value > 1_000_000:
                raise ValueError("score input outside bounded scheduling units")
        object.__setattr__(
            self,
            "inputs",
            tuple(
                (k, values.get(k, 0)) for k in sorted(POSITIVE_INPUTS + PENALTY_INPUTS)
            ),
        )

    @property
    def decomposition(self):
        return tuple((k, -v if k in PENALTY_INPUTS else v) for k, v in self.inputs)

    @property
    def total(self):
        return sum(v for _, v in self.decomposition)


class VerificationTarget(StrEnum):
    SOLANA_QPR02_DIRECT_STATE = "SOLANA_QPR02_DIRECT_STATE"
    SUI_GOVERNED_CHECKPOINT_OBJECT = "SUI_GOVERNED_CHECKPOINT_OBJECT"
    CROSS_CHAIN_RESEARCH = "CROSS_CHAIN_RESEARCH"
    REBALANCE_RESEARCH = "REBALANCE_RESEARCH"


@dataclass(frozen=True)
class VerificationRequest:
    relation_id: str
    chain: str
    representations: tuple[str, ...]
    target: VerificationTarget
    heat: Heat
    execution_class: ExecutionClass
    score: CandidateScore
    campaign_id: str
    repository_sha: str
    registry_generation: str
    graph_identity: str
    pool_or_book_ids: tuple[str, ...]
    provenance_refs: tuple[str, ...]

    @property
    def identity(self):
        return digest(asdict(self))


class VerificationQueue:
    def __init__(self, graph, evidence):
        require_generation(evidence, graph.registry, graph.seed)
        self.graph, self.evidence = graph, evidence

    def build(
        self,
        scores: dict[str, CandidateScore],
        *,
        top_k: int = 14,
        per_chain_budget: dict[str, int] | None = None,
        now_ns: int,
    ):
        integer(top_k, "top-K", 1)
        integer(now_ns, "queue time", 1)
        if top_k > 256 or set(scores) - set(self.graph.relations):
            raise ValueError("bounded known relation work required")
        budgets = dict(
            per_chain_budget
            if per_chain_budget is not None
            else {"solana-mainnet": top_k, "sui-mainnet": top_k}
        )
        for chain, budget in budgets.items():
            if chain not in ("solana-mainnet", "sui-mainnet"):
                raise ValueError("GPR-01 queues only Solana/Sui")
            integer(budget, "chain budget")
            if budget > 256:
                raise ValueError("chain budget exceeds cap")
        priority = {Heat.HOT: 0, Heat.EVENT: 1, Heat.WARM: 2, Heat.COLD: 3}
        ranked = []
        for relation in self.graph.relations.values():
            base = scores.get(relation.relation_id, CandidateScore())
            if not isinstance(base, CandidateScore):
                raise ValueError("typed scheduling score required")
            values = dict(base.inputs)
            if any(
                not self.graph.registry.resolve(ref).identifier_verified
                for ref in relation.representations
            ):
                values["unresolved_identity_penalty"] = max(
                    values["unresolved_identity_penalty"], 1
                )
            if relation.observed_at_ns is not None:
                if relation.observed_at_ns > now_ns:
                    raise ValueError("future research observation")
                if now_ns - relation.observed_at_ns > relation.staleness_ttl_ns:
                    values["staleness_penalty"] = max(values["staleness_penalty"], 1)
            groups = [e.correlation_group for e in relation.evidence]
            values["source_correlation_penalty"] = max(
                values["source_correlation_penalty"], len(groups) - len(set(groups))
            )
            score = CandidateScore(tuple(values.items()))
            ranked.append(
                (
                    -score.total,
                    priority[relation.heat],
                    relation.relation_id,
                    relation,
                    score,
                )
            )
        requests: list[VerificationRequest] = []
        for _, _, _, relation, score in sorted(ranked, key=lambda r: r[:3]):
            for chain in sorted(
                {
                    self.graph.registry.resolve(ref).chain
                    for ref in relation.representations
                }
            ):
                if len(requests) == top_k:
                    return tuple(requests)
                if budgets.get(chain, 0) == 0:
                    continue
                if relation.execution_class == ExecutionClass.CROSS_CHAIN_SIGNAL:
                    target = VerificationTarget.CROSS_CHAIN_RESEARCH
                elif relation.execution_class == ExecutionClass.REBALANCE_ONLY:
                    target = VerificationTarget.REBALANCE_RESEARCH
                else:
                    target = (
                        VerificationTarget.SOLANA_QPR02_DIRECT_STATE
                        if chain == "solana-mainnet"
                        else VerificationTarget.SUI_GOVERNED_CHECKPOINT_OBJECT
                    )
                requests.append(
                    VerificationRequest(
                        relation.relation_id,
                        chain,
                        tuple(
                            r
                            for r in relation.representations
                            if self.graph.registry.resolve(r).chain == chain
                        ),
                        target,
                        relation.heat,
                        relation.execution_class,
                        score,
                        self.evidence.manifest.campaign_id,
                        self.evidence.manifest.repository_sha,
                        self.graph.registry.generation,
                        self.graph.identity,
                        relation.known_pool_or_book_ids,
                        relation.provenance_refs,
                    )
                )
                budgets[chain] -= 1
        return tuple(requests)

    def persist(self, scores, *, top_k=14, per_chain_budget=None, now_ns):
        requests = self.build(
            scores, top_k=top_k, per_chain_budget=per_chain_budget, now_ns=now_ns
        )
        record = {
            "schema_version": "gpr.verification-queue.v1",
            "graph_identity": self.graph.identity,
            "scores": {key: asdict(value) for key, value in sorted(scores.items())},
            "top_k": top_k,
            "per_chain_budget": per_chain_budget,
            "now_ns": now_ns,
            "requests": [asdict(r) for r in requests],
        }
        return self.evidence.append(
            "gpr-queue",
            {
                "kind": "gpr_verification_queue",
                "queue": record,
                "queue_hash": digest(record),
            },
            observed_at_ns=now_ns,
        )

    def replay(self, queue_ref):
        record = retained_records(self.evidence).get(queue_ref)
        if record is None or record.get("kind") != "gpr_verification_queue":
            raise ValueError("retained verification queue required")
        raw = record["queue"]
        if (
            digest(raw) != record["queue_hash"]
            or raw["graph_identity"] != self.graph.identity
        ):
            raise ValueError("QUEUE_GRAPH_OR_HASH_MISMATCH")
        scores = {
            key: CandidateScore(tuple(tuple(p) for p in value["inputs"]))
            for key, value in raw["scores"].items()
        }
        requests = self.build(
            scores,
            top_k=raw["top_k"],
            per_chain_budget=raw["per_chain_budget"],
            now_ns=raw["now_ns"],
        )
        if digest([asdict(r) for r in requests]) != digest(raw["requests"]):
            raise ValueError("QUEUE_REPLAY_MISMATCH")
        return requests
