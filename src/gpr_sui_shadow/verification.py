"""Independent Sui checkpoint/object HARD_BOUND receipts; no atomic graph path."""

import base64
import hashlib
import inspect
from dataclasses import asdict, dataclass
from datetime import datetime

from src.qualification_campaign.identity import digest
from src.research_economic_graph import HardBoundIdentityReceipt, ExecutionClass
from src.research_economic_graph.graph import retained_records, require_generation
from src.research_economic_graph.queue import VerificationTarget
from .intake import validate_capture
from .models import SuiCandidate, coin_type, object_id, sha, uint
from .sources import OBJECT_QUERY
from .bcs import metadata_decimals, move_tag


def decoder_fingerprint(decoder):
    """Pin inspected decoder implementation instead of accepting its own label."""
    try:
        code = inspect.getsource(type(decoder))
    except (OSError, TypeError):
        raise ValueError("SUI_INSPECTABLE_REVIEWED_DECODER_REQUIRED") from None
    return digest(
        {
            "module": type(decoder).__module__,
            "class": type(decoder).__qualname__,
            "source_sha256": hashlib.sha256(code.encode()).hexdigest(),
        }
    )


@dataclass(frozen=True)
class RepresentationProof:
    asset_id: str
    representation_digest: str
    issuer: str | None
    origin_chain: str | None
    bridge: str | None
    sources: tuple[str, ...]

    def __post_init__(self):
        sha(self.representation_digest)
        if (
            not self.asset_id
            or not self.sources
            or any("#sha256=" not in s for s in self.sources)
        ):
            raise ValueError("SUI_HASHED_REPRESENTATION_SOURCES_REQUIRED")

    def require(self, asset):
        if self.asset_id != asset.asset_id or self.representation_digest != digest(
            asset.representation
        ):
            raise ValueError("SUI_REPRESENTATION_PROOF_MISMATCH")
        for name in ("issuer", "origin_chain", "bridge"):
            expected = getattr(asset, name)
            if expected is not None and getattr(self, name) != expected:
                raise ValueError("SUI_ISSUER_ORIGIN_BRIDGE_MISMATCH")
        if any(
            s in asset.representation_kind for s in ("wormhole", "bridge", "wrapped")
        ) and (not self.origin_chain or not self.bridge):
            raise ValueError("SUI_MATERIAL_BRIDGE_ORIGIN_PROOF_REQUIRED")
        if asset.economic_asset not in ("SUI", "DEEP") and not self.issuer:
            raise ValueError("SUI_MATERIAL_ISSUER_PROOF_REQUIRED")


@dataclass(frozen=True)
class SuiVerificationPolicy:
    chain_identifier: str
    identity_policy_generation: str
    decoder_code_sha256: str
    representation_proofs: tuple[RepresentationProof, ...]
    venue_move_types: tuple[tuple[str, str], ...]
    max_age_ns: int = 45_000_000_000
    minimum_independent_providers: int = 2

    def __post_init__(self):
        if not self.chain_identifier:
            raise ValueError("SUI_REVIEWED_GENESIS_ID_REQUIRED")
        sha(self.identity_policy_generation)
        sha(self.decoder_code_sha256)
        uint(self.max_age_ns, "max_age", 1, 45_000_000_000)
        uint(self.minimum_independent_providers, "quorum", 2, 3)
        if len({p.asset_id for p in self.representation_proofs}) != len(
            self.representation_proofs
        ):
            raise ValueError("SUI_UNIQUE_REPRESENTATION_PROOFS_REQUIRED")
        if not self.venue_move_types or len(set(self.venue_move_types)) != len(
            self.venue_move_types
        ):
            raise ValueError("SUI_REVIEWED_VENUE_MOVE_TYPE_REQUIRED")

    @property
    def generation(self):
        return digest(asdict(self))


@dataclass(frozen=True)
class DecodedPoolState:
    pool_id: str
    object_version: int
    checkpoint: int
    move_type: str
    coin_types: tuple[str, str]
    decimals: tuple[int, int]
    bid_depth_units: int
    ask_depth_units: int
    taker_fee_numerator: int
    fee_denominator: int
    lot_size: int
    tick_size: int
    fee_semantics: str
    state_bcs_sha256: str
    depth_bcs_sha256: str
    fee_bcs_sha256: str
    metadata_bcs_sha256: tuple[str, str]

    def __post_init__(self):
        object.__setattr__(self, "pool_id", object_id(self.pool_id))
        types = tuple(coin_type(t) for t in self.coin_types)
        if len(types) != 2 or len(set(types)) != 2 or len(self.decimals) != 2:
            raise ValueError("SUI_DECODED_POOL_TYPES_REQUIRED")
        object.__setattr__(self, "coin_types", types)
        if not self.move_type or not self.fee_semantics:
            raise ValueError("SUI_MOVE_TYPE_FEE_SEMANTICS_REQUIRED")
        for d in self.decimals:
            uint(d, "decimals", 0, 255)
        for name in (
            "object_version",
            "checkpoint",
            "bid_depth_units",
            "ask_depth_units",
            "fee_denominator",
            "lot_size",
            "tick_size",
        ):
            uint(getattr(self, name), name, 1, 2**256 - 1)
        uint(self.taker_fee_numerator, "taker_fee", 0, self.fee_denominator - 1)
        for name in ("state_bcs_sha256", "depth_bcs_sha256", "fee_bcs_sha256"):
            sha(getattr(self, name))
        if len(self.metadata_bcs_sha256) != 2:
            raise ValueError("SUI_METADATA_BCS_HASHES_REQUIRED")
        for value in self.metadata_bcs_sha256:
            sha(value)


def scoped_object(capture, *, now_ns, started_at_ns, policy, candidate):
    if (
        capture["quality"] != "accepted-read-only"
        or not capture["physical_attempt_started"]
        or capture.get("http_status") != 200
        or capture["profile"]["smoke_only"]
    ):
        raise ValueError("SUI_NONSMOKE_GOVERNED_OBJECT_CAPTURE_REQUIRED")
    if not started_at_ns <= capture["observed_at_ns"] <= capture[
        "available_at_ns"
    ] <= now_ns or (now_ns - capture["observed_at_ns"] > policy.max_age_ns):
        raise ValueError("SUI_STARTUP_STALE_OR_FUTURE_CAPTURE")
    request = capture["request"]
    if (
        request["purpose"] != "checkpoint-object"
        or request["body"]["query"] != OBJECT_QUERY
    ):
        raise ValueError("SUI_CHECKPOINT_SCOPED_OBJECT_QUERY_REQUIRED")
    variables = request["body"]["variables"]
    if (
        variables["pool"] != candidate.pool_id
        or (variables["a"], variables["b"]) != candidate.coin_types
    ):
        raise ValueError("SUI_EXACT_POOL_REPRESENTATION_REQUEST_MISMATCH")
    payload = capture["raw_payload"]
    if (
        payload.get("errors")
        or payload["data"]["chainIdentifier"] != policy.chain_identifier
    ):
        raise ValueError("SUI_NETWORK_OR_GRAPHQL_ERROR")
    checkpoint = payload["data"]["checkpoint"]
    if (
        checkpoint["sequenceNumber"] != variables["checkpoint"]
        or not checkpoint["digest"]
    ):
        raise ValueError("SUI_CHECKPOINT_SCOPE_MISMATCH")
    uint(checkpoint["sequenceNumber"], "checkpoint")
    timestamp = datetime.fromisoformat(checkpoint["timestamp"].replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("SUI_CHECKPOINT_TIMESTAMP_REQUIRED")
    timestamp_ns = int(timestamp.timestamp() * 10**9)
    if not 0 <= now_ns - timestamp_ns <= policy.max_age_ns:
        raise ValueError("SUI_CHECKPOINT_STALE_OR_FUTURE")
    obj = checkpoint["query"]["object"]
    if object_id(obj["address"]) != candidate.pool_id or not obj["digest"]:
        raise ValueError("SUI_EXACT_OBJECT_ID_DIGEST_REQUIRED")
    uint(obj["version"], "object_version", 1)
    contents = obj["asMoveObject"]["contents"]
    bcs = base64.b64decode(contents["bcs"], validate=True)
    if not bcs or not contents["type"]["repr"]:
        raise ValueError("SUI_MOVE_OBJECT_BCS_REQUIRED")
    for alias, t in zip(("a", "b"), candidate.coin_types, strict=True):
        metadata = checkpoint["query"][alias]
        uint(metadata["decimals"], "coin_decimals", 0, 255)
        uint(metadata["version"], "metadata_version", 1)
        object_id(metadata["address"])
        if not metadata["digest"] or not metadata["contents"]["bcs"]:
            raise ValueError("SUI_COIN_METADATA_OBJECT_PROOF_REQUIRED")
        tag = metadata["contents"]["type"]["repr"]
        decoded_decimals = metadata_decimals(
            base64.b64decode(metadata["contents"]["bcs"], validate=True),
            address=metadata["address"],
            tag=tag,
            expected_coin_type=t,
        )
        if decoded_decimals != metadata["decimals"]:
            raise ValueError("SUI_ACTUAL_COIN_METADATA_BCS_DECIMALS_MISMATCH")
    return checkpoint, obj, bcs


class SuiHardBoundGate:
    """Reconstruct receipts from independent retained object bytes every time."""

    def __init__(
        self,
        graph,
        evidence,
        identity_policy,
        policy,
        decoder,
        *,
        started_at_ns,
        wall_ns,
    ):
        require_generation(evidence, graph.registry, graph.seed)
        pins = dict(evidence.manifest.configuration_digests)
        if (
            pins.get("gpr.identity_policy") != identity_policy.generation
            or pins.get("gpr03.sui_verification") != policy.generation
            or policy.identity_policy_generation != identity_policy.generation
        ):
            raise ValueError("SUI_IDENTITY_OR_VERIFICATION_POLICY_GENERATION_MISMATCH")
        if (
            decoder is None
            or decoder_fingerprint(decoder) != policy.decoder_code_sha256
        ):
            raise ValueError("SUI_REVIEWED_DEPTH_FEE_DECODER_REQUIRED")
        uint(started_at_ns, "startup", 1, 2**63 - 1)
        self.graph, self.evidence, self.identity_policy, self.policy, self.decoder = (
            graph,
            evidence,
            identity_policy,
            policy,
            decoder,
        )
        self.started_at_ns, self.wall_ns = started_at_ns, wall_ns

    def _state(self, candidate, capture_refs):
        if (
            len(capture_refs) != len(set(capture_refs))
            or not self.policy.minimum_independent_providers <= len(capture_refs) <= 3
        ):
            raise ValueError("SUI_INDEPENDENT_QUORUM_REQUIRED")
        captures = [validate_capture(self.evidence, ref) for ref in capture_refs]
        for field in ("profile_id", "provider", "operator", "correlation_group"):
            if len({r["profile"][field] for r in captures}) != len(captures):
                raise ValueError("SUI_CORRELATED_PROVIDERS_BLOCKED")
        checked = [
            scoped_object(
                r,
                now_ns=self.wall_ns(),
                started_at_ns=self.started_at_ns,
                policy=self.policy,
                candidate=candidate,
            )
            for r in captures
        ]
        # Agree on checkpoint/digest and complete object+metadata bytes, not just prices.
        if len({digest(cp) for cp, _, _ in checked}) != 1:
            raise ValueError("SUI_CHECKPOINT_OBJECT_METADATA_DISAGREEMENT")
        cp, obj, bcs = checked[0]
        actual_type = move_tag(obj["asMoveObject"]["contents"]["type"]["repr"])
        if (candidate.venue, actual_type) not in {
            (v, move_tag(t)) for v, t in self.policy.venue_move_types
        }:
            raise ValueError("SUI_REVIEWED_VENUE_MOVE_TYPE_MISMATCH")
        decoded = self.decoder.decode(cp, obj, bcs)
        if not isinstance(decoded, DecodedPoolState):
            raise ValueError("SUI_TYPED_DECODER_STATE_REQUIRED")
        bcs_hash = hashlib.sha256(bcs).hexdigest()
        # This version supports inline verified state only. Dynamic-field book
        # proofs require a separately pinned decoder/query before they can qualify.
        if (
            decoded.pool_id != candidate.pool_id
            or decoded.object_version != obj["version"]
            or decoded.checkpoint != cp["sequenceNumber"]
            or decoded.move_type != obj["asMoveObject"]["contents"]["type"]["repr"]
            or set(decoded.coin_types) != set(candidate.coin_types)
            or any(
                h != bcs_hash
                for h in (
                    decoded.state_bcs_sha256,
                    decoded.depth_bcs_sha256,
                    decoded.fee_bcs_sha256,
                )
            )
        ):
            raise ValueError("SUI_OBJECT_TYPE_VERSION_DEPTH_FEE_PROOF_MISMATCH")
        for alias, t in zip(("a", "b"), candidate.coin_types, strict=True):
            if (
                cp["query"][alias]["decimals"]
                != decoded.decimals[decoded.coin_types.index(t)]
            ):
                raise ValueError("SUI_POOL_COIN_METADATA_DECIMALS_MISMATCH")
            metadata_hash = hashlib.sha256(
                base64.b64decode(cp["query"][alias]["contents"]["bcs"], validate=True)
            ).hexdigest()
            if (
                decoded.metadata_bcs_sha256[decoded.coin_types.index(t)]
                != metadata_hash
            ):
                raise ValueError("SUI_DECODED_METADATA_BCS_PROOF_MISMATCH")
        return decoded

    def _receipts(self, candidate, capture_refs, verification_id, checked_at_ns):
        state = self._state(candidate, capture_refs)
        result = []
        for t, decimals in zip(state.coin_types, state.decimals, strict=True):
            asset = self.graph.registry.by_identifier("sui-mainnet", t)
            expectation = self.identity_policy.require(asset)
            proof = next(
                (
                    p
                    for p in self.policy.representation_proofs
                    if p.asset_id == asset.asset_id
                ),
                None,
            )
            if proof is None:
                raise ValueError("SUI_FULL_REPRESENTATION_RECEIPT_REQUIRED")
            proof.require(asset)
            if decimals != expectation.decimals or expectation.extensions:
                raise ValueError("SUI_MOVE_DECIMALS_OR_STANDARD_MISMATCH")
            result.append(
                HardBoundIdentityReceipt(
                    asset.asset_id,
                    asset.chain,
                    asset.canonical_identifier,
                    asset.token_program_or_move_type,
                    decimals,
                    asset.standard,
                    (),
                    asset.representation_kind,
                    proof.origin_chain,
                    proof.bridge,
                    proof.issuer,
                    tuple(
                        sorted(set(expectation.representation_sources + proof.sources))
                    ),
                    expectation.deprecation_state,
                    checked_at_ns,
                    None,
                    state.checkpoint,
                    state.move_type,
                    state.pool_id,
                    digest(asdict(state)),
                    verification_id,
                    tuple(capture_refs),
                    self.evidence.manifest.campaign_id,
                    self.evidence.manifest.repository_sha,
                    self.graph.registry.generation,
                    self.identity_policy.generation,
                )
            )
        return state, tuple(sorted(result, key=lambda r: r.asset_id))

    def _request(self, request, candidate):
        relation = self.graph.relations[request.relation_id]
        if (
            request.target != VerificationTarget.SUI_GOVERNED_CHECKPOINT_OBJECT
            or request.chain != "sui-mainnet"
            or request.campaign_id != self.evidence.manifest.campaign_id
            or request.repository_sha != self.evidence.manifest.repository_sha
            or request.registry_generation != self.graph.registry.generation
            or request.graph_identity != self.graph.identity
            or request.representations != relation.representations
            or request.execution_class != relation.execution_class
            or request.pool_or_book_ids != relation.known_pool_or_book_ids
            or relation.execution_class
            in (ExecutionClass.CROSS_CHAIN_SIGNAL, ExecutionClass.REBALANCE_ONLY)
        ):
            raise ValueError("SUI_REQUEST_DOMAIN_GENERATION_OR_TRANSPORT_MISMATCH")
        if candidate.pool_id not in {
            object_id(p) for p in request.pool_or_book_ids
        } or set(
            self.graph.registry.by_identifier("sui-mainnet", t).asset_id
            for t in candidate.coin_types
        ) != set(
            request.representations
        ):
            raise ValueError("SUI_REQUEST_POOL_REPRESENTATION_MISMATCH")

    def qualify(self, request, candidate, capture_refs):
        self._request(request, candidate)
        checked_at = self.wall_ns()
        state = self._state(candidate, capture_refs)
        verification = {
            "kind": "gpr03_sui_object_verification",
            "request_id": request.identity,
            "candidate": asdict(candidate),
            "capture_refs": list(capture_refs),
            "state": asdict(state),
            "state_hash": digest(asdict(state)),
            "policy_generation": self.policy.generation,
            "classification": "RPC_VERIFIED",
            "shadow_only": True,
            "exact_graph_allowed": False,
        }
        # Validate complete identity set before emitting a successful verification.
        self._receipts(candidate, capture_refs, "pending", checked_at)
        ref = self.evidence.append(
            "gpr03-verification", verification, observed_at_ns=checked_at
        )
        _, receipts = self._receipts(candidate, capture_refs, ref, checked_at)
        receipt_refs = tuple(
            self.evidence.append(
                "gpr03-identity",
                {
                    "kind": "gpr03_sui_identity_receipt",
                    "receipt": r.to_dict(),
                    "receipt_hash": digest(r.to_dict()),
                    "sui_verification_policy_generation": self.policy.generation,
                },
                observed_at_ns=checked_at,
            )
            for r in receipts
        )
        return ref, receipt_refs

    def require_receipts(self, request, candidate, verification_ref, receipt_refs):
        self._request(request, candidate)
        records = retained_records(self.evidence)
        record = records.get(verification_ref)
        if (
            not record
            or record.get("kind") != "gpr03_sui_object_verification"
            or record["request_id"] != request.identity
        ):
            raise ValueError("SUI_RETAINED_VERIFICATION_REQUIRED")
        if (
            record["policy_generation"] != self.policy.generation
            or digest(record["state"]) != record["state_hash"]
            or SuiCandidate(**record["candidate"]) != candidate
            or record.get("shadow_only") is not True
            or record.get("exact_graph_allowed") is not False
            or len(receipt_refs) != 2
            or len(set(receipt_refs)) != 2
        ):
            raise ValueError("SUI_COMPLETE_CURRENT_RECEIPTS_REQUIRED")
        actual = []
        for ref in receipt_refs:
            raw = records.get(ref)
            if not raw or raw.get("kind") != "gpr03_sui_identity_receipt":
                raise ValueError("SUI_HARD_BOUND_RECEIPT_REQUIRED")
            receipt = raw["receipt"]
            if (
                not self.started_at_ns <= receipt["checked_at_ns"] <= self.wall_ns()
                or self.wall_ns() - receipt["checked_at_ns"] > self.policy.max_age_ns
            ):
                raise ValueError("SUI_RECEIPT_STALE_OR_FUTURE")
            state, expected = self._receipts(
                candidate,
                record["capture_refs"],
                verification_ref,
                receipt["checked_at_ns"],
            )
            matching = next(
                (r for r in expected if r.asset_id == receipt["asset_id"]), None
            )
            if (
                matching is None
                or digest(receipt) != raw["receipt_hash"]
                or digest(matching.to_dict()) != raw["receipt_hash"]
                or raw["sui_verification_policy_generation"] != self.policy.generation
            ):
                raise ValueError("SUI_RECEIPT_RECONSTRUCTION_MISMATCH")
            actual.append(receipt["asset_id"])
        if (
            set(actual) != set(request.representations)
            or digest(asdict(state)) != record["state_hash"]
        ):
            raise ValueError("SUI_RECEIPT_ASSET_SET_OR_STATE_MISMATCH")
        return state
