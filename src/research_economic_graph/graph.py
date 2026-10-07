"""Research graph above QPR-03, retaining its raw and negative evidence owners."""

from __future__ import annotations

from dataclasses import asdict, replace
from types import MappingProxyType

from src.qualification_campaign.identity import digest
from src.qualification_campaign.sources import Candidate
from .models import (
    EvidenceState,
    ExecutionClass,
    Heat,
    ResearchEvidence,
    ResearchRelation,
)
from .registry import AssetRegistry, CampaignSeed


def retained_records(evidence):
    # Validate journal and blob hashes before any normalization or exact use.
    bodies = evidence.replay()
    events = evidence.journal.events(available_at_ns=2**63 - 1)
    return {event.identity: body for event, body in zip(events, bodies, strict=True)}


def require_generation(evidence, registry, seed=None):
    configuration = dict(evidence.manifest.configuration_digests)
    if configuration.get("gpr.registry") != registry.generation:
        raise ValueError("GPR_REGISTRY_GENERATION_MISMATCH")
    if seed is not None and configuration.get("gpr.seed") != seed.generation:
        raise ValueError("GPR_SEED_GENERATION_MISMATCH")


class ResearchEconomicGraph:
    def __init__(self, registry: AssetRegistry, seed: CampaignSeed):
        self.registry = registry
        self.seed = seed
        self._relations: dict[str, ResearchRelation] = {}
        self._observations: dict[str, ResearchEvidence] = {}
        self._evidence_refs: set[str] = set()
        self._rejections: set[tuple[str, str, str]] = set()
        for relation in seed.relations:
            self.add(relation)
        for transformation in seed.transformations:
            transport_relation = transformation.relation()
            if transport_relation is not None:
                self.add(transport_relation)

    @property
    def relations(self):
        return MappingProxyType(self._relations)

    def add(self, relation: ResearchRelation):
        for ref in (
            *relation.representations,
            *(r for p in relation.synthetic_paths for r in p.representations),
        ):
            asset = self.registry.resolve(ref)
            if ref != asset.asset_id:
                raise ValueError("relations require resolved representation references")
            if (
                relation.evidence_state != EvidenceState.DISCOVERY_ONLY
                and not asset.identifier_verified
            ):
                raise ValueError("unresolved/revalidation identity cannot promote")
        # Exact evidence is owned by QPR-02 and the existing graph, never this API.
        if relation.evidence_state in (
            EvidenceState.RPC_VERIFIED,
            EvidenceState.EXECUTABLE,
        ):
            raise ValueError("research relation cannot self-promote exact evidence")
        previous = self._relations.get(relation.relation_id)
        if previous is None:
            self._relations[relation.relation_id] = relation
            return

        def core(value):
            raw = value.to_dict()
            for key in (
                "evidence",
                "provenance_refs",
                "direct_venues",
                "observed_at_ns",
            ):
                raw.pop(key)
            return raw

        if core(previous) != core(relation):
            raise ValueError("relation identity/classification conflict")
        times = [
            v
            for v in (previous.observed_at_ns, relation.observed_at_ns)
            if v is not None
        ]
        self._relations[relation.relation_id] = replace(
            previous,
            evidence=previous.evidence + relation.evidence,
            provenance_refs=previous.provenance_refs + relation.provenance_refs,
            direct_venues=previous.direct_venues + relation.direct_venues,
            observed_at_ns=max(times) if times else None,
        )

    def snapshot(self) -> dict:
        return {
            "schema_version": "gpr.research-economic-graph.v1",
            "registry_generation": self.registry.generation,
            "seed_generation": self.seed.generation,
            "representations": [
                asdict(a) for _, a in sorted(self.registry.assets.items())
            ],
            "relations": [r.to_dict() for _, r in sorted(self._relations.items())],
            "deepbook_pools": [asdict(p) for p in self.seed.pools],
            "transport_transformations": [asdict(t) for t in self.seed.transformations],
            "observations": [asdict(v) for _, v in sorted(self._observations.items())],
            "raw_evidence_refs": sorted(self._evidence_refs),
            "rejections": sorted(self._rejections),
        }

    @property
    def identity(self):
        return digest(self.snapshot())

    def persist(self, evidence, *, observed_at_ns: int):
        require_generation(evidence, self.registry, self.seed)
        return evidence.append(
            "gpr-graph",
            {
                "kind": "gpr_graph_snapshot",
                "snapshot": self.snapshot(),
                "snapshot_hash": self.identity,
            },
            observed_at_ns=observed_at_ns,
        )

    @classmethod
    def replay(cls, evidence, registry, seed):
        require_generation(evidence, registry, seed)
        records = retained_records(evidence)
        snapshots = [
            b for b in records.values() if b.get("kind") == "gpr_graph_snapshot"
        ]
        if not snapshots:
            raise ValueError("no retained research graph")
        body = snapshots[-1]
        raw = body["snapshot"]
        if (
            digest(raw) != body["snapshot_hash"]
            or raw["registry_generation"] != registry.generation
            or raw["seed_generation"] != seed.generation
        ):
            raise ValueError("GPR_GRAPH_GENERATION_OR_HASH_MISMATCH")
        graph = cls(registry, seed)
        graph._relations.clear()
        for row in raw["relations"]:
            graph.add(ResearchRelation.from_dict(row))
        graph._observations = {
            o["raw_evidence_id"]: ResearchEvidence(**o) for o in raw["observations"]
        }
        graph._evidence_refs = set(raw["raw_evidence_refs"])
        graph._rejections = {tuple(r) for r in raw["rejections"]}
        if (
            graph._evidence_refs - set(records)
            or graph.identity != body["snapshot_hash"]
        ):
            raise ValueError("GPR_GRAPH_REPLAY_MISMATCH")
        return graph


class SolanaResearchAdapter:
    """Normalize retained QPR-03 Candidates without widening their Solana domain."""

    def __init__(self, graph: ResearchEconomicGraph):
        self.graph = graph

    def ingest(self, evidence):
        require_generation(evidence, self.graph.registry, self.graph.seed)
        records = retained_records(evidence)
        generations = dict(evidence.manifest.source_generations)
        observations = {}
        for ref, body in records.items():
            if body.get("kind") in (
                "attempt",
                "rpc_observation",
                "capture_failure",
                "cancelled_capture",
            ):
                self.graph._evidence_refs.add(ref)
            if body.get("kind") != "source_observation":
                continue
            if (
                generations.get(body["source_id"]) != body["source_generation"]
                or generations.get(body["provider_id"]) != body["provider_generation"]
            ):
                raise ValueError("QPR_SOURCE_GENERATION_MISMATCH")
            if (
                body.get("raw_payload_hash") is not None
                and digest(body["raw_payload"]) != body["raw_payload_hash"]
            ):
                raise ValueError("QPR_RETAINED_PAYLOAD_HASH_MISMATCH")
            observed = ResearchEvidence(
                raw_evidence_id=ref,
                source_id=body["source_id"],
                source_generation=body["source_generation"],
                provider_id=body["provider_id"],
                provider_generation=body["provider_generation"],
                provider=body["provider"],
                operator=body["operator"],
                correlation_group=body["correlation_group"],
                request_hash=body["request_fingerprint"],
                response_hash=body.get("response_hash"),
                retained_payload_hash=body.get("raw_payload_hash"),
                observed_at_ns=body["observed_at_ns"],
                available_at_ns=body["available_at_ns"],
                quality=body["quality_state"],
                source_time=body.get("source_provided_time"),
                slot=body.get("slot"),
            )
            observations[ref] = observed
            self.graph._observations[ref] = observed
            self.graph._evidence_refs.add(ref)
        for body in records.values():
            if body.get("kind") != "discovery_candidate":
                continue
            candidate = Candidate(**body["candidate"])
            provenance = body["provenance"]
            raw_ref = provenance["raw_evidence_id"]
            observation = observations.get(raw_ref)
            if (
                body["candidate_id"] != candidate.identity
                or body["classification"] != "DISCOVERY_ONLY"
                or observation is None
            ):
                raise ValueError("QPR_CANDIDATE_PROVENANCE_MISMATCH")
            expected = {
                "source_id": observation.source_id,
                "source_generation": observation.source_generation,
                "raw_evidence_id": raw_ref,
                "request_fingerprint": observation.request_hash,
                "response_hash": observation.response_hash,
            }
            if provenance != expected or observation.quality not in (
                "accepted",
                "accepted-with-rejections",
            ):
                raise ValueError("QPR_CANDIDATE_PROVENANCE_MISMATCH")
            try:
                assets = tuple(
                    self.graph.registry.by_identifier(candidate.chain, mint)
                    for mint in candidate.mints
                )
            except ValueError:
                self.graph._rejections.add(
                    (candidate.identity, raw_ref, "unregistered-representation")
                )
                continue
            refs = tuple(a.asset_id for a in assets)
            matching = [
                r
                for r in self.graph.seed.relations
                if set(refs) <= set(r.representations)
            ]
            priorities = {Heat.HOT: 0, Heat.EVENT: 1, Heat.WARM: 2, Heat.COLD: 3}
            heat = min(
                (r.heat for r in matching),
                key=lambda h: priorities[h],
                default=Heat.COLD,
            )
            self.graph.add(
                ResearchRelation(
                    relation_id="qpr03:" + candidate.identity,
                    relation_class="SWAP_CANDIDATE",
                    representations=refs,
                    heat=heat,
                    execution_class=ExecutionClass.LOCAL_ATOMIC,
                    evidence_state=EvidenceState.DISCOVERY_ONLY,
                    direct_venues=(candidate.venue_label,),
                    known_pool_or_book_ids=(candidate.market_id,),
                    provenance_refs=(raw_ref,),
                    evidence=(observation,),
                    observed_at_ns=observation.observed_at_ns,
                    quality="indexed-discovery-only",
                )
            )
        return self.graph
