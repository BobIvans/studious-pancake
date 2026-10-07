"""Startup HARD_BOUND receipts over QPR-02; existing exact owners do the math.

Only the already governed SPL/native CPMM decoder is supported here. Token-2022
and Sui checkpoint qualification remain explicit GPR-02/GPR-03 work, not flags.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace

from src.qualification_campaign.identity import digest
from src.qualification_campaign.rpc import validate_quorum_evidence
from .graph import retained_records, require_generation
from .models import ExecutionClass, integer
from .queue import VerificationTarget


@dataclass(frozen=True)
class IdentityExpectation:
    asset_id: str
    representation_digest: str
    decimals: int
    representation_sources: tuple[str, ...]
    extensions: tuple[str, ...] = ()
    deprecation_state: str = "CURRENT"

    def __post_init__(self):
        integer(self.decimals, "expected decimals")
        if (
            self.decimals > 255
            or not self.asset_id
            or len(self.representation_digest) != 64
            or not self.representation_sources
        ):
            raise ValueError(
                "reviewed representation and decimals expectation required"
            )
        object.__setattr__(
            self,
            "representation_sources",
            tuple(sorted(set(self.representation_sources))),
        )
        object.__setattr__(self, "extensions", tuple(sorted(set(self.extensions))))


@dataclass(frozen=True)
class StartupIdentityPolicy:
    expectations: tuple[IdentityExpectation, ...]
    max_age_ns: int = 45_000_000_000

    def __post_init__(self):
        rows = tuple(sorted(self.expectations, key=lambda r: r.asset_id))
        if not rows or len(rows) > 1024 or len({r.asset_id for r in rows}) != len(rows):
            raise ValueError("bounded unique identity expectations required")
        integer(self.max_age_ns, "identity freshness", 1)
        if self.max_age_ns > 45_000_000_000:
            raise ValueError("identity freshness cannot exceed QPR-02 bound")
        object.__setattr__(self, "expectations", rows)

    @property
    def generation(self):
        return digest(asdict(self))

    def require(self, asset):
        if not asset.identifier_verified:
            raise ValueError("IDENTITY_REVALIDATION_REQUIRED")
        expectation = next(
            (r for r in self.expectations if r.asset_id == asset.asset_id), None
        )
        if expectation is None or expectation.representation_digest != digest(
            asset.representation
        ):
            raise ValueError("REVIEWED_REPRESENTATION_RECEIPT_REQUIRED")
        if expectation.deprecation_state != "CURRENT":
            raise ValueError("DEPRECATED_OR_REPLACED_IDENTITY")
        if asset.decimals is not None and asset.decimals != expectation.decimals:
            raise ValueError("REGISTRY_DECIMALS_MISMATCH")
        return expectation


@dataclass(frozen=True)
class HardBoundIdentityReceipt:
    asset_id: str
    chain: str
    canonical_identifier: str
    token_program_or_move_type: str
    decimals: int
    standard: str
    extensions: tuple[str, ...]
    representation_kind: str
    origin_chain: str | None
    bridge: str | None
    issuer: str | None
    representation_sources: tuple[str, ...]
    deprecation_state: str
    checked_at_ns: int
    slot: int | None
    checkpoint: int | None
    venue_program: str
    pool_or_book_id: str
    state_hash: str
    verification_evidence_id: str
    capture_refs: tuple[str, ...]
    campaign_id: str
    repository_sha: str
    registry_generation: str
    identity_policy_generation: str
    evidence_state: str = "RPC_VERIFIED"
    schema_version: str = "gpr.hard-bound-identity-receipt.v1"

    def to_dict(self):
        return asdict(self)


class HardBoundIdentityGate:
    def __init__(
        self,
        registry,
        evidence,
        policy: StartupIdentityPolicy,
        *,
        campaign_started_at_ns: int,
        wall_ns,
    ):
        require_generation(evidence, registry)
        integer(campaign_started_at_ns, "campaign startup", 1)
        if (
            dict(evidence.manifest.configuration_digests).get("gpr.identity_policy")
            != policy.generation
        ):
            raise ValueError("IDENTITY_POLICY_GENERATION_MISMATCH")
        self.registry, self.evidence, self.policy = registry, evidence, policy
        self.started_at_ns, self.wall_ns = campaign_started_at_ns, wall_ns

    def verified_state(self, verification_id, pool_id):
        from src.providers.raydium_cpmm_native import decode_native_capture
        from src.data_plane.rpc import RootedRpcQuorumPolicy

        require_generation(self.evidence, self.registry)
        if (
            dict(self.evidence.manifest.configuration_digests).get(
                "gpr.identity_policy"
            )
            != self.policy.generation
        ):
            raise ValueError("IDENTITY_POLICY_GENERATION_MISMATCH")
        records = retained_records(self.evidence)
        body = records.get(verification_id)
        if body is None or body.get("kind") != "rooted_snapshot_bundle":
            raise ValueError("RETAINED_QPR02_DIRECT_STATE_REQUIRED")
        required_policy = RootedRpcQuorumPolicy(
            max_observation_age_ms=45_000, max_root_lag_slots=128
        )
        if digest(body["quorum_policy"]) != digest(asdict(required_policy)):
            raise ValueError("QPR02_QUORUM_POLICY_MISMATCH")
        result = validate_quorum_evidence(body, self.evidence)
        if not result["accepted"]:
            raise ValueError("QPR02_QUORUM_BLOCKED:" + result["reason"])
        now = self.wall_ns()
        integer(now, "identity verification time", self.started_at_ns)
        states = []
        events = {
            e.identity: e
            for e in self.evidence.journal.events(available_at_ns=2**63 - 1)
        }
        source_generations = dict(self.evidence.manifest.source_generations)
        for capture_ref, sample in zip(
            body["capture_refs"], body["rooted_samples"], strict=True
        ):
            capture = records[capture_ref]["payload"]
            endpoint_id = sample["sample"]["endpoint_id"]
            if events[capture_ref].source != endpoint_id or source_generations.get(
                endpoint_id
            ) != capture.get("rpc_profile_generation"):
                raise ValueError("QPR02_CAPTURE_PROFILE_GENERATION_MISMATCH")
            observed = capture["observed_at_ns"]
            if (
                capture["evidence_kind"] != "captured-rpc"
                or not self.started_at_ns <= observed <= now
                or capture["available_at_ns"] > now
                or now - observed > self.policy.max_age_ns
            ):
                raise ValueError("STARTUP_CHAIN_STATE_STALE_OR_SYNTHETIC")
            decoded = decode_native_capture(capture)
            state = next(
                (s for s in decoded.pools if s.venue.market_id == pool_id), None
            )
            if state is None:
                raise ValueError("EXACT_POOL_IDENTITY_MISMATCH")
            states.append(state)

        # Provider generations differ by design; compare the decoded market
        # state while the existing quorum owner checks independent raw bytes.
        def market_state(state):
            raw = asdict(state)
            raw.pop("generation")
            return digest(raw)

        if not states or len({market_state(s) for s in states}) != 1:
            raise ValueError("EXACT_POOL_STATE_DISAGREEMENT")
        canonical = result["canonical_endpoint_id"]
        index = next(
            i
            for i, s in enumerate(body["rooted_samples"])
            if s["sample"]["endpoint_id"] == canonical
        )
        return states[index], body

    def _receipt(self, asset, state, bundle, verification_id, *, checked_at_ns):
        expectation = self.policy.require(asset)
        if asset.chain != "solana-mainnet":
            raise ValueError("GOVERNED_SUI_CHECKPOINT_PATH_REQUIRED")
        if asset.standard != "SPL" or expectation.extensions:
            raise ValueError("TOKEN_STANDARD_OR_EXTENSION_SEMANTICS_UNQUALIFIED")
        native = next(
            (
                a
                for a in (state.asset_a, state.asset_b)
                if a.mint == asset.canonical_identifier
            ),
            None,
        )
        if (
            native is None
            or native.token_program != asset.token_program_or_move_type
            or native.decimals != expectation.decimals
        ):
            raise ValueError("CHAIN_IDENTITY_PROGRAM_OR_DECIMALS_MISMATCH")
        return HardBoundIdentityReceipt(
            asset.asset_id,
            asset.chain,
            native.mint,
            native.token_program,
            native.decimals,
            asset.standard,
            (),
            asset.representation_kind,
            asset.origin_chain,
            asset.bridge,
            asset.issuer,
            expectation.representation_sources,
            expectation.deprecation_state,
            checked_at_ns,
            state.slot,
            None,
            state.venue.program_id,
            state.venue.market_id,
            state.identity,
            verification_id,
            tuple(bundle["capture_refs"]),
            self.evidence.manifest.campaign_id,
            self.evidence.manifest.repository_sha,
            self.registry.generation,
            self.policy.generation,
        )

    def startup_receipts(self, relation, *, verification_id: str, pool_id: str):
        self.require_local_atomic(relation)
        if (
            pool_id not in relation.known_pool_or_book_ids
            or len(relation.representations) != 2
        ):
            raise ValueError("EXACT_TWO_REPRESENTATION_POOL_REQUIRED")
        state, bundle = self.verified_state(verification_id, pool_id)
        checked_at = self.wall_ns()
        # Validate the entire set before persisting any successful receipt.
        receipts = tuple(
            self._receipt(
                self.registry.resolve(ref),
                state,
                bundle,
                verification_id,
                checked_at_ns=checked_at,
            )
            for ref in relation.representations
        )
        if {r.canonical_identifier for r in receipts} != {
            state.asset_a.mint,
            state.asset_b.mint,
        }:
            raise ValueError("POOL_REPRESENTATION_SET_MISMATCH")
        return tuple(
            self.evidence.append(
                "gpr-identity",
                {
                    "kind": "gpr_identity_receipt",
                    "receipt": r.to_dict(),
                    "receipt_hash": digest(r.to_dict()),
                },
                observed_at_ns=checked_at,
            )
            for r in receipts
        )

    def require_local_atomic(self, relation):
        if relation.execution_class != ExecutionClass.LOCAL_ATOMIC or any(
            self.registry.resolve(ref).chain != "solana-mainnet"
            for ref in relation.representations
        ):
            raise ValueError("NON_ATOMIC_OR_UNSUPPORTED_EXACT_RELATION")

    def require_receipts(self, relation, receipt_refs, *, verification_id, pool_id):
        self.require_local_atomic(relation)
        if len(receipt_refs) != len(relation.representations) or len(
            set(receipt_refs)
        ) != len(receipt_refs):
            raise ValueError("HARD_BOUND_RECEIPTS_REQUIRED")
        state, bundle = self.verified_state(verification_id, pool_id)
        records = retained_records(self.evidence)
        actual = {}
        for receipt_ref in receipt_refs:
            record = records.get(receipt_ref)
            if record is None or record.get("kind") != "gpr_identity_receipt":
                raise ValueError("HARD_BOUND_RECEIPTS_REQUIRED")
            raw = record["receipt"]
            if (
                record["receipt_hash"] != digest(raw)
                or not self.started_at_ns <= raw["checked_at_ns"] <= self.wall_ns()
            ):
                raise ValueError("IDENTITY_RECEIPT_HASH_OR_STARTUP_MISMATCH")
            asset = self.registry.resolve(raw["asset_id"])
            expected = self._receipt(
                asset,
                state,
                bundle,
                verification_id,
                checked_at_ns=raw["checked_at_ns"],
            )
            if (
                digest(expected.to_dict()) != record["receipt_hash"]
                or asset.asset_id in actual
            ):
                raise ValueError("IDENTITY_RECEIPT_GENERATION_OR_STATE_MISMATCH")
            actual[asset.asset_id] = expected
        if set(actual) != set(relation.representations):
            raise ValueError("IDENTITY_RECEIPT_REPRESENTATION_MISMATCH")
        return state


def ingest_solana_exact(
    request,
    graph,
    gate: HardBoundIdentityGate,
    ingest,
    *,
    binding_id: str,
    verification_id: str,
    receipt_refs: tuple[str, ...],
    input_asset_id: str,
    input_amount: int,
    cursor_offset: int,
):
    """VerificationRequest -> replayed QPR-02 -> existing exact observation/graph.

    No caller-supplied quote, Sui binding, bridge edge, synthetic success or
    alternate graph/math implementation is accepted by this boundary.
    """
    from src.market.observations import SourceCursor
    from src.strategy.exact_cpmm_capacity import QualifiedRaydiumCpmmAdapter

    require_generation(gate.evidence, graph.registry, graph.seed)
    relation = graph.relations[request.relation_id]
    gate.require_local_atomic(relation)
    if (
        request.target != VerificationTarget.SOLANA_QPR02_DIRECT_STATE
        or request.chain != "solana-mainnet"
        or request.execution_class != relation.execution_class
        or request.campaign_id != gate.evidence.manifest.campaign_id
        or request.repository_sha != gate.evidence.manifest.repository_sha
        or request.registry_generation != graph.registry.generation
        or gate.registry.generation != graph.registry.generation
        or request.graph_identity != graph.identity
        or request.representations != relation.representations
        or request.pool_or_book_ids != relation.known_pool_or_book_ids
    ):
        raise ValueError("VERIFICATION_REQUEST_GENERATION_OR_TARGET_MISMATCH")
    binding = ingest.bindings[binding_id]
    pool_id = binding.venue.market_id
    if (
        pool_id not in relation.known_pool_or_book_ids
        or input_asset_id not in relation.representations
    ):
        raise ValueError("EXACT_BINDING_IDENTITY_MISMATCH")
    state = gate.require_receipts(
        relation, receipt_refs, verification_id=verification_id, pool_id=pool_id
    )
    if binding.venue != state.venue or set(binding.mints) != {
        state.asset_a.mint,
        state.asset_b.mint,
    }:
        raise ValueError("EXACT_BINDING_IDENTITY_MISMATCH")
    integer(cursor_offset, "exact cursor")
    identifier = graph.registry.resolve(input_asset_id).canonical_identifier
    native_input = next(
        a for a in (state.asset_a, state.asset_b) if a.mint == identifier
    )
    evaluation = QualifiedRaydiumCpmmAdapter().evaluate(
        state, input_asset=native_input, requested_input=input_amount
    )
    observation = replace(
        evaluation.to_observation(),
        provider=binding.source_id,
        source="qpr02-rooted-direct-state",
        commitment="finalized",
        cursor=SourceCursor(
            binding.cursor_source,
            binding_id,
            cursor_offset,
            state.slot,
            ingest.reconnect_epoch,
        ),
        generation=replace(
            state.generation,
            asset_generation=digest(
                {
                    "native": state.generation.asset_generation,
                    "receipts": sorted(receipt_refs),
                    "registry": gate.registry.generation,
                }
            ),
            policy_generation=digest(
                {
                    "native": state.generation.policy_generation,
                    "identity_policy": gate.policy.generation,
                }
            ),
            code_generation=state.generation.code_generation
            + ":repo="
            + gate.evidence.manifest.repository_sha,
        ),
    )
    # Existing ingest/graph owns admission. Discovery never becomes a quote.
    accepted = ingest.ingest(binding_id, observation)
    gate.evidence.append(
        "gpr-verification",
        {
            "kind": "gpr_exact_shadow_observation",
            "request_id": request.identity,
            "verification_evidence_id": verification_id,
            "identity_receipt_refs": sorted(receipt_refs),
            "observation_id": observation.observation_id,
            "accepted": accepted,
            "runtime_enabled": False,
            "live_authorization": False,
        },
        observed_at_ns=gate.wall_ns(),
    )
    return observation
