"""Actual funnel delegation into the published QPR-02/GPR-01 exact owners."""

from dataclasses import asdict

from src.qualification_campaign.identity import digest
from src.research_economic_graph import (
    ExecutionClass,
    VerificationQueue,
    VerificationTarget,
    ingest_solana_exact,
)
from src.research_economic_graph.graph import retained_records
from .funnel import compare_quotes, normalize_jupiter
from .probes import normalize_zero_x
from src.qualification_campaign.sources import SourceReadRequest


def retained_quote(
    evidence,
    quote_ref,
    contract,
    *,
    input_mint,
    output_mint,
    input_amount,
    campaign_started_at_ns,
    now_ns,
):
    records = retained_records(evidence)
    row = records.get(quote_ref)
    if (
        row is None
        or row.get("kind") != "gpr02_quote_preview"
        or digest(row["quote"]) != row["quote_hash"]
    ):
        raise ValueError("RETAINED_QUOTE_RECEIPT_REQUIRED")
    raw = records.get(row["quote"]["raw_evidence_ref"])
    generations = dict(evidence.manifest.source_generations)
    if (
        raw is None
        or raw.get("kind") != "gpr02_reference_read"
        or raw["source_id"] != contract.source_id
        or raw["source_generation"] != contract.generation
        or generations.get(contract.source_id) != contract.generation
        or raw["provider_id"] != contract.profile.profile_id
        or raw["provider_generation"] != contract.profile.generation
        or generations.get(contract.profile.profile_id) != contract.profile.generation
        or raw["correlation_group"] != contract.profile.correlation_group
        or raw.get("http_status") != 200
        or raw["quality_state"] != "accepted"
        or digest(raw["raw_payload"]) != raw["raw_payload_hash"]
        or not campaign_started_at_ns <= raw["observed_at_ns"] <= now_ns
        or now_ns - raw["observed_at_ns"] > 45_000_000_000
    ):
        raise ValueError("QUOTE_PROVENANCE_GENERATION_OR_FRESHNESS_MISMATCH")
    request = SourceReadRequest(
        raw["request"]["url"],
        tuple(tuple(p) for p in raw["request"]["params"]),
        tuple(tuple(p) for p in raw["request"]["semantic_headers"]),
    )
    if (
        request.url != contract.profile.endpoint
        or tuple(request.semantic_headers) != tuple(contract.semantic_headers)
        or digest(
            {
                "request": asdict(request),
                "method": contract.method,
                "body": raw["request_body"],
            }
        )
        != raw["request_fingerprint"]
    ):
        raise ValueError("QUOTE_REQUEST_CONTRACT_MISMATCH")
    if contract.source_id == "gpr02-0x-preview":
        quote = normalize_zero_x(
            raw["raw_payload"],
            body=raw["request_body"],
            observed_at_ns=raw["observed_at_ns"],
            contract=contract,
            raw_evidence_ref=row["quote"]["raw_evidence_ref"],
        )
    else:
        quote = normalize_jupiter(
            raw["raw_payload"],
            request=request,
            observed_at_ns=raw["observed_at_ns"],
            source_id=contract.source_id,
            provider_generation=contract.profile.generation,
            correlation_group=contract.profile.correlation_group,
            raw_evidence_ref=row["quote"]["raw_evidence_ref"],
        )
    if digest(asdict(quote)) != row["quote_hash"] or (
        quote.input_mint,
        quote.output_mint,
        quote.input_amount,
    ) != (input_mint, output_mint, input_amount):
        raise ValueError("QUOTE_PAIR_AMOUNT_OR_RECONSTRUCTION_MISMATCH")
    return quote


async def qualify_exact_request(
    request,
    graph,
    gate,
    provider,
    ingest,
    *,
    queue_ref,
    zero_x_contract,
    jupiter_contract,
    zero_x_quote_ref,
    jupiter_reference_ref,
    jupiter_final_ref,
    binding_id,
    input_asset_id,
    input_amount,
    cursor_offset,
):
    """Reconstruct quotes, collect QPR-02 quorum, obtain real startup receipts.

    All failures are retained. The existing exact owner alone computes the final
    integer pool quote. A HOT relation or an unsigned router response grants no
    execution authority. Token-2022 remains blocked by the native decoder.
    """
    evidence, now = gate.evidence, gate.wall_ns()
    try:
        valid_requests = VerificationQueue(graph, evidence).replay(queue_ref)
        if not any(r.identity == request.identity for r in valid_requests):
            raise ValueError("CURRENT_RETAINED_VERIFICATION_REQUEST_REQUIRED")
        if (
            request.target != VerificationTarget.SOLANA_QPR02_DIRECT_STATE
            or request.execution_class != ExecutionClass.LOCAL_ATOMIC
            or len(request.representations) != 2
            or input_asset_id not in request.representations
        ):
            raise ValueError("NON_ATOMIC_OR_NONPAIR_EXACT_REQUEST")
        input_asset = graph.registry.resolve(input_asset_id)
        output_asset = graph.registry.resolve(
            next(a for a in request.representations if a != input_asset_id)
        )
        kwargs = {
            "input_mint": input_asset.canonical_identifier,
            "output_mint": output_asset.canonical_identifier,
            "input_amount": input_amount,
            "campaign_started_at_ns": gate.started_at_ns,
            "now_ns": now,
        }
        zx = retained_quote(evidence, zero_x_quote_ref, zero_x_contract, **kwargs)
        reference = retained_quote(
            evidence, jupiter_reference_ref, jupiter_contract, **kwargs
        )
        final = retained_quote(evidence, jupiter_final_ref, jupiter_contract, **kwargs)
        if reference.raw_evidence_ref == final.raw_evidence_ref:
            raise ValueError("INDEPENDENT_FRESH_JUPITER_FINAL_READ_REQUIRED")
        compare_quotes(zx, final, now_ns=now)
        if any(a.standard == "Token-2022" for a in (input_asset, output_asset)):
            raise ValueError("TOKEN_2022_QPR02_EXACT_POOL_DECODER_UNSUPPORTED")
        binding = ingest.bindings[binding_id]
        pool_id = binding.venue.market_id
        if pool_id not in request.pool_or_book_ids:
            raise ValueError("EXACT_BINDING_REQUEST_POOL_MISMATCH")
        if provider.evidence.manifest.campaign_id != evidence.manifest.campaign_id:
            raise ValueError("RPC_PROVIDER_CAMPAIGN_MISMATCH")
        await provider.collect((pool_id,))
        bundles = [
            (ref, b)
            for ref, b in retained_records(evidence).items()
            if b.get("kind") == "rooted_snapshot_bundle"
        ]
        if not bundles:
            raise ValueError("RETAINED_QPR02_QUORUM_REQUIRED")
        verification_id = bundles[-1][0]
        relation = graph.relations[request.relation_id]
        receipts = gate.startup_receipts(
            relation, verification_id=verification_id, pool_id=pool_id
        )
        observation = ingest_solana_exact(
            request,
            graph,
            gate,
            ingest,
            binding_id=binding_id,
            verification_id=verification_id,
            receipt_refs=receipts,
            input_asset_id=input_asset_id,
            input_amount=input_amount,
            cursor_offset=cursor_offset,
        )
        owner_decisions = [
            b
            for b in retained_records(evidence).values()
            if b.get("kind") == "gpr_exact_shadow_observation"
            and b.get("request_id") == request.identity
            and b.get("observation_id") == observation.observation_id
        ]
        if not owner_decisions or owner_decisions[-1].get("accepted") is not True:
            raise ValueError("EXISTING_SHADOW_INGEST_REJECTED")
        evidence.append(
            "gpr02-qualification",
            {
                "kind": "gpr02_exact_shadow_handoff",
                "request_id": request.identity,
                "quote_refs": [
                    zero_x_quote_ref,
                    jupiter_reference_ref,
                    jupiter_final_ref,
                ],
                "receipt_refs": receipts,
                "verification_id": verification_id,
                "observation_id": observation.observation_id,
                "live_authorization": False,
                "production_promotion": False,
            },
            observed_at_ns=gate.wall_ns(),
        )
        return observation
    except (ValueError, KeyError, RuntimeError) as exc:
        evidence.append(
            "gpr02-qualification",
            {
                "kind": "gpr02_exact_qualification_rejected",
                "request_id": request.identity,
                "reason": (
                    str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                ),
                "live_authorization": False,
            },
            observed_at_ns=gate.wall_ns(),
        )
        raise
